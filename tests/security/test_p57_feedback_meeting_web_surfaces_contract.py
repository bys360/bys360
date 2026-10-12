"""Contract #57 (web surfaces): the feedback meeting and request pages follow the same object rule.

Approved policy (HUMAN_POLICY_APPROVED, 2026-10-10): meeting and feedback records reach only their
parties or people with an explicitly defined duty relation; a role alone (admin, başkan, the
technical roles, a manager of another team) widens nothing; list, detail, search, export and
report use the same object check.

The independent review of #57 (head 18e115f5, re-verified on 035443e6) found 15 leaks outside the
aftercare/integration pages, where the role scope (``build_surface_scope_context``: "all" for
admin/başkan, the whole unit for a birim_sorumlusu) or an ``role == "admin"`` shortcut decided:

* ``/performance/feedback-meetings/<id>`` (detail), ``/performance/feedback-meetings`` (default
  and ``scope=all``) and ``/performance/feedback-ops`` showed the meeting note and the employee's
  name; ``/performance/feedback-requests?scope=all`` showed the employee's name;
* each for P57OMG (birim_sorumlusu of another team in the same unit), P57ADM (admin) and P57BSK
  (başkan): 5 surfaces x 3 users = 15.

Rule now (``app/performance/feedback_helpers.py``): a meeting is visible to its employee, its
manager and the managers its request names (level 1-3, scheduler); a request to its employee and
its named managers. The same relation filter feeds every page built on
``_load_scoped_feedback_data`` (operations, watch, alerts, executive summary, digest, go-live
centre and its exports, pilot simulation); the scope switch only narrows it. Writes (request
update, schedule, schedule preview, meeting update) need the duty relation; no role shortcut.

Labels: ``test_guard_*`` pass before and after; ``test_leak_*`` are the 15 verified leaks; every
other test also fails on 035443e6.
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
_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p57_web_surfaces")

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
        "APP_ENV": "testing", "FLASK_ENV": "testing", "SECRET_KEY": "test-secret-key-p57-web-surfaces",
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




def _met_request(app):
    return int(_scalar(app, "SELECT feedback_request_id FROM feedback_meetings WHERE id = :mid", mid=_data(app)["meeting"]))


def _get(app, sicil, path):
    return _client(app, sicil).get(path, follow_redirects=True)


# The 15 leaks verified on 035443e6 (5 surfaces x P57OMG / P57ADM / P57BSK).
_LEAK_PATHS = (
    "/performance/feedback-meetings/{meeting}",
    "/performance/feedback-meetings",
    "/performance/feedback-meetings?scope=all",
    "/performance/feedback-requests?scope=all",
    "/performance/feedback-ops",
)
_LEAK_USERS = ("P57OMG", "P57ADM", "P57BSK")


@pytest.mark.parametrize("sicil", _LEAK_USERS)
@pytest.mark.parametrize("path", _LEAK_PATHS)
def test_leak_closed(env, path, sicil):
    body = _get(env, sicil, path.format(meeting=_data(env)["meeting"])).get_data(as_text=True)
    assert _leaks(body, (NOTE, EMPLOYEE_NAME)) == [], (sicil, path)


# Every other page built on the same scope or loader, for every outsider.
_ALL_READ_PATHS = (
    "/performance/feedback-meetings/{meeting}",
    "/performance/feedback-meetings",
    "/performance/feedback-meetings?scope=all",
    "/performance/feedback-meetings?scope=team",
    "/performance/feedback-meetings?scope=all&q=Gizlikisi",
    "/performance/feedback-meetings?scope=all&view=my_managed",
    "/performance/feedback-requests",
    "/performance/feedback-requests?scope=all",
    "/performance/feedback-requests?scope=team",
    "/performance/feedback-requests/{met_request}",
    "/performance/feedback-requests/{open_request}",
    "/performance/feedback-ops?scope=all",
    "/performance/feedback-watch?scope=all",
    "/performance/feedback-executive-summary?scope=all",
    "/performance/feedback-audit?scope=all",
    "/performance/go-live-center?scope=all",
    "/performance/go-live-center/uat?scope=all",
    "/performance/go-live-center/uat/export.txt?scope=all",
    "/performance/go-live-center/issues.csv?scope=all",
    "/performance/go-live-center/release-packet.txt?scope=all",
    "/performance/go-live-center/smoke-test?scope=all",
    "/performance/go-live-center/smoke-test.csv?scope=all",
    "/performance/go-live-center/management-brief.txt?scope=all",
    "/performance/pilot-simulation-center?scope=all",
    "/performance/feedback-reports",
    "/performance/operations-center",
)


@pytest.mark.parametrize("sicil", OUTSIDERS)
def test_outsiders_see_nothing_of_the_employee_on_any_feedback_page(env, sicil):
    data = _data(env)
    fmt = {"meeting": data["meeting"], "met_request": _met_request(env), "open_request": data["open_request"]}
    client = _client(env, sicil)
    leaked = {}
    for path in _ALL_READ_PATHS:
        body = client.get(path.format(**fmt), follow_redirects=True).get_data(as_text=True)
        found = _leaks(body, (NOTE, EMPLOYEE_NAME))
        if found:
            leaked[path] = found
    assert leaked == {}, sicil


# --- writes and IDOR: no role shortcut ------------------------------------------------------


def _meeting_row(app):
    from app.extensions import db

    with app.app_context():
        row = db.session.execute(
            text("SELECT status, note, manager_id FROM feedback_meetings WHERE id = :mid"), {"mid": _data(app)["meeting"]}
        ).one()
        return tuple(row)


@pytest.mark.parametrize("sicil", ROLE_ONLY_MANAGERS)
def test_outsiders_cannot_update_the_meeting(env, sicil):
    before = _meeting_row(env)
    _client(env, sicil).post(
        f"/performance/feedback-meetings/{_data(env)['meeting']}/update",
        data={"status": "iptal_edildi", "note": "P57-OUTSIDER-WRITE", "meeting_date": "2026-10-01",
              "meeting_start": "10:00", "meeting_end": "10:30"},
    )
    assert _meeting_row(env) == before


@pytest.mark.parametrize("sicil", ROLE_ONLY_MANAGERS)
def test_outsiders_cannot_answer_or_close_the_request(env, sicil):
    request_id = _met_request(env)
    before = _scalar(env, "SELECT status FROM feedback_requests WHERE id = :rid", rid=request_id)
    _client(env, sicil).post(f"/performance/feedback-requests/{request_id}",
                             data={"status": "kapatildi", "response": "P57-OUTSIDER-RESPONSE"})
    assert _scalar(env, "SELECT status FROM feedback_requests WHERE id = :rid", rid=request_id) == before


@pytest.mark.parametrize("sicil", ROLE_ONLY_MANAGERS)
def test_outsiders_get_no_schedule_preview(env, sicil):
    response = _client(env, sicil).get(
        f"/performance/feedback-requests/{_data(env)['open_request']}/schedule-preview?meeting_date=2026-10-20"
    )
    assert response.status_code == 403
    assert _leaks(response.get_data(as_text=True), (NOTE, EMPLOYEE_NAME)) == []


@pytest.mark.parametrize("sicil", ROLE_ONLY_MANAGERS)
def test_outsiders_cannot_schedule_a_meeting_for_the_request(env, sicil):
    request_id = _data(env)["open_request"]
    _client(env, sicil).post(
        f"/performance/feedback-requests/{request_id}/schedule",
        data={"meeting_date": "2026-10-20", "meeting_start": "11:00", "meeting_end": "11:30",
              "meeting_type": "yuz_yuze", "location": "Oda", "note": "P57-OUTSIDER-SCHEDULE"},
    )
    assert _scalar(env, "SELECT COUNT(*) FROM feedback_meetings WHERE feedback_request_id = :rid", rid=request_id) == 0


# --- parties and named managers keep their pages ------------------------------------------------


@pytest.mark.parametrize("sicil", ["P57EMP", "P57MGR"])
def test_guard_parties_see_the_meeting_detail(env, sicil):
    assert NOTE in _client(env, sicil).get(f"/performance/feedback-meetings/{_data(env)['meeting']}").get_data(as_text=True)


def test_guard_the_meeting_manager_sees_the_meeting_in_the_list(env):
    # The list needs the performance_feedback_meetings menu, which the personel role does not have.
    assert EMPLOYEE_NAME in _client(env, "P57MGR").get("/performance/feedback-meetings?scope=all").get_data(as_text=True)


def test_guard_the_named_manager_sees_the_request_list_and_detail(env):
    client = _client(env, "P57MGR")
    assert EMPLOYEE_NAME in client.get("/performance/feedback-requests?scope=all").get_data(as_text=True)
    assert EMPLOYEE_NAME in client.get(f"/performance/feedback-requests/{_met_request(env)}").get_data(as_text=True)


def test_guard_the_named_manager_gets_the_schedule_preview(env):
    response = _client(env, "P57MGR").get(
        f"/performance/feedback-requests/{_data(env)['open_request']}/schedule-preview?meeting_date=2026-10-20"
    )
    assert response.status_code == 200


def test_guard_the_meeting_manager_updates_the_meeting(env):
    _client(env, "P57MGR").post(
        f"/performance/feedback-meetings/{_data(env)['meeting']}/update",
        data={"status": "ertelendi", "note": "P57-MANAGER-UPDATE", "meeting_date": "2026-10-02",
              "meeting_start": "10:00", "meeting_end": "10:30"},
    )
    status, note, _manager = _meeting_row(env)
    assert status == "ertelendi" and "P57-MANAGER-UPDATE" in (note or "")


# Independent review of 0c002960: the action-plan follow-up page and the digest fan-out ----------


def _execute(env, sql, **params):
    from sqlalchemy import text

    from app.extensions import db

    with env.app_context():
        db.session.execute(text(sql), params)
        db.session.commit()


@pytest.mark.parametrize("sicil", ["P57ADM", "P57BSK", "P57SYS", "P57OMG", "P57COL"])
def test_followup_page_hides_another_persons_action_plan(env, sicil):
    body = _client(env, sicil).get("/performance/feedback-followup?filter=all").get_data(as_text=True)
    assert ACTION not in body and EMPLOYEE_NAME not in body


@pytest.mark.parametrize("sicil", ["P57ADM", "P57BSK"])
def test_followup_quick_update_is_refused_to_non_parties(env, sicil):
    action_id = _data(env)["action"]
    _client(env, sicil).post(
        f"/performance/feedback-followup/actions/{action_id}/quick-update",
        data={"status": "tamamlandi", "follow_up_note": f"R71-{sicil}", "result_summary": f"R71-{sicil}"},
    )
    row = _scalar(
        env,
        "SELECT COALESCE(follow_up_note,'') || '|' || COALESCE(status,'') FROM feedback_meeting_action_plans WHERE id=:a",
        a=action_id,
    )
    assert f"R71-{sicil}" not in (row or "") and "tamamlandi" not in (row or "")


def test_digest_mail_reaches_each_manager_with_only_their_records(env, monkeypatch):
    import app.services.performance.feedback_executive_summary_service as svc

    sent: list[tuple[str, str]] = []

    def fake_send_email(to, subject, body, *args, **kwargs):
        sent.append((to, body))
        return True, "ok"

    monkeypatch.setattr(svc, "send_email", fake_send_email)
    data = _data(env)
    _execute(env, "UPDATE feedback_requests SET level_2_manager_id=:m WHERE id=:r", m=data["ids"]["P57MGR"], r=data["rep_request"])
    _execute(env, "UPDATE feedback_requests SET requested_at='2026-01-01 00:00:00' WHERE id=:r", r=data["open_request"])
    _client(env, "P57MGR").post(
        "/performance/feedback-executive-summary/run-digest",
        data={"scope": "all", "preset": "daily", "send_email": "1"},
    )
    to_other_manager = [body for to, body in sent if to.startswith("p57omg")]
    assert to_other_manager and not any(EMPLOYEE_NAME in body for body in to_other_manager), sent


@pytest.mark.parametrize("sicil", ["P57ADM", "P57BSK"])
def test_generating_notices_from_the_web_never_exposes_other_persons_notices(env, sicil):
    client = _client(env, sicil)
    client.post("/performance/feedback-followup/generate-notices")
    body = client.get("/performance/feedback-followup?filter=all").get_data(as_text=True)
    assert ACTION not in body and EMPLOYEE_NAME not in body
