"""Contract: a non-numeric user_id never turns a personnel-operations POST into a 500.

The document, note and status actions of /hr-management/personnel-operations redirect
back with ``int(request.form.get("user_id") or 0)`` in their form-token failure branch,
in their ``except`` blocks and in their final redirect, all outside any ``try``. A
tampered hidden ``user_id`` (for example ``abc``) raised ``ValueError`` there and the
request ended in a 500 instead of the usual warning and redirect.

Rule reused: ``_safe_int`` of the same route file, which the position actions already
use for the same ``user_id`` field. A numeric user_id is still carried into the redirect.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "HrInvalidUserIdTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "hr_invalid_user_id" / "dbs"
_BASE = "/hr-management/personnel-operations"
ROUTES = [
    ("document/save", "hr_personnel_document_save"),
    ("document/bulk-upload", "hr_personnel_document_bulk_upload"),
    ("document/987654/delete", "hr_personnel_document_delete"),
    ("note/save", "hr_personnel_note_save"),
    ("note/987654/toggle", "hr_personnel_note_close"),
    ("note/987654/delete", "hr_personnel_note_delete"),
    ("status/save", "hr_personnel_status_save"),
    ("status/987654/delete", "hr_personnel_status_delete"),
]


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-hr-invalid-user-id", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "hr-invalid-user-id-first-login",
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
        for sicil, role in (("HIU01", "birim_sorumlusu"), ("HIU02", "personel")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Hr", soyad=sicil, role=role,
                        birim="IK", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = user.id
        db.session.commit()
        flask_app.config["_USER_IDS"] = ids
    return flask_app


def _manager(app):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": "HIU01", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _post(client, path, namespace, *, with_token, **data):
    if with_token:
        token = uuid.uuid4().hex
        with client.session_transaction() as session:
            session[f"form_token:{namespace}:hr_personnel_operations"] = token
        data["form_token"] = token
    return client.post(f"{_BASE}/{path}", data=data)


@pytest.mark.parametrize("with_token", [False, True], ids=["token_rejected", "token_accepted"])
@pytest.mark.parametrize(("path", "namespace"), ROUTES)
def test_non_numeric_user_id_redirects_instead_of_500(app, path, namespace, with_token):
    response = _post(_manager(app), path, namespace, with_token=with_token, user_id="abc")
    assert response.status_code == 302
    location = response.headers.get("Location", "")
    assert _BASE in location
    assert "user_id=" not in location


@pytest.mark.parametrize(("path", "namespace"), ROUTES)
def test_numeric_user_id_is_still_kept_in_the_redirect(app, path, namespace):
    employee_id = app.config["_USER_IDS"]["HIU02"]
    response = _post(_manager(app), path, namespace, with_token=False, user_id=str(employee_id))
    assert response.status_code == 302
    assert f"user_id={employee_id}" in response.headers.get("Location", "")
