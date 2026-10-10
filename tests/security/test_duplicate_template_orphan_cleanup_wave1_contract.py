"""BYS360 Duplicate Template Dalga 1 -- confirmed-orphan duplicate-group
cleanup contract.

CONTEXT: a prior, separate read-only analysis ("BYS360 Tam Dosya Duplicate
Template Konsolidasyonu -- Aktif Tuketici ve Kanoniklestirme Analizi")
independently found 12 raw-byte-identical template groups (29 files total, 17
redundant copies) repo-wide. Of those, 4 groups (9 files) were proven to have
ZERO real consumers of any kind -- no `render_template()`/`safe_render()`
call, no Jinja `{% include/extends/import/from %}`, no macro import, no
dynamic template-name construction, no blueprint-scoped template loader, no
PDF/mail/export usage, no CLI/scheduler usage, no `app/menu_registry.py`
entry, no test file reference -- anywhere in the repo. The only hits for any
of these 9 filenames were incidental mentions inside static, historical JSON
inventory snapshots (`reports/architecture/BYS360_ANDROID_RESPONSIVE_*.json`,
`reports/archive/.../BYS360_A13A_UI_DESIGN_SYSTEM_INVENTORY.json`) and one
zip archive report (`reports/quality/BYS360_SAFE_RELEASE_CI_AUDIT.zip`) --
neither a real runtime/Jinja/test dependency; both are one-time-generated
audit artifacts that recorded the file's path at generation time, not a live
reference re-evaluated against the current worktree.

SCOPE CORRECTION (portal hero group): the source analysis's own group table
already listed all 3 `portal/_press_news_home_hero_v3a*.html` files as
ORPHAN_CONFIRMED, but an inconsistent later summary table implied only 2 of
the 3 were being removed (leaving one as an artificial "canonical" survivor
despite having zero consumers itself). Independently re-verified here: all 3
have zero consumers, so all 3 are deleted -- none is kept as a fake canonical.

DELETED (this wave, 9 files total):
    - app/templates/portal/_press_news_home_hero_v3a.html
    - app/templates/portal/_press_news_home_hero_v3a.safe_v1.html
    - app/templates/portal/_press_news_home_hero_v3a.safe_v1a.html
    - app/templates/_action_suggestion_macros.html
    - app/templates/action_suggestion_macros.html
    - app/templates/_decision_support_macros.html
    - app/templates/decision_support_macros.html
    - app/templates/_performance_workspace_macros.html
    - app/templates/performance_workspace_macros.html

PRESERVED (explicitly out of scope, independently re-verified below):
    - The 8 active Style-3C meeting-family templates and their route/context-
      builder Python files -- untouched, byte-identical to pre-wave.
    - app/static/css/meeting_development_c_shared.css -- untouched.
    - The 6 SHADOW_COPY macro groups (E/G/H/J/K/L in the source analysis:
      communication_suite_macros, list_workspace_macros,
      management_workspace_macros, premium_ui_kit, premium_ui_macros,
      premium_workspace_macros) -- their underscore-prefixed ("private
      partial") member is genuinely imported/included by multiple active
      templates and is kept; only THEIR non-underscore duplicate would ever
      be a deletion candidate, and that is explicitly NOT this wave's scope
      (a separate wave, not requested here).

STYLE/CSP IMPACT: all 9 deleted files independently measured 0 static style
attributes, 0 dynamic style attributes, 0 <style> blocks, 0 inline event
handlers, 0 javascript: URLs each (verified via the same canonical
`tests.security._bys360_style_inventory` helper used by every other wave in
this repo). This wave's `removed_static`/`removed_blocks`/`removed_dynamic`
are therefore all 0 -- the repo-wide totals were UNCHANGED by this wave
(1035/64/225 at the time this wave landed; see
`test_csp_style_migration_cumulative_inventory_contract.py`'s
`DELETED_TEMPLATE_WAVES["duplicate_template_orphan_cleanup_wave1"]`). A
LATER wave, `weights_orphan_template_cleanup` (see that same file's FORWARD-
COMPATIBILITY FOLLOW-UP 7), reduced the repo-wide totals further to
1034/64/224, and a further later wave, `weight_create_edit_orphan_cleanup`
(FORWARD-COMPATIBILITY FOLLOW-UP 8), reduced them again to 1032/64/222. A
further later wave, BYS360 Settings Center V2 (FORWARD-COMPATIBILITY
FOLLOW-UP 9), added 4 new templates but authored their CSS as an external
stylesheet with no inline style="..." attributes, so the totals remain
1032/64/222 -- all unrelated to this wave, which remains a 0-contribution
entry.

This file writes NOTHING to app/template/CSS/config sources -- only
`Path.read_text()`/`Path.exists()`, `git show`/`git status`/`git diff`
(read-only), and real Flask test-client requests against its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Tip of phase5-critical-lint-clean-v1 immediately before this wave's own
# deletion -- the repo state where all 9 templates still existed. Fixed,
# historical; never affected by any later commit.
PRE_DELETION_REF = "d4ee2043931b37cef6df2ceef898094e0eebb04d"

# This wave's own landing commit (parent is exactly PRE_DELETION_REF -- a
# single atomic commit). Fixed, historical; never affected by any later
# commit. Used, alongside PRE_DELETION_REF, to prove what THIS WAVE's own
# diff did and did not touch -- see test_out_of_scope_path_is_untouched_by_
# this_wave's docstring below for why this must be ref-vs-ref, not
# ref-vs-working-tree.
POST_DELETION_REF = "4af482e3dff5a35e6510a01159e97ec73b661b1b"

DELETED_GROUPS: dict[str, tuple[str, ...]] = {
    "portal_hero": (
        "app/templates/portal/_press_news_home_hero_v3a.html",
        "app/templates/portal/_press_news_home_hero_v3a.safe_v1.html",
        "app/templates/portal/_press_news_home_hero_v3a.safe_v1a.html",
    ),
    "action_suggestion_macros": (
        "app/templates/_action_suggestion_macros.html",
        "app/templates/action_suggestion_macros.html",
    ),
    "decision_support_macros": (
        "app/templates/_decision_support_macros.html",
        "app/templates/decision_support_macros.html",
    ),
    "performance_workspace_macros": (
        "app/templates/_performance_workspace_macros.html",
        "app/templates/performance_workspace_macros.html",
    ),
}
ALL_DELETED_TEMPLATES: tuple[str, ...] = tuple(
    p for paths in DELETED_GROUPS.values() for p in paths
)
assert len(ALL_DELETED_TEMPLATES) == 9

# The 6 SHADOW_COPY macro groups' surviving (underscore-prefixed, genuinely
# imported) members -- must remain byte-identical and importable.
PRESERVED_SHADOW_COPY_SURVIVORS: tuple[str, ...] = (
    "app/templates/_communication_suite_macros.html",
    "app/templates/_list_workspace_macros.html",
    "app/templates/_management_workspace_macros.html",
    "app/templates/_premium_ui_kit.html",
    "app/templates/_premium_ui_macros.html",
    "app/templates/_premium_workspace_macros.html",
)

# KOORDINATOR DUZELTMESI: originally included meeting_p0_completion.html and
# meeting_development_faz4.html -- correct while this orphan-cleanup wave was
# the most recent thing to touch app/templates/performance/. Two later,
# legitimate waves ("BYS360 Meeting UI Context Adapter -- Dalga 1 / P0
# Completion" and "-- Dalga 2 / Final Gate") rewrote those templates' bodies
# (see test_meeting_p0_completion_ui_context_adapter_contract.py and
# test_meeting_final_gate_ui_context_adapter_contract.py for each wave's own
# full evidence chain) -- intentional, in-scope changes for those later
# waves, not a regression of this one. Removed here so this wave's OWN
# untouched-template assertion no longer sees those later, unrelated waves'
# legitimate edits -- same class of drift already handled for
# test_csp_style3c_meeting_family_group_a_contract.py's own scope-guard test
# and test_meeting_p0_completion_settings_query_dialect_fix_contract.py's own
# MEETING_FAMILY_TEMPLATES list.
MEETING_FAMILY_TEMPLATES: tuple[str, ...] = (
    "app/templates/performance/meeting_development_faz3.html",
    "app/templates/performance/meeting_development_scenarios.html",
    "app/templates/performance/meeting_final_closure.html",
    "app/templates/performance/meeting_p1_scope.html",
    "app/templates/performance/meeting_p2_archive_notes.html",
    "app/templates/performance/meeting_rule_enforcement.html",
)
MEETING_FAMILY_SHARED_CSS = "app/static/css/meeting_development_c_shared.css"


def _normalize_line_endings(data: bytes) -> bytes:
    """CRLF/LF-agnostic byte comparison helper. This repo checks out some
    files with CRLF locally (Windows core.autocrlf) while git itself stores
    LF blobs -- a pure line-ending difference is not a real content change,
    so every byte-identity check in this file normalizes both sides through
    this function first (discovered empirically: several PRESERVED_SHADOW_
    COPY_SURVIVORS files failed a naive byte comparison on CRLF alone)."""
    return data.replace(b"\r\n", b"\n")


def _git_show(ref: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"'git show {ref}:{relative_path}' failed: {result.stderr!r}"
    return result.stdout


# ---------------------------------------------------------------------------
# 1) The 9 confirmed-orphan templates no longer exist on disk.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", ALL_DELETED_TEMPLATES)
def test_deleted_orphan_template_is_genuinely_absent_from_worktree(relative_path: str) -> None:
    assert not (REPO_ROOT / relative_path).exists(), (
        f"{relative_path} is claimed deleted by this wave but still exists on disk."
    )


# ---------------------------------------------------------------------------
# 2) At the fixed pre-deletion ref, all 9 files genuinely existed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", ALL_DELETED_TEMPLATES)
def test_deleted_template_existed_at_pre_deletion_ref(relative_path: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{PRE_DELETION_REF}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"{relative_path} does not appear to have existed at {PRE_DELETION_REF} "
        f"(git cat-file -e failed): {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# 3) Each group's raw-byte duplicate claim is independently re-derived from
#    the fixed pre-deletion ref -- never just trusted.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group_name", sorted(DELETED_GROUPS))
def test_group_members_were_raw_byte_identical_at_pre_deletion_ref(group_name: str) -> None:
    paths = DELETED_GROUPS[group_name]
    contents = [_git_show(PRE_DELETION_REF, p) for p in paths]
    shas = [hashlib.sha256(c).hexdigest() for c in contents]
    assert len(set(shas)) == 1, (
        f"{group_name}: members were not raw-byte identical at {PRE_DELETION_REF}: "
        f"{dict(zip(paths, shas, strict=True))!r}"
    )


# ---------------------------------------------------------------------------
# 4) Zero consumer references anywhere in app/templates/, app/workflow/
#    templates/, app/modules/*/templates/, or app/**/*.py -- for every
#    deleted filename, both with and without its directory prefix.
# ---------------------------------------------------------------------------


def _consumer_scan_roots() -> list[Path]:
    roots = [REPO_ROOT / "app"]
    return roots


@pytest.mark.parametrize("relative_path", ALL_DELETED_TEMPLATES)
def test_no_consumer_reference_to_deleted_template_remains_in_app(relative_path: str) -> None:
    basename = Path(relative_path).name
    offenders: list[str] = []
    for root in _consumer_scan_roots():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in (".py", ".html", ".js"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if basename in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        f"{basename}: found {len(offenders)} unexpected reference(s) under app/ "
        f"after deletion: {offenders!r}"
    )


# ---------------------------------------------------------------------------
# 5) No active Jinja {% import/from/include %} anywhere references any of
#    the deleted macro filenames.
# ---------------------------------------------------------------------------

_JINJA_TEMPLATE_REF_RE = re.compile(
    r"""\{%\s*(?:from|include|import)\s+["']([^"']+)["']""", re.IGNORECASE
)


def test_no_active_jinja_directive_references_a_deleted_macro_filename() -> None:
    deleted_basenames = {Path(p).name for p in ALL_DELETED_TEMPLATES}
    offenders: list[tuple[str, str]] = []
    for path in (REPO_ROOT / "app").rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _JINJA_TEMPLATE_REF_RE.finditer(text):
            referenced = Path(match.group(1)).name
            if referenced in deleted_basenames:
                offenders.append((str(path.relative_to(REPO_ROOT)), referenced))
    assert offenders == [], f"Active Jinja directive(s) referencing deleted macro(s): {offenders!r}"


# ---------------------------------------------------------------------------
# 6) The 6 SHADOW_COPY groups' surviving underscore-prefixed partials remain
#    on disk, byte-identical to pre-wave, and are still genuinely imported by
#    at least one other template.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", PRESERVED_SHADOW_COPY_SURVIVORS)
def test_preserved_shadow_copy_survivor_is_untouched(relative_path: str) -> None:
    current = _normalize_line_endings((REPO_ROOT / relative_path).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_DELETION_REF, relative_path))
    assert current == pre_wave, f"{relative_path}: byte content changed since pre-wave ref -- must be untouched."


@pytest.mark.parametrize("relative_path", PRESERVED_SHADOW_COPY_SURVIVORS)
def test_preserved_shadow_copy_survivor_still_has_a_real_consumer(relative_path: str) -> None:
    basename = Path(relative_path).name
    pattern = re.compile(
        r"""\{%\s*(?:from|include|import)\s+["']""" + re.escape(basename) + r"""["']"""
    )
    consumers = [
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "app").rglob("*.html")
        if p.name != basename and pattern.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert consumers, f"{relative_path}: expected at least one real Jinja consumer, found none."


# ---------------------------------------------------------------------------
# 7) The 8 active Style-3C meeting-family templates are byte-identical to
#    their pre-wave content -- this wave must not touch them at all.
# ---------------------------------------------------------------------------


# A later, legitimate wave (the stale-endpoint navigation fix -- see
# tests/services/test_meeting_stale_navigation_endpoint_fix_contract.py)
# corrected exactly two safe_url_for() endpoint strings per file in these
# same 6 templates: main.performance_development_guidance and main.
# performance_interim_notes_manager never existed as real Flask endpoints
# anywhere in this repo's git history (git log -S/-G across --all: 0 hits),
# silently rendering "#" via the real safe_url_for BuildError fallback.
# Corrected to their live, independently-confirmed successors (main.
# performance_meeting_p4_development_guidance and main.performance_
# interim_notes_tr). Same class of documented, evidence-based drift as the
# two prior exceptions already noted above this tuple's own definition --
# allowed here by name, nothing else.
_STALE_ENDPOINT_FIX_SUBSTITUTIONS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"safe_url_for('main.performance_interim_notes_manager')",
        b"safe_url_for('main.performance_interim_notes_tr')",
    ),
    (
        b"safe_url_for('main.performance_development_guidance')",
        b"safe_url_for('main.performance_meeting_p4_development_guidance')",
    ),
)


