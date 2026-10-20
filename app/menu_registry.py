# BYS360_PHASE3_2_MENU_REGISTRY_NOTE: Performans menü görünürlüğünün son kararı app/services/settings/effective_menu.py içindeki PHASE3_2_PERFORMANCE_MENU_POLICY ile verilir.
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from typing import Any

from flask import url_for
from flask_login import current_user
from werkzeug.routing import BuildError

from app.live_scope import is_live_settings_menu_key

# BYS360 P11-D2: büyük güvenli menu registry veri blokları bridge import ile ayrıldı.
from app.menu_registry_data_performance import (
    _BYS360_PERFORMANCE_MAIN_SWITCH_ROLE_POLICY,
    ROLE_MENU_DEFAULTS,  # noqa: F821 - dynamic menu registry global
)
from app.menu_registry_data_personnel import (
    _BYS360_PERSONEL_ROLE_MATRIX_CURRENT_DISALLOWED_KEYS,
    _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_OBSOLETE_KEYS,
)

# BYS360 P11-D3: menü section veri blokları bridge import ile ayrıldı.
from app.menu_registry_data_sections import (
    MENU_SECTIONS,  # noqa: F821 - dynamic menu registry global
)

"""BYS360 yan menü sicili.

Personel – .
Burasi benim en gurur duydugum taraflardan biri. Hem rol bazli hem kisi bazli
menu gorunurlugunu ayni yerde tutuyor. Son 10 gunde aceleyle ekledigim bir iki
blok da bilerek duruyor; gercek proje izi silinmesin istedim.
"""

MENU_KEY_CANONICAL_MAP = {
    "performance_hierarchy": "performance_hierarchy_tree",
    "performance_assignments": "performance_hierarchy_assignments",
}

MENU_KEY_ALIASES = {
    "performance_hierarchy_tree": {"performance_hierarchy"},
    "performance_hierarchy": {"performance_hierarchy_tree"},
    "performance_hierarchy_assignments": {"performance_assignments"},
    "performance_assignments": {"performance_hierarchy_assignments"},
}

# BYS360_PERSONNEL_MANAGEMENT_MENU_HIDE_V1_START
# Standart personel/kullanıcı tarafında Personel Yönetimi ana menüsü görünmez.
# Bu yalnızca sidebar görünürlüğüdür; login/auth/DB akışına dokunmaz.
PERSONNEL_MANAGEMENT_SECTION_KEYS = {"ik"}
PERSONNEL_MANAGEMENT_ALLOWED_ROLES = {
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "koordinator",
    "birim_sorumlusu",
}
# BYS360_PERSONNEL_MANAGEMENT_MENU_HIDE_V1_END

# BYS360 P11-D3: MENU_SECTIONS veri bloğu data modülüne taşındı.

# BYS360_PRESIDENT_APPROVALS_FORCE_VISIBLE_MENU
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})
FORCE_VISIBLE_MENU_ROLES.setdefault("performance_president_approvals", {"admin", "baskan"})  # noqa: F821 - dynamic menu registry global
# /BYS360_PRESIDENT_APPROVALS_FORCE_VISIBLE_MENU

def get_equivalent_menu_keys(menu_key: str) -> set[str]:
    key = (menu_key or "").strip()
    if not key:
        return set()
    canonical = MENU_KEY_CANONICAL_MAP.get(key, key)
    keys = {canonical, key}
    keys.update(MENU_KEY_ALIASES.get(canonical, set()))
    keys.update(MENU_KEY_ALIASES.get(key, set()))
    return {item for item in keys if item}

def get_role_default_menu_keys(role_name: str) -> set[str]:
    normalized = (role_name or "").strip().lower()
    return set(ROLE_MENU_DEFAULTS.get(normalized, {"home", "account", "logout"}))  # noqa: F821 - dynamic menu registry global

def get_expanded_role_menu_keys(role_name: str) -> set[str]:
    expanded: set[str] = set()
    for key in get_role_default_menu_keys(role_name):
        expanded.update(get_equivalent_menu_keys(key))
    return expanded

def get_grouped_menu_definitions() -> OrderedDict[str, list[dict[str, Any]]]:
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global
        section_items: list[dict[str, Any]] = []
        for item in section["items"]:
            if not item.get("show_in_settings", True):
                continue
            settings_key = item.get("settings_key") or item.get("key")
            if not is_live_settings_menu_key(settings_key):
                continue
            section_items.append(deepcopy(item))
        if section_items:
            grouped[section["label"]] = section_items
    return grouped

def flatten_menu_definitions() -> list[dict[str, Any]]:
    flat_items: list[dict[str, Any]] = []
    for group_name, items in get_grouped_menu_definitions().items():
        for item in items:
            row = deepcopy(item)
            row["group"] = group_name
            flat_items.append(row)
    return flat_items

def _matches_visibility(item: dict[str, Any], menu_visibility_map: dict[str, bool]) -> bool:
    # BYS360_SETTINGS_LIVE_AUTHORITY_V1: Hiçbir menü ayarlar haritasını bypass ederek görünmez.
    permission_keys = item.get("permission_keys") or [item.get("settings_key") or item.get("key")]
    for permission_key in permission_keys:
        for equivalent_key in get_equivalent_menu_keys(permission_key):
            if menu_visibility_map.get(equivalent_key, False):
                return True
    return False

def _normalize_role_value(value: Any) -> str:
    # BYS360 DEFECT AQ: 'İ'.lower() Python'da tek bir 'i' değil, 'i' +
    # COMBINING DOT ABOVE (U+0307) olmak üzere İKİ kod noktası üretir --
    # bu yüzden .lower() önce çalışırsa aşağıdaki tr_map'teki 'İ' anahtarı
    # asla eşleşmez. 'İ' burada .lower() çağrılmadan ÖNCE, tek kod noktalı
    # haldeyken ayrı olarak 'i'ye çevrilir.
    raw = str(value or "").strip().replace("İ", "i").lower()
    tr_map = str.maketrans("çğıöşüâîû", "cgiosuaiu")
    return raw.translate(tr_map).replace(" ", "_").replace("-", "_")

def _is_president_approvals_authorized_user(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return True
    # D3/R05: the job title (unvan/title) never grants president approvals.
    role_values = {
        _normalize_role_value(getattr(user, attr, ""))
        for attr in ("role", "role_name", "user_type")
    }
    admin_values = {"admin", "super_admin", "system_admin", "sistem_yoneticisi"}
    president_values = {"baskan", "president"}
    return bool(role_values & admin_values) or bool(role_values & president_values)

def _matches_role(item: dict[str, Any], user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if item.get("key") == "performance_president_approvals":
        return _is_president_approvals_authorized_user(user)
    role_name = _normalize_role_value(getattr(user, "role", ""))
    if item.get("admin_only") and not (
        role_name == "admin"
        or bool(getattr(user, "is_admin", False))
        or bool(getattr(user, "is_superuser", False))
    ):
        return False
    required_roles = item.get("required_roles")
    return not (required_roles and role_name not in {_normalize_role_value(r) for r in required_roles})

def _resolve_href(item: dict[str, Any]) -> str:
    if item.get("href"):
        return item["href"]
    endpoint = item.get("endpoint")
    if endpoint:
        try:
            return url_for(endpoint)
        except BuildError:
            return "javascript:void(0)"
    return "javascript:void(0)"

def _is_active(item: dict[str, Any], current_endpoint: str, current_path: str) -> bool:
    if current_endpoint and current_endpoint in set(item.get("active_endpoints") or []):
        return True

    for prefix in item.get("active_endpoint_prefixes") or []:
        if current_endpoint and current_endpoint.startswith(prefix):
            return True

    for prefix in item.get("active_path_prefixes") or []:
        if current_path and current_path.startswith(prefix):
            return True

    return False

def _resolve_badge(item: dict[str, Any], runtime_context: dict[str, Any]) -> Any:
    dynamic_badge = item.get("dynamic_badge")
    if dynamic_badge:
        return runtime_context.get(dynamic_badge, 0)
    return item.get("badge_value")

def _build_sidebar_menu_sections_base(menu_visibility_map: dict[str, bool], current_endpoint: str, current_path: str, runtime_context: dict[str, Any] | None = None, user=None) -> list[dict[str, Any]]:
    runtime_context = runtime_context or {}
    user = user or current_user
    (getattr(user, "role", "") or "").strip().lower()
    sections: list[dict[str, Any]] = []

    for section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global

        # BYS360_SETTINGS_LIVE_AUTHORITY_V2: Bölüm/rol sabitleri rol matrisini gölgeleyemez.
        # Bir bölümde en az bir menu_map=true satırı varsa bölüm görünür.
        visible_items: list[dict[str, Any]] = []

        for raw_item in section["items"]:
            item = deepcopy(raw_item)
            # V2: Önce ayarlar haritası kontrol edilir. Rol matrisi true ise
            # required_roles/admin_only gibi eski kayıt defteri şartları menünün
            # eklenmesini engellemez; gerçek erişim route tarafında ayrıca korunur.
            if not _matches_visibility(item, menu_visibility_map):
                continue

            item["href"] = _resolve_href(item)
            item["active"] = _is_active(item, current_endpoint=current_endpoint, current_path=current_path)
            item["badge_value"] = _resolve_badge(item, runtime_context)
            visible_items.append(item)

        if not visible_items:
            continue

        sections.append(
            {
                "key": section["key"],
                "label": section["label"],
                "icon": section["icon"],
                "items": visible_items,
                "is_open": any(item.get("active") for item in visible_items),
            }
        )

    return sections


# Faz 8 - Performans Süreç Takibi menü tanımı
PERFORMANCE_PROCESS_TRACKING_MENU_ITEM = {
    'key': 'performance_process_tracking',
    'label': 'Süreç Takibi',
    'title': 'Süreç Takibi',
    'endpoint': 'main.performance_process_tracking',
    'url': '/performans/surec-takibi',
    'module': 'performance',
}
# BYS360 Faz 10 görünürlük anahtarı: performance_process_reports
# BYS360 Faz 10 menü etiketi: Süreç Raporları

# BYS360_PRESIDENT_MENU_CARD_HISTORY_STATUS_FINAL_V1


# BYS360_INTERIM_NOTES_MANAGER_MENU_REGISTRY
# performance_interim_notes -> Dönem İçi Notlar

# BYS360_PHASE10_DEVELOPMENT_GUIDANCE_FORCE_VISIBLE
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})
FORCE_VISIBLE_MENU_ROLES.setdefault("performance_development_guidance", {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"})  # noqa: F821 - dynamic menu registry global
# /BYS360_PHASE10_DEVELOPMENT_GUIDANCE_FORCE_VISIBLE


# BYS360_PHASE9_REMINDERS_FORCE_VISIBLE
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})
FORCE_VISIBLE_MENU_ROLES.setdefault("performance_meeting_p3_reminders", {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"})  # noqa: F821 - dynamic menu registry global
# /BYS360_PHASE9_REMINDERS_FORCE_VISIBLE

# BYS360_SETTINGS_MANUAL_V1_MENU_REGISTRY_BEGIN
_BYS360_MANUAL_ROLE_MENU_ADDITIONS = {'admin': ['performance_archive', 'performance_process_tracking', 'performance_process_reports', 'performance_personnel_support_publish_approval'], 'baskan': ['performance_archive', 'performance_process_tracking', 'performance_process_reports'], 'baskan_yardimcisi': ['performance_archive', 'performance_process_tracking', 'performance_process_reports'], 'grup_baskani': ['performance_archive', 'performance_process_tracking', 'performance_process_reports', 'performance_personnel_support_publish_approval'], 'mali_musavir': ['performance_archive', 'performance_process_tracking', 'performance_process_reports'], 'koordinator': ['performance_archive', 'performance_process_tracking', 'performance_process_reports'], 'birim_sorumlusu': ['performance_archive', 'performance_process_tracking', 'performance_process_reports'], 'personel': ['performance_archive']}
_BYS360_MANUAL_MENU_ITEMS = [{'key': 'performance_process_tracking', 'label': 'Süreç Takibi', 'icon': 'fa-solid fa-route', 'endpoint': 'main.performance_process_tracking', 'active_path_prefixes': ['/performance/process-tracking', '/performans/surec-takibi'], 'required_roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu']}, {'key': 'performance_process_reports', 'label': 'Süreç Raporları', 'icon': 'fa-solid fa-chart-line', 'endpoint': 'main.performance_process_reports', 'active_path_prefixes': ['/performance/process-reports', '/performans/surec-raporlari'], 'required_roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu']}, {'key': 'performance_personnel_support_publish_approval', 'label': 'Yayın Ön Onayı', 'icon': 'fa-solid fa-user-check', 'endpoint': 'main.performance_personnel_support_publish_approvals', 'active_path_prefixes': ['/performance/personnel-support-publish-approvals', '/performans/personel-destek-yayin-onayi'], 'required_roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'grup_baskani']}]

for _role, _keys in _BYS360_MANUAL_ROLE_MENU_ADDITIONS.items():
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update(_keys)
    elif isinstance(_current, list):
        _current.extend([_k for _k in _keys if _k not in _current])

FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})  # noqa: F821 - dynamic menu registry global

for _role, _keys in _BYS360_MANUAL_ROLE_MENU_ADDITIONS.items():
    for _key in _keys:
        FORCE_VISIBLE_MENU_ROLES.setdefault(_key, set()).add(_role)  # noqa: F821 - dynamic menu registry global

