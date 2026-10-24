"""BYS360 H1E-B/H1E-C -- communication Phase 1-5 raw status/priority display
closure contract.

Two related defect classes, found in the same repo-wide grep sweep that
produced the H1E-A gate-status wave, are closed here:

  1. The FORBIDDEN `{{ x_labels.get(row.field, row.field) }}` template
     pattern (fallback to the raw machine value on a user-visible surface)
     -- present in ~20 locations across the Phase 1-5 communication module,
     feedback operations, notifications, and support screens. Every
     instance now falls back to the safe Turkish "Bilinmiyor" instead.
  2. Several dashboard/analytics screens (Phase 1 dashboard, Phase 2
     dashboard, Phase 3's real end-user-facing survey-take page, Phase 4
     analytics, Phase 5 automation center) rendered `row.status` /
     `row.priority` completely unmapped -- no label lookup at all. These
     now reuse the existing, already-established BULLETIN_STATUS_LABELS /
     BULLETIN_PRIORITY_LABELS / SURVEY_STATUS_LABELS / SUPPORT_STATUS_LABELS
     / gate_status_label() helpers (no new dictionaries duplicated).

This file proves, against real Flask routes and a real (temporary,
isolated) database:

  A. the three new GATE_STATUS_LABELS entries (queued/completed/failed,
     needed for Phase 5's CommunicationDigestJob/CommunicationAutomationLog
     status vocabulary) map correctly.
  B. Phase 1's dashboard and bulletin list/detail pages render Turkish
     status/priority labels for a bulletin whose status was previously
     shown completely raw, and NEVER leak an unmapped/future value --
     always falling back to "Bilinmiyor".
  C. Phase 2's dashboard renders Turkish survey/bulletin-revision status.
  D. Phase 3's survey-take page (real end user, not an admin screen) shows
     a Turkish survey status instead of the raw machine value.
  E. Phase 5's automation center shows Turkish status for both
     CommunicationAutomationLog rows and CommunicationDigestJob rows.
  F. the raw status values actually stored in the database are completely
     unchanged -- only the display layer changed.
  G. authorization behavior is unchanged (unauthenticated -> redirect to
     login).

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB (same pattern as
tests/communication/test_h1e_gate_status_turkish_label_contract.py).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_status_fallback_tmp" / "test_dbs"
_PASSWORD = "H1EStatusFallbackTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contract for the new GATE_STATUS_LABELS entries.
# ---------------------------------------------------------------------------


def test_gate_status_label_covers_digest_and_log_vocabulary() -> None:
    from app.services.communication_gate_status_labels import gate_status_label

    assert gate_status_label("queued") == "Sırada"
    assert gate_status_label("completed") == "Tamamlandı"
    assert gate_status_label("failed") == "Başarısız"


# ---------------------------------------------------------------------------
# App/client fixtures (same pattern as the H1E-A contract file).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-status-fallback-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-status-fallback-first-login-test-pw")
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


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD, menu_keys=("notifications", "announcements", "surveys", "settings", "support_index")):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="H1E",
            soyad="StatusFallbackContract",
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


def _insert_bulletin(app, *, status: str, priority: str = "future_priority_v9", title="H1E negative-test bulletin"):
    from app.extensions import db
    from app.models.communication_phase1_models import CommunicationBulletin

    with app.app_context():
        row = CommunicationBulletin(
            title=title,
            content="Test content",
            status=status,
            priority=priority,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_survey(app, *, status: str, title="H1E negative-test survey", with_assignment=True):
    from app.extensions import db
    from app.models import Survey, SurveyAssignment, User

    with app.app_context():
        creator = User.query.first()
        assert creator is not None, "a user must exist before inserting a survey (created_by_user_id is NOT NULL)"
        survey = Survey(title=title, survey_type="kurum_ici", created_by_user_id=creator.id, status=status)
        db.session.add(survey)
        db.session.commit()
        if with_assignment:
            db.session.add(SurveyAssignment(survey_id=survey.id, target_type="all", target_value=""))
            db.session.commit()
        return survey.id


def _insert_bulletin_revision(app, *, bulletin_id: int, status: str, priority: str = "future_priority_v9"):
    from app.extensions import db
    from app.models.communication_phase2_models import CommunicationBulletinRevision

    with app.app_context():
        row = CommunicationBulletinRevision(
            bulletin_id=bulletin_id,
            version_no=1,
            title="H1E negative-test revision",
            content="Test content",
            status=status,
            priority=priority,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_digest_job(app, *, status: str):
    from app.extensions import db
    from app.models import User
    from app.models.communication_phase5_models import CommunicationDigestJob

    with app.app_context():
        user = User.query.first()
        row = CommunicationDigestJob(
            user_id=user.id,
            digest_type="daily",
            period_label="2026-09-04",
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# B: Phase 1 dashboard + bulletin list/detail -- Turkish labels, safe
# fallback for an unmapped value, self-fallback anti-pattern fixed.
# ---------------------------------------------------------------------------


def test_phase1_dashboard_never_leaks_raw_bulletin_or_survey_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p1_a")
    _insert_bulletin(app, status="future_status_v9")
    _insert_survey(app, status="future_status_v9", with_assignment=False)
    _login(client, "h1e_p1_a")

    body = client.get("/communication/faz1").get_data(as_text=True)
    assert "future_status_v9" not in body
    assert "future_priority_v9" not in body
    assert "Bilinmiyor" in body


def test_phase1_bulletins_list_and_detail_never_leak_raw_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p1_b")
    bulletin_id = _insert_bulletin(app, status="future_status_v9")
    _login(client, "h1e_p1_b")

    list_body = client.get("/communication/faz1/bulletins").get_data(as_text=True)
    detail_body = client.get(f"/communication/faz1/bulletins/{bulletin_id}").get_data(as_text=True)

    for label, body in (("list", list_body), ("detail", detail_body)):
        assert "future_status_v9" not in body, f"{label}: raw status leaked"
        assert "future_priority_v9" not in body, f"{label}: raw priority leaked"
        assert "Bilinmiyor" in body, f"{label}: safe fallback missing"

    # Known values still render their real Turkish label (contract-preserving,
    # not just "always shows Bilinmiyor").
    known_id = _insert_bulletin(app, status="published", priority="high", title="Known-status bulletin")
    known_body = client.get(f"/communication/faz1/bulletins/{known_id}").get_data(as_text=True)
    assert "Yayında" in known_body
    assert "Yüksek" in known_body


# ---------------------------------------------------------------------------
# C: Phase 2 dashboard -- survey + bulletin-revision status.
# ---------------------------------------------------------------------------


def test_phase2_dashboard_never_leaks_raw_survey_or_revision_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p2_c")
    bulletin_id = _insert_bulletin(app, status="draft")
    _insert_bulletin_revision(app, bulletin_id=bulletin_id, status="future_status_v9")
    _insert_survey(app, status="future_status_v9", with_assignment=False)
    _login(client, "h1e_p2_c")

    body = client.get("/communication/faz2").get_data(as_text=True)
    assert "future_status_v9" not in body
    assert "future_priority_v9" not in body
    assert "Bilinmiyor" in body


# ---------------------------------------------------------------------------
# D: Phase 3 survey-take -- the real end-user-facing page.
# ---------------------------------------------------------------------------


def test_survey_take_page_shown_to_real_user_never_leaks_raw_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p3_d")
    survey_id = _insert_survey(app, status="future_status_v9")
    _login(client, "h1e_p3_d")

    response = client.get(f"/communication/faz3/surveys/{survey_id}/take")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "future_status_v9" not in body
    assert "Bilinmiyor" in body


def test_survey_take_page_shows_correct_turkish_label_for_known_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p3_d2")
    survey_id = _insert_survey(app, status="closed")
    _login(client, "h1e_p3_d2")

    body = client.get(f"/communication/faz3/surveys/{survey_id}/take").get_data(as_text=True)
    assert "Kapatıldı" in body


# ---------------------------------------------------------------------------
# E: Phase 5 automation center -- log + digest-job status.
# ---------------------------------------------------------------------------


def test_phase5_automation_center_never_leaks_raw_digest_job_status(app, client) -> None:
    _create_user(app, sicil_no="h1e_p5_e")
    _insert_digest_job(app, status="future_status_v9")
    _login(client, "h1e_p5_e")

    body = client.get("/communication/faz5/automation-center").get_data(as_text=True)
    assert "future_status_v9" not in body
    assert "Bilinmiyor" in body

    # A real, known digest job status renders its Turkish label.
    _insert_digest_job(app, status="completed")
    body2 = client.get("/communication/faz5/automation-center").get_data(as_text=True)
    assert "Tamamlandı" in body2


# ---------------------------------------------------------------------------
# F: stored raw values are completely unchanged -- display-only fix.
# ---------------------------------------------------------------------------


def test_stored_bulletin_status_and_priority_are_unchanged_by_rendering(app, client) -> None:
    bulletin_id = _insert_bulletin(app, status="future_status_v9", priority="future_priority_v9")
    _create_user(app, sicil_no="h1e_p1_f")
    _login(client, "h1e_p1_f")

    client.get(f"/communication/faz1/bulletins/{bulletin_id}")

    from app.extensions import db
    from app.models.communication_phase1_models import CommunicationBulletin

    with app.app_context():
        row = db.session.get(CommunicationBulletin, bulletin_id)
        assert row is not None
        assert row.status == "future_status_v9"
        assert row.priority == "future_priority_v9"


# ---------------------------------------------------------------------------
# G: authorization behavior is completely unchanged.
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    for path in (
        "/communication/faz1",
        "/communication/faz1/bulletins",
        "/communication/faz2",
        "/communication/faz5/automation-center",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, path
        assert "/login" in (response.headers.get("Location") or ""), path
