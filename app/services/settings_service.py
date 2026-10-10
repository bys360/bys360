from __future__ import annotations

from typing import Any

from sqlalchemy import inspect

from app.config import is_removed_menu_key
from app.extensions import db
from app.live_scope import is_live_settings_module_key
from app.menu_registry import (
    ROLE_MENU_DEFAULTS,
    flatten_menu_definitions,
    get_role_default_menu_keys as static_role_default_menu_keys,
)
from app.models import (
    ModuleSetting,
    RoleMenuDefault,
    SystemSetting,
    UnitMenuProfile,
    UserMenuPermission,
)
from app.services.personnel_read_grant import PERSONNEL_READ_ALL_KEY, without_personnel_read_all
from app.services.settings.catalog import MODULE_SETTING_DEFINITIONS, SYSTEM_SETTING_DEFINITIONS
from app.services.settings.change_logs import (
    create_settings_change_log as _create_settings_change_log,
    deserialize_settings_state as _deserialize_state,
    list_recent_settings_change_logs,
)
from app.services.settings.diagnostics import (
    build_settings_diagnostics_context as _build_settings_diagnostics_context,
)
from app.services.settings.final_hardening import (
    assert_settings_final_hardening_contract as _assert_settings_final_hardening_contract,
    build_settings_final_hardening_report as _build_settings_final_hardening_report,
    get_settings_final_release_checklist as _get_settings_final_release_checklist,
)
from app.services.settings.form_pipeline import (
    save_module_settings_from_form_handler as _save_module_settings_from_form_handler,
    save_system_settings_from_form_handler as _save_system_settings_from_form_handler,
)
from app.services.settings.foundation_access import (
    build_settings_foundation_context_handler as _build_settings_foundation_context_handler,
    ensure_settings_phase1_seeded_handler as _ensure_settings_phase1_seeded_handler,
    iter_live_module_setting_definitions as _iter_live_module_setting_definitions_handler,
)
from app.services.settings.menu_permissions import (
    build_complete_visibility_map as _build_complete_visibility_map,
    filter_live_menu_keys as _filter_live_menu_keys,
    filter_live_menu_rows as _filter_live_menu_rows,
    snapshot_module_settings_state as _snapshot_module_settings_state,
    snapshot_role_menu_state as _snapshot_role_menu_state,
    snapshot_system_settings_state as _snapshot_system_settings_state,
    snapshot_unit_menu_state as _snapshot_unit_menu_state,
    snapshot_user_override_state as _snapshot_user_override_state,
)
from app.services.settings.menu_profile_access import (
    build_base_rule_map_for_user_handler as _build_base_rule_map_for_user_handler,
    build_effective_user_menu_context_handler as _build_effective_user_menu_context_handler,
    build_role_default_rule_map_handler as _build_role_default_rule_map_handler,
    build_role_default_snapshot_handler as _build_role_default_snapshot_handler,
    build_settings_profile_context_handler as _build_settings_profile_context_handler,
    build_unit_profile_snapshot_handler as _build_unit_profile_snapshot_handler,
    clear_user_menu_overrides_handler as _clear_user_menu_overrides_handler,
    get_role_default_menu_keys_handler as _get_role_default_menu_keys_handler,
    get_unit_profile_menu_keys_handler as _get_unit_profile_menu_keys_handler,
    save_role_menu_defaults_handler as _save_role_menu_defaults_handler,
    save_unit_menu_profile_handler as _save_unit_menu_profile_handler,
    save_user_menu_overrides_handler as _save_user_menu_overrides_handler,
)
from app.services.settings.quality_gate import (
    build_settings_refactor_quality_snapshot as _build_settings_refactor_quality_snapshot,
    build_settings_template_guard_context as _build_settings_template_guard_context,
    get_settings_refactor_phase_sequence as _get_settings_refactor_phase_sequence,
)
from app.services.settings.rollback_handler import (
    rollback_settings_change_handler as _rollback_settings_change_handler,
)
from app.services.settings.ui_panel import (
    build_settings_ui_diagnostics_panel as _build_settings_ui_diagnostics_panel,
)
from app.services.settings.validation_defaults import (
    build_settings_defaults_snapshot as _build_settings_defaults_snapshot_handler,
    normalize_module_setting_definitions as _normalize_module_setting_definitions_handler,
    normalize_system_setting_definitions as _normalize_system_setting_definitions_handler,
    validate_settings_catalog_contract as _validate_settings_catalog_contract_handler,
)
from app.services.settings.value_codec import (
    value_to_python as _value_to_python,
    value_to_storage as _value_to_storage,
)


