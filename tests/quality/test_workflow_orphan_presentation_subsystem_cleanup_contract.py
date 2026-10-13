"""BYS360 Workflow Orphan Presentation Subsystem Temizliği -- düzeltilmiş
Alternatif A+ cleanup contract.

CONTEXT: a prior, separate read-only audit ("BYS360 Workflow Alt Sistemi
Runtime Aktiflik, Test Kirliliği ve Orphan Kapsam Denetimi") independently
proved the entire `app/workflow/` presentation/route package was dead code:

    - `app/workflow/routes.py` (1218 lines, 12 `@main_bp.route(...)`
      decorators) was NEVER imported by any startup/bootstrap/application
      code -- only two test files imported it directly:
      `tests/workflow/test_phase5w_workflow_schema_readiness.py` and
      `tests/workflow/test_generic_sync_sql_identifier_phase5u.py`.
      `"app.workflow.routes"` appeared in `app/route_registry.py`'s
      `_BASE_MODULAR_ROUTE_MODULES` tuple, but that tuple is only ever
      returned by `get_runtime_route_manifest()` as documentation/metadata
      -- never iterated over to perform a real `importlib.import_module()`
      call (the REAL blueprint-registration mechanism is
      `app/bootstrap/route_bootstrap.py::CORE_BLUEPRINT_SEQUENCE`, which
      never listed `app.workflow` at all).
    - `app/workflow/dashboard_upgrade_routes.py` (its own separate
      `workflow_dashboard_upgrade_bp` Blueprint) was likewise never
      registered.
    - All 12 of `routes.py`'s claimed URLs resolved to a genuine 404 in a
      real, isolated `create_app()` -- none were SHADOWED by another live
      view at the same URL.
    - Both template trees (`app/templates/workflow/*.html` and
      `app/workflow/templates/workflow/*.html`, 7 filenames each, 6/7
      byte-identical between the two trees) had zero reachable renderer:
      `routes.py`'s own `safe_render()` calls (the only would-be consumer of
      the first tree) never executed since the module was never imported;
      the second tree was only reachable via `workflow_dashboard_upgrade_bp`
      's blueprint-scoped `template_folder`, and that blueprint was never
      registered either.
    - `app/services/workflow/dashboard_upgrade.py` (`demo_dashboard_data`,
      `build_performance_map`, `build_delayed_managers`,
      `build_risky_personnel`) had zero consumers besides the two dead route
      files above.
    - Directly importing `app.workflow.routes` in-process (as the two now-
      deleted test files did, at MODULE level -- meaning pytest's own
      COLLECTION phase, which imports every test file up front before any
      test function runs, triggered it regardless of file/test ordering)
      permanently mutated the shared, module-level singleton `main_bp`
      Blueprint object in `app.route_registry`: every subsequent
      `create_app()` call in that SAME process afterwards saw 997 routes
      instead of 985 (the 12 extra endpoints from `routes.py`'s
      decorators), with a different sorted-endpoint-list SHA-256. A fresh,
      separate process was unaffected -- independently reproduced with a
      real A(clean)/B(dirty)/C(re-clean) three-state experiment.

DELETED (this wave, düzeltilmiş Alternatif A+):
    - app/workflow/routes.py
    - app/workflow/dashboard_upgrade_routes.py
    - app/workflow/__init__.py (and the now-empty app/workflow/ directory)
    - app/services/workflow/dashboard_upgrade.py
    - 14 templates: app/templates/workflow/{dashboard,delays,
      executive_dashboard,modules,notifications,president_approvals,
      timeline}.html + app/workflow/templates/workflow/{same 7 names}.html
    - tests/workflow/test_phase5w_workflow_schema_readiness.py and
      tests/workflow/test_generic_sync_sql_identifier_phase5u.py (and the
      now-empty tests/workflow/ directory) -- both tested ONLY functions
      defined inside the now-deleted app/workflow/routes.py
      (`assert_workflow_schema_ready`/`ensure_tables`,
      `_sync_generic_table`); there is no meaningful "absence contract" for
      unit tests of business logic that no longer exists anywhere -- the
      route file's own deletion (and this contract file's evidence of it)
      IS the absence contract.
    - The single `"app.workflow.routes"` entry in `app/route_registry.py`'s
      `_BASE_MODULAR_ROUTE_MODULES` tuple (the inert-but-misleading manifest
      string that made the dead module look like a live, tracked candidate)
      -- nothing else in that file was touched.

PRESERVED (explicitly out of scope, independently re-verified below, NOT
the same thing despite sharing the word "workflow"): `app/services/workflow/
{constants,state,visibility,transitions,__init__}.py` (a completely
unrelated concept -- an EVALUATION state machine, consumed by
`app/services/evaluation_workflow_service.py` -> `app/services/query_health/
workflow_meta.py` + `app/services/performance/evaluation_form_service.py`),
`performance_president_approvals` (a real, shared, actively-referenced-in-30
-files database table and its whole process-engine service/model chain),
all migration files (`migrations/versions/6f2b8c4d1a90_*` and
`5a7c9e1f2b30_*`, which own the `workflow_instances`/`workflow_steps`/
`workflow_logs`/`workflow_notifications`/`performance_president_approvals`
schema -- untouched; those tables simply have zero live application code
reading/writing them now, same as before this wave, since only
`app/workflow/routes.py` -- itself always-dead -- ever touched them).

This file writes NOTHING to application/template/CSS/config sources -- only
`Path.read_text()`/`.exists()`, `git show` (read-only), and real, isolated
subprocess `create_app()`/pytest-collection probes (no HTTP POST, no mail/
task code ever invoked, no shared session-scoped `app`/`client` fixture
relied upon for anything that could be polluted by import ordering).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The commit immediately BEFORE this wave's own deletion commit -- the repo
# state where every file this wave removed still existed on disk.
PRE_CLEANUP_REF = "88d148c61f11fe9cc8d323cd8cdce1d80a146dfe"

# This wave's own landing commit (parent is exactly PRE_CLEANUP_REF -- a
# single atomic commit). Fixed, historical; never affected by any later
# commit. Used, alongside PRE_CLEANUP_REF, to prove what THIS WAVE's own
# diff did and did not touch in migrations/versions/ -- see the two tests
# below for why this must be ref-vs-ref, not ref-vs-current-directory.
POST_CLEANUP_REF = "5401195cb2887a80e90c51ee6768d460c66b849b"

DELETED_APP_FILES = (
    "app/workflow/routes.py",
    "app/workflow/dashboard_upgrade_routes.py",
    "app/workflow/__init__.py",
    "app/services/workflow/dashboard_upgrade.py",
    "app/templates/workflow/dashboard.html",
    "app/templates/workflow/delays.html",
    "app/templates/workflow/executive_dashboard.html",
    "app/templates/workflow/modules.html",
    "app/templates/workflow/notifications.html",
    "app/templates/workflow/president_approvals.html",
    "app/templates/workflow/timeline.html",
    "app/workflow/templates/workflow/dashboard.html",
    "app/workflow/templates/workflow/delays.html",
    "app/workflow/templates/workflow/executive_dashboard.html",
    "app/workflow/templates/workflow/modules.html",
    "app/workflow/templates/workflow/notifications.html",
    "app/workflow/templates/workflow/president_approvals.html",
    "app/workflow/templates/workflow/timeline.html",
)

DELETED_TEST_FILES = (
    "tests/workflow/test_phase5w_workflow_schema_readiness.py",
    "tests/workflow/test_generic_sync_sql_identifier_phase5u.py",
)

# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): an unrelated later
# wave (AQ-2) removed the /performans/baskan-onaylari route registration
# that always lost that URL's dispatch conflict anyway (see
# tests/quality/test_route_conflict_runtime_contract.py's KNOWN_CONFLICTS
# update), dropping the real url_map route count from 985 to 984 and
# changing the endpoint-list hash. This wave's own change (dead workflow
# subsystem removal) remains independently unrelated; the baseline below
# is updated to the new, correct values.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): 11 new
# GET-only /settings-center/* routes (app/settings_center/routes.py) raised
# the count 984->995 and changed the endpoint-list hash accordingly --
# mechanically re-verified against a fresh app.url_map, unrelated to this
# wave's own dead-workflow-subsystem removal.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive route (POST /ai-agent/api/v2/ask) raised the count 995->996
# and changed the endpoint-list hash accordingly -- mechanically re-verified
# against a fresh app.url_map, unrelated to this wave's own dead-workflow-
# subsystem removal.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 B2-F06 private uploads): one new,
# additive route (GET /portal/attachments/<int:attachment_id>) raised the
# count 996->997 and changed the endpoint-list hash accordingly --
# mechanically re-verified against a fresh app.url_map.
EXPECTED_ROUTE_COUNT = 997
EXPECTED_ENDPOINT_LIST_SHA256 = "269dc9216997f412a6323e22a365605535f4214aab4fdb87c0dabb74e7820e4e"

# The 12 routes app/workflow/routes.py used to claim -- independently
# reproduced live in the same-process-contamination experiment during the
# read-only audit that preceded this wave.
FORMERLY_LEAKED_ENDPOINTS = frozenset(
    {
        "main.workflow_dashboard",
        "main.workflow_timeline",
        "main.workflow_delays",
        "main.workflow_run_delay_reminders",
        "main.workflow_notifications",
        "main.workflow_president_approvals",
        "main.workflow_president_decide",
        "main.workflow_executive_dashboard",
        "main.performance_workflow_shortcut",
        "main.workflow_sync_performance",
        "main.workflow_modules_dashboard",
        "main.workflow_sync_modules",
    }
)


def _git_show(ref: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"'git show {ref}:{relative_path}' failed: {result.stderr!r}"
    return result.stdout


def _run_isolated_probe(probe_script: str, timeout: int = 120) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", probe_script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, {"stdout": result.stdout, "stderr": result.stderr}
    return result.stdout.strip().splitlines()


# ---------------------------------------------------------------------------
# 1) Orphan-absence: every deleted app/ file and directory is genuinely gone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", DELETED_APP_FILES)
def test_deleted_app_file_no_longer_exists(relative_path: str) -> None:
    assert not (REPO_ROOT / relative_path).exists(), (
        f"{relative_path} is recorded as deleted but still exists on disk."
    )


def test_app_workflow_directory_no_longer_exists() -> None:
    assert not (REPO_ROOT / "app" / "workflow").exists()


@pytest.mark.parametrize("relative_path", DELETED_APP_FILES)
def test_deleted_app_file_pre_cleanup_content_is_reproducible_from_git_history(
    relative_path: str,
) -> None:
    """Companion check: PRE_CLEANUP_REF is a real, correct ref (proves the
    historical evidence used throughout this file is genuine, not a
    typo'd/broken ref that would silently make the absence checks above
    pass vacuously)."""
    text = _git_show(PRE_CLEANUP_REF, relative_path)
    assert text, f"{relative_path} unexpectedly empty at {PRE_CLEANUP_REF}."


# ---------------------------------------------------------------------------
# 2) `app.workflow.routes` / `app.workflow.dashboard_upgrade_routes` can no
#    longer be imported at all (not just "never imported at startup" --
#    literally gone).
# ---------------------------------------------------------------------------


def test_workflow_route_modules_cannot_be_imported() -> None:
    probe_script = (
        "results = {}\n"
        "for name in ('app.workflow', 'app.workflow.routes', 'app.workflow.dashboard_upgrade_routes'):\n"
        "    try:\n"
        "        __import__(name)\n"
        "        results[name] = 'IMPORTED'\n"
        "    except ModuleNotFoundError:\n"
        "        results[name] = 'ModuleNotFoundError'\n"
        "for name, outcome in results.items():\n"
        "    print('%s=%s' % (name, outcome))\n"
    )
    output_lines = _run_isolated_probe(probe_script)
    values = dict(line.split("=", 1) for line in output_lines)
    assert values == {
        "app.workflow": "ModuleNotFoundError",
        "app.workflow.routes": "ModuleNotFoundError",
        "app.workflow.dashboard_upgrade_routes": "ModuleNotFoundError",
    }, values


# ---------------------------------------------------------------------------
# 3) The historical same-process import-contamination class (985 -> 997) no
#    longer has any source anywhere in this repo -- re-derived from the
#    fixed pre-cleanup git ref (never just trusted), AND positively re-
#    proven absent by actually running this repo's full pytest COLLECTION
#    phase (which is what triggered it originally -- module-level imports
#    execute at collection time, before any test function runs, regardless
#    of file/test ordering) in the same process as a create_app() call.
# ---------------------------------------------------------------------------


def test_historical_contamination_source_is_reproducible_from_pre_cleanup_git_ref() -> None:
    """Grounds the "985 -> 997" historical claim in real git history: both
    now-deleted test files genuinely imported app.workflow.routes at module
    level, and the dead route file genuinely defined exactly 12
    `@main_bp.route(...)`-decorated views, at the fixed ref immediately
    before this wave's own deletion commit."""
    for relative_path in DELETED_TEST_FILES:
        text = _git_show(PRE_CLEANUP_REF, relative_path)
        assert "from app.workflow import routes" in text, (
            f"{relative_path} did not import app.workflow.routes at "
            f"{PRE_CLEANUP_REF} -- the historical contamination claim would be ungrounded."
        )

    routes_text = _git_show(PRE_CLEANUP_REF, "app/workflow/routes.py")
    route_decorator_count = routes_text.count("@main_bp.route(")
    assert route_decorator_count == EXPECTED_LEAKED_ROUTE_DECORATOR_COUNT, (
        f"app/workflow/routes.py had {route_decorator_count} @main_bp.route(...) "
        f"decorators at {PRE_CLEANUP_REF}; expected {EXPECTED_LEAKED_ROUTE_DECORATOR_COUNT} "
        "(the number independently reproduced as the same-process route-count leak)."
    )


