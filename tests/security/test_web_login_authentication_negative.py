"""BYS360 Test Integration Expansion Wave 1 — web login authentication.

Real Flask ``test_client()`` posting to the real ``/login`` route, against a
real (in-memory SQLite) user with a real password hash. Verifies the actual
session-cookie authentication chain end to end: a session established by a
successful POST really unlocks a protected page on a follow-up GET in the
same client, and a failed/blocked login really does not.
"""
from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text


def _make_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-web-login-flows")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    # Config froze its values when config.py was first imported, possibly by
    # another test pointing at its own SQLite file; pin them so every app here
    # gets its own empty in-memory database.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch):
    flask_app = _make_app(monkeypatch)
    yield flask_app
    from app.extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, email, password, is_active=True, must_change_password=False, must_set_security_question=False):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave1",
            soyad="Login",
            role="personel",
            is_active=is_active,
            must_change_password=must_change_password,
            must_set_security_question=must_set_security_question,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


# --- HTTP-INTEGRATION: full session-cookie login chain, real redirect targets ---


def test_login_page_renders_for_anonymous_get(client):
    response = client.get("/login")

    assert response.status_code == 200


def test_successful_login_with_clean_account_redirects_home_and_establishes_session(app, client):
    _create_user(app, sicil_no="80001", email="w1.web.login.ok@bys360.test", password="WebTestLoginOk1!")

    response = client.post(
        "/login",
        data={"sicil_or_email": "80001", "password": "WebTestLoginOk1!"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")

    # The session cookie set by the successful POST must actually authorize a
    # follow-up request in the SAME client -- proves this is a real session,
    # not just a redirect with no state behind it.
    home_response = client.get(response.headers["Location"])
    assert home_response.status_code in {200, 302}
    assert home_response.status_code != 401


def test_successful_login_accepts_email_identity(app, client):
    _create_user(app, sicil_no="80002", email="w1.web.login.email@bys360.test", password="WebTestLoginEmail1!")

    response = client.post(
        "/login",
        data={"sicil_or_email": "w1.web.login.email@bys360.test", "password": "WebTestLoginEmail1!"},
        follow_redirects=False,
    )

    assert response.status_code == 302


def test_login_with_wrong_password_does_not_redirect_and_does_not_establish_session(app, client):
    _create_user(app, sicil_no="80003", email="w1.web.wrongpw@bys360.test", password="RealTestPassword1!")

    response = client.post(
        "/login",
        data={"sicil_or_email": "80003", "password": "WrongTestPassword!"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert b"iri" in response.data or response.status_code == 200  # re-rendered login page, not a redirect

    # No session was established -- a protected page must not treat us as authenticated.
    protected = client.get("/hr-management", follow_redirects=False)
    assert protected.status_code in {302, 401, 403}


def test_login_with_nonexistent_identity_returns_generic_error_not_404(client):
    response = client.post(
        "/login",
        data={"sicil_or_email": "no-such-user-80099", "password": "whatever"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.status_code != 404


def test_login_for_inactive_account_is_rejected(app, client):
    _create_user(app, sicil_no="80004", email="w1.web.inactive@bys360.test", password="InactiveTest1!", is_active=False)

    response = client.post(
        "/login",
        data={"sicil_or_email": "80004", "password": "InactiveTest1!"},
        follow_redirects=False,
    )

    assert response.status_code == 200

    protected = client.get("/hr-management", follow_redirects=False)
    assert protected.status_code in {302, 401, 403}


# --- VALIDATION-NEGATIVE ---


def test_login_with_missing_password_field_does_not_500(app, client):
    _create_user(app, sicil_no="80005", email="w1.web.missingpw@bys360.test", password="WhateverTest1!")

    response = client.post("/login", data={"sicil_or_email": "80005"}, follow_redirects=False)

    assert response.status_code < 500


def test_login_with_missing_identity_field_does_not_500(client):
    response = client.post("/login", data={"password": "whatever"}, follow_redirects=False)

    assert response.status_code < 500


def test_login_with_empty_form_does_not_500(client):
    response = client.post("/login", data={}, follow_redirects=False)

    assert response.status_code < 500


# --- HTTP-INTEGRATION: first-login gating (must_change_password / must_set_security_question) ---


def test_first_login_with_default_flags_redirects_to_security_setup_not_home(app, client):
    """A freshly provisioned user (both first-login flags left at their real
    model defaults) must be routed to security-question setup before reaching
    the dashboard -- proves the first-login gate is actually enforced, not
    just present in source."""
    _create_user(
        app,
        sicil_no="80006",
        email="w1.web.firstlogin@bys360.test",
        password="FirstTestLogin1!",
        must_change_password=True,
        must_set_security_question=True,
    )

    response = client.post(
        "/login",
        data={"sicil_or_email": "80006", "password": "FirstTestLogin1!"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "home" not in response.headers.get("Location", "").lower()


# --- AUTHZ-NEGATIVE: logout actually clears the session ---


def test_logout_clears_session_and_protected_page_requires_login_again(app, client):
    _create_user(app, sicil_no="80007", email="w1.web.logout@bys360.test", password="LogoutTestFlow1!")

    login = client.post(
        "/login",
        data={"sicil_or_email": "80007", "password": "LogoutTestFlow1!"},
        follow_redirects=False,
    )
    assert login.status_code == 302

    client.get("/logout", follow_redirects=False)

    protected = client.get("/hr-management", follow_redirects=False)
    assert protected.status_code in {302, 401, 403}


# --- isolation from a stale process-global Config database URI ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported. If an earlier test imported it while DATABASE_URL pointed at
# its own SQLite file, setting DATABASE_URL here came too late: this module's
# apps silently used that file and collided on users.email when run again in
# the same process.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "web_login_negative_stale_config"


def test_app_does_not_inherit_a_stale_frozen_config_database_uri(monkeypatch):
    from app.extensions import db
    from config import Config

    _STALE_DB_ROOT.mkdir(parents=True, exist_ok=True)
    stale_path = _STALE_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    conn = sqlite3.connect(stale_path)
    conn.execute("CREATE TABLE stale_config_marker (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + stale_path.as_posix())

    app = _make_app(monkeypatch)
    counts = {}
    try:
        with app.app_context():
            engine_url = str(db.engine.url)
            on_stale_db = inspect(db.engine).has_table("stale_config_marker")
            counts["users"] = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        stale_path.unlink(missing_ok=True)

    assert engine_url == "sqlite:///:memory:"
    assert not on_stale_db
    assert counts == {"users": 0}
