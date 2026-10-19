from __future__ import annotations

from typing import Any

# BYS360_AG1_AG2_ASSISTANT_MENU_VISIBILITY_SERVICE_START

def _bys360_assistant_norm(value):
    value = str(value or "").strip().lower()
    return (
        value.replace("ı", "i")
        .replace("İ", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def _bys360_assistant_truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on", "aktif", "active", "enabled", "show", "visible", "izinli"}


def _bys360_assistant_user_role_values(user):
    values = []
    for attr in ("role", "role_name", "user_role", "profile", "authority_role"):
        value = getattr(user, attr, None)
        if value:
            values.append(value)
    role_obj = getattr(user, "role_obj", None) or getattr(user, "role_record", None)
    if role_obj is not None:
        for attr in ("name", "code", "title"):
            value = getattr(role_obj, attr, None)
            if value:
                values.append(value)
    return values


def _bys360_assistant_is_admin_like(user):
    normalized = {_bys360_assistant_norm(v) for v in _bys360_assistant_user_role_values(user)}
    allowed = {
        "admin",
        "administrator",
        "sistem yoneticisi",
        "sistem_yoneticisi",
        "super_admin",
        "baskan",
        "başkan",
        "ust yonetim",
        "ust_yonetim",
    }
    return bool(normalized & allowed)


def _bys360_assistant_get_db():
    try:
        from app.extensions import db
        return db
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/menu_visibility.py)")
    try:
        from app import db
        return db
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/menu_visibility.py:68")
        return None


def _bys360_assistant_collect_from_user_attrs(user, menu_map):
    for attr in ("menu_map", "menu_permissions", "permissions", "allowed_menus", "feature_flags"):
        value = getattr(user, attr, None)
        if not value:
            continue
        if isinstance(value, dict):
            for key, allowed in value.items():
                _bys360_assistant_apply_key(menu_map, key, allowed)
        elif isinstance(value, (list, tuple, set)):
            for key in value:
                _bys360_assistant_apply_key(menu_map, key, True)


def _legacy_build_menu_visibility_map_v1(user=None):
    if user is None:
        try:
            from flask_login import current_user
            user = current_user
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/menu_visibility.py:200")
            user = None

    menu_map: dict[str, bool] = {}
    if user is None or not getattr(user, "is_authenticated", False):
        return menu_map

    if _bys360_assistant_is_admin_like(user):
        menu_map["assistant_module"] = True
        menu_map["ai_agent_panel"] = True
        menu_map["ai_teaching_center"] = True

    _bys360_assistant_collect_from_user_attrs(user, menu_map)
    _bys360_assistant_collect_from_db(user, menu_map)

    if menu_map.get("assistant_module"):
        menu_map["ai_agent_panel"] = True
    if menu_map.get("ai_agent_panel"):
        menu_map["assistant_module"] = True
    if menu_map.get("ai_teaching_center"):
        menu_map["ai_agent_panel"] = True
        menu_map["assistant_module"] = True

    return menu_map
# BYS360_AG1_AG2_ASSISTANT_MENU_VISIBILITY_SERVICE_END

# BYS360_ASSISTANT_TABS_ROLE_MATRIX_V2_BEGIN
# BYS360 Asistanı alt sekmeleri için ayar/rol matrisi duyarlı görünürlük servisi.
_BYS360_ASSISTANT_PANEL_ROLES = {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'}
_BYS360_ASSISTANT_ADMIN_ROLES = {'admin', 'baskan'}
_BYS360_ASSISTANT_ALL_TAB_KEYS = {'assistant_module', 'ai_agent_panel', 'ai_agent_knowledge', 'ai_agent_teaching_center', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary', 'assistant_logs', 'assistant_settings'}

def _bys360_assistant_apply_key(menu_map, raw_key, raw_value=True):
    key_norm = _bys360_assistant_norm(raw_key)
    allowed = _bys360_assistant_truthy(raw_value)
    if key_norm in ('assistant_module', 'ai_agent', 'ai_agent_module', 'virtual_assistant', 'sanal_asistan', 'guvenli_sanal_asistan', 'güvenli_sanal_asistan'):
        menu_map["assistant_module"] = allowed
        if allowed:
            menu_map.setdefault("ai_agent_panel", True)
        else:
            for _key in ["ai_agent_panel", "ai_agent_knowledge", "ai_agent_teaching_center", "ai_teaching_center"]:
                menu_map[_key] = False
    elif key_norm in ('ai_agent_panel', 'assistant_panel', 'asistan_paneli', 'assistant_center'):
        menu_map["ai_agent_panel"] = allowed
    elif key_norm in ('ai_agent_knowledge', 'ai_teaching_center', 'assistant_knowledge', 'asistan_bilgi_bankasi', 'asistan_bilgi_bankası'):
        menu_map["ai_agent_knowledge"] = allowed
        menu_map["ai_teaching_center"] = allowed
    elif key_norm in ('ai_agent_teaching_center', 'assistant_teaching_center', 'asistan_ogretim_merkezi', 'asistan_öğretim_merkezi'):
        menu_map["ai_agent_teaching_center"] = allowed
    elif key_norm in _BYS360_ASSISTANT_ALL_TAB_KEYS:
        menu_map[key_norm] = allowed


def _bys360_assistant_role_key(user):
    for _value in _bys360_assistant_user_role_values(user):
        _norm = _bys360_assistant_norm(_value).replace(" ", "_")
        if _norm:
            return _norm
    return ""


def _bys360_assistant_default_map_for_role(role_key):
    _role = _bys360_assistant_norm(role_key).replace(" ", "_")
    _map = {}
    if _role in _BYS360_ASSISTANT_PANEL_ROLES:
        _map["assistant_module"] = True
        _map["ai_agent_panel"] = True
    if _role in _BYS360_ASSISTANT_ADMIN_ROLES:
        _map["ai_agent_knowledge"] = True
        _map["ai_teaching_center"] = True
        _map["ai_agent_teaching_center"] = True
    return _map


def _bys360_assistant_collect_from_db(user, menu_map):
    from app.services.assistant_settings_service import (
        assistant_feature_row_priority,
        canonical_assistant_feature_key,
    )

    db = _bys360_assistant_get_db()
    if db is None:
        return
    try:
        from sqlalchemy import bindparam, inspect, text
        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/menu_visibility.py:282")
        return

    uid = getattr(user, "id", None)
    role_values = [_bys360_assistant_norm(v).replace(" ", "_") for v in _bys360_assistant_user_role_values(user) if v]
    role_values = [v for v in role_values if v]

    queries: list[tuple[str, str | None, str | None]] = []
    if "role_menu_defaults" in table_names and role_values:
        queries.append(("role_menu_defaults", "role_name", None))
    if "user_menu_permissions" in table_names and uid is not None:
        queries.append(("user_menu_permissions", None, "user_id"))

    for table, role_col, user_col in queries:
        try:
            cols = [c["name"] for c in inspector.get_columns(table)]
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/menu_visibility.py:295)")
            continue
        if "menu_key" not in cols or "is_visible" not in cols:
            continue
        where = []
        params: dict[str, Any] = {}
        if role_col and role_col in cols:
            where.append(f"lower(cast({role_col} as text)) IN :roles")
            params["roles"] = tuple(role_values)
        if user_col and user_col in cols:
            where.append(f"{user_col} = :uid")
            params["uid"] = uid
        if not where:
            continue
        try:
            source = "source_type" if "source_type" in cols else "NULL"
            stmt = text(f"SELECT id, menu_key, is_visible, {source} AS source_type FROM {table} WHERE " + " AND ".join(where) + " ORDER BY id ASC")
            if "roles" in params:
                stmt = stmt.bindparams(bindparam("roles", expanding=True))
            rows = db.session.execute(stmt, params).mappings().all()
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/menu_visibility.py:312)")
            continue
        if table == "user_menu_permissions":
            # K2-b: a per-user row the main menu map's K2 ceiling does not recognise grants nothing here.
            from app.services.personnel_read_grant import explicit_grant_keys
            from app.services.settings.menu_grant_ceiling import unrecognised_user_row_grants

            refused = unrecognised_user_row_grants(
                user,
                [(row.get("menu_key"), _bys360_assistant_truthy(row.get("is_visible")), row.get("source_type")) for row in rows],
                exempt_keys=explicit_grant_keys(),
            )
            rows = [row for row in rows if not (_bys360_assistant_truthy(row.get("is_visible")) and str(row.get("menu_key") or "").strip() in refused)]
        resolved: dict[str, tuple[tuple[int, int], Any]] = {}
        for row in rows:
            feature = canonical_assistant_feature_key(row.get("menu_key"))
            if feature not in _BYS360_ASSISTANT_ALL_TAB_KEYS:
                _bys360_assistant_apply_key(menu_map, row.get("menu_key"), row.get("is_visible"))
                continue
            rank = (assistant_feature_row_priority(row.get("menu_key"), row.get("source_type"), feature), -row["id"])
            if feature not in resolved or rank < resolved[feature][0]:
                resolved[feature] = (rank, row)
        # Master last: no child or alias can reopen a resolved denial.
        for feature in sorted(resolved, key=lambda key: (key == "assistant_module", key)):
            _bys360_assistant_apply_key(menu_map, feature, resolved[feature][1].get("is_visible"))

    # Eski module_settings visible_roles desteği korunur; ama rol_menu_defaults kapalı satırı varsa yukarıdaki değer sonradan ezmez.
    try:
        if "module_settings" in table_names:
            from app.services.assistant_settings_service import assistant_enabled_for_value

            rows = db.session.execute(text("SELECT setting_key, value_text, is_active FROM module_settings WHERE module_key in ('assistant','ai_agent')")).mappings().all()
            for row in rows:
                setting = _bys360_assistant_norm(row.get("setting_key"))
                if setting == "visible_roles":
                    from app.services.assistant_settings_service import visible_roles_for_value

                    visible_roles = visible_roles_for_value(row.get("value_text") or "")
                    if role_values and not (set(role_values) & visible_roles):
                        menu_map["assistant_module"] = False
                        menu_map["ai_agent_panel"] = False
                elif setting in {"enabled", "active"} and not assistant_enabled_for_value(row.get("value_text")):
                    menu_map["assistant_module"] = False
                    menu_map["ai_agent_panel"] = False
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/menu_visibility.py)")