EXPECTED_LEAKED_ROUTE_DECORATOR_COUNT = 12


def test_no_remaining_repo_file_imports_the_deleted_workflow_route_module() -> None:
    """Repo-wide re-verification, independent of the historical git-ref
    evidence above: no file anywhere in app/, scripts/, or tests/ still
    contains a real import of the deleted module (the two historical
    offenders are themselves gone; this guards against a THIRD file ever
    reintroducing the same class of import)."""
    real_import_needle_patterns = (
        "import app.workflow",
        "from app.workflow",
        "from app import workflow",
    )
    offending_files: list[str] = []
    for scan_root in (REPO_ROOT / "app", REPO_ROOT / "scripts", REPO_ROOT / "tests"):
        for py_file in scan_root.rglob("*.py"):
            if py_file == Path(__file__):
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if any(pattern in content for pattern in real_import_needle_patterns):
                offending_files.append(str(py_file.relative_to(REPO_ROOT)))
    assert not offending_files, (
        f"A real import of the deleted app.workflow package was found: {offending_files!r} "
        "-- this reintroduces the historical same-process route-leak class."
    )


def test_full_pytest_collection_does_not_pollute_shared_main_bp() -> None:
    """Positive re-proof, in the same spirit as the historical contamination
    experiment: runs this repo's REAL, FULL pytest collection phase (every
    test file gets imported, exactly as happens in a real `pytest` run,
    exactly what triggered the historical leak) and THEN calls create_app()
    in that same process -- if any current test file reintroduced a
    module-level import of a route-registering dead module, this would
    catch it by route-count/hash drift, not just by grepping for the one
    specific historical pattern above."""
    probe_script = (
        "import hashlib, sys\n"
        "import pytest\n"
        "collector = pytest.main(['--collect-only', '-q', 'tests/'])\n"
        "from app import create_app\n"
        "app = create_app()\n"
        "endpoint_list = sorted(rule.endpoint for rule in app.url_map.iter_rules())\n"
        "print('ROUTE_COUNT=%d' % len(endpoint_list))\n"
        "print('ENDPOINT_SHA256=%s' % hashlib.sha256(chr(10).join(endpoint_list).encode()).hexdigest())\n"
    )
    output_lines = _run_isolated_probe(probe_script, timeout=180)
    values = dict(
        line.split("=", 1) for line in output_lines if line.startswith(("ROUTE_COUNT=", "ENDPOINT_SHA256="))
    )
    assert values.get("ROUTE_COUNT") == str(EXPECTED_ROUTE_COUNT), (
        f"After a full pytest --collect-only pass, isolated create_app() url_map route "
        f"count is {values.get('ROUTE_COUNT')}; expected {EXPECTED_ROUTE_COUNT}. A route-"
        "registering module-level import leaked from test collection into main_bp."
    )
    assert values.get("ENDPOINT_SHA256") == EXPECTED_ENDPOINT_LIST_SHA256, (
        f"After a full pytest --collect-only pass, isolated create_app() endpoint-list "
        f"SHA-256 is {values.get('ENDPOINT_SHA256')}; expected {EXPECTED_ENDPOINT_LIST_SHA256}."
    )