def _table_exists(table_name: str) -> bool:
    try:
        return inspect(db.engine).has_table(table_name)
    except Exception:
        _safe_rollback()
        return False


def _missing_settings_tables() -> list[str]:
    required = [
        'role_menu_defaults',
        'system_settings',
        'module_settings',
        'unit_menu_profiles',
        'settings_change_logs',
    ]
    return [name for name in required if not _table_exists(name)]


def _settings_bootstrap_ready(*, include_phase2_phase3: bool = False) -> bool:
    required = ['role_menu_defaults', 'system_settings', 'module_settings']
    if include_phase2_phase3:
        required.extend(['unit_menu_profiles', 'settings_change_logs'])
    return all(_table_exists(name) for name in required)


def _normalized_system_setting_definitions() -> list[dict[str, Any]]:
    """Sistem ayar katalogunu validasyon/default katmanindan gecirir."""
    return _normalize_system_setting_definitions_handler(SYSTEM_SETTING_DEFINITIONS)


def _normalized_module_setting_definitions() -> list[dict[str, Any]]:
    """Modul ayar katalogunu validasyon/default katmanindan gecirir."""
    return _normalize_module_setting_definitions_handler(MODULE_SETTING_DEFINITIONS)


def _iter_live_module_setting_definitions() -> list[dict[str, Any]]:
    """Yalnız canlı kapsamda kalan modül ayarlarını döndürür."""
    return _iter_live_module_setting_definitions_handler(
        _normalized_module_setting_definitions(),
        is_live_settings_module_key,
    )


def validate_settings_definition_contract() -> dict[str, Any]:
    """Ayar katalogu zorunlu alan/default sozlesmesini yan etkisiz denetler."""
    return _validate_settings_catalog_contract_handler(
        _normalized_system_setting_definitions(),
        _normalized_module_setting_definitions(),
    )


def build_settings_defaults_snapshot() -> dict[str, Any]:
    """Ayar kataloglarindaki varsayilan deger haritasini dondurur."""
    return _build_settings_defaults_snapshot_handler(
        _normalized_system_setting_definitions(),
        _iter_live_module_setting_definitions(),
    )

def _safe_rollback() -> None:
    try:
        db.session.rollback()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/settings_service.py")
def ensure_settings_phase1_seeded(updated_by_user_id: int | None = None) -> dict[str, Any]:
    return _ensure_settings_phase1_seeded_handler(
        updated_by_user_id=updated_by_user_id,
        table_exists=_table_exists,
        flatten_menu_definitions_func=flatten_menu_definitions,
        filter_live_menu_keys=_filter_live_menu_keys,
        static_role_default_menu_keys_func=static_role_default_menu_keys,
        role_menu_defaults=ROLE_MENU_DEFAULTS,
        role_menu_default_model=RoleMenuDefault,
        system_setting_model=SystemSetting,
        module_setting_model=ModuleSetting,
        db_session=db.session,
        system_definitions=_normalized_system_setting_definitions(),
        iter_live_module_setting_definitions_func=_iter_live_module_setting_definitions,
        value_to_storage=_value_to_storage,
        safe_rollback=_safe_rollback,
    )

def get_role_default_menu_keys(role_name: str, prefer_database: bool = True) -> set[str]:
    return _get_role_default_menu_keys_handler(
        role_name=role_name,
        prefer_database=prefer_database,
        role_menu_default_model=RoleMenuDefault,
        static_role_default_menu_keys_func=static_role_default_menu_keys,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        filter_live_menu_keys_func=_filter_live_menu_keys,
        safe_rollback_func=_safe_rollback,
    )

def _build_role_default_snapshot() -> list[dict[str, Any]]:
    return _build_role_default_snapshot_handler(
        role_menu_defaults=ROLE_MENU_DEFAULTS,
        flatten_menu_definitions_func=flatten_menu_definitions,
        get_role_default_menu_keys_func=get_role_default_menu_keys,
    )

def _build_unit_profile_snapshot() -> list[dict[str, Any]]:
    return _build_unit_profile_snapshot_handler(
        unit_menu_profile_model=UnitMenuProfile,
        flatten_menu_definitions_func=flatten_menu_definitions,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        safe_rollback_func=_safe_rollback,
    )

