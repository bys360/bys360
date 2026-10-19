"""R05c contract: /settings, file-center and account-state writes cannot escalate, bypass the
protected-account rules or lose the last administrator.

Owner decisions (HUMAN_POLICY_APPROVED, 2026-10-13):

K1 Holders of ``personnel_read_all`` are protected accounts too; protection follows the stored
   role and the explicit grants (``personnel_read_all`` / ``support_all``), never a title.
K2 A non-admin never changes a unit profile (unit rows override the role defaults of every
   member, admins included). Server side, not by hiding a button.
K3 A non-admin never changes its own menu/access matrix (no widening, no narrowing).
K4 Even a real admin cannot remove ``admin_users`` / ``settings`` from the admin role profile;
   no role default or unit profile locks an active admin out of them, and an admin cannot revoke
   them on its own account. (An explicit per-user revocation for ANOTHER admin account stays
   authoritative, as the admin routes contract requires.) The last active
   admin is never demoted, deactivated or deleted; an admin never demotes or deactivates itself.
K5 The file-center role matrix is in R05 scope: no escalation and no change to protected roles
   through it.
K6 P2c (title-based chair recognition) stays as it is in this PR; a migration plan only.

Findings closed here (each test fails on the PR head before the R05c fix, a8649c94):

R05-1 non-admin changes protected role defaults (role profile, role-matrix groups, communication
      and assistant matrices, module foundation, named archives).
R05-2 non-admin changes the per-user matrix of a protected account (K1) or its own (K3), also
      through template import and named archives.
R05-3 a role-matrix group save reaches the admin column.
F3    a bulk profile changes protected accounts, even when a real admin runs it.
R05-5 an admin demotes or deactivates itself; an Excel file demotes admins; an admin account
      stored as "Admin " can be deleted (the delete guard compared the exact spelling).
N1    rollback replays a protected change for a non-admin.
N2    = K3.
N3    = K2.
N4    the v10 assistant matrix endpoint writes the admin column for a non-admin, with no audit row.
C     two admins demoting each other at the same time leave no active admin (PostgreSQL test at
      the end, run against an ephemeral local database when ``BYS360_R05C_PG_URL`` is set).
S     the protected-grant check has one source (``account_change_guard.holds_protected_grant``).

Tests named ``test_guard_*`` are positive guards that also pass before the fix.
Every negative test asserts that the protected rows are byte-for-byte unchanged and that the
refusal is written to ``audit_logs``.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import (
    SICIL,
    _admin_edit_form,
    _personnel_edit_form,
    _upload,
    _web,
    _xlsx_row,
)

env = _r05.env  # seeded accounts (admin, admin2, leadership, technical, grant holders, plain), temp SQLite

UNIT = "R05 Birim"
OTHER_UNIT = "R05C Diger Birim"
PROTECTED_ROLES = ("admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu")
MATRIX_GROUPS = ("general", "portal", "personnel", "performance", "communication", "ai", "assistant", "settings_security")
LOCKOUT_KEYS = ("admin_users", "settings")
ADMIN_USERS_GATED_PATH = "/personnel"  # menu_key_required("admin_users")
NON_ADMIN = "baskan"


# --------------------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------------------


def _role_profile(env, role):
    from app.models import RoleMenuDefault

    with env.app.app_context():
        return sorted(
            (row.menu_key, bool(row.is_visible), row.source_type or "")
            for row in RoleMenuDefault.query.filter_by(role_name=role).all()
        )


def _visible_role_keys(env, role):
    return {key for key, visible, _source in _role_profile(env, role) if visible}


def _role_profiles(env, roles=PROTECTED_ROLES):
    return {role: _role_profile(env, role) for role in roles}


def _unit_profile(env, unit):
    from app.models import UnitMenuProfile

    with env.app.app_context():
        return sorted(
            (row.menu_key, bool(row.is_visible), row.source_type or "")
            for row in UnitMenuProfile.query.filter_by(unit_name=unit).all()
        )


def _overrides(env, key):
    from app.models import UserMenuPermission

    with env.app.app_context():
        return sorted(
            (row.menu_key, bool(row.is_visible), row.source_type or "")
            for row in UserMenuPermission.query.filter_by(user_id=env.ids[key]).all()
        )


def _module_setting(env, module_key, setting_key):
    from app.models import ModuleSetting

    with env.app.app_context():
        row = ModuleSetting.query.filter_by(module_key=module_key, setting_key=setting_key).first()
        return None if row is None else (row.value_text, bool(row.is_active))


def _v10_matrix(env):
    from app.services.assistant_role_matrix_v10 import get_assistant_role_matrix_v10

    with env.app.app_context():
        return get_assistant_role_matrix_v10()["matrix"]


def _account(env, key):
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[key])
        assert user is not None, key
        return (user.role, bool(user.is_active), bool(getattr(user, "is_archived", False)))


def _refusals(env, reason):
    from app.models import AuditLog

    with env.app.app_context():
        return [
            row
            for row in AuditLog.query.filter_by(action="account.change_refused").all()
            if reason in (row.summary or "")
        ]


def _audit(env, action):
    from app.models import AuditLog

    with env.app.app_context():
        return AuditLog.query.filter_by(action=action).all()


def _change_logs(env, **filters):
    from app.models import SettingsChangeLog

    with env.app.app_context():
        return [row.id for row in SettingsChangeLog.query.filter_by(**filters).order_by(SettingsChangeLog.id).all()]


def _settings(client, data):
    return client.post("/settings", data=data)


def _sync_role_defaults(env):
    """K13 (19 Oct 2026): rendering /settings no longer seeds the role defaults; the real admin's explicit sync does."""
    assert _web(env, "admin").post("/settings", data={"form_action": "sync_role_defaults"}).status_code == 302


