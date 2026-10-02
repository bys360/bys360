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


PATHS = ["/api/mobile/personnel/create", "/api/mobile/personnel/add"]


def _payload(**changes):
    payload = {
        "sicil_no": "new-staff", "email": "new-staff@forwarding.test",
        "ad": "New", "soyad": "Staff", "unvan": "Uzman", "birim": "Test unit",
        "ust_birim": "Test parent", "yonetici_sicil": "admin", "role": "personel",
    }
    payload.update(changes)
    return payload


@pytest.fixture
def create_calls(monkeypatch):
    from app.api.mobile.domains import personnel_write_all

    original = personnel_write_all._bys360_legacy_mobile_personnel_create
    calls = []

    def observe_create(user):
        calls.append(user.id)
        return original(user)

    monkeypatch.setattr(personnel_write_all, "_bys360_legacy_mobile_personnel_create", observe_create)
    return calls


def _assert_once(app, role, auth_calls, create_calls):
    user_id = app.config["FORWARDING_USER_IDS"][role]
    assert auth_calls == [user_id]
    assert create_calls == [user_id]


def _staff_rows(app):
    from app.models import User

    with app.app_context():
        return [(user.sicil_no, user.email, user.role) for user in User.query.order_by(User.id).all()]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("role", ["admin", "ik"])
def test_create_entries_use_same_real_implementation_once(app, auth_calls, create_calls, path, role):
    response = app.test_client().post(path, json=_payload(), headers=_headers(app, role))

    assert response.status_code == 201
    data = response.get_json()
    assert set(data) == {"ok", "success", "message", "can_create_personnel", "personnel"}
    assert data["ok"] is True and data["success"] is True and data["can_create_personnel"] is True
    assert data["message"] == "Personel kaydı oluşturuldu. Başlangıç şifresi sistem tarafından otomatik atanmıştır."
    assert data["personnel"]["sicil_no"] == "new-staff"
    assert data["personnel"]["role"] == "personel"
    from app.api.mobile.domains.personnel_write_all import (
        _bys360_legacy__mobile_created_personnel_row,
    )
    from app.models import User

    with app.app_context():
        created = User.query.filter_by(sicil_no="new-staff").one()
        assert data["personnel"] == _bys360_legacy__mobile_created_personnel_row(created)
    assert len(_staff_rows(app)) == 7
    _assert_once(app, role, auth_calls, create_calls)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-test-token"}])
def test_create_entries_reject_missing_or_invalid_auth(app, auth_calls, create_calls, path, headers):
    before = _staff_rows(app)
    response = app.test_client().post(path, json=_payload(), headers=headers)

    assert response.status_code == 401
    assert response.get_json() == {"message": "Mobil oturum bulunamadı veya süresi doldu."}
    assert _staff_rows(app) == before
    assert auth_calls == [None]
    assert create_calls == []


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("role", ["personel", "birim_admin_full", "unknown"])
def test_create_entries_preserve_role_denial(app, auth_calls, create_calls, path, role):
    before = _staff_rows(app)
    response = app.test_client().post(path, json=_payload(), headers=_headers(app, role))

    assert response.status_code == 403
    assert response.get_json() == {"message": "Bu işlem için personel ekleme yetkiniz bulunmamaktadır."}
    assert _staff_rows(app) == before
    _assert_once(app, role, auth_calls, create_calls)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "Zorunlu alanları doldurun: Sicil No, Ad, Soyad, Unvan, Birim, Üst Birim, Yönetici Sicil No"),
        (_payload(yonetici_sicil="missing-manager"), "Yönetici Sicil No sistemde bulunamadı."),
    ],
)
def test_create_entries_preserve_validation(app, auth_calls, create_calls, path, payload, message):
    before = _staff_rows(app)
    response = app.test_client().post(path, json=payload, headers=_headers(app, "ik"))

    assert response.status_code == 400
    assert response.get_json() == {"message": message}
    assert _staff_rows(app) == before
    _assert_once(app, "ik", auth_calls, create_calls)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_payload(sicil_no="admin"), "Bu Sicil No ile kayıtlı personel zaten bulunmaktadır."),
        (_payload(email="admin@forwarding.test"), "Bu e-posta adresiyle kayıtlı personel zaten bulunmaktadır."),
    ],
)
def test_create_entries_preserve_duplicate_response(app, auth_calls, create_calls, path, payload, message):
    before = _staff_rows(app)
    response = app.test_client().post(path, json=payload, headers=_headers(app, "ik"))

    assert response.status_code == 400
    assert response.get_json() == {"message": message}
    assert _staff_rows(app) == before
    _assert_once(app, "ik", auth_calls, create_calls)


@pytest.mark.parametrize("path", PATHS)
def test_hr_cannot_grant_admin_role_through_either_entry(app, auth_calls, create_calls, path):
    before = _staff_rows(app)
    response = app.test_client().post(path, json=_payload(role="admin"), headers=_headers(app, "ik"))

    assert response.status_code == 403
    assert response.get_json() == {"message": "Bu rolü atama yetkiniz bulunmamaktadır."}
    assert _staff_rows(app) == before
    _assert_once(app, "ik", auth_calls, create_calls)