def get_unit_profile_menu_keys(unit_name: str) -> set[str]:
    return _get_unit_profile_menu_keys_handler(
        unit_name=unit_name,
        unit_menu_profile_model=UnitMenuProfile,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        safe_rollback_func=_safe_rollback,
    )

def build_role_default_rule_map(role_name: str, flat_menu_items: list[dict[str, Any]] | None = None) -> dict[str, bool]:
    return _build_role_default_rule_map_handler(
        role_name=role_name,
        flat_menu_items=flat_menu_items,
        flatten_menu_definitions_func=flatten_menu_definitions,
        get_role_default_menu_keys_func=get_role_default_menu_keys,
    )

def build_base_rule_map_for_user(user, flat_menu_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    context = _build_base_rule_map_for_user_handler(
        user=user,
        flat_menu_items=flat_menu_items,
        flatten_menu_definitions_func=flatten_menu_definitions,
        build_role_default_rule_map_func=build_role_default_rule_map,
        unit_menu_profile_model=UnitMenuProfile,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        safe_rollback_func=_safe_rollback,
    )
    # B1-F1: the personnel_read_all grant comes only from the user's own override row.
    for map_name in ("base_rule_map", "role_rule_map"):
        if PERSONNEL_READ_ALL_KEY in context[map_name]:
            context[map_name][PERSONNEL_READ_ALL_KEY] = False
    context["unit_rows"] = [row for row in context["unit_rows"] if getattr(row, "menu_key", None) != PERSONNEL_READ_ALL_KEY]
    return context

def build_effective_user_menu_context(user, flat_menu_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _build_effective_user_menu_context_handler(
        user=user,
        flat_menu_items=flat_menu_items,
        flatten_menu_definitions_func=flatten_menu_definitions,
        build_base_rule_map_for_user_func=build_base_rule_map_for_user,
        user_menu_permission_model=UserMenuPermission,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        safe_rollback_func=_safe_rollback,
    )

def save_role_menu_defaults(role_name: str, all_menu_keys: list[str], visible_keys: set[str], *, updated_by_user_id: int | None = None) -> int:
    # B1-F1: the personnel_read_all grant is per-user only; role defaults never store it.
    return _save_role_menu_defaults_handler(
        role_name=role_name,
        all_menu_keys=without_personnel_read_all(all_menu_keys),
        visible_keys=set(without_personnel_read_all(visible_keys)),
        updated_by_user_id=updated_by_user_id,
        role_menu_default_model=RoleMenuDefault,
        db_session=db.session,
        filter_live_menu_keys_func=_filter_live_menu_keys,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        snapshot_role_menu_state_func=_snapshot_role_menu_state,
        build_complete_visibility_map_func=_build_complete_visibility_map,
        create_settings_change_log_func=_create_settings_change_log,
    )

def save_unit_menu_profile(unit_name: str, all_menu_keys: list[str], visible_keys: set[str], *, updated_by_user_id: int | None = None) -> int:
    # B1-F1: the personnel_read_all grant is per-user only; unit profiles never store it.
    return _save_unit_menu_profile_handler(
        unit_name=unit_name,
        all_menu_keys=without_personnel_read_all(all_menu_keys),
        visible_keys=set(without_personnel_read_all(visible_keys)),
        updated_by_user_id=updated_by_user_id,
        unit_menu_profile_model=UnitMenuProfile,
        db_session=db.session,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        filter_live_menu_keys_func=_filter_live_menu_keys,
        snapshot_unit_menu_state_func=_snapshot_unit_menu_state,
        build_complete_visibility_map_func=_build_complete_visibility_map,
        create_settings_change_log_func=_create_settings_change_log,
    )

def save_user_menu_overrides(
    user,
    flat_menu_items: list[dict[str, Any]],
    visible_keys: set[str],
    *,
    updated_by_user_id: int | None = None,
    allow_personnel_read_grant_change: bool = False,
) -> dict[str, int]:
    # B1-F1: personnel_read_all changes only on the explicit per-user save by ANOTHER user;
    # every other caller (template import, archive apply) leaves the existing row untouched.
    grant_change_allowed = bool(
        allow_personnel_read_grant_change
        and updated_by_user_id is not None
        and updated_by_user_id != getattr(user, "id", None)
    )
    return _save_user_menu_overrides_handler(
        preserved_menu_keys=() if grant_change_allowed else (PERSONNEL_READ_ALL_KEY,),
        user=user,
        flat_menu_items=flat_menu_items,
        visible_keys=visible_keys,
        updated_by_user_id=updated_by_user_id,
        user_menu_permission_model=UserMenuPermission,
        db_session=db.session,
        is_removed_menu_key_func=is_removed_menu_key,
        filter_live_menu_rows_func=_filter_live_menu_rows,
        filter_live_menu_keys_func=_filter_live_menu_keys,
        snapshot_user_override_state_func=_snapshot_user_override_state,
        build_base_rule_map_for_user_func=build_base_rule_map_for_user,
        create_settings_change_log_func=_create_settings_change_log,
    )

def clear_user_menu_overrides(
    user_id: int,
    *,
    updated_by_user_id: int | None = None,
    allow_personnel_read_grant_change: bool = False,
) -> int:
    # B1-F1: a reset removes the personnel_read_all grant only when an admin resets ANOTHER user.
    grant_change_allowed = bool(
        allow_personnel_read_grant_change and updated_by_user_id is not None and updated_by_user_id != user_id
    )
    return _clear_user_menu_overrides_handler(
        preserved_menu_keys=() if grant_change_allowed else (PERSONNEL_READ_ALL_KEY,),
        user_id=user_id,
        updated_by_user_id=updated_by_user_id,
        user_menu_permission_model=UserMenuPermission,
        db_session=db.session,
        create_settings_change_log_func=_create_settings_change_log,
    )

def build_settings_profile_context(selected_user=None, flat_menu_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _build_settings_profile_context_handler(
        selected_user=selected_user,
        flat_menu_items=flat_menu_items,
        flatten_menu_definitions_func=flatten_menu_definitions,
        unit_menu_profile_model=UnitMenuProfile,
        build_unit_profile_snapshot_func=_build_unit_profile_snapshot,
        build_effective_user_menu_context_func=build_effective_user_menu_context,
        list_recent_settings_change_logs_func=list_recent_settings_change_logs,
        safe_rollback_func=_safe_rollback,
    )

def build_settings_foundation_context() -> dict[str, Any]:
    return _build_settings_foundation_context_handler(
        table_exists=_table_exists,
        missing_settings_tables=_missing_settings_tables,
        system_setting_model=SystemSetting,
        module_setting_model=ModuleSetting,
        system_definitions=_normalized_system_setting_definitions(),
        iter_live_module_setting_definitions_func=_iter_live_module_setting_definitions,
        value_to_python=_value_to_python,
        build_role_default_snapshot=_build_role_default_snapshot,
        build_unit_profile_snapshot=_build_unit_profile_snapshot,
        list_recent_settings_change_logs_func=list_recent_settings_change_logs,
        role_menu_defaults=ROLE_MENU_DEFAULTS,
        safe_rollback=_safe_rollback,
    )

def save_system_settings_from_form(form, *, updated_by_user_id: int | None = None) -> int:
    """Genel sistem ayarlarını Faz 9 form pipeline servisi üzerinden kaydeder.

    Dış sözleşme korunur. Route/template tarafı aynı fonksiyon adını kullanmaya
    devam eder; kayıt detayı app.services.settings.form_pipeline modülündedir.
    """
    return _save_system_settings_from_form_handler(
        form,
        updated_by_user_id=updated_by_user_id,
        table_exists=_table_exists,
        system_definitions=_normalized_system_setting_definitions(),
        value_to_storage=_value_to_storage,
        snapshot_system_state=_snapshot_system_state,
        create_change_log=_create_settings_change_log,
    )


def save_module_settings_from_form(form, *, updated_by_user_id: int | None = None) -> int:
    """Modül ayarlarını Faz 9 form pipeline servisi üzerinden kaydeder.

    Canlı modül filtresi korunur; kaldırılmış modüller kayıt akışına yeniden
    sokulmaz.
    """
    return _save_module_settings_from_form_handler(
        form,
        updated_by_user_id=updated_by_user_id,
        table_exists=_table_exists,
        iter_live_module_setting_definitions=_iter_live_module_setting_definitions,
        value_to_storage=_value_to_storage,
        snapshot_module_state=_snapshot_module_state,
        create_change_log=_create_settings_change_log,
    )


def rollback_settings_change(log_id: int, *, actor_user_id: int | None = None) -> dict[str, Any]:
    """Ayar değişikliğini Faz 8 rollback handler servisi üzerinden geri alır.

    Dış sözleşme bilinçli olarak korunur. Route, template ve çağıran kodlar aynı
    fonksiyon adını kullanmaya devam eder; işlem detayı
    app.services.settings.rollback_handler modülüne taşınmıştır.
    """
    return _rollback_settings_change_handler(
        log_id,
        actor_user_id=actor_user_id,
        table_exists=_table_exists,
        system_definitions=_normalized_system_setting_definitions(),
        iter_live_module_setting_definitions=_iter_live_module_setting_definitions,
        value_to_storage=_value_to_storage,
        snapshot_system_state=_snapshot_system_state,
        snapshot_module_state=_snapshot_module_state,
        create_change_log=_create_settings_change_log,
        deserialize_state=_deserialize_state,
    )

# ---------------------------------------------------------------------------
# BYS360 Faz 5 menü izinleri servis köprüsü
# ---------------------------------------------------------------------------
def _snapshot_system_state() -> dict[str, str]:
    return _snapshot_system_settings_state(_normalized_system_setting_definitions())


def _snapshot_module_state() -> dict[str, dict[str, str]]:
    return _snapshot_module_settings_state(_iter_live_module_setting_definitions())

# ---------------------------------------------------------------------------
# BYS360 Faz 7 ayarlar tanılama / sağlık özeti servis köprüsü
# ---------------------------------------------------------------------------
def build_settings_diagnostics_context(*, include_recent_logs: bool = True, recent_limit: int = 8) -> dict[str, Any]:
    """Ayarlar servisinin canlı okuma ve tanılama özetini döndürür.

    Faz 7 bilinçli olarak kayıt/commit davranışına dokunmaz. Bu köprü;
    tablo varlığı, temel kayıt sayıları, canlı menü kayıt defteri ve son
    değişiklik geçmişi gibi bilgileri güvenli şekilde okunabilir hale getirir.
    """
    return _build_settings_diagnostics_context(
        include_recent_logs=include_recent_logs,
        recent_limit=recent_limit,
    )

# ---------------------------------------------------------------------------
# BYS360 Faz 10 ayarlar route/template cleanup kalite kapısı servis köprüsü
# ---------------------------------------------------------------------------
def build_settings_refactor_quality_snapshot() -> dict[str, Any]:
    """Faz 4-10 ayarlar servis parçalarının yan etkisiz kalite özetini döndürür."""
    return _build_settings_refactor_quality_snapshot()


def get_settings_refactor_phase_sequence() -> list[dict[str, str]]:
    """Ayarlar servisi refactor faz sırasını okunabilir liste olarak döndürür."""
    return _get_settings_refactor_phase_sequence()


def build_settings_template_guard_context(
    *,
    foundation_context: dict[str, Any] | None = None,
    profile_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Template tarafı için güvenli Faz 10 tanılama bağlamını döndürür."""
    return _build_settings_template_guard_context(
        foundation_context=foundation_context,
        profile_context=profile_context,
    )

# ---------------------------------------------------------------------------
# BYS360 Faz 11 ayarlar UI tanılama paneli servis köprüsü
# ---------------------------------------------------------------------------
def build_settings_ui_diagnostics_panel(
    *,
    foundation_context: dict[str, Any] | None = None,
    profile_context: dict[str, Any] | None = None,
    selected_user: Any | None = None,
) -> dict[str, Any]:
    """Ayarlar ekranı için yan etkisiz Faz 11 tanılama paneli bağlamını döndürür."""
    return _build_settings_ui_diagnostics_panel(
        foundation_context=foundation_context,
        profile_context=profile_context,
        selected_user=selected_user,
    )

# ---------------------------------------------------------------------------
# BYS360 Faz 12 final canlı sertleştirme / kapanış raporu servis köprüsü
# ---------------------------------------------------------------------------
def get_settings_final_release_checklist() -> list[dict[str, str]]:
    """Faz 12 canlı kapanış kontrol başlıklarını döndürür."""
    return _get_settings_final_release_checklist()


def build_settings_final_hardening_report(
    *,
    foundation_context: dict[str, Any] | None = None,
    profile_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ayarlar servisi final sertleştirme raporunu yan etkisiz üretir."""
    return _build_settings_final_hardening_report(
        foundation_context=foundation_context,
        profile_context=profile_context,
    )


def assert_settings_final_hardening_contract(
    *,
    foundation_context: dict[str, Any] | None = None,
    profile_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Faz 12 final sözleşmesini denetler ve raporu döndürür."""
    return _assert_settings_final_hardening_contract(
        foundation_context=foundation_context,
        profile_context=profile_context,
    )
