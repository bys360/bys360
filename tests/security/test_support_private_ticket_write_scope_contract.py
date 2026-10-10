"""Contract: the private-ticket unit scope (Phase 13B NEW-1) also covers status and assignment.

GET /support/<id> hides a private ticket from managers outside the ticket's unit
(_can_view_private_scope). POST /support/<id>/status and /support/<id>/assign only
checked the all-tickets permission, so such a manager could close a private ticket
of another unit, or assign it to themselves and then read it as its assignee.

K5-Q1 (approved policy, 2026-10-10): ``support_all`` is an explicit per-person grant, never a role
default; the managers and the admin below hold it, as an admin assigns it in Settings.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "SupportPrivateWriteTest1!"
MARKER = "BYS360-PRIVATE-WRITE-SCOPE-MARKER"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "support_private_write_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-support-private-write", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "support-private-write-first-login",
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
    from app.models import SupportTicket, User, UserMenuPermission
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        users = {}
        for sicil, role, birim in (
            ("SPW01", "personel", "Birim-A"),
            ("SPW02", "birim_sorumlusu", "Birim-B"),
            ("SPW03", "birim_sorumlusu", "Birim-A"),
            ("SPW04", "admin", "Birim-C"),
        ):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Support", soyad=sicil, role=role,
                        birim=birim, is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()
        for sicil in ("SPW02", "SPW03", "SPW04"):  # K5-Q1: explicit support_all, as assigned in Settings
            db.session.add(UserMenuPermission(user_id=users[sicil].id, menu_key="support_all", is_visible=True,
                                              source_type="user_override"))

        def _ticket(no, private):
            ticket = SupportTicket(ticket_no=no, title=f"Talep {no}", description=MARKER, ticket_type="other",
                                   module_name="test", status="open", created_by_user_id=users["SPW01"].id,
                                   is_private=private, unit_name_snapshot="Birim-A")
            db.session.add(ticket)
            db.session.flush()
            return ticket.id

        flask_app.config["_TICKETS"] = {"private": _ticket("SPW-T1", True), "public": _ticket("SPW-T2", False)}
        flask_app.config["_USER_IDS"] = {sicil: user.id for sicil, user in users.items()}
        db.session.commit()
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _ticket_state(app, key):
    from app.extensions import db
    from app.models import SupportTicket

    with app.app_context():
        ticket = db.session.get(SupportTicket, app.config["_TICKETS"][key])
        assert ticket is not None
        return ticket.status, ticket.assigned_to_user_id


def test_other_unit_manager_cannot_close_a_private_ticket(app):
    _client(app, "SPW02").post(f"/support/{app.config['_TICKETS']['private']}/status", data={"status": "closed"})
    assert _ticket_state(app, "private")[0] == "open"


def test_other_unit_manager_cannot_assign_a_private_ticket_to_themselves(app):
    ticket_id = app.config["_TICKETS"]["private"]
    client = _client(app, "SPW02")
    client.post(f"/support/{ticket_id}/assign", data={"assigned_to_user_id": app.config["_USER_IDS"]["SPW02"]})
    assert _ticket_state(app, "private")[1] is None
    response = client.get(f"/support/{ticket_id}")
    assert MARKER.encode() not in response.data


def test_same_unit_manager_can_still_close_a_private_ticket(app):
    _client(app, "SPW03").post(f"/support/{app.config['_TICKETS']['private']}/status", data={"status": "closed"})
    assert _ticket_state(app, "private")[0] == "closed"


def test_admin_can_still_assign_a_private_ticket(app):
    assignee = app.config["_USER_IDS"]["SPW03"]
    _client(app, "SPW04").post(f"/support/{app.config['_TICKETS']['private']}/assign", data={"assigned_to_user_id": assignee})
    assert _ticket_state(app, "private")[1] == assignee


def test_other_unit_manager_keeps_access_to_non_private_tickets(app):
    client = _client(app, "SPW02")
    ticket_id = app.config["_TICKETS"]["public"]
    client.post(f"/support/{ticket_id}/status", data={"status": "reviewing"})
    assert _ticket_state(app, "public")[0] == "reviewing"
    client.post(f"/support/{ticket_id}/assign", data={"assigned_to_user_id": app.config["_USER_IDS"]["SPW02"]})
    assert _ticket_state(app, "public")[1] == app.config["_USER_IDS"]["SPW02"]
