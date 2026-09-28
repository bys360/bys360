"""Contract: HR leave / attendance / delegation status and delete act only inside the caller's scope.

The management pages list only records of people in the caller's scope
(app.services.ui_context.scope.build_user_scope_context), but the POST
/status and /delete endpoints loaded any record by id, so a manager could
approve, change or delete another unit's leave, attendance and delegation
records. They now require the record's person to be in the caller's widest scope.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest

PASSWORD = "HrLeaveScopeTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "hr_leave_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-hr-leave-scope", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "hr-leave-scope-first-login",
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
    from app.models import AttendanceException, DelegationAssignment, PersonnelLeave, User

    with flask_app.app_context():
        db.create_all()

        def user(sicil, role, birim, manager=None):
            row = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Hr", soyad=sicil, role=role, birim=birim,
                       yonetici_sicil=manager, is_active=True, must_change_password=False, must_set_security_question=False)
            row.set_password(PASSWORD)
            db.session.add(row)
            return row

        user("HRS_MA", "birim_sorumlusu", "Birim A")
        user("HRS_EA", "personel", "Birim A", manager="HRS_MA")
        user("HRS_MB", "birim_sorumlusu", "Birim B")
        employee_b = user("HRS_EB", "personel", "Birim B", manager="HRS_MB")
        other_b = user("HRS_EB2", "personel", "Birim B", manager="HRS_MB")
        user("HRS_AD", "admin", "Başkanlık")
        db.session.flush()
        db.session.add(PersonnelLeave(user_id=employee_b.id, leave_type="yillik", status="beklemede",
                                      start_date=date(2026, 10, 5), end_date=date(2026, 10, 9)))
        db.session.add(AttendanceException(user_id=employee_b.id, record_date=date(2026, 10, 1), exception_type="gec",
                                           status="beklemede"))
        db.session.add(DelegationAssignment(delegator_user_id=employee_b.id, delegate_user_id=other_b.id, status="aktif",
                                            start_date=date(2026, 10, 1), end_date=date(2026, 10, 31)))
        db.session.commit()
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _state(app):
    from app.models import AttendanceException, DelegationAssignment, PersonnelLeave

    with app.app_context():
        return {
            "leave": [(r.id, r.status) for r in PersonnelLeave.query.all()],
            "attendance": [(r.id, r.status) for r in AttendanceException.query.all()],
            "delegation": [(r.id, r.status) for r in DelegationAssignment.query.all()],
        }


def _ids(app):
    state = _state(app)
    return state["leave"][0][0], state["attendance"][0][0], state["delegation"][0][0]


ACTIONS: tuple[tuple[str, dict[str, str]], ...] = (
    ("/hr-management/leave/{leave}/status", {"status": "onaylandi"}),
    ("/hr-management/attendance/{attendance}/status", {"status": "onaylandi"}),
    ("/hr-management/delegations/{delegation}/status", {"status": "iptal"}),
    ("/hr-management/leave/{leave}/delete", {}),
    ("/hr-management/attendance/{attendance}/delete", {}),
    ("/hr-management/delegations/{delegation}/delete", {}),
)


@pytest.mark.parametrize("path, data", ACTIONS)
def test_manager_of_another_unit_cannot_change_or_delete(app, path, data):
    leave, attendance, delegation = _ids(app)
    before = _state(app)
    _client(app, "HRS_MA").post(path.format(leave=leave, attendance=attendance, delegation=delegation), data=data)
    assert _state(app) == before


@pytest.mark.parametrize("sicil", ["HRS_MB", "HRS_AD"])
def test_in_scope_manager_and_admin_can_update_status(app, sicil):
    leave, _, _ = _ids(app)
    _client(app, sicil).post(f"/hr-management/leave/{leave}/status", data={"status": "onaylandi"})
    assert _state(app)["leave"] == [(leave, "onaylandi")]
