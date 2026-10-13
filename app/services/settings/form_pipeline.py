
"""Ayar kaydetme form pipeline servisleri.

Faz 9, genel sistem ayarları ve modül ayarları form kayıt akışını servis
katmanına taşır. Route/template sözleşmesi korunur; dışarıdan kullanılan
``settings_service.save_system_settings_from_form`` ve
``settings_service.save_module_settings_from_form`` fonksiyon adları aynı kalır.

Bu modül bilinçli olarak kayıt davranışını değiştirmez:
- Aynı alan adları okunur.
- Bool alanları yine checkbox ``on`` değerinden çevrilir.
- Değişiklik sayacı aynı mantıkla döner.
- Değişiklik olmasa da geçmiş kaydı oluşturma davranışı korunur.
- Commit tek ve kontrollü noktada yapılır.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol

from app.extensions import db
from app.models import ModuleSetting, SettingsChangeLog, SystemSetting


class FormLike(Protocol):
    def get(self, key: str, default: Any | None = None) -> Any: ...


SettingsDefinition = dict[str, Any]
TableExistsFn = Callable[[str], bool]
ValueToStorageFn = Callable[[Any, str], str]
SnapshotSystemFn = Callable[[], dict[str, str]]
SnapshotModuleFn = Callable[[], dict[str, dict[str, str]]]
ModuleDefinitionIterator = Callable[[], Iterable[SettingsDefinition]]
ChangeLogFn = Callable[..., SettingsChangeLog | None]


FORM_SAVE_PIPELINE_SCOPES: tuple[str, str] = ("system_settings", "module_settings")


def _ensure_table(table_name: str, table_exists: TableExistsFn) -> None:
    if not table_exists(table_name):
        raise RuntimeError(f"{table_name} tablosu yok. Önce flask db upgrade çalıştırın.")


def _system_field_name(setting_key: str) -> str:
    return f"system__{setting_key.replace('.', '__')}"


def _module_field_name(module_key: str, setting_key: str) -> str:
    return f"module__{module_key}__{setting_key.replace('.', '__')}"


def _incoming_form_value(form: FormLike | Mapping[str, Any], field_name: str, input_type: str) -> Any:
    if input_type == "bool":
        return "true" if form.get(field_name) == "on" else "false"
    return form.get(field_name)


def save_system_settings_from_form_handler(
    form: FormLike | Mapping[str, Any],
    *,
    updated_by_user_id: int | None = None,
    table_exists: TableExistsFn,
    system_definitions: Iterable[SettingsDefinition],
    value_to_storage: ValueToStorageFn,
    snapshot_system_state: SnapshotSystemFn,
    create_change_log: ChangeLogFn,
) -> int:
    """Genel sistem ayarlarını formdan kaydeder.

    Dönüş değeri eski servis fonksiyonuyla aynıdır: değişen/yeni kayıt sayısı.
    """
    _ensure_table("system_settings", table_exists)
    previous_state = snapshot_system_state()
    definitions = {item["setting_key"]: item for item in system_definitions}
    rows = {row.setting_key: row for row in SystemSetting.query.all()}
    changed = 0

    for setting_key, definition in definitions.items():
        incoming = _incoming_form_value(form, _system_field_name(setting_key), definition["input_type"])
        storage_value = value_to_storage(incoming, definition["value_type"])
        row = rows.get(setting_key)
        if row is None:
            row = SystemSetting(
                setting_key=setting_key,
                group_key=definition["group_key"],
                label=definition["label"],
                value_text=storage_value,
                value_type=definition["value_type"],
                description=definition.get("description"),
                updated_by_user_id=updated_by_user_id,
            )
            db.session.add(row)
            changed += 1
        elif (row.value_text or "") != storage_value:
            row.value_text = storage_value
            row.label = definition["label"]
            row.group_key = definition["group_key"]
            row.value_type = definition["value_type"]
            row.description = definition.get("description")
            row.updated_by_user_id = updated_by_user_id
            changed += 1

    new_state = snapshot_system_state()
    create_change_log(
        actor_user_id=updated_by_user_id,
        change_scope="system_settings",
        action_type="save",
        summary="Genel sistem ayarları güncellendi",
        previous_state=previous_state,
        new_state=new_state,
    )
    db.session.commit()
    return changed


def module_settings_state_from_form_handler(
    form: FormLike | Mapping[str, Any],
    *,
    iter_live_module_setting_definitions: ModuleDefinitionIterator,
    value_to_storage: ValueToStorageFn,
) -> dict[str, dict[str, str]]:
    """The module state ``save_module_settings_from_form_handler`` would store, without writing.

    R05c uses it to check role-authority settings before the save runs (the save commits).
    """
    state: dict[str, dict[str, str]] = {}
    for definition in iter_live_module_setting_definitions():
        incoming = _incoming_form_value(
            form,
            _module_field_name(definition["module_key"], definition["setting_key"]),
            definition["input_type"],
        )
        state.setdefault(definition["module_key"], {})[definition["setting_key"]] = value_to_storage(
            incoming, definition["value_type"]
        )
    return state


def save_module_settings_from_form_handler(
    form: FormLike | Mapping[str, Any],
    *,
    updated_by_user_id: int | None = None,
    table_exists: TableExistsFn,
    iter_live_module_setting_definitions: ModuleDefinitionIterator,
    value_to_storage: ValueToStorageFn,
    snapshot_module_state: SnapshotModuleFn,
    create_change_log: ChangeLogFn,
) -> int:
    """Canlı modül ayarlarını formdan kaydeder.

    Sadece ``iter_live_module_setting_definitions`` tarafından dönen canlı modül
    tanımları işlenir. Böylece kaldırılmış/eski modüller yanlışlıkla tekrar
    ayar ekranına veya kayıt akışına basılmaz.
    """
    _ensure_table("module_settings", table_exists)
    previous_state = snapshot_module_state()
    definitions = {
        (item["module_key"], item["setting_key"]): item
        for item in iter_live_module_setting_definitions()
    }
    rows = {(row.module_key, row.setting_key): row for row in ModuleSetting.query.all()}
    changed = 0

    for key, definition in definitions.items():
        incoming = _incoming_form_value(
            form,
            _module_field_name(definition["module_key"], definition["setting_key"]),
            definition["input_type"],
        )
        storage_value = value_to_storage(incoming, definition["value_type"])
        row = rows.get(key)
        if row is None:
            row = ModuleSetting(
                module_key=definition["module_key"],
                setting_key=definition["setting_key"],
                label=definition["label"],
                value_text=storage_value,
                value_type=definition["value_type"],
                description=definition.get("description"),
                updated_by_user_id=updated_by_user_id,
            )
            db.session.add(row)
            changed += 1
        elif (row.value_text or "") != storage_value:
            row.value_text = storage_value
            row.label = definition["label"]
            row.value_type = definition["value_type"]
            row.description = definition.get("description")
            row.updated_by_user_id = updated_by_user_id
            changed += 1

    new_state = snapshot_module_state()
    create_change_log(
        actor_user_id=updated_by_user_id,
        change_scope="module_settings",
        action_type="save",
        summary="Modül ayarları güncellendi",
        previous_state=previous_state,
        new_state=new_state,
    )
    db.session.commit()
    return changed
