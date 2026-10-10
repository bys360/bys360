"""BYS360 Executive Summary Dead Route Module Cleanup -- contract test.

CONTEXT: `app/dashboard/executive_summary_routes.py` defined THREE distinct
route groups (not just the one daily-weather-mail pair already handled by
a prior, separate wave):

    1. `/dashboard/yonetici-ozeti` (GET) -> `executive_summary_dashboard()`
       -> would have rendered `dashboard/executive_summary.html`.
    2. `/dashboard/yonetici-ozeti/send-test` (POST) ->
       `executive_summary_send_mail()`.
    3. `/executive-summary/daily-weather-mail` +
       `/yonetici-ozeti/gunluk-hava-maili` (GET/POST) ->
       `executive_summary_daily_weather_mail_tasks_v1_3_1()` -> would have
       rendered the already-deleted `executive_summary/daily_weather_mail_
       tasks.html` (see "BYS360 Daily Weather/Mail Orphan Template
       Temizliği").

INDEPENDENT RE-VERIFICATION (not assumed from the prior wave's finding):
a real, isolated `create_app()` proved:
    - `app.dashboard.executive_summary_routes` is absent from `sys.modules`
      -- neither `app/dashboard/routes.py` nor `app/dashboard/__init__.py`
      import it, and a repo-wide grep for any real `import`/`from ...
      import` of this module (excluding the module's own self-referential
      logging strings) returns zero hits.
    - `/dashboard/yonetici-ozeti` [GET] resolves to a COMPLETELY DIFFERENT,
      genuinely live module: `executive_summary.yonetici_ozeti` in
      `app/executive_summary/routes.py` (registered directly in
      `app/__init__.py::create_app()` via `app.register_blueprint(
      executive_summary_bp)`, `url_prefix="/dashboard"`). This is a real
      URL COLLISION between the dead file's claimed route and a genuinely
      live one -- the live one wins because the dead module's decorators
      never execute.
    - `/dashboard/yonetici-ozeti/send-test` [POST] has NO live equivalent
      at all -- 404.
    - `/executive-summary/daily-weather-mail` and `/yonetici-ozeti/gunluk-
      hava-maili` resolve to `main.daily_weather_mail_settings` in
      `app/communication/daily_weather_mail_routes.py` (already
      established by the prior daily-weather-mail orphan cleanup).
    - The real `url_map`'s sorted-endpoint-list SHA-256 and route count are
      BYTE-IDENTICAL before and after this module's deletion (985 routes,
      hash `624e25c447915f9eaf68c8583b80e962236dcecbea962259a1a21604bb48a94a`)
      -- this dead module never contributed a single runtime endpoint.

FILE-INTERNAL DEPENDENCY ANALYSIS: every symbol defined in the dead file
(`_ADMIN_ROLE_TOKENS`, `_normalize`, `_safe_actor_id`,
`_is_system_admin_user`, `system_admin_required`, `_v3_enrich_context`, and
the three view functions) was independently grepped repo-wide; the only
external hits were coincidental same-name-but-unrelated symbols in other
files (an independently-defined `_ADMIN_ROLE_TOKENS` constant in
`app/services/bys360_notification_bridge.py`; the string
`executive_summary_dashboard` appearing only as a menu-key ALLOWLIST ENTRY
in `app/menu_registry.py`, never as a `url_for()`/import reference) -- not
real dependencies. The service module it imported from,
`app/services/executive_summary_service.py`
(`build_executive_summary_context`, `send_executive_summary_mail`), has
NO other consumer either (confirmed absent from `sys.modules` too) --
it was left UNTOUCHED regardless, since deleting a service file was not
part of this task's declared scope (a candidate for a future, separate
cleanup, not acted on here). `app/templates/dashboard/executive_summary.
html` (the dead dashboard route's own template) was likewise left
UNTOUCHED for the same reason.

DELETED: `app/dashboard/executive_summary_routes.py` (150 lines, 3 route
groups, all confirmed unreachable).

PRESERVED (all explicitly out of scope, AT THE TIME): `app/services/
executive_summary_service.py`, `app/templates/dashboard/executive_summary.
html`, the real `app/executive_summary/` package, `app/communication/
daily_weather_mail_routes.py`, `app/dashboard/routes.py`,
`app/dashboard/__init__.py`, `app/route_registry.py`, all launcher/
installer scripts, CSS/JS, CSP/nonce, meeting templates.

FOLLOW-UP (BYS360 Executive Summary Artık Servis/Template Temizliği, a
separate, later wave -- the two tests below that used to assert these two
files still EXIST have been converted to absence contracts): the residual
candidates flagged above (`app/services/executive_summary_service.py` and
`app/templates/dashboard/executive_summary.html`) were independently
re-verified in that follow-up wave -- still zero application/CLI/test
consumers of either, real isolated `create_app()` still 985 routes /
byte-identical endpoint SHA, `/dashboard/yonetici-ozeti` still resolves to
the same live `executive_summary.yonetici_ozeti` view rendering
`executive_summary/yonetici_ozeti.html` (a completely different template
from the deleted `dashboard/executive_summary.html`) -- and BOTH files were
then deleted. `RESIDUAL_CLEANUP_PRE_DELETION_REF` below is the commit
immediately before that follow-up wave's own deletion (this file's own
commit, `c5a6a61b47caf2d39ca812b74f7fd22f329629c4`, HEAD at the time).

This file writes NOTHING to app/template/CSS/config sources -- only
`Path.read_text()`, `git show` (read-only), and real Flask
`app`-fixture-based `url_map`/route-resolution checks (no HTTP POST, no
mail/task code ever invoked).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

DEAD_ROUTE_FILE = "app/dashboard/executive_summary_routes.py"

# The commit immediately BEFORE this cleanup's own deletion commit -- the
# repo state where the dead route file still existed on disk.
PRE_DELETION_REF = "31394332285c54f05d41cbcebd70954d91676e7a"

# The commit immediately BEFORE the LATER "BYS360 Executive Summary Artık
# Servis/Template Temizliği" follow-up wave's own deletion commit -- the
# repo state where the two residual files below still existed on disk (see
# module docstring FOLLOW-UP section).
RESIDUAL_CLEANUP_PRE_DELETION_REF = "c5a6a61b47caf2d39ca812b74f7fd22f329629c4"

RESIDUAL_SERVICE_FILE = "app/services/executive_summary_service.py"
RESIDUAL_TEMPLATE_FILE = "app/templates/dashboard/executive_summary.html"

# Independently re-verified (see module docstring) via a real, isolated
# create_app() both immediately before and immediately after deletion --
# byte-identical in both cases, proving the dead module never contributed
# a single runtime endpoint.
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): an unrelated later
# wave (AQ-2) removed the /performans/baskan-onaylari route registration
# that always lost that URL's dispatch conflict anyway (see
# tests/quality/test_route_conflict_runtime_contract.py's KNOWN_CONFLICTS
# update), dropping the real url_map route count from 985 to 984 and
# changing the endpoint-list hash. This wave's own change (dead module
# deletion) remains unrelated to routes; the baseline below is updated to
# the new, correct values.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): 11 new
# GET-only /settings-center/* routes (app/settings_center/routes.py) raised
# the count 984->995 and changed the endpoint-list hash accordingly --
# mechanically re-verified against a fresh app.url_map, unrelated to this
# wave's own dead-module-deletion change.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive route (POST /ai-agent/api/v2/ask) raised the count 995->996
# and changed the endpoint-list hash accordingly -- mechanically re-verified
# against a fresh app.url_map, unrelated to this wave's own dead-module-
# deletion change.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 B2-F06 private uploads): one new,
# additive route (GET /portal/attachments/<int:attachment_id>) raised the
# count 996->997 and changed the endpoint-list hash accordingly --
# mechanically re-verified against a fresh app.url_map, unrelated to this wave.
EXPECTED_ROUTE_COUNT = 997
EXPECTED_ENDPOINT_LIST_SHA256 = "269dc9216997f412a6323e22a365605535f4214aab4fdb87c0dabb74e7820e4e"

STARTUP_FILES_THAT_MUST_NOT_REFERENCE_THE_DEAD_MODULE = (
    "app/dashboard/routes.py",
    "app/dashboard/__init__.py",
    "app/route_registry.py",
    "app/routes.py",
)

ROUTE_MANIFEST_FILES = (
    "app/admin/route_manifest.py",
    "app/communication/route_manifest.py",
    "app/institutional/route_manifest.py",
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


# ---------------------------------------------------------------------------
# 1) Orphan-absence: the dead route module file itself is gone.
# ---------------------------------------------------------------------------


def test_dead_route_module_file_no_longer_exists() -> None:
    assert not (REPO_ROOT / DEAD_ROUTE_FILE).exists(), (
        f"{DEAD_ROUTE_FILE} is recorded as deleted but still exists on disk."
    )


def test_dead_route_module_pre_deletion_content_is_reproducible_from_git_history() -> None:
    """Companion check: the file's PRE_DELETION_REF content is still
    retrievable (proves PRE_DELETION_REF is a real, correct ref and the
    historical evidence used elsewhere in this test suite is genuine, not
    a typo'd/broken ref that would silently make other git-show-based
    tests pass vacuously)."""
    text = _git_show(PRE_DELETION_REF, DEAD_ROUTE_FILE)
    assert "def executive_summary_dashboard():" in text
    assert "def executive_summary_send_mail():" in text
    assert "def executive_summary_daily_weather_mail_tasks_v1_3_1():" in text
    assert "@bp.route('/dashboard/yonetici-ozeti', methods=['GET'])" in text
    assert "@bp.route('/dashboard/yonetici-ozeti/send-test', methods=['POST'])" in text


# ---------------------------------------------------------------------------
# 2) Startup / manifest / blueprint-registration chain never referenced the
#    dead module -- independently re-verified, not assumed from the prior
#    wave's finding.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", STARTUP_FILES_THAT_MUST_NOT_REFERENCE_THE_DEAD_MODULE)
def test_startup_files_never_reference_the_dead_module(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert "executive_summary_routes" not in text, (
        f"{relative_path} references 'executive_summary_routes' -- the dead module may "
        "actually be live, in which case it should not have been deleted."
    )


@pytest.mark.parametrize("relative_path", ROUTE_MANIFEST_FILES)
def test_route_manifest_files_never_reference_the_dead_module(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert "executive_summary_routes" not in text, (
        f"{relative_path} references 'executive_summary_routes'."
    )


def test_no_python_file_anywhere_actually_imports_the_dead_module() -> None:
    """Repo-wide AST-free but precise textual scan for a REAL import
    statement (not a docstring/comment mention, which is intentionally
    common throughout this test suite's own historical-evidence comments)."""
    real_import_needle_patterns = (
        "import executive_summary_routes",
        "from .executive_summary_routes",
        "from app.dashboard.executive_summary_routes",
        "from app.dashboard import executive_summary_routes",
    )
    offending_files: list[str] = []
    for py_file in (REPO_ROOT / "app").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        if any(pattern in content for pattern in real_import_needle_patterns):
            offending_files.append(str(py_file.relative_to(REPO_ROOT)))
    assert not offending_files, (
        f"A real import of the dead module was found: {offending_files!r} -- this "
        "invalidates the orphan classification."
    )


# ---------------------------------------------------------------------------
# 3) Real Flask app: url_map route-count/hash invariance + active route
#    resolution proof.
#
#    BYS360 KOORDINATOR NOTU: bu bolum KASITLI olarak paylasilan (session-
#    scoped) `app` fixture'ini KULLANMAZ. `tests/workflow/test_phase5w_
#    workflow_schema_readiness.py` (ve benzer izole-birim-testi dosyalari)
#    olu kod modullerini (ornegin app.workflow.routes) dogrudan import
#    ediyor; tam test paketi icinde bu import, paylasilan `main_bp`
#    Blueprint nesnesine kalici olarak yaziliyor -- bu urunun kendisinde bir
#    hata DEGIL, test suite'inin ayni process'i paylasmasindan kaynaklanan
#    bir gozlem artefakti (bkz. tests/quality/test_president_approvals_
#    route_contract.py'nin ayni deseni KENDI docstring'inde tarif ettigi ve
#    izole bir alt-surecle cozdugu emsal). Bu yuzden asagidaki iki test,
#    o dosyanin KENDI kurulu deseniyle (3 ajanin da izledigi), TAMAMEN IZOLE
#    bir alt-process'te `create_app()` calistirir -- paylasilan `app`
#    fixture'ina guvenmez.
# ---------------------------------------------------------------------------


def _run_isolated_create_app_probe(probe_script: str) -> list[str]:
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, "-c", probe_script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, {"stdout": result.stdout, "stderr": result.stderr}
    return result.stdout.strip().splitlines()


def test_url_map_route_count_and_endpoint_hash_match_pre_and_post_deletion_baseline() -> None:
    """The EXPECTED_* constants above were independently derived from a
    real, isolated `create_app()` run both immediately BEFORE and
    immediately AFTER this module's deletion -- byte-identical in both
    cases. This test locks that invariance in permanently: if the live
    `url_map` ever drifts from this fixed baseline, something ELSE (not
    this cleanup) changed the route surface. Runs in an isolated
    subprocess (see module-level KOORDINATOR NOTU above) so a sibling test
    file's direct import of an unrelated dead route module cannot pollute
    the count."""
    probe_script = (
        "import hashlib\n"
        "from app import create_app\n"
        "app = create_app()\n"
        "endpoint_list = sorted(rule.endpoint for rule in app.url_map.iter_rules())\n"
        "print('ROUTE_COUNT=%d' % len(endpoint_list))\n"
        "print('ENDPOINT_SHA256=%s' % hashlib.sha256(chr(10).join(endpoint_list).encode()).hexdigest())\n"
    )
    output_lines = _run_isolated_create_app_probe(probe_script)
    values = dict(line.split("=", 1) for line in output_lines if "=" in line)
    assert values.get("ROUTE_COUNT") == str(EXPECTED_ROUTE_COUNT), (
        f"Isolated create_app() url_map route count is {values.get('ROUTE_COUNT')}; "
        f"expected {EXPECTED_ROUTE_COUNT}."
    )
    assert values.get("ENDPOINT_SHA256") == EXPECTED_ENDPOINT_LIST_SHA256, (
        f"Isolated create_app() url_map sorted-endpoint-list SHA-256 is "
        f"{values.get('ENDPOINT_SHA256')}; expected {EXPECTED_ENDPOINT_LIST_SHA256}."
    )


def test_dead_modules_claimed_urls_either_404_or_resolve_to_a_different_live_view() -> None:
    """For each of the 4 URLs the dead module claimed to serve: either the
    URL 404s (no live equivalent at all), or it resolves to a genuinely
    different, live module -- never to anything from the dead file. Also
    confirms the dead module is absent from `sys.modules`. Isolated
    subprocess, same reason as above."""
    probe_script = (
        "import sys\n"
        "from app import create_app\n"
        "app = create_app()\n"
        "print('MODULE_ABSENT=%s' % ('app.dashboard.executive_summary_routes' not in sys.modules))\n"
        "adapter = app.url_map.bind('localhost')\n"
        "cases = [\n"
        "    ('/dashboard/yonetici-ozeti', 'GET'),\n"
        "    ('/dashboard/yonetici-ozeti/send-test', 'POST'),\n"
        "    ('/executive-summary/daily-weather-mail', 'GET'),\n"
        "    ('/yonetici-ozeti/gunluk-hava-maili', 'GET'),\n"
        "]\n"
        "for path, method in cases:\n"
        "    try:\n"
        "        endpoint, _args = adapter.match(path, method=method)\n"
        "        vf = app.view_functions.get(endpoint)\n"
        "        mod = getattr(vf, '__module__', None)\n"
        "        print('%s|%s|MATCH|%s|%s' % (path, method, endpoint, mod))\n"
        "    except Exception as exc:\n"
        "        print('%s|%s|%s' % (path, method, type(exc).__name__))\n"
    )
    output_lines = _run_isolated_create_app_probe(probe_script)
    results = {}
    for line in output_lines:
        if line.startswith("MODULE_ABSENT="):
            continue
        parts = line.split("|")
        results[(parts[0], parts[1])] = parts[2:]

    assert "MODULE_ABSENT=True" in output_lines, (
        f"app.dashboard.executive_summary_routes is present in sys.modules: {output_lines!r}"
    )

    expected = {
        ("/dashboard/yonetici-ozeti", "GET"): ["MATCH", "executive_summary.yonetici_ozeti", "app.executive_summary.routes"],
        ("/dashboard/yonetici-ozeti/send-test", "POST"): ["NotFound"],
        ("/executive-summary/daily-weather-mail", "GET"): ["MATCH", "main.daily_weather_mail_settings", "app.communication.daily_weather_mail_routes"],
        ("/yonetici-ozeti/gunluk-hava-maili", "GET"): ["MATCH", "main.daily_weather_mail_settings", "app.communication.daily_weather_mail_routes"],
    }
    for key, expected_value in expected.items():
        assert results.get(key) == expected_value, (
            f"{key}: got {results.get(key)!r}, expected {expected_value!r}. Full output: {output_lines!r}"
        )


# ---------------------------------------------------------------------------
# 4) Residual files (service module + dashboard template): a LATER, separate
#    wave ("BYS360 Executive Summary Artık Servis/Template Temizliği")
#    independently re-verified both as still ORPHAN_CONFIRMED and deleted
#    them. These two tests used to assert the opposite (still exist,
#    untouched) -- converted to absence contracts, per that follow-up wave's
#    own evidence (see module docstring FOLLOW-UP section).
# ---------------------------------------------------------------------------


def test_executive_summary_service_module_no_longer_exists() -> None:
    """`app/services/executive_summary_service.py` had zero consumers even
    at the time of THIS file's own original wave (see module docstring);
    the later residual-cleanup follow-up wave independently re-confirmed
    that and deleted it."""
    service_path = REPO_ROOT / RESIDUAL_SERVICE_FILE
    assert not service_path.exists(), (
        f"{RESIDUAL_SERVICE_FILE} is recorded as deleted by the residual-cleanup "
        "follow-up wave but still exists on disk."
    )


def test_executive_summary_service_module_pre_deletion_content_is_reproducible_from_git_history() -> None:
    """Companion check: RESIDUAL_CLEANUP_PRE_DELETION_REF is a real, correct
    ref (not a typo'd/broken one that would silently make the absence check
    above pass vacuously)."""
    text = _git_show(RESIDUAL_CLEANUP_PRE_DELETION_REF, RESIDUAL_SERVICE_FILE)
    assert "def build_executive_summary_context(" in text
    assert "def send_executive_summary_mail(" in text


def test_dashboard_executive_summary_template_no_longer_exists() -> None:
    """`app/templates/dashboard/executive_summary.html` (the dead dashboard
    route's own template) -- likewise independently re-confirmed
    ORPHAN_CONFIRMED and deleted by the residual-cleanup follow-up wave."""
    template_path = REPO_ROOT / RESIDUAL_TEMPLATE_FILE
    assert not template_path.exists(), (
        f"{RESIDUAL_TEMPLATE_FILE} is recorded as deleted by the residual-cleanup "
        "follow-up wave but still exists on disk."
    )


def test_dashboard_executive_summary_template_pre_deletion_content_is_reproducible_from_git_history() -> None:
    """Companion check for the template's own absence contract, same
    reasoning as the service module's above."""
    text = _git_show(RESIDUAL_CLEANUP_PRE_DELETION_REF, RESIDUAL_TEMPLATE_FILE)
    assert '{% extends "base.html" %}' in text
    assert "execv3" in text


def test_no_python_file_anywhere_actually_imports_the_deleted_service_module() -> None:
    """Repo-wide re-verification (independent of the follow-up wave's own
    analysis) that no application or CLI code imports the deleted service
    module by its real module path. Scoped to `app/` and `scripts/` (real
    code, never a test file's own documentation/needle strings) -- the
    same scoping trick `test_no_python_file_anywhere_actually_imports_the_
    dead_module` above already relies on to avoid self-matching its own
    needle-pattern string literals; this test's needle patterns are
    themselves such literals, so scanning `tests/` (which would include
    this very file) would false-positive."""
    real_import_needle_patterns = (
        "import executive_summary_service",
        "from .executive_summary_service",
        "from app.services.executive_summary_service",
        "from app.services import executive_summary_service",
    )
    offending_files: list[str] = []
    for scan_root in (REPO_ROOT / "app", REPO_ROOT / "scripts"):
        for py_file in scan_root.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if any(pattern in content for pattern in real_import_needle_patterns):
                offending_files.append(str(py_file.relative_to(REPO_ROOT)))
    assert not offending_files, (
        f"A real import of the deleted service module was found: {offending_files!r} "
        "-- this invalidates the orphan classification."
    )


def test_no_template_anywhere_references_the_deleted_dashboard_template() -> None:
    """Repo-wide re-verification that no Jinja `render_template`, `include`,
    or `extends` anywhere still targets the deleted
    `dashboard/executive_summary.html` path."""
    offending_files: list[str] = []
    for template_file in (REPO_ROOT / "app/templates").rglob("*.html"):
        content = template_file.read_text(encoding="utf-8", errors="ignore")
        if "dashboard/executive_summary.html" in content:
            offending_files.append(str(template_file.relative_to(REPO_ROOT)))
    for py_file in (REPO_ROOT / "app").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        if "dashboard/executive_summary.html" in content or "dashboard\\executive_summary.html" in content:
            offending_files.append(str(py_file.relative_to(REPO_ROOT)))
    assert not offending_files, (
        f"A reference to the deleted template was found: {offending_files!r} -- this "
        "invalidates the orphan classification."
    )


def test_active_executive_summary_route_still_renders_its_own_unrelated_template() -> None:
    """Re-proves (independent of the residual-cleanup wave's own claim) that
    the real, live `/dashboard/yonetici-ozeti` route -- registered from the
    unrelated `app/executive_summary/` package -- renders
    `executive_summary/yonetici_ozeti.html`, a completely different template
    from the one just deleted, and that deleting the orphan template did not
    change that. Isolated subprocess, same reason as the url_map checks
    below."""
    probe_script = (
        "from app import create_app\n"
        "app = create_app()\n"
        "with app.test_request_context():\n"
        "    from app.executive_summary.routes import yonetici_ozeti\n"
        "    import inspect\n"
        "    src = inspect.getsource(yonetici_ozeti)\n"
        "    print('RENDERS_YONETICI_OZETI_TEMPLATE=%s' % ('executive_summary/yonetici_ozeti.html' in src))\n"
        "    print('RENDERS_DELETED_TEMPLATE=%s' % ('dashboard/executive_summary.html' in src))\n"
    )
    output_lines = _run_isolated_create_app_probe(probe_script)
    assert "RENDERS_YONETICI_OZETI_TEMPLATE=True" in output_lines, output_lines
    assert "RENDERS_DELETED_TEMPLATE=False" in output_lines, output_lines


def test_active_executive_summary_package_still_imports_cleanly() -> None:
    """Re-proves the real, live `app.executive_summary` package (routes,
    service, mail_engine -- the genuinely active code this cleanup must
    never touch) still imports without error after both deletions."""
    probe_script = (
        "from app.executive_summary import executive_summary_bp\n"
        "from app.executive_summary.service import build_executive_summary_payload\n"
        "from app.executive_summary.mail_engine import send_executive_summary_email\n"
        "print('ACTIVE_PACKAGE_IMPORTS_OK=True')\n"
    )
    output_lines = _run_isolated_create_app_probe(probe_script)
    assert "ACTIVE_PACKAGE_IMPORTS_OK=True" in output_lines, output_lines


def test_daily_weather_mail_service_and_cli_scripts_still_exist_untouched() -> None:
    """Regression guard carried over from the prior orphan-cleanup waves:
    the real daily-weather-mail route/service files and CLI scripts remain
    untouched by this Python-route-module cleanup too."""
    for relative_path in (
        "app/communication/daily_weather_mail_routes.py",
        "app/services/executive_mail_center.py",
        "scripts/communication/send_daily_evening_tomorrow_mail.py",
        "scripts/communication/send_daily_pulse_check_mail.py",
    ):
        assert (REPO_ROOT / relative_path).exists(), f"{relative_path} is missing."


# ---------------------------------------------------------------------------
# 5) Style/CSP/handler inventory unchanged (a .py-only deletion cannot
#    affect the HTML-scoped canonical inventory -- defense-in-depth check).
# ---------------------------------------------------------------------------

# BYS360 Executive Summary Artık Servis/Template Temizliği (the later
# residual-cleanup follow-up wave, see module docstring) deleted 1 more
# confirmed-orphan template (app/templates/dashboard/executive_summary.html),
# removing 3 static style="..." attributes and 1 <style> block:
# 1040 - 3 = 1037, 248 - 1 = 247. See tests/security/test_csp_style_
# migration_cumulative_inventory_contract.py's
# DELETED_TEMPLATE_WAVES["executive_summary_dashboard_cleanup"] for the
# independently re-derived evidence. The residual service `.py` file
# carried no template markup, so it contributes 0 to this ledger. A further
# later wave (BYS360 Workflow Orphan Presentation Subsystem Temizliği)
# deleted 14 more confirmed-orphan templates (2 full trees of 7), removing 2
# more static style="..." attributes, 2 dynamic style="..." attributes, and
# 14 more <style> blocks: 1037 - 2 = 1035, 66 - 2 = 64, 247 - 14 = 233. See
# that same ledger file's
# DELETED_TEMPLATE_WAVES["workflow_orphan_presentation_cleanup"]. Neither
# of this wave's own deleted files (app/workflow/routes.py,
# app/workflow/dashboard_upgrade_routes.py) carried template markup either.
# A further later wave (style3c_meeting_family_group_a) extracted 8 more
# <style> blocks from 8 active templates (no static/dynamic attributes
# touched): 233 - 8 = 225. See that same ledger file's
# STYLE_MIGRATION_WAVES["style3c_meeting_family_group_a"]. A further,
# unrelated later wave (weights_orphan_template_cleanup) deleted the orphan
# app/templates/weights.html, which independently carried its own one static
# style="..." attribute and one <style> block: 1035 - 1 = 1034, 225 - 1 = 224.
# See that same ledger file's FORWARD-COMPATIBILITY FOLLOW-UP 7. A further,
# unrelated later wave (weight_create_edit_orphan_cleanup) deleted the two
# sibling orphans app/templates/weight_create.html and
# app/templates/weight_edit.html, each independently carrying one static
# style="..." attribute and one <style> block: 1034 - 2 = 1032,
# 224 - 2 = 222. See that same ledger file's FORWARD-COMPATIBILITY
# FOLLOW-UP 8. A further, unrelated later wave (BYS360 Settings Center V2)
# added 4 new templates, but their CSS is an external stylesheet with no
# inline style="..." attributes or <style> blocks, contributing 0 -- totals
# remain 1032/222. See that same ledger file's FORWARD-COMPATIBILITY
# FOLLOW-UP 9.
EXPECTED_ACTIVE_STYLE_TOTAL = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL = 64
EXPECTED_STYLE_BLOCK_TOTAL = 221


def test_canonical_style_and_handler_inventory_is_unchanged() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL, (
        f"active_static_total is {inventory.active_static_total}; expected "
        f"{EXPECTED_ACTIVE_STYLE_TOTAL} (a .py-only deletion must not change this)."
    )
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL, (
        f"dynamic_total is {inventory.dynamic_total}; expected {EXPECTED_DYNAMIC_STYLE_TOTAL}."
    )
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL, (
        f"style_block_total is {inventory.style_block_total}; expected {EXPECTED_STYLE_BLOCK_TOTAL}."
    )
    assert inventory.inline_handler_total == 0, f"inline_handler_total is {inventory.inline_handler_total}; expected 0."
    assert inventory.javascript_url_total == 0, f"javascript_url_total is {inventory.javascript_url_total}; expected 0."


def test_csp_style_directives_unchanged(client) -> None:
    response = client.get("/login")
    policy = response.headers.get("Content-Security-Policy") or response.headers.get(
        "Content-Security-Policy-Report-Only"
    )
    assert policy, "No CSP header found in the response."
    directives: dict[str, str] = {}
    for chunk in policy.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(None, 1)
        directives[parts[0]] = parts[1] if len(parts) > 1 else ""
    expected = {
        "style-src": "'self' 'unsafe-inline' https:",
        "style-src-elem": "'self' 'unsafe-inline' https:",
        "style-src-attr": "'unsafe-inline'",
    }
    for directive, expected_value in expected.items():
        assert directives.get(directive) == expected_value, (
            f"'{directive}' is {directives.get(directive)!r}; expected {expected_value!r}."
        )
        assert "'nonce-" not in directives.get(directive, ""), (
            f"'{directive}' unexpectedly contains a 'nonce-' token."
        )


# ---------------------------------------------------------------------------
# 6) Route snapshot (static AST scan, independent of runtime reachability)
#    no longer contains this module's decorator-declared routes.
# ---------------------------------------------------------------------------


def test_phase2b_route_snapshot_no_longer_contains_dead_module_keys() -> None:
    import json

    snapshot_path = REPO_ROOT / "tests/architecture/snapshots/phase2b_route_snapshot_baseline.json"
    baseline = json.loads(snapshot_path.read_text(encoding="utf-8"))
    contract_keys = set(baseline["contract_keys"])
    dead_module_keys = {
        "/dashboard/yonetici-ozeti|GET",
        "/dashboard/yonetici-ozeti/send-test|POST",
        "/executive-summary/daily-weather-mail|GET,POST",
        "/yonetici-ozeti/gunluk-hava-maili|GET,POST",
    }
    # "/dashboard/yonetici-ozeti|GET" is still expected ONCE, from the real
    # executive_summary_bp -- only the dead module's SECOND, now-removed
    # copy of that exact key (and the other 3 dead-module-only keys) should
    # be gone.
    from collections import Counter

    key_counts = Counter(baseline["contract_keys"])
    assert key_counts["/dashboard/yonetici-ozeti|GET"] == 1, (
        f"'/dashboard/yonetici-ozeti|GET' appears {key_counts['/dashboard/yonetici-ozeti|GET']} "
        "times in the snapshot; expected exactly 1 (the real executive_summary_bp's own copy)."
    )
    for key in dead_module_keys - {"/dashboard/yonetici-ozeti|GET"}:
        assert key not in contract_keys, f"{key!r} still present in the route snapshot; expected removed."


# ---------------------------------------------------------------------------
# 7) No new xfail/skip introduced by this file; this file never writes to
#    application source paths.
# ---------------------------------------------------------------------------

_XFAIL_CALL_RE_PARTS = ("pytest", ".xfail(")
_XFAIL_MARK_RE_PARTS = ("@pytest", ".mark.xfail")
_SKIP_MARK_RE_PARTS = ("@pytest", ".mark.skip")
_SKIP_CALL_RE_PARTS = ("pytest", ".skip(")


def test_this_file_introduces_no_xfail_or_skip_usage() -> None:
    """Deliberately builds each needle via string concatenation so this
    check's OWN source line never contains the literal pattern it searches
    for (which would otherwise make it self-match)."""
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
