"""HTTP forwarding contracts against the real mobile blueprint."""
from __future__ import annotations

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    for name, value in {
        "APP_ENV": "testing",
        "DATABASE_URL": "sqlite:///:memory:",
        "SECRET_KEY": "mobile-forwarding-contract-test-key",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "Mobile-forwarding-test-password1!",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
    }.items():
        monkeypatch.setenv(name, value)
    from app import create_app
    from config import Config

    for config_name, config_value in {
        "APP_ENV": "testing",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_ENGINE_OPTIONS": {},
        "SECRET_KEY": "mobile-forwarding-contract-test-key",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "Mobile-forwarding-test-password1!",
        "LOG_FOLDER": str(tmp_path / "logs"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "REPORT_FOLDER": str(tmp_path / "reports"),
    }.items():
        monkeypatch.setattr(Config, config_name, config_value)
    flask_app = create_app()
    flask_app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False, WTF_CSRF_ENABLED=False)

    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        db.create_all()
        ids = {}
        for role in ("admin", "baskan", "ik", "personel", "birim_admin_full", "unknown"):
            user = User(
                sicil_no=role, email=f"{role}@forwarding.test", ad="Contract", soyad=role,
                role=role, is_active=True, birim="Test unit", ust_birim="Test parent",
                must_change_password=False, must_set_security_question=False,
            )
            user.set_password("Mobile-forwarding-fixture-password1!")
            db.session.add(user)
            db.session.flush()
            ids[role] = user.id
        db.session.commit()
        flask_app.config["FORWARDING_USER_IDS"] = ids
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


def _headers(app, role):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, app.config["FORWARDING_USER_IDS"][role])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


@pytest.fixture
def auth_calls(monkeypatch):
    from app.api.mobile import shared

    original = shared._load_token_user
    calls = []

    def observe_auth():
        user = original()
        calls.append(None if user is None else user.id)
        return user

    monkeypatch.setattr(shared, "_load_token_user", observe_auth)
    return calls


@pytest.fixture
def report_calls(monkeypatch):
    from app.api.mobile import performance_routes

    original = performance_routes._bys360_legacy_mobile_performance_reports
    calls = []

    def observe_reports(user):
        calls.append(user.id)
        return original(user)

    monkeypatch.setattr(performance_routes, "_bys360_legacy_mobile_performance_reports", observe_reports)
    return calls


@pytest.mark.parametrize("role", ["admin", "baskan"])
def test_manager_view_forwards_once_to_real_reports(app, auth_calls, report_calls, role):
    client = app.test_client()
    headers = _headers(app, role)
    expected = client.get("/api/mobile/performance/reports", headers=headers)
    assert expected.status_code == 200
    assert set(expected.get_json()) == {"source", "metrics", "items"}
    assert expected.get_json()["source"] == "real_api"
    assert len(expected.get_json()["metrics"]) == 4
    auth_calls.clear()
    report_calls.clear()

    response = client.get("/api/mobile/performance/manager-view", headers=headers)

    assert response.status_code == 200
    assert response.get_json() == expected.get_json()
    user_id = app.config["FORWARDING_USER_IDS"][role]
    assert auth_calls == [user_id]
    assert report_calls == [user_id]


@pytest.mark.parametrize("role", ["personel", "birim_admin_full", "unknown"])
def test_manager_view_preserves_limited_scope(app, auth_calls, report_calls, role):
    response = app.test_client().get(
        "/api/mobile/performance/manager-view", headers=_headers(app, role),
    )

    assert response.status_code == 200
    data = response.get_json()
    assert set(data) == {"source", "metrics", "items"}
    assert data["source"] == "real_api"
    assert data["items"] == []
    assert data["metrics"] == [
        {"title": "Görünürlük", "value": "Sınırlı",
         "subtitle": "Bu alan yetkili yönetici kapsamına göre açılır", "tone": "red", "icon": "lock"},
        {"title": "Veri Güvenliği", "value": "Aktif",
         "subtitle": "Yetkisiz personel veya karne detayı gösterilmez", "tone": "green", "icon": "shield"},
    ]
    assert auth_calls == [app.config["FORWARDING_USER_IDS"][role]]
    assert report_calls == []


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-test-token"}])
def test_manager_view_rejects_missing_or_invalid_auth(app, auth_calls, report_calls, headers):
    response = app.test_client().get("/api/mobile/performance/manager-view", headers=headers)

    assert response.status_code == 401
    assert response.get_json() == {"message": "Mobil oturum bulunamadı veya süresi doldu."}
    assert auth_calls == [None]
    assert report_calls == []
