"""Contract: mobile support ticket detail and reply apply the shared private-ticket rule.

``can_view_private_support_ticket`` (``app/services/support_ticket_access.py``, Phase 13B
NEW-1) limits a private ticket, for everyone but its creator, to the admin family and to
users of the ticket's unit (``unit_name_snapshot`` in ``{birim, ust_birim}``). /support/*
and /communication/faz3/support/* both apply it (Wave 2, fixes 2 and 3).

GET /api/mobile/support/tickets/<id> and POST /api/mobile/support/tickets/<id>/reply only
checked ``_can_mobile_view_ticket`` (creator or any mobile global role), which never read
``is_private``. A mobile global role outside the admin family (``ik``,
``performans_yetkilisi``, ...) of another unit could read the body, the messages and the
internal notes of a private ticket, and answer it, although the web refuses the same user.

Rule reused: ``can_view_private_support_ticket`` on top of the mobile global scope. The
creator, the admin family and same-unit global roles keep access; tickets that are not
private are unaffected; the mobile list is unchanged (private titles in lists are H3).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "MobileSupportPrivate1!"
MARKER = "BYS360-MOBILE-PRIVATE-TICKET-MARKER"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_support_private_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-mobile-support-private", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "mobile-support-private-first-login",
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
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        users = {}
        for sicil, role, birim in (
            ("MSP01", "personel", "Birim-A"),
            ("MSP02", "ik", "Birim-B"),
            ("MSP03", "ik", "Birim-A"),
            ("MSP04", "admin", "Birim-C"),
            ("MSP05", "personel", "Birim-A"),
            ("MSP06", "performans_yetkilisi", "Birim-B"),
        ):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Support", soyad=sicil, role=role,
                        birim=birim, is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()

        def _ticket(no, private):
            ticket = SupportTicket(ticket_no=no, title=f"Talep {no}", description=MARKER, ticket_type="other",
                                   module_name="test", status="open", created_by_user_id=users["MSP01"].id,
                                   is_private=private, unit_name_snapshot="Birim-A")
            db.session.add(ticket)
            db.session.flush()
            return ticket.id

        flask_app.config["_TICKETS"] = {"private": _ticket("MSP-T1", True), "public": _ticket("MSP-T2", False)}
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


def _detail(app, sicil, key):
    ticket_id = app.config["_TICKETS"][key]
    return app.test_client().get(f"/api/mobile/support/tickets/{ticket_id}", headers=_headers(app, sicil))


def _reply(app, sicil, key):
    ticket_id = app.config["_TICKETS"][key]
    return app.test_client().post(
        f"/api/mobile/support/tickets/{ticket_id}/reply", json={"message": "Mobil cevap metni"}, headers=_headers(app, sicil)
    )


def _message_count(app, key):
    from app.extensions import db
    from app.models import SupportTicketMessage

    with app.app_context():
        return db.session.query(SupportTicketMessage).filter_by(ticket_id=app.config["_TICKETS"][key]).count()


def test_web_hides_the_private_ticket_from_an_other_unit_global_role(app):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": "MSP02", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    page = client.get(f"/support/{app.config['_TICKETS']['private']}")
    assert MARKER.encode() not in page.data


@pytest.mark.parametrize("sicil", ["MSP02", "MSP06"])
def test_other_unit_mobile_global_role_cannot_read_a_private_ticket(app, sicil):
    response = _detail(app, sicil, "private")
    assert response.status_code == 403
    assert MARKER.encode() not in response.data


@pytest.mark.parametrize("sicil", ["MSP02", "MSP06"])
def test_other_unit_mobile_global_role_cannot_reply_to_a_private_ticket(app, sicil):
    assert _reply(app, sicil, "private").status_code == 403
    assert _message_count(app, "private") == 0


def test_other_unit_mobile_global_role_keeps_access_to_non_private_tickets(app):
    response = _detail(app, "MSP02", "public")
    assert response.status_code == 200
    assert MARKER.encode() in response.data
    assert _reply(app, "MSP02", "public").status_code == 200
    assert _message_count(app, "public") == 1


@pytest.mark.parametrize("sicil", ["MSP01", "MSP03", "MSP04"])
def test_creator_same_unit_global_role_and_admin_keep_private_ticket_access(app, sicil):
    response = _detail(app, sicil, "private")
    assert response.status_code == 200
    assert MARKER.encode() in response.data
    assert _reply(app, sicil, "private").status_code == 200
    assert _message_count(app, "private") == 1


def test_non_creator_personnel_is_still_refused(app):
    assert _detail(app, "MSP05", "private").status_code == 403
    assert _reply(app, "MSP05", "private").status_code == 403
    assert _message_count(app, "private") == 0


def _list_body(app, sicil):
    response = app.test_client().get("/api/mobile/support/tickets", headers=_headers(app, sicil))
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("sicil", ["MSP02", "MSP06"])
def test_other_unit_mobile_global_role_list_omits_the_private_ticket_body(app, sicil):
    # The list showed a 180-character description snippet of every ticket. The private-ticket
    # rule hides the body on the detail; the title stays listed (human decision H3).
    body = _list_body(app, sicil)
    assert "Talep MSP-T1" in body
    assert body.count(MARKER) == 1


@pytest.mark.parametrize("sicil", ["MSP03", "MSP04"])
def test_same_unit_global_role_and_admin_list_keeps_the_private_ticket_body(app, sicil):
    assert _list_body(app, sicil).count(MARKER) == 2
