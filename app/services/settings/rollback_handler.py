
"""Ayarlar geri alma (rollback) servis handler'i.

Faz 8 bu modülü bilinçli olarak route/template davranışından bağımsız tutar.
Dışarıya açık eski ``settings_service.rollback_settings_change`` fonksiyonu aynı
kalır; gerçek geri alma işlemi bu handler'a devredilir. Commit noktası yine tek
ve kontrollüdür.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from app.extensions import db
from app.menu_registry import flatten_menu_definitions
from app.models import (
    ModuleSetting,
    RoleMenuDefault,
    SettingsChangeLog,
    SystemSetting,
    UnitMenuProfile,
    UserMenuPermission,
)
from app.services.personnel_read_grant import EXPLICIT_GRANT_KEYS
from app.services.settings.change_logs import create_settings_change_log, deserialize_settings_state
from app.services.settings.menu_permissions import (
    filter_live_menu_keys,
    snapshot_role_menu_state,
    snapshot_unit_menu_state,
    snapshot_user_override_state,
)

SettingsDefinition = dict[str, Any]
SnapshotFn = Callable[[], dict[str, Any]]
TableExistsFn = Callable[[str], bool]
ValueToStorageFn = Callable[[Any, str], str]
ModuleDefinitionIterator = Callable[[], Iterable[SettingsDefinition]]
ChangeLogFn = Callable[..., SettingsChangeLog | None]
DeserializeFn = Callable[[str | None], dict[str, Any] | None]

ROLLBACK_SUPPORTED_SCOPES: tuple[str, ...] = (
    "system_settings",
    "module_settings",
    "role_menu_defaults",
    "unit_menu_profiles",
    "user_menu_overrides",
)


def _live_menu_keys() -> list[str]:
    return filter_live_menu_keys([item["key"] for item in flatten_menu_definitions()])


def _ensure_change_log_table(table_exists: TableExistsFn) -> None:
    if not table_exists("settings_change_logs"):
        raise RuntimeError("settings_change_logs tablosu yok. Önce flask db upgrade çalıştırın.")


def _load_target_log(log_id: int) -> SettingsChangeLog:
    row = db.session.get(SettingsChangeLog, log_id)
    if row is None:
        raise ValueError("Geri alınacak kayıt bulunamadı.")
    return row


def _rollback_system_settings(
    *,
    previous_state: dict[str, Any],
    actor_user_id: int | None,
    system_definitions: Iterable[SettingsDefinition],
    value_to_storage: ValueToStorageFn,
    snapshot_system_state: SnapshotFn,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    current_snapshot = snapshot_system_state()
    definitions = {item["setting_key"]: item for item in system_definitions}
    existing = {setting.setting_key: setting for setting in SystemSetting.query.all()}

    for setting_key, definition in definitions.items():
        storage_value = previous_state.get(
            setting_key,
            value_to_storage(definition.get("default"), definition["value_type"]),
        )
        target = existing.get(setting_key)
        if target is None:
            target = SystemSetting(
                setting_key=setting_key,
                group_key=definition["group_key"],
                label=definition["label"],
                value_text=storage_value,
                value_type=definition["value_type"],
                description=definition.get("description"),
                updated_by_user_id=actor_user_id,
            )
            db.session.add(target)
        else:
            target.group_key = definition["group_key"]
            target.label = definition["label"]
            target.value_text = storage_value
            target.value_type = definition["value_type"]
            target.description = definition.get("description")
            target.updated_by_user_id = actor_user_id

    return current_snapshot, snapshot_system_state(), "Genel sistem ayarları önceki sürüme alındı"


def _rollback_module_settings(
    *,
    previous_state: dict[str, Any],
    actor_user_id: int | None,
    iter_live_module_setting_definitions: ModuleDefinitionIterator,
    value_to_storage: ValueToStorageFn,
    snapshot_module_state: SnapshotFn,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    current_snapshot = snapshot_module_state()
    definitions = {
        (item["module_key"], item["setting_key"]): item
        for item in iter_live_module_setting_definitions()
    }
    existing = {(setting.module_key, setting.setting_key): setting for setting in ModuleSetting.query.all()}

    for key, definition in definitions.items():
        storage_value = (previous_state.get(definition["module_key"], {}) or {}).get(
            definition["setting_key"],
            value_to_storage(definition.get("default"), definition["value_type"]),
        )
        target = existing.get(key)
        if target is None:
            target = ModuleSetting(
                module_key=definition["module_key"],
                setting_key=definition["setting_key"],
                label=definition["label"],
                value_text=storage_value,
                value_type=definition["value_type"],
                description=definition.get("description"),
                updated_by_user_id=actor_user_id,
            )
            db.session.add(target)
        else:
            target.label = definition["label"]
            target.value_text = storage_value
            target.value_type = definition["value_type"]
            target.description = definition.get("description")
            target.updated_by_user_id = actor_user_id

    return current_snapshot, snapshot_module_state(), "Modül ayarları önceki sürüme alındı"


def _rollback_role_menu_defaults(
    *,
    row: SettingsChangeLog,
    previous_state: dict[str, Any],
    actor_user_id: int | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    all_menu_keys = _live_menu_keys()
    role_name = (row.target_role_name or "").strip().lower()
    if not role_name:
        raise ValueError("Kayıtta rol bilgisi bulunamadı.")

    current_snapshot = snapshot_role_menu_state(role_name, all_menu_keys)
    existing = {item.menu_key: item for item in RoleMenuDefault.query.filter_by(role_name=role_name).all()}

    for menu_key in all_menu_keys:
        desired = bool(previous_state.get(menu_key, False))
        target = existing.get(menu_key)
        if target is None:
            db.session.add(RoleMenuDefault(
                role_name=role_name,
                menu_key=menu_key,
                is_visible=desired,
                source_type="rollback",
                updated_by_user_id=actor_user_id,
            ))
        else:
            target.is_visible = desired
            target.source_type = "rollback"
            target.updated_by_user_id = actor_user_id

    return current_snapshot, snapshot_role_menu_state(role_name, all_menu_keys), f"Rol profili geri alındı: {role_name}"


def _rollback_unit_menu_profiles(
    *,
    row: SettingsChangeLog,
    previous_state: dict[str, Any],
    actor_user_id: int | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    all_menu_keys = _live_menu_keys()
    unit_name = (row.target_unit_name or "").strip()
    if not unit_name:
        raise ValueError("Kayıtta birim bilgisi bulunamadı.")

    current_snapshot = snapshot_unit_menu_state(unit_name, all_menu_keys)
    existing = {item.menu_key: item for item in UnitMenuProfile.query.filter_by(unit_name=unit_name).all()}

    for menu_key in all_menu_keys:
        desired = bool(previous_state.get(menu_key, False))
        target = existing.get(menu_key)
        if target is None:
            db.session.add(UnitMenuProfile(
                unit_name=unit_name,
                menu_key=menu_key,
                is_visible=desired,
                source_type="rollback",
                updated_by_user_id=actor_user_id,
            ))
        else:
            target.is_visible = desired
            target.source_type = "rollback"
            target.updated_by_user_id = actor_user_id

    return current_snapshot, snapshot_unit_menu_state(unit_name, all_menu_keys), f"Birim profili geri alındı: {unit_name}"


def _rollback_user_menu_overrides(
    *,
    row: SettingsChangeLog,
    previous_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    user_id = row.target_user_id
    if not user_id:
        raise ValueError("Kayıtta kullanıcı bilgisi bulunamadı.")

    current_snapshot = snapshot_user_override_state(user_id)
    # B1-F1, K5-Q2: a menu rollback never touches the explicit grants (personnel_read_all,
    # support_all): it neither restores nor removes them; only an admin's per-user save for
    # another user changes them.
    UserMenuPermission.query.filter(
        UserMenuPermission.user_id == user_id,
        UserMenuPermission.menu_key.notin_(EXPLICIT_GRANT_KEYS),
    ).delete()
    for menu_key, is_visible in (previous_state or {}).items():
        if menu_key in EXPLICIT_GRANT_KEYS:
            continue
        if menu_key in _live_menu_keys():
            db.session.add(UserMenuPermission(
                user_id=user_id,
                menu_key=menu_key,
                is_visible=bool(is_visible),
                source_type="rollback",
            ))

    return current_snapshot, snapshot_user_override_state(user_id), f"Kullanıcı override kaydı geri alındı: user_id={user_id}"


def rollback_settings_change_handler(
    log_id: int,
    *,
    actor_user_id: int | None = None,
    table_exists: TableExistsFn,
    system_definitions: Iterable[SettingsDefinition],
    iter_live_module_setting_definitions: ModuleDefinitionIterator,
    value_to_storage: ValueToStorageFn,
    snapshot_system_state: SnapshotFn,
    snapshot_module_state: SnapshotFn,
    create_change_log: ChangeLogFn = create_settings_change_log,
    deserialize_state: DeserializeFn = deserialize_settings_state,
) -> dict[str, Any]:
    """Ayar değişikliğini önceki durumuna alır ve rollback log'u oluşturur.

    Commit tek noktada yapılır. Çağıran katman için eski dönüş sözleşmesi korunur:
    ``rolled_back_log_id``, ``new_log_id`` ve ``summary``.
    """
    _ensure_change_log_table(table_exists)
    row = _load_target_log(log_id)
    previous_state = deserialize_state(row.previous_state_json) or {}

    if row.change_scope == "system_settings":
        current_snapshot, new_state, summary = _rollback_system_settings(
            previous_state=previous_state,
            actor_user_id=actor_user_id,
            system_definitions=system_definitions,
            value_to_storage=value_to_storage,
            snapshot_system_state=snapshot_system_state,
        )
    elif row.change_scope == "module_settings":
        current_snapshot, new_state, summary = _rollback_module_settings(
            previous_state=previous_state,
            actor_user_id=actor_user_id,
            iter_live_module_setting_definitions=iter_live_module_setting_definitions,
            value_to_storage=value_to_storage,
            snapshot_module_state=snapshot_module_state,
        )
    elif row.change_scope == "role_menu_defaults":
        current_snapshot, new_state, summary = _rollback_role_menu_defaults(
            row=row,
            previous_state=previous_state,
            actor_user_id=actor_user_id,
        )
    elif row.change_scope == "unit_menu_profiles":
        current_snapshot, new_state, summary = _rollback_unit_menu_profiles(
            row=row,
            previous_state=previous_state,
            actor_user_id=actor_user_id,
        )
    elif row.change_scope == "user_menu_overrides":
        current_snapshot, new_state, summary = _rollback_user_menu_overrides(
            row=row,
            previous_state=previous_state,
        )
    else:
        raise ValueError("Bu kayıt tipi geri alınamıyor.")

    rollback_row = create_change_log(
        actor_user_id=actor_user_id,
        change_scope=row.change_scope,
        action_type="rollback",
        summary=summary,
        previous_state=current_snapshot,
        new_state=new_state,
        target_user_id=row.target_user_id,
        target_role_name=row.target_role_name,
        target_unit_name=row.target_unit_name,
        reverted_from_log_id=row.id,
        is_rollback=True,
    )
    if rollback_row is None:
        raise RuntimeError("settings_change_logs tablosu yok. Önce flask db upgrade çalıştırın.")
    db.session.commit()
    return {"rolled_back_log_id": row.id, "new_log_id": rollback_row.id, "summary": summary}
