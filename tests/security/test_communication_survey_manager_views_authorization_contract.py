"""Contract: the Faz 2 survey manager read views require a manager, like its write actions.

/communication/faz2/surveys, /<id> and /<id>/results were gated only by the
"surveys" menu key (the menu employees use to take surveys), while every write
action in the same module also requires is_manager(). An employee could open the
manager list and read any survey's results, including free-text answers.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "SurveyManagerViews1!"
SECRET_ANSWER = "Gizli serbest metin yaniti SMV1"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "survey_manager_views" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-survey-manager-views", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "survey-manager-views-first-login",
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
    from app.models import Survey, SurveyAnswer, SurveyQuestion, SurveyResponse, User

    with flask_app.app_context():
        db.create_all()
        users = {}
        for sicil, role in (("SMV01", "personel"), ("SMV02", "admin")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Survey", soyad=sicil, role=role,
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()
        survey = Survey(title="Calisan Memnuniyeti SMV", created_by_user_id=users["SMV02"].id, status="published")
        db.session.add(survey)
        db.session.flush()
        question = SurveyQuestion(survey_id=survey.id, question_text="Gorusunuz nedir?", question_type="text")
        db.session.add(question)
        db.session.flush()
        response = SurveyResponse(survey_id=survey.id, user_id=users["SMV02"].id, is_completed=True)
        db.session.add(response)
        db.session.flush()
        db.session.add(SurveyAnswer(response_id=response.id, question_id=question.id, answer_text=SECRET_ANSWER))
        db.session.commit()
        flask_app.config["_TEST_SURVEY_ID"] = survey.id
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _paths(app):
    survey_id = app.config["_TEST_SURVEY_ID"]
    return (
        f"/communication/faz2/surveys/{survey_id}/results",
        f"/communication/faz2/surveys/{survey_id}",
        "/communication/faz2/surveys",
    )


def test_employee_cannot_open_the_survey_manager_read_views(app):
    client = _client(app, "SMV01")
    for path in _paths(app):
        response = client.get(path, follow_redirects=True)
        body = response.get_data(as_text=True)
        assert SECRET_ANSWER not in body, path
        assert "Calisan Memnuniyeti SMV" not in body or path.endswith("/surveys"), path


def test_employee_cannot_read_survey_results(app):
    response = _client(app, "SMV01").get(_paths(app)[0])
    assert response.status_code != 200 or SECRET_ANSWER not in response.get_data(as_text=True)


def test_manager_still_sees_results(app):
    response = _client(app, "SMV02").get(_paths(app)[0])
    assert response.status_code == 200
    assert SECRET_ANSWER in response.get_data(as_text=True)
