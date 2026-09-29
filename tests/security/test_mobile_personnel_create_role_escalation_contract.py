"""Contract: a mobile personnel creator outside the admin family cannot grant an admin-family role.

POST /api/mobile/personnel/create (and its /personnel/add alias) lets HR roles such as ``ik``
create staff on mobile (tests/behavior/test_mobile_personnel_create_authorization_contract.py
pins who may create). The new account's ``role`` was taken from the request body unchecked, so
an ``ik`` user could create an ``admin`` account, whose first-login password is the configured
default: a vertical privilege escalation.

Rule reused: the web account-creation route ``/personnel/add`` (app/admin/routes.py) is
``admin_required`` (route_support.ADMIN_FAMILY_ROLES), so on the web only admin-family users
can create accounts and grant roles. Mobile keeps the HR create right for other roles; which
non-admin-family roles HR may grant is a human decision and is not changed here.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "MobilePersonnelRoleEsc1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_personnel_role_escalation" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-mobile-personnel-role", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "mobile-personnel-role-first-login",
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

    with flask_app.app_context():
        db.create_all()
        ids = {}
        for sicil, role in (("MPR01", "ik"), ("MPR02", "admin"), ("MPR03", "personel")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Role", soyad=sicil, role=role,
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = user.id
        db.session.commit()
        flask_app.config["_USER_IDS"] = ids
    return flask_app


def _create(app, creator, role):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, app.config["_USER_IDS"][creator])
        assert user is not None
        token = _issue_token(user)
    sicil = f"MPRN{uuid.uuid4().hex[:6]}"
    payload = {"sicil_no": sicil, "ad": "Yeni", "soyad": "Personel", "unvan": "Uzman", "birim": "Birim A",
               "ust_birim": "Baskanlik", "yonetici_sicil": "MPR02", "role": role}
    response = app.test_client().post("/api/mobile/personnel/create", json=payload,
                                      headers={"Authorization": f"Bearer {token}"})
    return response, sicil


def _created_role(app, sicil):
    from app.models import User

    with app.app_context():
        user = User.query.filter_by(sicil_no=sicil).first()
        return None if user is None else user.role


@pytest.mark.parametrize("role", ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", " Admin "])
def test_hr_creator_cannot_grant_an_admin_family_role(app, role):
    response, sicil = _create(app, "MPR01", role)
    assert response.status_code == 403
    assert _created_role(app, sicil) is None


def test_hr_creator_keeps_creating_staff(app):
    response, sicil = _create(app, "MPR01", "personel")
    assert response.status_code == 201
    assert _created_role(app, sicil) == "personel"


def test_admin_creator_can_still_grant_an_admin_family_role(app):
    response, sicil = _create(app, "MPR02", "admin")
    assert response.status_code == 201
    assert _created_role(app, sicil) == "admin"


def test_non_creator_role_is_still_refused(app):
    response, sicil = _create(app, "MPR03", "personel")
    assert response.status_code == 403
    assert _created_role(app, sicil) is None
