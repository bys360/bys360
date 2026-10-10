"""Contract K5 metadata rule: a support ticket outside the viewer's scope leaks no metadata anywhere.

Approved policy (HUMAN_POLICY_APPROVED, 2026-10-10): a user without access to a support ticket sees
neither its content nor its title, number, status, attachments, notification content or any search
or dashboard metadata. ``support_all`` is an explicit per-person grant (K5-Q1) and even a holder sees
another unit's private ticket only through the private-ticket rule (``can_view_private_support_ticket``).

The rule has one SQL form, ``support_ticket_visibility_clause(user)``: own tickets (creator or
assignee), plus, for a ``support_all`` holder, every ticket the private-ticket rule lets them open.
Every list, counter, search, report, export and status history below uses it; detail, attachment
and AI triage use ``can_view_support_ticket``.

Before: the Faz 1 dashboard and the Faz 1 support center listed every ticket (number, title, the
start of the description) to every user with the ``notifications`` / ``support_index`` menu; the
Faz 5 support operations and SLA screens listed every open ticket and the latest status notes of
all tickets; ``/support/all``, the mobile list, Faz 3 and Faz 4 listed other units' private tickets
to any holder; AI triage read any ticket for a manager-family role.
"""
from __future__ import annotations

import csv
import io
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "K5qMetadataScopeTest1!"
PUB_NO, PUB_TITLE = "K5QM-PUB-01", "K5QM-ACIK-BASLIK"
PRV_NO, PRV_TITLE = "K5QM-PRV-02", "K5QM-GIZLI-BASLIK"
PRV_NOTE = "K5QM-GIZLI-DURUM-NOTU"
PRV_BODY = "K5QM-GIZLI-ICERIK"
PRIVATE_TOKENS = (PRV_NO, PRV_TITLE, PRV_NOTE, PRV_BODY)
ALL_TOKENS = PRIVATE_TOKENS + (PUB_NO, PUB_TITLE)
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "k5q_support_metadata" / "dbs"

# key -> (role, birim, explicit support_all grant)
USERS = {
    "creator": ("personel", "Birim-A", False),
    "holder_a": ("personel", "Birim-A", True),
    "holder_b": ("personel", "Birim-B", True),
    "colleague": ("personel", "Birim-A", False),
    "baskan": ("baskan", "Birim-C", False),
}

# Screens that list tickets to a support_all holder. A search page echoes its own query back in the
# search box, so the searched token itself is not counted there.
HOLDER_SCREENS = [
    "/support",
    "/support/all",
    f"/support/all?q={PRV_TITLE}",
    f"/support/all?q={PRV_NO}",
    f"/support/all?q={PRV_BODY}",
    "/communication/faz1",
    "/communication/faz1/support",
    "/communication/faz3/support/queue",
    "/communication/faz4",
    "/communication/faz4/reports",
    "/communication/faz4/support/analytics",
    "/communication/faz5/support-operations",
    "/communication/faz5/escalations",
]
# Screens a user without support_all may open; none may show other people's tickets.
NON_HOLDER_SCREENS = [
    "/support",
    "/communication/faz1",
    "/communication/faz1/support",
    "/communication/faz3/support/queue",
    "/communication/faz4",
    "/communication/faz4/reports",
]