# ---------------------------------------------------------------------------
# 4) Clean-process url_map invariance (no test-collection side effects at
#    all in this one -- a plain, freshly-started interpreter).
# ---------------------------------------------------------------------------


def test_clean_process_url_map_route_count_and_endpoint_hash_are_unchanged() -> None:
    probe_script = (
        "import hashlib\n"
        "from app import create_app\n"
        "app = create_app()\n"
        "endpoint_list = sorted(rule.endpoint for rule in app.url_map.iter_rules())\n"
        "print('ROUTE_COUNT=%d' % len(endpoint_list))\n"
        "print('ENDPOINT_SHA256=%s' % hashlib.sha256(chr(10).join(endpoint_list).encode()).hexdigest())\n"
    )
    output_lines = _run_isolated_probe(probe_script)
    values = dict(line.split("=", 1) for line in output_lines if "=" in line)
    assert values.get("ROUTE_COUNT") == str(EXPECTED_ROUTE_COUNT)
    assert values.get("ENDPOINT_SHA256") == EXPECTED_ENDPOINT_LIST_SHA256


def test_formerly_leaked_endpoints_are_absent_from_clean_url_map() -> None:
    probe_script = (
        "from app import create_app\n"
        "app = create_app()\n"
        "endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}\n"
        "candidates = " + repr(sorted(FORMERLY_LEAKED_ENDPOINTS)) + "\n"
        "for name in candidates:\n"
        "    print('%s=%s' % (name, name in endpoints))\n"
    )
    output_lines = _run_isolated_probe(probe_script)
    values = dict(line.split("=", 1) for line in output_lines)
    for endpoint in FORMERLY_LEAKED_ENDPOINTS:
        assert values.get(endpoint) == "False", f"{endpoint}: {values.get(endpoint)}"


