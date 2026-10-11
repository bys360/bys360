from __future__ import annotations

from typing import Any

from app.main_handlers.account_visibility_helpers import (
    _BYS360_ALL_MENU_ROLE_MATRIX_ITEM_BY_KEY,
    _BYS360_ALL_MENU_ROLE_MATRIX_ITEMS,
    _BYS360_ASSISTANT_TAB_RECOMMENDED,
    _BYS360_ASSISTANT_TAB_ROLE_MATRIX_ITEMS,
    _BYS360_BASE_ROLE_MATRIX_POLICY_CONFIGS,
    _BYS360_PERFORMANCE_MAIN_SWITCH_ITEM,
    _BYS360_PERFORMANCE_PERIOD_CENTER_POLICY_ITEMS_V2_1_23B,
    _BYS360_PERSONNEL_POLICY_CONFIG,
    _BYS360_PREVIOUS_BUILD_ROLE_MATRIX_POLICY_ITEMS,
    _BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_ALL_FEATURES_V1,
    _BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_FOR_ASSISTANT,
    _BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_V2_1_23B,
    _PERSONNEL_ROLE_MATRIX_CURRENT_SCOPE_KEYS,
    _PORTAL_ROLE_MATRIX_V2_12_CONFIG,
    ASSISTANT_ROLE_MATRIX_ITEMS,
    ASSISTANT_ROLE_MATRIX_KEYS,
    ASSISTANT_ROLE_MATRIX_RECOMMENDED,
    COMMUNICATION_POLICY_ROLE_OPTIONS,
    PERFORMANCE_ROLE_MATRIX_V12_ITEMS,
    PERSONNEL_ROLE_MATRIX_CURRENT_SCOPE_ITEMS,
    PORTAL_ROLE_MATRIX_V2_12_ITEMS,
    ROLE_MATRIX_POLICY_CONFIGS,
    SECURITY_QUESTION_CHOICES,
    SETTINGS_ARCHIVE_GROUP_KEY,
    SETTINGS_ARCHIVE_KEY_PREFIX,
    SUPPORT_HELP_ROLE_MATRIX_ITEMS,
    SystemSetting,
    User,
    UserMenuPermission,
    _apply_visibility_keys_to_user,
    _build_bulk_result_summary,
    _build_bulk_settings_profiles,
    _build_communication_policy_items,
    _build_communication_role_matrix,
    _build_role_matrix_group,
    _build_role_matrix_policy_items,
    _build_settings_archive_setting_key,
    _build_settings_matrix,
    _build_settings_presets,
    _build_settings_role_matrix_groups,
    _build_user_visibility_diff,
    _build_visibility_template_payload,
    _bys360_clean_general_role_matrix_performance_text_v5,
    _bys360_merge_performance_period_center_policy_items_v2_1_23b,
    _bys360_pf_v14_dedupe_flat_menu_items,
    _bys360_role_matrix_all_feature_items_v1,
    _collect_all_menu_keys,
    _collect_form_visible_keys,
    _collect_role_matrix_visible_keys_from_form,
    _delete_profile_photo_file,
    _delete_settings_template_archive,
    _extract_visible_keys_from_template_payload,
    _find_bulk_profile,
    _find_menu_item_by_key,
    _get_role_matrix_policy_items_or_raise,
    _get_settings_template_archive,
    _list_settings_template_archives,
    _normalize_visible_keys,
    _resolve_bulk_profile_keys,
    _resolve_bulk_result_summary_from_args,
    _role_matrix_form_field_name,
    _role_matrix_policy_config_map,
    _save_profile_photo,
    _save_settings_template_archive,
    _serialize_bulk_target_users,
    _slugify_archive_name,
    build_effective_user_menu_context,
    build_settings_foundation_context,
    build_settings_profile_context,
    build_settings_ui_diagnostics_panel,
    clear_user_menu_overrides,
    current_user,
    datetime,
    db,
    enforce_first_login_security_flow,
    enforce_first_login_security_flow_redirect,
    ensure_settings_phase1_seeded,
    extend_flat_menu_items_with_assistant_role_matrix_items,
    flash,
    flatten_settings_menu_definitions,
    get_assistant_role_matrix_recommended_keys,
    get_grouped_menu_definitions,
    get_role_default_menu_keys,
    get_unit_profile_menu_keys,
    io,
    json,
    logger,
    logging,
    re,
    redirect,
    request,
    rollback_settings_change,
    safe_render,
    save_module_settings_from_form,
    save_role_menu_defaults,
    save_system_settings_from_form,
    save_unit_menu_profile,
    save_user_menu_overrides,
    send_file,
    url_for,
    utc_now,
)
from app.route_support import normalize_role_name
from app.services.assistant_role_matrix_service import (
    build_assistant_role_matrix,
    reset_assistant_role_matrix_defaults,
    save_assistant_role_matrix_from_form,
)
from app.services.personnel_read_grant import (
    PERSONNEL_READ_ALL_KEY,
    PERSONNEL_READ_ALL_MENU_ITEM,
    has_personnel_read_all_grant,
)

# B1-F1: only an admin may assign or remove the personnel_read_all grant (and never on their
# own account); the rest of the admin family keeps the other /settings functions.
_PERSONNEL_READ_GRANT_ADMIN_ROLES = {"admin"}


def _can_change_personnel_read_grant(actor, target) -> bool:
    actor_id = getattr(actor, "id", None)
    return bool(
        actor_id is not None
        and getattr(target, "id", None) != actor_id
        and normalize_role_name(getattr(actor, "role", "")) in _PERSONNEL_READ_GRANT_ADMIN_ROLES
    )