@pytest.fixture
def env(monkeypatch, tmp_path):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-k5q-support-metadata", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "k5q-support-metadata-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri,
                            UPLOAD_FOLDER=str(tmp_path / "uploads"))
    from app.extensions import db
    from app.models import (
        SupportTicket,
        SupportTicketAttachment,
        SupportTicketStatusHistory,
        User,
        UserMenuPermission,
    )
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        users = {}
        for index, (key, (role, birim, _grant)) in enumerate(USERS.items()):
            user = User(sicil_no=f"K5QM{index:02d}", email=f"k5qm{index:02d}@example.gov.tr", ad="Meta", soyad=key,
                        role=role, birim=birim, is_active=True, must_change_password=False,
                        must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[key] = user
        db.session.flush()
        for key, (_role, _birim, grant) in USERS.items():
            if grant:  # support_all as assigned in Settings; reports opens the Faz 4 screens
                for menu_key in ("support_all", "reports"):
                    db.session.add(UserMenuPermission(user_id=users[key].id, menu_key=menu_key, is_visible=True,
                                                      source_type="user_override"))
        created = datetime.utcnow() - timedelta(days=10)  # open past every SLA target: breach rows

        def _ticket(no, title, private, priority):
            ticket = SupportTicket(ticket_no=no, title=title, description=PRV_BODY if private else "acik talep",
                                   ticket_type="other", module_name="test", status="open", priority=priority,
                                   created_by_user_id=users["creator"].id, is_private=private,
                                   unit_name_snapshot="Birim-A", created_at=created, updated_at=created)
            db.session.add(ticket)
            db.session.flush()
            return ticket

        public = _ticket(PUB_NO, PUB_TITLE, False, "normal")
        private = _ticket(PRV_NO, PRV_TITLE, True, "critical")
        db.session.add(SupportTicketStatusHistory(ticket_id=private.id, old_status=None, new_status="open",
                                                  changed_by_user_id=users["creator"].id, note=PRV_NOTE))
        attachment = SupportTicketAttachment(ticket_id=private.id, uploaded_by_user_id=users["creator"].id,
                                             filename="gizli.txt", stored_name=f"{uuid.uuid4().hex}.txt",
                                             mime_type="text/plain", file_size=5, attachment_type="document")
        db.session.add(attachment)
        db.session.flush()
        folder = Path(flask_app.config["UPLOAD_FOLDER"]) / "support_tickets" / str(private.id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / attachment.stored_name).write_text("gizli", encoding="utf-8")
        ids = {key: user.id for key, user in users.items()}
        sicils = {key: user.sicil_no for key, user in users.items()}
        tickets = {"public": public.id, "private": private.id, "attachment": attachment.id}
        db.session.commit()

    return SimpleNamespace(app=flask_app, ids=ids, sicils=sicils, tickets=tickets)


def _web(env, who):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": env.sicils[who], "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), who
    return client


def _bearer(env, who):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[who])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _page(client, path):
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.get_data(as_text=True)


def _leaks(text, tokens, path=""):
    echoed = path.split("?q=", 1)[1] if "?q=" in path else None
    return [token for token in tokens if token != echoed and token in text]


# --- a support_all holder of another unit: the private ticket is invisible -------------------


@pytest.mark.parametrize("path", HOLDER_SCREENS)
def test_other_unit_holder_sees_no_private_ticket_metadata(env, path):
    assert _leaks(_page(_web(env, "holder_b"), path), PRIVATE_TOKENS, path) == []


@pytest.mark.parametrize("path", ["/support/all", "/communication/faz1/support", "/communication/faz3/support/queue",
                                  "/communication/faz5/support-operations", "/communication/faz5/escalations"])
def test_same_unit_holder_keeps_both_tickets(env, path):
    text = _page(_web(env, "holder_a"), path)
    assert PUB_TITLE in text and PRV_TITLE in text


@pytest.mark.parametrize("path", ["/support/all", "/communication/faz1/support", "/communication/faz3/support/queue",
                                  "/communication/faz5/support-operations", "/communication/faz5/escalations"])
def test_other_unit_holder_keeps_the_public_ticket(env, path):
    assert PUB_TITLE in _page(_web(env, "holder_b"), path)


def test_other_unit_holder_mobile_list_and_counters_skip_the_private_ticket(env):
    client = env.app.test_client()
    listing = client.get("/api/mobile/support/tickets", headers=_bearer(env, "holder_b")).get_data(as_text=True)
    assert _leaks(listing, PRIVATE_TOKENS) == [] and PUB_TITLE in listing
    summary = client.get("/api/mobile/dashboard/summary", headers=_bearer(env, "holder_b")).get_json()
    assert summary["open_tickets"] == 1
    assert client.get("/api/mobile/dashboard/summary", headers=_bearer(env, "holder_a")).get_json()["open_tickets"] == 2


def test_other_unit_holder_web_dashboard_counters_skip_the_private_ticket(env):
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.support.routes import _build_dashboard_context

    with env.app.app_context(), env.app.test_request_context():
        login_user(db.session.get(User, env.ids["holder_b"]))
        counts = _build_dashboard_context()["counts"]
        assert counts["all_total"] == 1 and counts["critical_open"] == 0