@pytest.mark.parametrize(
    "path_and_method",
    [
        ("/workflow/dashboard", "GET"),
        ("/workflow/1/timeline", "GET"),
        ("/workflow/delays", "GET"),
        ("/workflow/reminders/run", "POST"),
        ("/workflow/notifications", "GET"),
        ("/workflow/president-approvals", "GET"),
        ("/workflow/president-approvals/1/decide", "POST"),
        ("/workflow/executive-dashboard", "GET"),
        ("/performance/workflow", "GET"),
        ("/workflow/sync/performance", "POST"),
        ("/workflow/modules", "GET"),
        ("/workflow/sync/modules", "POST"),
    ],
)
def test_all_formerly_leaked_urls_still_404_in_clean_url_map(path_and_method: tuple[str, str]) -> None:
    path, method = path_and_method
    probe_script = (
        "from app import create_app\n"
        "app = create_app()\n"
        "adapter = app.url_map.bind('localhost')\n"
        "try:\n"
        f"    adapter.match({path!r}, method={method!r})\n"
        "    print('MATCH')\n"
        "except Exception as exc:\n"
        "    print(type(exc).__name__)\n"
    )
    output_lines = _run_isolated_probe(probe_script)
    assert output_lines[-1] == "NotFound", f"{method} {path}: {output_lines}"


