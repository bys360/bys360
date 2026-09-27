"""BYS360 PERFORMANCE P0.2A: dead legacy cleanup safety contract.

app/services/performance/low_score_process_service.py carried 22
``_legacy_*_phaseN`` function twins plus one alias
(``_legacy_record_first_low_score_warning_phase3``). None of them was
referenced from live code, other modules, templates, scripts or tests, and no
dynamic lookup (getattr on the module, globals()/vars(), __all__, string
registry, decorator) could reach them, verified at commit
4b23f13a48ad2a4618f8a8bca4ccdccccf27a3fb before removal.

These tests pin what the removal must not change:

- the public callable surface of the service (names + signatures),
- every module-level ``from ...low_score_process_service import ...`` in app/
  still resolving to the very same service object. This matters most for
  app/services/performance/visibility_guard.py, which silently falls back to
  a no-lock stub (``return ""``) if that import ever fails,
- the low-score route endpoints registered by create_app(),
- no reference to any removed legacy name anywhere in app/, scripts/ or tests/.

Behavioral coverage of the live flows (approve/reject, first warning,
repeated low score, stage/status, publish lock) stays in the P0/P0.1 contract
tests and in the DB-backed workflow tests.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_SERVICE_PATH = _REPO_ROOT / "app" / "services" / "performance" / "low_score_process_service.py"
_LEGACY_TWIN_RE = re.compile(r"^_legacy_\w+_phase\d+$")

_PUBLIC_SURFACE = {
    "LowScorePeriodSummary": "(total: 'int', pending_president: 'int', pending_hr: 'int', pending_warning: 'int', pending_admin_process: 'int', ready_for_publish: 'int') -> None",
    "add_low_score_process_note": "(process_or_id, user_or_id=None, note=None)",
    "auto_record_first_low_score_warning": "(process, *, actor=None, note=None, user_or_id=None)",
    "auto_start_second_low_score_process": "(process, *, actor=None, note=None, user_or_id=None)",
    "build_low_score_period_summary": "(period: 'PerformancePeriod | None') -> 'dict[str, int]'",
    "build_low_score_process_rows": "(processes=None)",
    "build_process_timeline": "(process=None)",
    "calculate_sequence_no": "(evaluation: 'PerformanceEvaluation') -> 'int'",
    "ensure_low_score_process_for_evaluation": "(evaluation: 'PerformanceEvaluation | None', *, actor_user_id: 'int | None' = None, flush: 'bool' = True) -> 'PerformanceLowScoreProcess | None'",
    "ensure_low_score_processes_for_period": "(period: 'PerformancePeriod | None', *, actor_user_id: 'int | None' = None) -> 'dict[str, Any]'",
    "get_low_score_employee_publish_lock_reason": "(evaluation=None, *, ensure=False)",
    "get_low_score_publish_block_reason": "(process=None, evaluation=None, ensure=True)",
    "hr_precheck_process": "(process: 'PerformanceLowScoreProcess', *, actor: 'Any' = None, note: 'str | None' = None) -> 'PerformanceLowScoreProcess'",
    "humanize_low_score_status": "(value) -> 'str'",
    "humanize_process_status": "(status=None)",
    "is_low_score_employee_publish_released": "(evaluation=None)",
    "is_low_score_evaluation": "(evaluation: 'PerformanceEvaluation | float | int | None') -> 'bool'",
    "president_approve_process": "(process, *, actor=None, note=None, user_or_id=None)",
    "president_reject_process": "(process, *, actor=None, note=None, user_or_id=None)",
    "record_first_low_score_warning": "(process_or_id, user_or_id=None, note=None)",
    "record_first_warning": "(process, *, actor=None, note=None, user_or_id=None)",
    "start_second_repeat_admin_process": "(process, *, actor=None, note=None, user_or_id=None)",
}

_LOW_SCORE_ROUTE_ENDPOINTS = {
    "main.performance_low_score_add_note",
    "main.performance_low_score_hr_check",
    "main.performance_low_score_president_approve",
    "main.performance_low_score_president_reject",
    "main.performance_low_score_process_sync",
    "main.performance_low_score_processes",
    "main.performance_low_score_record_warning",
    "main.performance_low_score_start_admin_process",
}

_REMOVED_LEGACY_NAMES = (
    "_legacy_add_low_score_process_note_phase1",
    "_legacy_auto_record_first_low_score_warning_phase1",
    "_legacy_auto_record_first_low_score_warning_phase3",
    "_legacy_auto_start_second_low_score_process_phase2",
    "_legacy_get_low_score_employee_publish_lock_reason_phase1",
    "_legacy_get_low_score_employee_publish_lock_reason_phase3",
    "_legacy_get_low_score_publish_block_reason_phase1",
    "_legacy_get_low_score_publish_block_reason_phase2",
    "_legacy_get_low_score_publish_block_reason_phase3",
    "_legacy_humanize_process_status_phase1",
    "_legacy_is_low_score_employee_publish_released_phase1",
    "_legacy_is_low_score_employee_publish_released_phase2",
    "_legacy_is_low_score_employee_publish_released_phase3",
    "_legacy_president_approve_process_phase1",
    "_legacy_president_approve_process_phase2",
    "_legacy_president_reject_process_phase1",
    "_legacy_president_reject_process_phase2",
    "_legacy_record_first_low_score_warning_phase2",
    "_legacy_record_first_low_score_warning_phase3",
    "_legacy_record_first_warning_phase1",
    "_legacy_record_first_warning_phase3",
    "_legacy_start_second_repeat_admin_process_phase1",
    "_legacy_start_second_repeat_admin_process_phase2",
)


@pytest.fixture(scope="module")
def svc() -> Any:
    return importlib.import_module(_SERVICE_MODULE)


def _module_level_service_imports() -> list[tuple[str, str, str]]:
    """(importer module, imported name, bound name) for every module-level
    ``from app.services.performance.low_score_process_service import ...`` in
    app/, including ones inside a top-level try block."""
    found: list[tuple[str, str, str]] = []
    for path in sorted((_REPO_ROOT / "app").rglob("*.py")):
        if path == _SERVICE_PATH:
            continue
        # utf-8-sig: a few app modules start with a BOM.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        statements: list[ast.stmt] = []
        for node in tree.body:
            statements.append(node)
            if isinstance(node, ast.Try):
                statements.extend(node.body)
        module = ".".join(path.relative_to(_REPO_ROOT).with_suffix("").parts)
        for node in statements:
            if isinstance(node, ast.ImportFrom) and node.module == _SERVICE_MODULE:
                found.extend((module, alias.name, alias.asname or alias.name) for alias in node.names)
    return found


def test_public_service_surface_is_unchanged(svc) -> None:
    surface = {
        name: str(inspect.signature(obj))
        for name, obj in vars(svc).items()
        if callable(obj) and getattr(obj, "__module__", None) == svc.__name__ and not name.startswith("_")
    }
    assert surface == _PUBLIC_SURFACE


def test_every_module_level_service_import_resolves_to_the_live_service_object(app, svc) -> None:
    imports = _module_level_service_imports()
    importers = {module for module, _, _ in imports}
    # visibility_guard.py falls back to a no-lock stub if this import fails.
    assert "app.services.performance.visibility_guard" in importers
    assert "app.performance.low_score_process_routes" in importers
    for module, name, bound in imports:
        importer = importlib.import_module(module)
        assert getattr(importer, bound) is getattr(svc, name), (module, name)


def test_low_score_route_endpoints_are_registered(app) -> None:
    endpoints = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if getattr(app.view_functions.get(rule.endpoint), "__module__", "") == "app.performance.low_score_process_routes"
    }
    assert endpoints == _LOW_SCORE_ROUTE_ENDPOINTS


def test_service_defines_no_legacy_phase_twins(svc) -> None:
    # Post-removal guard: fails if a `_legacy_*_phaseN` twin is re-added.
    assert [name for name in vars(svc) if _LEGACY_TWIN_RE.match(name)] == []
    assert re.search(r"_legacy_\w+_phase\d", _SERVICE_PATH.read_text(encoding="utf-8")) is None


def test_event_model_has_no_misplaced_publish_gate_property() -> None:
    """The publish gate belongs to PerformanceLowScoreProcess only. The copy
    that used to sit on PerformanceLowScoreProcessEvent was double-wrapped
    (``@property @property``), raised TypeError on every access and had no
    caller; it was removed in P0.2A."""
    from app.models import PerformanceLowScoreProcess, PerformanceLowScoreProcessEvent

    assert "is_finalized_for_publish" not in vars(PerformanceLowScoreProcessEvent)
    assert not hasattr(PerformanceLowScoreProcessEvent(step_key="x", title="t"), "is_finalized_for_publish")
    assert isinstance(vars(PerformanceLowScoreProcess)["is_finalized_for_publish"], property)


def test_removed_legacy_names_are_not_referenced_outside_the_service() -> None:
    this_file = Path(__file__).resolve()
    offenders: list[str] = []
    for root in ("app", "scripts", "tests"):
        for path in sorted((_REPO_ROOT / root).rglob("*")):
            if path.suffix not in {".py", ".html", ".js"} or path.resolve() in {this_file, _SERVICE_PATH}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            offenders.extend(
                f"{path.relative_to(_REPO_ROOT).as_posix()}: {name}" for name in _REMOVED_LEGACY_NAMES if name in text
            )
    assert offenders == []
