"""PR #70 second-review regressions; synthetic databases only."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.security import test_r05c_settings_authority_and_admin_continuity_contract as previous

env = previous.env


def _setting(env, module, key, value):
    from app.extensions import db
    from app.models import ModuleSetting

    with env.app.app_context():
        row = ModuleSetting.query.filter_by(module_key=module, setting_key=key).first()
        if row is None:
            row = ModuleSetting(module_key=module, setting_key=key, label=key, value_type="string")
            db.session.add(row)
        row.value_text = value
        db.session.commit()


@pytest.mark.parametrize("raw,expected", [
    ("koordinator\npersonel", {"koordinator", "personel"}),
    ("koordinator;personel", {"koordinator", "personel"}),
    ("", set()), (" \t\r\n", set()), ("unknown", set()),
    ("admin\tpersonel", set()), ("__none__", set()),
    ("koordinator,personel", {"koordinator", "personel"}),
    (None, set()),
])
def test_m_consumer_guard_and_matrix_use_same_effective_roles(env, raw, expected):
    from app.extensions import db
    from app.models import User
    from app.services.assistant_role_matrix_service import build_assistant_role_matrix
    from app.services.assistant_settings_service import (
        current_visible_roles,
        get_assistant_settings,
        is_assistant_visible_for_user,
    )
    from app.services.menu_visibility import _bys360_assistant_collect_from_db

    _setting(env, "assistant", "visible_roles", raw)
    with env.app.app_context():
        assert current_visible_roles() == expected
        assert set(build_assistant_role_matrix()["visible_roles"]) == expected
        settings = get_assistant_settings()
        for key in ("koordinator", "plain"):
            user = db.session.get(User, env.ids[key])
            assert user is not None
            menu = {"assistant_module": True, "ai_agent_panel": True}
            _bys360_assistant_collect_from_db(user, menu)
            assert menu["assistant_module"] is (user.role in expected)
            assert is_assistant_visible_for_user(user, settings) is (user.role in expected)


def _module_form(env):
    from app.services.settings_service import snapshot_module_settings

    with env.app.app_context():
        state = snapshot_module_settings()
    form = {"form_action": "save_module_foundation"}
    for module, values in state.items():
        for key, value in values.items():
            if value != "false":
                form[f"module__{module}__{key}"] = "on" if value == "true" else value
    return form


@pytest.mark.parametrize("flag", ["enabled", "widget_enabled", "panel_enabled"])
def test_m_ai_agent_enabled_is_protected_on_save_and_rollback(env, flag):
    admin = previous._seeded_client(env, "admin")
    _setting(env, "ai_agent", flag, "false")
    form = _module_form(env)
    form[f"module__ai_agent__{flag}"] = "on"
    previous._settings(previous._web(env, "baskan"), form)
    assert previous._module_setting(env, "ai_agent", flag)[0] == "false"


    assert previous._refusals(env, "settings_assistant")
    previous._settings(admin, form)
    assert previous._module_setting(env, "ai_agent", flag)[0] == "true"
    log_id = previous._change_logs(env, change_scope="module_settings")[-1]
    previous._settings(previous._web(env, "baskan"), {"form_action": "rollback_settings_change_entry", "change_log_id": log_id})
    assert previous._module_setting(env, "ai_agent", flag)[0] == "true"
    previous._settings(admin, {"form_action": "rollback_settings_change_entry", "change_log_id": log_id})
    assert previous._module_setting(env, "ai_agent", flag)[0] == "false"


@pytest.mark.parametrize("before,reason", [("", None), ("admin", "settings_assistant_roles")])
def test_m_explicit_null_write_is_compared_as_an_empty_stored_role_list(monkeypatch, before, reason):
    from app.main_handlers import account_settings_helpers as settings

    monkeypatch.setattr(settings, "current_user", SimpleNamespace(id=1, role="baskan"))
    assert settings._module_authority_refusal({"assistant": {"visible_roles": before}}, {"assistant": {"visible_roles": None}}) == reason


@pytest.mark.parametrize("role", ["admin", "Admin ", "ADMIN", "admin\t", "\tadmin", "admin\n", " admin \r\n", "\u00a0admin\u00a0"])
def test_a_reset_all_preserves_admin_whitespace_spellings(env, role):
    previous._set_role(env, "admin2", role)
    previous._web(env, "admin").post("/admin/users/reset-all")
    assert previous._account(env, "admin2") == (role, True, False)


@pytest.mark.parametrize("role", ["admin\tpersonel", "superadmin", "admin\x00", "ad min"])
def test_a_malformed_roles_do_not_gain_admin_authority(role):
    from app.services.account_change_guard import is_real_admin

    assert not is_real_admin(SimpleNamespace(id=1, role=role))


@pytest.mark.parametrize("role", ["admin\t", "\tadmin", "admin\n", " admin \r\n", "\u00a0admin\u00a0"])
def test_a_whitespace_admin_import_delete_and_continuity_are_consistent(env, role):
    from app.extensions import db
    from app.models import User
    from app.services.account_change_guard import (
        admin_continuity_refusal,
        is_protected_account,
        lock_active_admin_ids,
    )
    from tests.security.test_r05_account_change_authority_contract import _xlsx

    previous._set_role(env, "admin2", role)
    client = previous._web(env, "admin")
    client.post("/admin/users/import", data={"excel_file": (_xlsx([previous._xlsx_row(previous.SICIL["admin2"], "personel")]), "personel.xlsx")}, content_type="multipart/form-data")
    client.post(f"/admin/users/{env.ids['admin2']}/delete")
    assert previous._account(env, "admin2") == (role, True, False)
    previous._set_role(env, "admin", "admin", active=False)
    with env.app.app_context():
        target = db.session.get(User, env.ids["admin2"])
        actor = db.session.get(User, env.ids["admin"])
        assert target is not None and actor is not None
        assert is_protected_account(target, actor)
        assert lock_active_admin_ids() == {env.ids["admin2"]}
        assert admin_continuity_refusal(actor, target, new_role="personel", new_active=True) == "last_active_admin"
        assert admin_continuity_refusal(actor, target, new_role=role, new_active=False) == "last_active_admin"
        db.session.rollback()


@pytest.mark.parametrize("actor", ["admin", "baskan"])
def test_c_alias_and_exact_rows_unchanged_form_writes_nothing(env, actor):
    from app.extensions import db
    from app.models import RoleMenuDefault

    previous._seeded_client(env, "admin")
    with env.app.app_context():
        exact = RoleMenuDefault.query.filter_by(role_name="grup_baskani", menu_key="assistant_module").first()
        exact.is_visible = True
        exact.source_type = "manual"
        db.session.add(RoleMenuDefault(role_name="grup_baskani", menu_key="sanal_asistan", is_visible=False, source_type="manual"))
        db.session.commit()
    matrix = previous._v10_matrix(env)
    before = previous._role_profiles(env)
    form = {f"assistant_matrix__{feature}__{role}": "on" for feature, roles in matrix.items() for role, visible in roles.items() if visible}
    previous._web(env, actor).post("/settings/assistant-role-matrix-v10/save", data=form)
    assert previous._role_profiles(env) == before
    assert not previous._refusals(env, "assistant_role_matrix_v10")
    audit = previous._audit(env, "settings.assistant_role_matrix_v10_save")
    assert not audit or "0 cell(s) changed" in audit[-1].summary


def test_b_demotion_keeps_an_admin_with_usable_critical_access(env):
    from app.extensions import db
    from app.models import User, UserMenuPermission
    from app.services.account_change_guard import admin_continuity_refusal

    with env.app.app_context():
        db.session.add(UserMenuPermission(user_id=env.ids["admin2"], menu_key="settings", is_visible=False, source_type="user_override"))
        db.session.commit()
        actor = db.session.get(User, env.ids["admin2"])
        target = db.session.get(User, env.ids["admin"])
        assert admin_continuity_refusal(actor, target, new_role="personel", new_active=True) == "last_admin_with_access"
        db.session.rollback()


def test_c_newer_alias_never_reopens_exact_disabled_runtime(env):
    from app.extensions import db
    from app.models import RoleMenuDefault, User
    from app.services.assistant_module_access import _query_role_menu_defaults
    from app.services.menu_visibility import _bys360_assistant_collect_from_db

    previous._seeded_client(env, "admin")
    with env.app.app_context():
        exact = RoleMenuDefault.query.filter_by(role_name="grup_baskani", menu_key="assistant_module").first()
        exact.is_visible = False
        exact.source_type = "manual"
        db.session.add(RoleMenuDefault(role_name="grup_baskani", menu_key="sanal_asistan", is_visible=True, source_type="manual"))
        db.session.commit()
        assert _query_role_menu_defaults(db.session, "grup_baskani") is False
        menu = {"assistant_module": True, "ai_agent_panel": True}
        _bys360_assistant_collect_from_db(db.session.get(User, env.ids["grup_baskani"]), menu)
        assert menu["assistant_module"] is False


def test_c_alias_real_change_is_authorized_manual_persistent_and_audited(env):
    from app.extensions import db
    from app.models import RoleMenuDefault

    admin = previous._seeded_client(env, "admin")
    with env.app.app_context():
        exact = RoleMenuDefault.query.filter_by(role_name="grup_baskani", menu_key="assistant_module").first()
        exact.source_type = "manual"
        db.session.add(RoleMenuDefault(role_name="grup_baskani", menu_key="sanal_asistan", is_visible=False, source_type="manual"))
        db.session.commit()
    matrix = previous._v10_matrix(env)
    assert matrix["assistant_module"]["grup_baskani"] is True
    form = {f"assistant_matrix__{feature}__{role}": "on" for feature, roles in matrix.items() for role, visible in roles.items() if visible and (feature, role) != ("assistant_module", "grup_baskani")}
    before = previous._role_profile(env, "grup_baskani")
    previous._web(env, "baskan").post("/settings/assistant-role-matrix-v10/save", data=form)
    assert previous._role_profile(env, "grup_baskani") == before
    assert previous._refusals(env, "assistant_role_matrix_v10")
    admin.post("/settings/assistant-role-matrix-v10/save", data=form)
    assert previous._v10_row(env, "grup_baskani", "assistant_module") == (False, "manual")
    previous._sync_role_defaults(env)  # K13: the seed runs on the explicit sync, not on GET /settings
    admin.get("/settings")
    assert previous._v10_matrix(env)["assistant_module"]["grup_baskani"] is False
    audit = previous._audit(env, "settings.assistant_role_matrix_v10_save")[-1]
    assert json.loads(audit.old_data_json) == {"assistant_module:grup_baskani": True}
    assert json.loads(audit.new_data_json) == {"assistant_module:grup_baskani": False}


@pytest.mark.parametrize("alias", ["sanal_asistan", "assistant.assistant_module", "sanal_asistan.assistant_module", "assistant_assistant_module", "sanal_asistan_assistant_module", "assistant"])
def test_c_alias_only_manual_denial_survives_no_op_and_seed_in_all_consumers(env, alias):
    from app.extensions import db
    from app.models import RoleMenuDefault, User
    from app.services.assistant_module_access import _query_role_menu_defaults
    from app.services.menu_visibility import build_assistant_menu_visibility_map

    admin = previous._seeded_client(env, "admin")
    with env.app.app_context():
        RoleMenuDefault.query.filter_by(role_name="grup_baskani", menu_key="assistant_module").delete()
        db.session.add(RoleMenuDefault(role_name="grup_baskani", menu_key=alias, is_visible=False, source_type="manual"))
        db.session.commit()
        assert _query_role_menu_defaults(db.session, "grup_baskani") is False
        assert build_assistant_menu_visibility_map(db.session.get(User, env.ids["grup_baskani"]))["assistant_module"] is False
    matrix = previous._v10_matrix(env)
    assert matrix["assistant_module"]["grup_baskani"] is False
    before = previous._role_profile(env, "grup_baskani")
    form = {f"assistant_matrix__{feature}__{role}": "on" for feature, roles in matrix.items() for role, visible in roles.items() if visible}
    admin.post("/settings/assistant-role-matrix-v10/save", data=form)
    assert previous._role_profile(env, "grup_baskani") == before
    previous._sync_role_defaults(env)  # K13: the seed runs on the explicit sync, not on GET /settings
    admin.get("/settings")
    assert previous._v10_matrix(env)["assistant_module"]["grup_baskani"] is False
    with env.app.app_context():
        assert _query_role_menu_defaults(db.session, "grup_baskani") is False
        assert build_assistant_menu_visibility_map(db.session.get(User, env.ids["grup_baskani"]))["assistant_module"] is False


@pytest.mark.parametrize("newer_key", ["assistant.assistant_module", "assistant_report_create"])
def test_c_user_exact_master_denial_beats_newer_alias_or_shortcut(env, monkeypatch, newer_key):
    from app.extensions import db
    from app.models import User, UserMenuPermission
    from app.services import assistant_module_access as access
    from app.services.menu_visibility import build_assistant_menu_visibility_map

    with env.app.test_request_context():
        user = db.session.get(User, env.ids["grup_baskani"])
        assert user is not None
        db.session.add(UserMenuPermission(user_id=user.id, menu_key="assistant_module", is_visible=False, source_type="manual"))
        db.session.flush()
        db.session.add(UserMenuPermission(user_id=user.id, menu_key=newer_key, is_visible=True, source_type="manual"))
        db.session.commit()
        monkeypatch.setattr(access, "current_user", user)
        assert access.assistant_module_enabled_for_current_user() is False
        assert build_assistant_menu_visibility_map(user)["assistant_module"] is False


@pytest.mark.parametrize("operation", ["bulk-passive", "bulk-archive"])
def test_b_bulk_change_keeps_an_admin_with_access(env, operation, monkeypatch):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    previous._set_role(env, "plain", "admin")
    with env.app.app_context():
        db.session.add(UserMenuPermission(user_id=env.ids["admin"], menu_key="settings", is_visible=False, source_type="user_override"))
        db.session.commit()
    from app.services import account_change_guard as guard

    real_lock = guard.lock_active_admin_ids
    loaded: list[User] = []

    def preloaded_lock():
        # Keep strong references in the actual request's identity map, before the first write.
        if not loaded:
            loaded.extend(User.query.all())
        return real_lock()

    monkeypatch.setattr(guard, "lock_active_admin_ids", preloaded_lock)
    previous._web(env, "admin").post(f"/admin/users/{operation}", data={"user_ids": [env.ids["admin2"], env.ids["plain"]]})
    with env.app.app_context():
        remaining = [db.session.get(User, env.ids[key]) for key in ("admin2", "plain")]
        assert any(user is not None and user.is_active for user in remaining)


@pytest.mark.parametrize("raw", ["", " \t", None, "invalid"])
def test_m_matrix_never_reenables_an_assistant_disabled_by_an_invalid_flag(env, raw):
    from app.services.assistant_settings_service import (
        current_visible_roles,
        get_assistant_settings,
    )

    previous._seeded_client(env, "admin")
    _setting(env, "assistant", "enabled", raw)
    with env.app.app_context():
        roles = current_visible_roles()
    form = {"form_action": "save_assistant_role_matrix"}
    form.update({f"assistant_role_policy__{role}__assistant_module": "on" for role in roles})
    previous._settings(previous._web(env, "baskan"), form)
    assert previous._module_setting(env, "assistant", "enabled")[0] == raw
    assert previous._refusals(env, "settings_assistant_roles:enabled")
    with env.app.app_context():
        assert get_assistant_settings()["enabled"] is False
