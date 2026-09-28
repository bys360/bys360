"""Contract: the JSON AI recommendation endpoints have the same gate as the admin review queue.

/ai/recommendations/list, /<id>/status, /<id>/apply and /bulk-apply were login-only:
any employee could read the AI recommendations stored for another person's
evaluation, or change their review status. Reviewing AI recommendations is an
admin function (/admin/ai-recommendations/<id>/status: admin_required +
menu_key_required("ai_center")); these endpoints now require the same.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "AiRecommendationAuthz1!"
SECRET_BODY = "Gizli degerlendirme onerisi AIRECAUTHZ"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "ai_recommendation_authz" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-ai-recommendation-authz", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "ai-recommendation-authz-first-login",
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
    from app.models import AIRecommendation, User

    with flask_app.app_context():
        db.create_all()
        for sicil, role in (("AIRA01", "personel"), ("AIRA02", "admin")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Rec", soyad=sicil, role=role,
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.add(AIRecommendation(module_type="performance", target_table="performance_evaluations", target_id=41,
                                        recommendation_type="consistency", title="Tutarlilik uyarisi", body=SECRET_BODY,
                                        severity="warning", status="open"))
        db.session.commit()
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _recommendation(app):
    from app.models import AIRecommendation

    with app.app_context():
        row = AIRecommendation.query.one()
        return row.id, row.status


LIST_URL = "/ai/recommendations/list"
# The endpoint reads its filters from a JSON (or form) body, also on GET.
LIST_QUERY = {"module_type": "performance", "target_table": "performance_evaluations", "target_id": 41}


def test_employee_cannot_read_recommendations_of_another_evaluation(app):
    response = _client(app, "AIRA01").get(LIST_URL, json=LIST_QUERY)
    assert response.status_code != 200
    assert SECRET_BODY not in response.get_data(as_text=True)


def test_employee_cannot_change_a_recommendation_status(app):
    rec_id, before = _recommendation(app)
    response = _client(app, "AIRA01").post(f"/ai/recommendations/{rec_id}/status", data={"status": "rejected"})
    assert response.status_code != 200
    assert _recommendation(app) == (rec_id, before)


@pytest.mark.parametrize("path", ["/ai/recommendations/{id}/apply", "/ai/recommendations/bulk-apply"])
def test_employee_cannot_call_the_apply_endpoints(app, path):
    rec_id, _ = _recommendation(app)
    response = _client(app, "AIRA01").post(path.format(id=rec_id), data={"recommendation_ids": [str(rec_id)]})
    assert response.status_code != 200


def test_admin_keeps_list_and_review(app):
    client = _client(app, "AIRA02")
    listed = client.get(LIST_URL, json=LIST_QUERY)
    assert listed.status_code == 200
    assert listed.get_json()["data"]["recommendation_count"] == 1
    rec_id, _ = _recommendation(app)
    changed = client.post(f"/ai/recommendations/{rec_id}/status", data={"status": "accepted"})
    assert changed.status_code == 200, changed.get_data(as_text=True)[:300]
    assert _recommendation(app) == (rec_id, "accepted")
