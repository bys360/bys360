"""Contract: personnel-operation records outside the manager's HR scope cannot be changed.

The asset, checklist and request-task actions look the record up inside the caller's
HR scope (_asset_in_scope, _review_in_scope, the request owner check) and had no test.
A birim_sorumlusu of unit "IK" must not return or delete an asset, delete a checklist
review, or complete a request task of an employee in "Finans"; the same actions on an
employee of their own unit still work.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest

PASSWORD = "HrObjectScopeTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "hr_object_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-hr-object-scope", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "hr-object-scope-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import User
    from app.models.hr_models import (
        PersonnelAssetAssignment,
        PersonnelChecklistReview,
        PersonnelChecklistTemplateItem,
        PersonnelSelfServiceRequest,
        PersonnelSelfServiceRequestTask,
    )

    with flask_app.app_context():
        db.create_all()
        ids = {}
        for sicil, role, birim in (
            ("HOS01", "birim_sorumlusu", "IK"),
            ("HOS02", "personel", "IK"),
            ("HOS03", "personel", "Finans"),
        ):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Hr", soyad=sicil, role=role,
                        birim=birim, is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = user.id
        item = PersonnelChecklistTemplateItem(code="HOS-ITEM", label="Kimlik fotokopisi")
        db.session.add(item)
        db.session.flush()
        records = {}
        for key, owner in (("inside", ids["HOS02"]), ("outside", ids["HOS03"])):
            asset = PersonnelAssetAssignment(user_id=owner, asset_name=f"Laptop {key}", assigned_date=date(2026, 1, 5))
            review = PersonnelChecklistReview(user_id=owner, template_item_id=item.id)
            request_row = PersonnelSelfServiceRequest(user_id=owner, created_by_id=owner, title=f"Talep {key}",
                                                      description="d", request_type="belge_talebi", priority="normal",
                                                      status="submitted", submitted_at=utc_now())
            db.session.add_all([asset, review, request_row])
            db.session.flush()
            task = PersonnelSelfServiceRequestTask(request_id=request_row.id, title=f"Gorev {key}")
            db.session.add(task)
            db.session.flush()
            records[key] = {"asset": asset.id, "review": review.id, "task": task.id}
        db.session.commit()
        flask_app.config["_RECORDS"] = records
    return flask_app


def _manager(app):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": "HOS01", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _post(client, path, namespace, scope, **data):
    token = uuid.uuid4().hex
    with client.session_transaction() as session:
        session[f"form_token:{namespace}:{scope}"] = token
    return client.post(path, data={"form_token": token, **data})


def _state(app, key):
    from app.extensions import db
    from app.models.hr_models import (
        PersonnelAssetAssignment,
        PersonnelChecklistReview,
        PersonnelSelfServiceRequestTask,
    )

    ids = app.config["_RECORDS"][key]
    with app.app_context():
        asset = db.session.get(PersonnelAssetAssignment, ids["asset"])
        review = db.session.get(PersonnelChecklistReview, ids["review"])
        task = db.session.get(PersonnelSelfServiceRequestTask, ids["task"])
        return (asset.status if asset else None, review is not None, task.status if task else None)


def _act(app, key):
    ids = app.config["_RECORDS"][key]
    client = _manager(app)
    base = "/hr-management/personnel-operations"
    _post(client, f"{base}/request-task/{ids['task']}/complete", "hr_personnel_request_task_complete",
          "hr_personnel_request_tasks", task_action="complete")
    _post(client, f"{base}/assets/{ids['asset']}/return", "hr_personnel_asset_return", "hr_personnel_operations")
    _post(client, f"{base}/checklists/{ids['review']}/delete", "hr_personnel_checklist_delete", "hr_personnel_operations")


def test_manager_cannot_change_records_of_another_unit(app):
    _act(app, "outside")
    assert _state(app, "outside") == ("assigned", True, "open")


def test_manager_can_change_records_of_own_unit(app):
    _act(app, "inside")
    assert _state(app, "inside") == ("returned", False, "completed")


@pytest.mark.parametrize("key, expected_remaining", [("outside", True), ("inside", False)])
def test_asset_delete_is_limited_to_the_manager_scope(app, key, expected_remaining):
    from app.extensions import db
    from app.models.hr_models import PersonnelAssetAssignment

    asset_id = app.config["_RECORDS"][key]["asset"]
    _post(_manager(app), f"/hr-management/personnel-operations/assets/{asset_id}/delete",
          "hr_personnel_asset_delete", "hr_personnel_operations")
    with app.app_context():
        assert (db.session.get(PersonnelAssetAssignment, asset_id) is not None) is expected_remaining