def _seeded_client(env, who):
    _sync_role_defaults(env)
    client = _web(env, who)
    client.get("/settings")  # rendering the page writes nothing (K13)
    return client


def _save_archive(env, *keys, name="r05c-arsiv"):
    client = _web(env, "admin")
    form = {"form_action": "save_named_archive", "user_id": env.ids["plain"], "archive_name": name, "archive_scope": "general"}
    form.update({f"menu_{key}": "on" for key in keys})
    _settings(client, form)
    return f"settings_archive::general::{name}"


# --------------------------------------------------------------------------------------
# R05-1 / R05-3: role defaults (every role other than the baseline is protected)
# --------------------------------------------------------------------------------------


def test_r05_1_r05_3_non_admin_role_matrix_groups_keep_every_protected_column(env):
    client = _seeded_client(env, NON_ADMIN)
    before = _role_profiles(env)
    assert before["admin"], "seeded admin role profile"
    for group in MATRIX_GROUPS:
        _settings(client, {"form_action": f"save_role_matrix_group__{group}"})  # every box unchecked
    _settings(client, {"form_action": "save_communication_role_matrix"})
    assert _role_profiles(env) == before
    # a non-admin is refused as such; the K4 lockout reason is for a real admin's own saves
    refused = len(_refusals(env, "settings_role_profile")) + len(_refusals(env, "admin_role_lockout_keys"))
    assert refused == len(MATRIX_GROUPS) + 1


def test_r05_1_non_admin_resets_cannot_rewrite_protected_columns(env):
    admin = _seeded_client(env, "admin")
    _settings(admin, {"form_action": "save_communication_role_matrix"})  # the real admin may clear them
    for group in ("communication", "portal"):
        _settings(admin, {"form_action": f"save_role_matrix_group__{group}"})
    client = _seeded_client(env, NON_ADMIN)  # the per-request seed re-adds hidden rows the saves pruned
    before = _role_profiles(env)
    _settings(client, {"form_action": "reset_communication_role_matrix"})
    for group in ("communication", "portal"):
        _settings(client, {"form_action": f"reset_role_matrix_group__{group}"})
    assert _role_profiles(env) == before
    assert len(_refusals(env, "settings_role_profile")) >= 3


@pytest.mark.parametrize("role", ["koordinator", "sistem_yoneticisi", "baskan_yardimcisi", "baskan", "birim_sorumlusu", "kullanici", "r05c_unknown"])
def test_r05_1_non_admin_cannot_save_a_protected_role_profile(env, role):
    client = _seeded_client(env, NON_ADMIN)
    before = _role_profile(env, role)
    _settings(
        client,
        {"form_action": "save_role_profile", "user_id": env.ids["plain"], "profile_role_target": role, "menu_dashboard": "on"},
    )
    assert _role_profile(env, role) == before
    assert _refusals(env, "settings_role_profile")


def test_r05_1_non_admin_archive_cannot_rewrite_a_protected_role_profile(env):
    _seeded_client(env, "admin")
    archive_key = _save_archive(env, "dashboard")
    before = _role_profiles(env)
    client = _web(env, NON_ADMIN)
    for role in ("admin", "koordinator", "baskan"):
        _settings(
            client,
            {"form_action": "apply_named_archive", "user_id": env.ids["plain"], "archive_key": archive_key,
             "archive_apply_mode": "role_profile", "archive_apply_role": role},
        )
    assert _role_profiles(env) == before
    assert len(_refusals(env, "settings_role_profile")) >= 2


def test_guard_non_admin_still_manages_the_baseline_role_profile(env):
    client = _seeded_client(env, NON_ADMIN)
    _settings(
        client,
        {"form_action": "save_role_profile", "user_id": env.ids["plain"], "profile_role_target": "personel", "menu_dashboard": "on"},
    )
    assert _visible_role_keys(env, "personel") == {"dashboard"}


def test_r05_1_non_admin_assistant_role_visibility_keeps_protected_roles(env):
    admin = _seeded_client(env, "admin")
    _settings(admin, {"form_action": "save_assistant_role_matrix", "assistant_role_policy__personel__assistant_module": "on"})
    after_admin = _module_setting(env, "assistant", "visible_roles")
    assert after_admin[0] == "personel"
    client = _web(env, NON_ADMIN)
    _settings(client, {"form_action": "reset_assistant_role_matrix"})
    _settings(client, {"form_action": "save_assistant_role_matrix", "assistant_role_policy__baskan__assistant_module": "on"})
    _settings(client, {"form_action": "save_module_foundation", "module__assistant__visible_roles": "admin,baskan,koordinator"})
    _settings(client, {"form_action": "save_module_foundation", "module__identity_access__allow_user_override": "on"})
    assert _module_setting(env, "assistant", "visible_roles") == after_admin
    assert len(_refusals(env, "settings_assistant_roles")) >= 3