# ---------------------------------------------------------------------------
# 5) Preserved active layers: the completely unrelated evaluation-workflow
#    state machine, and the shared president-approvals data/service chain.
# ---------------------------------------------------------------------------


def test_active_evaluation_workflow_service_package_still_imports_cleanly() -> None:
    probe_script = (
        "from app.services.workflow import constants, state, visibility, transitions\n"
        "from app.services import evaluation_workflow_service\n"
        "from app.services.query_health import workflow_meta\n"
        "from app.services.performance import evaluation_form_service\n"
        "print('WorkflowState=%s' % state.WorkflowState.__name__)\n"
        "print('WORKFLOW_DRAFT=%s' % state.WORKFLOW_DRAFT)\n"
        "print('has_get_workflow_state=%s' % hasattr(evaluation_workflow_service, 'get_workflow_state'))\n"
    )
    output_lines = _run_isolated_probe(probe_script)
    assert "WorkflowState=WorkflowState" in output_lines, output_lines
    assert any(line.startswith("WORKFLOW_DRAFT=") and len(line) > len("WORKFLOW_DRAFT=") for line in output_lines)
    assert "has_get_workflow_state=True" in output_lines, output_lines


def test_active_workflow_service_files_still_exist_untouched() -> None:
    for relative_path in (
        "app/services/workflow/constants.py",
        "app/services/workflow/state.py",
        "app/services/workflow/visibility.py",
        "app/services/workflow/transitions.py",
        "app/services/workflow/__init__.py",
        "app/services/evaluation_workflow_service.py",
        "app/services/query_health/workflow_meta.py",
        "app/services/performance/evaluation_form_service.py",
    ):
        assert (REPO_ROOT / relative_path).exists(), f"{relative_path} is missing."


