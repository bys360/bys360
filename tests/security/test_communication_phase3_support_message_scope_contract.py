"""Contract: posting to a Faz 3 support ticket uses the same access rule as reading it.

GET /communication/faz3/support/<id> shows a ticket only to a manager, its creator or
its assignee (support_detail_payload). The POST branch of the same route called
add_support_message before that check, with no check of its own, so a non-manager
holding the "support_all" menu (by default: koordinator) could add a message to any
ticket and notify its creator and assignee.

The same route family also ignored the private-ticket unit scope that /support/<id>
enforces (Phase 13B): any Faz 3 manager, birim_sorumlusu included, could read, answer,
assign or close a private ticket of another unit.

K5-Q1/K5-Q3 (approved policy, 2026-10-10): ``support_all`` is an explicit per-person grant, never a
role default, and every Faz 3 support route checks it (``menu_key_required("support_all")`` and
``can_view_all_support_tickets``). The "managers" below (SMS03 admin, SMS04 and SMS05
birim_sorumlusu) hold the grant, as an admin assigns it in Settings; the koordinator SMS02 does not:
it reaches no Faz 3 support page and answers its own and assigned tickets on /support/<id>.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "SupportMessageScopeTest1!"
INTRUDER_MESSAGE = "Yetkisiz mesaj SMS1"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "support_message_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-support-message-scope", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "support-message-scope-first-login",
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

    with flask_app.app_context():
        db.create_all()
        users = {}
        for sicil, role, birim in (
            ("SMS01", "personel", "Birim A"),
            ("SMS02", "koordinator", "Birim A"),
            ("SMS03", "admin", "Birim A"),
            ("SMS04", "birim_sorumlusu", "Birim B"),
            ("SMS05", "birim_sorumlusu", "Birim A"),
        ):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Support", soyad=sicil, role=role,
                        birim=birim, is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()
        for sicil in ("SMS03", "SMS04", "SMS05"):  # K5-Q1: explicit support_all, as assigned in Settings
            db.session.add(UserMenuPermission(user_id=users[sicil].id, menu_key="support_all", is_visible=True,
                                              source_type="user_override"))

        def _ticket(no, creator, assignee=None, private=False):
            ticket = SupportTicket(ticket_no=no, title=f"Talep {no}", description=f"Aciklama {no}",
                                   ticket_type="question", module_name="genel", status="open",
                                   created_by_user_id=creator.id,
                                   assigned_to_user_id=assignee.id if assignee else None,
                                   is_private=private, unit_name_snapshot="Birim A")
            db.session.add(ticket)
            db.session.flush()
            return ticket.id

        flask_app.config["_TICKETS"] = {
            "foreign": _ticket("SMS-T1", users["SMS01"]),
            "own": _ticket("SMS-T2", users["SMS02"]),
            "assigned": _ticket("SMS-T3", users["SMS01"], users["SMS02"]),
            "private": _ticket("SMS-T4", users["SMS01"], private=True),
        }
        flask_app.config["_USER_IDS"] = {sicil: user.id for sicil, user in users.items()}
        db.session.commit()
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _messages(app, ticket_id):
    from app.models import SupportTicketMessage

    with app.app_context():
        return [row.message for row in SupportTicketMessage.query.filter_by(ticket_id=ticket_id).all()]


def _notifications(app, user_sicil):
    from app.models import Notification, User

    with app.app_context():
        user = User.query.filter_by(sicil_no=user_sicil).one()
        return Notification.query.filter_by(user_id=user.id, source_type="support_ticket").count()


def _post(app, sicil, ticket_key, text):
    ticket_id = app.config["_TICKETS"][ticket_key]
    return _client(app, sicil).post(f"/communication/faz3/support/{ticket_id}", data={"message": text})


def test_non_manager_cannot_read_a_foreign_ticket(app):
    ticket_id = app.config["_TICKETS"]["foreign"]
    response = _client(app, "SMS02").get(f"/communication/faz3/support/{ticket_id}")
    assert response.status_code in (302, 403)  # K5-Q: no support_all, no Faz 3 support page
    assert f"/communication/faz3/support/{ticket_id}" not in response.headers.get("Location", "")
    assert b"Aciklama SMS-T1" not in response.data


def test_non_manager_cannot_post_to_a_foreign_ticket(app):
    _post(app, "SMS02", "foreign", INTRUDER_MESSAGE)
    assert INTRUDER_MESSAGE not in _messages(app, app.config["_TICKETS"]["foreign"])
    assert _notifications(app, "SMS01") == 0


@pytest.mark.parametrize("ticket_key", ["own", "assigned"])
def test_non_manager_can_post_to_own_or_assigned_ticket(app, ticket_key):
    # K5-Q: without support_all the koordinator answers its own and assigned tickets on /support.
    ticket_id = app.config["_TICKETS"][ticket_key]
    _client(app, "SMS02").post(f"/support/{ticket_id}/comment", data={"message": f"Mesaj {ticket_key}"})
    assert f"Mesaj {ticket_key}" in _messages(app, ticket_id)


def test_manager_can_post_to_any_ticket(app):
    _post(app, "SMS03", "foreign", "Yonetici mesaji")
    assert "Yonetici mesaji" in _messages(app, app.config["_TICKETS"]["foreign"])


def _ticket_state(app, key):
    from app.extensions import db
    from app.models import SupportTicket

    with app.app_context():
        ticket = db.session.get(SupportTicket, app.config["_TICKETS"][key])
        assert ticket is not None
        return ticket.status, ticket.assigned_to_user_id


def test_other_unit_manager_cannot_read_a_private_ticket(app):
    ticket_id = app.config["_TICKETS"]["private"]
    response = _client(app, "SMS04").get(f"/communication/faz3/support/{ticket_id}", follow_redirects=True)
    assert b"Aciklama SMS-T4" not in response.data


def test_other_unit_manager_cannot_answer_assign_or_close_a_private_ticket(app):
    ticket_id = app.config["_TICKETS"]["private"]
    client = _client(app, "SMS04")
    client.post(f"/communication/faz3/support/{ticket_id}", data={"message": INTRUDER_MESSAGE})
    client.post(f"/communication/faz3/support/{ticket_id}/assign",
                data={"assigned_to_user_id": str(app.config["_USER_IDS"]["SMS04"])})
    client.post(f"/communication/faz3/support/{ticket_id}/status", data={"status": "closed"})
    assert INTRUDER_MESSAGE not in _messages(app, ticket_id)
    assert _ticket_state(app, "private") == ("open", None)


def test_manager_can_open_the_queue_and_a_ticket(app):
    # _sla_snapshot_for_ticket called .filter() on the plain-list "messages" relationship,
    # so both pages answered 500 as soon as one ticket was visible.
    client = _client(app, "SMS03")
    assert client.get("/communication/faz3/support/queue").status_code == 200
    response = client.get(f"/communication/faz3/support/{app.config['_TICKETS']['foreign']}")
    assert response.status_code == 200 and b"Aciklama SMS-T1" in response.data


def test_same_unit_manager_and_admin_keep_access_to_a_private_ticket(app):
    ticket_id = app.config["_TICKETS"]["private"]
    response = _client(app, "SMS05").get(f"/communication/faz3/support/{ticket_id}")
    assert response.status_code == 200 and b"Aciklama SMS-T4" in response.data
    _client(app, "SMS03").post(f"/communication/faz3/support/{ticket_id}/status", data={"status": "reviewing"})
    assert _ticket_state(app, "private")[0] == "reviewing"
