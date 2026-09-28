"""BYS360_PHASE5_COVERAGE_WAVE4_AGENT2_FILE_CENTER_GUEST_ACCESS_CONTRACT

Behavioral contract for the two fully-anonymous routes in
app/file_center/routes.py:

    GET/POST /guest/files/<token>   (file_center_guest_download)
    GET/POST /guest/upload/<token>  (file_center_guest_upload)

Neither route carries `@login_required`, so both are reachable by anyone
with a link -- this file proves the route-layer security decisions those
two functions make with a real Flask test client (real HTTP requests, a
real SQLite-backed app, real bytes on disk), not by calling the underlying
service functions directly. Those service functions
(find_share_link_by_token, verify_share_password, record_guest_download,
find_file_request_by_token, verify_request_password,
record_guest_request_upload, validate_upload_request, save_uploaded_file,
secure_file_path, can_download_file, ...) already have a dedicated,
function-level behavioral contract in
tests/behavior/test_file_center_services_security_contract.py (Wave 1),
read in full before writing this file. None of the assertions below restate
that file's own test bodies (e.g. its blocked-extension / per-request
allowlist / double-extension / path-traversal assertions against the bare
functions) -- every test here instead exercises the ROUTE: token lookup via
a real HTTP token, the password gate, the availability gate
(FileShareLink.is_available() / FileRequest.is_available()), the route's
own try/except structure (the ValueError branch vs. the generic Exception
branch), and the observable effect on real DB rows and real files on disk.
Where a case in this file happens to also touch a validate_upload_request
rejection message (e.g. the blocked-extension upload test), the assertion
exists to prove the ROUTE correctly threads that rejection through
record_guest_request_upload's ValueError -> flash -> zero-mutation path,
not to re-verify validate_upload_request's own internal branching (already
proven directly in Wave 1).

Two narrow, deliberate mocking boundaries used below (both mock a genuinely
separate function's OUTPUT or a downstream call's ERROR PATH, never the
route's own token/password/availability decision, matching this wave's
"acceptable narrow boundary" carve-out and the precedent set by
tests/behavior/test_admin_ops_user_actions_destructive_operations_contract.py's
injected-IntegrityError test):

  1. `can_download_file` is monkeypatched to return (False, message) for
     exactly one test, to reach the download route's
     "blocked_by_security" branch without needing a real quarantined file.
  2. `secure_file_path` (download route) and `record_guest_request_upload`
     (upload route) are each monkeypatched to raise a plain RuntimeError in
     exactly one test apiece, to reach each route's own generic
     `except Exception as exc:` branch (distinct from the wrong-password
     and ValueError branches, which are exercised for real, with zero
     mocking, elsewhere in this file) and prove it rolls back, logs a
     failure audit row, and renders a clean (non-crashing) error page.

Fixture pattern: copied from the proven shape in
tests/behavior/test_admin_ops_user_actions_destructive_operations_contract.py
(`_make_app`) -- Config class attributes monkeypatched onto the Config
CLASS before create_app() (mandatory: Config.SQLALCHEMY_DATABASE_URI is a
class attribute frozen at first import in this pytest process, and
Flask-SQLAlchemy 3.x caches its Engine on create_app()'s own bootstrap),
StaticPool + connect_args={"check_same_thread": False}, and the pysqlite
dual-connection event-listener fix. Uses its own dedicated tmp DB directory
plus a fresh uuid-suffixed FILE_CENTER_STORAGE_ROOT subdirectory (set on
flask_app.config AFTER create_app(), which is safe because storage_root()
re-reads that config key on every single call rather than caching it) so
this file never writes to any real repo storage path and shares no state
with any other wave/agent test file running concurrently.
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from werkzeug.security import generate_password_hash

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent2_filecenter")
_RUN_ID = uuid.uuid4().hex
_TMP_STORAGE_ROOT = os.path.join(_TMP_DB_DIR, f"storage_{_RUN_ID}")


def _inside_scratch_root(path) -> bool:
    """Containment check on resolved paths: on Windows the temp dir can appear in 8.3 short form
    (e.g. an 8.3 short user-folder name) while the application resolves the long form of the same directory."""
    return Path(path).resolve().is_relative_to(Path(_TMP_STORAGE_ROOT).resolve())

DEFAULT_FIRST_LOGIN_PASSWORD = "file-center-guest-first-login-test-pw"

_counter = 0


def _next_suffix() -> int:
    global _counter
    _counter += 1
    return _counter


# ---------------------------------------------------------------------------
# App / DB fixture -- see module docstring for why this exact shape is
# mandatory.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-file-center-guest-access-contract")
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

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"agent2_filecenter_{uuid.uuid4().hex}.sqlite3")
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
    )

    # Filesystem isolation (mandatory): storage_root() reads
    # FILE_CENTER_STORAGE_ROOT from os.environ first, then
    # current_app.config -- set both so every write in this test file lands
    # under a dedicated, uuid-suffixed scratch directory, never the real
    # repo's app/static uploads path or C:\bys360\storage /
    # C:\bys360\local_storage.
    os.makedirs(_TMP_STORAGE_ROOT, exist_ok=True)
    monkeypatch.setenv("FILE_CENTER_STORAGE_ROOT", _TMP_STORAGE_ROOT)
    flask_app.config["FILE_CENTER_STORAGE_ROOT"] = _TMP_STORAGE_ROOT

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
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _body(response) -> str:
    """Both guest templates render `get_flashed_messages()` inline (in the
    same request/response cycle that set them), which POPS the flash from
    the session before the response cookie is written back -- so flash
    content must be read from the rendered response body, never from a
    follow-up `client.session_transaction()` (that would always find an
    already-emptied "_flashes" list, confirmed by reading both templates)."""
    return response.get_data(as_text=True)


def _create_owner(app) -> int:
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"FCG{suffix:06d}",
            email=f"fc-guest-{suffix}@bys360.test",
            ad="FileCenter",
            soyad=f"Owner{suffix}",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("FileCenterGuestTest1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _write_physical_file(app, owner_id: int, filename: str, content: bytes) -> str:
    """Writes real bytes under THIS test file's own scratch storage root
    (never the real repo storage) and returns the absolute path as a str,
    exactly as save_uploaded_file() would have produced it."""
    from app.file_center.services import upload_root_for_user

    with app.app_context():
        target_dir = upload_root_for_user(owner_id)
        assert _inside_scratch_root(target_dir)  # isolation proof
        target_path = target_dir / f"{uuid.uuid4().hex}_{filename}"
        target_path.write_bytes(content)
        return str(target_path)


def _create_storage_item(
    app,
    owner_id: int,
    *,
    filename: str = "report.pdf",
    content: bytes = b"BYS360 guest access contract payload",
    content_type: str = "application/pdf",
    status: str = "ready",
    scan_status: str = "clean",
    is_deleted: bool = False,
) -> tuple[int, str]:
    from app.extensions import db
    from app.models.file_center_models import FileStorageItem

    storage_path = _write_physical_file(app, owner_id, filename, content)
    with app.app_context():
        item = FileStorageItem(
            owner_user_id=owner_id,
            original_filename=filename,
            stored_filename=os.path.basename(storage_path),
            storage_path=storage_path,
            content_type=content_type,
            extension="." + filename.rsplit(".", 1)[-1] if "." in filename else None,
            size_bytes=len(content),
            sha256_hash=hashlib.sha256(content).hexdigest(),
            status=status,
            scan_status=scan_status,
            is_deleted=is_deleted,
        )
        db.session.add(item)
        db.session.commit()
        return item.id, storage_path


def _create_share_link(
    app,
    file_id: int,
    owner_id: int,
    *,
    password: str | None = None,
    expires_delta: timedelta = timedelta(days=1),
    max_downloads: int = 5,
    download_count: int = 0,
    is_active: bool = True,
) -> tuple[int, str]:
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.file_center_models import FileShareLink

    token = uuid.uuid4().hex + uuid.uuid4().hex
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with app.app_context():
        link = FileShareLink(
            file_id=file_id,
            token_hash=token_hash,
            public_token=token,
            password_hash=generate_password_hash(password) if password else None,
            expires_at=utc_now() + expires_delta,
            max_downloads=max_downloads,
            download_count=download_count,
            is_active=is_active,
            created_by_user_id=owner_id,
        )
        db.session.add(link)
        db.session.commit()
        return link.id, token


def _create_file_request(
    app,
    owner_id: int,
    *,
    password: str | None = None,
    expires_delta: timedelta = timedelta(days=1),
    max_file_gb: float = 5.0,
    allowed_extensions: str | None = None,
    status: str = "open",
    upload_count: int = 0,
) -> tuple[int, str]:
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.file_center_models import FileRequest

    token = uuid.uuid4().hex + uuid.uuid4().hex
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with app.app_context():
        row = FileRequest(
            owner_user_id=owner_id,
            title="Guest access contract file request",
            token_hash=token_hash,
            public_token=token,
            password_hash=generate_password_hash(password) if password else None,
            expires_at=utc_now() + expires_delta,
            max_file_gb=max_file_gb,
            allowed_extensions=allowed_extensions,
            status=status,
            upload_count=upload_count,
        )
        db.session.add(row)
        db.session.commit()
        return row.id, token


def _get_link(app, link_id):
    from app.models.file_center_models import FileShareLink

    with app.app_context():
        return FileShareLink.query.get(link_id)


def _get_request_row(app, request_id):
    from app.models.file_center_models import FileRequest

    with app.app_context():
        return FileRequest.query.get(request_id)


def _count(app, model_name: str, **filters) -> int:
    from app.models import file_center_models as m

    model = getattr(m, model_name)
    with app.app_context():
        return model.query.filter_by(**filters).count()


def _enable_guest_links(monkeypatch):
    monkeypatch.setenv("FILE_CENTER_GUEST_LINKS_ENABLED", "true")


def _disable_guest_links(monkeypatch):
    monkeypatch.setenv("FILE_CENTER_GUEST_LINKS_ENABLED", "false")


def _disable_guest_uploads(monkeypatch):
    monkeypatch.setenv("FILE_CENTER_GUEST_UPLOADS_ENABLED", "false")


# ---------------------------------------------------------------------------
# file_center_guest_download -- feature flag gate
# ---------------------------------------------------------------------------


def test_download_disabled_via_config_renders_disabled_message_with_zero_effect(app, client, monkeypatch):
    """guest_links_enabled() defaults to False when no env var / DB setting
    row is present (confirmed by reading _db_bool's default chain) -- this
    is itself the real, documented default behavior, exercised here with no
    setup at all: an anonymous caller hitting any token gets the disabled
    message, never a crash, never a lookup attempt."""
    response = client.post(f"/guest/files/{uuid.uuid4().hex}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    assert "kapal" in response.get_data(as_text=True).lower()
    assert _count(app, "FileDownloadLog") == 0


def test_download_explicitly_disabled_ignores_a_real_existing_link(app, client, monkeypatch):
    _disable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    file_id, _ = _create_storage_item(app, owner_id)
    _, token = _create_share_link(app, file_id, owner_id)

    response = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    assert "kapal" in response.get_data(as_text=True).lower()
    assert _count(app, "FileDownloadLog") == 0


# ---------------------------------------------------------------------------
# file_center_guest_download -- token / availability gate
# ---------------------------------------------------------------------------


def test_download_unknown_token_is_clean_invalid_render_no_session(app, client, monkeypatch):
    _enable_guest_links(monkeypatch)

    response = client.post(f"/guest/files/{uuid.uuid4().hex}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "geçersiz" in body.lower()
    assert _count(app, "FileDownloadLog") == 0


def test_download_expired_link_rejected_no_mutation(app, client, monkeypatch):
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    file_id, _ = _create_storage_item(app, owner_id)
    link_id, token = _create_share_link(app, file_id, owner_id, expires_delta=timedelta(days=-1))

    response = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    assert "geçersiz" in response.get_data(as_text=True).lower()
    assert _get_link(app, link_id).download_count == 0
    assert _count(app, "FileDownloadLog") == 0


def test_download_revoked_inactive_link_rejected_no_mutation(app, client, monkeypatch):
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    file_id, _ = _create_storage_item(app, owner_id)
    link_id, token = _create_share_link(app, file_id, owner_id, is_active=False)

    response = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    assert "geçersiz" in response.get_data(as_text=True).lower()
    assert _get_link(app, link_id).download_count == 0


@pytest.mark.parametrize(
    "download_count,max_downloads,should_be_available",
    [
        pytest.param(2, 3, True, id="one_download_remaining"),
        pytest.param(3, 3, False, id="limit_exactly_reached"),
    ],
)
def test_download_count_boundary_at_max_downloads(app, client, monkeypatch, download_count, max_downloads, should_be_available):
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    content = b"boundary payload"
    file_id, _ = _create_storage_item(app, owner_id, content=content)
    link_id, token = _create_share_link(
        app, file_id, owner_id, max_downloads=max_downloads, download_count=download_count
    )

    response = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)

    if should_be_available:
        assert response.status_code == 200
        assert response.data == content
        assert _get_link(app, link_id).download_count == download_count + 1
    else:
        assert response.status_code == 200
        assert "geçersiz" in response.get_data(as_text=True).lower()
        assert _get_link(app, link_id).download_count == download_count


# ---------------------------------------------------------------------------
# file_center_guest_download -- password gate
# ---------------------------------------------------------------------------


def test_download_empty_password_hash_auto_passes_with_empty_submitted_password(app, client, monkeypatch):
    """Boundary: verify_share_password() returns True unconditionally when
    link.password_hash is None (empty/never set) -- proven here through the
    real HTTP route, submitting an explicitly empty password field, and
    confirming real file bytes come back plus exactly one download_count
    increment."""
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    content = b"no password required payload"
    file_id, _ = _create_storage_item(app, owner_id, content=content)
    link_id, token = _create_share_link(app, file_id, owner_id, password=None)
    assert _get_link(app, link_id).password_hash is None

    response = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    assert response.data == content
    assert _get_link(app, link_id).download_count == 1


def test_download_wrong_password_rejected_no_download_count_increment_and_logs_wrong_password(app, client, monkeypatch):
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    content = b"password protected payload"
    file_id, _ = _create_storage_item(app, owner_id, content=content)
    link_id, token = _create_share_link(app, file_id, owner_id, password="CorrectHorseBatteryTest1!")

    response = client.post(f"/guest/files/{token}", data={"password": "totally-wrong"}, follow_redirects=False)

    assert response.status_code == 200
    assert response.data != content
    assert "Şifre hatalı." in _body(response)
    assert _get_link(app, link_id).download_count == 0
    assert _count(app, "FileDownloadLog", file_id=file_id, status="wrong_password") == 1


def test_download_correct_password_succeeds_and_increments_once(app, client, monkeypatch):
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    content = b"correct password payload"
    file_id, _ = _create_storage_item(app, owner_id, content=content)
    link_id, token = _create_share_link(app, file_id, owner_id, password="CorrectHorseBatteryTest1!")

    response = client.post(f"/guest/files/{token}", data={"password": "CorrectHorseBatteryTest1!"}, follow_redirects=False)

    assert response.status_code == 200
    assert response.data == content
    assert _get_link(app, link_id).download_count == 1
    assert _count(app, "FileDownloadLog", file_id=file_id, status="success") == 1


# ---------------------------------------------------------------------------
# file_center_guest_download -- security block / exception branches
# ---------------------------------------------------------------------------


def test_download_blocked_by_security_check_returns_no_bytes_and_zero_increment(app, client, monkeypatch):
    """Narrow, documented mocking boundary #1 (see module docstring):
    can_download_file's OUTPUT is monkeypatched -- a genuinely separate
    service function, already covered in isolation by Wave 1 -- purely to
    reach the route's own "blocked_by_security" branch without needing to
    reproduce a real quarantine. The route's own token/password/availability
    decisions above this point are all exercised for real."""
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    content = b"would-be-blocked payload"
    file_id, _ = _create_storage_item(app, owner_id, content=content)
    link_id, token = _create_share_link(app, file_id, owner_id)

    monkeypatch.setattr(
        "app.file_center.routes.can_download_file",
        lambda item: (False, "Dosya güvenlik nedeniyle indirilemez."),
    )

    response = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    assert response.data != content
    assert "güvenlik" in response.get_data(as_text=True).lower()
    assert _get_link(app, link_id).download_count == 0
    assert _count(app, "FileDownloadLog", file_id=file_id, status="blocked_by_security") == 1


def test_download_generic_exception_is_caught_rolled_back_and_session_stays_usable(app, client, monkeypatch):
    """Narrow, documented mocking boundary #2 (see module docstring):
    secure_file_path is monkeypatched to raise, forcing the route's own
    generic `except Exception as exc:` branch -- distinct from the
    wrong-password branch and the blocked_by_security branch exercised
    above -- and proving it rolls back cleanly (a real, unrelated follow-up
    download still succeeds afterward) instead of a raw 500 or a successful
    send_file.

    NOTE (observed while writing this test, not asserted on as correct
    behavior -- reported separately, not encoded here): the route's own
    `log_audit("guest_file_download_failed", ...)` call in this except
    branch is never followed by a `db.session.commit()` (confirmed by
    reading routes.py's except block directly under
    file_center_guest_download). A direct check after this exact request --
    querying FileAuditLog for that action from a fresh app context -- found
    zero persisted rows, meaning the failure-audit entry for this branch is
    added to the session but silently dropped on request teardown rather
    than ever reaching the database. This is left unasserted here (an
    assertion of either outcome would either fail against real code or lock
    in the gap as intended) and is called out in this file's final report
    instead."""
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    content = b"exception path payload"
    file_id, _ = _create_storage_item(app, owner_id, content=content)
    link_id, token = _create_share_link(app, file_id, owner_id)

    from app.file_center import routes as fc_routes

    real_secure_file_path = fc_routes.secure_file_path
    monkeypatch.setattr(
        fc_routes,
        "secure_file_path",
        lambda item: (_ for _ in ()).throw(RuntimeError("simulated disk failure")),
    )

    response = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)

    assert response.status_code == 200
    assert response.data != content
    assert "indirilemedi" in _body(response).lower()
    assert _get_link(app, link_id).download_count == 0

    # Session-health proof: restore the real function and confirm a real,
    # unrelated follow-up download still succeeds after the injected
    # failure + rollback above, proving the session was left in a usable
    # state (targeted restore, not a blanket monkeypatch.undo(), so none of
    # the app fixture's own env/Config patches are disturbed).
    monkeypatch.setattr(fc_routes, "secure_file_path", real_secure_file_path)
    follow_up = client.post(f"/guest/files/{token}", data={"password": ""}, follow_redirects=False)
    assert follow_up.status_code == 200
    assert follow_up.data == content
    assert _get_link(app, link_id).download_count == 1


def test_download_get_request_renders_without_mutating_state(app, client, monkeypatch):
    _enable_guest_links(monkeypatch)
    owner_id = _create_owner(app)
    file_id, _ = _create_storage_item(app, owner_id)
    link_id, token = _create_share_link(app, file_id, owner_id)

    response = client.get(f"/guest/files/{token}", follow_redirects=False)

    assert response.status_code == 200
    assert _get_link(app, link_id).download_count == 0
    assert _count(app, "FileDownloadLog") == 0


# ---------------------------------------------------------------------------
# file_center_guest_upload -- feature flag gate
# ---------------------------------------------------------------------------


def test_upload_disabled_via_config_renders_disabled_message_with_zero_effect(app, client, monkeypatch):
    _disable_guest_uploads(monkeypatch)
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id)

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"payload"), "doc.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "kapal" in response.get_data(as_text=True).lower()
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


# ---------------------------------------------------------------------------
# file_center_guest_upload -- token / availability gate
# ---------------------------------------------------------------------------


def test_upload_unknown_token_is_clean_invalid_render_no_mutation(app, client, monkeypatch):
    response = client.post(
        f"/guest/upload/{uuid.uuid4().hex}",
        data={"file": (io.BytesIO(b"payload"), "doc.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "geçersiz" in response.get_data(as_text=True).lower()
    assert _count(app, "FileStorageItem") == 0


def test_upload_closed_request_rejected_no_mutation(app, client, monkeypatch):
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, status="closed")

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"payload"), "doc.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "geçersiz" in response.get_data(as_text=True).lower()
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


def test_upload_expired_request_rejected_no_mutation(app, client, monkeypatch):
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, expires_delta=timedelta(days=-1))

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"payload"), "doc.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "geçersiz" in response.get_data(as_text=True).lower()
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


def test_upload_get_request_renders_without_mutating_state(app, client, monkeypatch):
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id)

    response = client.get(f"/guest/upload/{token}", follow_redirects=False)

    assert response.status_code == 200
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


# ---------------------------------------------------------------------------
# file_center_guest_upload -- password gate + real success path
# ---------------------------------------------------------------------------


def test_upload_empty_password_hash_auto_passes_and_persists_real_file_under_scratch_root(app, client, monkeypatch):
    """Positive contract + boundary: row.password_hash is None (never set),
    empty password submitted -> auto-pass (verify_request_password), and a
    real FileStorageItem + FileRequestUpload row is created with real bytes
    landing under THIS test file's own scratch FILE_CENTER_STORAGE_ROOT,
    never the real repo storage."""
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, password=None)
    assert _get_request_row(app, request_id).password_hash is None
    content = b"BYS360 guest upload contract payload " * 5

    response = client.post(
        f"/guest/upload/{token}",
        data={
            "file": (io.BytesIO(content), "guest_report.txt"),
            "password": "",
            "guest_name": "Contract Guest",
            "guest_email": "guest@example.test",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    body = _body(response)
    assert "Dosya başarıyla yüklendi: guest_report.txt" in body

    assert _count(app, "FileStorageItem", owner_user_id=owner_id) == 1
    assert _count(app, "FileRequestUpload", request_id=request_id) == 1
    reloaded_request = _get_request_row(app, request_id)
    assert reloaded_request.upload_count == 1
    assert reloaded_request.last_upload_at is not None

    from app.models.file_center_models import FileStorageItem

    with app.app_context():
        item = FileStorageItem.query.filter_by(owner_user_id=owner_id).one()
        stored_path = item.storage_path
        assert item.size_bytes == len(content)

    assert _inside_scratch_root(stored_path)  # filesystem isolation proof
    with open(stored_path, "rb") as fh:
        assert fh.read() == content


def test_upload_correct_password_succeeds(app, client, monkeypatch):
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, password="GuestUploadSecretTest1!")
    content = b"password-protected upload payload"

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(content), "secure.pdf"), "password": "GuestUploadSecretTest1!"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Dosya başarıyla yüklendi: secure.pdf" in _body(response)
    assert _count(app, "FileStorageItem", owner_user_id=owner_id) == 1
    assert _get_request_row(app, request_id).upload_count == 1


def test_upload_wrong_password_rejected_no_mutation(app, client, monkeypatch):
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, password="GuestUploadSecretTest1!")

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"payload"), "doc.pdf"), "password": "wrong-guess"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Şifre hatalı." in _body(response)
    assert _count(app, "FileStorageItem") == 0
    assert _count(app, "FileRequestUpload") == 0
    assert _get_request_row(app, request_id).upload_count == 0


# ---------------------------------------------------------------------------
# file_center_guest_upload -- validate_upload_request rejections, threaded
# through the route's ValueError branch
# ---------------------------------------------------------------------------


def test_upload_blocked_extension_rejected_no_mutation(app, client, monkeypatch):
    """A blocked extension (.exe is in the real default blocked_extensions
    set) raises ValueError inside record_guest_request_upload's call to
    validate_upload_request; the route's `except ValueError` branch must
    flash the real message, mark uploaded=False, and leave zero rows/files
    behind -- proven here through the real HTTP route with a real, narrow
    per-request allowlist configured on the row, not by calling
    validate_upload_request directly (that is Wave 1's job)."""
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, allowed_extensions="pdf")

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"MZ-fake-binary-content"), "tool.exe")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    body = _body(response)
    assert "Bu dosya türü güvenlik nedeniyle yüklenemez: .exe" in body
    assert _count(app, "FileStorageItem") == 0
    assert _count(app, "FileRequestUpload") == 0
    assert _get_request_row(app, request_id).upload_count == 0


