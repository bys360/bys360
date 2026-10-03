from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PACKAGE = "BYS360_PHASE3B_MOBILE_PERFORMANCE_CONFIG_HELPERS_GATE_V1"
REPORT_REL = Path("reports/architecture/BYS360_PHASE3B_MOBILE_PERFORMANCE_CONFIG_HELPERS_GATE_V1_REPORT.json")

ROOT_REL_ROUTE = Path("app/api/mobile/performance_routes.py")
ROOT_REL_SERVICE = Path("app/api/mobile/services/performance_config_helpers.py")

EXPECTED_HELPERS = [
    "_v2821_float",
    "_v2821_percent",
    "_v2821_active_text",
    "_v2821_mode_text",
    "_v2821_period_label",
    "_v2821_criteria_item",
    "_v2821_weight_item",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _route_decorator_count(text: str) -> int:
    pattern = re.compile(r"^@\w+(?:_\w+)*\.(?:route|get|post|put|patch|delete)\(", re.MULTILINE)
    return len(pattern.findall(text))


def _defined_functions(text: str) -> set[str]:
    pattern = re.compile(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
    return set(pattern.findall(text))


def _config_helper_imports(text: str) -> dict[str, set[str]]:
    imports: dict[str, set[str]] = {
        "app.api.mobile.shared": set(),
        "app.api.mobile.routes": set(),
    }
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return imports
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module is not None
            and node.module in imports
        ):
            imports[node.module].update(alias.name for alias in node.names)
    return imports


def run_checks(root: Path, write_report: bool = True) -> dict[str, Any]:
    route_path = root / ROOT_REL_ROUTE
    service_path = root / ROOT_REL_SERVICE

    route_text = _read(route_path)
    service_text = _read(service_path)

    route_functions = _defined_functions(route_text)
    service_functions = _defined_functions(service_text)

    helper_presence = {name: name in service_functions for name in EXPECTED_HELPERS}
    helper_removed_from_route = {name: name not in route_functions for name in EXPECTED_HELPERS}

    route_import_ok = "from app.api.mobile.services.performance_config_helpers import" in route_text
    helper_imports = _config_helper_imports(service_text)
    canonical_item_import_ok = "_item" in helper_imports["app.api.mobile.shared"]
    facade_item_import_absent = "_item" not in helper_imports["app.api.mobile.routes"]
    service_imports_ok = all(token in service_text for token in [
        "from app.models import PerformancePeriod",
        "from app.api.mobile.services.performance_base_helpers import _period_name",
        "def _safe_get_period(",
    ])

    result: dict[str, Any] = {
        "package": PACKAGE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "config_helpers_gate_ok": False,
        "route_path": str(ROOT_REL_ROUTE),
        "service_path": str(ROOT_REL_SERVICE),
        "route_exists": route_path.exists(),
        "service_exists": service_path.exists(),
        "route_lines": len(route_text.splitlines()),
        "service_lines": len(service_text.splitlines()),
        "route_decorator_count": _route_decorator_count(route_text),
        "route_line_reduction_ok": len(route_text.splitlines()) < 1624,
        "route_import_ok": route_import_ok,
        "service_imports_ok": service_imports_ok,
        "canonical_item_import_ok": canonical_item_import_ok,
        "facade_item_import_absent": facade_item_import_absent,
        "helper_presence": helper_presence,
        "helper_removed_from_route": helper_removed_from_route,
        "expected_helpers": EXPECTED_HELPERS,
    }

    result["config_helpers_gate_ok"] = bool(
        result["route_exists"]
        and result["service_exists"]
        and result["route_import_ok"]
        and result["service_imports_ok"]
        and result["canonical_item_import_ok"]
        and result["facade_item_import_absent"]
        and result["route_decorator_count"] == 22
        and result["route_line_reduction_ok"]
        and all(helper_presence.values())
        and all(helper_removed_from_route.values())
    )

    if write_report:
        report = root / REPORT_REL
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["report"] = str(report)

    return result


def main() -> int:
    root = Path.cwd()
    result = run_checks(root, write_report=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["config_helpers_gate_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
