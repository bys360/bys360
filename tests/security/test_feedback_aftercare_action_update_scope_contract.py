"""Contract: POST /performance/feedback-aftercare/actions/<id>/update authorizes before it writes.

The route called ``update_action_plan`` (UPDATE ... + ``db.session.commit()``) first and
only then checked ``_can_edit_meeting``. Any logged-in user, a plain ``personel``
included, could overwrite ``status``, ``follow_up_note`` and ``result_summary`` of any
meeting's action plan by id; the "no permission" flash appeared after the commit.

Rule reused: ``_can_edit_meeting`` of the same route file (global aftercare role, or the
meeting's manager or employee), which the sibling after-note, preparation and add-action
routes already check BEFORE writing. The update now resolves the action's meeting and
checks that rule first; allowed users keep the same behaviour.
"""
from __future__ import annotations

import datetime
import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "FeedbackAftercareScope1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "feedback_aftercare_action_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-feedback-aftercare", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "feedback-aftercare-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import User
    from app.models.communication_models import FeedbackMeeting
    from app.services import runtime_schema
    from app.services.performance.feedback_aftercare import add_action_plan

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        users = {}
        for sicil, role in (
            ("FAC01", "personel"), ("FAC02", "birim_sorumlusu"), ("FAC03", "personel"),
            ("FAC04", "birim_sorumlusu"), ("FAC05", "admin"),
        ):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Aftercare", soyad=sicil, role=role,
                        birim="Birim-A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()
        # SQLite does not enforce the feedback_requests foreign key; the request row is irrelevant here.
        meeting = FeedbackMeeting(feedback_request_id=1, employee_id=users["FAC01"].id, manager_id=users["FAC02"].id,
                                  meeting_date=datetime.date(2026, 6, 1), meeting_start=datetime.time(10, 0),
                                  meeting_end=datetime.time(10, 30), meeting_type="yuz_yuze", status="planlandi")
        db.session.add(meeting)
        db.session.commit()
        add_action_plan(meeting.id, users["FAC01"].id, users["FAC02"].id,
                        {"title": "FAC eylem", "status": "acik", "follow_up_note": "ilk not"})
        action_id = db.session.execute(
            db.text("SELECT id FROM feedback_meeting_action_plans WHERE meeting_id = :m"), {"m": meeting.id}
        ).scalar_one()
        flask_app.config["_ACTION_ID"] = int(action_id)
        flask_app.config["_MEETING_ID"] = int(meeting.id)
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _update(app, sicil, action_id=None):
    action_id = app.config["_ACTION_ID"] if action_id is None else action_id
    return _client(app, sicil).post(
        f"/performance/feedback-aftercare/actions/{action_id}/update",
        data={"status": "tamamlandi", "follow_up_note": f"not {sicil}", "result_summary": f"sonuc {sicil}"},
    )


def _action_state(app):
    from app.extensions import db

    with app.app_context():
        row = db.session.execute(
            db.text("SELECT status, follow_up_note, result_summary FROM feedback_meeting_action_plans WHERE id = :a"),
            {"a": app.config["_ACTION_ID"]},
        ).one()
        return tuple(row)


@pytest.mark.parametrize("sicil", ["FAC03", "FAC04"])
def test_unrelated_user_cannot_update_an_action_plan(app, sicil):
    response = _update(app, sicil)
    assert response.status_code == 302
    assert _action_state(app) == ("acik", "ilk not", "")


@pytest.mark.parametrize("sicil", ["FAC01", "FAC02", "FAC05"])
def test_meeting_employee_manager_and_admin_can_still_update(app, sicil):
    response = _update(app, sicil)
    assert response.status_code == 302
    assert f"/performance/feedback-aftercare/{app.config['_MEETING_ID']}" in response.headers.get("Location", "")
    assert _action_state(app) == ("tamamlandi", f"not {sicil}", f"sonuc {sicil}")


def test_unknown_action_id_still_redirects_without_error(app):
    response = _update(app, "FAC05", action_id=987654)
    assert response.status_code == 302
    assert _action_state(app) == ("acik", "ilk not", "")
