"""Contract #57: feedback meetings and requests follow one party / duty-relation object rule.

Approved policy (HUMAN_POLICY_APPROVED, 2026-10-10):

* Normal staff see only their own requests and the records they are entitled to.
* A manager role alone does not reveal other people's meeting notes or requests.
* Only explicitly authorised managers create meetings.
* Being a party to the meeting, or a defined duty relation, grants access.
* List, detail, search, export and report use the same object check.

Before (#57 HOLD findings, plus the paths found while closing it):

* the open-request picker listed every open request of the institution to every manager role;
* the integration page showed meeting notes, after-meeting summaries and action plans to managers
  who were not a party to the meeting;
* the aftercare list, detail and every write (preparation, after-meeting note, action plans) were
  open to every "global" role (admin, sistem_yoneticisi, system_admin, super_admin, başkan,
  başkan yardımcısı) for every meeting;
* any manager role could create a meeting from any open request, or for any person and period,
  which made it a party to that employee's meeting; the person picker listed every active user.

Rule now (``app/services/performance/feedback_meeting_access.py``): a meeting is visible and
editable only to its employee and its manager; a request is visible to its employee and the
managers it names; a meeting is created only by a manager role with a duty relation to the employee.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

PASSWORD = "P57MeetingPrivacyTest1!"
NOTE = "P57-MEETING-NOTE-MARKER"
SUMMARY = "P57-AFTER-SUMMARY-MARKER"
ACTION = "P57-ACTION-TITLE-MARKER"
EMPLOYEE_NAME = "Gizlikisi P57EMP"
_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p57_meeting_privacy")

# sicil -> (role, yonetici_sicil)
USERS = {
    "P57EMP": ("personel", "P57MGR"),       # the employee
    "P57MGR": ("birim_sorumlusu", None),    # its hierarchy manager, named on the request, meeting manager
    "P57OMG": ("birim_sorumlusu", None),    # a manager of another team
    "P57REP": ("personel", "P57OMG"),       # that manager's own report
    "P57COL": ("personel", "P57MGR"),       # a colleague of the employee
    "P57ADM": ("admin", None),
    "P57SYS": ("sistem_yoneticisi", None),
    "P57BSK": ("baskan", None),
}
OUTSIDERS = ["P57OMG", "P57COL", "P57ADM", "P57SYS", "P57BSK"]
ROLE_ONLY_MANAGERS = ["P57OMG", "P57ADM", "P57SYS", "P57BSK"]
MEETING_TOKENS = (NOTE, SUMMARY, ACTION)
PRIVATE_TOKENS = MEETING_TOKENS + (EMPLOYEE_NAME,)


@pytest.fixture
def env(monkeypatch):
    for key, value in {
        "APP_ENV": "testing", "FLASK_ENV": "testing", "SECRET_KEY": "test-secret-key-p57-meeting-privacy",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "p57-meeting-privacy-first-login", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_DB_DIR, exist_ok=True)
    uri = "sqlite:///" + os.path.join(_DB_DIR, f"p57_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", uri)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import User
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        ids = {}
        for sicil, (role, manager) in USERS.items():
            first, last = ("Gizlikisi", sicil) if sicil == "P57EMP" else ("Kullanici", sicil)
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@bys360.test", ad=first, soyad=last, role=role,
                        yonetici_sicil=manager, birim="Birim A", is_active=True, must_change_password=False,
                        must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = int(user.id)
        request_sql = text(
            "INSERT INTO feedback_requests (evaluation_id, period_id, employee_id, level_1_manager_id, reason, status, "
            "requested_at) VALUES (1, :period, :employee, :manager, :reason, 'bekliyor', CURRENT_TIMESTAMP) RETURNING id")
        open_request = db.session.execute(request_sql, {"period": 1, "employee": ids["P57EMP"], "manager": ids["P57MGR"],
                                                        "reason": "acik talep"}).scalar_one()
        met_request = db.session.execute(request_sql, {"period": 2, "employee": ids["P57EMP"], "manager": ids["P57MGR"],
                                                       "reason": "gorusulen talep"}).scalar_one()
        rep_request = db.session.execute(request_sql, {"period": 3, "employee": ids["P57REP"], "manager": ids["P57OMG"],
                                                       "reason": "diger ekip talebi"}).scalar_one()
        meeting = db.session.execute(text(
            "INSERT INTO feedback_meetings (feedback_request_id, employee_id, manager_id, meeting_date, meeting_start, "
            "meeting_end, meeting_type, note, status, created_at) VALUES (:request, :employee, :manager, '2026-10-01', "
            "'10:00:00', '10:30:00', 'yuz_yuze', :note, 'planlandi', CURRENT_TIMESTAMP) RETURNING id"),
            {"request": met_request, "employee": ids["P57EMP"], "manager": ids["P57MGR"], "note": NOTE}).scalar_one()
        db.session.execute(text(
            "INSERT INTO feedback_meeting_after_notes (meeting_id, manager_id, meeting_summary, closure_status, created_at, "
            "updated_at) VALUES (:meeting, :manager, :summary, 'taslak', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"meeting": meeting, "manager": ids["P57MGR"], "summary": SUMMARY})
        action = db.session.execute(text(
            "INSERT INTO feedback_meeting_action_plans (meeting_id, employee_id, manager_id, title, responsible_role, "
            "status, created_at, updated_at) VALUES (:meeting, :employee, :manager, :title, 'ortak', 'acik', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"),
            {"meeting": meeting, "employee": ids["P57EMP"], "manager": ids["P57MGR"], "title": ACTION}).scalar_one()
        db.session.commit()
        flask_app.config["_P57"] = {"ids": ids, "open_request": int(open_request), "rep_request": int(rep_request),
                                    "meeting": int(meeting), "action": int(action)}
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), sicil
    return client


def _data(app):
    return app.config["_P57"]


def _scalar(app, sql, **params):
    from app.extensions import db

    with app.app_context():
        return db.session.execute(text(sql), params).scalar()


def _leaks(text_value, tokens=PRIVATE_TOKENS):
    return [token for token in tokens if token in text_value]


# --- list, picker and search: nothing of the employee for outsiders -------------------------


@pytest.mark.parametrize("sicil", OUTSIDERS)
@pytest.mark.parametrize("path", ["/performance/feedback-aftercare", "/performance/feedback-aftercare/new",
                                  "/performance/feedback-aftercare?q=Gizlikisi", "/performance/feedback-integration"])
def test_outsiders_see_no_meeting_request_or_person_of_the_employee(env, sicil, path):
    response = _client(env, sicil).get(path)
    assert response.status_code == 200, (path, response.status_code)
    body = response.get_data(as_text=True)
    # The integration page's people picker, scorecards and interim notes are the performance (D2/D3)
    # package; #57 covers its meeting data.
    tokens = MEETING_TOKENS if "integration" in path else PRIVATE_TOKENS
    assert _leaks(body, tokens) == []
    assert f'<option value="{_data(env)["open_request"]}">' not in body


@pytest.mark.parametrize("sicil", OUTSIDERS)
def test_outsiders_cannot_open_the_meeting_detail(env, sicil):
    response = _client(env, sicil).get(f"/performance/feedback-aftercare/{_data(env)['meeting']}", follow_redirects=True)
    assert _leaks(response.get_data(as_text=True)) == []


@pytest.mark.parametrize("sicil", OUTSIDERS)
def test_outsiders_get_no_meeting_rows_from_the_integration_service(env, sicil):
    from app.services.performance.feedback_integration import build_integration_context

    ids = _data(env)["ids"]
    role = USERS[sicil][0]
    with env.app_context():
        for employee_id in (None, ids["P57EMP"]):
            ctx = build_integration_context(current_user_id=ids[sicil], current_user_role=role,
                                            is_admin=role in {"admin", "sistem_yoneticisi"}, employee_id=employee_id)
            assert ctx["aftercare_meetings"] == [] and ctx["action_plans"] == [], (sicil, employee_id)


# --- parties and the named manager keep their records ------------------------------------------


@pytest.mark.parametrize("sicil", ["P57EMP", "P57MGR"])
def test_parties_see_the_meeting_its_note_and_actions(env, sicil):
    client = _client(env, sicil)
    detail = client.get(f"/performance/feedback-aftercare/{_data(env)['meeting']}").get_data(as_text=True)
    assert NOTE in detail and SUMMARY in detail and ACTION in detail
    # The integration page shows the after-meeting summary (or the meeting note when there is none).
    assert SUMMARY in client.get("/performance/feedback-integration").get_data(as_text=True)


def test_the_named_manager_is_offered_the_open_request(env):
    body = _client(env, "P57MGR").get("/performance/feedback-aftercare").get_data(as_text=True)
    assert f'<option value="{_data(env)["open_request"]}">' in body


@pytest.mark.parametrize("sicil,reports", [("P57MGR", {"P57EMP", "P57COL"}), ("P57OMG", {"P57REP"}), ("P57ADM", set()),
                                            ("P57SYS", set()), ("P57BSK", set()), ("P57EMP", set())])
def test_the_person_picker_offers_only_the_users_own_reports(env, sicil, reports):
    from app.services.performance.feedback_aftercare_phase7_person_period import (
        build_phase7_1_context,
    )

    ids = _data(env)["ids"]
    role = USERS[sicil][0]
    with env.app_context():
        options = build_phase7_1_context(current_user_id=ids[sicil], current_user_role=role,
                                         is_admin=role in {"admin", "sistem_yoneticisi"})["person_options"]
    assert {int(row["id"]) for row in options} == {ids[key] for key in reports}


# --- writes: no outsider writes into the meeting -----------------------------------------------


@pytest.mark.parametrize("sicil", OUTSIDERS)
def test_outsiders_cannot_write_into_the_meeting(env, sicil):
    data = _data(env)
    client = _client(env, sicil)
    meeting = data["meeting"]
    client.post(f"/performance/feedback-aftercare/{meeting}/preparation", data={"purpose": "P57-INJECT-PREP"})
    client.post(f"/performance/feedback-aftercare/{meeting}/after-note", data={"meeting_summary": "P57-INJECT-NOTE"})
    client.post(f"/performance/feedback-aftercare/{meeting}/actions", data={"title": "P57-INJECT-ACTION"})
    client.post(f"/performance/feedback-aftercare/actions/{data['action']}/update",
                data={"status": "tamamlandi", "follow_up_note": "P57-INJECT-FOLLOW"})
    assert _scalar(env, "SELECT COUNT(*) FROM feedback_meeting_preparations WHERE purpose = 'P57-INJECT-PREP'") == 0
    assert _scalar(env, "SELECT meeting_summary FROM feedback_meeting_after_notes WHERE meeting_id = :m", m=meeting) == SUMMARY
    assert _scalar(env, "SELECT COUNT(*) FROM feedback_meeting_action_plans WHERE title = 'P57-INJECT-ACTION'") == 0
    assert _scalar(env, "SELECT status FROM feedback_meeting_action_plans WHERE id = :a", a=data["action"]) == "acik"


def test_the_meeting_manager_keeps_writing(env):
    meeting = _data(env)["meeting"]
    _client(env, "P57MGR").post(f"/performance/feedback-aftercare/{meeting}/after-note",
                                data={"meeting_summary": "P57-MANAGER-UPDATE"})
    assert _scalar(env, "SELECT meeting_summary FROM feedback_meeting_after_notes WHERE meeting_id = :m",
                   m=meeting) == "P57-MANAGER-UPDATE"


# --- creating a meeting needs a duty relation ---------------------------------------------------


def _meetings_for(app, request_id):
    return _scalar(app, "SELECT COUNT(*) FROM feedback_meetings WHERE feedback_request_id = :r", r=request_id)


@pytest.mark.parametrize("sicil", ROLE_ONLY_MANAGERS + ["P57COL"])
def test_role_only_managers_cannot_create_a_meeting_for_the_employee(env, sicil):
    data = _data(env)
    client = _client(env, sicil)
    client.post("/performance/feedback-aftercare/create", data={"feedback_request_id": str(data["open_request"])})
    client.post("/performance/feedback-aftercare/create-person-period",
                data={"employee_id": str(data["ids"]["P57EMP"]), "period_id": "1"})
    assert _meetings_for(env, data["open_request"]) == 0
    assert _scalar(env, "SELECT COUNT(*) FROM feedback_meetings WHERE manager_id = :u", u=data["ids"][sicil]) == 0


def test_the_named_manager_creates_the_meeting_from_the_request(env):
    data = _data(env)
    _client(env, "P57MGR").post("/performance/feedback-aftercare/create",
                                data={"feedback_request_id": str(data["open_request"])})
    assert _meetings_for(env, data["open_request"]) == 1


def test_the_hierarchy_manager_creates_a_person_period_meeting(env):
    data = _data(env)
    _client(env, "P57MGR").post("/performance/feedback-aftercare/create-person-period",
                                data={"employee_id": str(data["ids"]["P57EMP"]), "period_id": "1"})
    assert _meetings_for(env, data["open_request"]) == 1


def test_another_manager_creates_meetings_only_for_its_own_reports(env):
    data = _data(env)
    _client(env, "P57OMG").post("/performance/feedback-aftercare/create",
                                data={"feedback_request_id": str(data["rep_request"])})
    assert _meetings_for(env, data["rep_request"]) == 1