# BYS360_PERSONNEL_FEATURE_MATRIX_V1_4_HELPER_DEDUP_AND_FULL_SAVE
def _bys360_personnel_feature_matrix_v14_dedupe_items(items):
    seen = set()
    result = []
    for item in items or []:
        key = str((item or {}).get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        clean = dict(item)
        clean["key"] = key
        result.append(clean)
    return result


def _bys360_personnel_feature_matrix_v14_dedupe_grouped_menu(grouped):
    seen = set()
    result = {}
    for group_name, items in (grouped or {}).items():
        clean_items = []
        for item in items or []:
            key = str((item or {}).get("key") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            clean = dict(item)
            clean["key"] = key
            clean_items.append(clean)
        if clean_items:
            result[group_name] = clean_items
    return result


def settings_page():
    grouped_menu_definitions = _bys360_personnel_feature_matrix_v14_dedupe_grouped_menu(get_grouped_menu_definitions())
    flat_menu_items = _bys360_personnel_feature_matrix_v14_dedupe_items(flatten_settings_menu_definitions())
    flat_menu_items = _bys360_personnel_feature_matrix_v14_dedupe_items(extend_flat_menu_items_with_assistant_role_matrix_items(flat_menu_items))
    # BYS360_PERSONNEL_FEATURE_MATRIX_V1_3_DEDUP_HELPER
    # Aynı menu_key birden fazla kaynaktan geldiyse tek satıra indirir.
    # Örnek: ai_agent_panel hem genel menüden hem asistan matrisi ekinden gelirse
    # user_menu_permissions tablosundaki unique constraint hata vermemelidir.
    _seen_menu_keys = set()
    _deduped_flat_menu_items = []
    for _item in flat_menu_items or []:
        _menu_key = str((_item or {}).get("key") or "").strip()
        if not _menu_key or _menu_key in _seen_menu_keys:
            continue
        _seen_menu_keys.add(_menu_key)
        _clean_item = dict(_item)
        _clean_item["key"] = _menu_key
        _deduped_flat_menu_items.append(_clean_item)
    flat_menu_items = _deduped_flat_menu_items
    # B1-F1: the personnel_read_all grant is selectable only in the per-user matrix
    # (rendered separately in settings.html, not in a bulk-toggle menu group).
    if PERSONNEL_READ_ALL_KEY not in _seen_menu_keys:
        flat_menu_items.append(dict(PERSONNEL_READ_ALL_MENU_ITEM))
    all_menu_keys = [item["key"] for item in flat_menu_items]
    users = (
        User.query
        .filter(User.role != "admin")
        .order_by(User.ad.asc(), User.soyad.asc())
        .all()
    )
    selected_user_id = request.values.get("user_id", type=int)
    selected_user = db.session.get(User, selected_user_id) if selected_user_id else None
    compare_user_id = request.values.get("compare_user_id", type=int)
    compare_user = db.session.get(User, compare_user_id) if compare_user_id else None
    selected_rule_map = {}
    settings_matrix = None
    settings_presets: dict[str, list[Any]] = {"presets": [], "group_toggles": []}
    bulk_settings_profiles = _build_bulk_settings_profiles(grouped_menu_definitions)
    bulk_target_users = _serialize_bulk_target_users(users)
    role_options = sorted({(user.role or "").strip() for user in users if (user.role or "").strip()})
    birim_options = sorted({(user.birim or "").strip() for user in users if (user.birim or "").strip()})
    bulk_result_summary = _resolve_bulk_result_summary_from_args(request.args, grouped_menu_definitions)
    phase1_seed_summary = ensure_settings_phase1_seeded(updated_by_user_id=getattr(current_user, "id", None))
    if not phase1_seed_summary.get("ok"):
        missing_tables = phase1_seed_summary.get('missing_tables') or []
        if missing_tables:
            flash(
                'Ayarlar altyapısı henüz veritabanına uygulanmamış. Eksik tablolar: ' + ', '.join(missing_tables) + '. Lütfen proje klasöründe flask db upgrade çalıştırın.',
                'warning',
            )
        elif phase1_seed_summary.get('error'):
            flash(f"Ayarlar omurgası hazırlanamadı: {phase1_seed_summary.get('error')}", 'warning')
    communication_role_matrix = _build_communication_role_matrix(_build_communication_policy_items(grouped_menu_definitions, flat_menu_items))
    assistant_role_matrix = build_assistant_role_matrix()
    settings_role_matrix_groups = _build_settings_role_matrix_groups(grouped_menu_definitions, flat_menu_items)
    foundation_context = build_settings_foundation_context() if phase1_seed_summary.get("ok") else {
        "system_groups": [],
        "module_groups": [],
        "role_defaults_snapshot": [],
        "unit_profiles_snapshot": [],
        "recent_change_logs": [],
        "stats": {"system_total": 0, "module_total": 0, "module_group_total": 0, "role_total": 0, "unit_profile_total": 0, "history_total": 0},
    }

    if request.method == "POST":
        form_action = (request.form.get("form_action") or "save_user_visibility").strip()

        if form_action in {"reset_person_based_role_matrix", "reset_user_kişi bazlı yetkis"}:
            form_action = "reset_user_overrides"

        if form_action in {"save_personnel_feature_matrix_full", "save_personnel_matrix_full"}:
            form_action = "save_user_visibility"

        if form_action == "save_system_foundation":
            return _handle_save_system_foundation()

        if form_action == "save_module_foundation":
            return _handle_save_module_foundation()

        if form_action == "sync_role_defaults":
            return _handle_sync_role_defaults()

        if form_action.startswith("save_role_matrix_group__"):
            return _handle_save_role_matrix_group(form_action, grouped_menu_definitions, flat_menu_items, all_menu_keys)

        if form_action.startswith("reset_role_matrix_group__"):
            return _handle_reset_role_matrix_group(form_action, grouped_menu_definitions, flat_menu_items, all_menu_keys)

        if form_action == "save_communication_role_matrix":
            return _handle_save_communication_role_matrix(grouped_menu_definitions, flat_menu_items, all_menu_keys)

        if form_action == "reset_communication_role_matrix":
            return _handle_reset_communication_role_matrix(grouped_menu_definitions, flat_menu_items, all_menu_keys)

        if form_action == "save_assistant_role_matrix":
            return _handle_save_assistant_role_matrix()

        if form_action == "reset_assistant_role_matrix":
            return _handle_reset_assistant_role_matrix()

        if form_action == "rollback_settings_change_entry":
            return _handle_rollback_settings_change_entry()

        if form_action == "bulk_apply_profile":
            return _handle_bulk_apply_profile(users, grouped_menu_definitions, flat_menu_items)

        if form_action == "export_visibility_template":
            return _handle_export_visibility_template(flat_menu_items)

        if form_action == "import_visibility_template":
            return _handle_import_visibility_template(flat_menu_items)

        if form_action == "save_named_archive":
            return _handle_save_named_archive(flat_menu_items)

        if form_action == "apply_named_archive":
            return _handle_apply_named_archive(all_menu_keys, flat_menu_items)

        if form_action == "delete_named_archive":
            return _handle_delete_named_archive()

        return _handle_user_scoped_profile_action(form_action, flat_menu_items, all_menu_keys)

    settings_presets = _build_settings_presets(grouped_menu_definitions, get_role_default_menu_keys(selected_user.role) if selected_user else set())
    selected_profile_resolution = None
    if selected_user:
        selected_profile_resolution = build_effective_user_menu_context(selected_user, flat_menu_items)
        selected_rule_map = dict(selected_profile_resolution["effective_rule_map"])
        defaults = set(selected_profile_resolution["role_default_keys"])
        settings_matrix = _build_settings_matrix(grouped_menu_definitions, selected_rule_map, defaults, selected_user=selected_user, users=users)
    else:
        defaults = set()


    settings_section_links = [
        {"id": "system-foundation", "label": "Genel Sistem", "icon": "fa-solid fa-building-shield"},
        {"id": "system-group-about", "label": "Hakkımızda", "icon": "fa-solid fa-circle-info"},
        {"id": "system-group-kunye", "label": "Sistem Künyesi", "icon": "fa-solid fa-address-card"},
        {"id": "module-foundation", "label": "Modül Ayarları", "icon": "fa-solid fa-sliders"},
        {"id": "general-role-policy", "label": "Genel Rol Matrisi", "icon": "fa-solid fa-layer-group"},
        {"id": "personnel-role-policy", "label": "Personel Rol Matrisi", "icon": "fa-solid fa-users-gear"},
        {"id": "performance-role-policy", "label": "Performans Rol Matrisi", "icon": "fa-solid fa-chart-line"},
        {"id": "communication-role-policy", "label": "İletişim Rol Matrisi", "icon": "fa-solid fa-comments"},
        {"id": "portal-role-policy", "label": "Portal Rol Matrisi", "icon": "fa-solid fa-stream"},
        {"id": "ai-role-policy", "label": "AI Rol Matrisi", "icon": "fa-solid fa-brain"},
        {"id": "settings-security-role-policy", "label": "Ayarlar Rol Matrisi", "icon": "fa-solid fa-shield-halved"},
        {"id": "role-foundation", "label": "Rol Varsayılanları", "icon": "fa-solid fa-user-shield"},
        {"id": "unit-foundation", "label": "Birim Profilleri", "icon": "fa-solid fa-sitemap"},
        {"id": "settings-diagnostics", "label": "Tanılama", "icon": "fa-solid fa-stethoscope"},
        {"id": "settings-history", "label": "Ayar Geçmişi", "icon": "fa-solid fa-clock-rotate-left"},
    ]
    if selected_user:
        settings_section_links.append({"id": "user-overrides", "label": "Personel Bazlı Rol Matrisi", "icon": "fa-solid fa-user-gear"})
        settings_section_links.append({"id": "settings-archives", "label": "Şablon Arşivi", "icon": "fa-solid fa-box-archive"})

    profile_context = build_settings_profile_context(selected_user, flat_menu_items) if phase1_seed_summary.get("ok") else {
        "unit_profiles_snapshot": [],
        "unit_profile_total": 0,
        "selected_user_resolution": None,
    }
    settings_ui_panel_context = build_settings_ui_diagnostics_panel(
        foundation_context=foundation_context,
        profile_context=profile_context,
        selected_user=selected_user,
    )
    user_diff_context = _build_user_visibility_diff(selected_user, compare_user, flat_menu_items) if selected_user and compare_user else None
    settings_archives = _list_settings_template_archives(flat_menu_items) if phase1_seed_summary.get("ok") else []
    selected_archive_key = (request.values.get("archive_key") or "").strip()

    return safe_render(
        "settings.html",
        "<h3>Ayarlar</h3>",
        users=users,
        grouped_menu_definitions=grouped_menu_definitions,
        selected_user=selected_user,
        selected_rule_map=selected_rule_map,
        settings_matrix=settings_matrix,
        role_default_keys=sorted(defaults),
        settings_presets=settings_presets,
        bulk_settings_profiles=bulk_settings_profiles,
        bulk_target_users=bulk_target_users,
        bulk_result_summary=bulk_result_summary,
        role_options=role_options,
        birim_options=birim_options,
        foundation_context=foundation_context,
        communication_role_matrix=communication_role_matrix,
        assistant_role_matrix=assistant_role_matrix,
        settings_role_matrix_groups=settings_role_matrix_groups,
        phase1_seed_summary=phase1_seed_summary,
        profile_context=profile_context,
        settings_section_links=settings_section_links,
        selected_profile_resolution=selected_profile_resolution,
        compare_user=compare_user,
        user_diff_context=user_diff_context,
        settings_archives=settings_archives,
        selected_archive_key=selected_archive_key,
        settings_ui_panel_context=settings_ui_panel_context,
        personnel_read_all_granted=has_personnel_read_all_grant(selected_user) if selected_user else False,
        personnel_read_all_editable=_can_change_personnel_read_grant(current_user, selected_user) if selected_user else False,
    )


# ---------------------------------------------------------------------------
# settings_page() POST action handlers.
#
# One handler per form_action, extracted verbatim (behavior-preserving, not
# rewritten) from settings_page()'s former inline dispatch chain. Several
# handlers intentionally do NOT follow the uniform try/except/flash/redirect
# shape used by most of them -- that non-uniformity is existing, tested
# production behavior and must not be normalized away:
#   - _handle_sync_role_defaults has no try/except (relies on the callee).
#   - _handle_rollback_settings_change_entry uses an if/else guard before its
#     try, not a try-first shape.
#   - _handle_bulk_apply_profile has two early-return validation guards
#     before its try block, and owns the sole commit for its whole loop.
#   - _handle_export_visibility_template has no commit and returns
#     send_file(...) directly, never a redirect, on its success path.
#   - _handle_apply_named_archive calls one of three already-committing
#     helpers and then performs an additional, deliberately-preserved
#     redundant db.session.commit() -- this is a known legacy quirk covered
#     by test_apply_named_archive_double_flash_when_only_second_commit_fails
#     and must not be "fixed" here.
# ---------------------------------------------------------------------------


def _handle_save_system_foundation():
    try:
        changed = save_system_settings_from_form(request.form, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"Genel sistem ayarları kaydedildi. Güncellenen alan: {changed}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Genel sistem ayarları kaydedilirken hata oluştu.", "danger")
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id) if keep_user_id else url_for("main.settings_page"))


