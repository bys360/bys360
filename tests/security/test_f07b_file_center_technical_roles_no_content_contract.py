"""Contract F07b (D2 follow-up): the technical roles administer File Center but do not read other users' files.

Approved decision D2 (HUMAN_POLICY_APPROVED, 2026-10-09): ``sistem_yoneticisi`` keeps its technical
administration functions but gets no automatic access to personnel data, performance data, private
notes or sensitive documents; legitimate technical functions must keep working.

The default File Center role matrix gives ``sistem_yoneticisi`` every permission, and
``is_file_center_admin`` was the only check on another user's file. A technical administrator could
download any user's private file (``/file-center/download/<id>``) and create a password-protected
guest link on it (``/file-center/share/<id>``), which hands the content to anyone outside.

Rule now (``can_read_other_users_files``): reading or sharing another user's file needs File Center
admin AND a stored role outside the technical roles (``sistem_yoneticisi``, ``system_admin``). The
technical roles keep the admin dashboard, maintenance, quota, security, settings, the role matrix,
and deleting files and revoking links (no content exposure). The owner, ``admin`` and
``dosya_merkezi_yetkilisi`` are unchanged.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_f07b_file_center")
_TMP_STORAGE_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_f07b_file_center_storage")
PASSWORD = "F07bFileCenterTechTest1!"
CONTENT = b"BYS360 F07b private file content"
TECHNICAL_ROLES = ["sistem_yoneticisi", "system_admin"]


# --- the rule ---------------------------------------------------------------------------------


@pytest.mark.parametrize("role", TECHNICAL_ROLES)
def test_technical_roles_are_file_center_admins_but_cannot_read_other_users_files(role):
    from app.file_center.permissions import (
        can_manage_file_center_maintenance,
        can_manage_file_center_role_matrix,
        can_manage_file_center_security,
        can_manage_file_center_settings,
        can_read_other_users_files,
        is_file_center_admin,
    )

    user = SimpleNamespace(role=role, is_authenticated=True)
    assert can_read_other_users_files(user) is False
    if role == "sistem_yoneticisi":  # system_admin has no default matrix row
        for check in (is_file_center_admin, can_manage_file_center_maintenance, can_manage_file_center_role_matrix,
                      can_manage_file_center_security, can_manage_file_center_settings):
            assert check(user) is True, check.__name__


@pytest.mark.parametrize("role", ["admin", "dosya_merkezi_yetkilisi"])
def test_non_technical_file_center_admins_keep_reading_other_users_files(role):
    from app.file_center.permissions import can_read_other_users_files

    assert can_read_other_users_files(SimpleNamespace(role=role, is_authenticated=True)) is True


@pytest.mark.parametrize("role", ["personel", "koordinator", ""])
def test_non_admins_cannot_read_other_users_files(role):
    from app.file_center.permissions import can_read_other_users_files

    assert can_read_other_users_files(SimpleNamespace(role=role, is_authenticated=True)) is False
    assert can_read_other_users_files(SimpleNamespace(role="admin", is_authenticated=False)) is False


# --- HTTP -------------------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch):
    for key, value in {
        "APP_ENV": "testing", "FLASK_ENV": "testing", "SECRET_KEY": "test-secret-key-f07b-file-center",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "f07b-file-center-first-login-test", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "MAIL_SUPPRESS_SEND": "true", "SCHEDULER_ENABLED": "false", "FILE_CENTER_ENABLED": "true",
        "FILE_CENTER_GUEST_LINKS_ENABLED": "true",
    }.items():
        monkeypatch.setenv(key, value)
    storage_root = os.path.join(_TMP_STORAGE_DIR, uuid.uuid4().hex)
    os.makedirs(storage_root, exist_ok=True)
    monkeypatch.setenv("FILE_CENTER_STORAGE_ROOT", storage_root)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"f07b_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(
        TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
        FILE_CENTER_STORAGE_ROOT=storage_root,
    )
    from app.extensions import db

    with flask_app.app_context():
        db.create_all()
    return flask_app


def _create_user(app, sicil, role):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@bys360.test", ad="F07b", soyad=sicil, role=role,
                    is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_file(app, owner_id):
    from app.extensions import db
    from app.file_center.services import upload_root_for_user
    from app.models.file_center_models import FileStorageItem

    with app.app_context():
        path = upload_root_for_user(owner_id) / f"{uuid.uuid4().hex}.txt"
        path.write_bytes(CONTENT)
        item = FileStorageItem(owner_user_id=owner_id, original_filename="ozel.txt", stored_filename=path.name,
                               storage_path=str(path.resolve()), content_type="text/plain", extension="txt",
                               size_bytes=len(CONTENT), sha256_hash=uuid.uuid4().hex * 2, status="ready",
                               scan_status="clean", is_deleted=False)
        db.session.add(item)
        db.session.commit()
        return item.id


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _link_count(app, file_id):
    from app.extensions import db
    from app.models.file_center_models import FileShareLink

    with app.app_context():
        return db.session.query(FileShareLink).filter_by(file_id=file_id).count()


def _is_deleted(app, file_id):
    from app.extensions import db
    from app.models.file_center_models import FileStorageItem

    with app.app_context():
        item = db.session.get(FileStorageItem, file_id)
        assert item is not None
        return bool(item.is_deleted)


@pytest.mark.parametrize("role", TECHNICAL_ROLES)
def test_a_technical_role_cannot_download_or_share_another_users_file(app, role):
    owner = _create_user(app, "F07BOWNER", "personel")
    _create_user(app, "F07BTECH", role)
    file_id = _create_file(app, owner)
    client = _client(app, "F07BTECH")
    assert CONTENT not in client.get(f"/file-center/download/{file_id}").data
    client.post(f"/file-center/share/{file_id}", data={"password": "GuestLinkTest1", "days": "7", "max_downloads": "5"})
    assert _link_count(app, file_id) == 0


def test_the_technical_role_keeps_admin_pages_and_can_delete_for_cleanup(app):
    owner = _create_user(app, "F07BOWNER", "personel")
    _create_user(app, "F07BTECH", "sistem_yoneticisi")
    file_id = _create_file(app, owner)
    client = _client(app, "F07BTECH")
    for path in ("/file-center/admin", "/file-center/maintenance"):
        assert client.get(path).status_code == 200, path
    client.post(f"/file-center/delete/{file_id}")
    assert _is_deleted(app, file_id) is True


@pytest.mark.parametrize("sicil,role", [("F07BOWNER", "personel"), ("F07BADMIN", "admin"),
                                        ("F07BFILES", "dosya_merkezi_yetkilisi")])
def test_owner_admin_and_file_center_officer_keep_download_and_share(app, sicil, role):
    owner = _create_user(app, "F07BOWNER", "personel")
    if sicil != "F07BOWNER":
        _create_user(app, sicil, role)
    file_id = _create_file(app, owner)
    client = _client(app, sicil)
    assert client.get(f"/file-center/download/{file_id}").data == CONTENT
    client.post(f"/file-center/share/{file_id}", data={"password": "GuestLinkTest1", "days": "7", "max_downloads": "5"})
    assert _link_count(app, file_id) == 1