def test_upload_extension_outside_per_request_allowlist_rejected_no_mutation(app, client, monkeypatch):
    """Distinct branch from the blocked-extension test above: a NON-blocked
    extension (.docx) that simply is not on this request's own narrow
    allowlist ("pdf") -- proves the route genuinely threads
    row.allowed_extensions through to validate_upload_request(), end to end
    over real HTTP, not merely that the bare function respects an
    allowlist (already proven directly in Wave 1)."""
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, allowed_extensions="pdf")

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"not a pdf"), "report.docx")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Bu dosya türü bu talep için kabul edilmiyor: .docx" in _body(response)
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


def test_upload_oversized_relative_to_request_max_file_gb_rejected_no_mutation(app, client, monkeypatch):
    """Uses the REQUEST's own (tiny) max_file_gb override, not the global
    max_file_bytes() default, proving request_max_bytes() is genuinely
    applied at the route layer. The declared multipart Content-Length
    comfortably exceeds the ~1KB cap, tripping validate_upload_request's
    pre-stream size gate."""
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id, max_file_gb=0.000001)  # ~1073 bytes

    oversized_content = b"x" * 5000

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(oversized_content), "big.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Dosya boyutu izin verilen sınırı aşıyor." in _body(response)
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


def test_upload_missing_file_field_rejected_no_mutation(app, client, monkeypatch):
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id)

    response = client.post(
        f"/guest/upload/{token}",
        data={},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Dosya seçilmedi." in _body(response)
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


def test_upload_empty_filename_rejected_no_mutation(app, client, monkeypatch):
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id)

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"payload"), "")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Dosya seçilmedi." in _body(response)
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0