def _handle_save_module_foundation():
    try:
        changed = save_module_settings_from_form(request.form, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"Modül ayar omurgası kaydedildi. Güncellenen alan: {changed}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Modül ayarları kaydedilirken hata oluştu.", "danger")
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id) if keep_user_id else url_for("main.settings_page"))


def _handle_sync_role_defaults():
    seed_result = ensure_settings_phase1_seeded(updated_by_user_id=getattr(current_user, "id", None))
    if seed_result.get("ok"):
        flash("Rol varsayılanı ve ayar omurgası senkronize edildi.", "success")
    else:
        flash(f"Rol varsayılanları senkronize edilirken hata oluştu: {seed_result.get('error')}", "danger")
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id) if keep_user_id else url_for("main.settings_page"))


def _handle_save_role_matrix_group(form_action, grouped_menu_definitions, flat_menu_items, all_menu_keys):
    matrix_key = form_action.replace("save_role_matrix_group__", "", 1).strip()
    changed_total = 0
    try:
        config, policy_items = _get_role_matrix_policy_items_or_raise(matrix_key, grouped_menu_definitions, flat_menu_items)
        scoped_keys = {item["key"] for item in policy_items}
        for role_key, _role_label in COMMUNICATION_POLICY_ROLE_OPTIONS:
            current_visible = set(get_role_default_menu_keys(role_key))
            scoped_visible = _collect_role_matrix_visible_keys_from_form(matrix_key, role_key, scoped_keys)
            merged_visible = (current_visible - scoped_keys) | scoped_visible
            changed_total += save_role_menu_defaults(role_key, all_menu_keys, merged_visible, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"{config['title']} kaydedildi. İşlenen satır: {changed_total}", "success")
        section_id = config["section_id"]
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Rol matrisi kaydedilirken hata oluştu.", "danger")
        section_id = "module-role-matrices"
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id, section=section_id) if keep_user_id else url_for("main.settings_page", section=section_id))