PERFORMANCE_PRESIDENT_APPROVALS_ACTIVE_CONSUMERS = (
    "app/templates/performance/process_engine_president_approvals.html",
    "app/templates/base.html",
    "app/services/performance/process_engine_phase6_president_approvals.py",
    "app/services/performance/process_engine_phase5_notifications.py",
    "app/services/performance/process_engine_phase8_tracking.py",
    "app/api/mobile/performance_routes.py",
    "app/services/performance/president_card_review_service.py",
    "app/services/performance/process_engine_phase7_president_rule.py",
    "app/menu_registry.py",
    "app/performance/president_low_score_card_routes.py",
    "app/performance/process_engine_phase6_president_approvals_routes.py",
    "app/models/performance_process_engine_models.py",
    "app/services/performance/president_menu_card_access.py",
    "app/services/performance/process_engine_phase9_publish_lock.py",
    "app/templates/performance/president_card_review.html",
)


@pytest.mark.parametrize("relative_path", PERFORMANCE_PRESIDENT_APPROVALS_ACTIVE_CONSUMERS)
def test_performance_president_approvals_active_consumer_still_references_it(
    relative_path: str,
) -> None:
    """A sample of the 30 files that referenced `performance_president_
    approvals` before this wave (only ONE of the 30 was the now-deleted
    app/workflow/routes.py itself -- the other 29, sampled here, are all
    genuinely active and were never in scope for this cleanup)."""
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert "performance_president_approvals" in text, (
        f"{relative_path} no longer references performance_president_approvals -- "
        "this file was not supposed to be touched by this wave."
    )


# ---------------------------------------------------------------------------
# 6) Migration files preserved -- schema ownership of workflow_instances/
#    steps/logs/notifications/performance_president_approvals is untouched.
#
# TD-032 fix (2026-08-16): the two tests below used to compare a fixed
# historical git ref (PRE_CLEANUP_REF) against the *current* directory
# listing / working tree -- a hardcoded EXPECTED_MIGRATIONS_VERSIONS_COUNT
# = 72 that the CURRENT directory had to match forever, and a file-SET
# comparison against the CURRENT directory listing. Both forms conflate
# "did this 2026-08-06 workflow-cleanup wave touch migrations/versions/?"
# (a fixed historical fact) with "is the migrations directory identical to
# some frozen count/set *right now*, regardless of any later, unrelated
# wave?" (which drifts every time any legitimate migration is added --
# exactly what the later, real TD-032 migration-graph-repair work did).
# Fixed the same way as the companion fix in
# tests/security/test_duplicate_template_orphan_cleanup_wave1_contract.py:
# compare PRE_CLEANUP_REF against POST_CLEANUP_REF -- both fixed, historical
# commits bracketing this wave's own single atomic commit (5401195's only
# parent is PRE_CLEANUP_REF, and its own migrations/versions/ diff against
# PRE_CLEANUP_REF is empty) -- so both assertions are permanent,
# working-tree-independent facts about what that one commit did, and stay
# true no matter how many legitimate migrations are added later.
# ---------------------------------------------------------------------------

WORKFLOW_SCHEMA_MIGRATIONS = (
    "migrations/versions/6f2b8c4d1a90_adopt_workflow_president_approval_schema.py",
    "migrations/versions/5a7c9e1f2b30_adopt_workflow_core_runtime_schema.py",
)


@pytest.mark.parametrize("relative_path", WORKFLOW_SCHEMA_MIGRATIONS)
def test_workflow_schema_migration_file_still_exists_untouched(relative_path: str) -> None:
    assert (REPO_ROOT / relative_path).exists(), f"{relative_path} is missing."


