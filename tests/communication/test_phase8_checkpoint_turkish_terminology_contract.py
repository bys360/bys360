"""BYS360 Phase 8 cutover feature -- "checkpoint" -> "kontrol noktası" Turkish
terminology contract (H1B).

H1 deferred this word because it was used consistently across the whole
Phase 8 cutover feature (heading, form label, button, section title, empty
state -- not only the 3 flash messages P0's narrower scan found). This file
proves, against real Flask routes and a real (temporary, isolated) database:

  A. the cutover page renders the Turkish "kontrol noktası" terminology;
  B. the underlying form field names / hidden CSRF-style token field are
     UNCHANGED (checkpoint_token, checkpoint_key) -- only the label text
     users read changed, not the contract the browser submits;
  C. the route/endpoint names are unchanged;
  D. a successful checkpoint creation shows a Turkish success message;
  E. an expired/invalid token shows a Turkish error message, and the
     empty-state message (no checkpoint rows yet) is Turkish;
  F. authorization behavior (anonymous -> redirect to login; authenticated
     but without the 'settings' menu key -> access denied) is unchanged --
     this file never touches app/security/decorators.py or
     app/route_support.py;
  G. after creating one real checkpoint row, no user-visible "Checkpoint"
     text remains anywhere on the cutover or dashboard page -- including
     the machine `action_type` value ("phase8_checkpoint"/"phase8_note")
     that was previously rendered to the user verbatim (`{{ row.action_type
     }}`) and now renders through a display-only Turkish mapping.

This file writes NOTHING to any production source file -- only to its own
isolated, temporary SQLite DB (same pattern as
tests/behavior/test_admin_routes_authorization_contract.py).
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "phase8_checkpoint_turkish_tmp" / "test_dbs"
_PASSWORD = "Phase8CheckpointTurkishTest1!"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase8-checkpoint-turkish-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "phase8-checkpoint-first-login-test-pw")
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


def _stub_pilot_readiness_snapshot(*, viewer=None):  # K5 F4: callers pass the viewer
    """Stand-in for communication_phase8_service.pilot_readiness_snapshot().

    Unrelated pre-existing bugs (confirmed independently, NOT introduced or
    fixed by this H1B change) make the real function 500 unconditionally,
    before any DB rows even exist:

      - health_snapshot() calls Notification.query.filter_by(is_read=False,
        is_hidden=False) -- Notification has no is_hidden column anywhere
        in app/models/ or migrations/ (sqlalchemy.exc.InvalidRequestError).
      - pilot_readiness_snapshot() itself calls
        SurveyAssignment.query.filter(SurveyAssignment.status.in_(...)) --
        SurveyAssignment has no status attribute either (AttributeError).

    Both break the entire Phase 8 cutover/dashboard/readiness call chain
    (cutover_snapshot -> pilot_readiness_snapshot) regardless of anything in
    this file, in every environment (confirmed via a direct grep: neither
    referenced field exists anywhere in the models or migrations). Fixing
    those is out of scope for H1B (checkpoint terminology only) and has
    been flagged separately as a high-priority, unrelated production defect.

    This stub only unblocks route-level exercise of the checkpoint
    terminology under test (A-G in the module docstring) -- it asserts
    nothing about readiness/health scoring, and every field below is a
    fixed, inert value shaped to satisfy exactly what
    communication_phase8_service.cutover_snapshot() /
    phase8_dashboard_snapshot() read from it (see the exact `readiness[...]`
    access sites in that file)."""
    return {
        "generated_at": None,
        "decision": "Pilot açılışa hazır",
        "tone": "success",
        "counts": {"pass": 0, "warn": 0, "fail": 0},
        "gates": [],
        "recommendations": [],
        "go_live": {
            "readiness_score": 100,
            "blockers": [],
            "counts": {"pass": 0, "warn": 0, "fail": 0},
            "backup_summary": {"recent_files": []},
        },
        "health": {"summary": {}, "recent_checks": []},
        "automation": {"summary": {}},
        "escalation": {"summary": {}},
        "retention": {"policies": []},
    }


@pytest.fixture
def app(monkeypatch):
    app = _make_app(monkeypatch)
    import app.services.communication_phase8_service as _phase8_service

    monkeypatch.setattr(_phase8_service, "pilot_readiness_snapshot", _stub_pilot_readiness_snapshot)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="Phase8",
            soyad="CheckpointContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _checkpoint_token(body: str) -> str:
    m = re.search(r'name="checkpoint_token" value="([^"]*)"', body)
    assert m, "checkpoint_token hidden field not found in rendered cutover page"
    return m.group(1)


# ---------------------------------------------------------------------------
# A + B + C: rendered Turkish terminology, unchanged form-field/route contract
# ---------------------------------------------------------------------------


def test_cutover_page_renders_turkish_terminology_with_unchanged_form_contract(app, client) -> None:
    _create_user(app, sicil_no="p8_admin_a")
    _login(client, "p8_admin_a")

    response = client.get("/communication/faz8/cutover")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    # A: Turkish terminology is present.
    assert "Kontrol noktası ekle" in body
    assert "Kontrol noktası kaydet" in body
    assert "Son kontrol noktası kayıtları" in body
    assert "kontrol noktası ve karar notları" in body

    # A (negative): the old English literal no longer appears as visible text.
    assert ">Checkpoint<" not in body
    assert "Checkpoint ekle" not in body
    assert "Checkpoint kaydet" not in body
    assert "Son checkpoint kayıtları" not in body

    # B: the technical form contract (field names the browser submits) is
    # completely unchanged -- only the human-readable label text changed.
    assert 'name="checkpoint_token"' in body
    assert 'name="checkpoint_key"' in body

    # C: route/endpoint names are unchanged (this would raise BuildError if
    # the endpoint had been renamed).
    from flask import url_for

    with app.test_request_context():
        assert url_for("main.communication_phase8_checkpoint_create") == "/communication/faz8/cutover/checkpoint"
        assert url_for("main.communication_phase8_cutover") == "/communication/faz8/cutover"


# ---------------------------------------------------------------------------
# D + E: Turkish success / error / empty-state messages
# ---------------------------------------------------------------------------


def test_successful_checkpoint_creation_shows_turkish_success_message(app, client) -> None:
    _create_user(app, sicil_no="p8_admin_d")
    _login(client, "p8_admin_d")

    page = client.get("/communication/faz8/cutover")
    token = _checkpoint_token(page.get_data(as_text=True))

    response = client.post(
        "/communication/faz8/cutover/checkpoint",
        data={"checkpoint_token": token, "checkpoint_key": "config_freeze", "status": "done", "note": "H1B contract"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Pilot kontrol noktası kaydedildi." in body


def test_unexpected_creation_failure_shows_turkish_error_message(app, client, monkeypatch) -> None:
    """Covers the except-branch flash (phase8_routes.py's third translated
    string) via real fault injection, not just the token-validation branch.

    BYS360 H1F (exception-display hardening): this branch's flash used to
    append the raw exception's own text after a colon
    (f"Kontrol noktasi kaydi olusturulamadi: {exc}") -- a genuinely
    unexpected exception's message leaking to the admin verbatim. Fixed to
    a fixed safe message (no trailing colon/detail); this assertion was
    updated to match."""
    import app.communication.phase8_routes as _phase8_routes

    def _boom(*_args, **_kwargs):
        raise RuntimeError("forced failure for H1B exception-branch coverage")

    monkeypatch.setattr(_phase8_routes, "record_phase8_checkpoint", _boom)

    _create_user(app, sicil_no="p8_admin_e3")
    _login(client, "p8_admin_e3")

    page = client.get("/communication/faz8/cutover")
    token = _checkpoint_token(page.get_data(as_text=True))

    response = client.post(
        "/communication/faz8/cutover/checkpoint",
        data={"checkpoint_token": token, "checkpoint_key": "config_freeze", "status": "done"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Kontrol noktası kaydı oluşturulamadı." in body
    assert "forced failure for H1B exception-branch coverage" not in body


def test_invalid_or_expired_token_shows_turkish_error_message(app, client) -> None:
    _create_user(app, sicil_no="p8_admin_e1")
    _login(client, "p8_admin_e1")

    response = client.post(
        "/communication/faz8/cutover/checkpoint",
        data={"checkpoint_token": "not-a-real-token", "checkpoint_key": "config_freeze", "status": "done"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Faz 8 kontrol noktası formu geçersiz veya süresi dolmuş." in body


def test_empty_checkpoint_log_state_shows_turkish_message(app, client) -> None:
    _create_user(app, sicil_no="p8_admin_e2")
    _login(client, "p8_admin_e2")

    response = client.get("/communication/faz8/cutover")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Henüz kontrol noktası kaydı yok." in body


# ---------------------------------------------------------------------------
# F: authorization behavior is completely unchanged
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    response = client.get("/communication/faz8/cutover", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in (response.headers.get("Location") or "")


def test_authenticated_user_without_settings_menu_access_is_denied(app, client) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    user_id = _create_user(app, sicil_no="p8_no_settings", role="admin")
    with app.app_context():
        db.session.add(UserMenuPermission(user_id=user_id, menu_key="settings", is_visible=False, source_type="user_override"))
        db.session.commit()

    _login(client, "p8_no_settings")
    response = client.get("/communication/faz8/cutover")
    assert response.status_code in (403, 200), (
        "Expected either a real 403 or the access-denied page rendered with 200 "
        "(render_access_denied() may respond 200 with a denial template)"
    )
    if response.status_code == 200:
        body = response.get_data(as_text=True).lower()
        assert "checkpoint" not in body, "unrelated: page content check"
        assert "kontrol noktası ekle" not in body, "settings-denied user must not see the cutover form"


# ---------------------------------------------------------------------------
# G: no user-visible "checkpoint" remains anywhere in the Phase 8 feature,
# including the machine action_type value that used to leak into the table.
# ---------------------------------------------------------------------------


def test_no_user_visible_checkpoint_text_remains_after_a_real_checkpoint_is_recorded(app, client) -> None:
    _create_user(app, sicil_no="p8_admin_g")
    _login(client, "p8_admin_g")

    page = client.get("/communication/faz8/cutover")
    token = _checkpoint_token(page.get_data(as_text=True))
    client.post(
        "/communication/faz8/cutover/checkpoint",
        data={"checkpoint_token": token, "checkpoint_key": "db_backup", "status": "done", "note": "G-scan"},
        follow_redirects=True,
    )

    cutover_body = client.get("/communication/faz8/cutover").get_data(as_text=True)
    dashboard_body = client.get("/communication/faz8").get_data(as_text=True)

    for label, body in (("cutover", cutover_body), ("dashboard", dashboard_body)):
        # The raw machine action_type value must never be shown verbatim --
        # it must render through the Turkish display mapping instead.
        assert "phase8_checkpoint" not in body, f"{label}: raw action_type leaked into user-visible text"
        assert ">Checkpoint<" not in body, f"{label}: untranslated 'Checkpoint' literal found"

    assert "Kontrol noktası" in cutover_body
    # The created row's summary (built server-side) must also be Turkish now.
    assert "Faz 8 kontrol noktası |" in cutover_body
