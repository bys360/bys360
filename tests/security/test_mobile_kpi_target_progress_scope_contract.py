"""Contract: POST /api/mobile/kpi/target-management/<id>/progress uses the list's owner scope.

GET /api/mobile/kpi/target-management shows a caller without mobile global scope only
the targets they own (``Target.owner_user_id == user.id``). The progress write path
accepted ``owner_user_id in {0, user.id}``, so any mobile user, a plain ``personel``
included, could overwrite ``current_value``, ``completion_rate`` and ``status`` of an
ownerless target (an institution or unit target created on the web with no owner user),
a target that the same user can neither see in the mobile list nor edit on the web.

Rule reused: the list filter of the same mobile route family
(``_bys360_legacy_mobile_kpi_target_management_v2853``), already reused for
GET /api/mobile/kpi/goals by ``test_mobile_kpi_goals_scope_leak_contract.py``.
"""
from __future__ import annotations

import datetime
import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "MobileKpiProgressScope1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_kpi_progress_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-mobile-kpi-progress", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "mobile-kpi-progress-first-login",
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
    from app.modules.strategic_performance.models import PerformanceTarget

    with flask_app.app_context():
        db.create_all()
        users = {}
        for sicil, role in (("MKP01", "personel"), ("MKP02", "personel"), ("MKP03", "birim_sorumlusu"), ("MKP04", "admin")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Kpi", soyad=sicil, role=role,
                        birim="Birim-A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()

        def _target(name, owner_user_id):
            target = PerformanceTarget(
                target_code=f"MKP-{uuid.uuid4().hex[:10]}", target_name=name, target_type="personnel", category="KPI",
                owner_user_id=owner_user_id, weight=0, target_value=100, current_value=10, completion_rate=10,
                status="ongoing", risk_level="low", start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2026, 12, 31),
            )
            db.session.add(target)
            db.session.flush()
            return target.id

        flask_app.config["_TARGETS"] = {
            "own": _target("MKP own target", users["MKP01"].id),
            "other": _target("MKP other user target", users["MKP02"].id),
            "ownerless": _target("MKP ownerless institution target", None),
        }
        flask_app.config["_USER_IDS"] = {sicil: user.id for sicil, user in users.items()}
        db.session.commit()
    return flask_app


def _headers(app, sicil):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, app.config["_USER_IDS"][sicil])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _progress(app, sicil, key, value=95):
    target_id = app.config["_TARGETS"][key]
    return app.test_client().post(
        f"/api/mobile/kpi/target-management/{target_id}/progress", json={"current_value": value}, headers=_headers(app, sicil)
    )


def _current_value(app, key):
    from app.extensions import db
    from app.modules.strategic_performance.models import PerformanceTarget

    with app.app_context():
        target = db.session.get(PerformanceTarget, app.config["_TARGETS"][key])
        assert target is not None
        return float(target.current_value or 0)


def _listed_ids(app, sicil):
    response = app.test_client().get("/api/mobile/kpi/target-management", headers=_headers(app, sicil))
    assert response.status_code == 200
    return {str(item.get("id")) for item in (response.get_json() or {}).get("items") or []}


def test_personnel_cannot_update_progress_of_an_ownerless_target(app):
    response = _progress(app, "MKP01", "ownerless")
    assert response.status_code == 403
    assert _current_value(app, "ownerless") == 10


def test_unit_manager_without_mobile_global_scope_cannot_update_an_ownerless_target(app):
    response = _progress(app, "MKP03", "ownerless")
    assert response.status_code == 403
    assert _current_value(app, "ownerless") == 10


def test_ownerless_target_is_not_in_the_personnel_mobile_list(app):
    listed = _listed_ids(app, "MKP01")
    assert str(app.config["_TARGETS"]["own"]) in listed
    assert str(app.config["_TARGETS"]["ownerless"]) not in listed


def test_personnel_cannot_update_progress_of_another_users_target(app):
    assert _progress(app, "MKP01", "other").status_code == 403
    assert _current_value(app, "other") == 10


def test_personnel_can_still_update_progress_of_their_own_target(app):
    response = _progress(app, "MKP01", "own")
    assert response.status_code == 200
    assert _current_value(app, "own") == 95


def test_mobile_global_scope_can_still_update_an_ownerless_target(app):
    response = _progress(app, "MKP04", "ownerless")
    assert response.status_code == 200
    assert _current_value(app, "ownerless") == 95