def _migrations_versions_file_set_at_ref(ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "migrations/versions"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return {line for line in result.stdout.splitlines() if line.endswith(".py")}


def test_migrations_versions_directory_file_count_is_unchanged() -> None:
    """This wave's own landing commit (POST_CLEANUP_REF) added/removed zero
    migration files relative to its own parent (PRE_CLEANUP_REF) -- a fixed
    historical fact, independent of the current (and any future) directory
    state."""
    pre_count = len(_migrations_versions_file_set_at_ref(PRE_CLEANUP_REF))
    post_count = len(_migrations_versions_file_set_at_ref(POST_CLEANUP_REF))
    assert post_count == pre_count, (
        f"migrations/versions/ had {pre_count} .py files at {PRE_CLEANUP_REF} and "
        f"{post_count} at this wave's own landing commit {POST_CLEANUP_REF}. This wave "
        "must not have added, removed, or modified any migration."
    )


def test_no_migration_file_was_modified_by_this_wave() -> None:
    """Independent of git status (which only reflects the CURRENT working
    tree at test-run time, and could theoretically be run against a dirty
    tree) -- re-derives the migration file SET at both PRE_CLEANUP_REF and
    this wave's own landing commit (POST_CLEANUP_REF) and confirms they are
    byte-identical, plus confirms the wave's own commit has an empty
    `git diff --stat` for migrations/versions/ against its parent (catching
    same-name content modifications, not just adds/removes)."""
    pre_cleanup_files = _migrations_versions_file_set_at_ref(PRE_CLEANUP_REF)
    post_cleanup_files = _migrations_versions_file_set_at_ref(POST_CLEANUP_REF)
    assert post_cleanup_files == pre_cleanup_files, {
        "missing": sorted(pre_cleanup_files - post_cleanup_files),
        "added": sorted(post_cleanup_files - pre_cleanup_files),
    }

    diff_result = subprocess.run(
        ["git", "diff", "--stat", PRE_CLEANUP_REF, POST_CLEANUP_REF, "--", "migrations/versions"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert diff_result.returncode == 0, diff_result.stderr
    assert diff_result.stdout.strip() == "", (
        f"migrations/versions/ has changes between {PRE_CLEANUP_REF} and this wave's own "
        f"landing commit {POST_CLEANUP_REF}; this wave must not have modified any migration "
        f"file's content:\n{diff_result.stdout}"
    )


# ---------------------------------------------------------------------------
# 7) No dangling template consumer of any deleted template remains anywhere.
# ---------------------------------------------------------------------------

DELETED_TEMPLATE_BASENAMES = (
    "workflow/dashboard.html",
    "workflow/delays.html",
    "workflow/executive_dashboard.html",
    "workflow/modules.html",
    "workflow/notifications.html",
    "workflow/president_approvals.html",
    "workflow/timeline.html",
)


def test_no_template_or_python_file_references_a_deleted_workflow_template_name() -> None:
    offending: list[str] = []
    for scan_root in (REPO_ROOT / "app",):
        for py_or_html in list(scan_root.rglob("*.py")) + list(scan_root.rglob("*.html")):
            content = py_or_html.read_text(encoding="utf-8", errors="ignore")
            for basename in DELETED_TEMPLATE_BASENAMES:
                if basename in content:
                    offending.append(f"{py_or_html.relative_to(REPO_ROOT)}::{basename}")
    assert not offending, (
        f"A reference to a deleted workflow template was found: {offending!r} -- this "
        "invalidates the orphan classification."
    )


# ---------------------------------------------------------------------------
# 8) route_registry.py no longer reports the dead module (see also the
#    companion, positive-direction check in
#    tests/quality/test_phase12b_route_ownership_contract.py::test_
#    workflow_routes_manifest_string_and_dead_test_dependencies_are_gone).
# ---------------------------------------------------------------------------


def test_route_registry_manifest_no_longer_contains_the_dead_module_string() -> None:
    text = (REPO_ROOT / "app" / "route_registry.py").read_text(encoding="utf-8")
    assert '"app.workflow.routes"' not in text


def test_get_runtime_route_manifest_no_longer_reports_the_dead_module() -> None:
    from app.route_registry import get_runtime_route_manifest

    manifest = get_runtime_route_manifest()
    modular_route_modules = manifest["modular_route_modules"]
    assert isinstance(modular_route_modules, list)
    assert "app.workflow.routes" not in modular_route_modules



# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): a later,
# unrelated wave appended one new, legitimate entry to the end of the same
# static `_BASE_MODULAR_ROUTE_MODULES` tuple -- `"app.settings_center.routes"`
# (the real import that triggers registration of the 11 new, admin-gated
# `/settings-center/*` routes; see `app/settings_center/routes.py`). This is
# an intentional, evidence-based addition, not drift, so it is named here
# explicitly and added on top of the pre-cleanup-derived expectation below
# rather than silently widening the comparison.
_POST_PRE_CLEANUP_LEGITIMATE_ADDITIONS: tuple[str, ...] = ("app.settings_center.routes",)


def test_route_registry_other_manifest_entries_are_unchanged() -> None:
    """Only the single dead-module string was removed from the STATIC
    `_BASE_MODULAR_ROUTE_MODULES` tuple -- everything else in it is
    unchanged from the fixed pre-cleanup git ref, plus exactly the
    explicitly-named, independently-documented additions made by later
    waves (`_POST_PRE_CLEANUP_LEGITIMATE_ADDITIONS`). Compares against
    `_BASE_MODULAR_ROUTE_MODULES` directly (not the computed
    `MODULAR_ROUTE_MODULES`/manifest, which conditionally appends
    "app.portal.routes" at runtime via `_build_modular_route_modules()` --
    an orthogonal, unrelated mechanism this wave never touched) to keep the
    comparison apples-to-apples. Scoped precisely to that one tuple's own
    text block (not a whole-file scan) so it can't accidentally pick up
    unrelated entries from LEGACY_SHIM_MODULES/LEGACY_ARCHIVE_MODULES
    elsewhere in the same file."""
    import re

    from app.route_registry import _BASE_MODULAR_ROUTE_MODULES

    before_text = _git_show(PRE_CLEANUP_REF, "app/route_registry.py")
    block_match = re.search(
        r"_BASE_MODULAR_ROUTE_MODULES\s*=\s*\((.*?)\n\)",
        before_text,
        re.DOTALL,
    )
    assert block_match, "Could not locate _BASE_MODULAR_ROUTE_MODULES tuple in pre-cleanup text."
    before_modules = re.findall(r'"([^"]+)"', block_match.group(1))
    assert before_modules, "Extracted zero entries from the pre-cleanup _BASE_MODULAR_ROUTE_MODULES block."

    expected_after = tuple(
        m for m in before_modules if m != "app.workflow.routes"
    ) + _POST_PRE_CLEANUP_LEGITIMATE_ADDITIONS
    assert expected_after == _BASE_MODULAR_ROUTE_MODULES, {
        "expected": expected_after,
        "actual": _BASE_MODULAR_ROUTE_MODULES,
    }


# ---------------------------------------------------------------------------
# 9) No new xfail/skip introduced by this file; this file never writes to
#    application source paths.
# ---------------------------------------------------------------------------

_XFAIL_CALL_RE_PARTS = ("pytest", ".xfail(")
_XFAIL_MARK_RE_PARTS = ("@pytest", ".mark.xfail")
_SKIP_MARK_RE_PARTS = ("@pytest", ".mark.skip")
_SKIP_CALL_RE_PARTS = ("pytest", ".skip(")


def test_this_file_introduces_no_xfail_or_skip_usage() -> None:
    own_text = Path(__file__).read_text(encoding="utf-8")
    assert "".join(_XFAIL_CALL_RE_PARTS) not in own_text
    assert "".join(_XFAIL_MARK_RE_PARTS) not in own_text
    assert "".join(_SKIP_MARK_RE_PARTS) not in own_text
    assert "".join(_SKIP_CALL_RE_PARTS) not in own_text


def test_this_file_never_writes_to_application_source_paths() -> None:
    forbidden_write_markers = (
        "write_text(",
        "shutil.copy",
        "shutil.move",
        "shutil.rmtree",
        "os.rename(",
        "os.remove(",
        "os.unlink(",
    )
    own_text = Path(__file__).read_text(encoding="utf-8")
    marker_def_start = own_text.index("forbidden_write_markers = (")
    marker_def_end = own_text.index(")\n", marker_def_start) + 1
    scan_text = own_text[:marker_def_start] + own_text[marker_def_end:]
    hits = [marker for marker in forbidden_write_markers if marker in scan_text]
    assert hits == [], f"Unexpected file-write/mutation call trace found in this file: {hits!r}"
