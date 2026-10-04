"""Phase 13B security closure -- setup-admin bootstrap negatives (SEC-001).

The prior brutal audit found ``/setup-admin`` publicly reachable whenever
``users`` is empty, with no environment gate at all -- reachable even in a
production-shaped app. The fix adds a fail-closed environment gate
(``_setup_admin_route_permitted`` in app/main_handlers/auth_handlers.py):
closed by default whenever ``APP_ENV`` is production/staging unless the
operator explicitly opts in via ``SETUP_ADMIN_ENABLED``.
"""
from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, text

_PHASE13B_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "phase13b" / "test_dbs"

# Apps built by _make_app during the current test; the autouse fixture below
# disposes their engines and deletes their SQLite files afterwards.
_CREATED_APPS: list[tuple[Any, Path]] = []


def _make_app(monkeypatch, *, app_env: str = "testing", setup_admin_enabled: bool | None = None):
    # BYS360_P13B_TEST_APP_ENV: config.Config.APP_ENV (and everything derived
    # from it, e.g. SESSION_COOKIE_SECURE) is a class attribute computed once
    # from os.environ the FIRST time the `config` module is imported in this
    # process, so a later monkeypatch.setenv("APP_ENV", ...) has no effect on
    # an already-imported process (the value is frozen). The app is therefore
    # always built under the safe/permissive "testing" environment (which
    # boots without needing a full production-grade config), and the specific
    # APP_ENV value under test is applied directly to the created app's own
    # (mutable, per-instance) config dict -- exactly what
    # `_setup_admin_route_permitted()` reads at request time.
    _PHASE13B_TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _PHASE13B_TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase13b-setup-admin-negatives")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    # Config froze its database URI when config.py was first imported, so the
    # DATABASE_URL above came too late; pin it so this app uses only its own file.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    _CREATED_APPS.append((app, db_path))
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
        APP_ENV=app_env,
    )
    if setup_admin_enabled is not None:
        app.config["SETUP_ADMIN_ENABLED"] = setup_admin_enabled

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def _dispose_created_apps():
    from app.extensions import db

    while _CREATED_APPS:
        app, db_path = _CREATED_APPS.pop()
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        db_path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _dispose_apps_after_each_test():
    yield
    _dispose_created_apps()


def _user_count(app) -> int:
    from app.extensions import db
    from app.models import User

    with app.app_context():
        return db.session.query(User).count()


def _delete_all_users(app) -> None:
    # BYS360_P13B_TEST_ISOLATION: config.Config.SQLALCHEMY_DATABASE_URI is a
    # class attribute resolved once at first import of this process (like
    # APP_ENV). _make_app now pins it to the app's own task-owned sqlite file,
    # so `users` already starts empty; this explicit clear is kept only as a
    # cheap guard and touches nothing but that file.
    from app.extensions import db
    from app.models import User

    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()


# --- SEC-001: setup-admin disabled by default in production ---


def test_setup_admin_disabled_by_default_in_production(monkeypatch):
    app = _make_app(monkeypatch, app_env="production")
    _delete_all_users(app)
    before = _user_count(app)
    client = app.test_client()

    get_response = client.get("/setup-admin", follow_redirects=False)
    assert get_response.status_code == 404

    post_response = client.post(
        "/setup-admin",
        data={
            "ad": "Attacker",
            "soyad": "Bootstrap",
            "sicil_no": "90000",
            "email": "attacker@ktb.gov.tr",
            # BYS360 secret-gate closure: not a real credential -- an obviously
            # fake, test-only fixture value (contains "Test", matched
            # case-insensitively by the gate's own PLACEHOLDER_WORDS list in
            # scripts/quality/bys360_secret_repo_gate.py), still >= 8 chars to
            # satisfy _MIN_PASSWORD_LENGTH in app/main_handlers/auth_handlers.py.
            "password": "AttackerTestFixtureOnly123!",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 404
    assert _user_count(app) == before


def test_setup_admin_requires_explicit_flag_in_production(monkeypatch):
    app = _make_app(monkeypatch, app_env="production", setup_admin_enabled=True)
    _delete_all_users(app)
    before = _user_count(app)
    client = app.test_client()

    get_response = client.get("/setup-admin", follow_redirects=False)
    assert get_response.status_code == 200

    post_response = client.post(
        "/setup-admin",
        data={
            "ad": "Ops",
            "soyad": "Bootstrap",
            "sicil_no": "90001",
            "email": "ops.bootstrap@ktb.gov.tr",
            # Fake test-only fixture value; see comment on the attacker-path
            # password above.
            "password": "OperatorTestFixtureOnly1!",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 302
    assert _user_count(app) == before + 1


# --- SEC-001: setup-admin blocked once a user exists ---


def test_setup_admin_blocked_when_user_exists(monkeypatch):
    app = _make_app(monkeypatch)  # APP_ENV=testing -> route open by default
    _delete_all_users(app)
    from app.extensions import db
    from app.models import User

    with app.app_context():
        existing = User(
            sicil_no="10000",
            email="existing.admin@ktb.gov.tr",
            ad="Existing",
            soyad="Admin",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        existing.set_password("ExistingAdminPass1!")
        db.session.add(existing)
        db.session.commit()

    before = _user_count(app)
    assert before == 1
    client = app.test_client()

    get_response = client.get("/setup-admin", follow_redirects=False)
    assert get_response.status_code == 302
    assert "/login" in get_response.headers.get("Location", "")

    post_response = client.post(
        "/setup-admin",
        data={
            "ad": "Second",
            "soyad": "Admin",
            "sicil_no": "10001",
            "email": "second.admin@ktb.gov.tr",
            # Fake test-only fixture value; see comment on the attacker-path
            # password above.
            "password": "SecondAdminTestFixtureOnly1!",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 302
    assert _user_count(app) == before


# --- bonus: weak bootstrap password rejected ---


def test_setup_admin_rejects_weak_password(monkeypatch):
    app = _make_app(monkeypatch)  # APP_ENV=testing, zero users -> route open
    _delete_all_users(app)
    before = _user_count(app)
    client = app.test_client()

    response = client.post(
        "/setup-admin",
        data={
            "ad": "Weak",
            "soyad": "Password",
            "sicil_no": "10002",
            "email": "weak.password@ktb.gov.tr",
            "password": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert _user_count(app) == before


# --- task-owned test database lifecycle ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported, so setting DATABASE_URL in _make_app came too late: every app
# here shared whatever SQLite file Config froze to first (possibly another
# module's), and no engine was disposed or file deleted afterwards.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "phase13b_setup_admin_stale_config"


def test_app_uses_only_its_own_disposable_database(monkeypatch):
    from app.extensions import db
    from config import Config

    _STALE_DB_ROOT.mkdir(parents=True, exist_ok=True)
    stale_path = _STALE_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    conn = sqlite3.connect(stale_path)
    conn.execute("CREATE TABLE stale_config_marker (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + stale_path.as_posix())

    try:
        app = _make_app(monkeypatch)
        with app.app_context():
            own_db = Path(db.engine.url.database or "")
            on_stale_db = inspect(db.engine).has_table("stale_config_marker")
            users = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()

        assert own_db.parent == _PHASE13B_TEST_DB_ROOT
        assert own_db != stale_path
        assert not on_stale_db
        assert users == 0

        _dispose_created_apps()
        assert not own_db.exists()
    finally:
        stale_path.unlink(missing_ok=True)
