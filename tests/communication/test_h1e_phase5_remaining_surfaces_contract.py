"""BYS360 H1E-C -- remaining Phase 5 communication surfaces + status-count
chart-label closure contract.

Continuing the repo-wide grep sweep from H1E-A/H1E-B, four more surfaces
were found with a raw status/scope leak:

  1. app/templates/communication/phase5_audit_logs.html -- the "Durum"
     filter <select> showed raw success/failed as visible option text,
     the log table showed raw CommunicationAutomationLog.status, and the
     "Durum dağılımı" breakdown list rendered raw status strings as dict
     keys.
  2. app/templates/communication/phase5_operational_health.html -- both
     the live synthetic checks and the stored CommunicationOperationHealth
     history rendered the raw "ok"/"warning" vocabulary.
  3. app/templates/communication/phase5_retention_center.html -- the
     retention-policy "Kapsam" (data_scope) select/table and the
     scope-statistics table rendered raw internal scope identifiers
     (notifications/support/surveys/digest_logs/automation_logs) and the
     raw "ok"/"warning" status.
  4. app/templates/communication/phase4_survey_analytics.html and
     phase4_support_analytics.html fed a Chart.js bar chart directly from
     a raw-status-keyed breakdown dict (status_breakdown.keys()|tojson).

All four now reuse gate_status_label() (extended with "ok") for the
small closed status vocabulary, and two new dicts
(RETENTION_SCOPE_LABELS in communication_phase5_service.py) for the
retention scope identifiers. The chart-label dicts are re-keyed through
a new _labeled_counter() helper that MERGES counts for raw values that
share a Turkish label (e.g. Survey.status "published" and the legacy
"yayinda" both display as "Yayında") instead of silently dropping one
bucket -- this file specifically proves that merge is correct, not just
that individual values translate.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB (same pattern as the other H1E contract files).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_phase5_remaining_tmp" / "test_dbs"
_PASSWORD = "H1EPhase5RemainingTest1!"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-phase5-remaining-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-phase5-remaining-first-login-test-pw")
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


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD, menu_keys=("reports", "settings", "surveys", "support")):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="H1E",
            soyad="Phase5RemainingContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        for key in menu_keys:
            db.session.add(UserMenuPermission(user_id=user.id, menu_key=key, is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _insert_automation_log(app, *, status: str, action_type: str = "phase5_test_event"):
    from app.extensions import db
    from app.models.communication_phase5_models import CommunicationAutomationLog

    with app.app_context():
        row = CommunicationAutomationLog(action_type=action_type, status=status, summary="H1E negative-test log")
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_health_check(app, *, status: str, check_name: str = "H1E negative-test check"):
    from app.extensions import db
    from app.models.communication_phase5_models import CommunicationOperationHealth

    with app.app_context():
        row = CommunicationOperationHealth(check_name=check_name, status=status, metric_value="0")
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_retention_policy(app, *, data_scope: str):
    from app.extensions import db
    from app.models.communication_phase5_models import CommunicationRetentionPolicy

    with app.app_context():
        row = CommunicationRetentionPolicy(data_scope=data_scope, keep_days=365)
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_survey(app, *, status: str, title="H1E chart-label survey"):
    from app.extensions import db
    from app.models import Survey, User

    with app.app_context():
        creator = User.query.first()
        assert creator is not None
        survey = Survey(title=title, survey_type="kurum_ici", created_by_user_id=creator.id, status=status)
        db.session.add(survey)
        db.session.commit()
        return survey.id


# ---------------------------------------------------------------------------
# 1. Phase 5 audit logs.
# ---------------------------------------------------------------------------


def test_audit_logs_page_never_leaks_raw_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p5_audit_a")
    _insert_automation_log(app, status="future_status_v9")
    _login(client, "h1e_p5_audit_a")

    body = client.get("/communication/faz5/audit-logs").get_data(as_text=True)
    assert "future_status_v9" not in body
    assert "Bilinmiyor" in body


def test_audit_logs_page_shows_turkish_for_known_status_and_select(app, client) -> None:
    _create_user(app, sicil_no="h1e_p5_audit_b")
    _insert_automation_log(app, status="failed")
    _login(client, "h1e_p5_audit_b")

    body = client.get("/communication/faz5/audit-logs").get_data(as_text=True)
    assert "Başarısız" in body
    assert ">success</option>" not in body
    assert ">failed</option>" not in body
    assert 'value="success"' in body
    assert 'value="failed"' in body


# ---------------------------------------------------------------------------
# 2. Phase 5 operational health.
# ---------------------------------------------------------------------------


def test_operational_health_page_never_leaks_raw_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p5_health_a")
    _insert_health_check(app, status="future_status_v9")
    _login(client, "h1e_p5_health_a")

    body = client.get("/communication/faz5/health").get_data(as_text=True)
    assert "future_status_v9" not in body
    assert "Bilinmiyor" in body


def test_operational_health_page_shows_turkish_for_ok_and_warning(app, client) -> None:
    _create_user(app, sicil_no="h1e_p5_health_b")
    _insert_health_check(app, status="ok")
    _insert_health_check(app, status="warning")
    _login(client, "h1e_p5_health_b")

    body = client.get("/communication/faz5/health").get_data(as_text=True)
    assert "Uygun" in body
    assert "Uyarı" in body


# ---------------------------------------------------------------------------
# 3. Phase 5 retention center.
# ---------------------------------------------------------------------------


def test_retention_center_never_leaks_raw_scope_or_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p5_retention_a")
    _insert_retention_policy(app, data_scope="future_scope_v9")
    _login(client, "h1e_p5_retention_a")

    body = client.get("/communication/faz5/retention").get_data(as_text=True)
    assert "future_scope_v9" not in body
    assert "Bilinmiyor" in body


def test_retention_center_shows_turkish_scope_labels_and_select(app, client) -> None:
    _create_user(app, sicil_no="h1e_p5_retention_b")
    _insert_retention_policy(app, data_scope="support")
    _login(client, "h1e_p5_retention_b")

    body = client.get("/communication/faz5/retention").get_data(as_text=True)
    assert "Destek" in body
    assert ">notifications</option>" not in body
    assert ">automation_logs</option>" not in body
    assert 'value="notifications"' in body
    assert 'value="automation_logs"' in body


# ---------------------------------------------------------------------------
# 4. Chart-label breakdown -- merge behavior, not just individual mapping.
# ---------------------------------------------------------------------------


def test_survey_analytics_chart_labels_merge_legacy_and_current_status_values(app, client) -> None:
    """'published' and the legacy 'yayinda' both display as "Yayında" --
    the breakdown dict fed to the Chart.js bar chart must merge their
    counts into ONE bucket, not silently drop one raw key's count."""
    _create_user(app, sicil_no="h1e_p4_survey_c")
    _insert_survey(app, status="published", title="Survey A")
    _insert_survey(app, status="published", title="Survey B")
    _insert_survey(app, status="yayinda", title="Survey C (legacy status)")
    _login(client, "h1e_p4_survey_c")

    from app.services.communication_phase4_service import survey_analytics_snapshot

    with app.app_context():
        payload = survey_analytics_snapshot(days=365)

    assert payload["status_label_breakdown"]["Yayında"] == 3

    body = client.get("/communication/faz4/surveys/analytics").get_data(as_text=True)
    assert "yayinda" not in body
    assert "Yayında" in body


