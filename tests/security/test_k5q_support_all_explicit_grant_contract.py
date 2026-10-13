"""Contract K5-Q1/K5-Q2/K5-Q3: support_all is an explicit, admin-assigned, per-person grant.

Approved decisions (HUMAN_POLICY_APPROVED, 2026-10-10):

* K5-Q1: ``support_all`` (the institution-wide support ticket view) is assigned only explicitly and
  per person. It is never gained through a role default or a unit profile.
* K5-Q2: only the server-verified ``admin`` role assigns or removes it, and only for ANOTHER user.
  Self-grant, bulk apply, templates, import, archives and rollback never grant it; every change is
  written to the settings change log.
* K5-Q3: every web and mobile support screen, Faz 3 included, applies the same central server-side
  ``support_all`` check; no extra role or title condition blocks a legitimate holder.

Before: ``support_all`` was a role default (admin, başkan, başkan yardımcısı, grup başkanı, mali
müşavir, koordinatör, birim sorumlusu) and a unit-profile key; every admin-family user could set it
for anyone, themselves included, on /settings; the Faz 3 pages also required a manager role; and new
ticket notifications went to users whose role, role_label or title merely contained "admin",
"destek", "ik" and similar tokens.

Rule now: ``has_support_all_grant`` (an active user's own visible ``user_override`` row) is the only
source. ``can_view_all_support_tickets``, the menu map, ``menu_key_required("support_all")``, Faz 3
and the support notifications read it.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "K5qSupportGrantTest1!"
MARKER = "BYS360-K5Q-SUPPORT-MARKER"
KEY = "support_all"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "k5q_support_all_grant" / "dbs"

# key -> (role, birim, role_label, unvan)
USERS = {
    "creator": ("personel", "Birim-A", None, None),
    "holder": ("personel", "Birim-A", None, None),
    "holder_b": ("personel", "Birim-B", None, None),
    "colleague": ("personel", "Birim-A", None, None),
    "admin": ("admin", "Birim-C", None, None),
    "admin2": ("admin", "Birim-C", None, None),
    "baskan": ("baskan", "Birim-C", None, None),
    "baskan_yardimcisi": ("baskan_yardimcisi", "Birim-C", None, None),
    "grup_baskani": ("grup_baskani", "Birim-C", None, None),
    "mali_musavir": ("mali_musavir", "Birim-C", None, None),
    "koordinator": ("koordinator", "Birim-A", None, None),
    "birim_sorumlusu": ("birim_sorumlusu", "Birim-A", None, None),
    "sistem_yoneticisi": ("sistem_yoneticisi", "Birim-A", None, None),
    "label_support": ("personel", "Birim-A", "Destek Sorumlusu", "Sistem Yöneticisi"),
}
ROLE_DEFAULT_ROLES = ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator",
                      "birim_sorumlusu"]
NON_ADMIN_SETTINGS_ROLES = ["baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir"]


@pytest.fixture
def env(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-k5q-support-grant", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "k5q-support-grant-first-login",
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
        for index, (key, (role, birim, role_label, unvan)) in enumerate(USERS.items()):
            user = User(sicil_no=f"K5Q{index:02d}", email=f"k5q{index:02d}@example.gov.tr", ad="Destek",
                        soyad=key, role=role, birim=birim, role_label=role_label, unvan=unvan, is_active=True,
                        must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[key] = user
        db.session.flush()

        def _ticket(no, private):
            ticket = SupportTicket(ticket_no=no, title=f"Talep {no}", description=MARKER, ticket_type="other",
                                   module_name="test", status="open", created_by_user_id=users["creator"].id,
                                   is_private=private, unit_name_snapshot="Birim-A")
            db.session.add(ticket)
            db.session.flush()
            return ticket.id

        tickets = {"public": _ticket("K5Q-T1", False), "private": _ticket("K5Q-T2", True)}
        ids = {key: user.id for key, user in users.items()}
        sicils = {key: user.sicil_no for key, user in users.items()}
        db.session.commit()

    return SimpleNamespace(app=flask_app, ids=ids, sicils=sicils, tickets=tickets)


# --- helpers ----------------------------------------------------------------------------------


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


def _mobile_list(env, who):
    response = env.app.test_client().get("/api/mobile/support/tickets", headers=_bearer(env, who))
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _sees_all(env, who) -> bool:
    """True when the user gets the institution-wide view on mobile AND on the web all-tickets page."""
    mobile = "Talep K5Q-T1" in _mobile_list(env, who)
    web_page = _web(env, who).get("/support/all")
    web = web_page.status_code == 200 and b"Talep K5Q-T1" in web_page.data
    assert mobile == web, (who, mobile, web)
    return mobile


def _grant_row(env, who):
    from app.models import UserMenuPermission

    with env.app.app_context():
        row = UserMenuPermission.query.filter_by(user_id=env.ids[who], menu_key=KEY).first()
        return None if row is None else (bool(row.is_visible), row.source_type)


def _active(env, who) -> bool:
    return _grant_row(env, who) == (True, "user_override")


def _seed_row(env, who, *, is_visible=True, source_type="user_override"):
    from app.extensions import db
    from app.models import UserMenuPermission

    with env.app.app_context():
        row = UserMenuPermission.query.filter_by(user_id=env.ids[who], menu_key=KEY).first()
        if row is None:
            row = UserMenuPermission(user_id=env.ids[who], menu_key=KEY)
            db.session.add(row)
        row.is_visible = is_visible
        row.source_type = source_type
        db.session.commit()


def _change_logs(env, who):
    from app.models import SettingsChangeLog

    with env.app.app_context():
        rows = (SettingsChangeLog.query.filter_by(target_user_id=env.ids[who], change_scope="user_menu_overrides")
                .order_by(SettingsChangeLog.id.asc()).all())
        return [(row.actor_user_id, row.action_type, json.loads(row.new_state_json or "{}")) for row in rows]


def _settings(env, actor, data, client=None):
    return (client or _web(env, actor)).post("/settings", data=data)


def _grant(env, target, *, actor="admin", form_action="save_user_visibility", client=None):
    return _settings(env, actor, {"form_action": form_action, "user_id": str(env.ids[target]), f"menu_{KEY}": "on"},
                     client=client)


def _save_without(env, target, *, actor="admin", client=None):
    return _settings(env, actor, {"form_action": "save_user_visibility", "user_id": str(env.ids[target])},
                     client=client)


# --- K5-Q1: per person only, never a role default or a unit profile --------------------------


@pytest.mark.parametrize("who", ROLE_DEFAULT_ROLES)
def test_k5q1_former_role_default_roles_see_only_their_own_tickets(env, who):
    assert _sees_all(env, who) is False


@pytest.mark.parametrize("who", ["sistem_yoneticisi", "label_support", "colleague"])
def test_k5q1_technical_role_label_and_title_grant_nothing(env, who):
    assert _sees_all(env, who) is False


def test_k5q1_a_role_matrix_or_unit_profile_row_grants_nothing(env):
    from app.extensions import db
    from app.models import RoleMenuDefault, UnitMenuProfile

    with env.app.app_context():
        db.session.add(RoleMenuDefault(role_name="personel", menu_key=KEY, is_visible=True, source_type="manual"))
        db.session.add(UnitMenuProfile(unit_name="Birim-A", menu_key=KEY, is_visible=True))
        db.session.commit()
    assert _sees_all(env, "colleague") is False


def test_k5q1_seeded_role_defaults_never_store_the_grant(env):
    # Opening /settings seeds the role matrix from the static role menus, which still list support_all
    # for seven roles (and personel). The seed must store the explicit grants as not visible.
    from app.models import RoleMenuDefault

    assert _web(env, "admin").get("/settings").status_code == 200
    with env.app.app_context():
        assert RoleMenuDefault.query.filter_by(menu_key=KEY).count() > 0, "the seed must have run"
        assert RoleMenuDefault.query.filter_by(menu_key=KEY, is_visible=True).count() == 0
        assert RoleMenuDefault.query.filter_by(menu_key="personnel_read_all", is_visible=True).count() == 0


@pytest.mark.parametrize("source_type", ["seed", "rollback", "bulk_profile", "import"])
def test_k5q1_only_a_user_override_row_counts(env, source_type):
    _seed_row(env, "colleague", source_type=source_type)
    assert _sees_all(env, "colleague") is False


def test_k5q1_the_explicit_grant_opens_web_mobile_and_the_menu(env):
    _seed_row(env, "holder")
    assert _sees_all(env, "holder") is True
    from app.extensions import db
    from app.models import User
    from app.route_support import build_menu_visibility_map

    with env.app.app_context(), env.app.test_request_context():
        holder = db.session.get(User, env.ids["holder"])
        baskan = db.session.get(User, env.ids["baskan"])
        assert build_menu_visibility_map(holder).get(KEY) is True
        assert build_menu_visibility_map(baskan).get(KEY) is False


def test_k5q1_an_inactive_holder_has_no_grant(env):
    _seed_row(env, "holder")
    from app.extensions import db
    from app.models import User
    from app.services.personnel_read_grant import has_support_all_grant

    with env.app.app_context():
        user = db.session.get(User, env.ids["holder"])
        assert user is not None
        user.is_active = False
        db.session.commit()
        assert has_support_all_grant(db.session.get(User, env.ids["holder"])) is False


# --- K5-Q2: only the admin, only for another user, audited ------------------------------------


def test_k5q2_admin_grants_another_user_with_an_audit_row(env):
    assert _grant(env, "holder").status_code == 302
    assert _active(env, "holder")
    logs = [log for log in _change_logs(env, "holder") if log[2].get(KEY) is True]
    assert logs and logs[-1][0] == env.ids["admin"]
    assert _sees_all(env, "holder") is True


@pytest.mark.parametrize("form_action", ["save_user_visibility", "save_personnel_feature_matrix_full",
                                         "contract_unknown_action"])
def test_k5q2_admin_self_grant_is_refused(env, form_action):
    _grant(env, "admin", actor="admin", form_action=form_action)
    assert not _active(env, "admin")
    assert _sees_all(env, "admin") is False


@pytest.mark.parametrize("actor", NON_ADMIN_SETTINGS_ROLES)
def test_k5q2_non_admin_admin_family_cannot_grant_others_or_themselves(env, actor):
    before = len(_change_logs(env, "holder"))
    _grant(env, "holder", actor=actor)
    assert len(_change_logs(env, "holder")) == before + 1, "the save itself must have run"
    assert not _active(env, "holder")
    _grant(env, actor, actor=actor)
    assert not _active(env, actor)
    assert _sees_all(env, actor) is False


def test_k5q2_two_non_admins_cannot_cross_grant(env):
    _grant(env, "mali_musavir", actor="grup_baskani")
    _grant(env, "grup_baskani", actor="mali_musavir")
    assert not _active(env, "mali_musavir") and not _active(env, "grup_baskani")


def test_k5q2_non_admin_save_and_reset_keep_an_existing_grant(env):
    _grant(env, "holder")
    _save_without(env, "holder", actor="mali_musavir")
    assert _active(env, "holder"), "only an admin may revoke"
    _settings(env, "baskan", {"form_action": "reset_user_overrides", "user_id": str(env.ids["holder"])})
    assert _active(env, "holder")


def test_k5q2_admin_revokes_and_a_rollback_never_restores(env):
    client = _web(env, "admin")
    _grant(env, "holder", client=client)
    _save_without(env, "holder", client=client)
    assert not _active(env, "holder")
    assert _sees_all(env, "holder") is False
    from app.models import SettingsChangeLog

    with env.app.app_context():
        revoke_log = (SettingsChangeLog.query.filter_by(target_user_id=env.ids["holder"],
                                                        change_scope="user_menu_overrides")
                      .order_by(SettingsChangeLog.id.desc()).first())
        assert revoke_log is not None
        revoke_id = revoke_log.id
    _settings(env, "admin", {"form_action": "rollback_settings_change_entry", "change_log_id": str(revoke_id),
                             "keep_user_id": str(env.ids["holder"])}, client=client)
    assert any(log[1] == "rollback" for log in _change_logs(env, "holder")), "rollback must have run"
    assert not _active(env, "holder")
    assert _sees_all(env, "holder") is False


def test_k5q2_admin_reset_of_another_user_removes_the_grant(env):
    client = _web(env, "admin")
    _grant(env, "holder", client=client)
    _settings(env, "admin", {"form_action": "reset_user_overrides", "user_id": str(env.ids["holder"])}, client=client)
    assert not _active(env, "holder")


def test_k5q2_bulk_apply_creates_and_removes_no_grant(env):
    from app.extensions import db
    from app.models import RoleMenuDefault

    with env.app.app_context():
        db.session.add(RoleMenuDefault(role_name="personel", menu_key=KEY, is_visible=True, source_type="manual"))
        db.session.commit()
    _seed_row(env, "holder")
    response = _settings(env, "admin", {"form_action": "bulk_apply_profile", "bulk_profile_key": "dynamic::role_defaults",
                                        "bulk_scope_type": "role", "bulk_role": "personel"})
    assert response.status_code == 302 and "last_bulk_count" in response.headers.get("Location", "")
    assert _active(env, "holder")
    assert not _active(env, "colleague")
    assert _sees_all(env, "colleague") is False


@pytest.mark.parametrize("form_action,target_field,target_value", [
    ("save_role_profile", "profile_role_target", "personel"),
    ("save_unit_profile", "profile_unit_target", "Birim-A"),
])
def test_k5q2_role_and_unit_profile_saves_never_grant(env, form_action, target_field, target_value):
    from app.models import RoleMenuDefault, UnitMenuProfile

    response = _settings(env, "admin", {"form_action": form_action, "user_id": str(env.ids["colleague"]),
                                        target_field: target_value, f"menu_{KEY}": "on"})
    assert response.status_code == 302
    with env.app.app_context():
        assert RoleMenuDefault.query.filter_by(role_name="personel", menu_key=KEY, is_visible=True).count() == 0
        assert UnitMenuProfile.query.filter_by(unit_name="Birim-A", menu_key=KEY, is_visible=True).count() == 0
    assert not _active(env, "colleague")
    assert _sees_all(env, "colleague") is False


def test_k5q2_template_import_never_grants(env):
    template = json.dumps({"visible_keys": [KEY], "effective_rule_map": {KEY: True}})
    response = _settings(env, "admin", {"form_action": "import_visibility_template", "user_id": str(env.ids["holder"]),
                                        "import_template_json": template})
    assert response.status_code == 302
    assert _change_logs(env, "holder"), "the import must have saved the matrix"
    assert not _active(env, "holder")


def test_k5q2_named_archive_apply_never_grants(env):
    client = _web(env, "admin")
    _settings(env, "admin", {"form_action": "save_named_archive", "user_id": str(env.ids["holder"]),
                             "archive_name": "k5q-arsiv", "archive_scope": "general", f"menu_{KEY}": "on"},
              client=client)
    _settings(env, "admin", {"form_action": "apply_named_archive", "user_id": str(env.ids["holder"]),
                             "archive_key": "settings_archive::general::k5q-arsiv",
                             "archive_apply_mode": "user_override"}, client=client)
    assert _change_logs(env, "holder"), "the archive must have been applied"
    assert not _active(env, "holder")


@pytest.mark.parametrize("who", ["sistem_yoneticisi", "koordinator", "colleague"])
def test_k5q2_users_outside_the_admin_family_cannot_post_settings(env, who):
    assert _grant(env, "holder", actor=who).status_code == 403
    assert _grant_row(env, "holder") is None


# --- K5-Q3: Faz 3 and the notifications use the same central rule ------------------------------


def test_k5q3_faz3_queue_and_detail_follow_the_grant_without_a_manager_role(env):
    _seed_row(env, "holder")
    holder = _web(env, "holder")
    assert b"Talep K5Q-T1" in holder.get("/communication/faz3/support/queue").data
    detail = holder.get(f"/communication/faz3/support/{env.tickets['public']}")
    assert detail.status_code == 200 and MARKER.encode() in detail.data
    holder.post(f"/communication/faz3/support/{env.tickets['public']}/status", data={"status": "reviewing"})
    from app.extensions import db
    from app.models import SupportTicket

    with env.app.app_context():
        ticket = db.session.get(SupportTicket, env.tickets["public"])
        assert ticket is not None and ticket.status == "reviewing"


@pytest.mark.parametrize("who", ["baskan", "birim_sorumlusu", "sistem_yoneticisi"])
def test_k5q3_faz3_refuses_role_only_users(env, who):
    client = _web(env, who)
    assert b"Talep K5Q-T1" not in client.get("/communication/faz3/support/queue").data
    assert MARKER.encode() not in client.get(f"/communication/faz3/support/{env.tickets['public']}").data


def _notified(env, ticket_key):
    from app.extensions import db
    from app.models import Notification, SupportTicket, User
    from app.services.bys360_notification_bridge import notify_support_ticket_created

    with env.app.app_context(), env.app.test_request_context():
        ticket = db.session.get(SupportTicket, env.tickets[ticket_key])
        actor = db.session.get(User, env.ids["creator"])
        notify_support_ticket_created(ticket, actor)
        db.session.commit()
        rows = Notification.query.filter_by(notification_type="support_ticket_created").all()
        by_id = {value: key for key, value in env.ids.items()}
        return {by_id[row.user_id] for row in rows}


def test_k5q3_new_ticket_notifications_reach_only_grant_holders(env):
    _seed_row(env, "holder")
    _seed_row(env, "holder_b")
    recipients = _notified(env, "public")
    assert recipients == {"holder", "holder_b"}


def test_k5q3_private_ticket_notifications_keep_the_unit_rule(env):
    _seed_row(env, "holder")
    _seed_row(env, "holder_b")
    assert _notified(env, "private") == {"holder"}
