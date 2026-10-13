"""BYS360 ayarlar temel okuma/yazma erisim katmani.

Settings Service Tamamlama Faz 1:
- settings_service.py icindeki temel seed ve foundation context akisini dis modüle tasir.
- Route/template sozlesmesini degistirmez.
- Bagimliliklar parametre olarak alinir; bu sayede mevcut model, db ve menu registry akisi korunur.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any

from app.services.personnel_read_grant import without_explicit_grants

logger = logging.getLogger(__name__)


def iter_live_module_setting_definitions(
    module_setting_definitions: Iterable[dict[str, Any]],
    is_live_module_key: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Yalniz canli kapsamda kalan modul ayar tanimlarini dondurur."""
    live_items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in module_setting_definitions:
        module_key = (item.get("module_key") or "").strip()
        setting_key = (item.get("setting_key") or "").strip()
        if not module_key or not setting_key:
            continue
        if not is_live_module_key(module_key):
            continue
        pair = (module_key, setting_key)
        if pair in seen:
            continue
        seen.add(pair)
        live_items.append(item)
    return live_items


def ensure_settings_phase1_seeded_handler(
    *,
    updated_by_user_id: int | None,
    table_exists: Callable[[str], bool],
    flatten_menu_definitions_func: Callable[[], list[dict[str, Any]]],
    filter_live_menu_keys: Callable[[Iterable[str]], list[str]],
    static_role_default_menu_keys_func: Callable[[str], set[str]],
    role_menu_defaults: dict[str, Any],
    role_menu_default_model: Any,
    system_setting_model: Any,
    module_setting_model: Any,
    db_session: Any,
    system_definitions: list[dict[str, Any]],
    iter_live_module_setting_definitions_func: Callable[[], list[dict[str, Any]]],
    value_to_storage: Callable[[Any, str], str],
    safe_rollback: Callable[[], None],
) -> dict[str, Any]:
    """Role/menu, system ve module ayar varsayilanlarini guvenli sekilde seed eder."""
    summary = {
        "ok": True,
        "seeded_role_defaults": 0,
        "seeded_system_settings": 0,
        "seeded_module_settings": 0,
    }
    missing_tables = [
        name
        for name in ("role_menu_defaults", "system_settings", "module_settings")
        if not table_exists(name)
    ]
    if missing_tables:
        return {
            **summary,
            "ok": False,
            "error": "Ayarlar altyapısı henüz veritabanına uygulanmamış.",
            "missing_tables": missing_tables,
        }

    try:
        flat_items = flatten_menu_definitions_func()
        all_menu_keys = filter_live_menu_keys([item["key"] for item in flat_items])
        for role_name in sorted(role_menu_defaults.keys()):
            # B1-F1, K5-Q1: the explicit per-user grants are never a role default, not even a
            # stored seed row (the effective menu ignores them; the role matrix must not show them).
            visible_keys = set(without_explicit_grants(static_role_default_menu_keys_func(role_name)))
            existing_rows = {
                row.menu_key: row
                for row in role_menu_default_model.query.filter_by(role_name=role_name).all()
            }
            for menu_key in all_menu_keys:
                row = existing_rows.get(menu_key)
                should_be_visible = menu_key in visible_keys
                if row is None:
                    db_session.add(role_menu_default_model(
                        role_name=role_name,
                        menu_key=menu_key,
                        is_visible=should_be_visible,
                        source_type="seed",
                        updated_by_user_id=updated_by_user_id,
                    ))
                    summary["seeded_role_defaults"] += 1
                elif row.source_type == "seed" and row.is_visible != should_be_visible:
                    row.is_visible = should_be_visible
                    row.updated_by_user_id = updated_by_user_id

        existing_system = {row.setting_key: row for row in system_setting_model.query.all()}
        for definition in system_definitions:
            row = existing_system.get(definition["setting_key"])
            if row is None:
                db_session.add(system_setting_model(
                    setting_key=definition["setting_key"],
                    group_key=definition["group_key"],
                    label=definition["label"],
                    value_text=value_to_storage(definition.get("default"), definition["value_type"]),
                    value_type=definition["value_type"],
                    description=definition.get("description"),
                    updated_by_user_id=updated_by_user_id,
                ))
                summary["seeded_system_settings"] += 1

        existing_module = {
            (row.module_key, row.setting_key): row
            for row in module_setting_model.query.all()
        }
        for definition in iter_live_module_setting_definitions_func():
            key = (definition["module_key"], definition["setting_key"])
            row = existing_module.get(key)
            if row is None:
                db_session.add(module_setting_model(
                    module_key=definition["module_key"],
                    setting_key=definition["setting_key"],
                    label=definition["label"],
                    value_text=value_to_storage(definition.get("default"), definition["value_type"]),
                    value_type=definition["value_type"],
                    description=definition.get("description"),
                    updated_by_user_id=updated_by_user_id,
                ))
                summary["seeded_module_settings"] += 1

        db_session.commit()
        return summary
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/settings/foundation_access.py | line=137")
        safe_rollback()
        return {**summary, "ok": False, "error": "Ayarlar omurgası hazırlanırken beklenmeyen bir hata oluştu."}