def _handle_reset_role_matrix_group(form_action, grouped_menu_definitions, flat_menu_items, all_menu_keys):
    matrix_key = form_action.replace("reset_role_matrix_group__", "", 1).strip()
    changed_total = 0
    try:
        config, policy_items = _get_role_matrix_policy_items_or_raise(matrix_key, grouped_menu_definitions, flat_menu_items)
        scoped_keys = {item["key"] for item in policy_items}
        for role_key, _role_label in COMMUNICATION_POLICY_ROLE_OPTIONS:
            current_visible = set(get_role_default_menu_keys(role_key))
            static_visible = set(get_role_default_menu_keys(role_key, prefer_database=False))
            if matrix_key == "assistant":
                static_visible |= get_assistant_role_matrix_recommended_keys(role_key)
            merged_visible = (current_visible - scoped_keys) | (static_visible & scoped_keys)
            changed_total += save_role_menu_defaults(role_key, all_menu_keys, merged_visible, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"{config['title']} önerilen rol politikasına döndürüldü. İşlenen satır: {changed_total}", "success")
        section_id = config["section_id"]
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Rol matrisi sıfırlanırken hata oluştu.", "danger")
        section_id = "module-role-matrices"
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id, section=section_id) if keep_user_id else url_for("main.settings_page", section=section_id))


