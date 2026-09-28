"""Contract: a missing period on /ai/decision-support/performance/periods/<id>/scope-check is a JSON 404.

The route looked the period up before entering its JSON runner, so the runner's
LookupError -> 404 mapping never applied and the request ended as a 500 (found by the
migration-built GET probe).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "Faz8MissingPeriodTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "faz8_missing_period" / "dbs"


@pytest.fixture
def client(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-faz8-missing-period", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "faz8-missing-period-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import User

    with app.app_context():
        db.create_all()
        user = User(sicil_no="FZ8ADM", email="fz8adm@example.gov.tr", ad="Faz", soyad="Sekiz", role="admin",
                    is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
    test_client = app.test_client()
    response = test_client.post("/login", data={"sicil_or_email": "FZ8ADM", "password": PASSWORD})
    assert response.status_code == 302
    return test_client


def test_missing_period_is_a_json_404(client):
    response = client.get("/ai/decision-support/performance/periods/999999/scope-check")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False
