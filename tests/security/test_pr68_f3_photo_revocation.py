"""F3 attacks against real photo handlers, synthetic files and an in-memory DB."""
from __future__ import annotations

import io
import logging
import secrets
from pathlib import Path

import pytest
from flask import Flask
from flask_login import LoginManager
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.main_handlers.account_handlers import account_change_photo
from app.models import User
from app.routes import bys360_profile_photo_file
from app.security.private_uploads import install_private_static_guard
from app.services.personnel.profile_photo import delete_personnel_profile_photo
from app.services.profile_photo_service import save_profile_photo

NAME = "user_1_old_key.png"
REL = "uploads/profile_photos/" + NAME
SECRET = b"REVOKED-PRIVATE-PHOTO"


def _user(user_id: int) -> User:
    user = db.session.get(User, user_id)
    assert user is not None
    return user


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
def env(tmp_path):
    root = tmp_path / "app"
    static = root / "static"
    static.mkdir(parents=True)
    (static / "img").mkdir()
    (static / "img" / "default-avatar.svg").write_text("default")
    app = Flask("f3", root_path=str(root), static_folder=str(static))
    app.config.update(TESTING=True, SECRET_KEY=secrets.token_urlsafe(32), SQLALCHEMY_DATABASE_URI="sqlite://",
                      PRIVATE_UPLOAD_FOLDER=str(tmp_path / "private"), UPLOAD_FOLDER=str(tmp_path / "legacy"))
    db.init_app(app)
    login = LoginManager(app)
    login.login_view = "login"
    login.user_loader(lambda uid: db.session.get(User, int(uid)))
    app.add_url_rule("/login", "login", lambda: "login")
    app.add_url_rule("/uploads/profile_photos/<path:filename>", view_func=bys360_profile_photo_file)
    app.add_url_rule("/account", "main.account", lambda: "account")
    app.add_url_rule("/account/photo", view_func=account_change_photo, methods=["POST"])
    install_private_static_guard(app)
    with app.app_context():
        User.__table__.create(db.engine)
        for uid in (1, 2, 3):
            db.session.add(User(id=uid, sicil_no=str(uid), email=f"u{uid}@example.test", password_hash="test",
                                ad="Test", soyad=str(uid), is_active=True,
                                profile_photo_path=REL if uid == 1 else None))
        db.session.commit()
    roots = [tmp_path / "private" / "profile_photos", static / "uploads" / "profile_photos",
             tmp_path / "legacy" / "profile_photos", tmp_path / "legacy" / "uploads" / "profile_photos"]
    yield app, roots
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def client(app, uid=2):
    result = app.test_client()
    if uid is not None:
        with result.session_transaction() as session:
            session["_user_id"] = str(uid)
            session["_fresh"] = True
    return result


def copies(roots):
    files = []
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
        path = root / NAME
        path.write_bytes(SECRET)
        files.append(path)
    return files


def revoke(app):
    with app.app_context():
        result = delete_personnel_profile_photo(_user(1), app_root_path=app.root_path)
        db.session.commit()
        assert _user(1).profile_photo_path is None
    return result


def refused(app):
    for uid in (None, 1, 2):
        response = client(app, uid).get("/uploads/profile_photos/" + NAME,
                                       headers={"Range": "bytes=0-10", "If-None-Match": "old"})
        assert response.status_code in (302, 404)
        assert SECRET not in response.data
    assert client(app).get("/static/" + REL).status_code == 404


def test_delete_cleans_all_four_copies_and_preserves_other_photo(env):
    app, roots = env
    files = copies(roots)
    other = roots[0] / "user_2_other.png"
    other.write_bytes(b"OTHER")
    assert client(app).get("/uploads/profile_photos/" + NAME).data == SECRET
    assert revoke(app).file_deleted
    assert not any(path.exists() for path in files)
    assert other.read_bytes() == b"OTHER"
    refused(app)


@pytest.mark.parametrize("failed", [0, 1, 2, 3, "all"])
def test_partial_cleanup_revokes_persisted_reference_and_old_url(env, monkeypatch, caplog, failed):
    app, roots = env
    files = copies(roots)
    unlink = Path.unlink

    def denied(path, *args, **kwargs):
        if path.name == NAME and (failed == "all" or path == files[failed]):
            raise PermissionError(13, "denied", str(path))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    result = revoke(app)
    assert result.warning.startswith("profile_photo_delete_failed")
    for index, path in enumerate(files):
        assert path.exists() == (failed == "all" or index == failed)
    refused(app)
    assert "PRIVATE_UPLOAD_DELETE_FAILED" in caplog.text
    assert NAME not in caplog.text and str(roots[0]) not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("reference", [REL, REL.upper().replace("/", "\\")])
def test_shared_reference_is_not_physically_deleted(env, reference):
    app, roots = env
    files = copies(roots)
    with app.app_context():
        _user(3).profile_photo_path = reference
        db.session.commit()
    revoke(app)
    assert all(path.read_bytes() == SECRET for path in files)
    if reference == REL:
        assert client(app, 3).get("/uploads/profile_photos/" + NAME).data == SECRET


@pytest.mark.parametrize("state", ["cleared", "replaced", "inactive"])
def test_unreferenced_or_inactive_photo_is_not_downloadable(env, state):
    app, roots = env
    copies(roots)
    with app.app_context():
        owner = _user(1)
        if state == "inactive":
            owner.is_active = False
        else:
            owner.profile_photo_path = None if state == "cleared" else "uploads/profile_photos/new.png"
        db.session.commit()
    refused(app)


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("separator", ["/", "\\"])
def test_active_legacy_and_private_photo_remain_readable_without_cache(env, index, separator):
    app, roots = env
    copies([roots[index]])
    with app.app_context():
        _user(1).profile_photo_path = REL.replace("/", separator)
        db.session.commit()
    response = client(app).get("/uploads/profile_photos/" + NAME)
    assert response.status_code == 200 and response.data == SECRET
    assert "no-store" in response.headers["Cache-Control"]


def test_account_remove_revokes_even_when_private_unlink_fails(env, monkeypatch):
    app, roots = env
    files = copies(roots)
    unlink = Path.unlink

    def denied(path, *args, **kwargs):
        if path == files[0]:
            raise PermissionError(13, "denied", str(path))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    response = client(app, 1).post("/account/photo", data={"remove_profile_photo": "1"})
    assert response.status_code == 302
    assert files[0].exists() and not any(path.exists() for path in files[1:])
    refused(app)


def test_replacement_revokes_old_url_even_when_cleanup_fails(env, monkeypatch):
    app, roots = env
    copies(roots)
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")))
    with app.app_context():
        new = save_profile_photo(FileStorage(stream=io.BytesIO(b"NEW"), filename="new.png"), _user(1))
        db.session.commit()
    refused(app)
    assert client(app).get("/" + new).data == b"NEW"


def test_traversal_reference_does_not_delete_other_user_file(env):
    app, roots = env
    files = copies(roots)
    with app.app_context():
        _user(1).profile_photo_path = "../outside/" + NAME
        db.session.commit()
    revoke(app)
    assert all(path.exists() for path in files)


def test_mismatched_user_filename_is_not_deleted(env):
    app, roots = env
    files = copies(roots)
    with app.app_context():
        _user(1).profile_photo_path = None
        other = _user(2)
        other.profile_photo_path = REL
        db.session.commit()
        delete_personnel_profile_photo(other, app_root_path=app.root_path)
        db.session.commit()
    assert all(path.exists() for path in files)
    refused(app)
