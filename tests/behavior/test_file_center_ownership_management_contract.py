"""BYS360_COVERAGE_WAVE6_AGENT1_FILE_CENTER_OWNERSHIP_MANAGEMENT_CONTRACT

Behavioral, route-boundary contract for the still-uncovered authenticated
ownership routes in app/file_center/routes.py:

    file_center_download                 GET  /file-center/download/<id>
    file_center_delete                   POST /file-center/delete/<id>
    file_center_create_guest_link        POST /file-center/share/<file_id>
    file_center_revoke_guest_link        POST /file-center/share/<link_id>/revoke
    file_center_close_request            POST /file-center/requests/<id>/close
    file_center_revoke_request           POST /file-center/requests/<id>/revoke
    file_center_request_message          GET  /file-center/requests/<id>/message.txt
    file_center_prepare_request_reminder POST /file-center/requests/<id>/reminder

Explicitly out of scope (already covered elsewhere or excluded by the wave
brief): anonymous guest upload/download (test_file_center_anonymous_guest_
access_contract.py), quota policy / role matrix administration
(test_file_center_quota_and_role_matrix_admin_contract.py), and the Wave-1
service-layer contracts (test_file_center_services_security_contract.py,
save_uploaded_file / secure_file_path / run_security_scan / log_audit /
log_access unit coverage). This file never re-tests those; every route here
was independently confirmed to have zero existing test-name overlap via
`grep -n "file_center_download\\|file_center_delete\\|..." tests/behavior/*.py`
before writing a single test.

Ownership contract under test (identical shape for both models, read
directly from app/file_center/routes.py):

    _can_manage_file(item)  = item.owner_user_id == current_user.id or is_admin_like(current_user)
    _can_manage_request(row) = row.owner_user_id == current_user.id or is_admin_like(current_user)

`is_admin_like` (app/file_center/services.py) is substring-sensitive on
`role`/`role_label`/`username` (documented precedent: this wave's sibling
test_file_center_quota_and_role_matrix_admin_contract.py's Defect I note is
about a *different* function, `permissions.py::_effective_role_key`, not
this one -- but the same defensive fixture discipline is applied here
regardless: every "stranger" identity below uses role="personel", no
role_label, and an ad/soyad/email/sicil_no containing no "admin"/"yonetici"
substring anywhere, so a false-pass via accidental admin-like matching is
structurally impossible.

Judgment calls:

1. `file_center_download`'s success path requires a REAL file on disk
   (`secure_file_path` calls `Path.is_file()`) -- `FILE_CENTER_STORAGE_ROOT`
   is pointed at a dedicated per-test-run temp directory (never inside the
   repo) and a real small file is written there via the same
   `upload_root_for_user(owner_id)` helper the real upload path uses, so the
   download route's `send_file(...)` call is exercised for real, not
   skipped/mocked.

2. `guest_links_enabled()` defaults to False (same `_db_bool(..., False)`
   pattern documented for `file_center_enabled()` in the sibling quota/role
   test file) -- `FILE_CENTER_GUEST_LINKS_ENABLED=true` is set for every
   test in this file so the guest-link routes' own feature gate does not
   mask the ownership gate under test.

3. `can_download_file` additionally requires `scan_status in {"clean",
   "ready"}` when `require_clean_before_download()` is on (env-driven,
   defaults on) -- fixtures always create items with `scan_status="clean"`
   so ownership is the only variable under test in the owner/stranger cases.

4. `file_center_prepare_request_reminder` and `file_center_send_request_
   email_route` both gate on `row.status == "open"` -- this file proves that
   state boundary for the reminder route (send-email is not selected; SMTP
   side effects would need additional mocking discipline out of this wave's
   scope) using MAIL_SUPPRESS_SEND=true regardless, matching this repo's
   established fixture convention.

5. Defects F, I, K, L are NOT re-characterized here. Every assertion below
   is about the object-ownership gate (`_can_manage_file`/`_can_manage_
   request`) and real lifecycle state transitions only -- nothing in this
   file asserts correctness of quota policy, role-matrix administration, or
   any other area those defect IDs might cover.

Fixture pattern: this wave's mandatory proven shape, copied from
tests/behavior/test_file_center_quota_and_role_matrix_admin_contract.py
(Config class-attribute patch BEFORE create_app(), StaticPool + pysqlite
isolation_level=None + explicit BEGIN event listener, real `/login` POST).
Uses its own dedicated tmp DB directory (C:\\bys360_pytest_tmp_wave6_agent1)
and its own dedicated storage root so it shares no state with any other
wave/agent running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave6_agent1")
_TMP_STORAGE_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave6_agent1_storage")

DEFAULT_PASSWORD = "Wave6Agent1OwnershipTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "wave6-agent1-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-wave6-agent1-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", DEFAULT_FIRST_LOGIN_PASSWORD)
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")
    monkeypatch.setenv("FILE_CENTER_GUEST_LINKS_ENABLED", "true")

    storage_root = os.path.join(_TMP_STORAGE_DIR, uuid.uuid4().hex)
    os.makedirs(storage_root, exist_ok=True)
    monkeypatch.setenv("FILE_CENTER_STORAGE_ROOT", storage_root)

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"wave6_agent1_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
        FILE_CENTER_STORAGE_ROOT=storage_root,
    )

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# User / login helpers
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role="personel", role_label=None, is_active=True, password=DEFAULT_PASSWORD):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"W6A1{n:06d}",
            email=f"wave6-agent1-{n}@bys360.test",
            ad="Wave6",
            soyad=f"Owner{n}",
            role=role,
            role_label=role_label,
            is_active=is_active,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id, user.sicil_no


def _create_owner(app):
    return _create_user(app, role="personel")


def _create_stranger(app):
    """Clean, unambiguous non-admin identity -- no admin-like substring anywhere."""
    return _create_user(app, role="personel")


def _create_admin(app):
    return _create_user(app, role="admin")


def _login(client, sicil_no, password=DEFAULT_PASSWORD):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


# ---------------------------------------------------------------------------
# Fixture builders (real DB rows + real files on disk)
# ---------------------------------------------------------------------------


def _write_real_file(app, owner_id, content: bytes = b"BYS360 wave6 agent1 fixture content"):
    from app.file_center.services import upload_root_for_user

    with app.app_context():
        root = upload_root_for_user(owner_id)
        stored_name = f"{uuid.uuid4().hex}.txt"
        path = root / stored_name
        path.write_bytes(content)
        return str(path.resolve())


def _create_file(app, *, owner_id, is_deleted=False):
    from app.extensions import db
    from app.models.file_center_models import FileStorageItem

    storage_path = _write_real_file(app, owner_id)
    with app.app_context():
        item = FileStorageItem(
            owner_user_id=owner_id,
            original_filename="rapor.txt",
            stored_filename=os.path.basename(storage_path),
            storage_path=storage_path,
            content_type="text/plain",
            extension="txt",
            size_bytes=len(b"BYS360 wave6 agent1 fixture content"),
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status="ready",
            scan_status="clean",
            is_deleted=is_deleted,
        )
        db.session.add(item)
        db.session.commit()
        return item.id


def _create_share_link(app, *, file_id, created_by_id, is_active=True):
    import datetime as _dt

    from werkzeug.security import generate_password_hash

    from app.extensions import db
    from app.models.file_center_models import FileShareLink

    with app.app_context():
        link = FileShareLink(
            file_id=file_id,
            token_hash=uuid.uuid4().hex,
            public_token=uuid.uuid4().hex,
            password_hash=generate_password_hash("guestpass1"),
            expires_at=_dt.datetime.utcnow() + _dt.timedelta(days=7),
            max_downloads=5,
            created_by_user_id=created_by_id,
            is_active=is_active,
        )
        db.session.add(link)
        db.session.commit()
        return link.id


def _create_request(app, *, owner_id, status="open", recipient_email="alici@bys360.test"):
    import datetime as _dt

    from app.extensions import db
    from app.models.file_center_models import FileRequest

    with app.app_context():
        row = FileRequest(
            owner_user_id=owner_id,
            title="Wave6 Agent1 Dosya Talebi",
            description="test talebi",
            recipient_name="Alıcı Kişi",
            recipient_email=recipient_email,
            token_hash=uuid.uuid4().hex,
            public_token=uuid.uuid4().hex,
            password_hash="irrelevant-hash",
            expires_at=_dt.datetime.utcnow() + _dt.timedelta(days=7),
            max_file_gb=5,
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# DB read helpers
# ---------------------------------------------------------------------------


def _file_snapshot(app, file_id):
    from app.models.file_center_models import FileStorageItem

    with app.app_context():
        item = FileStorageItem.query.get(file_id)
        if item is None:
            return None
        return {"is_deleted": item.is_deleted, "deleted_by_user_id": item.deleted_by_user_id}


def _link_snapshot(app, link_id):
    from app.models.file_center_models import FileShareLink

    with app.app_context():
        link = FileShareLink.query.get(link_id)
        if link is None:
            return None
        return {"is_active": link.is_active, "revoked_by_user_id": link.revoked_by_user_id}


def _request_snapshot(app, request_id):
    from app.models.file_center_models import FileRequest

    with app.app_context():
        row = FileRequest.query.get(request_id)
        if row is None:
            return None
        return {"status": row.status, "closed_at": row.closed_at, "revoked_at": row.revoked_at}


def _link_count(app):
    from app.models.file_center_models import FileShareLink

    with app.app_context():
        return FileShareLink.query.count()


def _download_log_count(app):
    from app.models.file_center_models import FileDownloadLog

    with app.app_context():
        return FileDownloadLog.query.count()


# ---------------------------------------------------------------------------
# 1. file_center_download
# ---------------------------------------------------------------------------


def test_download_owner_success_streams_file_and_logs(app, client):
    owner_id, owner_sicil = _create_owner(app)
    file_id = _create_file(app, owner_id=owner_id)
    _login(client, owner_sicil)

    before_logs = _download_log_count(app)
    resp = client.get(f"/file-center/download/{file_id}", follow_redirects=False)

    assert resp.status_code == 200
    assert resp.data == b"BYS360 wave6 agent1 fixture content"
    assert _download_log_count(app) == before_logs + 1


def test_download_stranger_denied_403_no_download_log(app, client):
    owner_id, _ = _create_owner(app)
    stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=owner_id)
    _login(client, stranger_sicil)

    before_logs = _download_log_count(app)
    resp = client.get(f"/file-center/download/{file_id}", follow_redirects=False)

    assert resp.status_code == 403
    assert _download_log_count(app) == before_logs
    _ = stranger_id


def test_download_admin_override_allowed(app, client):
    owner_id, _ = _create_owner(app)
    _admin_id, admin_sicil = _create_admin(app)
    file_id = _create_file(app, owner_id=owner_id)
    _login(client, admin_sicil)

    resp = client.get(f"/file-center/download/{file_id}", follow_redirects=False)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. file_center_delete
# ---------------------------------------------------------------------------


def test_delete_owner_success_soft_deletes_and_revokes_active_links(app, client):
    owner_id, owner_sicil = _create_owner(app)
    file_id = _create_file(app, owner_id=owner_id)
    link_id = _create_share_link(app, file_id=file_id, created_by_id=owner_id, is_active=True)
    _login(client, owner_sicil)

    resp = client.post(f"/file-center/delete/{file_id}", follow_redirects=False)

    assert resp.status_code == 302
    snap = _file_snapshot(app, file_id)
    assert snap["is_deleted"] is True
    assert snap["deleted_by_user_id"] == owner_id
    link_snap = _link_snapshot(app, link_id)
    assert link_snap["is_active"] is False, "soft-delete must revoke active guest links as a real side effect"


def test_delete_stranger_denied_403_zero_mutation(app, client):
    owner_id, _ = _create_owner(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=owner_id)
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/delete/{file_id}", follow_redirects=False)

    assert resp.status_code == 403
    snap = _file_snapshot(app, file_id)
    assert snap["is_deleted"] is False, "denied delete must not mutate the file row"


# ---------------------------------------------------------------------------
# 3. file_center_create_guest_link
# ---------------------------------------------------------------------------


def test_create_guest_link_owner_success_creates_real_row(app, client):
    owner_id, owner_sicil = _create_owner(app)
    file_id = _create_file(app, owner_id=owner_id)
    _login(client, owner_sicil)

    before = _link_count(app)
    resp = client.post(
        f"/file-center/share/{file_id}",
        data={"password": "guestpass1", "days": "5", "max_downloads": "3"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _link_count(app) == before + 1


def test_create_guest_link_stranger_denied_403_zero_row(app, client):
    owner_id, _ = _create_owner(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=owner_id)
    _login(client, stranger_sicil)

    before = _link_count(app)
    resp = client.post(
        f"/file-center/share/{file_id}",
        data={"password": "guestpass1", "days": "5", "max_downloads": "3"},
        follow_redirects=False,
    )

    assert resp.status_code == 403
    assert _link_count(app) == before, "denied guest-link creation must write zero rows"


# ---------------------------------------------------------------------------
# 4. file_center_revoke_guest_link
# ---------------------------------------------------------------------------


def test_revoke_guest_link_owner_success_deactivates(app, client):
    owner_id, owner_sicil = _create_owner(app)
    file_id = _create_file(app, owner_id=owner_id)
    link_id = _create_share_link(app, file_id=file_id, created_by_id=owner_id, is_active=True)
    _login(client, owner_sicil)

    resp = client.post(f"/file-center/share/{link_id}/revoke", follow_redirects=False)

    assert resp.status_code == 302
    snap = _link_snapshot(app, link_id)
    assert snap["is_active"] is False
    assert snap["revoked_by_user_id"] == owner_id


def test_revoke_guest_link_stranger_denied_403_link_stays_active(app, client):
    owner_id, _ = _create_owner(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=owner_id)
    link_id = _create_share_link(app, file_id=file_id, created_by_id=owner_id, is_active=True)
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/share/{link_id}/revoke", follow_redirects=False)

    assert resp.status_code == 403
    snap = _link_snapshot(app, link_id)
    assert snap["is_active"] is True, "denied revoke must leave the guest link active"


# ---------------------------------------------------------------------------
# 5. file_center_close_request / file_center_revoke_request
# ---------------------------------------------------------------------------


def test_close_request_owner_success_sets_closed_status(app, client):
    owner_id, owner_sicil = _create_owner(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, owner_sicil)

    resp = client.post(f"/file-center/requests/{request_id}/close", follow_redirects=False)

    assert resp.status_code == 302
    snap = _request_snapshot(app, request_id)
    assert snap["status"] == "closed"
    assert snap["closed_at"] is not None


def test_close_request_stranger_denied_403_zero_mutation(app, client):
    owner_id, _ = _create_owner(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/requests/{request_id}/close", follow_redirects=False)

    assert resp.status_code == 403
    snap = _request_snapshot(app, request_id)
    assert snap["status"] == "open", "denied close must not mutate request status"


def test_revoke_request_owner_success_sets_revoked_status(app, client):
    owner_id, owner_sicil = _create_owner(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, owner_sicil)

    resp = client.post(f"/file-center/requests/{request_id}/revoke", follow_redirects=False)

    assert resp.status_code == 302
    snap = _request_snapshot(app, request_id)
    assert snap["status"] == "revoked"
    assert snap["revoked_at"] is not None


def test_revoke_request_stranger_denied_403_zero_mutation(app, client):
    owner_id, _ = _create_owner(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/requests/{request_id}/revoke", follow_redirects=False)

    assert resp.status_code == 403
    snap = _request_snapshot(app, request_id)
    assert snap["status"] == "open", "denied revoke must not mutate request status"


# ---------------------------------------------------------------------------
# 6. file_center_request_message
# ---------------------------------------------------------------------------


def test_request_message_owner_success_returns_text(app, client):
    owner_id, owner_sicil = _create_owner(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, owner_sicil)

    resp = client.get(f"/file-center/requests/{request_id}/message.txt", follow_redirects=False)

    assert resp.status_code == 200
    assert b"Wave6 Agent1 Dosya Talebi" in resp.data


def test_request_message_stranger_denied_403(app, client):
    owner_id, _ = _create_owner(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, stranger_sicil)

    resp = client.get(f"/file-center/requests/{request_id}/message.txt", follow_redirects=False)

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 7. file_center_prepare_request_reminder -- open/not-open state boundary
# ---------------------------------------------------------------------------


def test_reminder_owner_success_when_open(app, client):
    owner_id, owner_sicil = _create_owner(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, owner_sicil)

    resp = client.post(f"/file-center/requests/{request_id}/reminder", follow_redirects=False)
    assert resp.status_code == 302


def test_reminder_denied_when_request_closed(app, client):
    owner_id, owner_sicil = _create_owner(app)
    request_id = _create_request(app, owner_id=owner_id, status="closed")
    _login(client, owner_sicil)

    resp = client.post(f"/file-center/requests/{request_id}/reminder", follow_redirects=False)

    assert resp.status_code == 302
    with client.session_transaction() as sess:
        flashes = [msg for _cat, msg in sess.get("_flashes", [])]
    assert any("Kapalı veya iptal edilmiş" in msg for msg in flashes)


def test_reminder_stranger_denied_403(app, client):
    owner_id, _ = _create_owner(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    request_id = _create_request(app, owner_id=owner_id, status="open")
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/requests/{request_id}/reminder", follow_redirects=False)
    assert resp.status_code == 403