def _bys360_manual_add_menu_item_to_list(_target):
    if not isinstance(_target, list):
        return
    _existing = {_item.get("key") for _item in _target if isinstance(_item, dict)}
    for _item in _BYS360_MANUAL_MENU_ITEMS:
        if _item.get("key") not in _existing:
            _target.append(dict(_item))
            _existing.add(_item.get("key"))

for _list_name in ["MENU_ITEMS", "PERFORMANCE_MENU_ITEMS", "NAV_ITEMS", "MENU_REGISTRY"]:
    _target = globals().get(_list_name)
    if isinstance(_target, list):
        _bys360_manual_add_menu_item_to_list(_target)
    elif isinstance(_target, dict):
        for _item in _BYS360_MANUAL_MENU_ITEMS:
            _target.setdefault(_item["key"], dict(_item))
# BYS360_SETTINGS_MANUAL_V1_MENU_REGISTRY_END

# BYS360_PROCESS_TRACKING_REPORTS_MENU_REGISTRY_V1_BEGIN
_BYS360_PROCESS_MENU_ITEMS = [
    {
        "key": "performance_process_tracking",
        "label": "Süreç Takibi",
        "icon": "fa-solid fa-route",
        "endpoint": "main.performance_process_tracking",
        "url": "/performance/process-tracking",
        "active_path_prefixes": ["/performance/process-tracking"],
        "required_roles": ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu'],
    },
    {
        "key": "performance_process_reports",
        "label": "Süreç Raporları",
        "icon": "fa-solid fa-chart-line",
        "endpoint": "main.performance_process_reports",
        "url": "/performance/process-reports",
        "active_path_prefixes": ["/performance/process-reports"],
        "required_roles": ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu'],
    },
]

ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global

for _role in ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu']:
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    for _key in ['performance_process_tracking', 'performance_process_reports']:
        if isinstance(_current, set):
            _current.add(_key)
        elif isinstance(_current, list) and _key not in _current:
            _current.append(_key)

for _list_name in ["MENU_ITEMS", "PERFORMANCE_MENU_ITEMS", "NAV_ITEMS", "MENU_REGISTRY"]:
    _target = globals().get(_list_name)
    if isinstance(_target, list):
        _existing = {_item.get("key") for _item in _target if isinstance(_item, dict)}
        for _item in _BYS360_PROCESS_MENU_ITEMS:
            if _item["key"] not in _existing:
                _target.append(dict(_item))
                _existing.add(_item["key"])
    elif isinstance(_target, dict):
        for _item in _BYS360_PROCESS_MENU_ITEMS:
            _target.setdefault(_item["key"], dict(_item))
# BYS360_PROCESS_TRACKING_REPORTS_MENU_REGISTRY_V1_END

# BYS360_PERFORMANCE_ROLE_MATRIX_NEW_TABS_V1_MENU_REGISTRY_BEGIN
_BYS360_PERFORMANCE_ROLE_MATRIX_NEW_TABS = [{'key': 'performance_process_tracking', 'label': 'Süreç Takibi', 'icon': 'fa-solid fa-route', 'url': '/performance/process-tracking', 'endpoint': 'main.performance_process_tracking', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu'], 'group': 'Performans Yönetimi', 'order': 610}, {'key': 'performance_process_reports', 'label': 'Süreç Raporları', 'icon': 'fa-solid fa-chart-line', 'url': '/performance/process-reports', 'endpoint': 'main.performance_process_reports', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu'], 'group': 'Performans Yönetimi', 'order': 620}, {'key': 'performance_interim_notes', 'label': 'Dönem İçi Notlar', 'icon': 'fa-solid fa-clipboard-list', 'url': '/performance/interim-notes', 'endpoint': 'main.performance_interim_notes_tr', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu'], 'group': 'Performans Yönetimi', 'order': 630}, {'key': 'performance_development_guidance', 'label': 'Gelişim Rehberi', 'icon': 'fa-solid fa-seedling', 'url': '/performance/meeting-development/faz10', 'endpoint': 'main.performance_meeting_p4_development_guidance', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu'], 'group': 'Performans Yönetimi', 'order': 640}, {'key': 'performance_meeting_p3_reminders', 'label': 'Hatırlatma ve Aksatan Amirler', 'icon': 'fa-solid fa-bell', 'url': '/performance/meeting-development/faz9', 'endpoint': 'main.performance_meeting_p3_reminders', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu'], 'group': 'Performans Yönetimi', 'order': 650}, {'key': 'performance_archive', 'label': 'Geçmiş Karne Arşivi', 'icon': 'fa-solid fa-box-archive', 'url': '/performance/archive', 'endpoint': 'main.performance_archive', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'], 'group': 'Performans Yönetimi', 'order': 660}, {'key': 'performance_personnel_support_publish_approval', 'label': 'Yayın Ön Onayı', 'icon': 'fa-solid fa-user-check', 'url': '/performance/personnel-support-publish-approvals', 'endpoint': 'main.performance_personnel_support_publish_approvals', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'grup_baskani'], 'group': 'Performans Yönetimi', 'order': 670}, {'key': 'performance_president_approvals', 'label': 'Başkan Onayları', 'icon': 'fa-solid fa-stamp', 'url': '/performance/president-approvals', 'endpoint': 'main.performance_president_approvals', 'roles': ['admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'baskan'], 'group': 'Performans Yönetimi', 'order': 680}]

ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global

for _item in _BYS360_PERFORMANCE_ROLE_MATRIX_NEW_TABS:
    _key = _item["key"]
    for _role in _item.get("roles", []):
        _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
        if isinstance(_current, set):
            _current.add(_key)
        elif isinstance(_current, list) and _key not in _current:
            _current.append(_key)

for _list_name in ["MENU_ITEMS", "PERFORMANCE_MENU_ITEMS", "NAV_ITEMS", "MENU_REGISTRY", "ROLE_MATRIX_MENU_ITEMS"]:
    _target = globals().get(_list_name)

    if isinstance(_target, list):
        _existing = {_row.get("key") for _row in _target if isinstance(_row, dict)}
        for _item in _BYS360_PERFORMANCE_ROLE_MATRIX_NEW_TABS:
            if _item["key"] not in _existing:
                _target.append(dict(_item))
                _existing.add(_item["key"])

    elif isinstance(_target, dict):
        for _item in _BYS360_PERFORMANCE_ROLE_MATRIX_NEW_TABS:
            _target.setdefault(_item["key"], dict(_item))
# BYS360_PERFORMANCE_ROLE_MATRIX_NEW_TABS_V1_MENU_REGISTRY_END


# BYS360_SETTINGS_MODULE_ROLE_MATRIX_V12_MENU_SECTION_SYNC_BEGIN
# Ayarlar > Modül Bazlı Rol Matrisleri ve sidebar aynı canlı performans satırlarını görsün.
_BYS360_ROLE_MATRIX_V12_PERFORMANCE_MENU_ITEMS = [
    {
        "key": "performance_process_tracking",
        "label": "Süreç Takibi",
        "icon": "fa-solid fa-route",
        "endpoint": "main.performance_process_tracking",
        "active_path_prefixes": ["/performance/process-tracking", "/performans/surec-takibi"],
        "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"],
    },
    {
        "key": "performance_process_reports",
        "label": "Süreç Raporları",
        "icon": "fa-solid fa-chart-line",
        "endpoint": "main.performance_process_reports",
        "active_path_prefixes": ["/performance/process-reports", "/performans/surec-raporlari"],
        "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"],
    },
    {
        "key": "performance_personnel_support_publish_approval",
        "label": "Yayın Ön Onayı",
        "icon": "fa-solid fa-user-check",
        "endpoint": "main.performance_personnel_support_publish_approvals",
        "active_path_prefixes": ["/performance/personnel-support-publish-approvals", "/performans/personel-destek-yayin-onayi"],
        "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "grup_baskani"],
    },
]

try:
    _performance_section = next((_section for _section in MENU_SECTIONS if _section.get("key") == "performans"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_performance_section, dict):
        _items = _performance_section.setdefault("items", [])
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        for _item in _BYS360_ROLE_MATRIX_V12_PERFORMANCE_MENU_ITEMS:
            if _item["key"] not in _existing:
                _items.append(dict(_item))
                _existing.add(_item["key"])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1260)")

ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global

_BYS360_ROLE_MATRIX_V12_ROLE_DEFAULTS = {
    "admin": {"performance_process_tracking", "performance_process_reports", "performance_personnel_support_publish_approval"},
    "baskan": {"performance_process_tracking", "performance_process_reports"},
    "baskan_yardimcisi": {"performance_process_tracking", "performance_process_reports"},
    "grup_baskani": {"performance_process_tracking", "performance_process_reports", "performance_personnel_support_publish_approval"},
    "mali_musavir": {"performance_process_tracking", "performance_process_reports"},
    "koordinator": {"performance_process_tracking", "performance_process_reports"},
    "birim_sorumlusu": {"performance_process_tracking", "performance_process_reports"},
}
for _role, _keys in _BYS360_ROLE_MATRIX_V12_ROLE_DEFAULTS.items():
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update(_keys)
    elif isinstance(_current, list):
        _current.extend([_key for _key in _keys if _key not in _current])
# BYS360_SETTINGS_MODULE_ROLE_MATRIX_V12_MENU_SECTION_SYNC_END

# BYS360_MAINTENANCE_V13_REMOVED_MENU_FILTER_BEGIN
# Maintenance v13 P0 canlı kapısı: eğitim/portal/repository/strategy gibi kapsam dışı
# modül izleri sidebar, ayarlar menü listesi ve force-visible haritasından süzülür.
_BYS360_V13_REMOVED_DIRECT_MENU_KEYS = {"education", "egitim", "eğitim", "repository", "strategy", "strateji"}


def _bys360_v13_text(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _bys360_v13_value_is_removed_menu_key(value) -> bool:
    key = _bys360_v13_text(value)
    if not key:
        return False
    if key in _BYS360_V13_REMOVED_DIRECT_MENU_KEYS:
        return True
    try:
        from app.config import is_removed_menu_key
        return bool(is_removed_menu_key(key))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:467")
        return key.startswith(("education_", "egitim_", "strategy_", "repository_", "isg_"))


def _bys360_v13_value_is_removed_endpoint(value) -> bool:
    endpoint = str(value or "").strip()
    if not endpoint:
        return False
    try:
        from app.config import is_removed_route_endpoint
        if is_removed_route_endpoint(endpoint):
            return True
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1316)")
    return any(token in endpoint.lower() for token in (".education_", ".strategy_", ".repository_"))


def _bys360_v13_value_is_removed_path(value) -> bool:
    path = str(value or "").strip()
    if not path:
        return False
    try:
        from app.config import is_removed_route_path
        if is_removed_route_path(path):
            return True
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1329)")
    lowered = path.lower()
    return lowered.startswith(("/education", "/education-isg", "/egitim-isg", "/isg", "/strategy", "/repository"))


def _bys360_v13_is_removed_menu_item(item: dict) -> bool:
    keys = [item.get("key"), item.get("settings_key")]
    keys.extend(item.get("permission_keys") or [])
    if any(_bys360_v13_value_is_removed_menu_key(key) for key in keys):
        return True
    endpoints = [item.get("endpoint")]
    endpoints.extend(item.get("active_endpoints") or [])
    endpoints.extend(item.get("active_endpoint_prefixes") or [])
    if any(_bys360_v13_value_is_removed_endpoint(endpoint) for endpoint in endpoints):
        return True
    paths = [item.get("href")]
    paths.extend(item.get("active_path_prefixes") or [])
    return any(_bys360_v13_value_is_removed_path(path) for path in paths)


def _bys360_v13_prune_removed_menu_registry() -> None:
    try:
        for role_name, keys in list(ROLE_MENU_DEFAULTS.items()):  # noqa: F821 - dynamic menu registry global
            ROLE_MENU_DEFAULTS[role_name] = {key for key in set(keys) if not _bys360_v13_value_is_removed_menu_key(key)}  # noqa: F821 - dynamic menu registry global
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1356)")
    try:
        for section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global
            section["items"] = [item for item in list(section.get("items") or []) if not _bys360_v13_is_removed_menu_item(item)]
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1361)")
    try:
        for key in list(FORCE_VISIBLE_MENU_ROLES.keys()):  # noqa: F821 - dynamic menu registry global
            if _bys360_v13_value_is_removed_menu_key(key):
                FORCE_VISIBLE_MENU_ROLES.pop(key, None)  # noqa: F821 - dynamic menu registry global
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1367)")


_bys360_v13_prune_removed_menu_registry()
# BYS360_MAINTENANCE_V13_REMOVED_MENU_FILTER_END
# BYS360_AY1_AI_PERFORMANCE_SETTINGS_INTEGRATION_V1_BEGIN
# Ayarlar/Rol Matrisi ile sidebar aynı BYS360 Asistanı ve performans sekme anahtarlarını görsün.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2, Blocker 2 --
# duplicate menu key closure): this list used to carry its own "ai_agent_panel"
# item (label "BYS360 Asistanı") into the "genel" section. That was a genuine,
# pre-existing duplicate of the "assistant" section's own "ai_agent_panel"
# item (label "Asistan Paneli", added later by the
# BYS360_ASSISTANT_TABS_ROLE_MATRIX_V2 block below) -- both resolved to the
# exact same endpoint (ai_agent.ai_agent_panel) and href (/ai-agent/panel),
# and by the time _BYS360_ALL_MENU_ROLE_MATRIX_MENU_ATTRS's override ran,
# both already carried the identical effective required_roles set. Two
# sidebar entries under one key pointing at one page is not two capabilities,
# it is one capability registered twice. Removed the "genel" section's copy
# (this list) and kept the "assistant" section's copy, since it sits
# correctly grouped with its sibling assistant_module/ai_agent_knowledge/
# ai_agent_teaching_center items. No required_roles change: the surviving
# "assistant" section item already carried the same effective role set this
# list's item resolved to, so no role gains or loses visibility.
_BYS360_AY1_AI_AGENT_MENU_ITEMS: list[dict] = []

