"""BYS360 config yardımcı paketleri.

Canlı öncesi düşük riskli temizliklerde uygulama ayarlarından bağımsız,
kod tabanı içinde tutulacak küçük karar dosyaları burada yer alır.
"""

from .live_scope import (
    REMOVED_ROUTE_ENDPOINT_PREFIXES,
    REMOVED_ROUTE_PATH_PREFIXES,
    REMOVED_SCOPE_COMPAT_ENDPOINTS,
    REMOVED_SCOPE_COMPAT_PATHS,
    get_live_scope_release_notes,
    get_live_scope_summary,
    get_removed_module_names,
    get_removed_scope_dashboard_target,
    is_removed_menu_key,
    is_removed_route_endpoint,
    is_removed_route_path,
    is_removed_scope_compat,
)
from .removed_modules import (
    REMOVED_MODULE_ALIASES,
    REMOVED_MODULES,
    get_removed_modules,
    is_module_removed,
    is_removed,
)

__all__ = [
    "REMOVED_MODULES",
    "REMOVED_MODULE_ALIASES",
    "get_removed_modules",
    "is_module_removed",
    "is_removed",
    "REMOVED_ROUTE_ENDPOINT_PREFIXES",
    "REMOVED_ROUTE_PATH_PREFIXES",
    "REMOVED_SCOPE_COMPAT_ENDPOINTS",
    "REMOVED_SCOPE_COMPAT_PATHS",
    "get_removed_scope_dashboard_target",
    "get_live_scope_release_notes",
    "get_live_scope_summary",
    "get_removed_module_names",
    "is_removed_menu_key",
    "is_removed_route_endpoint",
    "is_removed_route_path",
    "is_removed_scope_compat",
]