def build_menu_visibility_map(user=None):
    if user is None:
        try:
            from flask_login import current_user
            user = current_user
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/menu_visibility.py:344")
            user = None
    menu_map: dict[str, bool] = {}
    if user is None or not getattr(user, "is_authenticated", False):
        return menu_map
    role_key = _bys360_assistant_role_key(user)
    menu_map.update(_bys360_assistant_default_map_for_role(role_key))
    _bys360_assistant_collect_from_user_attrs(user, menu_map)
    _bys360_assistant_collect_from_db(user, menu_map)

    # Ana anahtar kapalıysa alt sekmeler kapalı kalır. Ana anahtar açıksa panel açılabilir ama bilgi/öğretim ayrı yönetilir.
    if menu_map.get("assistant_module") is False:
        for _key in ["ai_agent_panel", "ai_agent_knowledge", "ai_agent_teaching_center", "ai_teaching_center"]:
            menu_map[_key] = False
    if menu_map.get("ai_agent_panel"):
        menu_map["assistant_module"] = True
    if menu_map.get("ai_agent_knowledge"):
        menu_map["ai_teaching_center"] = True
    if menu_map.get("ai_teaching_center"):
        menu_map["ai_agent_knowledge"] = True
    return menu_map
# BYS360_ASSISTANT_TABS_ROLE_MATRIX_V2_END

