"""Phase 13B security closure -- password reset hardening (AUTH-003).

Prior brutal-audit follow-up confirmed a full unauthenticated account
takeover chain through ``/forgot-password``: no throttle at all (40+ wrong
security-answer guesses in seconds), a default security question whose
answer space was a single letter, and no invalidation of the victim's other
already-authenticated sessions after a reset. The fix adds: a reset-specific
throttle (mirrors the login throttle, see app/security/request_guard.py),
removal of the single-letter question from ``SECURITY_QUESTION_CHOICES``,
and a ``User.security_stamp`` rotated on every successful reset so any other
session's embedded stamp (baked into Flask-Login's ``get_id()``) is
invalidated on its next request.

Note on scope: this app's reset flow has no email/token step at all -- the
security answer *is* the reset factor. Some of the 20 mandated Phase 13B
tests ("token expires", "token single-use", "token tampered") are therefore
adapted to what actually exists rather than a literal token lifecycle, per
the campaign brief's own instruction to adapt scenario details to the real
implementation. Full unknown-vs-known response-body parity (closing the
enumeration content oracle entirely) is NOT addressed in this pass -- the
docstring on that test says so explicitly; it is a documented residual, not
a claimed fix.
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


def _make_app(monkeypatch, **config_overrides):
    _PHASE13B_TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _PHASE13B_TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase13b-password-reset-negatives")
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
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    app.config.update(config_overrides)

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


def _clear_request_guard_buckets():
    # BYS360_P13B_TEST_ISOLATION: the throttle buckets in
    # app/security/request_guard.py are plain module-level dicts, not scoped
    # to a Flask app instance -- state from an earlier test in the same
    # pytest process/file would otherwise leak into this one.
    from app.security import request_guard

    request_guard._BUCKETS.clear()
    request_guard._LOG_COOLDOWNS.clear()


def _create_user(app, *, sicil_no, email, question="İlk okul öğretmeninizin adı nedir?", answer="OgretmenAyse", password="OldPassword1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Phase13b",
            soyad="Reset",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
            security_question=question,
        )
        user.set_password(password)
        user.set_security_answer(answer)
        db.session.add(user)
        db.session.commit()
        return user.id


def _password_hash(app, sicil_no):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.query(User).filter_by(sicil_no=sicil_no).first()
        assert user is not None
        return user.password_hash


def _login(client, sicil_no, password):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


# --- #12 (adapted from "token expires"): reset throttle blocks excessive guessing ---


def test_reset_throttle_blocks_excessive_attempts(monkeypatch):
    app = _make_app(monkeypatch, RESET_IDENTITY_MAX_ATTEMPTS=5, RESET_LOCKOUT_MINUTES=15)
    _clear_request_guard_buckets()
    _create_user(app, sicil_no="13c001", email="p13b.throttle@ktb.gov.tr", answer="CorrectAnswer1")
    client = app.test_client()

    # 5 wrong attempts are allowed through (checked and rejected on their own merit).
    for _ in range(5):
        response = client.post(
            "/forgot-password",
            data={
                "sicil_or_email": "13c001",
                "security_answer": "WrongGuess",
                "new_password": "GuessAttempt1!",
                "new_password_repeat": "GuessAttempt1!",
            },
        )
        assert response.status_code == 200

    # The 6th is throttled before the answer is even checked.
    blocked = client.post(
        "/forgot-password",
        data={
            "sicil_or_email": "13c001",
            "security_answer": "CorrectAnswer1",
            "new_password": "AttackerChangedThis1!",
            "new_password_repeat": "AttackerChangedThis1!",
        },
    )
    assert blocked.status_code == 200
    assert b"fazla" in blocked.data or b"deneme" in blocked.data

    # Even with the *correct* answer, the throttled request must not have reset the password.
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.query(User).filter_by(sicil_no="13c001").first()
        assert user is not None
        assert user.check_password("OldPassword1!")


# --- #13/#14 (adapted from "single-use"/"tampered"): identity+answer pairing cannot be mixed ---


def test_reset_answer_from_other_account_is_rejected(monkeypatch):
    app = _make_app(monkeypatch)
    _clear_request_guard_buckets()
    _create_user(app, sicil_no="13c002", email="p13b.victim@ktb.gov.tr", answer="VictimSecretAnswer", password="VictimOldPass1!")
    _create_user(app, sicil_no="13c003", email="p13b.other@ktb.gov.tr", answer="OtherSecretAnswer", password="OtherOldPass1!")
    client = app.test_client()

    # Attacker knows account B's answer but targets account A's identity.
    response = client.post(
        "/forgot-password",
        data={
            "sicil_or_email": "13c002",
            "security_answer": "OtherSecretAnswer",
            "new_password": "AttackerPass1!",
            "new_password_repeat": "AttackerPass1!",
        },
    )

    assert response.status_code == 200
    from app.extensions import db
    from app.models import User

    with app.app_context():
        victim = db.session.query(User).filter_by(sicil_no="13c002").first()
        assert victim is not None
        assert victim.check_password("VictimOldPass1!")
        assert not victim.check_password("AttackerPass1!")


# --- #15 (partial/honest): known vs unknown identity does not crash and both settle on the same status code ---


def test_reset_unknown_identity_does_not_crash_or_leak_500(monkeypatch):
    # Full response-body/enumeration parity between known and unknown
    # identities is NOT claimed fixed by this test -- see module docstring.
    # This test only locks the part that genuinely holds: an unknown
    # identity is handled safely (no crash, no stack trace, no reset).
    app = _make_app(monkeypatch)
    _clear_request_guard_buckets()
    _create_user(app, sicil_no="13c004", email="p13b.known@ktb.gov.tr")
    client = app.test_client()

    known = client.post("/forgot-password", data={"sicil_or_email": "13c004"})
    unknown = client.post("/forgot-password", data={"sicil_or_email": "13c004-does-not-exist"})

    assert known.status_code == 200
    assert unknown.status_code == 200


# --- #16: reset invalidates prior sessions ---


def test_reset_invalidates_prior_sessions(monkeypatch):
    app = _make_app(monkeypatch)
    _clear_request_guard_buckets()
    _create_user(app, sicil_no="13c005", email="p13b.session@ktb.gov.tr", answer="SessionAnswer1", password="OriginalPass1!")

    victim_client = app.test_client()
    _login(victim_client, "13c005", "OriginalPass1!")

    still_valid = victim_client.get("/account", follow_redirects=False)
    assert still_valid.status_code == 200

    attacker_client = app.test_client()
    reset_response = attacker_client.post(
        "/forgot-password",
        data={
            "sicil_or_email": "13c005",
            "security_answer": "SessionAnswer1",
            "new_password": "AttackerControlled1!",
            "new_password_repeat": "AttackerControlled1!",
        },
        follow_redirects=False,
    )
    assert reset_response.status_code == 302

    after_reset = victim_client.get("/account", follow_redirects=False)
    assert after_reset.status_code == 302
    assert "/login" in after_reset.headers.get("Location", "")


# --- #20: audit log generated for the sensitive change ---


def test_reset_writes_audit_log_entry(monkeypatch, caplog):
    import logging

    app = _make_app(monkeypatch)
    _clear_request_guard_buckets()
    _create_user(app, sicil_no="13c006", email="p13b.audit@ktb.gov.tr", answer="AuditAnswer1", password="AuditOldPass1!")
    client = app.test_client()

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/forgot-password",
            data={
                "sicil_or_email": "13c006",
                "security_answer": "AuditAnswer1",
                "new_password": "AuditNewPass1!",
                "new_password_repeat": "AuditNewPass1!",
            },
        )

    assert response.status_code == 302
    reset_log_records = [r for r in caplog.records if "sifirlama" in r.getMessage().lower()]
    assert reset_log_records, "expected a password-reset audit log line"
    # identity must be masked, not logged in the clear
    assert not any("p13b.audit@ktb.gov.tr" in r.getMessage() for r in caplog.records)


# --- task-owned test database lifecycle ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported, so setting DATABASE_URL in _make_app came too late: every app
# here shared whatever SQLite file Config froze to first (possibly another
# module's), and no engine was disposed or file deleted afterwards.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "phase13b_password_reset_stale_config"


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
