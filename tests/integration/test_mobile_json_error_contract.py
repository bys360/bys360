"""P2-03 regression contract: mobile API errors use the mobile JSON contract.

Final pre-live audit (2026-09-27): every app-wide error handler rendered the
HTML error page, also for /api/mobile/... requests. The Flutter client
(lib/core/network/api_client.dart) reads ``payload['message']`` and, for a
non-JSON body, shows the raw body text -- i.e. HTML source -- to the user.

Since P2-03 both ``render_error_page`` implementations (app/error_handlers.py
and app/bootstrap/error_pages.py) answer mobile API requests with
``{"message": <safe text>, "title": <safe title>}`` and the same status code;
web requests keep the HTML error pages.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError


def _make_app(monkeypatch):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-mobile-json-error-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "test-password",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "DATABASE_URL": "sqlite:///:memory:",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with app.app_context():
        db.create_all()
    return app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


def _bearer(app) -> dict[str, str]:
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no="93001",
            email="mobile.json.error@bys360.test",
            ad="Json",
            soyad="Hata",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("MobileJsonErrorTest1!")
        db.session.add(user)
        db.session.commit()
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _assert_mobile_json(response, status: int) -> dict:
    assert response.status_code == status
    assert response.headers.get("Content-Type", "").startswith("application/json")
    body = response.get_json()
    assert isinstance(body, dict)
    assert isinstance(body.get("message"), str) and body["message"]
    assert "<html" not in response.get_data(as_text=True).lower()
    return body


def test_unknown_mobile_path_returns_json_404(app) -> None:
    _assert_mobile_json(app.test_client().get("/api/mobile/does-not-exist"), 404)


def test_wrong_method_on_mobile_route_returns_json_405(app) -> None:
    _assert_mobile_json(app.test_client().get("/api/mobile/auth/login"), 405)


def test_unexpected_mobile_exception_returns_safe_json_500(app, monkeypatch) -> None:
    import app.api.mobile.domains.auth as auth_routes

    def _boom(*_args, **_kwargs):
        raise RuntimeError("internal-detail-must-not-leak")

    monkeypatch.setattr(auth_routes, "mobile_me_response", _boom)
    response = app.test_client().get("/api/mobile/me", headers=_bearer(app))

    body = _assert_mobile_json(response, 500)
    assert body["title"] == "Sistem Hatası"
    assert "internal-detail-must-not-leak" not in response.get_data(as_text=True)
    assert "RuntimeError" not in response.get_data(as_text=True)


def test_mobile_database_error_returns_safe_json_500(app, monkeypatch) -> None:
    import app.api.mobile.domains.auth as auth_routes

    def _db_down(*_args, **_kwargs):
        raise OperationalError("SELECT secret_column FROM hidden_table", {}, Exception("db-detail-must-not-leak"))

    monkeypatch.setattr(auth_routes, "mobile_me_response", _db_down)
    response = app.test_client().get("/api/mobile/me", headers=_bearer(app))

    body = _assert_mobile_json(response, 500)
    assert body["title"] == "Veritabanı Hatası"
    text = response.get_data(as_text=True)
    assert "db-detail-must-not-leak" not in text
    assert "hidden_table" not in text


def test_missing_mobile_token_keeps_the_existing_json_401(app) -> None:
    body = _assert_mobile_json(app.test_client().get("/api/mobile/me"), 401)
    assert body == {"message": "Mobil oturum bulunamadı veya süresi doldu."}


def test_web_error_pages_stay_html(app) -> None:
    response = app.test_client().get("/this-web-page-does-not-exist")

    assert response.status_code == 404
    assert response.headers.get("Content-Type", "").startswith("text/html")


def test_similar_non_mobile_prefix_stays_html(app) -> None:
    response = app.test_client().get("/api/mobilex/anything")

    assert response.status_code == 404
    assert response.headers.get("Content-Type", "").startswith("text/html")