def test_other_unit_holder_is_refused_detail_attachment_and_mobile_detail(env):
    client = _web(env, "holder_b")
    private = env.tickets["private"]
    for path in (f"/support/{private}", f"/support/{private}/attachments/{env.tickets['attachment']}",
                 f"/communication/faz3/support/{private}"):
        response = client.get(path)
        assert response.status_code in (302, 403, 404), path
        assert _leaks(response.get_data(as_text=True), PRIVATE_TOKENS) == [], path
    mobile = env.app.test_client().get(f"/api/mobile/support/tickets/{private}", headers=_bearer(env, "holder_b"))
    assert mobile.status_code == 403 and _leaks(mobile.get_data(as_text=True), PRIVATE_TOKENS) == []


def test_same_unit_holder_downloads_the_attachment(env):
    response = _web(env, "holder_a").get(f"/support/{env.tickets['private']}/attachments/{env.tickets['attachment']}")
    assert response.status_code == 200 and response.data == b"gizli"


def _export_rows(env, who):
    response = _web(env, who).post("/communication/faz4/export", data={"export_type": "support_analytics"})
    assert response.status_code == 200, response.status_code
    return response.data.decode("utf-8-sig")


def test_faz4_support_export_is_scoped_to_the_holder(env):
    other_unit = _export_rows(env, "holder_b")
    assert _leaks(other_unit, PRIVATE_TOKENS) == [] and PUB_TITLE in other_unit
    same_unit = _export_rows(env, "holder_a")
    assert PRV_TITLE in same_unit and len(list(csv.reader(io.StringIO(same_unit)))) > 1


# --- users without support_all: no other people's tickets on any screen -----------------------


@pytest.mark.parametrize("who", ["colleague", "baskan"])
@pytest.mark.parametrize("path", NON_HOLDER_SCREENS)
def test_non_holders_see_no_other_peoples_ticket_metadata(env, who, path):
    response = _web(env, who).get(path)
    assert response.status_code in (200, 302, 403), (path, response.status_code)
    assert _leaks(response.get_data(as_text=True), ALL_TOKENS) == []


@pytest.mark.parametrize("who", ["colleague", "baskan"])
def test_non_holders_mobile_list_and_counters_show_only_their_own_tickets(env, who):
    client = env.app.test_client()
    listing = client.get("/api/mobile/support/tickets", headers=_bearer(env, who)).get_data(as_text=True)
    assert _leaks(listing, ALL_TOKENS) == []
    assert client.get("/api/mobile/dashboard/summary", headers=_bearer(env, who)).get_json()["open_tickets"] == 0


def test_the_creator_keeps_its_own_tickets_on_the_faz1_screens(env):
    client = _web(env, "creator")
    for path in ("/communication/faz1", "/communication/faz1/support"):
        text = _page(client, path)
        assert PUB_TITLE in text and PRV_TITLE in text, path


# --- AI triage reads a ticket only under the same object rule ----------------------------------


@pytest.mark.parametrize("who,ticket_key", [("baskan", "public"), ("baskan", "private"), ("colleague", "public"),
                                            ("holder_b", "private")])
def test_ai_triage_refuses_tickets_outside_the_viewer_scope(env, who, ticket_key):
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.services.ai.guardrails import AIInputError
    from app.services.ai.query_adapters import get_support_ticket_payload

    with env.app.app_context(), env.app.test_request_context():
        login_user(db.session.get(User, env.ids[who]))
        with pytest.raises(AIInputError):
            get_support_ticket_payload(env.tickets[ticket_key])


@pytest.mark.parametrize("who,ticket_key", [("creator", "private"), ("holder_a", "private"), ("holder_b", "public")])
def test_ai_triage_keeps_tickets_inside_the_viewer_scope(env, who, ticket_key):
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.services.ai.query_adapters import get_support_ticket_payload

    with env.app.app_context(), env.app.test_request_context():
        login_user(db.session.get(User, env.ids[who]))
        ticket, payload = get_support_ticket_payload(env.tickets[ticket_key])
        assert ticket.id == env.tickets[ticket_key]