@pytest.mark.parametrize("relative_path", MEETING_FAMILY_TEMPLATES)
def test_meeting_family_template_is_untouched_by_this_wave(relative_path: str) -> None:
    current = _normalize_line_endings((REPO_ROOT / relative_path).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_DELETION_REF, relative_path))
    expected = pre_wave
    for old, new in _STALE_ENDPOINT_FIX_SUBSTITUTIONS:
        assert old in expected, f"{relative_path}: expected pre-wave stale pattern {old!r} not found."
        expected = expected.replace(old, new)
    assert current == expected, (
        f"{relative_path}: byte content changed since pre-wave ref by more than the known, "
        "documented stale-endpoint navigation fix substitutions -- must be untouched otherwise."
    )


# ---------------------------------------------------------------------------
# 8) The meeting family's shared CSS file is untouched.
# ---------------------------------------------------------------------------


def test_meeting_family_shared_css_is_untouched() -> None:
    current = _normalize_line_endings((REPO_ROOT / MEETING_FAMILY_SHARED_CSS).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_DELETION_REF, MEETING_FAMILY_SHARED_CSS))
    assert current == pre_wave, f"{MEETING_FAMILY_SHARED_CSS}: byte content changed since pre-wave ref."


# ---------------------------------------------------------------------------
# 9) Real, isolated create_app(): url_map route count is unchanged (985) --
#    deleting unreferenced templates cannot change registered routes, but
#    this is independently re-verified, not assumed.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): an unrelated later
# wave (AQ-2) removed the /performans/baskan-onaylari route registration
# that always lost that URL's dispatch conflict anyway (see
# tests/quality/test_route_conflict_runtime_contract.py's KNOWN_CONFLICTS
# update), dropping the real url_map route count from 985 to 984. This
# wave's own change (template deletion only) is still unrelated to routes;
# the baseline below is updated to the new, correct total.
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "dup_template_wave1" / "test_dbs"