_BYS360_AY1_PERFORMANCE_MENU_ITEMS = [
    {"key": "performance_president_approvals", "label": "Başkan Onayları", "icon": "fa-solid fa-stamp", "endpoint": "main.performance_president_approvals", "href": "/performance/president-approvals", "active_path_prefixes": ["/performance/president-approvals"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan"]},
    {"key": "performance_personnel_support_publish_approval", "label": "Yayın Ön Onayı", "icon": "fa-solid fa-user-check", "endpoint": "main.performance_personnel_support_publish_approvals", "href": "/performance/personnel-support-publish-approvals", "active_path_prefixes": ["/performance/personnel-support-publish-approvals", "/performans/personel-destek-yayin-onayi"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "grup_baskani"]},
    {"key": "performance_process_tracking", "label": "Süreç Takibi", "icon": "fa-solid fa-route", "endpoint": "main.performance_process_tracking", "href": "/performance/process-tracking", "active_path_prefixes": ["/performance/process-tracking", "/performans/surec-takibi"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_process_reports", "label": "Süreç Raporları", "icon": "fa-solid fa-chart-line", "endpoint": "main.performance_process_reports", "href": "/performance/process-reports", "active_path_prefixes": ["/performance/process-reports", "/performans/surec-raporlari"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_interim_notes", "label": "Dönem İçi Notlar", "icon": "fa-regular fa-note-sticky", "endpoint": "main.performance_interim_notes", "href": "/performance/interim-notes", "active_path_prefixes": ["/performance/interim-notes"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_development_guidance", "label": "Gelişim Rehberi", "icon": "fa-solid fa-seedling", "endpoint": "main.performance_meeting_p4_development_guidance", "href": "/performance/meeting-development/faz10", "active_path_prefixes": ["/performance/meeting-development/faz10", "/performans/gelisim-rehberi"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_meeting_p3_reminders", "label": "Hatırlatma ve Aksatan Amirler", "icon": "fa-solid fa-bell", "endpoint": "main.performance_meeting_p3_reminders", "href": "/performance/meeting-development/faz9", "active_path_prefixes": ["/performance/meeting-development/faz9", "/performans/toplanti-gelistirme/faz9-hatirlatma"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_archive", "label": "Geçmiş Karne Arşivi", "icon": "fa-solid fa-box-archive", "endpoint": "main.performance_archive", "href": "/performance/archive", "active_path_prefixes": ["/performance/archive", "/performans/gecmis-karne-arsivi"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"]},
    {"key": "performance_kpi_dashboard", "label": "KPI Dashboard", "icon": "fa-solid fa-gauge-high", "endpoint": "strategic_performance.dashboard", "href": "/strategic-performance", "active_path_prefixes": ["/strategic-performance"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_kpi_management", "label": "KPI / Hedef Yönetimi", "icon": "fa-solid fa-bullseye", "endpoint": "strategic_performance.targets", "href": "/strategic-performance/targets", "active_path_prefixes": ["/strategic-performance/targets"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator"]},
    {"key": "performance_competency_library", "label": "Yetkinlik Kütüphanesi", "icon": "fa-solid fa-layer-group", "endpoint": "strategic_performance.competencies", "href": "/strategic-performance/competencies", "active_path_prefixes": ["/strategic-performance/competencies"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_self_assessment", "label": "Öz Değerlendirme", "icon": "fa-solid fa-user-pen", "endpoint": "strategic_performance.self_assessment", "href": "/strategic-performance/self-assessment", "active_path_prefixes": ["/strategic-performance/self-assessment"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"]},
    {"key": "performance_kpi_analysis", "label": "KPI Analizi", "icon": "fa-solid fa-chart-pie", "endpoint": "strategic_performance.kpi_analysis", "href": "/strategic-performance/kpi-analysis", "active_path_prefixes": ["/strategic-performance/kpi-analysis"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator"]},
]

try:
    _genel_section = next((_section for _section in MENU_SECTIONS if _section.get("key") == "genel"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_genel_section, dict):
        _items = _genel_section.setdefault("items", [])
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        for _item in _BYS360_AY1_AI_AGENT_MENU_ITEMS:
            if _item["key"] not in _existing:
                _items.append(dict(_item))
                _existing.add(_item["key"])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1412)")

try:
    _performance_section = next((_section for _section in MENU_SECTIONS if _section.get("key") == "performans"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_performance_section, dict):
        _items = _performance_section.setdefault("items", [])
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        for _item in _BYS360_AY1_PERFORMANCE_MENU_ITEMS:
            if _item["key"] not in _existing:
                _items.append(dict(_item))
                _existing.add(_item["key"])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1424)")

ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global

_BYS360_AY1_ROLE_DEFAULTS = {
    "admin": {"ai_agent_panel", "performance_president_approvals", "performance_personnel_support_publish_approval", "performance_process_tracking", "performance_process_reports", "performance_interim_notes", "performance_development_guidance", "performance_meeting_p3_reminders", "performance_archive", "performance_kpi_dashboard", "performance_kpi_management", "performance_competency_library", "performance_self_assessment", "performance_kpi_analysis"},
    "baskan": {"ai_agent_panel", "performance_president_approvals", "performance_process_tracking", "performance_process_reports", "performance_interim_notes", "performance_development_guidance", "performance_meeting_p3_reminders", "performance_archive", "performance_kpi_dashboard", "performance_kpi_management", "performance_competency_library", "performance_self_assessment", "performance_kpi_analysis"},
    "baskan_yardimcisi": {"ai_agent_panel", "performance_process_tracking", "performance_process_reports", "performance_interim_notes", "performance_development_guidance", "performance_meeting_p3_reminders", "performance_archive", "performance_kpi_dashboard", "performance_kpi_management", "performance_competency_library", "performance_self_assessment", "performance_kpi_analysis"},
    "grup_baskani": {"ai_agent_panel", "performance_personnel_support_publish_approval", "performance_process_tracking", "performance_process_reports", "performance_interim_notes", "performance_development_guidance", "performance_meeting_p3_reminders", "performance_archive", "performance_kpi_dashboard", "performance_kpi_management", "performance_competency_library", "performance_self_assessment", "performance_kpi_analysis"},
    "mali_musavir": {"ai_agent_panel", "performance_process_tracking", "performance_process_reports", "performance_interim_notes", "performance_development_guidance", "performance_meeting_p3_reminders", "performance_archive", "performance_kpi_dashboard", "performance_kpi_management", "performance_competency_library", "performance_self_assessment", "performance_kpi_analysis"},
    "koordinator": {"ai_agent_panel", "performance_process_tracking", "performance_process_reports", "performance_interim_notes", "performance_development_guidance", "performance_meeting_p3_reminders", "performance_archive", "performance_kpi_dashboard", "performance_kpi_management", "performance_competency_library", "performance_self_assessment", "performance_kpi_analysis"},
    "birim_sorumlusu": {"ai_agent_panel", "performance_process_tracking", "performance_process_reports", "performance_interim_notes", "performance_development_guidance", "performance_meeting_p3_reminders", "performance_archive", "performance_kpi_dashboard", "performance_competency_library", "performance_self_assessment"},
    "personel": {"ai_agent_panel", "performance_archive", "performance_self_assessment"},
}

for _role, _keys in _BYS360_AY1_ROLE_DEFAULTS.items():
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update(_keys)
    elif isinstance(_current, list):
        _current.extend([_key for _key in _keys if _key not in _current])

FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})  # noqa: F821 - dynamic menu registry global

for _role, _keys in _BYS360_AY1_ROLE_DEFAULTS.items():
    for _key in _keys:
        FORCE_VISIBLE_MENU_ROLES.setdefault(_key, set()).add(_role)  # noqa: F821 - dynamic menu registry global
# BYS360_AY1_AI_PERFORMANCE_SETTINGS_INTEGRATION_V1_END


# BYS360_SETTINGS_LIVE_AUTHORITY_V1_REGISTRY_BEGIN
# Rol matrisi ve base.html aynı anahtarları görsün diye görüşme sonrası performans ekranları da
# ayarlar kataloguna eklenir. Bu blok yalnızca eksikse ekler; mevcut kayıtları bozmaz.
_BYS360_SETTINGS_V1_FEEDBACK_MENU_ITEMS = [
    {"key": "performance_feedback_aftercare", "label": "Görüşme Sonrası Notlar", "icon": "fa-solid fa-clipboard-check", "endpoint": "main.performance_feedback_aftercare", "href": "/performance/feedback-aftercare", "active_path_prefixes": ["/performance/feedback-aftercare", "/performans/gorusme-sonrasi-notlar"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_feedback_aftercare_new", "label": "Personel ve Dönem Görüşmesi", "icon": "fa-solid fa-user-clock", "endpoint": "main.performance_feedback_aftercare_new", "href": "/performance/feedback-aftercare/new", "active_path_prefixes": ["/performance/feedback-aftercare/new", "/performans/gorusme-sonrasi-notlar/yeni"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_feedback_meeting_guide", "label": "Geri Bildirim Rehberi", "icon": "fa-solid fa-comments", "endpoint": "main.performance_feedback_meeting_guide", "href": "/performance/feedback-meeting-guide", "active_path_prefixes": ["/performance/feedback-meeting-guide", "/performans/geri-bildirim-gorusme-rehberi"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_feedback_followup", "label": "Eylem Planı Takibi", "icon": "fa-solid fa-calendar-check", "endpoint": "main.performance_feedback_followup", "href": "/performance/feedback-followup", "active_path_prefixes": ["/performance/feedback-followup", "/performans/eylem-plani-takibi"], "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
]
try:
    _performance_section = next((_section for _section in MENU_SECTIONS if _section.get("key") == "performans"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_performance_section, dict):
        _items = _performance_section.setdefault("items", [])
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        for _item in _BYS360_SETTINGS_V1_FEEDBACK_MENU_ITEMS:
            if _item["key"] not in _existing:
                _items.append(dict(_item))
                _existing.add(_item["key"])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1479)")

_BYS360_SETTINGS_V1_ROLE_ADDITIONS = {
    "admin": {"performance_feedback_aftercare", "performance_feedback_aftercare_new", "performance_feedback_meeting_guide", "performance_feedback_followup"},
    "baskan": {"performance_feedback_aftercare", "performance_feedback_aftercare_new", "performance_feedback_meeting_guide", "performance_feedback_followup"},
    "baskan_yardimcisi": {"performance_feedback_aftercare", "performance_feedback_aftercare_new", "performance_feedback_meeting_guide", "performance_feedback_followup"},
    "grup_baskani": {"performance_feedback_aftercare", "performance_feedback_aftercare_new", "performance_feedback_meeting_guide", "performance_feedback_followup"},
    "mali_musavir": {"performance_feedback_aftercare", "performance_feedback_aftercare_new", "performance_feedback_meeting_guide", "performance_feedback_followup"},
    "koordinator": {"performance_feedback_aftercare", "performance_feedback_aftercare_new", "performance_feedback_meeting_guide", "performance_feedback_followup"},
    "birim_sorumlusu": {"performance_feedback_aftercare", "performance_feedback_aftercare_new", "performance_feedback_meeting_guide", "performance_feedback_followup"},
}
try:
    for _role, _keys in _BYS360_SETTINGS_V1_ROLE_ADDITIONS.items():
        _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
        if isinstance(_current, set):
            _current.update(_keys)
        elif isinstance(_current, list):
            _current.extend([_key for _key in _keys if _key not in _current])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1498)")
# BYS360_SETTINGS_LIVE_AUTHORITY_V1_REGISTRY_END

# BYS360_SETTINGS_LIVE_AUTHORITY_V1_SPECIAL_ROLES_BEGIN
# Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı rol varyantları.
_BYS360_PUBLISH_PREAPPROVAL_ROLE_VARIANTS = {
    "personel_ve_destek_hizmetleri_grup_baskani",
    "personel_destek_hizmetleri_grup_baskani",
    "personel_ve_idari_isler_grup_baskani",
    "personel_idari_isler_grup_baskani",
}
try:
    for _section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global
        for _item in _section.get("items", []):
            if isinstance(_item, dict) and _item.get("key") == "performance_personnel_support_publish_approval":
                _roles = list(_item.get("required_roles") or [])
                for _role in _BYS360_PUBLISH_PREAPPROVAL_ROLE_VARIANTS:
                    if _role not in _roles:
                        _roles.append(_role)
                _item["required_roles"] = _roles
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1519)")

for _role in _BYS360_PUBLISH_PREAPPROVAL_ROLE_VARIANTS:
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update({"home", "dashboard", "account", "logout", "performance_personnel_support_publish_approval", "performance_process_tracking", "performance_process_reports"})
    elif isinstance(_current, list):
        for _key in ["home", "dashboard", "account", "logout", "performance_personnel_support_publish_approval", "performance_process_tracking", "performance_process_reports"]:
            if _key not in _current:
                _current.append(_key)
# BYS360_SETTINGS_LIVE_AUTHORITY_V1_SPECIAL_ROLES_END

# BYS360_SETTINGS_LIVE_AUTHORITY_V1_SUPPORT_ADMIN_BEGIN
# Yardım Merkezi rehber yönetimi de ayarlar rol matrisinde görünür olmalıdır.
try:
    _genel_section = next((_section for _section in MENU_SECTIONS if _section.get("key") == "genel"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_genel_section, dict):
        _items = _genel_section.setdefault("items", [])
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        if "support_help_admin" not in _existing:
            _items.append({
                "key": "support_help_admin",
                "label": "Rehber Yönetimi",
                "icon": "fa-solid fa-book-open-reader",
                "endpoint": "main.support_help_admin",
                "href": "/support/help-admin",
                "active_path_prefixes": ["/support/help-admin"],
                "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi"],
            })
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1549)")
try:
    _current = ROLE_MENU_DEFAULTS.setdefault("admin", set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.add("support_help_admin")
    elif isinstance(_current, list) and "support_help_admin" not in _current:
        _current.append("support_help_admin")
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1557)")
# BYS360_SETTINGS_LIVE_AUTHORITY_V1_SUPPORT_ADMIN_END


# BYS360_SETTINGS_LIVE_AUTHORITY_V2_MENU_REGISTRY_END
# Menü kayıt defteri, rol matrisinde açık görünen satırları ikinci bir rol
# filtresiyle engellemez; görünürlük kararının tek kaynağı menu_visibility_map olur.

# BYS360_AG5E_AI_TEACHING_MENU_REGISTRY_START
# Asistan Bilgi Bankası, AI Karar Destek Merkezi'nin gerçek alt sekmesidir.
_BYS360_AG5E_AI_TEACHING_MENU_ITEM = {
    "key": "ai_teaching_center",
    "label": "Asistan Bilgi Bankası",
    "icon": "fa-solid fa-graduation-cap",
    "endpoint": "ai_agent.ag5_knowledge_center",
    "href": "/ai-agent/knowledge",
    "active_endpoints": ["ai_agent.ag5_knowledge_center"],
    "active_path_prefixes": ["/ai-agent/knowledge"],
    "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "başkan", "ust_yonetim", "ai_yoneticisi"],
}
try:
    _ai_section = next((_section for _section in MENU_SECTIONS if _section.get("key") == "ai"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_ai_section, dict):
        _items = _ai_section.setdefault("items", [])
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        if "ai_teaching_center" not in _existing:
            _items.append(dict(_BYS360_AG5E_AI_TEACHING_MENU_ITEM))
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1585)")
ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global
_BYS360_AG5E_AI_TEACHING_ROLES = ["admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "başkan", "ust_yonetim", "ai_yoneticisi"]
for _role in _BYS360_AG5E_AI_TEACHING_ROLES:
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.add("ai_teaching_center")
    elif isinstance(_current, list) and "ai_teaching_center" not in _current:
        _current.append("ai_teaching_center")
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})  # noqa: F821 - dynamic menu registry global
for _role in _BYS360_AG5E_AI_TEACHING_ROLES:
    FORCE_VISIBLE_MENU_ROLES.setdefault("ai_teaching_center", set()).add(_role)  # noqa: F821 - dynamic menu registry global
# BYS360_AG5E_AI_TEACHING_MENU_REGISTRY_END


# BYS360_PERSONEL_LIVE_SCOPE_NARROW_V1_BEGIN
# Personel Yönetimi canlı kapsamı daraltıldı:
# - Özlük ve organizasyon omurgası kendi mevcut anahtarlarıyla kalır: admin_users, org_units.
# - Personel alt operasyonlarında yalnızca izin, devamsızlık ve vekâlet hattı kalır: hr_leave_tracking.
# - Talep, evrak, zimmet, checklist, yaşam döngüsü, devir teslim ve rapor sekmeleri canlı menüye geri eklenmez.
_BYS360_PERSONEL_NARROW_ROLES = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi", "administrator",
    "baskan", "başkan", "president", "baskan_yardimcisi", "başkan_yardımcısı",
    "grup_baskani", "grup_başkanı", "mali_musavir", "mali_müşavir",
    "koordinator", "koordinatör", "birim_sorumlusu",
}
_BYS360_PERSONEL_ALLOWED_LIVE_KEYS = {"admin_users", "org_units", "hr_leave_tracking"}
_BYS360_PERSONEL_DISALLOWED_LIVE_KEYS = {
    "hr_management",
    "hr_reports",
    "hr_personnel_operations",
    "hr_career_planning",
    "hr_reward_discipline",
}
try:
    _ik_section = next((_section for _section in MENU_SECTIONS if _section.get("key") == "ik"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_ik_section, dict):
        _items = _ik_section.setdefault("items", [])
        _items[:] = [
            _item for _item in _items
            if not (isinstance(_item, dict) and _item.get("key") in _BYS360_PERSONEL_DISALLOWED_LIVE_KEYS)
        ]
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        if "hr_leave_tracking" not in _existing:
            _items.append({
                "key": "hr_leave_tracking",
                "label": "İzin, Devamsızlık ve Vekâlet",
                "icon": "fa-solid fa-calendar-check",
                "endpoint": "main.hr_leave_management",
                "href": "/hr-management/leave",
                "active_endpoints": ["main.hr_leave_management", "main.hr_attendance_management"],
                "active_path_prefixes": ["/hr-management/leave", "/hr-management/attendance", "/hr-management/delegations"],
                "required_roles": sorted(_BYS360_PERSONEL_NARROW_ROLES),
            })
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1646)")

try:
    for _role in _BYS360_PERSONEL_NARROW_ROLES:
        _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
        if isinstance(_current, set):
            _current.difference_update(_BYS360_PERSONEL_DISALLOWED_LIVE_KEYS)
            _current.update(_BYS360_PERSONEL_ALLOWED_LIVE_KEYS)
        elif isinstance(_current, list):
            _current[:] = [_key for _key in _current if _key not in _BYS360_PERSONEL_DISALLOWED_LIVE_KEYS]
            for _key in sorted(_BYS360_PERSONEL_ALLOWED_LIVE_KEYS):
                if _key not in _current:
                    _current.append(_key)
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1660)")
# BYS360_PERSONEL_LIVE_SCOPE_NARROW_V1_END

# BYS360_PERSONEL_ROLE_MATRIX_CURRENT_SCOPE_V1_MENU_BEGIN
# Personel Yönetimi rol matrisi güncel kapsam varsayılanları.
_BYS360_PERSONEL_ROLE_MATRIX_CURRENT_ALLOWED_KEYS = {"admin_users", "org_units", "hr_leave_tracking"}
# BYS360 P11-D2: _BYS360_PERSONEL_ROLE_MATRIX_CURRENT_DISALLOWED_KEYS veri bloğu data modülüne taşındı.
_BYS360_PERSONEL_ROLE_MATRIX_MANAGER_ROLES = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi", "administrator",
    "baskan", "başkan", "president", "baskan_yardimcisi", "başkan_yardımcısı",
    "grup_baskani", "grup_başkanı", "mali_musavir", "mali_müşavir",
    "koordinator", "koordinatör", "birim_sorumlusu",
}
_BYS360_PERSONEL_ROLE_MATRIX_STANDARD_ROLES = {"personel", "user", "kullanici", "kullanıcı", "standart_personel", "rolsuz", "__none__"}