def _handle_save_communication_role_matrix(grouped_menu_definitions, flat_menu_items, all_menu_keys):
    communication_policy_items = _build_communication_policy_items(grouped_menu_definitions, flat_menu_items)
    communication_keys = {item["key"] for item in communication_policy_items}
    changed_total = 0
    try:
        for role_key, _role_label in COMMUNICATION_POLICY_ROLE_OPTIONS:
            current_visible = set(get_role_default_menu_keys(role_key))
            scoped_visible = {
                item_key
                for item_key in communication_keys
                if request.form.get(f"role_policy__{role_key}__{item_key}")
            }
            merged_visible = (current_visible - communication_keys) | scoped_visible
            changed_total += save_role_menu_defaults(role_key, all_menu_keys, merged_visible, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"İletişim ve anket rol matrisi kaydedildi. İşlenen satır: {changed_total}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("İletişim ve anket rol matrisi kaydedilirken hata oluştu.", "danger")
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id, section="communication-role-policy") if keep_user_id else url_for("main.settings_page", section="communication-role-policy"))


def _handle_reset_communication_role_matrix(grouped_menu_definitions, flat_menu_items, all_menu_keys):
    communication_policy_items = _build_communication_policy_items(grouped_menu_definitions, flat_menu_items)
    communication_keys = {item["key"] for item in communication_policy_items}
    changed_total = 0
    try:
        for role_key, _role_label in COMMUNICATION_POLICY_ROLE_OPTIONS:
            current_visible = set(get_role_default_menu_keys(role_key))
            static_visible = set(get_role_default_menu_keys(role_key, prefer_database=False))
            merged_visible = (current_visible - communication_keys) | (static_visible & communication_keys)
            changed_total += save_role_menu_defaults(role_key, all_menu_keys, merged_visible, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"İletişim ve anket rol matrisi önerilen kurala döndürüldü. İşlenen satır: {changed_total}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Rol matrisi sıfırlanırken hata oluştu.", "danger")
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id, section="communication-role-policy") if keep_user_id else url_for("main.settings_page", section="communication-role-policy"))


def _handle_save_assistant_role_matrix():
    try:
        selected_count = save_assistant_role_matrix_from_form(request.form, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"Sanal Asistan rol matrisi kaydedildi. Açık rol sayısı: {selected_count}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Sanal Asistan rol matrisi kaydedilirken hata oluştu.", "danger")
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id, section="assistant-role-policy") if keep_user_id else url_for("main.settings_page", section="assistant-role-policy"))


def _handle_reset_assistant_role_matrix():
    try:
        selected_count = reset_assistant_role_matrix_defaults(updated_by_user_id=getattr(current_user, "id", None))
        flash(f"Sanal Asistan rol matrisi önerilen politikaya döndürüldü. Açık rol sayısı: {selected_count}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Sanal Asistan rol matrisi sıfırlanırken hata oluştu.", "danger")
    keep_user_id = request.form.get("keep_user_id", type=int)
    return redirect(url_for("main.settings_page", user_id=keep_user_id, section="assistant-role-policy") if keep_user_id else url_for("main.settings_page", section="assistant-role-policy"))


def _handle_rollback_settings_change_entry():
    log_id = request.form.get("change_log_id", type=int)
    keep_user_id = request.form.get("keep_user_id", type=int)
    if log_id is None:
        flash("Geri alınacak ayar değişikliği kaydı belirtilmedi.", "danger")
    else:
        try:
            result = rollback_settings_change(log_id, actor_user_id=getattr(current_user, "id", None))
            flash(result.get("summary") or "Ayar değişikliği geri alındı.", "success")
        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Ayar geçmişi geri alınırken hata oluştu.", "danger")
    return redirect(url_for("main.settings_page", user_id=keep_user_id) if keep_user_id else url_for("main.settings_page"))


