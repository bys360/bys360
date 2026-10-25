"""BYS360 H1E -- communication go-live "gate" family raw status/enum display
closure contract.

H1D found that the Phase 8/9/9A/9B/9C/9D go-live gate family
(communication_phase8_service.py's `_pilot_gate()`, communication_phase9_
service.py's `_gate()`, and four parallel copy-pasted variants in phase9a/
9b/9c/9d) all rendered their raw English status vocabulary
(pass/warn/fail/pending/ready/hold/done/watch/risk/critical/controlled/
approved/blocked/paused/stable/success) directly to end users -- both as
table/badge text and as <select> option text in the operator-facing
recording forms.

H1E fixes this with one shared, additive helper
(app.services.communication_gate_status_labels.gate_status_label /
GATE_STATUS_LABELS) that every gate/row dict in the family now also carries
as a new `status_label` field, alongside the unchanged raw `status` field
(still used for CSS tone selection and business-logic comparisons). This
file proves, against real Flask routes and a real (temporary, isolated)
database:

  A. gate_status_label() maps every known vocabulary word to its Turkish
     label, is case/whitespace-insensitive, and -- critically -- NEVER
     falls back to the raw value for an unrecognized word: it always
     returns the safe generic Turkish fallback "Bilinmiyor".
  B. the Phase 8 cutover page and Phase 9 release-center page render the
     Turkish labels, not the raw English words, in both status badges and
     <select> option text -- while every <option value="..."> attribute
     (the actual submitted machine value) is completely unchanged.
  C. a CommunicationAutomationLog row carrying a status value from BEFORE
     this vocabulary existed, or ANY future/unmapped status value, never
     leaks that raw value to the user anywhere it is displayed -- it
     always renders through the safe "Bilinmiyor" fallback instead.
  D. the raw `status` value actually stored in the database (via a real
     POST through the real record_* functions) is completely unchanged --
     only the display layer changed, not what gets persisted.
  E. Phase 9C's incident severity fix (INCIDENT_SEVERITY_LABELS) keeps the
     raw `severity` value available for CSS tone selection while showing
     the Turkish `severity_label` for text, and never leaks an unmapped
     severity value raw either.
  F. authorization behavior is completely unchanged (unauthenticated ->
     redirect to login).

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB (same pattern as
tests/communication/test_phase9_checkpoint_turkish_terminology_contract.py).
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_gate_status_tmp" / "test_dbs"
_PASSWORD = "H1EGateStatusTurkishTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contract for the shared helper (no app required).
# ---------------------------------------------------------------------------


def test_gate_status_label_maps_known_vocabulary_to_turkish() -> None:
    from app.services.communication_gate_status_labels import gate_status_label

    expected = {
        "pass": "Geçti",
        "warn": "Uyarı",
        "fail": "Başarısız",
        "ready": "Hazır",
        "done": "Tamamlandı",
        "hold": "Beklemede",
        "pending": "Bekliyor",
        "watch": "İzleniyor",
        "risk": "Riskli",
        "critical": "Kritik",
        "controlled": "Kontrollü",
        "approved": "Onaylandı",
        "blocked": "Engellendi",
        "paused": "Duraklatıldı",
        "stable": "Stabil",
        "success": "Başarılı",
    }
    for raw, turkish in expected.items():
        assert gate_status_label(raw) == turkish

    # Case-insensitive, whitespace-tolerant.
    assert gate_status_label("PASS") == "Geçti"
    assert gate_status_label("  Warn  ") == "Uyarı"


def test_gate_status_label_never_leaks_an_unmapped_value_raw() -> None:
    """The mandatory H1E negative test: an unknown/future machine value must
    NEVER be returned verbatim -- always the safe Turkish fallback."""
    from app.services.communication_gate_status_labels import gate_status_label

    assert gate_status_label("future_status_v99") == "Bilinmiyor"
    assert gate_status_label("some_other_new_backend_value") == "Bilinmiyor"
    assert gate_status_label(None) == "Bilinmiyor"
    assert gate_status_label("") == "Bilinmiyor"
    assert gate_status_label("   ") == "Bilinmiyor"


# ---------------------------------------------------------------------------
# App/client fixtures (same pattern as
# test_phase9_checkpoint_turkish_terminology_contract.py -- no stub needed,
# the H1C fix already makes the real snapshot functions safe to call).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-gate-status-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-gate-status-first-login-test-pw")
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
            ad="H1E",
            soyad="GateStatusContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        db.session.add(UserMenuPermission(user_id=user.id, menu_key="settings", is_visible=True, source_type="user_override"))
        db.session.add(UserMenuPermission(user_id=user.id, menu_key="reports", is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _hidden_token(body: str, field_name: str) -> str:
    m = re.search(rf'name="{field_name}" value="([^"]*)"', body)
    assert m, f"{field_name} hidden field not found in rendered page"
    return m.group(1)


def _insert_log_row(app, *, action_type: str, status: str, summary: str, payload_json: dict | None = None):
    """Insert a CommunicationAutomationLog row directly, bypassing the
    record_* helpers -- used to simulate a status value that predates this
    vocabulary or that no future code path is expected to ever validate
    against a fixed set (exactly the scenario H1E's fallback must survive)."""
    from app.extensions import db
    from app.models.communication_phase5_models import CommunicationAutomationLog

    with app.app_context():
        row = CommunicationAutomationLog(
            action_type=action_type,
            status=status,
            summary=summary,
            payload_json=payload_json or {},
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# B: Phase 8 cutover + Phase 9 release-center render Turkish labels, with
# the underlying <select> value contract completely unchanged.
# ---------------------------------------------------------------------------


def test_phase8_cutover_renders_turkish_task_status_and_select_options(app, client) -> None:
    _create_user(app, sicil_no="h1e_p8_a")
    _login(client, "h1e_p8_a")

    response = client.get("/communication/faz8/cutover")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    # Task status badges must show a Turkish label, never the raw word.
    assert ">done<" not in body
    assert ">pending<" not in body
    assert ("Tamamlandı" in body) or ("Bekliyor" in body)

    # The "Durum" <select> shows Turkish option text ...
    assert ">Tamamlandı</option>" in body
    assert ">Bekliyor</option>" in body
    assert ">Beklemede</option>" in body
    # ... while the submitted machine values are completely unchanged.
    assert 'value="done">Tamamlandı' in body
    assert 'value="pending">Bekliyor' in body
    assert 'value="hold">Beklemede' in body


def test_phase9_release_center_renders_turkish_select_options_and_gate_labels(app, client) -> None:
    _create_user(app, sicil_no="h1e_p9_b")
    _login(client, "h1e_p9_b")

    response = client.get("/communication/faz9/release-center")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    # "Durum" select (gate status) -- Turkish text, unchanged values.
    assert 'value="pass">Geçti' in body
    assert 'value="warn">Uyarı' in body
    assert 'value="fail">Başarısız' in body
    assert 'value="pending" selected>Bekliyor' in body

    # "Karar tipi" select (decision status) -- Turkish text, unchanged values.
    assert 'value="controlled" selected>Kontrollü' in body
    assert 'value="approved">Onaylandı' in body
    assert 'value="blocked">Engellendi' in body
    # "rollback" -> "geri dönüş" was already correct before H1E; must remain.
    assert 'value="rollback">geri dönüş' in body

    # No raw option text leaks (would appear as e.g. ">pass</option>").
    assert ">pass</option>" not in body
    assert ">warn</option>" not in body
    assert ">fail</option>" not in body
    assert ">controlled</option>" not in body
    assert ">approved</option>" not in body
    assert ">blocked</option>" not in body

    # The gates table itself renders a Turkish status_label, not raw status.
    gates_section = body.split("Canlıya geçiş kapıları", 1)[1]
    first_table_chunk = gates_section.split("</table>", 1)[0]
    assert ">pass<" not in first_table_chunk
    assert ">warn<" not in first_table_chunk
    assert ">fail<" not in first_table_chunk


# ---------------------------------------------------------------------------
# C: an unmapped/future status value never leaks raw anywhere it is shown.
# ---------------------------------------------------------------------------


def test_unknown_future_status_value_never_leaks_raw_on_phase9_dashboard(app, client) -> None:
    _insert_log_row(
        app,
        action_type="phase9_checkpoint",
        status="future_status_v99",
        summary="H1E negative-test checkpoint",
    )

    _create_user(app, sicil_no="h1e_p9_c")
    _login(client, "h1e_p9_c")

    dashboard_body = client.get("/communication/faz9").get_data(as_text=True)
    release_body = client.get("/communication/faz9/release-center").get_data(as_text=True)

    for label, body in (("dashboard", dashboard_body), ("release-center", release_body)):
        assert "future_status_v99" not in body, f"{label}: raw unmapped status leaked to the user"
        assert "Bilinmiyor" in body, f"{label}: safe Turkish fallback did not render"


def test_unknown_future_status_value_never_leaks_raw_on_phase9d_stabilization_center(app, client) -> None:
    _insert_log_row(
        app,
        action_type="phase9d_checkin",
        status="future_status_v99",
        summary="H1E negative-test 9D record",
        payload_json={"window_key": "0_24", "status": "future_status_v99", "note": ""},
    )

    _create_user(app, sicil_no="h1e_p9d_c")
    _login(client, "h1e_p9d_c")

    body = client.get("/communication/faz9d/stabilization-center").get_data(as_text=True)
    assert "future_status_v99" not in body
    assert "Bilinmiyor" in body


# ---------------------------------------------------------------------------
# D: the raw status value actually persisted via a real POST is unchanged --
# only the display layer changed.
# ---------------------------------------------------------------------------


def test_stored_checkpoint_status_value_is_unchanged_by_a_real_submission(app, client) -> None:
    _create_user(app, sicil_no="h1e_p9_d")
    _login(client, "h1e_p9_d")

    page = client.get("/communication/faz9/release-center")
    token = _hidden_token(page.get_data(as_text=True), "checkpoint_token")

    response = client.post(
        "/communication/faz9/checkpoint",
        data={"checkpoint_token": token, "checkpoint_key": "rollback_plan", "status": "warn", "note": "H1E contract"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    from app.models.communication_phase5_models import CommunicationAutomationLog

    with app.app_context():
        row = (
            CommunicationAutomationLog.query
            .filter_by(action_type="phase9_checkpoint")
            .order_by(CommunicationAutomationLog.id.desc())
            .first()
        )
        assert row is not None
        # The raw machine value stored in payload_json is exactly what was
        # submitted -- the display fix never touches storage.
        assert row.payload_json.get("status") == "warn"


# ---------------------------------------------------------------------------
# E: Phase 9C incident severity -- tone (raw) vs. text (Turkish label) split.
# ---------------------------------------------------------------------------


def test_phase9c_incident_severity_keeps_raw_tone_and_shows_turkish_label(app, client) -> None:
    _insert_log_row(
        app,
        action_type="phase9c_incident",
        status="critical",
        summary="H1E negative-test incident (known severity)",
        payload_json={"severity": "critical", "note": "known"},
    )
    _insert_log_row(
        app,
        action_type="phase9c_incident",
        status="future_severity_v9",
        summary="H1E negative-test incident (unmapped severity)",
        payload_json={"severity": "future_severity_v9", "note": "unmapped"},
    )

    _create_user(app, sicil_no="h1e_p9c_e")
    _login(client, "h1e_p9c_e")

    body = client.get("/communication/faz9c").get_data(as_text=True)

    # Known severity: Turkish label shown, danger tone class applied.
    assert "Kritik" in body
    assert "text-bg-danger" in body

    # Unmapped severity: never leaks raw, falls back to the safe label.
    assert "future_severity_v9" not in body
    assert "Bilinmiyor" in body


# ---------------------------------------------------------------------------
# F: authorization behavior is completely unchanged.
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    for path in (
        "/communication/faz8/cutover",
        "/communication/faz9/release-center",
        "/communication/faz9b/transition-center",
        "/communication/faz9c/pilot-opening",
        "/communication/faz9d/stabilization-center",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, path
        assert "/login" in (response.headers.get("Location") or ""), path