# ---------------------------------------------------------------------------
# Contract: stored raw values are completely unchanged.
# ---------------------------------------------------------------------------


def test_stored_retention_scope_and_health_status_are_unchanged_by_rendering(app, client) -> None:
    policy_id = _insert_retention_policy(app, data_scope="future_scope_v9")
    health_id = _insert_health_check(app, status="future_status_v9")
    _create_user(app, sicil_no="h1e_p5_contract")
    _login(client, "h1e_p5_contract")

    client.get("/communication/faz5/retention")
    client.get("/communication/faz5/health")

    from app.extensions import db
    from app.models.communication_phase5_models import (
        CommunicationOperationHealth,
        CommunicationRetentionPolicy,
    )

    with app.app_context():
        policy = db.session.get(CommunicationRetentionPolicy, policy_id)
        health = db.session.get(CommunicationOperationHealth, health_id)
        assert policy is not None
        assert health is not None
        assert policy.data_scope == "future_scope_v9"
        assert health.status == "future_status_v9"


# ---------------------------------------------------------------------------
# Authorization is unchanged.
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    for path in (
        "/communication/faz5/audit-logs",
        "/communication/faz5/health",
        "/communication/faz5/retention",
        "/communication/faz4/surveys/analytics",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, path
        assert "/login" in (response.headers.get("Location") or ""), path