def _handle_bulk_apply_profile(users, grouped_menu_definitions, flat_menu_items):
    profile_key = (request.form.get("bulk_profile_key") or "").strip()
    scope_type = (request.form.get("bulk_scope_type") or "role").strip()
    scope_role = (request.form.get("bulk_role") or "").strip()
    scope_birim = (request.form.get("bulk_birim") or "").strip()
    keep_user_id = request.form.get("keep_user_id", type=int)

    target_users = [user for user in users if getattr(user, "is_active", True)]
    if scope_type == "role" and scope_role:
        target_users = [user for user in target_users if (user.role or "").strip() == scope_role]
    elif scope_type == "birim" and scope_birim:
        target_users = [user for user in target_users if (user.birim or "").strip() == scope_birim]
    elif scope_type == "role_and_birim":
        if scope_role:
            target_users = [user for user in target_users if (user.role or "").strip() == scope_role]
        if scope_birim:
            target_users = [user for user in target_users if (user.birim or "").strip() == scope_birim]

    if not profile_key:
        flash("Toplu uygulama için bir profil seçiniz.", "warning")
        return redirect(url_for("main.settings_page", user_id=keep_user_id) if keep_user_id else url_for("main.settings_page"))
    if not target_users:
        flash("Seçilen kapsamda güncellenecek kullanıcı bulunamadı.", "warning")
        return redirect(url_for("main.settings_page", user_id=keep_user_id) if keep_user_id else url_for("main.settings_page"))

    try:
        for user in target_users:
            visible_keys = set(_resolve_bulk_profile_keys(profile_key, user, grouped_menu_definitions))
            _apply_visibility_keys_to_user(user, flat_menu_items, visible_keys)
        db.session.commit()
        bulk_summary = _build_bulk_result_summary(profile_key, scope_type, scope_role, scope_birim, target_users, grouped_menu_definitions)
        flash(f"{len(target_users)} kullanıcı için profil uygulandı.", "success")
        redirect_kwargs = {
            "last_bulk_profile": bulk_summary["profile_key"],
            "last_bulk_scope": bulk_summary["scope_type"],
            "last_bulk_role": bulk_summary["scope_role"],
            "last_bulk_birim": bulk_summary["scope_birim"],
            "last_bulk_count": bulk_summary["target_count"],
            "last_bulk_detail": bulk_summary["scope_detail"],
            "last_bulk_preview": "||".join([row["name"] for row in bulk_summary["preview_users"]]),
        }
        if keep_user_id:
            redirect_kwargs["user_id"] = keep_user_id
        return redirect(url_for("main.settings_page", **redirect_kwargs))
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Toplu profil uygulanırken hata oluştu.", "danger")
        return redirect(url_for("main.settings_page", user_id=keep_user_id) if keep_user_id else url_for("main.settings_page"))


def _handle_export_visibility_template(flat_menu_items):
    export_user_id = request.form.get("user_id", type=int)
    export_user = db.session.get(User, export_user_id)
    if not export_user:
        flash("Dışa aktarma için kullanıcı seçiniz.", "warning")
        return redirect(url_for("main.settings_page"))
    export_ctx = build_effective_user_menu_context(export_user, flat_menu_items)
    payload = _build_visibility_template_payload(export_user, flat_menu_items, export_ctx)
    buffer = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    safe_name = f"{(getattr(export_user, 'ad', '') + '_' + getattr(export_user, 'soyad', '')).strip('_') or 'kullanici'}"
    safe_name = safe_name.replace(' ', '_')
    return send_file(buffer, mimetype="application/json", as_attachment=True, download_name=f"bys360_yetki_sablonu_{safe_name}.json")


def _handle_import_visibility_template(flat_menu_items):
    import_user_id = request.form.get("user_id", type=int)
    import_user = db.session.get(User, import_user_id)
    if not import_user:
        flash("İçe aktarma için kullanıcı seçiniz.", "warning")
        return redirect(url_for("main.settings_page"))
    raw_payload = (request.form.get("import_template_json") or "").strip()
    upload = request.files.get("import_template_file")
    if not raw_payload and upload and upload.filename:
        raw_payload = upload.read().decode("utf-8", errors="ignore").strip()
    if not raw_payload:
        flash("İçe aktarmak için JSON metni veya dosyası seçiniz.", "warning")
        return redirect(url_for("main.settings_page", user_id=import_user.id))
    try:
        payload = json.loads(raw_payload)
        visible_keys = _extract_visible_keys_from_template_payload(payload, flat_menu_items)
        if not visible_keys and not isinstance(payload.get("effective_rule_map"), dict):
            raise ValueError("Şablonda görünür menü anahtarları bulunamadı.")
        result = save_user_menu_overrides(import_user, flat_menu_items, visible_keys, updated_by_user_id=getattr(current_user, "id", None))
        flash(f"Yetki şablonu içe aktarıldı. Aktif override: {result['override_count']}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Yetki şablonu içe aktarılırken hata oluştu.", "danger")
    return redirect(url_for("main.settings_page", user_id=import_user.id))


def _handle_save_named_archive(flat_menu_items):
    selected_user_id = request.form.get("user_id", type=int)
    selected_user = db.session.get(User, selected_user_id)
    if not selected_user:
        flash("Şablon arşivi kaydetmek için kullanıcı seçiniz.", "warning")
        return redirect(url_for("main.settings_page"))
    archive_name = (request.form.get("archive_name") or "").strip()
    archive_scope = (request.form.get("archive_scope") or "general").strip()
    archive_description = (request.form.get("archive_description") or "").strip()
    archive_role_target = (request.form.get("archive_role_target") or getattr(selected_user, "role", "") or "").strip()
    archive_birim_target = (request.form.get("archive_birim_target") or getattr(selected_user, "birim", "") or "").strip()
    visible_keys = _collect_form_visible_keys(request.form, flat_menu_items)
    try:
        result = _save_settings_template_archive(
            archive_name,
            archive_scope,
            visible_keys,
            flat_menu_items,
            description=archive_description,
            target_role=archive_role_target,
            target_birim=archive_birim_target,
            source_user=selected_user,
            updated_by_user_id=getattr(current_user, "id", None),
        )
        db.session.commit()
        flash(f"Şablon arşivi kaydedildi: {result['archive_name']} · Açık sekme: {result['visible_count']}", "success")
        archive_redirect_key = result["setting_key"]
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        archive_redirect_key = (request.form.get('archive_key') or "").strip()
        flash("Şablon arşivi kaydedilirken hata oluştu.", "danger")
    return redirect(url_for("main.settings_page", user_id=selected_user.id, archive_key=archive_redirect_key))