try:
    for _role_key, _keys in list(ROLE_MENU_DEFAULTS.items()):  # noqa: F821 - dynamic menu registry global
        if isinstance(_keys, set):
            _keys.difference_update(_BYS360_PERSONEL_ROLE_MATRIX_CURRENT_DISALLOWED_KEYS)
            if str(_role_key).strip().lower() in _BYS360_PERSONEL_ROLE_MATRIX_MANAGER_ROLES:
                _keys.update(_BYS360_PERSONEL_ROLE_MATRIX_CURRENT_ALLOWED_KEYS)
            if str(_role_key).strip().lower() in _BYS360_PERSONEL_ROLE_MATRIX_STANDARD_ROLES:
                _keys.difference_update(_BYS360_PERSONEL_ROLE_MATRIX_CURRENT_ALLOWED_KEYS)
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1691)")
# BYS360_PERSONEL_ROLE_MATRIX_CURRENT_SCOPE_V1_MENU_END

# BYS360_SETTINGS_MENU_ROLE_MATRIX_ALL_TABS_V1_BEGIN
# Statik varsayılanlar güncellendi; gerçek canlı karar yine Ayarlar > Rol Matrisi kayıtlarıdır.
_BYS360_ALL_MENU_ROLE_MATRIX_DEFAULTS = {
    'admin': {'home', 'dashboard', 'notifications', 'announcements', 'account', 'settings', 'db_check', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'support_assigned', 'support_all', 'admin_users', 'org_units', 'hr_leave_tracking', 'performance_scorecard', 'my_performance_comparison', 'performance_reports', 'performance_tasks', 'performance_criteria', 'performance_periods', 'performance_evaluation_tasks', 'performance_task_management', 'performance_hierarchy_tree', 'performance_hierarchy_assignments', 'performance_team_compare', 'team_performance_comparison_history', 'performance_feedback_meetings', 'performance_publish', 'performance_president_approvals', 'performance_personnel_support_publish_approval', 'performance_process_tracking', 'performance_process_reports', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_archive', 'performance_history_import', 'performance_mail_settings', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis', 'messages', 'surveys', 'survey_manage', 'survey_results', 'feedback_dashboard', 'feedback_pulse', 'feedback_campaigns', 'feedback_results', 'feedback_actions', 'feedback_manager', 'feedback_admin', 'ai_center', 'ai_agent_panel', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary', 'assistant_logs', 'assistant_settings'},
    'baskan': {'home', 'dashboard', 'notifications', 'announcements', 'account', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'support_assigned', 'support_all', 'admin_users', 'org_units', 'hr_leave_tracking', 'performance_scorecard', 'my_performance_comparison', 'performance_reports', 'performance_tasks', 'performance_criteria', 'performance_periods', 'performance_evaluation_tasks', 'performance_hierarchy_tree', 'performance_team_compare', 'team_performance_comparison_history', 'performance_feedback_meetings', 'performance_publish', 'performance_president_approvals', 'performance_personnel_support_publish_approval', 'performance_process_tracking', 'performance_process_reports', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_archive', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis', 'messages', 'surveys', 'survey_manage', 'survey_results', 'feedback_dashboard', 'feedback_pulse', 'feedback_campaigns', 'feedback_results', 'feedback_actions', 'feedback_manager', 'feedback_admin', 'ai_center', 'ai_agent_panel', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary', 'assistant_logs'},
    'baskan_yardimcisi': {'home', 'dashboard', 'notifications', 'announcements', 'account', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'support_assigned', 'support_all', 'admin_users', 'org_units', 'hr_leave_tracking', 'performance_scorecard', 'my_performance_comparison', 'performance_reports', 'performance_tasks', 'performance_criteria', 'performance_periods', 'performance_evaluation_tasks', 'performance_hierarchy_tree', 'performance_team_compare', 'team_performance_comparison_history', 'performance_feedback_meetings', 'performance_publish', 'performance_process_tracking', 'performance_process_reports', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_archive', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis', 'messages', 'surveys', 'survey_manage', 'survey_results', 'feedback_dashboard', 'feedback_pulse', 'feedback_campaigns', 'feedback_results', 'feedback_actions', 'feedback_manager', 'feedback_admin', 'ai_center', 'ai_agent_panel', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary'},
    'grup_baskani': {'home', 'dashboard', 'notifications', 'announcements', 'account', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'support_assigned', 'support_all', 'admin_users', 'org_units', 'hr_leave_tracking', 'performance_scorecard', 'my_performance_comparison', 'performance_reports', 'performance_tasks', 'performance_criteria', 'performance_periods', 'performance_evaluation_tasks', 'performance_hierarchy_tree', 'performance_team_compare', 'team_performance_comparison_history', 'performance_feedback_meetings', 'performance_publish', 'performance_personnel_support_publish_approval', 'performance_process_tracking', 'performance_process_reports', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_archive', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis', 'messages', 'surveys', 'survey_manage', 'survey_results', 'feedback_dashboard', 'feedback_pulse', 'feedback_campaigns', 'feedback_results', 'feedback_actions', 'feedback_manager', 'feedback_admin', 'ai_center', 'ai_agent_panel', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary'},
    'mali_musavir': {'home', 'dashboard', 'notifications', 'announcements', 'account', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'support_assigned', 'support_all', 'admin_users', 'org_units', 'hr_leave_tracking', 'performance_scorecard', 'my_performance_comparison', 'performance_reports', 'performance_tasks', 'performance_criteria', 'performance_periods', 'performance_evaluation_tasks', 'performance_hierarchy_tree', 'performance_team_compare', 'team_performance_comparison_history', 'performance_feedback_meetings', 'performance_publish', 'performance_process_tracking', 'performance_process_reports', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_archive', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis', 'messages', 'surveys', 'survey_manage', 'survey_results', 'feedback_dashboard', 'feedback_pulse', 'feedback_campaigns', 'feedback_results', 'feedback_actions', 'feedback_manager', 'feedback_admin', 'ai_center', 'ai_agent_panel', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary'},
    'koordinator': {'home', 'dashboard', 'notifications', 'announcements', 'account', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'support_assigned', 'support_all', 'admin_users', 'org_units', 'hr_leave_tracking', 'performance_scorecard', 'my_performance_comparison', 'performance_reports', 'performance_tasks', 'performance_criteria', 'performance_periods', 'performance_evaluation_tasks', 'performance_hierarchy_tree', 'performance_team_compare', 'team_performance_comparison_history', 'performance_feedback_meetings', 'performance_publish', 'performance_process_tracking', 'performance_process_reports', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_archive', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis', 'messages', 'surveys', 'survey_manage', 'survey_results', 'feedback_dashboard', 'feedback_pulse', 'feedback_campaigns', 'feedback_results', 'feedback_actions', 'feedback_manager', 'feedback_admin', 'ai_center', 'ai_agent_panel', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary'},
    'birim_sorumlusu': {'home', 'dashboard', 'notifications', 'announcements', 'account', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'support_assigned', 'support_all', 'admin_users', 'org_units', 'hr_leave_tracking', 'performance_scorecard', 'my_performance_comparison', 'performance_reports', 'performance_tasks', 'performance_criteria', 'performance_periods', 'performance_evaluation_tasks', 'performance_hierarchy_tree', 'performance_team_compare', 'team_performance_comparison_history', 'performance_feedback_meetings', 'performance_publish', 'performance_process_tracking', 'performance_process_reports', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_archive', 'performance_kpi_dashboard', 'performance_competency_library', 'performance_self_assessment', 'messages', 'surveys', 'survey_manage', 'survey_results', 'feedback_dashboard', 'feedback_pulse', 'feedback_campaigns', 'feedback_results', 'feedback_actions', 'feedback_manager', 'feedback_admin', 'ai_center', 'ai_agent_panel', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary'},
    'personel': {'home', 'dashboard', 'notifications', 'account', 'logout', 'support_index', 'support_new', 'support_my_tickets', 'messages', 'surveys', 'feedback_dashboard', 'feedback_pulse', 'performance_scorecard', 'my_performance_comparison', 'performance_archive', 'performance_self_assessment', 'ai_agent_panel', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders'},
}
for _role, _keys in _BYS360_ALL_MENU_ROLE_MATRIX_DEFAULTS.items():
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update(_keys)
    elif isinstance(_current, list):
        _current.extend([_key for _key in _keys if _key not in _current])

# Mevcut menü kayıtlarında eski required_roles/href/endpoint kalmışsa yeni sekmelerin ayar matrisine uyumlu çalışmasını sağlar.
_BYS360_ALL_MENU_ROLE_MATRIX_MENU_ATTRS = {
    "performance_self_assessment": {"required_roles": {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'}},
    "performance_personnel_support_publish_approval": {"required_roles": {'admin', 'grup_baskani', 'personel_ve_destek_hizmetleri_grup_baskani', 'personel_destek_hizmetleri_grup_baskani', 'personel_ve_idari_isler_grup_baskani', 'personel_idari_isler_grup_baskani'}},
    "ai_agent_panel": {"required_roles": {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'}},
}
try:
    for _section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global
        for _item in _section.get("items", []) or []:
            if not isinstance(_item, dict):
                continue
            _attrs = _BYS360_ALL_MENU_ROLE_MATRIX_MENU_ATTRS.get(_item.get("key"))
            if not _attrs:
                continue
            for _attr_key, _attr_value in _attrs.items():
                _item[_attr_key] = list(_attr_value) if isinstance(_attr_value, set) else _attr_value
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1730)")
# BYS360_SETTINGS_MENU_ROLE_MATRIX_ALL_TABS_V1_END

# BYS360_ASSISTANT_TABS_ROLE_MATRIX_V2_BEGIN
# Menü kayıt defterine BYS360 Asistanı gerçek sekmeleri eklendi.
_BYS360_ASSISTANT_TAB_MENU_ITEMS = [
    {"key": "assistant_module", "label": "BYS360 Asistanı Modülü", "icon": "fa-solid fa-robot", "endpoint": "ai_agent.ai_agent_panel", "href": "/ai-agent/panel", "active_path_prefixes": ["/ai-agent"], "required_roles": {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'}},
    {"key": "ai_agent_panel", "label": "Asistan Paneli", "icon": "fa-solid fa-robot", "endpoint": "ai_agent.ai_agent_panel", "href": "/ai-agent/panel", "active_path_prefixes": ["/ai-agent/panel"], "required_roles": {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'}},
    {"key": "ai_agent_knowledge", "label": "Asistan Bilgi Bankası", "icon": "fa-solid fa-book-open-reader", "endpoint": "ai_agent.ag5_knowledge_center", "href": "/ai-agent/knowledge", "active_endpoints": ["ai_agent.ag5_knowledge_center"], "active_path_prefixes": ["/ai-agent/knowledge"], "required_roles": {'admin', 'baskan'}},
    {"key": "ai_agent_teaching_center", "label": "Asistan Öğretim Merkezi", "icon": "fa-solid fa-chalkboard-user", "endpoint": "ai_agent.assistant_teaching_center", "href": "/ai-agent/teaching-center", "active_endpoints": ["ai_agent.assistant_teaching_center"], "active_path_prefixes": ["/ai-agent/teaching-center"], "required_roles": {'admin', 'baskan'}},
]
try:
    _assistant_section = next((_section for _section in MENU_SECTIONS if _section.get("key") in {"assistant", "bys360_assistant", "bys360_asistani"}), None)  # noqa: F821 - dynamic menu registry global
    if not isinstance(_assistant_section, dict):
        _assistant_section = {"key": "assistant", "label": "BYS360 Asistanı", "icon": "fa-solid fa-robot", "items": []}
        MENU_SECTIONS.append(_assistant_section)  # noqa: F821 - dynamic menu registry global
    _items = _assistant_section.setdefault("items", [])
    _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
    for _item in _BYS360_ASSISTANT_TAB_MENU_ITEMS:
        if _item["key"] not in _existing:
            _items.append(dict(_item))
            _existing.add(_item["key"])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1753)")
ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global
_BYS360_ASSISTANT_TAB_ROLE_DEFAULTS = {
    'admin': {'assistant_module', 'ai_agent_panel', 'ai_agent_knowledge', 'ai_agent_teaching_center', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders', 'assistant_scheduled_tasks', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary', 'assistant_logs', 'assistant_settings'},
    'baskan': {'assistant_module', 'ai_agent_panel', 'ai_agent_knowledge', 'ai_agent_teaching_center', 'ai_teaching_center', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_president_approval_guidance', 'assistant_publish_preapproval_guidance', 'assistant_process_alerts', 'assistant_report_generate', 'assistant_report_share', 'assistant_ai_summary', 'assistant_logs'},
    'baskan_yardimcisi': {'assistant_module', 'ai_agent_panel', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_process_alerts', 'assistant_report_generate', 'assistant_ai_summary'},
    'grup_baskani': {'assistant_module', 'ai_agent_panel', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_publish_preapproval_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders'},
    'mali_musavir': {'assistant_module', 'ai_agent_panel', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_process_alerts', 'assistant_report_generate', 'assistant_ai_summary'},
    'koordinator': {'assistant_module', 'ai_agent_panel', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders'},
    'birim_sorumlusu': {'assistant_module', 'ai_agent_panel', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_performance_guidance', 'assistant_interim_notes_guidance', 'assistant_development_guidance', 'assistant_process_alerts', 'assistant_my_reminders'},
    'personel': {'assistant_module', 'ai_agent_panel', 'assistant_center', 'assistant_quick_help', 'assistant_my_summary', 'assistant_support_routing', 'assistant_archive_guidance', 'assistant_process_alerts', 'assistant_my_reminders'},
}
for _role, _keys in _BYS360_ASSISTANT_TAB_ROLE_DEFAULTS.items():
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update(_keys)
    elif isinstance(_current, list):
        _current.extend([_key for _key in _keys if _key not in _current])
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})  # noqa: F821 - dynamic menu registry global
# Zorla görünürlük rol matrisi davranışını ezmesin; görünürlüğün son kararı Ayarlar/Rol Matrisi olsun.
for _key in ["assistant_module", "ai_agent_panel", "ai_agent_knowledge", "ai_agent_teaching_center", "ai_teaching_center"]:
    FORCE_VISIBLE_MENU_ROLES.pop(_key, None)  # noqa: F821 - dynamic menu registry global
# Eski anahtar uyumluluğu: önceki "ai_teaching_center" Asistan Bilgi Bankası olarak kabul edilir.
try:
    for _role in ["admin", "baskan"]:
        _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
        if isinstance(_current, set):
            _current.add("ai_teaching_center")
        elif isinstance(_current, list) and "ai_teaching_center" not in _current:
            _current.append("ai_teaching_center")
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1790)")
# BYS360_ASSISTANT_TABS_ROLE_MATRIX_V2_END

# BYS360_PERFORMANCE_MAIN_SWITCH_ROLE_MATRIX_V3_BEGIN
# Performans Yönetimi ana anahtarı menü/rol kayıt defterine eklendi.
_BYS360_PERFORMANCE_MAIN_SWITCH_ITEM = {
    "key": "performance_module",
    "label": "Performans Yönetimi Modülü Ana Anahtarı",
    "icon": "fa-solid fa-toggle-on",
    "href": "javascript:void(0)",
    "settings_key": "performance_module",
    "show_in_settings": True,
    "show_in_sidebar": False,
    "required_roles": {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'},
    "permission_keys": ["performance_module", "performance_management", "performans_yonetimi"],
}
try:
    _perf_section = next((_section for _section in MENU_SECTIONS if _section.get("key") in {"performans", "performance", "performans_yonetimi"} or _section.get("label") == "Performans Yönetimi"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_perf_section, dict):
        _items = _perf_section.setdefault("items", [])
        _existing = {_item.get("key") for _item in _items if isinstance(_item, dict)}
        if "performance_module" not in _existing:
            _items.insert(0, dict(_BYS360_PERFORMANCE_MAIN_SWITCH_ITEM))
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:1814)")
ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global
# BYS360 P11-D2: _BYS360_PERFORMANCE_MAIN_SWITCH_ROLE_POLICY veri bloğu data modülüne taşındı.
for _role, _keys in {_role: {_key for _key, _roles in _BYS360_PERFORMANCE_MAIN_SWITCH_ROLE_POLICY.items() if _role in _roles} for _role in {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'} }.items():
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update(_keys)
    elif isinstance(_current, list):
        _current.extend([_key for _key in _keys if _key not in _current])
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})  # noqa: F821 - dynamic menu registry global
for _key in {'performance_module', 'performance_management', 'performans_yonetimi', 'performance_tasks', 'performance_scorecard', 'scorecards', 'my_performance_comparison', 'performance_dashboard', 'performance_reports', 'performance_criteria', 'criteria', 'performance_periods', 'periods', 'performance_evaluation_tasks', 'assignments', 'performance_task_management', 'performance_hierarchy_tree', 'performance_hierarchy_assignments', 'performance_team_compare', 'team_analysis', 'team_performance_comparison_history', 'performance_feedback_meetings', 'feedback_meetings', 'performance_publish', 'publish', 'performance_mail_settings', 'performance_mail', 'performance_process_tracking', 'performance_process_reports', 'performance_president_approvals', 'performance_personnel_support_publish_approval', 'performance_archive', 'performance_interim_notes', 'performance_development_guidance', 'performance_meeting_p3_reminders', 'performance_kpi_dashboard', 'performance_kpi_management', 'performance_competency_library', 'performance_self_assessment', 'performance_kpi_analysis'}:
    FORCE_VISIBLE_MENU_ROLES.pop(_key, None)  # noqa: F821 - dynamic menu registry global
# BYS360_PERFORMANCE_MAIN_SWITCH_ROLE_MATRIX_V3_END

# BYS360_GENERAL_SECTION_RESTORE_V4_BEGIN
# Genel çekirdek menüleri tüm roller için varsayılan görünür tutulur.
_BYS360_GENERAL_CORE_KEYS_V4 = {'general_section', 'home', 'dashboard', 'notifications', 'support_index', 'support_new', 'support_my_tickets'}
ROLE_MENU_DEFAULTS = globals().get("ROLE_MENU_DEFAULTS", {})  # noqa: F821 - dynamic menu registry global
for _role in {'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'}:
    _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_current, set):
        _current.update(_BYS360_GENERAL_CORE_KEYS_V4)
    elif isinstance(_current, list):
        _current.extend([_key for _key in _BYS360_GENERAL_CORE_KEYS_V4 if _key not in _current])
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})  # noqa: F821 - dynamic menu registry global
# Genel bölümün kaybolmasına neden olabilecek eski zorla-kapat/yanlış filtre izlerini etkisiz bırak.
for _key in ["home", "dashboard", "general_section"]:
    _roles = FORCE_VISIBLE_MENU_ROLES.setdefault(_key, set())  # noqa: F821 - dynamic menu registry global
    if isinstance(_roles, set):
        _roles.update({'admin', 'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'personel'})
# BYS360_GENERAL_SECTION_RESTORE_V4_END

# BYS360_PERFORMANCE_ITEMS_ONLY_UNDER_PERFORMANCE_V5_BEGIN
# Performansa ait kısa yollar artık Genel altında değil, yalnızca Performans Yönetimi altında görünür.
# Bu blok import sırasında MENU_SECTIONS listesini güvenli biçimde düzenler.
_BYS360_PERFORMANCE_GENERAL_MOVED_KEYS = {
    "performance_tasks",
    "performance_scorecard",
    "my_performance_comparison",
    "performance_reports",
}
_BYS360_PERFORMANCE_GENERAL_MOVE_ORDER = [
    "performance_tasks",
    "performance_scorecard",
    "my_performance_comparison",
    "performance_reports",
]
_BYS360_PERFORMANCE_GENERAL_MOVE_DEFAULTS = {
    "performance_tasks": {
        "key": "performance_tasks",
        "label": "Görevlerim",
        "icon": "fa-solid fa-list-check",
        "endpoint": "main.performance_tasks",
        "active_endpoints": [
            "main.performance_tasks",
            "main.performance_evaluate",
            "main.performance_v2_phase3_dashboard",
            "main.performance_v2_phase3_assignment",
            "main.performance_v2_phase4_dashboard",
            "main.performance_v2_phase4_assignment",
        ],
        "active_path_prefixes": ["/performance/tasks", "/performans/gorevlerim"],
    },
    "performance_scorecard": {
        "key": "performance_scorecard",
        "label": "Not Karnesi",
        "icon": "fa-solid fa-id-card",
        "endpoint": "main.performance_scorecard",
        "active_endpoints": ["main.performance_scorecard"],
        "active_path_prefixes": ["/performance/scorecard", "/performans/not-karnesi", "/performans/v2/faz5/scorecard"],
    },
    "my_performance_comparison": {
        "key": "my_performance_comparison",
        "label": "Kişisel / Grup Ortalaması",
        "icon": "fa-solid fa-chart-line",
        "endpoint": "main.my_performance_comparison",
        "active_endpoints": ["main.my_performance_comparison"],
        "active_path_prefixes": ["/performance/my-comparison", "/performans/kisisel-grup-ortalamasi"],
    },
    "performance_reports": {
        "key": "performance_reports",
        "label": "Performans Raporları",
        "icon": "fa-solid fa-chart-pie",
        "endpoint": "main.performance_reports",
        "active_endpoint_prefixes": ["main.performance_reports"],
        "active_path_prefixes": ["/performance/reports", "/performans/raporlar"],
    },
}


def _bys360_section_by_label_v5(label):
    for _section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global
        if str(_section.get("label") or "").strip() == label:
            return _section
    return None


def _bys360_dedupe_menu_items_v5(items):
    _seen = set()
    _result = []
    for _item in items or []:
        if not isinstance(_item, dict):
            continue
        _key = str(_item.get("key") or "").strip()
        if not _key or _key in _seen:
            continue
        _seen.add(_key)
        _result.append(_item)
    return _result


def _bys360_move_performance_items_from_general_to_performance_v5():
    _general = _bys360_section_by_label_v5("Genel")
    _performance = _bys360_section_by_label_v5("Performans Yönetimi")
    if not isinstance(_general, dict) or not isinstance(_performance, dict):
        return

    _moved_by_key = {}
    _clean_general_items = []
    for _item in list(_general.get("items") or []):
        if not isinstance(_item, dict):
            continue
        _key = str(_item.get("key") or "").strip()
        if _key in _BYS360_PERFORMANCE_GENERAL_MOVED_KEYS:
            _moved_by_key[_key] = dict(_item)
            continue
        _clean_general_items.append(_item)
    _general["items"] = _bys360_dedupe_menu_items_v5(_clean_general_items)

    _performance_items = list(_performance.get("items") or [])
    _existing_keys = {str(_item.get("key") or "").strip() for _item in _performance_items if isinstance(_item, dict)}
    _to_insert = []
    for _key in _BYS360_PERFORMANCE_GENERAL_MOVE_ORDER:
        if _key in _existing_keys:
            continue
        _candidate = dict(_moved_by_key.get(_key) or _BYS360_PERFORMANCE_GENERAL_MOVE_DEFAULTS[_key])
        _candidate["section"] = "Performans Yönetimi"
        _to_insert.append(_candidate)
        _existing_keys.add(_key)
    _performance["items"] = _bys360_dedupe_menu_items_v5(_to_insert + _performance_items)


_bys360_move_performance_items_from_general_to_performance_v5()
# BYS360_PERFORMANCE_ITEMS_ONLY_UNDER_PERFORMANCE_V5_END

# BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MENU_BEGIN
# Personel Yönetimi sol şerit / registry hizalaması.
# Bu blok, rol matrisinde seçilen Personel sekmelerinin flatten_menu_definitions içinde kalmasını sağlar.
_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi", "administrator",
    "baskan", "başkan", "president", "baskan_yardimcisi", "başkan_yardımcısı",
    "grup_baskani", "grup_başkanı", "mali_musavir", "mali_müşavir",
    "koordinator", "koordinatör", "birim_sorumlusu",
}
_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_KEYS = {"admin_users", "org_units", "hr_management", "hr_leave_tracking", "hr_reports"}
# BYS360 P11-D2: _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_OBSOLETE_KEYS veri bloğu data modülüne taşındı.
_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_ITEMS = [
    {"key": "admin_users", "label": "Personel Özlük Dosyaları", "icon": "fa-solid fa-folder-open", "endpoint": "main.personnel_list", "href": "/personnel", "active_endpoints": ["main.admin_users", "main.admin_user_create", "main.admin_user_edit", "main.personnel_list", "main.personnel_add", "main.personnel_edit"], "active_path_prefixes": ["/admin/users", "/personnel"], "required_roles": sorted(_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES)},
    {"key": "org_units", "label": "Birim ve Pozisyon Yönetimi", "icon": "fa-solid fa-diagram-project", "endpoint": "main.admin_org_units", "href": "/admin/org-units", "active_endpoints": ["main.admin_org_units", "main.admin_org_unit_create", "main.admin_org_unit_edit"], "active_path_prefixes": ["/admin/org-units", "/org-units"], "required_roles": sorted(_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES)},
    {"key": "hr_management", "label": "Personel Kontrol Paneli", "icon": "fa-solid fa-users-gear", "endpoint": "main.hr_management", "href": "/hr-management", "active_endpoints": ["main.hr_management"], "active_path_prefixes": ["/hr-management"], "required_roles": sorted(_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES)},
    {"key": "hr_leave_tracking", "label": "İzin, Devamsızlık ve Vekâlet", "icon": "fa-solid fa-calendar-check", "endpoint": "main.hr_leave_management", "href": "/hr-management/leave", "active_endpoints": ["main.hr_leave_management", "main.hr_attendance_management"], "active_path_prefixes": ["/hr-management/leave", "/hr-management/attendance", "/hr-management/delegations"], "required_roles": sorted(_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES)},
    {"key": "hr_reports", "label": "Personel Raporları", "icon": "fa-solid fa-chart-column", "endpoint": "main.hr_reports", "href": "/hr-management/reports", "active_endpoints": ["main.hr_reports"], "active_path_prefixes": ["/hr-management/reports"], "required_roles": sorted(_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES)},
]
try:
    _ik_section = next((_section for _section in MENU_SECTIONS if isinstance(_section, dict) and _section.get("key") == "ik"), None)  # noqa: F821 - dynamic menu registry global
    if not isinstance(_ik_section, dict):
        _ik_section = {"key": "ik", "label": "Personel Yönetimi", "icon": "fa-solid fa-user-group", "items": []}
        MENU_SECTIONS.append(_ik_section)  # noqa: F821 - dynamic menu registry global
    _items = _ik_section.setdefault("items", [])
    _items[:] = [_item for _item in _items if not (isinstance(_item, dict) and _item.get("key") in _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_OBSOLETE_KEYS)]
    _by_key = {_item.get("key"): _item for _item in _items if isinstance(_item, dict)}
    for _new_item in _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_ITEMS:
        _existing = _by_key.get(_new_item["key"])
        if isinstance(_existing, dict):
            _existing.update(_new_item)
        else:
            _items.append(dict(_new_item))
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2061)")
try:
    for _role_key, _keys in list(ROLE_MENU_DEFAULTS.items()):  # noqa: F821 - dynamic menu registry global
        _role_norm = str(_role_key or "").strip().lower()
        if isinstance(_keys, set):
            _keys.difference_update(_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_OBSOLETE_KEYS)
            if _role_norm in _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES:
                _keys.update(_BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_KEYS)
        elif isinstance(_keys, list):
            _keys[:] = [_key for _key in _keys if _key not in _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_OBSOLETE_KEYS]
            if _role_norm in _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MANAGER_ROLES:
                _keys.extend([_key for _key in _BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_KEYS if _key not in _keys])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2074)")
# BYS360_PERSONEL_ROLE_MATRIX_VISIBILITY_V7_MENU_END

# BYS360_PERFORMANCE_ROLE_MATRIX_PERSONNEL_V8_BEGIN
# Menü kayıt defteri düzeltmesi: performansa ait satırlar Genel'den çıkarılır,
# Performans Yönetimi altında tekil/canonical anahtarlarla tutulur.
_BYS360_PERF_RM_V8_MAIN_ITEM = {
    "key": "performance_module",
    "label": "Performans Yönetimi Modülü Ana Anahtarı",
    "icon": "fa-solid fa-toggle-on",
    "href": "javascript:void(0)",
    "settings_key": "performance_module",
    "show_in_settings": True,
    "show_in_sidebar": False,
    "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"],
}
_BYS360_PERF_RM_V8_MENU_ITEMS = [
    _BYS360_PERF_RM_V8_MAIN_ITEM,
    {"key": "performance_tasks", "label": "Görevlerim", "icon": "fa-solid fa-list-check", "endpoint": "main.performance_tasks", "href": "/performance/tasks", "active_path_prefixes": ["/performance/tasks", "/performance/assignments", "/performance/evaluate", "/performance/v2/faz", "/performans/v2/faz"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_scorecard", "label": "Not Karnesi", "icon": "fa-solid fa-id-card", "endpoint": "main.performance_scorecard", "href": "/performance/scorecard", "active_path_prefixes": ["/performance/scorecard", "/performance/report-card", "/performance/v2/faz5", "/performans/v2/faz5", "/scorecard"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"]},
    {"key": "performance_archive", "label": "Geçmiş Karne Arşivi", "icon": "fa-solid fa-box-archive", "endpoint": "main.performance_archive", "href": "/performans/gecmis-karne-arsivi", "active_path_prefixes": ["/performance/archive", "/performans/gecmis-karne-arsivi"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"]},
    {"key": "my_performance_comparison", "label": "Kişisel Performans Analizi", "icon": "fa-solid fa-chart-line", "endpoint": "main.my_performance_comparison", "href": "/performance/my-comparison", "active_path_prefixes": ["/performance/my-comparison", "/performans/kisisel-grup-ortalamasi"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"]},
    {"key": "performance_reports", "label": "Performans Raporları", "icon": "fa-solid fa-chart-pie", "endpoint": "main.performance_reports", "href": "/performance/reports", "active_endpoint_prefixes": ["main.performance_reports"], "active_path_prefixes": ["/performance/reports", "/performans/raporlar"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_kpi_dashboard", "label": "KPI Dashboardu", "icon": "fa-solid fa-gauge-high", "endpoint": "strategic_performance.kpi_dashboard", "href": "/performans/stratejik/kpi-dashboard", "active_path_prefixes": ["/performans/stratejik/kpi-dashboard"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_kpi_management", "label": "KPI ve Hedef Yönetimi", "icon": "fa-solid fa-bullseye", "endpoint": "strategic_performance.target_list", "href": "/performans/stratejik/hedefler", "active_path_prefixes": ["/performans/stratejik/hedefler"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator"]},
    {"key": "performance_competency_library", "label": "Yetkinlik Kütüphanesi", "icon": "fa-solid fa-book-open", "endpoint": "strategic_performance.competency_library", "href": "/performans/stratejik/yetkinlik-kutuphanesi", "active_path_prefixes": ["/performans/stratejik/yetkinlik-kutuphanesi"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_self_assessment", "label": "Öz Değerlendirme", "icon": "fa-solid fa-user-check", "href": "/performans/stratejik/oz-degerlendirme", "active_path_prefixes": ["/performans/stratejik/oz-degerlendirme"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"]},
    {"key": "performance_kpi_analysis", "label": "KPI Analiz Merkezi", "icon": "fa-solid fa-chart-column", "href": "/performans/stratejik/ai-kpi-analiz", "active_path_prefixes": ["/performans/stratejik/ai-kpi-analiz"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator"]},
    {"key": "performance_criteria", "label": "Sorular / Kriterler", "icon": "fa-solid fa-list-ul", "endpoint": "main.performance_criteria", "href": "/performance/criteria", "active_endpoint_prefixes": ["main.performance_criteria"], "required_roles": ["admin", "baskan", "baskan_yardimcisi"]},
    {"key": "performance_periods", "label": "Dönemler", "icon": "fa-solid fa-calendar-days", "endpoint": "main.performance_periods", "href": "/performance/periods", "active_endpoint_prefixes": ["main.performance_period"], "required_roles": ["admin", "baskan", "baskan_yardimcisi"]},
    {"key": "performance_evaluation_tasks", "label": "Değerlendirme Görevleri", "icon": "fa-solid fa-clipboard-check", "endpoint": "main.performance_evaluation_tasks", "href": "/performance/evaluation-tasks", "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_process_tracking", "label": "Süreç Takibi", "icon": "fa-solid fa-route", "endpoint": "main.performance_process_tracking", "href": "/performance/process-tracking", "active_path_prefixes": ["/performance/process-tracking", "/performans/surec-takibi"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_process_reports", "label": "Süreç Raporları", "icon": "fa-solid fa-chart-line", "endpoint": "main.performance_process_reports", "href": "/performance/process-reports", "active_path_prefixes": ["/performance/process-reports", "/performans/surec-raporlari"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_personnel_support_publish_approval", "label": "Yayın Ön Onayı", "icon": "fa-solid fa-user-check", "endpoint": "main.performance_personnel_support_publish_approvals", "href": "/performance/personnel-support-publish-approvals", "active_path_prefixes": ["/performance/personnel-support-publish-approvals", "/performans/personel-destek-yayin-onayi"], "required_roles": ["admin", "grup_baskani", "personel_ve_destek_hizmetleri_grup_baskani", "personel_destek_hizmetleri_grup_baskani", "personel_ve_idari_isler_grup_baskani", "personel_idari_isler_grup_baskani"]},
    {"key": "performance_president_approvals", "label": "Başkan Onayları", "icon": "fa-solid fa-user-tie", "endpoint": "main.performance_president_approvals", "href": "/performance/president-approvals", "active_path_prefixes": ["/performance/president-approvals", "/performans/baskan-onaylari"], "required_roles": ["admin", "baskan"]},
    {"key": "performance_meeting_p3_reminders", "label": "Hatırlatma ve Aksatan Amirler", "icon": "fa-solid fa-bell", "endpoint": "main.performance_meeting_p3_reminders", "href": "/performance/meeting-development/faz9", "active_path_prefixes": ["/performance/meeting-development/faz9", "/performans/toplanti-gelistirme/faz9-hatirlatma"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_interim_notes", "label": "Dönem İçi Notlar", "icon": "fa-solid fa-note-sticky", "endpoint": "main.performance_interim_notes", "href": "/performance/interim-notes", "active_path_prefixes": ["/performance/interim-notes", "/performans/donem-ici-notlar"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_feedback_aftercare", "label": "Görüşme Sonrası Notlar", "icon": "fa-solid fa-clipboard-check", "endpoint": "main.performance_feedback_aftercare", "href": "/performance/feedback-aftercare", "active_path_prefixes": ["/performance/feedback-aftercare", "/performans/gorusme-sonrasi-notlar"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_feedback_aftercare_new", "label": "Personel ve Dönem Görüşmesi", "icon": "fa-solid fa-user-clock", "endpoint": "main.performance_feedback_aftercare_new", "href": "/performance/feedback-aftercare/new", "active_path_prefixes": ["/performance/feedback-aftercare/new", "/performans/gorusme-sonrasi-notlar/yeni"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_feedback_meeting_guide", "label": "Geri Bildirim Rehberi", "icon": "fa-solid fa-comments", "endpoint": "main.performance_feedback_meeting_guide", "href": "/performance/feedback-meeting-guide", "active_path_prefixes": ["/performance/feedback-meeting-guide", "/performans/geri-bildirim-gorusme-rehberi"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_feedback_followup", "label": "Eylem Planı Takibi", "icon": "fa-solid fa-calendar-check", "endpoint": "main.performance_feedback_followup", "href": "/performance/feedback-followup", "active_path_prefixes": ["/performance/feedback-followup", "/performans/eylem-plani-takibi"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_development_guidance", "label": "Gelişim Rehberi", "icon": "fa-solid fa-seedling", "endpoint": "main.performance_meeting_p4_development_guidance", "href": "/performance/meeting-development/faz10", "active_path_prefixes": ["/performance/meeting-development/faz10", "/performans/toplanti-gelistirme/faz10-gelisim-rehberi"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_task_management", "label": "Görev Yönetimi", "icon": "fa-solid fa-screwdriver-wrench", "endpoint": "main.performance_task_management", "href": "/performance/task-management", "required_roles": ["admin"]},
    {"key": "performance_feedback_meetings", "label": "Geri Bildirim Talepleri / Randevu", "icon": "fa-solid fa-comments", "endpoint": "main.manager_feedback_requests", "href": "/performance/feedback-requests", "active_path_prefixes": ["/performance/feedback-requests", "/performance/feedback-meetings"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_hierarchy_tree", "label": "Hiyerarşi Ağacı", "icon": "fa-solid fa-sitemap", "endpoint": "main.performance_hierarchy_tree", "href": "/performance/hierarchy-tree", "active_path_prefixes": ["/performance/hierarchy-tree"], "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "performance_hierarchy_assignments", "label": "Hiyerarşi Atamaları & Ayarları", "icon": "fa-solid fa-code-branch", "endpoint": "main.performance_hierarchy_assignments", "href": "/performance/hierarchy-assignments", "active_path_prefixes": ["/performance/hierarchy-settings", "/performance/hierarchy-assignments"], "required_roles": ["admin"]},
    {"key": "performance_team_compare", "label": "Personel Analizi", "icon": "fa-solid fa-people-arrows", "endpoint": "main.performance_team_compare", "href": "/performance/team-compare", "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
    {"key": "team_performance_comparison_history", "label": "Personel Dönem Analizi", "icon": "fa-solid fa-code-compare", "endpoint": "main.team_performance_comparison_history", "href": "/performance/team-comparison-history", "required_roles": ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"]},
]
_BYS360_PERF_RM_V8_GENERAL_REMOVE_KEYS = {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS if item.get("key") != "performance_module"}
_BYS360_PERF_RM_V8_ALIAS_REMOVE_KEYS = {"scorecards", "criteria", "periods", "assignments", "team_analysis", "feedback_meetings", "publish", "performance_mail"}
try:
    _general = next((_section for _section in MENU_SECTIONS if isinstance(_section, dict) and _section.get("key") == "genel"), None)  # noqa: F821 - dynamic menu registry global
    if isinstance(_general, dict):
        _general["items"] = [
            _item for _item in (_general.get("items") or [])
            if not (isinstance(_item, dict) and _item.get("key") in (_BYS360_PERF_RM_V8_GENERAL_REMOVE_KEYS | _BYS360_PERF_RM_V8_ALIAS_REMOVE_KEYS))
        ]
    _perf = next((_section for _section in MENU_SECTIONS if isinstance(_section, dict) and (_section.get("key") == "performans" or _section.get("label") == "Performans Yönetimi")), None)  # noqa: F821 - dynamic menu registry global
    if not isinstance(_perf, dict):
        _perf = {"key": "performans", "label": "Performans Yönetimi", "icon": "fa-solid fa-chart-simple", "items": []}
        MENU_SECTIONS.append(_perf)  # noqa: F821 - dynamic menu registry global
    _existing_non_perf = [
        _item for _item in (_perf.get("items") or [])
        if isinstance(_item, dict) and _item.get("key") not in (_BYS360_PERF_RM_V8_GENERAL_REMOVE_KEYS | _BYS360_PERF_RM_V8_ALIAS_REMOVE_KEYS | {"performance_module"})
    ]
    _seen = set()
    _deduped = []
    for _item in list(_BYS360_PERF_RM_V8_MENU_ITEMS) + _existing_non_perf:
        _key = _item.get("key") if isinstance(_item, dict) else None
        if not _key or _key in _seen:
            continue
        _seen.add(_key)
        _deduped.append(_item)
    _perf["items"] = _deduped
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2150)")
FORCE_VISIBLE_MENU_ROLES = globals().get("FORCE_VISIBLE_MENU_ROLES", {})  # noqa: F821 - dynamic menu registry global
try:
    for _key in (_BYS360_PERF_RM_V8_GENERAL_REMOVE_KEYS | _BYS360_PERF_RM_V8_ALIAS_REMOVE_KEYS | {"performance_module", "performance_management", "performans_yonetimi"}):
        FORCE_VISIBLE_MENU_ROLES.pop(_key, None)  # noqa: F821 - dynamic menu registry global
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2159)")
_BYS360_PERF_RM_V8_ROLE_POLICY = {
    "admin": {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS},
    "baskan": {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS if "baskan" in set(item.get("required_roles", []))},
    "baskan_yardimcisi": {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS if "baskan_yardimcisi" in set(item.get("required_roles", []))},
    "grup_baskani": {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS if "grup_baskani" in set(item.get("required_roles", []))},
    "mali_musavir": {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS if "mali_musavir" in set(item.get("required_roles", []))},
    "koordinator": {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS if "koordinator" in set(item.get("required_roles", []))},
    "birim_sorumlusu": {item["key"] for item in _BYS360_PERF_RM_V8_MENU_ITEMS if "birim_sorumlusu" in set(item.get("required_roles", []))},
    "personel": {"performance_module", "performance_scorecard", "performance_archive", "my_performance_comparison", "performance_self_assessment"},
}
try:
    for _role, _keys in _BYS360_PERF_RM_V8_ROLE_POLICY.items():
        _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
        if isinstance(_current, set):
            _current.update(_keys)
        elif isinstance(_current, list):
            _current.extend([_key for _key in _keys if _key not in _current])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2178)")

# PHASE3A_MENU_REGISTRY_EXPLICIT_SIDEBAR_BUILDER_BEGIN
def build_sidebar_menu_sections(menu_visibility_map, current_endpoint, current_path, runtime_context=None, user=None):
    """Build sidebar menu sections through one explicit public layer.

    Flattened legacy wrapper chain:
    - Base menu generation is handled by _build_sidebar_menu_sections_base.
    - The legacy performance_module menu key is removed.
    - Old performance role-matrix keys are removed from the General section.
    """
    _sections = _build_sidebar_menu_sections_base(
        menu_visibility_map,
        current_endpoint,
        current_path,
        runtime_context,
        user,
    )

    for _section in _sections:
        _items = list(_section.get("items", []) or [])

        if _section.get("key") == "genel" or _section.get("label") == "Genel":
            _items = [
                _item
                for _item in _items
                if _item.get("key") not in _BYS360_PERF_RM_V8_GENERAL_REMOVE_KEYS
            ]

        _items = [
            _item
            for _item in _items
            if _item.get("key") != "performance_module"
        ]

        _section["items"] = _items

    return [_section for _section in _sections if _section.get("items")]
# PHASE3A_MENU_REGISTRY_EXPLICIT_SIDEBAR_BUILDER_END

# BYS360_PERFORMANCE_ROLE_MATRIX_PERSONNEL_V8_END

# BYS360_GENERAL_CATEGORY_VISIBILITY_FIX_V1_BEGIN
# Genel kategori anahtar aliaslari ve varsayilanlari.
try:
    MENU_KEY_CANONICAL_MAP.update({"genel": "general_section", "general": "general_section"})
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2198)")
try:
    MENU_KEY_ALIASES.setdefault("general_section", set()).update({"genel", "general"})
    MENU_KEY_ALIASES.setdefault("genel", set()).update({"general_section", "general"})
    MENU_KEY_ALIASES.setdefault("general", set()).update({"general_section", "genel"})
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2204)")
_BYS360_GENERAL_CATEGORY_DEFAULT_ROLES_V1 = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi", "administrator",
    "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel", "user", "standart_personel",
}
_BYS360_GENERAL_CATEGORY_DEFAULT_KEYS_V1 = {"general_section", "home", "dashboard", "notifications", "support_index", "support_new", "support_my_tickets"}
try:
    for _role in _BYS360_GENERAL_CATEGORY_DEFAULT_ROLES_V1:
        _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
        if isinstance(_current, set):
            _current.update(_BYS360_GENERAL_CATEGORY_DEFAULT_KEYS_V1)
        elif isinstance(_current, list):
            _current.extend([_key for _key in _BYS360_GENERAL_CATEGORY_DEFAULT_KEYS_V1 if _key not in _current])
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2218)")
try:
    FORCE_VISIBLE_MENU_ROLES.setdefault("general_section", set()).update(_BYS360_GENERAL_CATEGORY_DEFAULT_ROLES_V1)  # noqa: F821 - dynamic menu registry global
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2222)")
# BYS360_GENERAL_CATEGORY_VISIBILITY_FIX_V1_END

# BYS360_HOME_MENU_ALWAYS_VISIBLE_V1_BEGIN
# Anasayfa temel menü anahtarıdır; tüm rol varsayılanlarında korunur.
try:
    _BYS360_HOME_MENU_ALWAYS_VISIBLE_ROLES_V1 = set(ROLE_MENU_DEFAULTS.keys()) | {  # noqa: F821 - dynamic menu registry global
        "admin", "super_admin", "system_admin", "sistem_yoneticisi", "administrator",
        "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator",
        "birim_sorumlusu", "personel", "user", "standart_personel",
    }
    for _role in _BYS360_HOME_MENU_ALWAYS_VISIBLE_ROLES_V1:
        _items = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
        if isinstance(_items, set):
            _items.update({"general_section", "home", "account", "logout"})
        elif isinstance(_items, list):
            for _key in ["general_section", "home", "account", "logout"]:
                if _key not in _items:
                    _items.append(_key)
    try:
        FORCE_VISIBLE_MENU_ROLES.setdefault("home", set()).update(_BYS360_HOME_MENU_ALWAYS_VISIBLE_ROLES_V1)  # noqa: F821 - dynamic menu registry global
        FORCE_VISIBLE_MENU_ROLES.setdefault("general_section", set()).update(_BYS360_HOME_MENU_ALWAYS_VISIBLE_ROLES_V1)  # noqa: F821 - dynamic menu registry global
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2245)")
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/menu_registry.py:2247)")
# BYS360_HOME_MENU_ALWAYS_VISIBLE_V1_END


# BYS360_DAILY_WEATHER_MAIL_EXEC_ROLE_DEFAULTS_V1_0_7_BEGIN
try:
    _BYS360_DAILY_WEATHER_SYSTEM_ADMIN_ROLES = {'admin', 'super_admin', 'system_admin', 'sistem_yoneticisi'}
    _BYS360_DAILY_WEATHER_DISALLOWED_ROLES = {'baskan', 'baskan_yardimcisi', 'grup_baskani', 'mali_musavir', 'koordinator', 'birim_sorumlusu', 'performans_yetkilisi', 'personel', 'user', 'employee', 'ik', 'hr'}
    for _role in _BYS360_DAILY_WEATHER_DISALLOWED_ROLES:
        try:
            ROLE_MENU_DEFAULTS.setdefault(_role, set()).discard("daily_weather_mail")  # noqa: F821 - dynamic menu registry global
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:1367")
            pass
    for _role in _BYS360_DAILY_WEATHER_SYSTEM_ADMIN_ROLES:
        ROLE_MENU_DEFAULTS.setdefault(_role, set()).add("executive_summary")  # noqa: F821 - dynamic menu registry global
        ROLE_MENU_DEFAULTS.setdefault(_role, set()).add("daily_weather_mail")  # noqa: F821 - dynamic menu registry global
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:1372")
    pass
# BYS360_DAILY_WEATHER_MAIL_EXEC_ROLE_DEFAULTS_V1_0_7_END

# BYS360_EXECUTIVE_SUMMARY_V1_0_10_ADMIN_ONLY_MENU_LOCK_BEGIN
# Yönetici Özeti ailesi statik rol politikası: yalnız sistem yöneticisi / teknik admin.
try:
    _BYS360_EXEC_ADMIN_ONLY_ROLES = {'admin', 'administrator', 'sistem_yoneticisi', 'super_admin', 'system_admin'}
    _BYS360_EXEC_KNOWN_KEYS = {'daily_weather_mail', 'executive_summary_tasks', 'executive_summary_automatic_emails', 'executive_summary_auto_emails', 'executive_summary_logs', 'executive_summary_mail_logs', 'executive_summary_panel', 'executive_summary_test_send', 'executive_daily_weather_mail', 'executive_summary_scheduled_jobs', 'executive_summary_test', 'executive_summary', 'executive_summary_admin_panel', 'executive_summary_dashboard'}
    for _policy_name in ["ROLE_MENU_DEFAULTS", "ROLE_MENU_POLICY", "ROLE_MATRIX_POLICY", "PHASE3_PERFORMANCE_MENU_POLICY", "PHASE3_2_PERFORMANCE_MENU_POLICY"]:
        _policy = globals().get(_policy_name)
        if isinstance(_policy, dict):
            for _key in _BYS360_EXEC_KNOWN_KEYS:
                if _key in _policy or _key.startswith("executive") or _key == "daily_weather_mail":
                    _policy[_key] = set(_BYS360_EXEC_ADMIN_ONLY_ROLES)
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:1387")
    pass
# BYS360_EXECUTIVE_SUMMARY_V1_0_10_ADMIN_ONLY_MENU_LOCK_END

# BYS360_PERFORMANCE_V2_1_3A_RUNTIME_MENU_GUARD_BEGIN
try:
    _BYS360_V213A_CATEGORY_MENU_KEY = "performance_personnel_category_card"
    _BYS360_V213A_CATEGORY_MENU_ITEM = {
        "key": _BYS360_V213A_CATEGORY_MENU_KEY,
        "label": "Personel Kategori Atama",
        "icon": "fa-solid fa-tags",
        "endpoint": "main.performance_v2_1_3_personnel_category_card",
        "active_endpoints": ["main.performance_v2_1_3_personnel_category_card"],
        "active_path_prefixes": ["/performance/v2-1-3-personnel-category-card"],
        "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi"],
    }
    for _section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global
        if _section.get("key") == "performans" or _section.get("label") == "Performans Yönetimi":
            _items = _section.setdefault("items", [])
            if not any((_item or {}).get("key") == _BYS360_V213A_CATEGORY_MENU_KEY for _item in _items):
                _insert_at = next((idx for idx, _item in enumerate(_items) if (_item or {}).get("key") == "performance_kpi_dashboard"), len(_items))
                _items.insert(_insert_at, dict(_BYS360_V213A_CATEGORY_MENU_ITEM))
            break
    for _role in ("admin", "super_admin", "system_admin", "sistem_yoneticisi"):
        ROLE_MENU_DEFAULTS.setdefault(_role, set()).add(_BYS360_V213A_CATEGORY_MENU_KEY)  # noqa: F821 - dynamic menu registry global
    FORCE_VISIBLE_MENU_ROLES.setdefault(_BYS360_V213A_CATEGORY_MENU_KEY, set()).update({"admin", "super_admin", "system_admin", "sistem_yoneticisi"})  # noqa: F821 - dynamic menu registry global
except Exception:
    import logging as _logging
    _logging.getLogger(__name__).exception("BYS360 V2.1.3A personel kategori menü guard uygulanamadı")
# BYS360_PERFORMANCE_V2_1_3A_RUNTIME_MENU_GUARD_END

# BYS360_PERFORMANCE_V2_1_3B_FORCE_PERSONNEL_CATEGORY_MENU_BEGIN
# V2.1.3B: Personel Kategori Atama menüsünü sol şerit registry tarafında emniyete alır.
try:
    _bys360_v213b_key = "performance_personnel_category_card"
    _bys360_v213b_item = {
        "key": _bys360_v213b_key,
        "label": "Personel Kategori Atama",
        "icon": "fa-solid fa-tags",
        "endpoint": "main.performance_v2_1_3_personnel_category_card",
        "active_endpoints": ["main.performance_v2_1_3_personnel_category_card", "performance_v2_1_3_personnel_category_card"],
        "active_path_prefixes": ["/performance/v2-1-3-personnel-category-card"],
        "url": "/performance/v2-1-3-personnel-category-card",
        "href": "/performance/v2-1-3-personnel-category-card",
        "required_roles": ["admin", "super_admin", "system_admin", "sistem_yoneticisi"],
    }
    if "MENU_SECTIONS" in globals():
        _section_found = False
        for _section in MENU_SECTIONS:  # noqa: F821 - dynamic menu registry global
            _section_key = str((_section or {}).get("key") or "").lower()
            _section_label = str((_section or {}).get("label") or "").lower()
            if _section_key in {"performans", "performance", "performance_management"} or "performans" in _section_label:
                _items = _section.setdefault("items", [])
                if not any(((_item or {}).get("key") == _bys360_v213b_key) for _item in _items):
                    _items.append(dict(_bys360_v213b_item))
                _section_found = True
                break
        if not _section_found:
            MENU_SECTIONS.append({  # noqa: F821 - dynamic menu registry global
                "key": "performans",
                "label": "Performans Yönetimi",
                "icon": "fa-solid fa-chart-line",
                "items": [dict(_bys360_v213b_item)],
            })
    if "ROLE_MENU_DEFAULTS" in globals():
        for _role in ("admin", "super_admin", "system_admin", "sistem_yoneticisi"):
            _current = ROLE_MENU_DEFAULTS.setdefault(_role, set())  # noqa: F821 - dynamic menu registry global
            try:
                _current.add(_bys360_v213b_key)
            except AttributeError:
                if _bys360_v213b_key not in _current:
                    _current.append(_bys360_v213b_key)
    if "FORCE_VISIBLE_MENU_ROLES" in globals():
        FORCE_VISIBLE_MENU_ROLES.setdefault(_bys360_v213b_key, set()).update({"admin", "super_admin", "system_admin", "sistem_yoneticisi"})  # noqa: F821 - dynamic menu registry global
    if "LIVE_SETTINGS_MENU_KEYS" in globals():
        try:
            LIVE_SETTINGS_MENU_KEYS.add(_bys360_v213b_key)  # noqa: F821 - dynamic menu registry global
        except AttributeError:
            if _bys360_v213b_key not in LIVE_SETTINGS_MENU_KEYS:  # noqa: F821 - dynamic menu registry global
                LIVE_SETTINGS_MENU_KEYS.append(_bys360_v213b_key)  # noqa: F821 - dynamic menu registry global
except Exception:
    import logging as _logging
    _logging.getLogger(__name__).exception("BYS360 V2.1.3B personel kategori menü görünürlük guard uygulanamadı")
# BYS360_PERFORMANCE_V2_1_3B_FORCE_PERSONNEL_CATEGORY_MENU_END

# BYS360_PERFORMANCE_V2_1_5_CATEGORY_PERIOD_SCOPE_MENU_BEGIN
try:
    _bys360_v215_item = {"key":"performance_category_period_scope","label":"Kategori Dönem Kapsamı","endpoint":"main.performance_v2_1_5_category_period_scope","url":"/performance/v2-1-5-category-period-scope","icon":"fa-calendar-check"}
    if "MENU_SECTIONS" in globals():
        _perf = next((_section for _section in MENU_SECTIONS if isinstance(_section, dict) and (_section.get("key") == "performans" or _section.get("label") == "Performans Yönetimi")), None)  # noqa: F821 - dynamic menu registry global
        if _perf is None:
            _perf = {"key": "performans", "label": "Performans Yönetimi", "icon": "fa-solid fa-chart-line", "items": []}
            MENU_SECTIONS.append(_perf)  # noqa: F821 - dynamic menu registry global
        _items = _perf.setdefault("items", [])
        if not any(isinstance(_i, dict) and _i.get("key") == "performance_category_period_scope" for _i in _items):
            _items.append(dict(_bys360_v215_item))
    if "ROLE_MENU_DEFAULTS" in globals():
        for _role in ("admin", "super_admin", "system_admin", "sistem_yoneticisi"):
            ROLE_MENU_DEFAULTS.setdefault(_role, set()).add("performance_category_period_scope")  # noqa: F821 - dynamic menu registry global
    if "LIVE_MENU_SCOPE" in globals():
        try:
            LIVE_MENU_SCOPE.add("performance_category_period_scope")  # noqa: F821 - dynamic menu registry global
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:1490")
            pass
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:1491")
    pass
# BYS360_PERFORMANCE_V2_1_5_CATEGORY_PERIOD_SCOPE_MENU_END

# BYS360_PERFORMANCE_V2_1_6_CATEGORY_PERIOD_INTEGRATION_MENU_BEGIN
try:
    _bys360_v216_item = {"key":"performance_category_period_integration","label":"Kategori Dönem Entegrasyonu","endpoint":"main.performance_v2_1_6_category_period_integration","url":"/performance/v2-1-6-category-period-integration","icon":"fa-link"}
    if "MENU_SECTIONS" in globals():
        _perf = next((_section for _section in MENU_SECTIONS if isinstance(_section, dict) and (_section.get("key") == "performans" or _section.get("label") == "Performans Yönetimi")), None)  # noqa: F821 - dynamic menu registry global
        if _perf is None:
            _perf = {"key": "performans", "label": "Performans Yönetimi", "icon": "fa-solid fa-chart-line", "items": []}
            MENU_SECTIONS.append(_perf)  # noqa: F821 - dynamic menu registry global
        _items = _perf.setdefault("items", [])
        if not any(isinstance(_i, dict) and _i.get("key") == "performance_category_period_integration" for _i in _items):
            _items.append(dict(_bys360_v216_item))
    if "ROLE_MENU_DEFAULTS" in globals():
        for _role in ("admin", "super_admin", "system_admin", "sistem_yoneticisi"):
            ROLE_MENU_DEFAULTS.setdefault(_role, set()).add("performance_category_period_integration")  # noqa: F821 - dynamic menu registry global
    if "LIVE_MENU_SCOPE" in globals():
        try:
            LIVE_MENU_SCOPE.add("performance_category_period_integration")  # noqa: F821 - dynamic menu registry global
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:1511")
            pass
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/menu_registry.py:1512")
    pass
# BYS360_PERFORMANCE_V2_1_6_CATEGORY_PERIOD_INTEGRATION_MENU_END
# BYS360_A5_P2D2_FEEDBACK_PULSE_MENU_REGISTRY_START
# Nab?z ?l??m? men? kay?t s?zle?mesi.
FEEDBACK_PULSE_MENU_REGISTRY_CONTRACT = [
    {
        "key": "feedback_pulse",
        "label": "Nab?z ?l??m?",
        "endpoint": "main.feedback_pulse",
        "analytics_endpoint": "main.feedback_pulse_analytics",
        "admin_endpoint": "main.feedback_admin_pulse_analytics",
    }
]
# BYS360_A5_P2D2_FEEDBACK_PULSE_MENU_REGISTRY_END
# BYS360_A5_P2D2_FEEDBACK_PULSE_ROUTE_SUPPORT_POLICY_START
# Nab?z ?l??m?, geri bildirim ?ekirde?inin kurum geneli g?r?n?r alt mod?l?d?r.
FEEDBACK_PULSE_CORE_MENU_POLICY = {
    "feedback_pulse": {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"},
}
# Static contract anchor: "feedback_pulse": {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"}
# Static contract anchor: "feedback_pulse"
# BYS360_A5_P2D2_FEEDBACK_PULSE_ROUTE_SUPPORT_POLICY_END


# BYS360_K13_PERSONEL_STATIC_DEFAULT_ALIGNMENT_START
# K13 (19 Oct 2026): the static personel default carried seven keys whose menu definition
# (required_roles) excludes personel. The old seeder copied them into role_menu_defaults as "seed"
# rows on every GET /settings, which lifted the static role gate and opened 14 performance GET routes,
# run-alerts/run-digest and /support/assigned to every personel. performance_self_assessment stays.
_BYS360_K13_PERSONEL_KEYS_OUTSIDE_ROLE_DEFINITION = {
    "feedback_actions",
    "feedback_admin",
    "feedback_manager",
    "feedback_results",
    "performance_feedback_meetings",
    "performance_tasks",
    "support_assigned",
}
ROLE_MENU_DEFAULTS.setdefault("personel", set()).difference_update(_BYS360_K13_PERSONEL_KEYS_OUTSIDE_ROLE_DEFINITION)  # noqa: F821 - dynamic menu registry global
# BYS360_K13_PERSONEL_STATIC_DEFAULT_ALIGNMENT_END


# BYS360_A5_P2D4_LIVE_SCOPE_PORTAL_PREFIX_ANCHOR_START
# Static contract anchor: /portal
# Portal prefix canl? kapsam/karantina s?zle?mesinde a??k?a izlenir.
# BYS360_A5_P2D4_LIVE_SCOPE_PORTAL_PREFIX_ANCHOR_END