def test_guard_non_admin_still_saves_module_foundation_without_authority_settings(env):
    client = _seeded_client(env, NON_ADMIN)
    current_identity = {
        key: _module_setting(env, "identity_access", key) for key in ("use_role_based_visibility", "allow_user_override")
    }
    form = {"form_action": "save_module_foundation", "module__assistant__enabled": "on"}
    # R05d protects these activation flags too. An unchanged real form posts their current
    # checked values; omitting them would ask the full-form writer to disable the assistant.
    for key in ("enabled", "widget_enabled", "panel_enabled"):
        value = _module_setting(env, "ai_agent", key)
        if value is None or value[0] == "true":
            form[f"module__ai_agent__{key}"] = "on"
    for key, value in current_identity.items():
        if value is None or value[0] == "true":
            form[f"module__identity_access__{key}"] = "on"
    visible = _module_setting(env, "assistant", "visible_roles")
    from app.services.assistant_role_matrix_service import ASSISTANT_DEFAULT_VISIBLE_ROLES

    form["module__assistant__visible_roles"] = visible[0] if visible else ",".join(sorted(ASSISTANT_DEFAULT_VISIBLE_ROLES))
    before = len(_change_logs(env, change_scope="module_settings"))
    _settings(client, form)
    assert len(_change_logs(env, change_scope="module_settings")) == before + 1


def test_n4_non_admin_v10_assistant_matrix_keeps_protected_columns_and_admin_save_is_audited(env):
    _seeded_client(env, "admin")
    before = _v10_matrix(env)
    client = _web(env, NON_ADMIN)
    client.post("/settings/assistant-role-matrix-v10/save", data={})  # every cell unchecked
    after = _v10_matrix(env)
    for feature, roles in before.items():
        for role in PROTECTED_ROLES:
            assert after[feature][role] == roles[role], (feature, role)
    assert _refusals(env, "assistant_role_matrix_v10")
    admin = _web(env, "admin")
    admin.post("/settings/assistant-role-matrix-v10/save", data={"assistant_matrix__assistant_module__personel": "on"})
    assert _v10_matrix(env)["assistant_module"]["personel"] is True
    assert _audit(env, "settings.assistant_role_matrix_v10_save")


# --------------------------------------------------------------------------------------
# R05-2 / K1 / K3: per-user matrices of protected accounts and of the editor itself
# --------------------------------------------------------------------------------------


USER_MATRIX_TARGETS = ("admin", "admin2", "koordinator", "sysadm", "pra_holder", "sup_holder", "baskan_yardimcisi", NON_ADMIN)


def test_r05_2_k1_k3_non_admin_cannot_change_protected_or_own_per_user_matrix(env):
    archive_key = _save_archive(env, "dashboard", "personnel_read_all", "support_all", "settings")
    before = {key: _overrides(env, key) for key in USER_MATRIX_TARGETS}
    template = json.dumps({"visible_keys": ["dashboard", "settings"], "effective_rule_map": {"dashboard": True}})
    client = _web(env, NON_ADMIN)
    for key in USER_MATRIX_TARGETS:
        uid = env.ids[key]
        _settings(client, {"form_action": "save_user_visibility", "user_id": uid, "menu_dashboard": "on", "menu_settings": "on"})
        _settings(client, {"form_action": "save_personnel_feature_matrix_full", "user_id": uid})
        _settings(client, {"form_action": "reset_user_overrides", "user_id": uid})
        _settings(client, {"form_action": "import_visibility_template", "user_id": uid, "import_template_json": template})
        _settings(
            client,
            {"form_action": "apply_named_archive", "user_id": uid, "archive_key": archive_key, "archive_apply_mode": "user_override"},
        )
    for key in USER_MATRIX_TARGETS:
        assert _overrides(env, key) == before[key], key
    assert len(_refusals(env, "settings_own_matrix")) >= 5
    assert len(_refusals(env, "settings_user_matrix")) >= 5 * (len(USER_MATRIX_TARGETS) - 1)


def test_s_a_grant_row_of_any_source_protects_the_account(env):
    from app.extensions import db
    from app.models import UserMenuPermission

    with env.app.app_context():
        db.session.add(UserMenuPermission(user_id=env.ids["plain2"], menu_key="personnel_read_all", is_visible=True, source_type="manual"))
        db.session.commit()
    before = _overrides(env, "plain2")
    _settings(_web(env, NON_ADMIN), {"form_action": "save_user_visibility", "user_id": env.ids["plain2"], "menu_dashboard": "on"})
    assert _overrides(env, "plain2") == before
    assert _refusals(env, "settings_user_matrix")


def test_guard_non_admin_still_manages_an_ordinary_account_and_the_admin_manages_protected_ones(env):
    _settings(_web(env, NON_ADMIN), {"form_action": "save_user_visibility", "user_id": env.ids["plain"], "menu_dashboard": "on"})
    assert ("dashboard", True, "user_override") in _overrides(env, "plain")
    _settings(_web(env, "admin"), {"form_action": "save_user_visibility", "user_id": env.ids["koordinator"], "menu_dashboard": "on"})
    assert ("dashboard", True, "user_override") in _overrides(env, "koordinator")


# --------------------------------------------------------------------------------------
# N3 / K2: unit profiles
# --------------------------------------------------------------------------------------


def test_n3_k2_non_admin_cannot_change_any_unit_profile(env):
    _seeded_client(env, "admin")
    archive_key = _save_archive(env, "dashboard")
    before = {unit: _unit_profile(env, unit) for unit in (UNIT, OTHER_UNIT)}
    client = _web(env, NON_ADMIN)
    for unit in (UNIT, OTHER_UNIT):
        _settings(
            client,
            {"form_action": "save_unit_profile", "user_id": env.ids["plain"], "profile_unit_target": unit, "menu_dashboard": "on"},
        )
        _settings(
            client,
            {"form_action": "apply_named_archive", "user_id": env.ids["plain"], "archive_key": archive_key,
             "archive_apply_mode": "unit_profile", "archive_apply_birim": unit},
        )
    assert {unit: _unit_profile(env, unit) for unit in (UNIT, OTHER_UNIT)} == before
    assert len(_refusals(env, "settings_unit_profile")) >= 4


