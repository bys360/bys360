"""BYS360 executive report status -- raw DB status leak closure (H1D).

Root cause (found during the H1D repo-wide scan, same defect class as the
Phase 8 "checkpoint" action_type leak fixed in H1B):
CommunicationExecutiveReport.status is stored as a raw English code
("draft", "review", "approved", "revision", "rejected") and was rendered
VERBATIM in two places:

  - app/templates/communication/phase4_report_detail.html
    ("Durum: {{ row.status }}")
  - app/templates/communication/phase4_reports.html
    ("Son üretilen raporlar" table, history.rows[].status)

Fix: a new REPORT_STATUS_LABELS dict (single source of truth) was added to
app/services/communication_phase4_service.py; report_history_snapshot() now
attaches a status_label per row for the list page, and the detail route
passes REPORT_STATUS_LABELS to its template for a display-only lookup. The
stored CommunicationExecutiveReport.status column and the values assigned by
submit_report_for_review()/decide_governance() are completely untouched --
this is presentation-only.

This file writes NOTHING to any production source file -- only to its own
isolated, temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "phase4_report_status_turkish_tmp" / "test_dbs"
_PASSWORD = "Phase4ReportStatusTurkishTest1!"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase4-report-status-turkish-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "phase4-report-status-first-login-test-pw")
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
            ad="Phase4",
            soyad="ReportStatusContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        db.session.add(UserMenuPermission(user_id=user.id, menu_key="reports", is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def test_report_detail_page_shows_turkish_status_label(app, client) -> None:
    from app.extensions import db
    from app.models.communication_phase4_models import CommunicationExecutiveReport

    _create_user(app, sicil_no="p4_admin_detail")
    with app.app_context():
        report = CommunicationExecutiveReport(title="H1D contract report", period_label="2026-09", status="review")
        db.session.add(report)
        db.session.commit()
        report_id = report.id

    _login(client, "p4_admin_detail")
    response = client.get(f"/communication/faz4/reports/{report_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Durum: İncelemede" in body
    assert "Durum: review" not in body


@pytest.mark.parametrize(
    ("status", "expected_label"),
    [("draft", "Taslak"), ("approved", "Onaylandı"), ("revision", "Revizyon İstendi"), ("rejected", "Reddedildi")],
)
def test_report_detail_page_covers_every_known_status(app, client, status, expected_label) -> None:
    from app.extensions import db
    from app.models.communication_phase4_models import CommunicationExecutiveReport

    _create_user(app, sicil_no=f"p4_admin_{status}")
    with app.app_context():
        report = CommunicationExecutiveReport(title=f"H1D {status} report", period_label="2026-09", status=status)
        db.session.add(report)
        db.session.commit()
        report_id = report.id

    _login(client, f"p4_admin_{status}")
    response = client.get(f"/communication/faz4/reports/{report_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"Durum: {expected_label}" in body


def test_reports_list_history_table_shows_turkish_status_label(app, client) -> None:
    from app.extensions import db
    from app.models.communication_phase4_models import CommunicationExecutiveReport

    _create_user(app, sicil_no="p4_admin_list")
    with app.app_context():
        db.session.add(CommunicationExecutiveReport(title="List contract report", period_label="2026-09", status="rejected"))
        db.session.commit()

    _login(client, "p4_admin_list")
    response = client.get("/communication/faz4/reports")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Reddedildi" in body
    assert "<td>rejected</td>" not in body


def test_anonymous_user_still_redirected_on_both_routes(client) -> None:
    for path in ("/communication/faz4/reports", "/communication/faz4/reports/1"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, f"{path}: expected 302, got {response.status_code}"
        assert "/login" in (response.headers.get("Location") or "")
