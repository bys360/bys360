"""Contract: the feedback-aftercare lists show existing records instead of always being empty.

Both lists build raw SQL that referenced a column the query cannot see. The query failed every
time, and the module's ``_rows`` helper swallowed the error and returned ``[]``, so the pages
answered 200 with an empty list:

  1. Open feedback-request picker on GET /performance/feedback-aftercare
     (feedback_aftercare_phase7.list_open_feedback_requests). _user_label_expr put
     ``u.username`` into the label expression; no model or migration defines users.username.
     The sibling feedback_aftercare_phase7_person_period._user_label_expr adds a column only
     when the users table has it.

  2. Meetings section on GET /performance/feedback-integration
     (feedback_integration.aftercare_rows). ``p.title`` was selected whenever
     performance_periods exists, but ``performance_periods p`` is joined only when
     feedback_meetings has a period column, which it does not.

Real Flask app, real test client and login, file-backed SQLite only.

#57 policy (HUMAN_POLICY_APPROVED, 2026-10-10): the picker offers a manager only the requests that
name it as a manager, and a meeting reaches only its parties. The admin below is therefore the
requests' level-1 manager and the meeting's manager; ``tests/security/test_p57_feedback_meeting_
privacy_contract.py`` covers the users who are neither.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

_PASSWORD = "FeedbackAftercareListsTest1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_feedback_aftercare_lists")
_MEETING_NOTE = "FBLISTS-MEETING-NOTE-MARKER"


@pytest.fixture
def aftercare_app(monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-feedback-aftercare-lists-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "test-password",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"aftercare_lists_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

    from app.extensions import db
    from app.models import User
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
        ids = {}
        for sicil, role in (("FAL000001", "admin"), ("FAL000002", "personel")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@bys360.test", ad="Aftercare", soyad=sicil, role=role,
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(_PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = int(user.id)
        admin_id, employee_id = ids["FAL000001"], ids["FAL000002"]
        request_sql = text(
            "INSERT INTO feedback_requests (evaluation_id, period_id, employee_id, level_1_manager_id, reason, status, "
            "requested_at) VALUES (1, 1, :employee_id, :manager_id, :reason, 'bekliyor', CURRENT_TIMESTAMP) RETURNING id"
        )
        request_params = {"employee_id": employee_id, "manager_id": admin_id}
        open_request_id = db.session.execute(request_sql, {**request_params, "reason": "Açık talep"}).scalar_one()
        met_request_id = db.session.execute(request_sql, {**request_params, "reason": "Görüşülen talep"}).scalar_one()
        meeting_id = db.session.execute(text(
            "INSERT INTO feedback_meetings (feedback_request_id, employee_id, manager_id, meeting_date, meeting_start, "
            "meeting_end, meeting_type, note, status, created_at) "
            "VALUES (:request_id, :employee_id, :manager_id, '2026-10-01', '10:00:00', '10:30:00', 'yuz_yuze', :note, "
            "'planlandi', CURRENT_TIMESTAMP) RETURNING id"
        ), {"request_id": met_request_id, "employee_id": employee_id, "manager_id": admin_id, "note": _MEETING_NOTE}).scalar_one()
        db.session.commit()
        flask_app.config["_IDS"] = {
            "admin": admin_id, "employee": employee_id, "open_request": int(open_request_id), "meeting": int(meeting_id),
        }
    return flask_app


def _admin_client(flask_app):
    client = flask_app.test_client()
    response = client.post("/login", data={"sicil_or_email": "FAL000001", "password": _PASSWORD}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return client


# ---------------------------------------------------------------------------
# 1. Open feedback-request picker (feedback_aftercare_phase7)
# ---------------------------------------------------------------------------


def test_open_feedback_requests_lists_the_request_without_a_meeting(aftercare_app):
    from app.services.performance.feedback_aftercare_phase7 import list_open_feedback_requests

    ids = aftercare_app.config["_IDS"]
    with aftercare_app.app_context():
        rows = list_open_feedback_requests(current_user_id=ids["admin"], current_user_role="admin", is_admin=True)

    # The request that already has a meeting is excluded, as before.
    assert [row["id"] for row in rows] == [ids["open_request"]]
    assert rows[0]["employee_id"] == ids["employee"]
    assert rows[0]["employee_label"]


def test_aftercare_page_offers_the_open_request(aftercare_app):
    ids = aftercare_app.config["_IDS"]
    response = _admin_client(aftercare_app).get("/performance/feedback-aftercare")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="feedback_request_id"' in html
    assert f'<option value="{ids["open_request"]}">' in html


# ---------------------------------------------------------------------------
# 2. Meetings section of the integration page (feedback_integration)
# ---------------------------------------------------------------------------


def test_aftercare_rows_returns_the_meeting(aftercare_app):
    from app.services.performance.feedback_integration import aftercare_rows

    ids = aftercare_app.config["_IDS"]
    with aftercare_app.app_context():
        rows = aftercare_rows(viewer_id=ids["admin"])  # the admin is the meeting's manager

    assert [row["meeting_id"] for row in rows] == [ids["meeting"]]
    assert rows[0]["employee_id"] == ids["employee"]
    assert rows[0]["meeting_note"] == _MEETING_NOTE


def test_integration_page_shows_the_meeting(aftercare_app):
    response = _admin_client(aftercare_app).get("/performance/feedback-integration")

    assert response.status_code == 200
    assert _MEETING_NOTE in response.get_data(as_text=True)
