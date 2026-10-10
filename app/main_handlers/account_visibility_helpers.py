from __future__ import annotations

from app.main_handlers.account_communication_helpers import (
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
    SUPPORT_HELP_ROLE_MATRIX_ITEMS,
    SystemSetting,
    User,
    UserMenuPermission,
    _build_communication_policy_items,
    _build_communication_role_matrix,
    _build_role_matrix_group,
    _build_role_matrix_policy_items,
    _build_settings_role_matrix_groups,
    _bys360_clean_general_role_matrix_performance_text_v5,
    _bys360_merge_performance_period_center_policy_items_v2_1_23b,
    _bys360_role_matrix_all_feature_items_v1,
    _collect_role_matrix_visible_keys_from_form,
    _delete_profile_photo_file,
    _find_menu_item_by_key,
    _get_role_matrix_policy_items_or_raise,
    _role_matrix_form_field_name,
    _role_matrix_policy_config_map,
    _save_profile_photo,
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
from app.services.personnel_read_grant import EXPLICIT_GRANT_KEYS


def _build_settings_matrix(grouped_menu_definitions, selected_rule_map: dict[str, bool], role_defaults: set[str], *, selected_user=None, users=None):
    matrix_rows = []
    open_total = 0
    default_total = 0
    custom_open = []
    custom_closed = []
    preview_groups = []
    fully_visible_groups = 0
    partially_visible_groups = 0
    fully_hidden_groups = 0

    for group_name, items in grouped_menu_definitions.items():
        total = len(items)
        default_open = 0
        current_open = 0
        overridden = 0
        visible_labels = []
        hidden_labels = []
        for item in items:
            key = item["key"] if isinstance(item, dict) else item.key
            label = item["label"] if isinstance(item, dict) else item.label
            is_default = key in role_defaults
            is_open = bool(selected_rule_map.get(key, False))
            if is_default:
                default_open += 1
                default_total += 1
            if is_open:
                current_open += 1
                open_total += 1
                visible_labels.append(label)
            else:
                hidden_labels.append(label)
            if is_open != is_default:
                overridden += 1
                if is_open:
                    custom_open.append(key)
                else:
                    custom_closed.append(key)

        closed_count = max(total - current_open, 0)
        open_ratio = round((current_open / total) * 100, 1) if total else 0
        default_ratio = round((default_open / total) * 100, 1) if total else 0
        visibility_state = "partial"
        if current_open == 0:
            visibility_state = "hidden"
            fully_hidden_groups += 1
        elif current_open == total:
            visibility_state = "full"
            fully_visible_groups += 1
        else:
            partially_visible_groups += 1

        row = {
            "group_name": group_name,
            "total": total,
            "default_open": default_open,
            "current_open": current_open,
            "closed_count": closed_count,
            "override_count": overridden,
            "open_ratio": open_ratio,
            "default_ratio": default_ratio,
            "visibility_state": visibility_state,
            "visible_labels": visible_labels,
            "hidden_labels": hidden_labels,
        }
        matrix_rows.append(row)
        preview_groups.append({
            "group_name": group_name,
            "visible_labels": visible_labels,
            "hidden_count": closed_count,
            "visible_count": current_open,
            "visibility_state": visibility_state,
        })

    role_peer_count = 0
    unit_peer_count = 0
    same_role_same_unit_count = 0
    if selected_user and users:
        selected_role = (selected_user.role or "").strip().lower()
        selected_unit = (selected_user.birim or "").strip().lower()
        for user in users:
            if user.id == selected_user.id:
                continue
            if ((user.role or "").strip().lower() == selected_role):
                role_peer_count += 1
            if selected_unit and ((user.birim or "").strip().lower() == selected_unit):
                unit_peer_count += 1
                if ((user.role or "").strip().lower() == selected_role):
                    same_role_same_unit_count += 1

    override_total = len(custom_open) + len(custom_closed)
    role_alignment_ratio = round(((default_total - len(custom_closed) + len([key for key in custom_open if key not in role_defaults])) / default_total) * 100, 1) if default_total else 100
    return {
        "matrix_rows": matrix_rows,
        "preview_groups": preview_groups,
        "open_total": open_total,
        "default_total": default_total,
        "closed_total": max(sum(row["total"] for row in matrix_rows) - open_total, 0),
        "custom_open": custom_open,
        "custom_closed": custom_closed,
        "override_total": override_total,
        "role_alignment_ratio": max(min(role_alignment_ratio, 100), 0),
        "custom_preview": custom_open[:6] + custom_closed[:6],
        "role_peer_count": role_peer_count,
        "unit_peer_count": unit_peer_count,
        "same_role_same_unit_count": same_role_same_unit_count,
        "fully_visible_groups": fully_visible_groups,
        "partially_visible_groups": partially_visible_groups,
        "fully_hidden_groups": fully_hidden_groups,
    }

def _build_settings_presets(grouped_menu_definitions, role_defaults: set[str]):
    group_key_map: dict[str, list[str]] = {}
    for group_name, items in grouped_menu_definitions.items():
        group_key_map[group_name] = [item["key"] if isinstance(item, dict) else item.key for item in items]

    common_support = set()
    for label in ("Genel", "Personel Yönetimi", "İletişim ve Anket Yönetimi", "AI Karar Destek Merkezi", "Karar Destek Merkezi", "Kullanıcı"):
        common_support.update(group_key_map.get(label, []))

    presets = [
        {
            "key": "role_defaults",
            "label": "Rol Varsayılanı",
            "description": "Sistemin seçili rol için önerdiği doğal menü yapısına geri döner.",
            "mode": "only",
            "icon": "fa-solid fa-rotate-left",
            "keys": sorted(role_defaults),
        },
        {
            "key": "full_access",
            "label": "Tam Erişim",
            "description": "Tüm modülleri ve tüm sekmeleri görünür yapar.",
            "mode": "only",
            "icon": "fa-solid fa-check-double",
            "keys": sorted({key for keys in group_key_map.values() for key in keys}),
        },
        {
            "key": "performance_focus",
            "label": "Performans Seti",
            "description": "Performans yönetimi akışları ile temel ekranları birlikte açar.",
            "mode": "only",
            "icon": "fa-solid fa-chart-line",
            "keys": sorted(common_support | set(group_key_map.get("Performans Yönetimi", []))),
        },
        {
            "key": "live_scope",
            "label": "Canlı Omurga",
            "description": "Canlıya çıkan modülleri ve temel kişisel ekranları görünür yapar.",
            "mode": "only",
            "icon": "fa-solid fa-rocket",
            "keys": sorted({key for keys in group_key_map.values() for key in keys}),
        },
        {
            "key": "communication_focus",
            "label": "İletişim Seti",
            "description": "Mesajlar, bildirimler, duyurular ve anket akışlarını öne çıkarır.",
            "mode": "only",
            "icon": "fa-solid fa-comments",
            "keys": sorted(common_support | set(group_key_map.get("İletişim ve Anket Yönetimi", []))),
        },
    ]

    group_toggles = []
    for group_name, keys in group_key_map.items():
        if not keys:
            continue
        group_toggles.append({
            "group_name": group_name,
            "open_icon": "fa-solid fa-eye",
            "close_icon": "fa-solid fa-eye-slash",
            "keys": sorted(keys),
        })

    return {
        "presets": presets,
        "group_toggles": group_toggles,
    }

def _collect_all_menu_keys(grouped_menu_definitions):
    keys = []
    for items in grouped_menu_definitions.values():
        for item in items:
            keys.append(item["key"] if isinstance(item, dict) else item.key)
    return sorted(set(keys))


def _build_bulk_settings_profiles(grouped_menu_definitions):
    group_key_map: dict[str, list[str]] = {}
    for group_name, items in grouped_menu_definitions.items():
        group_key_map[group_name] = [item["key"] if isinstance(item, dict) else item.key for item in items]

    all_keys = _collect_all_menu_keys(grouped_menu_definitions)
    common_support = set()
    for label in ("Genel", "Personel Yönetimi", "İletişim ve Anket Yönetimi", "AI Karar Destek Merkezi", "Karar Destek Merkezi", "Kullanıcı"):
        common_support.update(group_key_map.get(label, []))

    def role_profile(key: str, label: str, icon: str):
        role_keys = sorted(get_role_default_menu_keys(key))
        return {
            "key": f"role::{key}",
            "label": label,
            "description": f"{label} için sistemde tanımlı rol varsayılanını uygular.",
            "icon": icon,
            "keys": role_keys,
            "estimated_count": len(role_keys),
        }

    profiles = [
        {
            "key": "dynamic::role_defaults",
            "label": "Rol Varsayılanı (Dinamik)",
            "description": "Seçili kapsamdaki herkes için kendi rol varsayılanını uygular.",
            "icon": "fa-solid fa-rotate-left",
            "keys": [],
            "estimated_count": 0,
        },
        {
            "key": "static::full_access",
            "label": "Tam Erişim",
            "description": "Seçili kapsamdaki herkes için tüm sekmeleri açar.",
            "icon": "fa-solid fa-check-double",
            "keys": all_keys,
            "estimated_count": len(all_keys),
        },
        {
            "key": "static::performance_focus",
            "label": "Performans Seti",
            "description": "Performans akışlarını ve temel destek ekranlarını açar.",
            "icon": "fa-solid fa-chart-line",
            "keys": sorted(common_support | set(group_key_map.get("Performans Yönetimi", []))),
            "estimated_count": len(common_support | set(group_key_map.get("Performans Yönetimi", []))),
        },
        {
            "key": "static::live_scope",
            "label": "Canlı Omurga",
            "description": "Canlıya çıkan modülleri ve temel kişisel ekranları açar.",
            "icon": "fa-solid fa-rocket",
            "keys": all_keys,
            "estimated_count": len(all_keys),
        },
        role_profile("admin", "Admin", "fa-solid fa-user-shield"),
        role_profile("baskan", "Başkan", "fa-solid fa-landmark"),
        role_profile("baskan_yardimcisi", "Başkan Yardımcısı", "fa-solid fa-user-tie"),
        role_profile("grup_baskani", "Grup Başkanı", "fa-solid fa-sitemap"),
        role_profile("mali_musavir", "Mali Müşavir", "fa-solid fa-scale-balanced"),
        role_profile("birim_sorumlusu", "Birim Sorumlusu", "fa-solid fa-diagram-project"),
        role_profile("koordinator", "Koordinatör", "fa-solid fa-people-arrows"),
        role_profile("personel", "Personel", "fa-solid fa-id-badge"),
    ]

    profile_context = build_settings_profile_context()
    for row in profile_context.get("unit_profiles_snapshot", []):
        unit_name = (row.get("unit_name") or "").strip()
        if not unit_name:
            continue
        profiles.append({
            "key": f"unit::{unit_name}",
            "label": f"Birim Profili · {unit_name}",
            "description": "Kaydedilmiş birim profilini toplu uygulama için kullanır.",
            "icon": "fa-solid fa-sitemap",
            "keys": sorted(get_unit_profile_menu_keys(unit_name)),
            "estimated_count": int(row.get("visible_count") or 0),
        })
    return profiles


def _serialize_bulk_target_users(users):
    rows = []
    for user in users:
        rows.append({
            "id": getattr(user, "id", None),
            "name": f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip(),
            "role": (getattr(user, "role", "") or "").strip(),
            "birim": (getattr(user, "birim", "") or "").strip(),
            "unit": (getattr(user, "birim", "") or "").strip(),
            "sicil_no": (getattr(user, "sicil_no", "") or "").strip(),
            "unvan": (getattr(user, "unvan", "") or "").strip(),
            "active": bool(getattr(user, "is_active", True)),
        })
    return rows


def _find_bulk_profile(profile_key: str, grouped_menu_definitions):
    for profile in _build_bulk_settings_profiles(grouped_menu_definitions):
        if profile.get("key") == profile_key:
            return profile
    return None


def _build_bulk_result_summary(profile_key: str, scope_type: str, scope_role: str, scope_birim: str, target_users, grouped_menu_definitions):
    profile = _find_bulk_profile(profile_key, grouped_menu_definitions)
    profile_label = profile.get("label") if profile else "Özel Profil"
    scope_label = {
        "role": "Rol Bazlı",
        "birim": "Birim Bazlı",
        "role_and_birim": "Rol + Birim",
    }.get(scope_type, "Özel Kapsam")
    if scope_type == "role" and scope_role:
        scope_detail = scope_role
    elif scope_type == "birim" and scope_birim:
        scope_detail = scope_birim
    elif scope_type == "role_and_birim":
        parts = [part for part in [scope_role, scope_birim] if part]
        scope_detail = " / ".join(parts) if parts else "Tüm kullanıcılar"
    else:
        scope_detail = "Tüm kullanıcılar"

    preview_users = []
    for user in target_users[:5]:
        preview_users.append({
            "name": f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip(),
            "role": (getattr(user, "role", "") or "").strip(),
            "birim": (getattr(user, "birim", "") or "").strip(),
        })

    return {
        "profile_key": profile_key or "",
        "profile_label": profile_label,
        "scope_type": scope_type or "",
        "scope_label": scope_label,
        "scope_role": scope_role or "",
        "scope_birim": scope_birim or "",
        "scope_detail": scope_detail,
        "target_count": len(target_users),
        "preview_users": preview_users,
    }


def _resolve_bulk_result_summary_from_args(args, grouped_menu_definitions):
    profile_key = (args.get("last_bulk_profile") or "").strip()
    if not profile_key:
        return None

    preview_names = []
    preview_raw = (args.get("last_bulk_preview") or "").strip()
    if preview_raw:
        preview_names = [part.strip() for part in preview_raw.split("||") if part.strip()]

    return {
        "profile_key": profile_key,
        "profile_label": (_find_bulk_profile(profile_key, grouped_menu_definitions) or {}).get("label", "Özel Profil"),
        "scope_type": (args.get("last_bulk_scope") or "").strip(),
        "scope_label": {
            "role": "Rol Bazlı",
            "birim": "Birim Bazlı",
            "role_and_birim": "Rol + Birim",
        }.get((args.get("last_bulk_scope") or "").strip(), "Özel Kapsam"),
        "scope_role": (args.get("last_bulk_role") or "").strip(),
        "scope_birim": (args.get("last_bulk_birim") or "").strip(),
        "scope_detail": (args.get("last_bulk_detail") or "Tüm kullanıcılar").strip(),
        "target_count": int(args.get("last_bulk_count") or 0),
        "preview_names": preview_names,
    }


def _resolve_bulk_profile_keys(profile_key: str, user, grouped_menu_definitions):
    profile_key = (profile_key or "").strip()
    if not profile_key:
        return []
    if profile_key == "dynamic::role_defaults":
        return sorted(get_role_default_menu_keys(getattr(user, "role", "")))
    if profile_key.startswith("unit::"):
        return sorted(get_unit_profile_menu_keys(profile_key.split("::", 1)[1]))
    for profile in _build_bulk_settings_profiles(grouped_menu_definitions):
        if profile["key"] == profile_key:
            return list(profile.get("keys") or [])
    return []


SETTINGS_ARCHIVE_GROUP_KEY = "settings_template_archive"
SETTINGS_ARCHIVE_KEY_PREFIX = "settings_archive::"


def _slugify_archive_name(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9çğıöşü_-]+", "-", value, flags=re.IGNORECASE)
    value = value.strip("-")
    return value or utc_now().strftime("%Y%m%d%H%M%S")


def _build_settings_archive_setting_key(scope_type: str, archive_name: str) -> str:
    scope = (scope_type or "general").strip().lower() or "general"
    return f"{SETTINGS_ARCHIVE_KEY_PREFIX}{scope}::{_slugify_archive_name(archive_name)}"


def _normalize_visible_keys(visible_keys, flat_menu_items) -> list[str]:
    allowed = {item["key"] for item in flat_menu_items}
    return sorted({str(key).strip() for key in (visible_keys or []) if str(key).strip() in allowed})


def _list_settings_template_archives(flat_menu_items) -> list[dict]:
    rows = (
        SystemSetting.query
        .filter(SystemSetting.group_key == SETTINGS_ARCHIVE_GROUP_KEY, SystemSetting.is_active.is_(True))
        .order_by(SystemSetting.label.asc(), SystemSetting.id.asc())
        .all()
    )
    archives = []
    label_map = {item["key"]: item.get("label", item["key"]) for item in flat_menu_items}
    for row in rows:
        payload = {}
        try:
            payload = json.loads(row.value_text or "{}")
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/main_handlers/account_visibility_helpers.py:432")
            payload = {}
        visible_keys = _normalize_visible_keys(payload.get("visible_keys") or [], flat_menu_items)
        if not visible_keys and isinstance(payload.get("effective_rule_map"), dict):
            visible_keys = sorted({key for key, visible in payload.get("effective_rule_map", {}).items() if visible and key in label_map})
        preview_labels = [label_map.get(key, "Bilinmiyor") for key in visible_keys[:4]]
        archives.append({
            "setting_key": row.setting_key,
            "archive_name": payload.get("archive_name") or row.label,
            "archive_scope": (payload.get("archive_scope") or "general").strip() or "general",
            "target_role": (payload.get("target_role") or "").strip(),
            "target_birim": (payload.get("target_birim") or "").strip(),
            "description": payload.get("description") or row.description or "",
            "visible_keys": visible_keys,
            "visible_count": len(visible_keys),
            "preview_labels": preview_labels,
            "updated_at": getattr(row, "updated_at", None),
            "source_user_name": ((payload.get("source_user") or {}).get("name") or "").strip(),
        })
    return archives


def _save_settings_template_archive(
    archive_name: str,
    archive_scope: str,
    visible_keys: set[str],
    flat_menu_items,
    *,
    description: str = "",
    target_role: str = "",
    target_birim: str = "",
    source_user=None,
    updated_by_user_id: int | None = None,
) -> dict:
    archive_name = (archive_name or "").strip()
    if not archive_name:
        raise ValueError("Arşiv adı zorunludur.")

    setting_key = _build_settings_archive_setting_key(archive_scope, archive_name)
    visible_key_list = _normalize_visible_keys(visible_keys, flat_menu_items)
    label_map = {item["key"]: item.get("label", item["key"]) for item in flat_menu_items}
    row = SystemSetting.query.filter_by(setting_key=setting_key).first()
    created = row is None
    payload = {
        "template_version": "1.0",
        "template_type": "settings_template_archive",
        "archive_name": archive_name,
        "archive_scope": (archive_scope or "general").strip() or "general",
        "description": (description or "").strip(),
        "target_role": (target_role or "").strip(),
        "target_birim": (target_birim or "").strip(),
        "visible_keys": visible_key_list,
        "labels": {key: label_map.get(key, "Bilinmiyor") for key in visible_key_list},
        "source_user": {
            "id": getattr(source_user, "id", None),
            "sicil_no": getattr(source_user, "sicil_no", None),
            "name": f"{getattr(source_user, 'ad', '')} {getattr(source_user, 'soyad', '')}".strip(),
            "role": getattr(source_user, "role", None),
            "birim": getattr(source_user, "birim", None),
        },
        "saved_at": utc_now().isoformat() + "Z",
    }
    if row is None:
        row = SystemSetting(
            setting_key=setting_key,
            group_key=SETTINGS_ARCHIVE_GROUP_KEY,
            label=archive_name,
            value_type="json",
            is_active=True,
        )
        db.session.add(row)
    row.label = archive_name
    row.group_key = SETTINGS_ARCHIVE_GROUP_KEY
    row.value_type = "json"
    row.value_text = json.dumps(payload, ensure_ascii=False, indent=2)
    row.description = (description or "").strip() or "Kayıtlı ayar şablonu arşivi"
    row.is_active = True
    row.updated_by_user_id = updated_by_user_id
    db.session.flush()
    return {
        "created": created,
        "setting_key": row.setting_key,
        "archive_name": archive_name,
        "visible_count": len(visible_key_list),
    }


def _get_settings_template_archive(setting_key: str, flat_menu_items) -> dict | None:
    setting_key = (setting_key or "").strip()
    if not setting_key:
        return None
    row = SystemSetting.query.filter_by(setting_key=setting_key, group_key=SETTINGS_ARCHIVE_GROUP_KEY).first()
    if not row:
        return None
    payload = {}
    try:
        payload = json.loads(row.value_text or "{}")
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/main_handlers/account_visibility_helpers.py:529")
        payload = {}
    visible_keys = _normalize_visible_keys(payload.get("visible_keys") or [], flat_menu_items)
    return {
        "row": row,
        "setting_key": row.setting_key,
        "archive_name": payload.get("archive_name") or row.label,
        "archive_scope": (payload.get("archive_scope") or "general").strip() or "general",
        "description": payload.get("description") or row.description or "",
        "target_role": (payload.get("target_role") or "").strip(),
        "target_birim": (payload.get("target_birim") or "").strip(),
        "visible_keys": visible_keys,
    }


def _delete_settings_template_archive(setting_key: str) -> dict:
    row = SystemSetting.query.filter_by(setting_key=setting_key, group_key=SETTINGS_ARCHIVE_GROUP_KEY).first()
    if not row:
        raise ValueError("Şablon arşivi bulunamadı.")
    archive_name = row.label
    db.session.delete(row)
    db.session.flush()
    return {"archive_name": archive_name}


def _build_visibility_template_payload(user, flat_menu_items, selected_profile_resolution: dict | None = None) -> dict:
    selected_profile_resolution = selected_profile_resolution or build_effective_user_menu_context(user, flat_menu_items)
    label_map = {item["key"]: item.get("label", item["key"]) for item in flat_menu_items}
    effective_rule_map = dict(selected_profile_resolution.get("effective_rule_map") or {})
    visible_keys = sorted([key for key, visible in effective_rule_map.items() if visible])
    return {
        "template_version": "1.0",
        "template_type": "user_menu_visibility",
        "exported_at": utc_now().isoformat() + "Z",
        "source_user": {
            "id": getattr(user, "id", None),
            "sicil_no": getattr(user, "sicil_no", None),
            "name": f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip(),
            "role": getattr(user, "role", None),
            "birim": getattr(user, "birim", None),
        },
        "visible_keys": visible_keys,
        "effective_rule_map": effective_rule_map,
        "labels": {key: label_map.get(key, "Bilinmiyor") for key in effective_rule_map},
    }


def _extract_visible_keys_from_template_payload(payload: dict, flat_menu_items) -> set[str]:
    allowed_keys = {item["key"] for item in flat_menu_items}
    visible_keys = payload.get("visible_keys") or []
    if isinstance(visible_keys, list):
        return {str(key).strip() for key in visible_keys if str(key).strip() in allowed_keys}
    effective_rule_map = payload.get("effective_rule_map") or {}
    if isinstance(effective_rule_map, dict):
        return {str(key).strip() for key, visible in effective_rule_map.items() if bool(visible) and str(key).strip() in allowed_keys}
    return set()


def _build_user_visibility_diff(selected_user, compare_user, flat_menu_items) -> dict | None:
    if not selected_user or not compare_user or getattr(selected_user, "id", None) == getattr(compare_user, "id", None):
        return None

    selected_ctx = build_effective_user_menu_context(selected_user, flat_menu_items)
    compare_ctx = build_effective_user_menu_context(compare_user, flat_menu_items)
    label_map = {item["key"]: item.get("label", item["key"]) for item in flat_menu_items}
    grouped_labels: dict[str, str] = {}
    for item in flat_menu_items:
        grouped_labels[item["key"]] = item.get("group_name") or item.get("section") or "Genel"

    rows = []
    selected_visible_total = 0
    compare_visible_total = 0
    for item in flat_menu_items:
        key = item["key"]
        selected_visible = bool((selected_ctx.get("effective_rule_map") or {}).get(key, False))
        compare_visible = bool((compare_ctx.get("effective_rule_map") or {}).get(key, False))
        if selected_visible:
            selected_visible_total += 1
        if compare_visible:
            compare_visible_total += 1
        if selected_visible == compare_visible:
            continue
        rows.append({
            "key": key,
            "label": label_map.get(key, "Bilinmiyor"),
            "group_name": grouped_labels.get(key, "Genel"),
            "selected_visible": selected_visible,
            "compare_visible": compare_visible,
            "selected_source": (selected_ctx.get("source_map") or {}).get(key, "role_default"),
            "compare_source": (compare_ctx.get("source_map") or {}).get(key, "role_default"),
        })

    rows.sort(key=lambda row: (row["group_name"].lower(), row["label"].lower()))
    return {
        "compare_user": compare_user,
        "selected_visible_total": selected_visible_total,
        "compare_visible_total": compare_visible_total,
        "difference_count": len(rows),
        "rows": rows,
    }

__all__ = [
    "annotations",
    "_BYS360_ALL_MENU_ROLE_MATRIX_ITEM_BY_KEY",
    "_BYS360_ALL_MENU_ROLE_MATRIX_ITEMS",
    "_BYS360_ASSISTANT_TAB_RECOMMENDED",
    "_BYS360_ASSISTANT_TAB_ROLE_MATRIX_ITEMS",
    "_BYS360_BASE_ROLE_MATRIX_POLICY_CONFIGS",
    "_BYS360_PERFORMANCE_MAIN_SWITCH_ITEM",
    "_BYS360_PERFORMANCE_PERIOD_CENTER_POLICY_ITEMS_V2_1_23B",
    "_BYS360_PERSONNEL_POLICY_CONFIG",
    "_BYS360_PREVIOUS_BUILD_ROLE_MATRIX_POLICY_ITEMS",
    "_BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_ALL_FEATURES_V1",
    "_BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_FOR_ASSISTANT",
    "_BYS360_PREVIOUS_EXTEND_FLAT_MENU_ITEMS_V2_1_23B",
    "_PERSONNEL_ROLE_MATRIX_CURRENT_SCOPE_KEYS",
    "_PORTAL_ROLE_MATRIX_V2_12_CONFIG",
    "ASSISTANT_ROLE_MATRIX_ITEMS",
    "ASSISTANT_ROLE_MATRIX_KEYS",
    "ASSISTANT_ROLE_MATRIX_RECOMMENDED",
    "COMMUNICATION_POLICY_ROLE_OPTIONS",
    "PERFORMANCE_ROLE_MATRIX_V12_ITEMS",
    "PERSONNEL_ROLE_MATRIX_CURRENT_SCOPE_ITEMS",
    "PORTAL_ROLE_MATRIX_V2_12_ITEMS",
    "ROLE_MATRIX_POLICY_CONFIGS",
    "SECURITY_QUESTION_CHOICES",
    "SUPPORT_HELP_ROLE_MATRIX_ITEMS",
    "SystemSetting",
    "User",
    "UserMenuPermission",
    "_build_communication_policy_items",
    "_build_communication_role_matrix",
    "_build_role_matrix_group",
    "_build_role_matrix_policy_items",
    "_build_settings_role_matrix_groups",
    "_bys360_clean_general_role_matrix_performance_text_v5",
    "_bys360_merge_performance_period_center_policy_items_v2_1_23b",
    "_bys360_role_matrix_all_feature_items_v1",
    "_collect_role_matrix_visible_keys_from_form",
    "_delete_profile_photo_file",
    "_find_menu_item_by_key",
    "_get_role_matrix_policy_items_or_raise",
    "_role_matrix_form_field_name",
    "_role_matrix_policy_config_map",
    "_save_profile_photo",
    "build_effective_user_menu_context",
    "build_settings_foundation_context",
    "build_settings_profile_context",
    "build_settings_ui_diagnostics_panel",
    "clear_user_menu_overrides",
    "current_user",
    "datetime",
    "db",
    "enforce_first_login_security_flow",
    "enforce_first_login_security_flow_redirect",
    "ensure_settings_phase1_seeded",
    "extend_flat_menu_items_with_assistant_role_matrix_items",
    "flash",
    "flatten_settings_menu_definitions",
    "get_assistant_role_matrix_recommended_keys",
    "get_grouped_menu_definitions",
    "get_role_default_menu_keys",
    "get_unit_profile_menu_keys",
    "io",
    "json",
    "logger",
    "logging",
    "re",
    "redirect",
    "request",
    "rollback_settings_change",
    "safe_render",
    "save_module_settings_from_form",
    "save_role_menu_defaults",
    "save_system_settings_from_form",
    "save_unit_menu_profile",
    "save_user_menu_overrides",
    "send_file",
    "url_for",
    "utc_now",
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
]
# BYS360_PERSONNEL_FEATURE_MATRIX_V1_4_VISIBILITY_HELPERS
def _bys360_pf_v14_dedupe_flat_menu_items(items):
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


def _collect_form_visible_keys(form, flat_menu_items):
    visible = set()
    for item in _bys360_pf_v14_dedupe_flat_menu_items(flat_menu_items):
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        values = form.getlist(f"menu_{key}") if hasattr(form, "getlist") else [form.get(f"menu_{key}")]
        if any(str(value).lower() in {"on", "true", "1", "yes"} for value in values):
            visible.add(key)
    return visible


def _apply_visibility_keys_to_user(user, flat_menu_items, visible_keys: set[str]):
    # B1-F1, K5-Q2: bulk profiles never write, prune or grant the per-user explicit grant rows
    # (personnel_read_all, support_all).
    UserMenuPermission.query.filter(
        UserMenuPermission.user_id == user.id,
        UserMenuPermission.menu_key.notin_(EXPLICIT_GRANT_KEYS),
    ).delete()
    allowed_items = _bys360_pf_v14_dedupe_flat_menu_items(flat_menu_items)
    visible_keys = {str(key).strip() for key in (visible_keys or set()) if str(key).strip()}
    for item in allowed_items:
        key = str(item.get("key") or "").strip()
        if not key or key in EXPLICIT_GRANT_KEYS:
            continue
        db.session.add(
            UserMenuPermission(
                user_id=user.id,
                menu_key=key,
                is_visible=key in visible_keys,
                source_type="user_override",
            )
        )

