"""Contract F07a (D3 follow-up): File Center rights come from the stored role only.

Approved decision D3 (HUMAN_POLICY_APPROVED, 2026-10-09): ``role_label`` never grants access on
its own; no indirect access through a display label or a title.

``app/file_center/permissions.py`` read seven attributes as role identity
(``_ROLE_IDENTITY_ATTRS``: role, role_key, role_name, role_label, title, position, job_title).
A ``personel`` whose display label or title was "admin", "Sistem Yöneticisi" or
"Dosya Merkezi Yetkilisi" became a File Center admin (``is_file_center_admin``): download,
delete and share links on every other user's private files, the organisation quota board,
the role matrix, security, settings and maintenance. A label such as "Koordinatör" made the
user a File Center manager (logs). User import (``ops_import_services``) and the personnel
sync write ``role_label`` from the source system, independently of the stored role.

Rule now: only the stored ``role`` (and the ``role_key``/``role_name`` attributes some callers
pass) is role identity. The stored-role behaviour and the DB role matrix are unchanged.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

from app.file_center.permissions import (
    _admin_like_text,
    _effective_role_key,
    _manager_like_text,
    can_manage_file_center_role_matrix,
    can_manage_file_center_security,
    can_manage_file_center_settings,
    can_view_logs,
    is_file_center_admin,
    is_file_center_manager,
)

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_f07_file_center")
_TMP_STORAGE_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_f07_file_center_storage")
PASSWORD = "F07FileCenterRoleTest1!"
CONTENT = b"BYS360 F07 private file content"

ADMIN_LABELS = ["admin", "Admin", "Sistem Yöneticisi", "sistem_yoneticisi", "SİSTEM YÖNETİCİSİ", "superadmin",
                "Dosya Merkezi Yetkilisi"]
MANAGER_LABELS = ["Koordinatör", "yonetici", "Müdür", "Amir", "Başkan"]
DISPLAY_ATTRS = ["role_label", "title", "position", "job_title"]


def _fake(role: str, **display) -> SimpleNamespace:
    values = {attr: None for attr in DISPLAY_ATTRS}
    values.update(display)
    return SimpleNamespace(role=role, is_authenticated=True, **values)


ADMIN_WRAPPERS = (is_file_center_admin, can_manage_file_center_role_matrix, can_manage_file_center_security,
                  can_manage_file_center_settings)


# --- pure logic (no app, no DB: the default matrix path) -------------------------------------


@pytest.mark.parametrize("attr", DISPLAY_ATTRS)
@pytest.mark.parametrize("label", ADMIN_LABELS)
def test_an_admin_display_label_or_title_grants_no_file_center_admin(attr, label):
    for role in ("personel", ""):
        user = _fake(role, **{attr: label})
        assert _admin_like_text(user) is False, (role, attr, label)
        assert _effective_role_key(user) == "personel", (role, attr, label)
        for wrapper in ADMIN_WRAPPERS:
            assert wrapper(user) is False, (wrapper.__name__, role, attr, label)


@pytest.mark.parametrize("attr", DISPLAY_ATTRS)
@pytest.mark.parametrize("label", MANAGER_LABELS)
def test_a_manager_display_label_or_title_grants_no_file_center_manager(attr, label):
    user = _fake("personel", **{attr: label})
    assert _manager_like_text(user) is False
    assert is_file_center_manager(user) is False
    assert can_view_logs(user) is False


@pytest.mark.parametrize("role", ["admin", "sistem_yoneticisi", "dosya_merkezi_yetkilisi"])
def test_the_stored_role_still_decides(role):
    user = _fake(role, role_label="Personel", title="Uzman")
    assert is_file_center_admin(user) is True
    assert _effective_role_key(user) == role


@pytest.mark.parametrize("role", ["koordinator", "yonetici", "baskan"])
def test_a_stored_manager_role_is_still_a_manager(role):
    user = _fake(role, role_label="Personel")
    assert is_file_center_manager(user) is True
    assert is_file_center_admin(user) is False


def test_role_key_and_role_name_attributes_still_count_as_role():
    assert is_file_center_admin(SimpleNamespace(role="", role_key="admin", is_authenticated=True)) is True
    assert is_file_center_admin(SimpleNamespace(role="", role_name="sistem_yoneticisi", is_authenticated=True)) is True


# --- HTTP: another user's private file -------------------------------------------------------


@pytest.fixture
def app(monkeypatch):
    for key, value in {
        "APP_ENV": "testing", "FLASK_ENV": "testing", "SECRET_KEY": "test-secret-key-f07-file-center",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "f07-file-center-first-login-test", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "MAIL_SUPPRESS_SEND": "true", "SCHEDULER_ENABLED": "false", "FILE_CENTER_ENABLED": "true",
    }.items():
        monkeypatch.setenv(key, value)
    storage_root = os.path.join(_TMP_STORAGE_DIR, uuid.uuid4().hex)
    os.makedirs(storage_root, exist_ok=True)
    monkeypatch.setenv("FILE_CENTER_STORAGE_ROOT", storage_root)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"f07_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@bys360.test", ad="F07", soyad=sicil, role=role,
                    role_label=role_label, is_active=True, must_change_password=False,
                    must_set_security_question=False)
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


def _download_as(app, sicil, file_id):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client.get(f"/file-center/download/{file_id}")


@pytest.mark.parametrize("label", ["admin", "Sistem Yöneticisi", "Dosya Merkezi Yetkilisi"])
def test_a_personel_with_an_admin_label_cannot_download_another_users_private_file(app, label):
    owner = _create_user(app, "F07OWNER", "personel")
    _create_user(app, "F07LABEL", "personel", role_label=label)
    file_id = _create_file(app, owner)
    response = _download_as(app, "F07LABEL", file_id)
    assert CONTENT not in response.data


def test_the_owner_and_a_stored_admin_role_keep_their_access(app):
    owner = _create_user(app, "F07OWNER", "personel")
    _create_user(app, "F07ADMIN", "admin", role_label="Personel")
    file_id = _create_file(app, owner)
    assert _download_as(app, "F07OWNER", file_id).data == CONTENT
    assert _download_as(app, "F07ADMIN", file_id).data == CONTENT
