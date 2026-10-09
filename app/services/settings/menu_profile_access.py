"""BYS360 rol/birim/kisi bazli menu yetki profili erisim katmani.

Settings Service Tamamlama Faz 3:
- user_menu_permissions, role_menu_defaults ve unit_menu_profiles akisini
  settings_service.py icinden dis modüle alir.
- Veritabani semasina dokunmaz.
- Commit, rollback ve change-log baglantilari cagiran servis tarafindan
  parametre olarak verilir; bu sayede canli davranis korunur.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any

logger = logging.getLogger(__name__)


def get_role_default_menu_keys_handler(
    *,
    role_name: str,
    prefer_database: bool,
    role_menu_default_model: Any,
    static_role_default_menu_keys_func: Callable[[str], Iterable[str]],
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    filter_live_menu_keys_func: Callable[[Iterable[Any]], list[str]],
    safe_rollback_func: Callable[[], None],
) -> set[str]:
    """Rolun gorunur menu anahtarlarini DB tercihli olarak dondurur."""
    normalized_role = (role_name or "").strip().lower()
    if prefer_database and normalized_role:
        try:
            rows = filter_live_menu_rows_func(
                role_menu_default_model.query.filter_by(role_name=normalized_role, is_visible=True).all()
            )
            if rows:
                return {row.menu_key for row in rows}
            any_rows = filter_live_menu_rows_func(
                role_menu_default_model.query.filter_by(role_name=normalized_role).all()
            )
            if any_rows:
                return set()
        except Exception:
            logger.exception("BYS360 V6B guarded exception | file=app/services/settings/menu_profile_access.py | line=43")
            safe_rollback_func()
    return set(filter_live_menu_keys_func(static_role_default_menu_keys_func(normalized_role)))


def build_role_default_snapshot_handler(
    *,
    role_menu_defaults: dict[str, Any],
    flatten_menu_definitions_func: Callable[[], list[dict[str, Any]]],
    get_role_default_menu_keys_func: Callable[[str], set[str]],
) -> list[dict[str, Any]]:
    """Rol bazli varsayilan menu gorunurluk ozetini uretir."""
    all_menu_count = max(len(flatten_menu_definitions_func()), 1)
    rows: list[dict[str, Any]] = []
    for role_name in sorted(role_menu_defaults.keys()):
        visible_keys = get_role_default_menu_keys_func(role_name)
        rows.append({
            "role_name": role_name,
            "visible_count": len(visible_keys),
            "total_count": all_menu_count,
            "coverage_ratio": round((len(visible_keys) / all_menu_count) * 100, 1),
        })
    return rows


def build_unit_profile_snapshot_handler(
    *,
    unit_menu_profile_model: Any,
    flatten_menu_definitions_func: Callable[[], list[dict[str, Any]]],
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    safe_rollback_func: Callable[[], None],
) -> list[dict[str, Any]]:
    """Birim profillerinin kapsama oranini yan etkisiz ozetler."""
    all_menu_count = max(len(flatten_menu_definitions_func()), 1)
    grouped: OrderedDict[str, list[Any]] = OrderedDict()
    try:
        rows = filter_live_menu_rows_func(
            unit_menu_profile_model.query.order_by(
                unit_menu_profile_model.unit_name.asc(),
                unit_menu_profile_model.menu_key.asc(),
            ).all()
        )
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/settings/menu_profile_access.py | line=85")
        safe_rollback_func()
        return []
    for row in rows:
        grouped.setdefault((row.unit_name or "").strip(), []).append(row)

    snapshot_rows: list[dict[str, Any]] = []
    for unit_name, items in grouped.items():
        visible_count = len([row for row in items if row.is_visible])
        snapshot_rows.append({
            "unit_name": unit_name,
            "configured_count": len(items),
            "visible_count": visible_count,
            "coverage_ratio": round((visible_count / all_menu_count) * 100, 1),
        })
    return snapshot_rows


def get_unit_profile_menu_keys_handler(
    *,
    unit_name: str,
    unit_menu_profile_model: Any,
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    safe_rollback_func: Callable[[], None],
) -> set[str]:
    """Birim profiline gore gorunur menu anahtarlarini dondurur."""
    normalized_unit = (unit_name or "").strip()
    if not normalized_unit:
        return set()
    try:
        rows = filter_live_menu_rows_func(
            unit_menu_profile_model.query.filter_by(unit_name=normalized_unit, is_visible=True).all()
        )
        return {row.menu_key for row in rows}
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/settings/menu_profile_access.py | line=119")
        safe_rollback_func()
        return set()


def build_role_default_rule_map_handler(
    *,
    role_name: str,
    flat_menu_items: list[dict[str, Any]] | None,
    flatten_menu_definitions_func: Callable[[], list[dict[str, Any]]],
    get_role_default_menu_keys_func: Callable[[str], set[str]],
) -> dict[str, bool]:
    """Rol varsayilanlarindan menu->gorunur haritasi uretir."""
    items = flat_menu_items or flatten_menu_definitions_func()
    role_defaults = get_role_default_menu_keys_func(role_name)
    return {item["key"]: item["key"] in role_defaults for item in items}


def build_base_rule_map_for_user_handler(
    *,
    user: Any,
    flat_menu_items: list[dict[str, Any]] | None,
    flatten_menu_definitions_func: Callable[[], list[dict[str, Any]]],
    build_role_default_rule_map_func: Callable[[str, list[dict[str, Any]]], dict[str, bool]],
    unit_menu_profile_model: Any,
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    safe_rollback_func: Callable[[], None],
) -> dict[str, Any]:
    """Kullanicinin rol + birim profilinden gelen temel menu haritasini uretir."""
    items = flat_menu_items or flatten_menu_definitions_func()
    role_map = build_role_default_rule_map_func(getattr(user, "role", ""), items)
    base_rule_map = dict(role_map)
    unit_name = (getattr(user, "birim", "") or "").strip()
    unit_rows: list[Any] = []
    if unit_name:
        try:
            unit_rows = filter_live_menu_rows_func(unit_menu_profile_model.query.filter_by(unit_name=unit_name).all())
        except Exception:
            logger.exception("BYS360 V6B guarded exception | file=app/services/settings/menu_profile_access.py | line=156")
            safe_rollback_func()
            unit_rows = []
    for row in unit_rows:
        base_rule_map[row.menu_key] = bool(row.is_visible)
    return {
        "base_rule_map": base_rule_map,
        "role_rule_map": role_map,
        "unit_rows": unit_rows,
        "unit_name": unit_name,
    }


def build_effective_user_menu_context_handler(
    *,
    user: Any,
    flat_menu_items: list[dict[str, Any]] | None,
    flatten_menu_definitions_func: Callable[[], list[dict[str, Any]]],
    build_base_rule_map_for_user_func: Callable[[Any, list[dict[str, Any]]], dict[str, Any]],
    user_menu_permission_model: Any,
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    safe_rollback_func: Callable[[], None],
) -> dict[str, Any]:
    """Kullanici icin rol + birim + kisi override sonucunu tek contextte toplar."""
    items = flat_menu_items or flatten_menu_definitions_func()
    base_context = build_base_rule_map_for_user_func(user, items)
    effective_rule_map = dict(base_context["base_rule_map"])
    source_map = {
        key: ("unit_profile" if any(row.menu_key == key for row in base_context["unit_rows"]) else "role_default")
        for key in effective_rule_map
    }

    try:
        override_rows = filter_live_menu_rows_func(user_menu_permission_model.query.filter_by(user_id=user.id).all())
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/settings/menu_profile_access.py | line=190")
        safe_rollback_func()
        override_rows = []

    for row in override_rows:
        effective_rule_map[row.menu_key] = bool(row.is_visible)
        source_map[row.menu_key] = "user_override"

    visible_source_counts = {"role_default": 0, "unit_profile": 0, "user_override": 0}
    hidden_source_counts = {"role_default": 0, "unit_profile": 0, "user_override": 0}
    for item in items:
        key = item["key"]
        source = source_map.get(key, "role_default")
        if effective_rule_map.get(key):
            visible_source_counts[source] = visible_source_counts.get(source, 0) + 1
        else:
            hidden_source_counts[source] = hidden_source_counts.get(source, 0) + 1

    return {
        "effective_rule_map": effective_rule_map,
        "base_rule_map": base_context["base_rule_map"],
        "role_rule_map": base_context["role_rule_map"],
        "role_default_keys": {key for key, visible in base_context["role_rule_map"].items() if visible},
        "unit_profile_keys": {row.menu_key for row in base_context["unit_rows"] if row.is_visible},
        "unit_profile_rows": base_context["unit_rows"],
        "override_rows": override_rows,
        "source_map": source_map,
        "visible_source_counts": visible_source_counts,
        "hidden_source_counts": hidden_source_counts,
        "base_visible_total": len([key for key, visible in base_context["base_rule_map"].items() if visible]),
    }


def save_role_menu_defaults_handler(
    *,
    role_name: str,
    all_menu_keys: list[str],
    visible_keys: set[str],
    updated_by_user_id: int | None,
    role_menu_default_model: Any,
    db_session: Any,
    filter_live_menu_keys_func: Callable[[Iterable[Any]], list[str]],
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    snapshot_role_menu_state_func: Callable[[str, Iterable[Any]], dict[str, bool]],
    build_complete_visibility_map_func: Callable[[Iterable[Any], Iterable[Any]], dict[str, bool]],
    create_settings_change_log_func: Callable[..., object],
) -> int:
    """Rol menu varsayilanlarini kaydeder ve degisim gunlugu olusturur.

    Kaldirilmis/decommission menu scope'una ait satirlara dokunmaz -- kardeş
    save_unit_menu_profile_handler/save_user_menu_overrides_handler ile ayni
    davranis (existing sorgusu live-row filtresinden gecer).
    """
    normalized_role = (role_name or "").strip().lower()
    if not normalized_role:
        raise ValueError("Rol seçilmedi.")
    previous_state = snapshot_role_menu_state_func(normalized_role, all_menu_keys)
    all_menu_keys = list(dict.fromkeys(filter_live_menu_keys_func(all_menu_keys)))
    visible_keys = set(filter_live_menu_keys_func(visible_keys))
    existing = {
        row.menu_key: row
        for row in filter_live_menu_rows_func(role_menu_default_model.query.filter_by(role_name=normalized_role).all())
    }
    changed = 0
    keep_keys = set(all_menu_keys)
    for menu_key in all_menu_keys:
        desired = menu_key in visible_keys
        row = existing.get(menu_key)
        if row is None:
            db_session.add(role_menu_default_model(
                role_name=normalized_role,
                menu_key=menu_key,
                is_visible=desired,
                source_type="manual",
                updated_by_user_id=updated_by_user_id,
            ))
            changed += 1
        elif row.is_visible != desired or (row.source_type or "") != "manual":
            row.is_visible = desired
            row.source_type = "manual"
            row.updated_by_user_id = updated_by_user_id
            changed += 1
    for menu_key, row in existing.items():
        if menu_key not in keep_keys:
            db_session.delete(row)
            changed += 1
    new_state = build_complete_visibility_map_func(all_menu_keys, visible_keys)
    create_settings_change_log_func(
        actor_user_id=updated_by_user_id,
        change_scope="role_menu_defaults",
        action_type="save",
        summary=f"Rol profili güncellendi: {normalized_role}",
        previous_state=previous_state,
        new_state=new_state,
        target_role_name=normalized_role,
    )
    db_session.commit()
    return changed


def save_unit_menu_profile_handler(
    *,
    unit_name: str,
    all_menu_keys: list[str],
    visible_keys: set[str],
    updated_by_user_id: int | None,
    unit_menu_profile_model: Any,
    db_session: Any,
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    filter_live_menu_keys_func: Callable[[Iterable[Any]], list[str]],
    snapshot_unit_menu_state_func: Callable[[str, Iterable[Any]], dict[str, bool]],
    build_complete_visibility_map_func: Callable[[Iterable[Any], Iterable[Any]], dict[str, bool]],
    create_settings_change_log_func: Callable[..., object],
) -> int:
    """Birim menu profilini kaydeder ve degisim gunlugu olusturur."""
    normalized_unit = (unit_name or "").strip()
    if not normalized_unit:
        raise ValueError("Birim seçilmedi.")
    previous_state = snapshot_unit_menu_state_func(normalized_unit, all_menu_keys)
    all_menu_keys = list(dict.fromkeys(filter_live_menu_keys_func(all_menu_keys)))
    visible_keys = set(filter_live_menu_keys_func(visible_keys))
    existing = {
        row.menu_key: row
        for row in filter_live_menu_rows_func(unit_menu_profile_model.query.filter_by(unit_name=normalized_unit).all())
    }
    changed = 0
    keep_keys = set(all_menu_keys)
    for menu_key in all_menu_keys:
        desired = menu_key in visible_keys
        row = existing.get(menu_key)
        if row is None:
            db_session.add(unit_menu_profile_model(
                unit_name=normalized_unit,
                menu_key=menu_key,
                is_visible=desired,
                source_type="manual",
                updated_by_user_id=updated_by_user_id,
            ))
            changed += 1
        elif row.is_visible != desired or (row.source_type or "") != "manual":
            row.is_visible = desired
            row.source_type = "manual"
            row.updated_by_user_id = updated_by_user_id
            changed += 1
    for menu_key, row in existing.items():
        if menu_key not in keep_keys:
            db_session.delete(row)
            changed += 1
    new_state = build_complete_visibility_map_func(all_menu_keys, visible_keys)
    create_settings_change_log_func(
        actor_user_id=updated_by_user_id,
        change_scope="unit_menu_profiles",
        action_type="save",
        summary=f"Birim profili güncellendi: {normalized_unit}",
        previous_state=previous_state,
        new_state=new_state,
        target_unit_name=normalized_unit,
    )
    db_session.commit()
    return changed


def clear_user_menu_overrides_handler(
    *,
    user_id: int,
    updated_by_user_id: int | None,
    user_menu_permission_model: Any,
    db_session: Any,
    create_settings_change_log_func: Callable[..., object],
) -> int:
    """Kisi bazli TUM override satirlarini (canli/kaldirilmis ayrimi yapmadan) temizler ve loglar."""
    rows = user_menu_permission_model.query.filter_by(user_id=user_id).all()
    previous_state = {row.menu_key: bool(row.is_visible) for row in rows}
    deleted = len(rows)
    for row in rows:
        db_session.delete(row)
    create_settings_change_log_func(
        actor_user_id=updated_by_user_id,
        change_scope="user_menu_overrides",
        action_type="clear",
        summary=f"Kullanıcı override temizlendi: user_id={user_id}",
        previous_state=previous_state,
        new_state={},
        target_user_id=user_id,
    )
    db_session.commit()
    return deleted


def build_settings_profile_context_handler(
    *,
    selected_user: Any = None,
    flat_menu_items: list[dict[str, Any]] | None = None,
    flatten_menu_definitions_func: Callable[[], list[dict[str, Any]]],
    unit_menu_profile_model: Any,
    build_unit_profile_snapshot_func: Callable[[], list[dict[str, Any]]],
    build_effective_user_menu_context_func: Callable[[Any, list[dict[str, Any]]], dict[str, Any]],
    list_recent_settings_change_logs_func: Callable[..., list[Any]],
    safe_rollback_func: Callable[[], None],
) -> dict[str, Any]:
    """Ayarlar profil ekraninin rol/birim/kisi context'ini uretir."""
    items = flat_menu_items or flatten_menu_definitions_func()
    unit_profiles_snapshot = build_unit_profile_snapshot_func()
    try:
        unit_profile_total = unit_menu_profile_model.query.with_entities(unit_menu_profile_model.unit_name).distinct().count()
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/settings/menu_profile_access.py | line=473")
        safe_rollback_func()
        unit_profile_total = 0
    context = {
        "unit_profiles_snapshot": unit_profiles_snapshot,
        "unit_profile_total": unit_profile_total,
        "selected_user_resolution": None,
        "recent_change_logs": list_recent_settings_change_logs_func(
            target_user_id=getattr(selected_user, "id", None) if selected_user else None
        ),
    }
    if selected_user:
        context["selected_user_resolution"] = build_effective_user_menu_context_func(selected_user, items)
    return context


