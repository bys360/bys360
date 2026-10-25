"""BYS360_COVERAGE_WAVE7_AGENT2_FILE_CENTER_SECURITY_ACTIONS_CONTRACT

Behavioral, route-boundary contract for the approved Wave 7 File Center
security-action scope (app/file_center/routes.py + the exact service
functions these routes call in app/file_center/services.py):

    file_center_security                  GET  /file-center/security
    file_center_security_scan_pending     POST /file-center/security/scan-pending
    file_center_security_scan_file        POST /file-center/security/scan/<id>
    file_center_security_quarantine_file  POST /file-center/security/quarantine/<id>
    file_center_security_release_file     POST /file-center/security/release/<id>
    file_center_security_block_file       POST /file-center/security/block/<id>

Explicitly excluded (covered by earlier waves or reserved for a later
scope): Wave 6 ownership management (_can_manage_file/_can_manage_request),
Wave 5 quota/role-matrix administration, Wave 4 anonymous guest upload/
download, chunk-upload lifecycle, transfers, settings, request creation/
email. Confirmed zero existing test-name overlap for these 6 routes via
`grep -rln "file_center_security_scan_pending\\|...\\|/file-center/security"
tests/` (zero matches) before writing a single test.

Authorization gate under test: `can_manage_file_center_admin(current_user)`
(app/file_center/permissions.py) -- a DIFFERENT function from Wave 6's
`_can_manage_file`/`is_admin_like` ownership gate, so there is zero
authorization-logic overlap with Wave 6's File Center file.

Defect boundary (mechanically confirmed, all NO):
  INTERSECTS_DEFECT_F = NO -- Defect F concerns guest-operation failed-audit
    persistence; this file only exercises authenticated admin actions.
  INTERSECTS_DEFECT_I = NO -- `can_manage_file_center_admin` is a different
    function from `permissions.py::_effective_role_key` (the substring-
    escalation function Defect I is about); this file's manager fixture
    uses role="admin" (the genuine, unambiguous explicit-match path) and
    its stranger fixture uses role="personel" with no admin/yonetici
    substring anywhere in any field, so the distinction is moot either way.
  INTERSECTS_DEFECT_K = NO -- this file never touches role-matrix seeding.
  INTERSECTS_DEFECT_L = NO -- the scan/quarantine/release/block routes each
    wrap their real work in `try/except Exception: safe_db_rollback()`
    exactly like the download/upload routes Defect L concerns, but this
    file only exercises the success path plus the pre-try `get_or_404`
    404 boundary, not a forced internal exception -- see the rollback note
    below for why that specific path is not fabricated here.

Drift-risk boundary (per Wave 7 planning, NOT re-litigated here):
  `permissions.py` separately defines `can_manage_file_center_security`
  (reads the `can_manage_security` matrix field) but the routes above use
  the broader `can_manage_file_center_admin` (reads `can_manage_admin`)
  instead. This file does NOT assert anything about a hypothetical
  security-only role being denied -- it uses exactly two canonical,
  unambiguous identities (a genuine `role="admin"` positive and a genuine
  `role="personel"` negative), so it neither freezes nor resolves that
  open design question.

Rollback note: every route here wraps its work in `try/except Exception:
safe_db_rollback()`, matching the exact pattern already covered honestly
in this repo's other test files (see Wave 6's task-management file for the
same reasoning). Forcing a genuine internal exception here without broad-
mocking the function under test (forbidden by this wave's rules) would
require breaking the real filesystem or DB mid-operation in a way that
is not a realistic, honest reproduction -- so this file instead proves
the DB/filesystem-coherence-after-a-rejected-operation contract via the
`get_or_404` 404 boundary (an unknown file_id) and via the authorization-
denial zero-mutation cases, both of which are real, mechanically provable
"rejected operation leaves state untouched" contracts.

Fixture pattern: this wave's mandatory proven shape, copied from Wave 6's
own tests/behavior/test_file_center_ownership_management_contract.py
(Config class-attribute patch BEFORE create_app(), StaticPool + pysqlite
isolation_level=None + explicit BEGIN event listener, real `/login` POST,
real file on disk via upload_root_for_user, dedicated
FILE_CENTER_STORAGE_ROOT). Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_wave7_agent2) and its own dedicated storage root so
it shares no state with any other wave/agent running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave7_agent2")
_TMP_STORAGE_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave7_agent2_storage")

DEFAULT_PASSWORD = "Wave7Agent2SecurityActionsTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "wave7-agent2-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-wave7-agent2-contract")
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

    storage_root = os.path.join(_TMP_STORAGE_DIR, uuid.uuid4().hex)
    os.makedirs(storage_root, exist_ok=True)
    monkeypatch.setenv("FILE_CENTER_STORAGE_ROOT", storage_root)

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"wave7_agent2_{uuid.uuid4().hex}.sqlite3")
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


def _create_user(app, *, role):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"W7A2{n:06d}",
            email=f"wave7-agent2-{n}@bys360.test",
            ad="Wave7",
            soyad=f"Security{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id, user.sicil_no


def _create_manager(app):
    return _create_user(app, role="admin")


def _create_stranger(app):
    return _create_user(app, role="personel")


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


def _write_real_file(app, owner_id, content: bytes = b"BYS360 wave7 agent2 fixture content"):
    from app.file_center.services import upload_root_for_user

    with app.app_context():
        root = upload_root_for_user(owner_id)
        stored_name = f"{uuid.uuid4().hex}.txt"
        path = root / stored_name
        path.write_bytes(content)
        return str(path.resolve())


def _create_file(app, *, owner_id, scan_status="pending", status="ready"):
    from app.extensions import db
    from app.models.file_center_models import FileStorageItem

    storage_path = _write_real_file(app, owner_id)
    with app.app_context():
        item = FileStorageItem(
            owner_user_id=owner_id,
            original_filename="temiz_dosya.txt",
            stored_filename=os.path.basename(storage_path),
            storage_path=storage_path,
            content_type="text/plain",
            extension="txt",
            size_bytes=len(b"BYS360 wave7 agent2 fixture content"),
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=status,
            scan_status=scan_status,
            is_deleted=False,
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


# ---------------------------------------------------------------------------
# DB / filesystem read helpers
# ---------------------------------------------------------------------------


def _file_snapshot(app, file_id):
    from app.models.file_center_models import FileStorageItem

    with app.app_context():
        item = FileStorageItem.query.get(file_id)
        if item is None:
            return None
        return {"scan_status": item.scan_status, "status": item.status, "storage_path": item.storage_path}


def _scan_count(app, file_id=None):
    from app.models.file_center_models import FileSecurityScan

    with app.app_context():
        q = FileSecurityScan.query
        if file_id is not None:
            q = q.filter_by(file_id=file_id)
        return q.count()


def _latest_scan_message(app, file_id):
    from app.models.file_center_models import FileSecurityScan

    with app.app_context():
        row = FileSecurityScan.query.filter_by(file_id=file_id).order_by(FileSecurityScan.id.desc()).first()
        return row.result_message if row else None


def _audit_count(app, action=None):
    from app.models.file_center_models import FileAuditLog

    with app.app_context():
        q = FileAuditLog.query
        if action:
            q = q.filter_by(action=action)
        return q.count()


def _link_is_active(app, link_id):
    from app.models.file_center_models import FileShareLink

    with app.app_context():
        return FileShareLink.query.get(link_id).is_active


def _file_exists_on_disk(path: str) -> bool:
    from pathlib import Path

    return Path(path).is_file()


# ---------------------------------------------------------------------------
# 1. file_center_security -- dashboard access
# ---------------------------------------------------------------------------


def test_security_dashboard_manager_access_allowed(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    resp = client.get("/file-center/security", follow_redirects=False)
    assert resp.status_code == 200


def test_security_dashboard_denied_for_non_manager(app, client):
    _stranger_id, stranger_sicil = _create_stranger(app)
    _login(client, stranger_sicil)

    resp = client.get("/file-center/security", follow_redirects=False)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 2. file_center_security_scan_pending -- selective processing of eligible items
# ---------------------------------------------------------------------------


def test_scan_pending_manager_success_scans_only_eligible_pending_files(app, client):
    manager_id, manager_sicil = _create_manager(app)
    pending_a = _create_file(app, owner_id=manager_id, scan_status="pending")
    pending_b = _create_file(app, owner_id=manager_id, scan_status="pending")
    already_clean = _create_file(app, owner_id=manager_id, scan_status="clean")
    _login(client, manager_sicil)

    before_clean_scan_count = _scan_count(app, already_clean)
    resp = client.post("/file-center/security/scan-pending", follow_redirects=False)

    assert resp.status_code == 302
    assert _file_snapshot(app, pending_a)["scan_status"] == "clean"
    assert _file_snapshot(app, pending_b)["scan_status"] == "clean"
    assert _scan_count(app, already_clean) == before_clean_scan_count, "an already-clean file must not be re-scanned by the pending sweep"


def test_scan_pending_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    pending_file = _create_file(app, owner_id=manager_id, scan_status="pending")
    _login(client, stranger_sicil)

    resp = client.post("/file-center/security/scan-pending", follow_redirects=False)

    assert resp.status_code == 403
    assert _file_snapshot(app, pending_file)["scan_status"] == "pending"
    assert _scan_count(app, pending_file) == 0


# ---------------------------------------------------------------------------
# 3. file_center_security_scan_file -- single-file scan persistence
# ---------------------------------------------------------------------------


def test_scan_file_manager_success_persists_clean_state(app, client):
    manager_id, manager_sicil = _create_manager(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="pending")
    _login(client, manager_sicil)

    before = _scan_count(app, file_id)
    resp = client.post(f"/file-center/security/scan/{file_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _file_snapshot(app, file_id)["scan_status"] == "clean"
    assert _scan_count(app, file_id) == before + 1


def test_scan_file_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="pending")
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/security/scan/{file_id}", follow_redirects=False)

    assert resp.status_code == 403
    assert _file_snapshot(app, file_id)["scan_status"] == "pending"
    assert _scan_count(app, file_id) == 0


def test_scan_file_unknown_id_returns_404(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    resp = client.post("/file-center/security/scan/999999", follow_redirects=False)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. file_center_security_quarantine_file -- state + real filesystem move + audit + link cascade
# ---------------------------------------------------------------------------


def test_quarantine_manager_success_moves_file_and_revokes_active_links(app, client):
    manager_id, manager_sicil = _create_manager(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="clean")
    original_path = _file_snapshot(app, file_id)["storage_path"]
    link_id = _create_share_link(app, file_id=file_id, created_by_id=manager_id, is_active=True)
    _login(client, manager_sicil)

    before_audit = _audit_count(app, "file_quarantined")
    resp = client.post(f"/file-center/security/quarantine/{file_id}", data={"reason": "Wave7 manuel inceleme"}, follow_redirects=False)

    assert resp.status_code == 302
    snap = _file_snapshot(app, file_id)
    assert snap["scan_status"] == "quarantined"
    new_path = snap["storage_path"]
    assert new_path != original_path, "quarantine must physically move the file to the quarantine area"
    assert not _file_exists_on_disk(original_path)
    assert _file_exists_on_disk(new_path)
    assert "quarantine" in new_path.replace("\\", "/").lower()
    assert _link_is_active(app, link_id) is False, "quarantine must revoke active guest links as a real side effect"
    assert _audit_count(app, "file_quarantined") == before_audit + 1


def test_quarantine_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="clean")
    original_path = _file_snapshot(app, file_id)["storage_path"]
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/security/quarantine/{file_id}", data={"reason": "deneme"}, follow_redirects=False)

    assert resp.status_code == 403
    snap = _file_snapshot(app, file_id)
    assert snap["scan_status"] == "clean"
    assert snap["storage_path"] == original_path
    assert _file_exists_on_disk(original_path)


def test_quarantine_reason_text_is_stored_but_does_not_alter_outcome(app, client):
    manager_id, manager_sicil = _create_manager(app)
    file_a = _create_file(app, owner_id=manager_id, scan_status="clean")
    file_b = _create_file(app, owner_id=manager_id, scan_status="clean")
    _login(client, manager_sicil)

    reason_a = "Wave7 sebep metni A"
    reason_b = "Wave7 tamamen farklı sebep metni B"
    resp_a = client.post(f"/file-center/security/quarantine/{file_a}", data={"reason": reason_a}, follow_redirects=False)
    resp_b = client.post(f"/file-center/security/quarantine/{file_b}", data={"reason": reason_b}, follow_redirects=False)

    assert resp_a.status_code == 302
    assert resp_b.status_code == 302
    assert _file_snapshot(app, file_a)["scan_status"] == "quarantined"
    assert _file_snapshot(app, file_b)["scan_status"] == "quarantined"
    assert _latest_scan_message(app, file_a) == reason_a
    assert _latest_scan_message(app, file_b) == reason_b


# ---------------------------------------------------------------------------
# 5. file_center_security_release_file -- restores quarantined file to clean
# ---------------------------------------------------------------------------


def test_release_manager_success_restores_clean_state(app, client):
    manager_id, manager_sicil = _create_manager(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="clean")
    _login(client, manager_sicil)

    client.post(f"/file-center/security/quarantine/{file_id}", data={"reason": "önce karantina"}, follow_redirects=False)
    quarantined_path = _file_snapshot(app, file_id)["storage_path"]
    assert _file_snapshot(app, file_id)["scan_status"] == "quarantined"

    resp = client.post(f"/file-center/security/release/{file_id}", data={"reason": "inceleme tamam"}, follow_redirects=False)

    assert resp.status_code == 302
    snap = _file_snapshot(app, file_id)
    assert snap["scan_status"] == "clean"
    assert _file_exists_on_disk(snap["storage_path"])
    assert snap["storage_path"] != quarantined_path


def test_release_denied_for_non_manager_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="clean")
    _login(client, manager_sicil)
    client.post(f"/file-center/security/quarantine/{file_id}", data={"reason": "önce karantina"}, follow_redirects=False)
    quarantined_snap = _file_snapshot(app, file_id)

    client.get("/logout", follow_redirects=False)
    _login(client, stranger_sicil)
    resp = client.post(f"/file-center/security/release/{file_id}", data={"reason": "deneme"}, follow_redirects=False)

    assert resp.status_code == 403
    assert _file_snapshot(app, file_id) == quarantined_snap


# ---------------------------------------------------------------------------
# 6. file_center_security_block_file -- state + filesystem move + link cascade
# ---------------------------------------------------------------------------


def test_block_manager_success_moves_file_and_revokes_active_links(app, client):
    manager_id, manager_sicil = _create_manager(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="clean")
    original_path = _file_snapshot(app, file_id)["storage_path"]
    link_id = _create_share_link(app, file_id=file_id, created_by_id=manager_id, is_active=True)
    _login(client, manager_sicil)

    before_audit = _audit_count(app, "file_blocked")
    resp = client.post(f"/file-center/security/block/{file_id}", data={"reason": "Wave7 engelleme"}, follow_redirects=False)

    assert resp.status_code == 302
    snap = _file_snapshot(app, file_id)
    assert snap["scan_status"] == "blocked"
    assert snap["storage_path"] != original_path
    assert not _file_exists_on_disk(original_path)
    assert _file_exists_on_disk(snap["storage_path"])
    assert _link_is_active(app, link_id) is False
    assert _audit_count(app, "file_blocked") == before_audit + 1


def test_block_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _stranger_id, stranger_sicil = _create_stranger(app)
    file_id = _create_file(app, owner_id=manager_id, scan_status="clean")
    original_path = _file_snapshot(app, file_id)["storage_path"]
    _login(client, stranger_sicil)

    resp = client.post(f"/file-center/security/block/{file_id}", data={"reason": "deneme"}, follow_redirects=False)

    assert resp.status_code == 403
    snap = _file_snapshot(app, file_id)
    assert snap["scan_status"] == "clean"
    assert snap["storage_path"] == original_path
    assert _file_exists_on_disk(original_path)


def test_block_unknown_id_returns_404(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    resp = client.post("/file-center/security/block/999999", data={"reason": "deneme"}, follow_redirects=False)
    assert resp.status_code == 404
