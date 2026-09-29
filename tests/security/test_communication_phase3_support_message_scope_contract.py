"""Contract: posting to a Faz 3 support ticket uses the same access rule as reading it.

GET /communication/faz3/support/<id> shows a ticket only to a manager, its creator or
its assignee (support_detail_payload). The POST branch of the same route called
add_support_message before that check, with no check of its own, so a non-manager
holding the "support_all" menu (by default: koordinator) could add a message to any
ticket and notify its creator and assignee.
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
    from app.models import SupportTicket, User

    with flask_app.app_context():
        db.create_all()
        users = {}
        for sicil, role in (("SMS01", "personel"), ("SMS02", "koordinator"), ("SMS03", "admin")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Support", soyad=sicil, role=role,
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()

        def _ticket(no, creator, assignee=None):
            ticket = SupportTicket(ticket_no=no, title=f"Talep {no}", description="Aciklama", ticket_type="question",
                                   module_name="genel", created_by_user_id=creator.id,
                                   assigned_to_user_id=assignee.id if assignee else None)
            db.session.add(ticket)
            db.session.flush()
            return ticket.id

        flask_app.config["_TICKETS"] = {
            "foreign": _ticket("SMS-T1", users["SMS01"]),
            "own": _ticket("SMS-T2", users["SMS02"]),
            "assigned": _ticket("SMS-T3", users["SMS01"], users["SMS02"]),
        }
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
    assert response.status_code == 302
    assert f"/communication/faz3/support/{ticket_id}" not in response.headers.get("Location", "")


def test_non_manager_cannot_post_to_a_foreign_ticket(app):
    _post(app, "SMS02", "foreign", INTRUDER_MESSAGE)
    assert INTRUDER_MESSAGE not in _messages(app, app.config["_TICKETS"]["foreign"])
    assert _notifications(app, "SMS01") == 0


@pytest.mark.parametrize("ticket_key", ["own", "assigned"])
def test_non_manager_can_post_to_own_or_assigned_ticket(app, ticket_key):
    _post(app, "SMS02", ticket_key, f"Mesaj {ticket_key}")
    assert f"Mesaj {ticket_key}" in _messages(app, app.config["_TICKETS"][ticket_key])


def test_manager_can_post_to_any_ticket(app):
    _post(app, "SMS03", "foreign", "Yonetici mesaji")
    assert "Yonetici mesaji" in _messages(app, app.config["_TICKETS"]["foreign"])