# BYS360_PERFORMANCE_MAIN_SWITCH_ROLE_MATRIX_V3_BEGIN
# Eski/yardımcı menu_visibility servisinden gelen maplerde de performans ana anahtarı korunur.
_BYS360_PERFORMANCE_MAIN_KEYS = {'performance_module', 'performance_management', 'performans_yonetimi'}
_BYS360_PERFORMANCE_CHILD_KEYS = {'performance_tasks', 'performance_scorecard', 'scorecards', 'my_performance_comparison', 'performance_dashboard', 'performance_reports', 'performance_criteria', 'criteria', 'performance_periods', 'periods', 'performance_evaluation_tasks', 'assignments', 'performance_task_management', 'performance_hierarchy_tree', 'performance_hierarchy_assignments', 'performance_team_compare', 'team_analysis', 'team_performance_comparison_history', 'performance_feedback_meetings', 'feedback_meetings', 'performance_publish', 'publish', 'performance_mail_settings', 'performance_mail', 'performance_process_tracking', 'performance_process_reports', 'performance_president_approvals', 'performance_personnel_support_publish_approval', 'performance_archive', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis'}

def _bys360_performance_apply_key(menu_map, raw_key, raw_value=True):
    key_norm = _bys360_assistant_norm(raw_key)
    allowed = _bys360_assistant_truthy(raw_value)
    if key_norm in _BYS360_PERFORMANCE_MAIN_KEYS:
        for _key in _BYS360_PERFORMANCE_MAIN_KEYS:
            menu_map[_key] = allowed
        if not allowed:
            for _key in _BYS360_PERFORMANCE_CHILD_KEYS:
                menu_map[_key] = False
    elif key_norm in _BYS360_PERFORMANCE_CHILD_KEYS:
        menu_map[key_norm] = allowed

try:
    _bys360_original_apply_key_perf_main_v3 = _bys360_assistant_apply_key
    def _bys360_assistant_apply_key(menu_map, raw_key, raw_value=True):
        _bys360_original_apply_key_perf_main_v3(menu_map, raw_key, raw_value)
        _bys360_performance_apply_key(menu_map, raw_key, raw_value)
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/menu_visibility.py)")
try:
    _bys360_original_build_menu_visibility_map_perf_main_v3_menu_visibility = build_menu_visibility_map
    def build_menu_visibility_map(user=None):
        menu_map = _bys360_original_build_menu_visibility_map_perf_main_v3_menu_visibility(user)
        if any(menu_map.get(_key) is False for _key in _BYS360_PERFORMANCE_MAIN_KEYS):
            for _child in _BYS360_PERFORMANCE_CHILD_KEYS:
                menu_map[_child] = False
        return menu_map
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/menu_visibility.py)")
# BYS360_PERFORMANCE_MAIN_SWITCH_ROLE_MATRIX_V3_END