@pytest.fixture(scope="module")
def wave1_app():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-dup-template-wave1-contract-min-length-ok")
    mp.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    mp.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    mp.setenv("AUTO_REPAIR_SCHEMA", "false")
    mp.setenv("STRICT_SCHEMA_CHECK", "false")
    mp.setenv("REQUIRE_DOTENV_FILE", "false")
    mp.setenv("STRICT_ENV_VALIDATION", "false")
    mp.setenv("WTF_CSRF_ENABLED", "false")
    mp.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    mp.setenv("MAIL_SUPPRESS_SEND", "true")
    mp.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    mp.setattr(Config, "APP_ENV", "testing")
    mp.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    mp.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    yield app

    mp.undo()


# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): 11 new
# GET-only /settings-center/* routes raised the count 984->995 -- mechanically
# re-verified against a fresh app.url_map, unrelated to this wave.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive route (POST /ai-agent/api/v2/ask) raised the count 995->996
# -- mechanically re-verified against a fresh app.url_map, unrelated to
# this wave.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 B2-F06 private uploads): one new,
# additive route (GET /portal/attachments/<int:attachment_id>) raised the
# count 996->997 -- mechanically re-verified against a fresh app.url_map,
# unrelated to this wave.
EXPECTED_URL_MAP_TOTAL = 997