def _handle_apply_named_archive(all_menu_keys, flat_menu_items):
    selected_user_id = request.form.get("user_id", type=int)
    selected_user = db.session.get(User, selected_user_id)
    archive_key = (request.form.get("archive_key") or "").strip()
    archive = _get_settings_template_archive(archive_key, flat_menu_items)
    if not archive:
        flash("Uygulanacak arşiv seçilemedi.", "warning")
        return redirect(url_for("main.settings_page", user_id=selected_user_id) if selected_user_id else url_for("main.settings_page"))
    apply_mode = (request.form.get("archive_apply_mode") or "user_override").strip()
    target_role = (request.form.get("archive_apply_role") or archive.get("target_role") or getattr(selected_user, "role", "") or "").strip()
    target_birim = (request.form.get("archive_apply_birim") or archive.get("target_birim") or getattr(selected_user, "birim", "") or "").strip()
    visible_keys = set(archive.get("visible_keys") or [])
    try:
        if apply_mode == "role_profile":
            if not target_role:
                raise ValueError("Rol profiline uygulamak için rol seçiniz.")
            changed = save_role_menu_defaults(target_role, all_menu_keys, visible_keys, updated_by_user_id=getattr(current_user, "id", None))
            flash(f"Arşiv rol profiline uygulandı: {target_role} · İşlenen satır: {changed}", "success")
        elif apply_mode == "unit_profile":
            if not target_birim:
                raise ValueError("Birim profiline uygulamak için birim seçiniz.")
            changed = save_unit_menu_profile(target_birim, all_menu_keys, visible_keys, updated_by_user_id=getattr(current_user, "id", None))
            flash(f"Arşiv birim profiline uygulandı: {target_birim} · İşlenen satır: {changed}", "success")
        else:
            if not selected_user:
                raise ValueError("Personel bazlı rol matrisi için önce personel seçiniz.")
            result = save_user_menu_overrides(selected_user, flat_menu_items, visible_keys, updated_by_user_id=getattr(current_user, "id", None))
            flash(f"Arşiv seçili personele uygulandı. Kişiye özel sekme kaydı: {result['override_count']}", "success")
        db.session.commit()
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Arşiv uygulanırken hata oluştu.", "danger")
    return redirect(url_for("main.settings_page", user_id=selected_user.id if selected_user else None, archive_key=archive_key) if selected_user else url_for("main.settings_page", archive_key=archive_key))


def _handle_delete_named_archive():
    selected_user_id = request.form.get("user_id", type=int)
    archive_key = (request.form.get("archive_key") or "").strip()
    try:
        result = _delete_settings_template_archive(archive_key)
        db.session.commit()
        flash(f"Şablon arşivi silindi: {result['archive_name']}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Şablon arşivi silinirken hata oluştu.", "danger")
    return redirect(url_for("main.settings_page", user_id=selected_user_id) if selected_user_id else url_for("main.settings_page"))


def _handle_user_scoped_profile_action(form_action, flat_menu_items, all_menu_keys):
    selected_user_id = request.form.get("user_id", type=int)
    selected_user = db.session.get(User, selected_user_id)
    if not selected_user:
        flash("Personel seçiniz.", "warning")
        return redirect(url_for("main.settings_page"))

    visible_keys = _collect_form_visible_keys(request.form, flat_menu_items)
    keep_user_id = selected_user.id
    try:
        if form_action == "save_role_profile":
            target_role = (request.form.get("profile_role_target") or selected_user.role or "").strip()
            changed = save_role_menu_defaults(target_role, all_menu_keys, visible_keys, updated_by_user_id=getattr(current_user, "id", None))
            flash(f"{target_role or '-'} rol profili güncellendi. İşlenen satır: {changed}", "success")
        elif form_action == "save_unit_profile":
            target_unit = (request.form.get("profile_unit_target") or selected_user.birim or "").strip()
            changed = save_unit_menu_profile(target_unit, all_menu_keys, visible_keys, updated_by_user_id=getattr(current_user, "id", None))
            flash(f"{target_unit or '-'} birim profili güncellendi. İşlenen satır: {changed}", "success")
        elif form_action == "reset_user_overrides":
            deleted = clear_user_menu_overrides(
                selected_user.id,
                updated_by_user_id=getattr(current_user, "id", None),
                allow_personnel_read_grant_change=_can_change_personnel_read_grant(current_user, selected_user),
            )
            flash(f"{selected_user.ad} {selected_user.soyad} için personel bazlı rol matrisi temizlendi. Kaldırılan sekme kaydı: {deleted}", "success")
        else:
            actor_id = getattr(current_user, "id", None)
            # B1-F1: only an explicit per-user save by an admin for ANOTHER user may change
            # personnel_read_all; every other save leaves the existing grant as it is.
            grant_change_allowed = form_action == "save_user_visibility" and _can_change_personnel_read_grant(current_user, selected_user)
            if not grant_change_allowed and PERSONNEL_READ_ALL_KEY in visible_keys and not has_personnel_read_all_grant(selected_user):
                flash("Kurum geneli personel rehberi okuma yetkisi değiştirilmedi: bu yetkiyi yalnız admin rolü, başka bir personel için atayabilir veya kaldırabilir.", "warning")
            result = save_user_menu_overrides(
                selected_user,
                flat_menu_items,
                visible_keys,
                updated_by_user_id=actor_id,
                allow_personnel_read_grant_change=grant_change_allowed,
            )
            flash(
                f"{selected_user.ad} {selected_user.soyad} için kişi bazlı sekme ayarları kaydedildi. Bu personelin menüsü artık ekrandaki işaretlere göre çalışır. Kaydedilen sekme: {result['override_count']}",
                "success",
            )
        return redirect(url_for("main.settings_page", user_id=keep_user_id))
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Ayarlar kaydedilirken hata oluştu.", "danger")
        return redirect(url_for("main.settings_page", user_id=keep_user_id))


