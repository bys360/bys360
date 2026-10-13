"""Contract K5: one server-side support_all rule for the web and the mobile support views.

Approved policy K5 (HUMAN_POLICY_APPROVED, 2026-10-10):

* ``sistem_yoneticisi`` and ``system_admin`` do not see every support ticket automatically;
* the existing ``support_all`` permission is assigned separately and explicitly, in Settings;
* the web and the mobile API apply the same server-side rule;
* a user without it sees only their own tickets (created by them, or assigned to them to work on);
* no access through the role name, ``role_label`` or the title (``unvan``).

Before K5 the two channels disagreed. The web opened the all-tickets view to the manager family
by role name even when Settings had taken ``support_all`` away from the user, and the mobile API
used its own role list (``_has_global_scope``: admin, baskan, baskan_yardimcisi, baskanlik) for the
list, the detail, internal notes, the open -> reviewing transition and the dashboard and assistant
counters, ignoring ``support_all`` both ways.

Rule now (``app/services/support_ticket_access.py``): ``can_view_all_support_tickets`` is the
``support_all`` permission; ``can_view_support_ticket`` is creator, assignee, or ``support_all`` plus
the Phase 13B private-ticket unit rule.

K5-Q1 (HUMAN_POLICY_APPROVED, 2026-10-10): ``support_all`` comes only from an explicit per-user grant
(``has_support_all_grant``), never from a role default or a unit profile. The former role-default
users below (K507 başkan, K510 birim sorumlusu) therefore see only their own tickets; the assignment
paths are pinned in ``test_k5q_support_all_explicit_grant_contract.py``.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "K5SupportAllAccessTest1!"
MARKER = "BYS360-K5-SUPPORT-ALL-MARKER"
SUPPORT_ALL = "support_all"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "k5_support_all" / "dbs"

# sicil -> (role, birim, role_label, unvan, support_all user override: None = no row)
USERS = {
    "K501": ("personel", "Birim-A", None, None, None),  # creator of every ticket
    "K502": ("sistem_yoneticisi", "Birim-A", None, None, None),
    "K503": ("system_admin", "Birim-A", None, None, None),
    "K504": ("personel", "Birim-A", "Sistem Yöneticisi", "Destek Yöneticisi", None),
    "K505": ("personel", "Birim-A", None, None, True),  # explicit grant, ticket unit
    "K506": ("personel", "Birim-B", None, None, True),  # explicit grant, other unit
    "K507": ("baskan", "Birim-C", None, None, None),  # former role default (K5-Q1: no longer grants)
    "K508": ("personel", "Birim-B", None, None, None),  # assignee of the private ticket
    "K509": ("baskanlik", "Birim-A", None, None, None),  # was a mobile-only global role
    "K510": ("birim_sorumlusu", "Birim-A", None, None, None),  # former role default (K5-Q1: no longer grants)
    "K511": ("baskan", "Birim-C", None, None, False),  # role default removed in Settings
    "K512": ("sistem_yoneticisi", "Birim-A", None, None, True),  # technical role + explicit grant
}
ALL_VIEW = {"K505", "K506", "K512"}
NO_ALL_VIEW = {"K502", "K503", "K504", "K507", "K508", "K509", "K510", "K511"}


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-k5-support-all", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "k5-support-all-first-login",
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
        for sicil, (role, birim, role_label, unvan, _grant) in USERS.items():
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Destek", soyad=sicil, role=role,
                        role_label=role_label, unvan=unvan, birim=birim, is_active=True,
                        must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()
        for sicil, (*_rest, grant) in USERS.items():
            if grant is not None:
                db.session.add(UserMenuPermission(user_id=users[sicil].id, menu_key=SUPPORT_ALL, is_visible=grant,
                                                  source_type="user_override"))

        def _ticket(no, private, assignee=None):
            ticket = SupportTicket(ticket_no=no, title=f"Talep {no}", description=MARKER, ticket_type="other",
                                   module_name="test", status="open", created_by_user_id=users["K501"].id,
                                   assigned_to_user_id=users[assignee].id if assignee else None,
                                   is_private=private, unit_name_snapshot="Birim-A")
            db.session.add(ticket)
            db.session.flush()
            return ticket.id

        flask_app.config["_TICKETS"] = {"private": _ticket("K5-T1", True, assignee="K508"), "public": _ticket("K5-T2", False)}
        flask_app.config["_USER_IDS"] = {sicil: user.id for sicil, user in users.items()}
        db.session.commit()
    return flask_app


def _user(app, sicil):
    from app.extensions import db
    from app.models import User

    user = db.session.get(User, app.config["_USER_IDS"][sicil])
    assert user is not None
    return user


def _headers(app, sicil):
    from app.api.mobile.shared import _issue_token

    with app.app_context():
        return {"Authorization": f"Bearer {_issue_token(_user(app, sicil))}"}


def _mobile_detail(app, sicil, key):
    return app.test_client().get(f"/api/mobile/support/tickets/{app.config['_TICKETS'][key]}", headers=_headers(app, sicil))


def _mobile_list(app, sicil):
    response = app.test_client().get("/api/mobile/support/tickets", headers=_headers(app, sicil))
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _mobile_reply(app, sicil, key, *, internal=False):
    ticket_id = app.config["_TICKETS"][key]
    return app.test_client().post(f"/api/mobile/support/tickets/{ticket_id}/reply",
                                  json={"message": "K5 mobil cevap metni", "is_internal": internal},
                                  headers=_headers(app, sicil))


def _web_client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _web_detail_shows_ticket(app, sicil, key):
    page = _web_client(app, sicil).get(f"/support/{app.config['_TICKETS'][key]}")
    return page.status_code == 200 and MARKER.encode() in page.data


def _ticket_state(app, key):
    from app.extensions import db
    from app.models import SupportTicket, SupportTicketMessage

    with app.app_context():
        ticket_id = app.config["_TICKETS"][key]
        ticket = db.session.get(SupportTicket, ticket_id)
        assert ticket is not None
        messages = db.session.query(SupportTicketMessage).filter_by(ticket_id=ticket_id).all()
        return ticket.status, [bool(row.is_internal) for row in messages]


def _helpers(app, sicil):
    from app.extensions import db
    from app.models import SupportTicket
    from app.services.support_ticket_access import (
        can_view_all_support_tickets,
        can_view_support_ticket,
    )

    with app.app_context(), app.test_request_context():
        user = _user(app, sicil)
        tickets = {key: db.session.get(SupportTicket, ticket_id) for key, ticket_id in app.config["_TICKETS"].items()}
        return (can_view_all_support_tickets(user),
                {key: can_view_support_ticket(ticket, user) for key, ticket in tickets.items()})


# --- the shared server-side rule -------------------------------------------------------------


@pytest.mark.parametrize("sicil", sorted(ALL_VIEW))
def test_support_all_holders_get_the_all_tickets_view(app, sicil):
    all_view, _ = _helpers(app, sicil)
    assert all_view is True


@pytest.mark.parametrize("sicil", sorted(NO_ALL_VIEW))
def test_no_role_name_label_or_title_grants_the_all_tickets_view(app, sicil):
    # K502/K503 technical roles, K504 role_label "Sistem Yöneticisi" + unvan, K509 the old mobile
    # global role, K511 the admin family with support_all removed in Settings.
    all_view, _ = _helpers(app, sicil)
    assert all_view is False


def test_anonymous_and_missing_users_get_nothing():
    from app.services.support_ticket_access import (
        can_view_all_support_tickets,
        can_view_support_ticket,
    )

    ticket = SimpleNamespace(created_by_user_id=0, assigned_to_user_id=0, is_private=False, unit_name_snapshot=None)
    assert can_view_all_support_tickets(None) is False
    assert can_view_support_ticket(ticket, None) is False
    anonymous = SimpleNamespace(id=None, is_authenticated=False, role="admin")
    assert can_view_all_support_tickets(anonymous) is False
    assert can_view_support_ticket(ticket, anonymous) is False


# --- mobile: list, detail, reply, internal notes, status, counters ---------------------------


@pytest.mark.parametrize("sicil", ["K502", "K503", "K504", "K507", "K509", "K510", "K511"])
def test_mobile_users_without_support_all_reach_only_their_own_tickets(app, sicil):
    for key in ("private", "public"):
        response = _mobile_detail(app, sicil, key)
        assert response.status_code == 403
        assert MARKER.encode() not in response.data
        assert _mobile_reply(app, sicil, key).status_code == 403
        assert _ticket_state(app, key) == ("open", [])
    body = _mobile_list(app, sicil)
    assert "Talep K5-T1" not in body and "Talep K5-T2" not in body


@pytest.mark.parametrize("sicil", ["K505", "K512"])
def test_mobile_support_all_holders_see_and_answer_every_ticket(app, sicil):
    body = _mobile_list(app, sicil)
    assert "Talep K5-T1" in body and "Talep K5-T2" in body
    for key in ("private", "public"):
        response = _mobile_detail(app, sicil, key)
        assert response.status_code == 200
        assert MARKER.encode() in response.data
        assert response.get_json()["can_manage"] is True


def test_mobile_support_all_of_another_unit_keeps_the_private_ticket_rule(app):
    assert _mobile_detail(app, "K506", "public").status_code == 200
    response = _mobile_detail(app, "K506", "private")
    assert response.status_code == 403
    assert MARKER.encode() not in response.data
    assert _mobile_reply(app, "K506", "private").status_code == 403


def test_mobile_assignee_reaches_the_ticket_assigned_to_them_like_the_web(app):
    response = _mobile_detail(app, "K508", "private")
    assert response.status_code == 200
    assert MARKER.encode() in response.data
    assert response.get_json()["can_manage"] is False
    assert _web_detail_shows_ticket(app, "K508", "private") is True
    assert _mobile_detail(app, "K508", "public").status_code == 403


def test_mobile_internal_note_and_status_change_need_support_all(app):
    # The assignee may answer, but only as a comment and without moving the ticket to review.
    assert _mobile_reply(app, "K508", "private", internal=True).status_code == 200
    assert _ticket_state(app, "private") == ("open", [False])
    # A support_all holder writes an internal note and takes the ticket into review.
    assert _mobile_reply(app, "K505", "private", internal=True).status_code == 200
    assert _ticket_state(app, "private") == ("reviewing", [False, True])


def test_mobile_internal_notes_are_hidden_without_support_all(app):
    assert _mobile_reply(app, "K505", "private", internal=True).status_code == 200
    holder = _mobile_detail(app, "K505", "private").get_json()
    assignee = _mobile_detail(app, "K508", "private").get_json()
    assert any(row["is_internal"] for row in holder["messages"])
    assert not any(row["is_internal"] for row in assignee["messages"])


def _open_ticket_count_on_dashboard(app, sicil):
    response = app.test_client().get("/api/mobile/dashboard/summary", headers=_headers(app, sicil))
    assert response.status_code == 200
    return response.get_json()["open_tickets"]


def _open_ticket_count_in_assistant(app, sicil):
    response = app.test_client().post("/api/mobile/assistant/v2/ask", json={"question": ""}, headers=_headers(app, sicil))
    assert response.status_code == 200
    metrics = {row["title"]: row["value"] for row in response.get_json()["metrics"]}
    return int(metrics["Destek"])


@pytest.mark.parametrize("sicil", ["K502", "K503", "K507", "K509", "K510", "K511"])
def test_mobile_counters_count_only_own_tickets_without_support_all(app, sicil):
    assert _open_ticket_count_on_dashboard(app, sicil) == 0
    assert _open_ticket_count_in_assistant(app, sicil) == 0


@pytest.mark.parametrize("sicil", ["K505", "K512"])
def test_mobile_counters_count_every_ticket_with_support_all(app, sicil):
    assert _open_ticket_count_on_dashboard(app, sicil) == 2
    assert _open_ticket_count_in_assistant(app, sicil) == 2


# --- web: the same rule ----------------------------------------------------------------------


def test_web_settings_removal_of_support_all_closes_the_all_view_for_the_admin_family(app):
    # K511 is baskan (admin family) with support_all set to hidden in Settings: the role name used
    # to reopen the all-tickets view and other people's tickets on the web.
    client = _web_client(app, "K511")
    assert MARKER.encode() not in client.get(f"/support/{app.config['_TICKETS']['public']}").data
    assert b"Talep K5-T2" not in client.get("/support/all").data


@pytest.mark.parametrize("sicil", ["K502", "K503", "K504", "K507", "K509", "K510", "K511"])
def test_web_users_without_support_all_reach_only_their_own_tickets(app, sicil):
    assert _web_detail_shows_ticket(app, sicil, "public") is False
    assert _web_detail_shows_ticket(app, sicil, "private") is False


@pytest.mark.parametrize("sicil", ["K505", "K512"])
def test_web_support_all_holders_see_every_ticket(app, sicil):
    assert _web_detail_shows_ticket(app, sicil, "public") is True
    assert _web_detail_shows_ticket(app, sicil, "private") is True


@pytest.mark.parametrize("sicil", sorted(USERS))
def test_web_and_mobile_agree_for_every_user_and_ticket(app, sicil):
    _, per_ticket = _helpers(app, sicil)
    for key, allowed in per_ticket.items():
        assert (_mobile_detail(app, sicil, key).status_code == 200) is allowed, (sicil, key)
        assert _web_detail_shows_ticket(app, sicil, key) is allowed, (sicil, key)