def test_url_map_route_count_is_unchanged(wave1_app) -> None:
    total = len(list(wave1_app.url_map.iter_rules()))
    assert total == EXPECTED_URL_MAP_TOTAL, (
        f"url_map route count is {total}; expected {EXPECTED_URL_MAP_TOTAL} (unchanged -- "
        "this wave deleted only unreferenced templates, no route/service Python code)."
    )


# ---------------------------------------------------------------------------
# 10) Repo-wide style inventory totals are UNCHANGED (this wave's 9 deleted
#     files each contributed 0 to every bucket).
# ---------------------------------------------------------------------------

EXPECTED_ACTIVE_STYLE_TOTAL = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL = 64
EXPECTED_STYLE_BLOCK_TOTAL = 221


def test_repo_wide_style_inventory_totals_are_unchanged() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL, (
        f"active_static_total is {inventory.active_static_total}; expected "
        f"{EXPECTED_ACTIVE_STYLE_TOTAL} (unchanged -- deleted templates each carried 0)."
    )
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL, (
        f"dynamic_total is {inventory.dynamic_total}; expected {EXPECTED_DYNAMIC_STYLE_TOTAL}."
    )
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL, (
        f"style_block_total is {inventory.style_block_total}; expected {EXPECTED_STYLE_BLOCK_TOTAL} "
        "(unchanged -- deleted templates each carried 0 <style> blocks)."
    )


