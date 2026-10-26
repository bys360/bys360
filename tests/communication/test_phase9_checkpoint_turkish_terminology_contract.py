"""BYS360 Phase 9 release-center feature -- "checkpoint" -> "kontrol noktası"
Turkish terminology contract (H1D).

H1B fixed Phase 8's "checkpoint" terminology and deliberately left Phase 9 /
Phase 9c out of scope (a separate, parallel feature). H1D closes that gap.
This file proves, against real Flask routes and a real (temporary,
isolated) database:

  A. the release-center page renders the Turkish "kontrol noktası"
     terminology;
  B. the underlying form field/token contract (checkpoint_token,
     checkpoint_key) is UNCHANGED;
  C. a successful checkpoint creation shows a Turkish success message, and
     an invalid/expired token shows a Turkish error message;
  D. the row.summary text written by record_phase9_checkpoint() is Turkish;
  E. authorization behavior is unchanged (anonymous -> redirect to login).

This test also exercises Phase 9's real (NOT stubbed)
phase9_release_center_snapshot(), which itself calls
communication_phase8_service.health_snapshot() and
communication_phase8_service.cutover_snapshot() -- both fixed in H1C
(commit 21a34b3). No stub is needed here, which is itself a behavioral
confirmation that the H1C fix benefits Phase 9 too, not only Phase 8.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB (same pattern as
tests/communication/test_phase8_checkpoint_turkish_terminology_contract.py).
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "phase9_checkpoint_turkish_tmp" / "test_dbs"
_PASSWORD = "Phase9CheckpointTurkishTest1!"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase9-checkpoint-turkish-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "phase9-checkpoint-first-login-test-pw")
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

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="Phase9",
            soyad="CheckpointContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        db.session.add(UserMenuPermission(user_id=user.id, menu_key="settings", is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _checkpoint_token(body: str) -> str:
    m = re.search(r'name="checkpoint_token" value="([^"]*)"', body)
    assert m, "checkpoint_token hidden field not found in rendered release-center page"
    return m.group(1)


# ---------------------------------------------------------------------------
# A + B: rendered Turkish terminology, unchanged form-field contract.
# ---------------------------------------------------------------------------


def test_release_center_renders_turkish_terminology_with_unchanged_form_contract(app, client) -> None:
    _create_user(app, sicil_no="p9_admin_a")
    _login(client, "p9_admin_a")

    response = client.get("/communication/faz9/release-center")
    assert response.status_code == 200, "real (unstubbed) phase9_release_center_snapshot must succeed after the H1C fix"
    body = response.get_data(as_text=True)

    assert "Kontrol noktası kaydı" in body
    assert "Kontrol noktası kaydet" in body
    assert ">Checkpoint<" not in body
    assert "Checkpoint kaydı" not in body
    assert "Checkpoint kaydet" not in body

    assert 'name="checkpoint_token"' in body
    assert 'name="checkpoint_key"' in body


# ---------------------------------------------------------------------------
# C + D: Turkish success / error messages, Turkish stored summary.
# ---------------------------------------------------------------------------


def test_successful_checkpoint_creation_shows_turkish_success_message_and_summary(app, client) -> None:
    _create_user(app, sicil_no="p9_admin_c")
    _login(client, "p9_admin_c")

    page = client.get("/communication/faz9/release-center")
    token = _checkpoint_token(page.get_data(as_text=True))

    response = client.post(
        "/communication/faz9/checkpoint",
        data={"checkpoint_token": token, "checkpoint_key": "release_gate", "status": "pass", "note": "H1D contract"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Faz 9 kontrol noktası kaydedildi." in body
    # The stored row.summary (rendered in the "Son kayıtlar" table) is
    # also Turkish now, not "Faz 9 checkpoint | ...".
    assert "Faz 9 kontrol noktası |" in body
    assert "phase9_checkpoint" not in body
    assert ">Checkpoint<" not in body


def test_invalid_or_expired_token_shows_turkish_error_message(app, client) -> None:
    _create_user(app, sicil_no="p9_admin_e")
    _login(client, "p9_admin_e")

    response = client.post(
        "/communication/faz9/checkpoint",
        data={"checkpoint_token": "not-a-real-token", "checkpoint_key": "release_gate", "status": "pass"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Faz 9 kontrol noktası formu geçersiz veya süresi dolmuş." in body


def test_unexpected_creation_failure_shows_turkish_error_message(app, client, monkeypatch) -> None:
    """BYS360 H1F (exception-display hardening): this branch's flash used
    to append the raw exception's own text after a colon
    (f"Kontrol noktasi kaydi olusturulamadi: {exc}") -- a genuinely
    unexpected exception's message leaking to the admin verbatim. Fixed to
    a fixed safe message (no trailing colon/detail); this assertion was
    updated to match."""
    import app.communication.phase9_routes as _phase9_routes

    def _boom(*_args, **_kwargs):
        raise RuntimeError("forced failure for H1D exception-branch coverage")

    monkeypatch.setattr(_phase9_routes, "record_phase9_checkpoint", _boom)

    _create_user(app, sicil_no="p9_admin_e2")
    _login(client, "p9_admin_e2")

    page = client.get("/communication/faz9/release-center")
    token = _checkpoint_token(page.get_data(as_text=True))

    response = client.post(
        "/communication/faz9/checkpoint",
        data={"checkpoint_token": token, "checkpoint_key": "release_gate", "status": "pass"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Kontrol noktası kaydı oluşturulamadı." in body
    assert "forced failure for H1D exception-branch coverage" not in body


# ---------------------------------------------------------------------------
# E: authorization behavior is unchanged.
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    response = client.get("/communication/faz9/release-center", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in (response.headers.get("Location") or "")
