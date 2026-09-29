"""Contract: POST /ai/feedback/<id> answers a missing log or an oversized type with a client error.

log_ai_feedback inserted the row without checking that the AI request log exists and
without checking feedback_type against its String(30) column. On PostgreSQL the foreign-key
or length violation surfaced at flush as the route's generic 500 ("beklenmeyen hata"); on
SQLite, where foreign keys are not enforced, a row pointing at no request log was stored.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "AiFeedbackInputTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "ai_feedback_input" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-ai-feedback-input", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "ai-feedback-input-first-login",
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
    from app.models.ai_models import AIRequestLog

    with flask_app.app_context():
        db.create_all()
        user = User(sicil_no="AFI01", email="afi01@example.gov.tr", ad="Ai", soyad="Feedback", role="personel",
                    birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.flush()
        log = AIRequestLog(module_type="performance", feature_type="summary", user_id=user.id)
        db.session.add(log)
        db.session.commit()
        flask_app.config["_LOG_ID"] = log.id
    return flask_app


def _client(app):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": "AFI01", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _feedback_rows(app):
    from app.models.ai_models import AIFeedbackLog

    with app.app_context():
        return [(row.ai_request_log_id, row.feedback_type) for row in AIFeedbackLog.query.all()]


def test_feedback_on_an_existing_log_is_stored(app):
    response = _client(app).post(f"/ai/feedback/{app.config['_LOG_ID']}", json={"feedback_type": "helpful"})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert _feedback_rows(app) == [(app.config["_LOG_ID"], "helpful")]


def test_feedback_on_a_missing_log_is_404_and_stores_nothing(app):
    response = _client(app).post("/ai/feedback/999999", json={"feedback_type": "helpful"})
    assert response.status_code == 404
    assert _feedback_rows(app) == []


def test_oversized_feedback_type_is_400_and_stores_nothing(app):
    response = _client(app).post(f"/ai/feedback/{app.config['_LOG_ID']}", json={"feedback_type": "x" * 31})
    assert response.status_code == 400
    assert _feedback_rows(app) == []