# ---------------------------------------------------------------------------
# 11) Repo-wide inline handler / javascript: URL totals stay 0.
# ---------------------------------------------------------------------------


def test_repo_wide_inline_handler_and_javascript_url_totals_are_zero() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.inline_handler_total == 0, (
        f"Repo-wide inline event-handler total is {inventory.inline_handler_total}; expected 0."
    )
    assert inventory.javascript_url_total == 0, (
        f"Repo-wide javascript: URL total is {inventory.javascript_url_total}; expected 0."
    )


# ---------------------------------------------------------------------------
# 12) CSP header style directives are byte-identical to Style-1's end state,
#     with no 'nonce-' token anywhere.
# ---------------------------------------------------------------------------

STYLE_DIRECTIVES = ["style-src", "style-src-elem", "style-src-attr"]
EXPECTED_STYLE_DIRECTIVE_VALUES = {
    "style-src": "'self' 'unsafe-inline' https:",
    "style-src-elem": "'self' 'unsafe-inline' https:",
    "style-src-attr": "'unsafe-inline'",
}


def _csp_header_value(response) -> str:
    value = response.headers.get("Content-Security-Policy")
    if value is None:
        value = response.headers.get("Content-Security-Policy-Report-Only")
    assert value, "No CSP header found in the response."
    return value


def _parse_csp_directives(policy_text: str) -> dict[str, str]:
    directives: dict[str, str] = {}
    for chunk in policy_text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(None, 1)
        directives[parts[0]] = parts[1] if len(parts) > 1 else ""
    return directives


