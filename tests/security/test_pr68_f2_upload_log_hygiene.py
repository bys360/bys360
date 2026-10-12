"""F2 fault injection: synthetic uploads only, without a database or live services."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from flask import Flask, get_flashed_messages
from werkzeug.datastructures import FileStorage

from app.institutional import hr_personnel_operations_routes as hr
from app.main_handlers import account_handlers as account
from app.portal import routes as portal
from app.services import message_service, profile_photo_service as profile
from app.support import routes as support

# The secrets are assembled at runtime so that no traceback source line in this
# file can contain them; only data that really flowed through a handler can.
ORIGINAL = "-".join(("sensitive", "original"))
STORAGE_KEY = "-".join(("secret", "storage", "key"))
STORE_DIR = "-".join(("private", "secret", "store"))
STORED_PREFIX = "_".join(("user", "123", ""))


@pytest.fixture(autouse=True)
def _logging_enabled():
    """These tests assert on log text, so they must not depend on a process-wide
    ``logging.disable()`` left on by an earlier test (the authorization-matrix
    script disables logging when it builds its app)."""
    previous = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    yield
    logging.disable(previous)


@pytest.fixture
def app(tmp_path):
    app = Flask("f2", static_folder=str(tmp_path / "static"))
    app.secret_key = "synthetic-f2-test-only"
    app.config.update(PRIVATE_UPLOAD_FOLDER=str(tmp_path / STORE_DIR),
                      MAX_CONTENT_LENGTH=1024 * 1024)
    return app


def upload(kind):
    if kind == "portal-image":
        return FileStorage(stream=io.BytesIO(b"\x89PNG\r\n\x1a\nimage"), filename=f"{ORIGINAL}.png",
                           content_type="image/png")
    if kind == "portal-video":
        return FileStorage(stream=io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), filename=f"{ORIGINAL}.mp4",
                           content_type="video/mp4")
    return FileStorage(stream=io.BytesIO(b"%PDF-1.4\n%%EOF\n"),
                       filename=f"{ORIGINAL}.png" if kind == "profile" else f"{ORIGINAL}.pdf")


def write(kind, file):
    if kind == "profile":
        return profile.save_profile_photo(file, SimpleNamespace(id=123, profile_photo_path=None))
    if kind == "support":
        return support._store_ticket_attachment(cast(Any, SimpleNamespace(id=123)), file)
    if kind == "message":
        return message_service.save_message_attachment(file, SimpleNamespace(id=123), 123)
    if kind == "portal-image":
        return portal._save_portal_images(cast(Any, SimpleNamespace(id=123)), [file])
    if kind == "portal-video":
        return portal._save_portal_video_file(cast(Any, SimpleNamespace(id=123)), [file])
    return hr._save_file(file)


def assert_clean(caplog, app, code):
    text = caplog.text.replace("\\\\", "\\")
    assert code in text
    for secret in (app.config["PRIVATE_UPLOAD_FOLDER"], STORE_DIR, ORIGINAL, STORED_PREFIX, STORAGE_KEY):
        assert secret not in text


@pytest.mark.parametrize("kind", ["profile", "support", "hr", "message", "portal-image", "portal-video"])
@pytest.mark.parametrize("failure", ["save", "chained", "mkdir"])
def test_upload_io_failures_are_safe_for_outer_exception_logs(app, monkeypatch, caplog, kind, failure):
    monkeypatch.setattr(portal, "current_user", SimpleNamespace(id=123))
    def denied(target):
        try:
            raise PermissionError(13, STORAGE_KEY, str(target))
        except PermissionError as exc:
            if failure == "chained":
                raise RuntimeError(f"{ORIGINAL} {STORAGE_KEY}") from exc
            raise

    if failure == "mkdir":
        monkeypatch.setattr(Path, "mkdir", lambda self, *args, **kwargs: denied(self))
    else:
        monkeypatch.setattr(FileStorage, "save", lambda self, target, *args, **kwargs: denied(target))
    with app.test_request_context():
        with pytest.raises(Exception) as caught:
            write(kind, upload(kind))
        # The existing support/HR handlers use logger.exception; test formatted
        # traceback and chained exceptions, not merely the exception message.
        logging.getLogger("f2-outer-handler").error("Upload failed: %s", caught.value,
                                                  exc_info=(type(caught.value), caught.value, caught.tb))
    assert_clean(caplog, app, "PRIVATE_UPLOAD_WRITE_FAILED")


def test_hr_size_failure_keeps_zero_size_without_leaking(app, monkeypatch, caplog):
    def denied(path):
        raise PermissionError(13, STORAGE_KEY, path)

    monkeypatch.setattr(hr.os.path, "getsize", denied)
    with app.app_context():
        payload = hr._save_file(upload("hr"))
    assert payload["file_size"] == 0
    assert_clean(caplog, app, "PRIVATE_UPLOAD_SIZE_CHECK_FAILED")


def test_account_photo_failure_keeps_flash_redirect_and_rollback(app, monkeypatch, caplog):
    events = []
    user = SimpleNamespace(id=123, profile_photo_path="old-reference.png")
    monkeypatch.setattr(account, "current_user", user)
    monkeypatch.setattr(account, "_save_profile_photo", profile.save_profile_photo)
    monkeypatch.setattr(account, "url_for", lambda *args, **kwargs: "/account")
    monkeypatch.setattr(account, "db", SimpleNamespace(session=SimpleNamespace(
        rollback=lambda: events.append("rollback"), commit=lambda: events.append("commit"))))

    def denied(self, target, *args, **kwargs):
        raise PermissionError(13, STORAGE_KEY, str(target))

    monkeypatch.setattr(FileStorage, "save", denied)
    with app.test_request_context("/account/photo", method="POST", data={
        "profile_photo": (io.BytesIO(b"photo"), f"{ORIGINAL}.png"), "next": "/account"}):
        response = account.account_change_photo()
        assert response.status_code == 302 and response.location == "/account"
        assert get_flashed_messages(with_categories=True) == [
            ("danger", "Profil fotoğrafı güncellenirken hata oluştu.")]
    assert events == ["rollback"]
    assert user.profile_photo_path == "old-reference.png"
    assert_clean(caplog, app, "PROFILE_PHOTO_UPDATE_FAILED")


@pytest.mark.parametrize("kind", ["profile", "support", "hr"])
def test_successful_upload_contract_is_preserved(app, monkeypatch, kind):
    added: list[Any] = []
    if kind == "support":
        monkeypatch.setattr(support, "current_user", SimpleNamespace(id=123))
        monkeypatch.setattr(support, "db", SimpleNamespace(session=SimpleNamespace(add=added.append)))
        monkeypatch.setattr(support, "SupportTicketAttachment", lambda **kwargs: kwargs)
    with app.app_context():
        result = write(kind, upload(kind))
    files = list(Path(app.config["PRIVATE_UPLOAD_FOLDER"]).rglob("*.*"))
    assert len(files) == 1 and files[0].read_bytes() == b"%PDF-1.4\n%%EOF\n"
    if kind == "profile":
        assert result.startswith("uploads/profile_photos/user_123_")
    elif kind == "support":
        assert added[0]["filename"] == f"{ORIGINAL}.pdf"
    else:
        assert result["original_filename"] == f"{ORIGINAL}.pdf"
        assert result["file_size"] == len(b"%PDF-1.4\n%%EOF\n")