__all__ = [
    "build_base_rule_map_for_user_handler",
    "build_effective_user_menu_context_handler",
    "build_role_default_rule_map_handler",
    "build_role_default_snapshot_handler",
    "build_settings_profile_context_handler",
    "build_unit_profile_snapshot_handler",
    "clear_user_menu_overrides_handler",
    "get_role_default_menu_keys_handler",
    "get_unit_profile_menu_keys_handler",
    "save_role_menu_defaults_handler",
    "save_unit_menu_profile_handler",
    "save_user_menu_overrides_handler",
]

# BYS360_PERSONNEL_FEATURE_MATRIX_V1_4_FULL_USER_OVERRIDE_SERVICE
def _bys360_pf_v14_dedupe_menu_items(items):
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


def save_user_menu_overrides_handler(
    *,
    user: Any,
    flat_menu_items: list[dict[str, Any]],
    visible_keys: set[str],
    updated_by_user_id: int | None,
    user_menu_permission_model: Any,
    db_session: Any,
    is_removed_menu_key_func: Callable[[Any], bool],
    filter_live_menu_rows_func: Callable[[Iterable[Any]], list[Any]],
    filter_live_menu_keys_func: Callable[[Iterable[Any]], list[str]],
    snapshot_user_override_state_func: Callable[[int | None], dict[str, bool]],
    build_base_rule_map_for_user_func: Callable[[Any, list[dict[str, Any]]], dict[str, Any]],
    create_settings_change_log_func: Callable[..., object],
    preserved_menu_keys: Iterable[str] = (),
) -> dict[str, int]:
    # preserved_menu_keys: rows this save must neither write nor prune (B1-F1 grant key).
    preserved = {str(key).strip() for key in preserved_menu_keys or () if str(key).strip()}
    flat_menu_items = [
        item for item in _bys360_pf_v14_dedupe_menu_items(flat_menu_items)
        if not is_removed_menu_key_func(item.get("key"))
    ]
    all_menu_keys = [str(item.get("key") or "").strip() for item in flat_menu_items if str(item.get("key") or "").strip()]
    all_menu_keys = list(dict.fromkeys(filter_live_menu_keys_func(all_menu_keys)))
    visible_keys = set(filter_live_menu_keys_func(visible_keys))
    previous_state = snapshot_user_override_state_func(user.id)
    existing_rows = filter_live_menu_rows_func(user_menu_permission_model.query.filter_by(user_id=user.id).all())
    existing = {row.menu_key: row for row in existing_rows}
    changed = 0
    keep_keys = set(all_menu_keys)
    for menu_key in all_menu_keys:
        if menu_key in preserved:
            continue
        desired = menu_key in visible_keys
        row = existing.get(menu_key)
        if row is None:
            db_session.add(user_menu_permission_model(
                user_id=user.id,
                menu_key=menu_key,
                is_visible=desired,
                source_type="user_override",
            ))
            changed += 1
        else:
            if row.is_visible != desired or (row.source_type or "") != "user_override":
                row.is_visible = desired
                row.source_type = "user_override"
                changed += 1
    for menu_key, row in existing.items():
        if menu_key not in keep_keys and menu_key not in preserved:
            db_session.delete(row)
            changed += 1
    new_state = {menu_key: (menu_key in visible_keys) for menu_key in all_menu_keys if menu_key not in preserved}
    for menu_key in preserved:
        if menu_key in existing:
            new_state[menu_key] = bool(existing[menu_key].is_visible)
    create_settings_change_log_func(
        actor_user_id=updated_by_user_id,
        change_scope="user_menu_overrides",
        action_type="save_full_personnel_feature_matrix",
        summary=f"Personel bazlı rol matrisi kaydedildi: {getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip(),
        previous_state=previous_state,
        new_state=new_state,
        target_user_id=user.id,
    )
    db_session.commit()
    return {"changed": changed, "override_count": len(all_menu_keys)}

