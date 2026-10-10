"""Contract F07b (D2, F07b-Q1, F07b-Q2): only a verified admin reads, shares or deletes another user's file.

Approved decisions:

* D2 (HUMAN_POLICY_APPROVED, 2026-10-09): ``sistem_yoneticisi`` keeps its technical administration
  functions but gets no automatic access to sensitive documents.
* F07b-Q1 (HUMAN_POLICY_APPROVED, 2026-10-10): ``dosya_merkezi_yetkilisi`` gives no automatic access
  to other users' private file contents. No new content-access permission is created here.
* F07b-Q2 (HUMAN_POLICY_APPROVED, 2026-10-10): deleting another user's file belongs only to the
  verified ``admin`` role; ownership and authorization are checked on the server before the delete,
  and the delete is written to the audit log.

The default File Center role matrix gives ``sistem_yoneticisi`` and ``dosya_merkezi_yetkilisi`` the
File Center admin permission, and ``is_file_center_admin`` was the only check on another user's file:
both could download any user's private file (``/file-center/download/<id>``), put a guest link on it
(``/file-center/share/<id>``) and delete it (``/file-center/delete/<id>``).

Rule now (``app/file_center/permissions.py``): ``can_read_other_users_files`` and
``can_delete_other_users_files`` need the stored role ``admin`` AND the File Center admin permission.
The owner keeps full control of their own files. The technical roles and ``dosya_merkezi_yetkilisi``
keep File Center administration (dashboard, maintenance, quota, security, settings, role matrix,
revoking links).
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
TECHNICAL = ["sistem_yoneticisi", "system_admin"]
NOT_VERIFIED_ADMIN = [*TECHNICAL, "dosya_merkezi_yetkilisi"]


# --- the rule ---------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["sistem_yoneticisi", "dosya_merkezi_yetkilisi"])
def test_file_center_administrators_keep_administration_but_not_other_users_files(role):
    from app.file_center.permissions import (
        can_delete_other_users_files,
        can_manage_file_center_admin,
        can_read_other_users_files,
        is_file_center_admin,
    )

    user = SimpleNamespace(role=role, is_authenticated=True)
    assert is_file_center_admin(user) is True
    assert can_manage_file_center_admin(user) is True
    assert can_read_other_users_files(user) is False
    assert can_delete_other_users_files(user) is False


def test_only_the_verified_admin_reads_and_deletes_other_users_files():
    from app.file_center.permissions import can_delete_other_users_files, can_read_other_users_files

    admin = SimpleNamespace(role="admin", is_authenticated=True)
    assert can_read_other_users_files(admin) is True
    assert can_delete_other_users_files(admin) is True
    for role in ("system_admin", "super_admin", "baskan", "koordinator", "personel", ""):
        user = SimpleNamespace(role=role, is_authenticated=True)
        assert can_read_other_users_files(user) is False, role
        assert can_delete_other_users_files(user) is False, role
    anonymous = SimpleNamespace(role="admin", is_authenticated=False)
    assert can_read_other_users_files(anonymous) is False
    assert can_delete_other_users_files(anonymous) is False


@pytest.mark.parametrize("attr", ["role_label", "title", "role_key", "role_name"])
def test_admin_must_be_the_stored_role_not_a_label_or_alias_attribute(attr):
    from app.file_center.permissions import can_delete_other_users_files, can_read_other_users_files

    user = SimpleNamespace(role="personel", is_authenticated=True, **{attr: "admin"})
    assert can_read_other_users_files(user) is False
    assert can_delete_other_users_files(user) is False


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


def _create_user(app, sicil, role, role_label=None):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@bys360.test", ad="F07b", soyad=sicil, role=role,
                    role_label=role_label, is_active=True, must_change_password=False,
                    must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_file(app, owner_id):
    from app.extensions import db
    from app.file_center.services import update_quota_for_user, upload_root_for_user
    from app.models.file_center_models import FileStorageItem

    with app.app_context():
        path = upload_root_for_user(owner_id) / f"{uuid.uuid4().hex}.txt"
        path.write_bytes(CONTENT)
        item = FileStorageItem(owner_user_id=owner_id, original_filename="ozel.txt", stored_filename=path.name,
                               storage_path=str(path.resolve()), content_type="text/plain", extension="txt",
                               size_bytes=len(CONTENT), sha256_hash=uuid.uuid4().hex * 2, status="ready",
                               scan_status="clean", is_deleted=False)
        db.session.add(item)
        db.session.flush()
        update_quota_for_user(owner_id)
        db.session.commit()
        return item.id


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _share(client, file_id):
    return client.post(f"/file-center/share/{file_id}",
                       data={"password": "GuestLinkTest1", "days": "7", "max_downloads": "5"})


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


def _delete_audit_actors(app, file_id):
    from app.extensions import db
    from app.models.file_center_models import FileAuditLog

    with app.app_context():
        rows = db.session.query(FileAuditLog).filter_by(file_id=file_id, action="file_deleted").all()
        return [row.actor_user_id for row in rows]


def _quota_file_count(app, user_id):
    from app.extensions import db
    from app.models.file_center_models import FileQuotaUsage

    with app.app_context():
        row = db.session.query(FileQuotaUsage).filter_by(user_id=user_id).one_or_none()
        return None if row is None else int(row.file_count)


@pytest.mark.parametrize("role", NOT_VERIFIED_ADMIN)
def test_a_non_admin_file_center_role_cannot_download_share_or_delete_another_users_file(app, role):
    owner = _create_user(app, "F07BOWNER", "personel")
    _create_user(app, "F07BROLE", role)
    file_id = _create_file(app, owner)
    client = _client(app, "F07BROLE")
    assert CONTENT not in client.get(f"/file-center/download/{file_id}").data
    _share(client, file_id)
    assert _link_count(app, file_id) == 0
    client.post(f"/file-center/delete/{file_id}")
    assert _is_deleted(app, file_id) is False
    assert _delete_audit_actors(app, file_id) == []


@pytest.mark.parametrize("label", ["admin", "Admin"])
def test_a_personel_labelled_admin_cannot_delete_another_users_file(app, label):
    owner = _create_user(app, "F07BOWNER", "personel")
    _create_user(app, "F07BLABEL", "personel", role_label=label)
    file_id = _create_file(app, owner)
    _client(app, "F07BLABEL").post(f"/file-center/delete/{file_id}")
    assert _is_deleted(app, file_id) is False


@pytest.mark.parametrize("role", ["sistem_yoneticisi", "dosya_merkezi_yetkilisi"])
def test_file_center_administrators_keep_the_admin_pages(app, role):
    _create_user(app, "F07BROLE", role)
    client = _client(app, "F07BROLE")
    for path in ("/file-center/admin", "/file-center/maintenance"):
        assert client.get(path).status_code == 200, (role, path)


def test_the_verified_admin_downloads_shares_and_deletes_with_an_audit_row(app):
    owner = _create_user(app, "F07BOWNER", "personel")
    admin = _create_user(app, "F07BADMIN", "admin")
    file_id = _create_file(app, owner)
    assert _quota_file_count(app, owner) == 1
    client = _client(app, "F07BADMIN")
    assert client.get(f"/file-center/download/{file_id}").data == CONTENT
    _share(client, file_id)
    assert _link_count(app, file_id) == 1
    client.post(f"/file-center/delete/{file_id}")
    assert _is_deleted(app, file_id) is True
    assert _delete_audit_actors(app, file_id) == [admin]
    # The owner's quota is recalculated (it was the actor's before).
    assert _quota_file_count(app, owner) == 0


def test_the_owner_keeps_download_share_and_delete_of_their_own_file(app):
    owner = _create_user(app, "F07BOWNER", "personel")
    file_id = _create_file(app, owner)
    client = _client(app, "F07BOWNER")
    assert client.get(f"/file-center/download/{file_id}").data == CONTENT
    _share(client, file_id)
    assert _link_count(app, file_id) == 1
    client.post(f"/file-center/delete/{file_id}")
    assert _is_deleted(app, file_id) is True
    assert _delete_audit_actors(app, file_id) == [owner]
    assert _quota_file_count(app, owner) == 0


def test_the_owner_can_still_upload(app):
    import io

    owner = _create_user(app, "F07BOWNER", "personel")
    client = _client(app, "F07BOWNER")
    client.post("/file-center/upload", data={"file": (io.BytesIO(b"F07b upload content"), "yukleme.txt")},
                content_type="multipart/form-data")
    from app.extensions import db
    from app.models.file_center_models import FileStorageItem

    with app.app_context():
        assert db.session.query(FileStorageItem).filter_by(owner_user_id=owner, is_deleted=False).count() == 1