def test_guard_real_admin_still_saves_a_unit_profile(env):
    _settings(
        _seeded_client(env, "admin"),
        {"form_action": "save_unit_profile", "user_id": env.ids["plain"], "profile_unit_target": OTHER_UNIT, "menu_dashboard": "on"},
    )
    assert ("dashboard", True, "manual") in _unit_profile(env, OTHER_UNIT)


# --------------------------------------------------------------------------------------
# K4: lockout keys
# --------------------------------------------------------------------------------------


def test_k4_real_admin_cannot_remove_the_lockout_keys_from_the_admin_role(env):
    admin = _seeded_client(env, "admin")
    assert set(LOCKOUT_KEYS) <= _visible_role_keys(env, "admin"), "seeded admin profile"
    archive_key = _save_archive(env, "dashboard")
    _settings(admin, {"form_action": "save_role_profile", "user_id": env.ids["plain"], "profile_role_target": "admin", "menu_dashboard": "on"})
    _settings(
        admin,
        {"form_action": "apply_named_archive", "user_id": env.ids["plain"], "archive_key": archive_key,
         "archive_apply_mode": "role_profile", "archive_apply_role": "admin"},
    )
    for group in MATRIX_GROUPS:
        _settings(admin, {"form_action": f"save_role_matrix_group__{group}"})
    assert set(LOCKOUT_KEYS) <= _visible_role_keys(env, "admin")
    assert len(_refusals(env, "admin_role_lockout_keys")) >= 3


def test_k4_a_unit_profile_never_locks_an_admin_out_and_an_admin_cannot_lock_itself_out(env):
    admin = _seeded_client(env, "admin")
    _settings(admin, {"form_action": "save_unit_profile", "user_id": env.ids["plain"], "profile_unit_target": UNIT, "menu_dashboard": "on"})
    assert ("admin_users", False, "manual") in _unit_profile(env, UNIT)
    for who in ("admin", "admin2"):
        client = _web(env, who)
        assert client.get(ADMIN_USERS_GATED_PATH).status_code == 200, who
        assert client.get("/communication/faz9a/preflight").status_code == 200, who
    # the floor is for active real admins only: the unit row still hides admin_users from others
    assert _web(env, "plain").get(ADMIN_USERS_GATED_PATH).status_code in (302, 403)
    # an admin's own matrix, template or archive can never revoke the lockout keys
    before = _overrides(env, "admin")
    archive_key = _save_archive(env, "dashboard")
    template = json.dumps({"visible_keys": ["dashboard"], "effective_rule_map": {"dashboard": True}})
    _settings(admin, {"form_action": "save_user_visibility", "user_id": env.ids["admin"], "menu_dashboard": "on"})
    _settings(admin, {"form_action": "import_visibility_template", "user_id": env.ids["admin"], "import_template_json": template})
    _settings(admin, {"form_action": "apply_named_archive", "user_id": env.ids["admin"], "archive_key": archive_key, "archive_apply_mode": "user_override"})
    assert _overrides(env, "admin") == before
    assert len(_refusals(env, "admin_self_lockout_keys")) == 3
    assert _web(env, "admin").get(ADMIN_USERS_GATED_PATH).status_code == 200


def test_guard_an_explicit_per_user_revocation_for_another_admin_stays_authoritative(env):
    """Admin routes contract: role "admin" alone is not enough once admin_users is revoked for
    that one account (single-account admin action, audited in settings_change_logs)."""
    _settings(_seeded_client(env, "admin"), {"form_action": "save_user_visibility", "user_id": env.ids["admin2"], "menu_dashboard": "on"})
    assert ("admin_users", False, "user_override") in _overrides(env, "admin2")
    assert _web(env, "admin2").get(ADMIN_USERS_GATED_PATH).status_code == 403


def test_k4_rollback_cannot_restore_an_admin_profile_without_the_lockout_keys(env):
    from app.extensions import db
    from app.models import SettingsChangeLog

    _seeded_client(env, "admin")
    with env.app.app_context():
        row = SettingsChangeLog(
            actor_user_id=env.ids["admin"],
            change_scope="role_menu_defaults",
            action_type="save",
            summary="r05c crafted",
            previous_state_json=json.dumps({"dashboard": True, "admin_users": False, "settings": False}),
            new_state_json=json.dumps({"dashboard": True, "admin_users": True, "settings": True}),
            target_role_name="admin",
        )
        db.session.add(row)
        db.session.commit()
        log_id = row.id
    _settings(_web(env, "admin"), {"form_action": "rollback_settings_change_entry", "change_log_id": log_id})
    assert set(LOCKOUT_KEYS) <= _visible_role_keys(env, "admin")
    assert _refusals(env, "admin_role_lockout_keys")


# --------------------------------------------------------------------------------------
# N1: rollback
# --------------------------------------------------------------------------------------