def test_csp_style_directives_are_byte_identical_to_style1_end_state(client) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    for directive, expected_value in EXPECTED_STYLE_DIRECTIVE_VALUES.items():
        assert directive in directives, f"'{directive}' not found in the CSP header."
        assert directives[directive] == expected_value, (
            f"'{directive}' not at expected value: {directives[directive]!r} != {expected_value!r}"
        )


@pytest.mark.parametrize("directive", STYLE_DIRECTIVES)
def test_csp_style_directives_contain_no_nonce_token(client, directive: str) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert "'nonce-" not in directives.get(directive, ""), (
        f"'{directive}' unexpectedly contains a 'nonce-' token: {directives.get(directive)!r}"
    )


# ---------------------------------------------------------------------------
# 13) PWA/service-worker, Workflow/OpenAPI, and migrations were untouched BY
#     THIS WAVE'S OWN COMMIT.
#
# TD-032 fix (2026-08-16): this used to diff PRE_DELETION_REF against the
# *current working tree* (a bare `git diff <ref>` with no second ref). That
# conflates two different questions: "did this 2026-08-07 template-cleanup
# wave touch migrations/?" (a fixed historical fact, answered once and
# forever) versus "are there changes to migrations/ *right now*, for any
# reason, by any later wave?" (drifts constantly -- any future, unrelated
# migration wave breaks this "historical" scope-guard). Concretely, the
# real, later TD-032 migration-graph-repair work legitimately added/edited
# migrations/versions/*.py, which made the old ref-vs-working-tree form fail
# even though the 2026-08-07 wave itself never touched migrations/. Fixed by
# comparing PRE_DELETION_REF against POST_DELETION_REF -- both fixed,
# historical commits bracketing this wave's own single atomic commit
# (4af482e's only parent is PRE_DELETION_REF) -- so the assertion is a
# permanent, working-tree-independent fact about what that one commit did,
# and stays true no matter what any later, unrelated wave does to
# migrations/ (or any of the other scope_path values here).
# ---------------------------------------------------------------------------


def _git_diff_stat_between_refs(ref_a: str, ref_b: str, scope_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--stat", ref_a, ref_b, "--", scope_path],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"'git diff --stat' failed: {result.stderr!r}"
    return result.stdout


@pytest.mark.parametrize(
    "scope_path",
    [
        "app/static/pwa/",
        "service-worker.js",
        "sw.js",
        "docs/api/openapi_draft.json",
        "app/workflow/",
        "migrations/",
    ],
)
def test_out_of_scope_path_is_untouched_by_this_wave(scope_path: str) -> None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI not available in this environment.")

    diff_output = _git_diff_stat_between_refs(PRE_DELETION_REF, POST_DELETION_REF, scope_path)
    assert diff_output.strip() == "", (
        f"{scope_path} has changes between {PRE_DELETION_REF} and this wave's own landing "
        f"commit {POST_DELETION_REF}; this wave must not have touched it:\n{diff_output}"
    )


# ---------------------------------------------------------------------------
# 14) No new xfail introduced by this file.
# ---------------------------------------------------------------------------

_XFAIL_CALL_RE = re.compile(r"pytest" + r"\.xfail\(")
_XFAIL_MARK_RE = re.compile(r"@pytest" + r"\.mark\.xfail")


def test_this_file_introduces_no_xfail_usage() -> None:
    own_text = Path(__file__).read_text(encoding="utf-8")
    call_count = len(_XFAIL_CALL_RE.findall(own_text))
    mark_count = len(_XFAIL_MARK_RE.findall(own_text))
    assert call_count + mark_count == 0, (
        f"This test-only file must not introduce any real xfail usage (found "
        f"{call_count} xfail-call usages and {mark_count} xfail-mark-decorator usages)."
    )


# ---------------------------------------------------------------------------
# 15) This file never writes to any application/template/CSS source path --
#     only Path.read_text()/read_bytes()/exists(), git show/status/diff
#     (read-only), and its own isolated, temporary test SQLite DB.
# ---------------------------------------------------------------------------


def test_this_file_never_writes_to_application_or_template_or_css_source_paths() -> None:
    forbidden_write_markers = (
        "write_text(",
        "write_bytes(",
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
    assert hits == [], (
        f"Unexpected file-write/mutation call trace found in this file (it should only "
        f"read + write to its own isolated temp test DB): {hits!r}"
    )