def account():
    return safe_render(
        "account.html",
        "<h3>Hesabım</h3>",
        user=current_user,
        security_questions=SECURITY_QUESTION_CHOICES,
    )

__all__ = [
    "annotations",
    "utc_now",
    "datetime",
    "io",
    "json",
    "re",
    "flash",
    "redirect",
    "request",
    "send_file",
    "url_for",
    "current_user",
    "db",
    "flatten_settings_menu_definitions",
    "get_grouped_menu_definitions",
    "SECURITY_QUESTION_CHOICES",
    "SystemSetting",
    "User",
    "UserMenuPermission",
    "safe_render",
    "_delete_profile_photo_file",
    "_save_profile_photo",
    "build_effective_user_menu_context",
    "build_settings_foundation_context",
    "build_settings_profile_context",
    "build_settings_ui_diagnostics_panel",
    "clear_user_menu_overrides",
    "ensure_settings_phase1_seeded",
    "get_role_default_menu_keys",
    "get_unit_profile_menu_keys",
    "save_module_settings_from_form",
    "save_role_menu_defaults",
    "save_system_settings_from_form",
    "save_unit_menu_profile",
    "save_user_menu_overrides",
    "rollback_settings_change",
    "enforce_first_login_security_flow_redirect",
    "logging",
    "logger",
    "COMMUNICATION_POLICY_ROLE_OPTIONS",
    "_build_communication_policy_items",
    "_build_communication_role_matrix",
    "SUPPORT_HELP_ROLE_MATRIX_ITEMS",
    "PERFORMANCE_ROLE_MATRIX_V12_ITEMS",
    "ASSISTANT_ROLE_MATRIX_ITEMS",
    "ASSISTANT_ROLE_MATRIX_KEYS",
    "ASSISTANT_ROLE_MATRIX_RECOMMENDED",
    "ROLE_MATRIX_POLICY_CONFIGS",
    "get_assistant_role_matrix_recommended_keys",
    "_role_matrix_policy_config_map",
    "_find_menu_item_by_key",
    "_build_role_matrix_group",
    "_build_settings_role_matrix_groups",
    "_get_role_matrix_policy_items_or_raise",
    "_role_matrix_form_field_name",
    "_collect_role_matrix_visible_keys_from_form",
    "enforce_first_login_security_flow",
    "PERSONNEL_ROLE_MATRIX_CURRENT_SCOPE_ITEMS",
    "_PERSONNEL_ROLE_MATRIX_CURRENT_SCOPE_KEYS",
    "_BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_FOR_ASSISTANT",
    "_BYS360_BASE_ROLE_MATRIX_POLICY_CONFIGS",
    "_BYS360_PERSONNEL_POLICY_CONFIG",
    "_BYS360_PREVIOUS_BUILD_ROLE_MATRIX_POLICY_ITEMS",
    "_build_role_matrix_policy_items",
    "_BYS360_ALL_MENU_ROLE_MATRIX_ITEMS",
    "_BYS360_ALL_MENU_ROLE_MATRIX_ITEM_BY_KEY",
    "_BYS360_ASSISTANT_TAB_ROLE_MATRIX_ITEMS",
    "_BYS360_ASSISTANT_TAB_RECOMMENDED",
    "_BYS360_PERFORMANCE_MAIN_SWITCH_ITEM",
    "_bys360_clean_general_role_matrix_performance_text_v5",
    "_BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_ALL_FEATURES_V1",
    "_bys360_role_matrix_all_feature_items_v1",
    "PORTAL_ROLE_MATRIX_V2_12_ITEMS",
    "_PORTAL_ROLE_MATRIX_V2_12_CONFIG",
    "_BYS360_PERFORMANCE_PERIOD_CENTER_POLICY_ITEMS_V2_1_23B",
    "_bys360_merge_performance_period_center_policy_items_v2_1_23b",
    "_BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_V2_1_23B",
    "extend_flat_menu_items_with_assistant_role_matrix_items",
    "_build_settings_matrix",
    "_build_settings_presets",
    "_collect_all_menu_keys",
    "_build_bulk_settings_profiles",
    "_serialize_bulk_target_users",
    "_find_bulk_profile",
    "_build_bulk_result_summary",
    "_resolve_bulk_result_summary_from_args",
    "_resolve_bulk_profile_keys",
    "_apply_visibility_keys_to_user",
    "_collect_form_visible_keys",
    "SETTINGS_ARCHIVE_GROUP_KEY",
    "SETTINGS_ARCHIVE_KEY_PREFIX",
    "_slugify_archive_name",
    "_build_settings_archive_setting_key",
    "_normalize_visible_keys",
    "_list_settings_template_archives",
    "_save_settings_template_archive",
    "_get_settings_template_archive",
    "_delete_settings_template_archive",
    "_build_visibility_template_payload",
    "_extract_visible_keys_from_template_payload",
    "_build_user_visibility_diff",
    "_bys360_pf_v14_dedupe_flat_menu_items",
    "_bys360_personnel_feature_matrix_v14_dedupe_items",
    "_bys360_personnel_feature_matrix_v14_dedupe_grouped_menu",
    "settings_page",
    "account",
]
