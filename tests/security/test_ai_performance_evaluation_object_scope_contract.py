"""Contract: AI evaluation endpoints respect the evaluation's visibility scope.

Covers /ai/performance/evaluation/<id>/summary and /consistency. The fix sits in
their shared payload loader, which /ai/decision-support/performance/evaluation/<id>
also uses (that route currently answers 400: its AI feature policy is undefined).

The role gate (manager-family roles) is not enough: the services loaded any
evaluation by id, so a unit manager could have another unit's evaluation
(scores, comments, justifications) summarised and stored in the AI request log.
They now apply app.services.ai_decision.permission_guard.can_view_evaluation, the
visibility policy the AI decision-support pages already use.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest

PASSWORD = "AiEvaluationScopeTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "ai_evaluation_scope" / "dbs"
ENDPOINTS = (
    "/ai/performance/evaluation/{id}/summary",
    "/ai/performance/evaluation/{id}/consistency",
)


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-ai-evaluation-scope", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "ai-evaluation-scope-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri, AI_ENABLED=True)
    from app.extensions import db

    with flask_app.app_context():
        db.create_all()
    return flask_app


def _user(sicil: str, role: str, birim: str):
    from app.models import User

    user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Scope", soyad=sicil, role=role,
                birim=birim, is_active=True, must_change_password=False, must_set_security_question=False)
    user.set_password(PASSWORD)
    return user


@pytest.fixture
def evaluation_id(app):
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    with app.app_context():
        people = {
            "outside": _user("AISC01", "birim_sorumlusu", "Birim A"),
            "evaluator": _user("AISC02", "birim_sorumlusu", "Birim B"),
            "employee": _user("AISC03", "personel", "Birim B"),
            "unit_head": _user("AISC04", "birim_sorumlusu", "Birim B"),
            "admin": _user("AISC05", "admin", "Başkanlık"),
        }
        db.session.add_all(people.values())
        db.session.flush()
        period = PerformancePeriod(title="AI Kapsam Dönemi", period_type="quarterly",
                                   start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
        db.session.add(period)
        db.session.flush()
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=people["employee"].id,
                                           level_1_evaluator_id=people["evaluator"].id, final_total_100=64.0,
                                           status="completed", workflow_status="tamamlandi", is_published_to_employee=False)
        db.session.add(evaluation)
        db.session.commit()
        return evaluation.id


def _client_for(app, sicil: str):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _logged_targets(app, evaluation_id: int) -> int:
    from app.extensions import db
    from app.models import AIRequestLog

    with app.app_context():
        return db.session.query(AIRequestLog).filter_by(target_table="performance_evaluations", target_id=evaluation_id).count()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_manager_outside_the_evaluation_scope_is_denied(app, evaluation_id, endpoint):
    client = _client_for(app, "AISC01")
    response = client.get(endpoint.format(id=evaluation_id))
    assert response.status_code == 403
    body = response.get_data(as_text=True)
    assert "AISC03" not in body and "64" not in body
    assert _logged_targets(app, evaluation_id) == 0


@pytest.mark.parametrize("sicil", ["AISC02", "AISC05"])
@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_evaluator_and_admin_keep_access(app, evaluation_id, endpoint, sicil):
    client = _client_for(app, sicil)
    response = client.get(endpoint.format(id=evaluation_id))
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert response.get_json()["ok"] is True


@pytest.mark.parametrize("sicil", ["AISC01", "AISC02", "AISC03", "AISC04", "AISC05"])
def test_endpoint_decision_follows_the_evaluation_visibility_policy(app, evaluation_id, sicil):
    """Whatever can_view_evaluation decides (e.g. for a same-unit head who is not the evaluator), the endpoint follows."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, User
    from app.services.ai_decision.permission_guard import can_view_evaluation

    with app.app_context():
        user = User.query.filter_by(sicil_no=sicil).one()
        allowed = can_view_evaluation(user, db.session.get(PerformanceEvaluation, evaluation_id))
    client = _client_for(app, sicil)
    response = client.get(ENDPOINTS[0].format(id=evaluation_id))
    if sicil == "AISC03":  # personel: blocked earlier by the AI feature's manager-role gate
        assert response.status_code == 403
    else:
        assert response.status_code == (200 if allowed else 403)
