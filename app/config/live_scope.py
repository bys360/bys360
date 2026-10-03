
"""Canlı kapsam karantina yardımcıları.

Faz 6 ile kaldırılan modüllerin kalan endpoint/menu izleri tek yerden
denetlenir. Amaç, çalışan çekirdek sistemi bozmadan legacy linkleri nazikçe
karantinaya almak ve görünürlük haritasını sadeleştirmektir.
"""
from __future__ import annotations

from app.config.removed_modules import is_removed

REMOVED_ROUTE_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "strategy": ("/strategy", "/ai/strategy"),
    "education": ("/education", "/education-isg", "/egitim-isg", "/isg", "/ai/education", "/ai/education-isg", "/ai/isg", "/hr-management/rotation"),
    "repository": ("/repository", "/ai/repository"),
}

REMOVED_ROUTE_ENDPOINT_PREFIXES: dict[str, tuple[str, ...]] = {
    "strategy": ("main.strategy_",),
    "education": ("main.education_", "main.education_isg_", "main.isg_", "main.hr_rotation_management"),
    "repository": ("main.repository_", "main.education_repository_", "main.strategy_repository_"),
}

REMOVED_SCOPE_COMPAT_ENDPOINTS: set[str] = {
    "main.education_reports_export_legacy",
    "main.strategy_reports_export_compat",
}

REMOVED_SCOPE_COMPAT_PATHS: set[str] = {
    "/education/reports/export-legacy",
    "/strategy/reports/export-legacy",
}

_DIRECT_MENU_KEY_MAP: dict[str, str] = {
# BYS360_MAINTENANCE_V13_REMOVED_DIRECT_MENU_KEYS
    "repository": "repository",
    "education": "education",
    "egitim": "education",
    "eğitim": "education",
    "strategy": "strategy",
    "strateji": "strategy",
    "education_management": "education",
    "training_assignments": "education",
    "certificate_management": "education",
    "isg_management": "education",
    "education_isg_management": "education",
    "strategy_management": "strategy",
}

_PREFIX_MENU_KEY_MAP: dict[str, str] = {
    "education_": "education",
    "isg_": "education",
    "strategy_": "strategy",
    "repository_": "repository",
}


def is_removed_route_endpoint(endpoint: str | None) -> bool:
    endpoint = str(endpoint or "").strip()
    if not endpoint:
        return False
    for module_name, prefixes in REMOVED_ROUTE_ENDPOINT_PREFIXES.items():
        if not is_removed(module_name):
            continue
        if any(endpoint == prefix or endpoint.startswith(prefix) for prefix in prefixes):
            return True
    return False


def is_removed_route_path(path: str | None) -> bool:
    path = str(path or "").strip()
    if not path:
        return False
    for module_name, prefixes in REMOVED_ROUTE_PATH_PREFIXES.items():
        if not is_removed(module_name):
            continue
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                return True
    return False


def is_removed_scope_compat(endpoint: str | None = None, path: str | None = None) -> bool:
    endpoint = str(endpoint or "").strip()
    path = str(path or "").strip()
    return endpoint in REMOVED_SCOPE_COMPAT_ENDPOINTS or path in REMOVED_SCOPE_COMPAT_PATHS


def is_removed_menu_key(menu_key: str | None) -> bool:
    key = str(menu_key or "").strip().lower()
    if not key:
        return False
    direct = _DIRECT_MENU_KEY_MAP.get(key)
    if direct:
        return is_removed(direct)
    for prefix, module_name in _PREFIX_MENU_KEY_MAP.items():
        if key.startswith(prefix) and is_removed(module_name):
            return True
    return False


def get_removed_scope_dashboard_target() -> str:
    return "main.dashboard"


LIVE_CORE_AREAS: tuple[str, ...] = (
    "dashboard",
    "personel_yetki",
    "organizasyon_hiyerarsi",
    "performance",
    "izin_vekalet",
    "iletisim_bildirim",
    "raporlama_karar_destek",
)

def get_removed_module_names() -> tuple[str, ...]:
    return tuple(sorted(module for module in REMOVED_ROUTE_PATH_PREFIXES if is_removed(module)))


def get_live_scope_summary() -> dict[str, object]:
    removed = get_removed_module_names()
    active_core = tuple(area for area in LIVE_CORE_AREAS)
    return {
        "active_core_areas": active_core,
        "active_core_count": len(active_core),
        "removed_modules": removed,
        "removed_module_count": len(removed),
        "compat_endpoint_count": len(REMOVED_SCOPE_COMPAT_ENDPOINTS),
        "compat_path_count": len(REMOVED_SCOPE_COMPAT_PATHS),
    }


def get_live_scope_release_notes() -> tuple[str, ...]:
    return (
        "Canlı kapsam çekirdek omurga ile sınırlandırıldı.",
        "Kaldırılan modül izleri route/menu seviyesinde karantinada tutuluyor.",
        "Fiziksel söküm ancak overlay manifest ve dry-run doğrulamasından sonra yapılmalı.",
    )