def test_n1_non_admin_rollback_cannot_replay_a_protected_change(env):
    admin = _seeded_client(env, "admin")
    _settings(admin, {"form_action": "save_role_profile", "user_id": env.ids["plain"], "profile_role_target": "koordinator", "menu_dashboard": "on"})
    _settings(admin, {"form_action": "save_unit_profile", "user_id": env.ids["plain"], "profile_unit_target": OTHER_UNIT, "menu_dashboard": "on"})
    for key in ("pra_holder", "admin2", NON_ADMIN):
        # the admin keeps pra_holder's grant, so pra_holder stays a protected account (K1)
        _settings(
            admin,
            {"form_action": "save_user_visibility", "user_id": env.ids[key], "menu_dashboard": "on", "menu_personnel_read_all": "on"},
        )
    assert ("personnel_read_all", True, "user_override") in _overrides(env, "pra_holder")
    _settings(admin, {"form_action": "save_module_foundation", "module__assistant__visible_roles": "personel"})
    logs = (
        _change_logs(env, change_scope="role_menu_defaults", target_role_name="koordinator")
        + _change_logs(env, change_scope="unit_menu_profiles", target_unit_name=OTHER_UNIT)
        + _change_logs(env, change_scope="user_menu_overrides", target_user_id=env.ids["pra_holder"])
        + _change_logs(env, change_scope="user_menu_overrides", target_user_id=env.ids["admin2"])
        + _change_logs(env, change_scope="user_menu_overrides", target_user_id=env.ids[NON_ADMIN])
        + _change_logs(env, change_scope="module_settings")
    )
    assert len(logs) >= 6
    before = (
        _role_profile(env, "koordinator"),
        _unit_profile(env, OTHER_UNIT),
        {key: _overrides(env, key) for key in ("pra_holder", "admin2", NON_ADMIN)},
        _module_setting(env, "assistant", "visible_roles"),
    )
    client = _web(env, NON_ADMIN)
    for log_id in logs:
        _settings(client, {"form_action": "rollback_settings_change_entry", "change_log_id": log_id})
    after = (
        _role_profile(env, "koordinator"),
        _unit_profile(env, OTHER_UNIT),
        {key: _overrides(env, key) for key in ("pra_holder", "admin2", NON_ADMIN)},
        _module_setting(env, "assistant", "visible_roles"),
    )
    assert after == before
    assert len(_refusals(env, "settings_rollback")) >= len(logs)
    assert _change_logs(env, is_rollback=True) == []


def test_guard_non_admin_still_rolls_back_baseline_and_ordinary_changes(env):
    client = _seeded_client(env, NON_ADMIN)
    _settings(client, {"form_action": "save_role_profile", "user_id": env.ids["plain"], "profile_role_target": "personel", "menu_dashboard": "on"})
    _settings(client, {"form_action": "save_user_visibility", "user_id": env.ids["plain"], "menu_dashboard": "on"})
    for log_id in (
        _change_logs(env, change_scope="role_menu_defaults", target_role_name="personel")[-1],
        _change_logs(env, change_scope="user_menu_overrides", target_user_id=env.ids["plain"])[-1],
    ):
        _settings(client, {"form_action": "rollback_settings_change_entry", "change_log_id": log_id})
    assert len(_change_logs(env, is_rollback=True)) == 2


# --------------------------------------------------------------------------------------
# F3: bulk profiles never touch protected accounts, whoever runs them
# --------------------------------------------------------------------------------------


