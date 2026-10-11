"""F2 fault injection: synthetic uploads only, without a database or live services."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, get_flashed_messages
from werkzeug.datastructures import FileStorage

from app.institutional import hr_personnel_operations_routes as hr
from app.main_handlers import account_handlers as account
from app.services import profile_photo_service as profile
from app.support import routes as support


@pytest.fixture
def app(tmp_path):
    app = Flask("f2", static_folder=str(tmp_path / "static"))
    app.secret_key = "synthetic-f2-test-only"
    app.config.update(PRIVATE_UPLOAD_FOLDER=str(tmp_path / "private-secret-store"),
                      MAX_CONTENT_LENGTH=1024 * 1024)
    return app


def upload(kind):
    return FileStorage(stream=io.BytesIO(b"%PDF-1.4\n%%EOF\n"),
                       filename="sensitive-original.png" if kind == "profile" else "sensitive-original.pdf")


def write(kind, file):
    if kind == "profile":
        return profile.save_profile_photo(file, SimpleNamespace(id=123, profile_photo_path=None))
    if kind == "support":
        return support._store_ticket_attachment(SimpleNamespace(id=123), file)
    return hr._save_file(file)


def assert_clean(caplog, app, code):
    text = caplog.text.replace("\\\\", "\\")
    assert code in text
    for secret in (app.config["PRIVATE_UPLOAD_FOLDER"], "private-secret-store",
                   "sensitive-original", "user_123_", "secret-storage-key"):
        assert secret not in text


@pytest.mark.parametrize("kind", ["profile", "support", "hr"])
@pytest.mark.parametrize("failure", ["save", "chained", "mkdir"])
def test_upload_io_failures_are_safe_for_outer_exception_logs(app, monkeypatch, caplog, kind, failure):
    def denied(target):
        try:
            raise PermissionError(13, "secret-storage-key", str(target))
        except PermissionError as exc:
            if failure == "chained":
                raise RuntimeError("sensitive-original secret-storage-key") from exc
            raise

    if failure == "mkdir":
        monkeypatch.setattr(Path, "mkdir", lambda self, *args, **kwargs: denied(self))
    else:
        monkeypatch.setattr(FileStorage, "save", lambda self, target, *args, **kwargs: denied(target))
    with app.app_context():
        with pytest.raises(Exception) as caught:
            write(kind, upload(kind))
        # The existing support/HR handlers use logger.exception; test formatted
        # traceback and chained exceptions, not merely the exception message.
        logging.getLogger("f2-outer-handler").error("Upload failed: %s", caught.value,
                                                  exc_info=(type(caught.value), caught.value, caught.tb))
    assert_clean(caplog, app, "PRIVATE_UPLOAD_WRITE_FAILED")


def test_hr_size_failure_keeps_zero_size_without_leaking(app, monkeypatch, caplog):
    def denied(path):
        raise PermissionError(13, "secret-storage-key", path)

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
        raise PermissionError(13, "secret-storage-key", str(target))

    monkeypatch.setattr(FileStorage, "save", denied)
    with app.test_request_context("/account/photo", method="POST", data={
        "profile_photo": (io.BytesIO(b"photo"), "sensitive-original.png"), "next": "/account"}):
        response = account.account_change_photo()
        assert response.status_code == 302 and response.location == "/account"
        assert get_flashed_messages(with_categories=True) == [
            ("danger", "Profil fotoğrafı güncellenirken hata oluştu.")]
    assert events == ["rollback"]
    assert user.profile_photo_path == "old-reference.png"
    assert_clean(caplog, app, "PROFILE_PHOTO_UPDATE_FAILED")


@pytest.mark.parametrize("kind", ["profile", "support", "hr"])
def test_successful_upload_contract_is_preserved(app, monkeypatch, kind):
    added = []
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
        assert added[0]["filename"] == "sensitive-original.pdf"
    else:
        assert result["original_filename"] == "sensitive-original.pdf"
        assert result["file_size"] == len(b"%PDF-1.4\n%%EOF\n")