# BYS360_GENERAL_SECTION_RESTORE_V4_BEGIN
# Yardımcı menu_visibility servisinde Genel çekirdeği korunur.
_BYS360_GENERAL_CORE_KEYS_V4 = {'general_section', 'home', 'dashboard', 'notifications', 'support_index', 'support_new', 'support_my_tickets'}
_BYS360_PERFORMANCE_MAIN_KEYS_V4 = {'performance_module', 'performance_management', 'performans_yonetimi'}
_BYS360_PERFORMANCE_GENERAL_SHORTCUT_KEYS_V4 = {'performance_tasks', 'performance_scorecard', 'performance_archive', 'my_performance_comparison', 'performance_reports'}
try:
    _bys360_original_build_menu_visibility_map_general_restore_v4 = build_menu_visibility_map
    def build_menu_visibility_map(user=None):
        menu_map = _bys360_original_build_menu_visibility_map_general_restore_v4(user)
        menu_map.setdefault("general_section", True)
        menu_map.setdefault("home", True)
        menu_map.setdefault("dashboard", True)
        main_enabled = any(bool(menu_map.get(_key, _key == "performance_module")) for _key in _BYS360_PERFORMANCE_MAIN_KEYS_V4)
        if not main_enabled:
            for _key in _BYS360_PERFORMANCE_GENERAL_SHORTCUT_KEYS_V4:
                menu_map[_key] = False
        return menu_map
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/menu_visibility.py)")
# BYS360_GENERAL_SECTION_RESTORE_V4_END

# BYS360_SETTINGS_CENTER_V2_NAME_COLLISION_FIX_BEGIN
# BYS360 SETTINGS CENTER V2: this module's build_menu_visibility_map (assistant/
# AI-agent-specific, role-matrix-driven) has the exact same name as the
# unrelated, main-sidebar-wide app.services.settings.effective_menu.
# build_menu_visibility_map -- two functions, two different implementations,
# same importable name in two different modules. This alias gives this
# module's version an unambiguous name for new call sites; the internal
# wrapper chain above (v3/v4) and the original name are both left completely
# untouched so no existing caller or behavior changes.
build_assistant_menu_visibility_map = build_menu_visibility_map
# BYS360_SETTINGS_CENTER_V2_NAME_COLLISION_FIX_END
