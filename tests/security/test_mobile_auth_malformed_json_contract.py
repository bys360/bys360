"""Contract: malformed JSON on the unauthenticated mobile auth endpoints is a 4xx, never a 500.

POST /api/mobile/auth/login and POST /api/mobile/auth/refresh need no token, so anyone can
reach them. Both read ``request.get_json(silent=True) or {}`` and then call ``.get`` on it,
so a JSON body that is an array, a string or a number reached ``.get`` and raised
AttributeError (HTTP 500). Field values that are not strings did the same: ``.strip()`` on a
number for ``username`` in mobile_login_response, and on the ``refresh_token`` in
_load_refresh_token_user.

Rule reused: the endpoints' own existing answers for a missing body or field.
- login: 400 "Kullanıcı adı/sicil ve şifre zorunludur." (as for an empty or null body)
- refresh: 401 "Mobil oturum yenilenemedi..." (as for a missing refresh token)

A malformed request is treated as "field missing"; no new message or status is introduced.
Valid logins and refreshes are unchanged.

Real Flask app, real test client, file-backed SQLite only.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "MobileAuthMalformedJsonTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_auth_malformed_json" / "dbs"
_LOGIN = "/api/mobile/auth/login"
_REFRESH = "/api/mobile/auth/refresh"
_LOGIN_REQUIRED_MESSAGE = "Kullanıcı adı/sicil ve şifre zorunludur."
_REFRESH_FAILED_MESSAGE = "Mobil oturum yenilenemedi. Lütfen tekrar giriş yapın."

# JSON documents that are valid JSON but not an object.
_NON_OBJECT_BODIES = ["[]", '["x"]', '"x"', "7", "1.5", "true"]


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-mobile-auth-malformed-json", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "mobile-auth-malformed-json-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    # Report errors the way a real client sees them (status code), not as raised exceptions.
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri, PROPAGATE_EXCEPTIONS=False)
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        db.create_all()
        user = User(sicil_no="MAJ01", email="maj01@example.gov.tr", ad="Mobile", soyad="Auth", role="personel",
                    birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
    return flask_app


def _post_raw(app, path, body):
    return app.test_client().post(path, data=body, content_type="application/json")


@pytest.mark.parametrize("body", _NON_OBJECT_BODIES)
def test_login_with_non_object_json_body_is_400(app, body):
    response = _post_raw(app, _LOGIN, body)
    assert response.status_code == 400
    assert response.get_json() == {"message": _LOGIN_REQUIRED_MESSAGE}


@pytest.mark.parametrize(
    "payload",
    [
        {"username": 123, "password": PASSWORD},
        {"username": ["MAJ01"], "password": PASSWORD},
        {"username": {"x": 1}, "password": PASSWORD},
        {"username": "MAJ01", "password": 123},
        {"username": "MAJ01", "password": ["x"]},
    ],
)
def test_login_with_non_string_fields_is_400(app, payload):
    response = app.test_client().post(_LOGIN, json=payload)
    assert response.status_code == 400
    assert response.get_json() == {"message": _LOGIN_REQUIRED_MESSAGE}


@pytest.mark.parametrize("body", _NON_OBJECT_BODIES)
def test_refresh_with_non_object_json_body_is_401(app, body):
    response = _post_raw(app, _REFRESH, body)
    assert response.status_code == 401
    assert response.get_json() == {"message": _REFRESH_FAILED_MESSAGE}


@pytest.mark.parametrize("token", [123, ["x"], {"x": 1}, True])
def test_refresh_with_non_string_token_is_401(app, token):
    for key in ("refresh_token", "refreshToken"):
        response = app.test_client().post(_REFRESH, json={key: token})
        assert response.status_code == 401
        assert response.get_json() == {"message": _REFRESH_FAILED_MESSAGE}


# ---------------------------------------------------------------------------
# Existing behaviour is unchanged.
# ---------------------------------------------------------------------------


def test_login_and_refresh_still_work_for_valid_requests(app):
    client = app.test_client()
    login = client.post(_LOGIN, json={"username": "MAJ01", "password": PASSWORD})
    assert login.status_code == 200
    tokens = login.get_json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["user"]["sicil_no"] == "MAJ01"

    refresh = client.post(_REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 200
    assert refresh.get_json()["user"]["sicil_no"] == "MAJ01"

    refresh_camel = client.post(_REFRESH, json={"refreshToken": tokens["refresh_token"]})
    assert refresh_camel.status_code == 200


def test_existing_error_answers_are_unchanged(app):
    client = app.test_client()
    assert client.post(_LOGIN, json={"username": "MAJ01", "password": "wrong"}).status_code == 401
    assert client.post(_LOGIN, json={}).status_code == 400
    assert _post_raw(app, _LOGIN, "null").status_code == 400
    assert client.post(_LOGIN, json={"username": "  ", "password": PASSWORD}).status_code == 400
    assert client.post(_REFRESH, json={}).status_code == 401
    assert client.post(_REFRESH, json={"refresh_token": "not-a-token"}).status_code == 401
    assert _post_raw(app, _REFRESH, "null").status_code == 401