BULK_PROTECTED = ("koordinator", "sysadm", "pra_holder", "sup_holder", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir")


@pytest.mark.parametrize("actor", ["admin", NON_ADMIN])
def test_f3_bulk_profile_skips_protected_accounts_and_is_audited(env, actor):
    client = _seeded_client(env, actor)
    before = {key: _overrides(env, key) for key in BULK_PROTECTED}
    response = _settings(
        client,
        {"form_action": "bulk_apply_profile", "bulk_profile_key": "dynamic::role_defaults", "bulk_scope_type": "birim", "bulk_birim": UNIT},
    )
    assert response.status_code == 302
    for key in BULK_PROTECTED:
        assert _overrides(env, key) == before[key], key
    assert _overrides(env, "plain"), "the ordinary accounts in scope are still updated"
    rows = _audit(env, "settings.bulk_profile_apply")
    assert rows, "the bulk change is audited"
    detail = json.loads(rows[-1].new_data_json)
    assert detail["skipped_protected"] >= len(BULK_PROTECTED)
    assert detail["applied"] >= 2


# --------------------------------------------------------------------------------------
# R05-5 / K4: the admin's own account, Excel and the last active admin
# --------------------------------------------------------------------------------------


def test_r05_5_admin_cannot_demote_or_deactivate_itself(env):
    client = _web(env, "admin")
    client.post(f"/admin/users/{env.ids['admin']}/edit", data=_admin_edit_form(env, "admin", role="personel"))
    client.post(f"/personnel/{env.ids['admin']}/edit", data=_personnel_edit_form(env, "admin", role="koordinator"))
    client.post(f"/admin/users/{env.ids['admin']}/edit", data=_admin_edit_form(env, "admin", is_active=None))
    client.post(f"/personnel/{env.ids['admin']}/edit", data=_personnel_edit_form(env, "admin", is_active=None))
    client.post(f"/personnel/{env.ids['admin']}/toggle-active")
    assert _account(env, "admin") == ("admin", True, False)
    assert len(_refusals(env, "admin_self_demotion")) >= 5


def test_r05_5_excel_upload_never_demotes_an_admin(env):
    client = _web(env, "admin")
    _upload(
        client,
        "/personnel/excel-upload",
        [_xlsx_row(SICIL["admin2"], "personel"), _xlsx_row(SICIL["admin"], "personel")],
        update_existing="on",
    )
    assert _account(env, "admin") == ("admin", True, False)
    assert _account(env, "admin2") == ("admin", True, False)
    assert _refusals(env, "excel_admin_role_change")


def test_k4_an_admin_account_of_any_spelling_is_never_deleted(env):
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        admin2 = db.session.get(User, env.ids["admin2"])
        assert admin2 is not None
        admin2.role = "Admin "
        db.session.commit()
    client = _web(env, "admin")
    client.post(f"/admin/users/{env.ids['admin2']}/delete")
    client.post(f"/personnel/{env.ids['admin2']}/delete")
    client.post("/admin/users/bulk-delete", data={"user_ids": [str(env.ids["admin2"])]})
    with env.app.app_context():
        assert db.session.get(User, env.ids["admin2"]) is not None


def test_guard_real_admin_still_demotes_another_admin_while_one_remains(env):
    client = _web(env, "admin")
    client.post(f"/admin/users/{env.ids['admin2']}/edit", data=_admin_edit_form(env, "admin2", role="personel"))
    assert _account(env, "admin2")[0] == "personel"
    assert _audit(env, "account.role_change")


def test_c_last_active_admin_is_never_removed_by_a_concurrent_request(env):
    """Decision function: a request whose actor is no longer an active admin (another request
    already demoted it) cannot remove the remaining one."""
    from types import SimpleNamespace

    from app.extensions import db
    from app.models import User
    from app.services.account_change_guard import admin_continuity_refusal

    with env.app.app_context():
        admin2 = db.session.get(User, env.ids["admin2"])
        assert admin2 is not None
        admin2.is_active = False
        db.session.commit()
        stale_actor = SimpleNamespace(id=env.ids["admin2"], role="admin")
        target = db.session.get(User, env.ids["admin"])
        assert admin_continuity_refusal(stale_actor, target, new_role="personel", new_active=True) == "last_active_admin"
        assert admin_continuity_refusal(stale_actor, target, new_role="admin", new_active=False) == "last_active_admin"
        assert admin_continuity_refusal(target, target, new_role="personel", new_active=True) == "admin_self_demotion"
        assert admin_continuity_refusal(stale_actor, target, new_role="admin", new_active=True) is None
        plain = db.session.get(User, env.ids["plain"])
        assert admin_continuity_refusal(stale_actor, plain, new_role="personel", new_active=False) is None
        db.session.rollback()


def test_c_active_admin_lock_is_a_row_lock_on_postgresql():
    from sqlalchemy.dialects import postgresql

    from app.services.account_change_guard import active_admin_lock_statement

    sql = str(active_admin_lock_statement().compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert "ORDER BY" in sql


# --------------------------------------------------------------------------------------
# K5: file-center role matrix
# --------------------------------------------------------------------------------------


def _fc_rows(env):
    from app.file_center.permissions import PERMISSION_FIELDS
    from app.models.file_center_models import FileCenterRolePermission

    with env.app.app_context():
        return {
            row.role_key: (row.id, row.role_label, row.description or "", bool(row.is_active))
            + tuple(bool(getattr(row, field, False)) for field in PERMISSION_FIELDS)
            for row in FileCenterRolePermission.query.order_by(FileCenterRolePermission.id).all()
        }


def _fc_form(env, change=None, extra=None):
    """The full current matrix as a form, with ``change`` = {(role_key, field): bool} applied."""
    from app.file_center.permissions import PERMISSION_FIELDS

    form = {}
    for role_key, values in _fc_rows(env).items():
        row_id, label, description, active = values[:4]
        prefix = f"role_{row_id}_"
        form[prefix + "role_label"] = label
        form[prefix + "description"] = description
        if active:
            form[prefix + "is_active"] = "on"
        for field, value in zip(PERMISSION_FIELDS, values[4:], strict=True):
            value = (change or {}).get((role_key, field), value)
            if value:
                form[prefix + field] = "on"
    form.update(extra or {})
    return form


def test_k5_file_center_non_admin_matrix_manager_cannot_escalate_or_touch_protected_rows(env, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")
    client = _web(env, "sysadm")
    assert client.get("/file-center/settings/roles").status_code == 200
    before = _fc_rows(env)
    attempts = (
        {("admin", "can_manage_role_matrix"): False},
        {("sistem_yoneticisi", "can_manage_admin"): False},
        {("dosya_merkezi_yetkilisi", "can_manage_role_matrix"): True},
        {("personel", "can_manage_role_matrix"): True},
        {("personel", "can_view_logs"): True},
    )
    for change in attempts:
        client.post("/file-center/settings/roles", data=_fc_form(env, change))
    client.post("/file-center/settings/roles", data=_fc_form(env, extra={"new_role_key": "baskan", "new_role_label": "Baskan"}))
    assert _fc_rows(env) == before
    assert len(_refusals(env, "file_center_role_matrix")) >= len(attempts) + 1


def test_guard_file_center_real_admin_changes_still_work(env, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")
    admin = _web(env, "admin")
    admin.get("/file-center/settings/roles")
    from app.file_center.permissions import PERMISSION_FIELDS

    admin.post("/file-center/settings/roles", data=_fc_form(env, {("sistem_yoneticisi", "can_manage_admin"): False}))
    assert _fc_rows(env)["sistem_yoneticisi"][4 + PERMISSION_FIELDS.index("can_manage_admin")] is False
    from app.models.file_center_models import FileAuditLog

    with env.app.app_context():
        assert FileAuditLog.query.filter_by(action="file_center_role_matrix_updated").count() >= 1


# --------------------------------------------------------------------------------------
# C: real PostgreSQL, two concurrent requests
# --------------------------------------------------------------------------------------


PG_URL = os.environ.get("BYS360_R05C_PG_URL", "")


def _pg_env(monkeypatch, install_interim_notes_schema):
    from app.extensions import db
    from app.services import runtime_schema

    assert "127.0.0.1" in PG_URL or "localhost" in PG_URL, "only an ephemeral local database"
    app = _r05._make_app(monkeypatch, PG_URL)
    with app.app_context():
        from sqlalchemy import text

        with db.engine.begin() as connection:  # throwaway local database: start from an empty schema
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        db.create_all()
        runtime_schema.provision_all()
        install_interim_notes_schema(db.engine)
        data = _r05._seed()
    data.app = app
    return data


def _active_admins(pg):
    from app.models import User

    with pg.app.app_context():
        return sorted(
            user.sicil_no for user in User.query.filter(User.role == "admin", User.is_active.is_(True)).all()
        )


def _race(pg, monkeypatch, *, lock):
    """admin demotes admin2 while admin2 demotes admin. The first request holds the lock until the
    second has reached its own lock call, so the two requests always overlap."""
    import app.services.account_change_guard as guard

    real_lock = guard.lock_active_admin_ids
    second_waiting = threading.Event()
    first_locked = threading.Event()
    order: list[str] = []

    def plain_read():  # the pre-fix pattern: read, then write, no row lock
        from app.extensions import db
        from app.models import User

        return {
            int(row.id)
            for row in db.session.query(User.id, User.role, User.is_active).filter(User.is_active.is_(True)).all()
            if (row.role or "").strip().lower() == "admin"
        }

    def instrumented():
        name = threading.current_thread().name
        if name == "second":
            first_locked.wait(10)
            second_waiting.set()
            order.append("second:lock-call")
        result = real_lock() if lock else plain_read()
        order.append(f"{name}:locked")
        if name == "first":
            first_locked.set()
            second_waiting.wait(10)
            time.sleep(0.5)  # the second request is now blocked on the row lock (or has read)
        return result

    monkeypatch.setattr(guard, "lock_active_admin_ids", instrumented)
    clients = {"first": _web(pg, "admin"), "second": _web(pg, "admin2")}
    targets = {"first": "admin2", "second": "admin"}
    errors: list[BaseException] = []

    def run(name):
        try:
            target = targets[name]
            clients[name].post(f"/admin/users/{pg.ids[target]}/edit", data=_admin_edit_form(pg, target, role="personel"))
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(name,), name=name) for name in ("first", "second")]
    threads[0].start()
    first_locked.wait(10)
    threads[1].start()
    for thread in threads:
        thread.join(30)
    assert not errors, errors
    return order


@pytest.mark.skipif(not PG_URL, reason="needs BYS360_R05C_PG_URL (an ephemeral local PostgreSQL database)")
def test_c_postgresql_concurrent_mutual_demotion_keeps_one_active_admin(monkeypatch, install_interim_notes_schema):
    pg = _pg_env(monkeypatch, install_interim_notes_schema)
    assert _active_admins(pg) == sorted([SICIL["admin"], SICIL["admin2"]])
    order = _race(pg, monkeypatch, lock=True)
    assert order.index("first:locked") < order.index("second:locked"), order
    assert len(_active_admins(pg)) == 1, "the row lock serialises the two demotions; the second is refused"
    assert _refusals(pg, "last_active_admin") or _refusals(pg, "admin_self_demotion")


@pytest.mark.skipif(not PG_URL, reason="needs BYS360_R05C_PG_URL (an ephemeral local PostgreSQL database)")
def test_c_postgresql_control_without_the_row_lock_the_race_loses_every_admin(monkeypatch, install_interim_notes_schema):
    """Sensitivity check for the test above: the same overlap with a plain read (no FOR UPDATE)
    lets both requests pass the check and leaves no active admin."""
    pg = _pg_env(monkeypatch, install_interim_notes_schema)
    _race(pg, monkeypatch, lock=False)
    assert _active_admins(pg) == []


# --------------------------------------------------------------------------------------
# Independent review of edf00cfb (REQUEST_CHANGES): each test failed on edf00cfb
# --------------------------------------------------------------------------------------


def _set_role(env, key, role, *, active=None):
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[key])
        assert user is not None
        user.role = role
        if active is not None:
            user.is_active = active
        db.session.commit()


def test_m1_admin_import_never_demotes_or_deactivates_an_admin_of_any_spelling(env):
    from tests.security.test_r05_account_change_authority_contract import _xlsx

    _set_role(env, "admin", "Admin ")
    _set_role(env, "admin2", "admin", active=False)
    headers = ("Sicil No", "Ad", "Soyad", "E-posta", "Unvan", "Birim", "Üst Birim", "Rol", "Aktif")
    rows = [(*_xlsx_row(SICIL["admin"], "personel"), "0")]
    _web(env, "admin").post(
        "/admin/users/import",
        data={"excel_file": (_xlsx(rows, headers=headers), "personel.xlsx")},
        content_type="multipart/form-data",
    )
    assert _account(env, "admin") == ("Admin ", True, False)


def test_m2_reset_all_keeps_every_admin_account_of_any_spelling(env):
    _set_role(env, "admin", "Admin ")
    _set_role(env, "admin2", "ADMIN")
    _web(env, "admin").post("/admin/users/reset-all")
    assert _account(env, "admin") == ("Admin ", True, False)
    assert _account(env, "admin2") == ("ADMIN", True, False)


def _v10_row(env, role, key):
    from app.models import RoleMenuDefault

    with env.app.app_context():
        row = RoleMenuDefault.query.filter_by(role_name=role, menu_key=key).order_by(RoleMenuDefault.id.desc()).first()
        return None if row is None else (bool(row.is_visible), row.source_type)


def test_m3_a_settings_visit_never_reverts_an_admin_v10_change(env):
    admin = _seeded_client(env, "admin")
    matrix = _v10_matrix(env)
    form = {
        f"assistant_matrix__{feature}__{role}": "on"
        for feature, roles in matrix.items()
        for role, visible in roles.items()
        if visible and not (feature == "assistant_module" and role == "grup_baskani")
    }
    admin.post("/settings/assistant-role-matrix-v10/save", data=form)
    assert _v10_row(env, "grup_baskani", "assistant_module")[0] is False
    _sync_role_defaults(env)  # K13: the settings seed runs on the real admin's explicit sync, not per request
    _web(env, NON_ADMIN).get("/settings")
    assert _v10_row(env, "grup_baskani", "assistant_module")[0] is False
    assert _v10_matrix(env)["assistant_module"]["grup_baskani"] is False


def test_l1_an_unchanged_v10_form_by_a_non_admin_writes_nothing(env):
    from app.extensions import db
    from app.models import RoleMenuDefault

    _seeded_client(env, "admin")
    with env.app.app_context():
        db.session.add(RoleMenuDefault(role_name="grup_baskani", menu_key="sanal_asistan", is_visible=False, source_type="manual"))
        db.session.commit()
    matrix = _v10_matrix(env)
    before = _role_profile(env, "grup_baskani")
    form = {f"assistant_matrix__{f}__{r}": "on" for f, roles in matrix.items() for r, v in roles.items() if v}
    _web(env, NON_ADMIN).post("/settings/assistant-role-matrix-v10/save", data=form)
    assert _role_profile(env, "grup_baskani") == before


def test_l2_k5_a_non_admin_matrix_manager_never_changes_the_row_that_also_backs_protected_roles(env, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")
    client = _web(env, "sysadm")
    client.get("/file-center/settings/roles")
    before = _fc_rows(env)
    from app.file_center.permissions import PERMISSION_FIELDS

    guest_index = 4 + PERMISSION_FIELDS.index("can_create_guest_links")
    client.post("/file-center/settings/roles", data=_fc_form(env, {("personel", "can_create_guest_links"): not before["personel"][guest_index]}))
    assert _fc_rows(env) == before
    assert _refusals(env, "file_center_role_matrix")


def test_l3_revoking_the_lockout_keys_never_leaves_no_admin_with_access(env):
    _set_role(env, "admin2", "admin")
    admin = _seeded_client(env, "admin")
    _settings(admin, {"form_action": "save_user_visibility", "user_id": env.ids["admin2"], "menu_dashboard": "on"})
    assert ("admin_users", False, "user_override") in _overrides(env, "admin2")
    # admin2 is now without access; a later revocation of admin (by a stale admin2 request) must fail
    from types import SimpleNamespace

    from app.extensions import db
    from app.models import User
    from app.services.account_change_guard import lockout_revocation_refusal

    with env.app.test_request_context():
        target = db.session.get(User, env.ids["admin"])
        stale_actor = SimpleNamespace(id=env.ids["admin2"], role="admin")
        assert lockout_revocation_refusal(stale_actor, target, revoked_keys={"admin_users"}) == "last_admin_with_access"
        assert lockout_revocation_refusal(stale_actor, target, revoked_keys={"dashboard"}) is None
        db.session.rollback()


def test_l4_named_archives_are_written_and_deleted_by_a_real_admin_only_and_audited(env):
    from app.models import SystemSetting

    archive_key = _save_archive(env, "dashboard", name="r05c-yonetim")
    assert _audit(env, "settings.archive_save")
    with env.app.app_context():
        before = SystemSetting.query.filter_by(setting_key=archive_key).first().value_text
    client = _web(env, NON_ADMIN)
    _settings(client, {"form_action": "save_named_archive", "user_id": env.ids["plain"], "archive_name": "r05c-yonetim", "archive_scope": "general", "menu_settings": "on"})
    _settings(client, {"form_action": "delete_named_archive", "user_id": env.ids["plain"], "archive_key": archive_key})
    with env.app.app_context():
        row = SystemSetting.query.filter_by(setting_key=archive_key).first()
        assert row is not None and row.value_text == before
    assert len(_refusals(env, "settings_archive_write")) == 2


def test_info_a_non_admin_assistant_matrix_save_never_re_enables_a_disabled_assistant(env):
    from app.extensions import db
    from app.models import ModuleSetting

    _seeded_client(env, "admin")
    with env.app.app_context():
        row = ModuleSetting.query.filter_by(module_key="assistant", setting_key="enabled").first()
        if row is None:
            row = ModuleSetting(module_key="assistant", setting_key="enabled", label="Sanal Asistan Aktif", value_type="bool")
            db.session.add(row)
        row.value_text = "false"
        db.session.commit()
    current = _module_setting(env, "assistant", "visible_roles")
    form = {"form_action": "save_assistant_role_matrix"}
    roles = (current[0] if current else "admin,baskan,baskan_yardimcisi,grup_baskani,mali_musavir,koordinator,birim_sorumlusu").split(",")
    form.update({f"assistant_role_policy__{role}__assistant_module": "on" for role in roles if role})
    _settings(_web(env, NON_ADMIN), form)
    assert _module_setting(env, "assistant", "enabled")[0] == "false"