def build_settings_foundation_context_handler(
    *,
    table_exists: Callable[[str], bool],
    missing_settings_tables: Callable[[], list[str]],
    system_setting_model: Any,
    module_setting_model: Any,
    system_definitions: list[dict[str, Any]],
    iter_live_module_setting_definitions_func: Callable[[], list[dict[str, Any]]],
    value_to_python: Callable[[str | None, str], Any],
    build_role_default_snapshot: Callable[[], list[dict[str, Any]]],
    build_unit_profile_snapshot: Callable[[], list[dict[str, Any]]],
    list_recent_settings_change_logs_func: Callable[..., list[Any]],
    role_menu_defaults: dict[str, Any],
    safe_rollback: Callable[[], None],
) -> dict[str, Any]:
    """Ayarlar ana ekraninin temel okuma context'ini uretir."""
    system_rows = {}
    module_rows = {}
    missing_tables = missing_settings_tables()

    if table_exists("system_settings"):
        try:
            system_rows = {row.setting_key: row for row in system_setting_model.query.all()}
        except Exception:
            logger.exception("BYS360 V6B guarded exception | file=app/services/settings/foundation_access.py | line=165")
            safe_rollback()
            system_rows = {}

    if table_exists("module_settings"):
        try:
            module_rows = {
                (row.module_key, row.setting_key): row
                for row in module_setting_model.query.all()
            }
        except Exception:
            logger.exception("BYS360 V6B guarded exception | file=app/services/settings/foundation_access.py | line=175")
            safe_rollback()
            module_rows = {}

    system_groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for definition in system_definitions:
        group = system_groups.setdefault(definition["group_key"], {
            "group_key": definition["group_key"],
            "group_label": definition["group_label"],
            "group_description": definition.get("group_description", ""),
            "rows": [],
        })
        row = system_rows.get(definition["setting_key"])
        current_value = value_to_python(
            row.value_text if row else definition.get("default"),
            definition["value_type"],
        )
        group["rows"].append({**definition, "current_value": current_value})

    module_definitions = iter_live_module_setting_definitions_func()
    module_groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for definition in module_definitions:
        group = module_groups.setdefault(definition["module_key"], {
            "module_key": definition["module_key"],
            "module_label": definition["module_label"],
            "module_description": definition.get("module_description", ""),
            "rows": [],
        })
        row = module_rows.get((definition["module_key"], definition["setting_key"]))
        current_value = value_to_python(
            row.value_text if row else definition.get("default"),
            definition["value_type"],
        )
        group["rows"].append({**definition, "current_value": current_value})

    unit_profiles_snapshot = build_unit_profile_snapshot()
    recent_logs = list_recent_settings_change_logs_func()
    return {
        "system_groups": list(system_groups.values()),
        "module_groups": list(module_groups.values()),
        "role_defaults_snapshot": build_role_default_snapshot(),
        "unit_profiles_snapshot": unit_profiles_snapshot,
        "recent_change_logs": recent_logs,
        "db_ready": len(missing_tables) == 0,
        "missing_tables": missing_tables,
        "stats": {
            "system_total": len(system_definitions),
            "module_total": len(module_definitions),
            "module_group_total": len(module_groups),
            "role_total": len(role_menu_defaults),
            "unit_profile_total": len(unit_profiles_snapshot),
            "history_total": len(recent_logs),
        },
    }


__all__ = [
    "build_settings_foundation_context_handler",
    "ensure_settings_phase1_seeded_handler",
    "iter_live_module_setting_definitions",
]