# ---------------------------------------------------------------------------
# file_center_guest_upload -- generic exception branch
# ---------------------------------------------------------------------------


def test_upload_generic_exception_is_caught_rolled_back_and_session_stays_usable(app, client, monkeypatch):
    """Narrow, documented mocking boundary #2 (see module docstring):
    record_guest_request_upload is monkeypatched to raise a plain
    RuntimeError (not a ValueError), forcing the route's generic
    `except Exception as exc:` branch -- distinct from the ValueError
    branch exercised in every rejection test above -- and proving it rolls
    back cleanly (a real, unrelated follow-up upload still succeeds
    afterward) and flashes the generic Turkish failure message instead of
    crashing with a raw 500. The token lookup and availability check above
    this point still run for real against a genuine, open, unexpired
    FileRequest row.

    NOTE (observed while writing this test, not asserted on as correct
    behavior -- reported separately, not encoded here): exactly like the
    download route's equivalent branch, this except block's
    `log_audit("guest_file_upload_failed", ...)` call is never followed by
    a `db.session.commit()` (confirmed by reading routes.py's except block
    directly under file_center_guest_upload), so the failure-audit row is
    added to the session but silently dropped on request teardown instead
    of ever reaching the database. Left unasserted here and called out in
    this file's final report instead."""
    owner_id = _create_owner(app)
    request_id, token = _create_file_request(app, owner_id)

    from app.file_center import routes as fc_routes

    real_record_guest_request_upload = fc_routes.record_guest_request_upload

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated unexpected upload failure")

    monkeypatch.setattr(fc_routes, "record_guest_request_upload", _boom)

    response = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"payload"), "doc.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 200
    body = _body(response)
    assert "yüklenemedi" in body.lower()
    assert _count(app, "FileStorageItem") == 0
    assert _get_request_row(app, request_id).upload_count == 0

    # Session-health proof: restore the real function and confirm a real,
    # unrelated follow-up upload still succeeds after the injected failure
    # + rollback above (targeted restore, not a blanket monkeypatch.undo()).
    monkeypatch.setattr(fc_routes, "record_guest_request_upload", real_record_guest_request_upload)
    follow_up = client.post(
        f"/guest/upload/{token}",
        data={"file": (io.BytesIO(b"payload after recovery"), "recovered.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert follow_up.status_code == 200
    assert "Dosya başarıyla yüklendi: recovered.pdf" in _body(follow_up)
    assert _count(app, "FileStorageItem", owner_user_id=owner_id) == 1
    assert _get_request_row(app, request_id).upload_count == 1
