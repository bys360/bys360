from pathlib import Path

import pytest

from app.config.live_scope import (
    REMOVED_ROUTE_PATH_PREFIXES,
    is_removed_menu_key,
    is_removed_route_path,
)
from app.config.removed_modules import REMOVED_MODULES, is_module_removed

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def test_admin_org_units_has_single_owner():
    institutional_routes = text("app/institutional/routes.py")
    org_routes = text("app/institutional/org_unit_routes.py")
    assert "def admin_org_units" in org_routes
    assert "app.institutional.org_unit_routes" in institutional_routes
    assert "main_bp.add_url_rule(\n        \"/admin/org-units\"" not in institutional_routes
    assert 'endpoint="admin_org_units"' not in institutional_routes


def test_hr_reports_and_ai_breakdowns_are_defensive_templates():
    hr = text("app/templates/hr_reports.html")
    assert "{% for unit_name, count in unit_stats %}" not in hr
    assert "{% for row in unit_stats %}" in hr
    ai = text("app/templates/admin_ai_notification_priority.html")
    assert "type_breakdown.items() if type_breakdown is mapping" in ai
    assert "priority_breakdown.items() if priority_breakdown is mapping" in ai


def test_feedback_privacy_and_cache_are_kept():
    feedback = text("app/services/feedback_service.py")
    assert "_build_pulse_risk_users_from_rows" in feedback
    assert 'not bool(getattr(row, "is_anonymous", False))' in feedback
    assert "_PULSE_ANALYTICS_CACHE_KEY" in feedback
    assert "_set_pulse_cache" in feedback


def test_schema_guard_is_check_first_not_auto_repair_default():
    config = text("config.py")
    app_init = text("app/__init__.py")
    schema_guard = text("app/schema_guard.py")
    assert "str_to_bool(os.getenv('AUTO_REPAIR_SCHEMA'), False)" in config
    assert "auto_repair_schema and should_auto_repair_schema()" in app_init
    assert "BYS_SKIP_SCHEMA_GUARD" in schema_guard
    assert "db upgrade" in schema_guard


def test_removed_modules_stay_out_of_live_scope_and_menus():
    route_support = text("app/route_support.py")
    for module in ["repository", "education", "strategy"]:
        assert REMOVED_MODULES[module] is True
        assert is_module_removed(module) is True
        assert is_removed_menu_key(module) is True
        assert is_removed_menu_key(f"{module}_reports") is True
        for prefix in REMOVED_ROUTE_PATH_PREFIXES[module]:
            assert is_removed_route_path(prefix) is True
            assert is_removed_route_path(f"{prefix}/reports") is True
    assert "is_removed_menu_key" in route_support
    assert "active_menu_items" in route_support


def test_portal_remains_outside_removed_scope():
    assert REMOVED_MODULES["portal"] is False
    assert is_module_removed("portal") is False
    assert is_removed_menu_key("portal") is False
    assert is_removed_menu_key("portal_reports") is False
    assert is_removed_route_path("/portal") is False
    assert is_removed_route_path("/portal/reports") is False
    assert "portal" not in REMOVED_ROUTE_PATH_PREFIXES
    prefixes = [prefix for values in REMOVED_ROUTE_PATH_PREFIXES.values() for prefix in values]
    assert not any(prefix == "/portal" or prefix.startswith("/portal/") for prefix in prefixes)


@pytest.mark.parametrize(
    "config_path",
    ["app/config/removed_modules.py", "app/config/live_scope.py", "app/config/__init__.py"],
)
def test_config_has_no_stale_portal_comment_anchors(config_path: str):
    source = text(config_path)
    for anchor in [
        "BYS360_A5_P2D4_REMOVED_PORTAL_STATIC_ANCHOR",
        "BYS360_A5_P2D4_LIVE_SCOPE_PORTAL_PREFIX_ANCHOR",
        'Static contract anchor: "portal": True',
        "Static contract anchor: /portal",
    ]:
        assert anchor not in source


def test_releaseignore_excludes_non_release_artifacts():
    releaseignore = text(".releaseignore")
    for token in [".venv/", "__pycache__/", "*.pyc", "data/uploads/", "app/portal/", "app/**/*snippet*.py"]:
        assert token in releaseignore
