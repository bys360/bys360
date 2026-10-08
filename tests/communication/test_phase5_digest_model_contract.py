"""BYS360 Faz 5 digest model-contract regression.

DEFECT -- POST /communication/faz5/preferences/digest
  communication_phase5_service.create_digest_job() read three ORM attributes
  that exist neither on the current models nor in any migration:
    - Notification.is_hidden
    - SurveyAssignment.user_id
    - SurveyAssignment.status
  Every call raised sqlalchemy InvalidRequestError, the route answered 500
  and no CommunicationDigestJob row was written.

FIX CONTRACT (proved below against a real Flask app + real temporary DB):
  - Notifications are counted on the real Notification.user_id and
    Notification.is_read columns. Notification has no hidden/dismiss concept;
    this is the same decision as the earlier health_snapshot() fix pinned in
    test_phase8_readiness_runtime_defect_contract.py.
  - surveys_pending is the number of rows returned by
    app.services.surveys.listing.get_assigned_surveys_for_user(user) whose
    state key is "active" -- the "Açık" count of the web /surveys page. No
    new matching rule or survey policy.
  - tickets_open keeps its existing semantics.

Anonymous-survey completion matching is existing web behavior and is
deliberately not asserted here.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB (same pattern as the other communication contract files).
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "phase5_digest_contract_tmp" / "test_dbs"
_PASSWORD = "Phase5DigestContractTest1!"
_DIGEST_PATH = "/communication/faz5/preferences/digest"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase5-digest-model-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "phase5-digest-contract-first-login-test-pw")
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
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="personel", birim=None, grant_menu_keys=("settings",)):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="Phase5",
            soyad="DigestContract",
            role=role,
            birim=birim,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(_PASSWORD)
        db.session.add(user)
        db.session.commit()
        for menu_key in grant_menu_keys:
            db.session.add(UserMenuPermission(user_id=user.id, menu_key=menu_key, is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": _PASSWORD}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _seed_notifications(user_id, other_id):
    from app.extensions import db
    from app.models import Notification

    rows = [
        (user_id, False),
        (user_id, False),
        (user_id, True),
        (other_id, False),
        (other_id, True),
        (other_id, True),
        (other_id, True),
    ]
    for index, (owner_id, is_read) in enumerate(rows):
        db.session.add(Notification(user_id=owner_id, title=f"Bildirim {index}", notification_type="info", is_read=is_read))
    db.session.commit()


def _seed_surveys(user_id, other_id):
    """Seed one survey per web /surveys state; returns {name: survey_id}."""
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import Survey, SurveyAssignment, SurveyResponse

    now = utc_now()
    past = now - timedelta(days=10)
    future = now + timedelta(days=10)
    specs: dict[str, tuple[str, datetime | None, datetime | None, list[tuple[str, str | None]]]] = {
        # name: (status, start_at, end_at, [(target_type, target_value)])
        "open": ("published", past, future, [("user", str(user_id)), ("all", None)]),
        "started": ("published", None, None, [("unit", "P5DG BIRIMI")]),
        "completed": ("published", past, future, [("user", str(user_id))]),
        "upcoming": ("published", future, future + timedelta(days=10), [("all", None)]),
        "expired": ("published", past - timedelta(days=10), past, [("all", None)]),
        "unmatched_user": ("published", past, future, [("user", str(other_id))]),
        "unmatched_role": ("published", past, future, [("role", "baskan")]),
        "draft": ("draft", past, future, [("all", None)]),
    }
    ids: dict[str, int] = {}
    assignments: dict[str, int] = {}
    for name, (status, start_at, end_at, targets) in specs.items():
        survey = Survey(title=f"P5DG {name}", status=status, start_at=start_at, end_at=end_at, created_by_user_id=other_id)
        db.session.add(survey)
        db.session.flush()
        ids[name] = survey.id
        for target_type, target_value in targets:
            assignment = SurveyAssignment(survey_id=survey.id, target_type=target_type, target_value=target_value)
            db.session.add(assignment)
            db.session.flush()
            assignments.setdefault(name, assignment.id)
    db.session.add_all([
        # Started but not completed by the user: still open on the web list.
        SurveyResponse(survey_id=ids["started"], user_id=user_id, assignment_id=assignments["started"], is_completed=False),
        # Completed by the user (non-anonymous): no longer open for the user.
        SurveyResponse(survey_id=ids["completed"], user_id=user_id, assignment_id=assignments["completed"], is_completed=True, submitted_at=now),
        # Completed by someone else: must not close the survey for the user.
        SurveyResponse(survey_id=ids["open"], user_id=other_id, assignment_id=assignments["open"], is_completed=True, submitted_at=now),
    ])
    db.session.commit()
    return ids


def _seed_tickets(user_id, other_id):
    from app.extensions import db
    from app.models import SupportTicket

    rows = [
        ("P5DG-1", user_id, None, "open"),
        ("P5DG-2", user_id, None, "reviewing"),
        ("P5DG-3", user_id, None, "closed"),
        ("P5DG-4", other_id, None, "open"),
        ("P5DG-5", other_id, user_id, "open"),
    ]
    for ticket_no, creator_id, assignee_id, status in rows:
        db.session.add(
            SupportTicket(
                ticket_no=ticket_no,
                title=f"Talep {ticket_no}",
                description="Faz 5 digest sözleşme testi",
                ticket_type="question",
                module_name="communication",
                status=status,
                created_by_user_id=creator_id,
                assigned_to_user_id=assignee_id,
            )
        )
    db.session.commit()


def _seed_all(app):
    user_id = _create_user(app, sicil_no="p5dg_user", birim="p5dg birimi")
    other_id = _create_user(app, sicil_no="p5dg_other", birim="Başka Birim", grant_menu_keys=())
    with app.app_context():
        _seed_notifications(user_id, other_id)
        survey_ids = _seed_surveys(user_id, other_id)
        _seed_tickets(user_id, other_id)
    return user_id, other_id, survey_ids


def _create_digest(app, user_id, digest_type="daily"):
    from app.extensions import db
    from app.models import User
    from app.services.communication_phase5_service import create_digest_job

    with app.app_context():
        user = db.session.get(User, user_id)
        row = create_digest_job(user, digest_type=digest_type)
        return {"id": row.id, "payload": dict(row.payload_json or {}), "summary": row.result_summary, "status": row.status}


# ---------------------------------------------------------------------------
# 1. Route level -- the endpoint no longer answers 500 and writes a job.
# ---------------------------------------------------------------------------


def test_digest_route_redirects_and_creates_job_on_empty_db(app, client) -> None:
    from app.models.communication_phase5_models import CommunicationDigestJob

    user_id = _create_user(app, sicil_no="p5dg_route")
    _login(client, "p5dg_route")

    response = client.post(_DIGEST_PATH, data={"digest_type": "daily"}, follow_redirects=False)

    assert response.status_code == 302, f"{_DIGEST_PATH} returned {response.status_code}, expected 302"
    assert response.headers.get("Location", "").endswith("/communication/faz5/preferences")
    with app.app_context():
        jobs = CommunicationDigestJob.query.filter_by(user_id=user_id).all()
        assert len(jobs) == 1
        assert jobs[0].status == "completed"
        assert jobs[0].payload_json == {
            "notifications_unread": 0,
            "notifications_total": 0,
            "surveys_pending": 0,
            "tickets_open": 0,
        }


def test_digest_route_with_populated_data_writes_expected_payload(app, client) -> None:
    from app.models.communication_phase5_models import CommunicationDigestJob

    user_id, _other_id, _survey_ids = _seed_all(app)
    _login(client, "p5dg_user")

    response = client.post(_DIGEST_PATH, data={"digest_type": "weekly"}, follow_redirects=False)

    assert response.status_code == 302, f"{_DIGEST_PATH} returned {response.status_code}, expected 302"
    with app.app_context():
        job = CommunicationDigestJob.query.filter_by(user_id=user_id).one()
        assert job.digest_type == "weekly"
        assert job.payload_json == {
            "notifications_unread": 2,
            "notifications_total": 3,
            "surveys_pending": 2,
            "tickets_open": 2,
        }


# ---------------------------------------------------------------------------
# 2. Service level -- create_digest_job counts on the real model contract.
# ---------------------------------------------------------------------------


def test_create_digest_job_counts_only_own_notifications(app) -> None:
    user_id, other_id, _survey_ids = _seed_all(app)

    own = _create_digest(app, user_id)["payload"]
    other = _create_digest(app, other_id)["payload"]

    # 7 notifications / 3 unread exist in total; each digest sees only its own.
    assert own["notifications_total"] == 3
    assert own["notifications_unread"] == 2
    assert other["notifications_total"] == 4
    assert other["notifications_unread"] == 1


def test_create_digest_job_surveys_pending_matches_web_open_state(app) -> None:
    from app.extensions import db
    from app.models import User
    from app.services.surveys.listing import get_assigned_surveys_for_user

    user_id, _other_id, survey_ids = _seed_all(app)

    with app.app_context():
        rows = get_assigned_surveys_for_user(db.session.get(User, user_id))
        states = {row["survey"].id: row["state"]["key"] for row in rows}

    # The fixture really produces each web /surveys state for this user.
    assert states == {
        survey_ids["open"]: "active",
        survey_ids["started"]: "active",
        survey_ids["completed"]: "completed",
        survey_ids["upcoming"]: "upcoming",
        survey_ids["expired"]: "expired",
    }
    # Not matched by any assignment, or not published: not listed at all.
    for name in ("unmatched_user", "unmatched_role", "draft"):
        assert survey_ids[name] not in states

    payload = _create_digest(app, user_id)["payload"]

    # Only open + started count: completed, upcoming, expired, unmatched and
    # draft surveys are excluded, and the open survey is counted once even
    # though two of its assignments match.
    assert payload["surveys_pending"] == 2
    assert payload["surveys_pending"] == sum(1 for key in states.values() if key == "active")


def test_create_digest_job_keeps_open_ticket_semantics(app) -> None:
    user_id, _other_id, _survey_ids = _seed_all(app)

    payload = _create_digest(app, user_id)["payload"]

    # Own open + reviewing tickets; not the closed one, not tickets created by
    # someone else (even when assigned to the user).
    assert payload["tickets_open"] == 2


def test_create_digest_job_persists_completed_job_and_audit_log(app) -> None:
    from app.models.communication_phase5_models import (
        CommunicationAutomationLog,
        CommunicationDigestJob,
    )

    user_id, _other_id, _survey_ids = _seed_all(app)

    created = _create_digest(app, user_id, digest_type="daily")

    assert created["status"] == "completed"
    assert created["summary"] == "Okunmamış bildirim: 2 | Açık destek talebi: 2 | Bekleyen anket: 2"
    with app.app_context():
        job = CommunicationDigestJob.query.filter_by(id=created["id"], user_id=user_id).one()
        assert job.digest_type == "daily"
        assert job.period_label.startswith("Daily özeti - ")
        assert job.executed_at is not None
        log = CommunicationAutomationLog.query.filter_by(action_type="create_digest", target_id=job.id).one()
        assert log.status == "success"
        assert log.actor_user_id == user_id
