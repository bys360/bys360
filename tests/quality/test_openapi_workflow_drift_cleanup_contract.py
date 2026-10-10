"""BYS360 OpenAPI ve Route Dokümantasyonu -- Workflow Drift Kapanışı.

CONTEXT: `docs/api/openapi_draft.json` (OpenAPI 3.0.3, `info.version`
`"p1a-inventory"`) is a STATIC, manually-maintained documentation snapshot
-- its own `info.description` says it was originally "auto-extracted from
code" in an early bootstrap phase ("Koddan otomatik çıkarılan başlangıç
OpenAPI taslağıdır"), but the bootstrap doc that would have documented that
process (`docs/api/BYS360_OPENAPI_BOOTSTRAP.md`) was itself deleted in
commit `e1b8c62c` (2026-07-08), and no regeneration script exists anywhere
in this repo (`scripts/` has zero hits for "openapi"/"swagger"/"apispec";
no CI workflow references it either -- confirmed by repo-wide search before
this wave touched anything). `STATUS.md` shows it has since been
periodically hand-updated (path count drifted 820 -> 888 across several
audit waves) with only JSON-syntax validation ("JSON validasyon PASS"), not
regeneration. There being no canonical generator, this wave edits the JSON
directly, programmatically and deterministically (`json.load`/`del`/
`json.dumps(indent=2, ensure_ascii=False)`, then CRLF-normalized to match
the file's existing line endings) -- never by hand, never reformatting
anything it didn't need to touch.

WORKFLOW MATCH INVENTORY: a repo-wide, case-insensitive search across every
path's FULL operation body (not just the path string) for the substring
"workflow" found exactly 12 matches -- all 12 are the exact same dead
routes removed from `app/workflow/routes.py` in the prior "BYS360 Workflow
Orphan Presentation Subsystem Temizliği" wave (commit `5401195c`), each
self-documenting its own origin via its `summary` field, e.g.
`"workflow_dashboard (app/workflow/routes.py)"`. Cross-checked against a
real, isolated `create_app()` url_map: all 12 resolve to `NotFound`. Zero
of the 12 reference any `$ref` component (`data["components"]` itself has
zero "workflow" occurrences at all -- `securitySchemes.bearerAuth` and
`schemas.{MobileApiEnvelope,MobileApiError}` only), so there was no
orphaned shared component to separately prove dead. Zero overlap with the
completely unrelated evaluation-workflow state machine
(`app/services/workflow/{constants,state,visibility,transitions}.py` /
`workflow_status` data fields) -- none of those ever had, or were ever
claimed to have, an OpenAPI path entry.

EDIT: removed exactly those 12 path objects (204 lines, pure deletion --
zero additions, zero modifications elsewhere) from `docs/api/
openapi_draft.json`. Independently verified before/after: `/api/mobile`
operation count unchanged (72/72); the byte-content SHA-256 of every
`/api/mobile` path object unchanged; `components`/`security` SHA-256
unchanged; the SHA-256 of the sorted key-list of all 876 REMAINING (non-
workflow) paths is IDENTICAL before and after (proving nothing else in the
document was reordered or touched); `info`/`servers`/`openapi` version
unchanged.

This file writes NOTHING -- only `Path.read_text()`/`json.load`, `git show`
(read-only), and real, isolated subprocess `create_app()`/url_map probes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.ci_safe

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = REPO_ROOT / "docs" / "api" / "openapi_draft.json"

# The commit immediately BEFORE this wave's own edit -- the repo state
# where the 12 dead workflow path entries still existed in the JSON.
PRE_CLEANUP_REF = "5401195cb2887a80e90c51ee6768d460c66b849b"

DEAD_WORKFLOW_PATHS = (
    "/performance/workflow",
    "/workflow/dashboard",
    "/workflow/delays",
    "/workflow/executive-dashboard",
    "/workflow/modules",
    "/workflow/notifications",
    "/workflow/president-approvals",
    "/workflow/president-approvals/{approval_id}/decide",
    "/workflow/reminders/run",
    "/workflow/sync/modules",
    "/workflow/sync/performance",
    "/workflow/{workflow_id}/timeline",
)

EXPECTED_TOTAL_PATHS = 876
EXPECTED_TOTAL_OPERATIONS = 990
EXPECTED_MOBILE_OPERATION_COUNT = 72

ACTIVE_PRESIDENT_APPROVAL_PATHS = (
    "/performance/president-approvals",
    "/performance/president-approvals/{approval_id}/approve",
    "/performance/president-approvals/{approval_id}/return",
    "/performance/president-approvals/{approval_id}/delete",
    "/performance/president-approvals/{approval_id}/scorecard",
    "/performance/president-approvals/{approval_id}/card",
    "/performans/baskan-onaylari",
    "/performans/baskan-onaylari/{approval_id}/onayla",
    "/performans/baskan-onaylari/{approval_id}/iade",
    "/performans/baskan-onaylari/{approval_id}/sil",
    "/performans/baskan-onaylari/{approval_id}/karne",
    "/api/mobile/performance/president-approvals",
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


def _load_openapi() -> dict:
    with OPENAPI_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _run_isolated_probe(probe_script: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", probe_script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, {"stdout": result.stdout, "stderr": result.stderr}
    return result.stdout.strip().splitlines()


# ---------------------------------------------------------------------------
# 1) The document still parses as valid JSON.
# ---------------------------------------------------------------------------


def test_openapi_document_parses_as_valid_json() -> None:
    data = _load_openapi()
    assert data["openapi"] == "3.0.3"
    assert "paths" in data


# ---------------------------------------------------------------------------
# 2) The 12 dead workflow paths are gone; historical evidence they existed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dead_path", DEAD_WORKFLOW_PATHS)
def test_dead_workflow_path_no_longer_in_document(dead_path: str) -> None:
    data = _load_openapi()
    assert dead_path not in data["paths"], (
        f"{dead_path} is recorded as removed but still present in openapi_draft.json."
    )


def test_dead_workflow_paths_existed_at_pre_cleanup_git_ref() -> None:
    """Grounds the removal in real git history -- proves PRE_CLEANUP_REF is
    a real, correct ref (not typo'd/broken, which would make the absence
    checks above pass vacuously)."""
    text = _git_show(PRE_CLEANUP_REF, "docs/api/openapi_draft.json")
    before_data = json.loads(text)
    for dead_path in DEAD_WORKFLOW_PATHS:
        assert dead_path in before_data["paths"], (
            f"{dead_path} did not exist in openapi_draft.json at {PRE_CLEANUP_REF} -- "
            "the historical removal claim would be ungrounded."
        )
        summary = next(iter(before_data["paths"][dead_path].values()))["summary"]
        assert "app/workflow/routes.py" in summary, (
            f"{dead_path}'s summary at {PRE_CLEANUP_REF} did not cite app/workflow/routes.py "
            f"as its source: {summary!r}."
        )


def test_no_workflow_matching_path_remains_anywhere_in_the_document() -> None:
    """Repo-wide re-verification, independent of the fixed DEAD_WORKFLOW_
    PATHS list: a fresh, case-insensitive scan of every remaining path's
    FULL operation body (not just the path string) for "workflow" finds
    zero matches -- confirming the 12-item list above was exhaustive."""
    data = _load_openapi()
    offending = []
    for path, ops in data["paths"].items():
        blob = json.dumps(ops, ensure_ascii=False)
        if "workflow" in path.lower() or "workflow" in blob.lower():
            offending.append(path)
    assert not offending, f"Unexpected remaining workflow-matching path(s): {offending!r}"


# ---------------------------------------------------------------------------
# 3) No real url_map endpoint corresponds to a Workflow presentation route
#    (independent of the JSON -- re-proves the underlying app-level claim
#    the deletion relies on, using a real isolated create_app()).
# ---------------------------------------------------------------------------


def test_no_dead_workflow_endpoint_exists_in_real_url_map() -> None:
    probe_script = (
        "from app import create_app\n"
        "app = create_app()\n"
        "endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}\n"
        "print('ANY_WORKFLOW_ENDPOINT=%s' % any('workflow' in e.lower() for e in endpoints))\n"
    )
    output_lines = _run_isolated_probe(probe_script)
    assert "ANY_WORKFLOW_ENDPOINT=False" in output_lines, output_lines


# ---------------------------------------------------------------------------
# 4) /api/mobile operation count is unchanged (72), and every mobile path's
#    full content is byte-identical to the pre-cleanup git ref.
# ---------------------------------------------------------------------------


def test_mobile_api_operation_count_is_still_72() -> None:
    data = _load_openapi()
    mobile_paths = {p: ops for p, ops in data["paths"].items() if p.startswith("/api/mobile")}
    operation_count = sum(len(ops) for ops in mobile_paths.values())
    assert operation_count == EXPECTED_MOBILE_OPERATION_COUNT, (
        f"/api/mobile operation count is {operation_count}; expected {EXPECTED_MOBILE_OPERATION_COUNT}."
    )


def test_mobile_api_paths_are_byte_identical_to_pre_cleanup_git_ref() -> None:
    before_data = json.loads(_git_show(PRE_CLEANUP_REF, "docs/api/openapi_draft.json"))
    after_data = _load_openapi()

    before_mobile = {p: ops for p, ops in before_data["paths"].items() if p.startswith("/api/mobile")}
    after_mobile = {p: ops for p, ops in after_data["paths"].items() if p.startswith("/api/mobile")}

    before_sha = hashlib.sha256(json.dumps(before_mobile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    after_sha = hashlib.sha256(json.dumps(after_mobile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert before_sha == after_sha, (before_sha, after_sha)


# ---------------------------------------------------------------------------
# 5) Active-route -> OpenAPI mapping doesn't regress: a sample of genuinely
#    live, non-workflow routes still has its OpenAPI entry.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path_and_method",
    [("/", "GET"), ("/about-bys360", "GET"), ("/login", "GET")],
)
def test_sample_active_route_still_has_an_openapi_entry(path_and_method: tuple[str, str]) -> None:
    path, method = path_and_method
    data = _load_openapi()
    assert path in data["paths"], f"{path} missing from openapi_draft.json."
    assert method.lower() in data["paths"][path], f"{path} missing {method} operation."


# ---------------------------------------------------------------------------
# 6) Active President Approval records preserved (the ACTIVE performance-
#    domain family, not the deleted /workflow/president-approvals).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", ACTIVE_PRESIDENT_APPROVAL_PATHS)
def test_active_president_approval_path_still_present(relative_path: str) -> None:
    data = _load_openapi()
    assert relative_path in data["paths"], f"{relative_path} missing from openapi_draft.json."


# ---------------------------------------------------------------------------
# 7 & 8) Shared components/security schemes unchanged.
# ---------------------------------------------------------------------------


def test_components_section_is_byte_identical_to_pre_cleanup_git_ref() -> None:
    before_data = json.loads(_git_show(PRE_CLEANUP_REF, "docs/api/openapi_draft.json"))
    after_data = _load_openapi()
    before_sha = hashlib.sha256(
        json.dumps(before_data["components"], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    after_sha = hashlib.sha256(
        json.dumps(after_data["components"], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert before_sha == after_sha, (before_sha, after_sha)


def test_security_section_is_byte_identical_to_pre_cleanup_git_ref() -> None:
    before_data = json.loads(_git_show(PRE_CLEANUP_REF, "docs/api/openapi_draft.json"))
    after_data = _load_openapi()
    assert after_data["security"] == before_data["security"]
    assert after_data["components"]["securitySchemes"] == before_data["components"]["securitySchemes"]


def test_no_workflow_reference_anywhere_in_components_or_security() -> None:
    data = _load_openapi()
    blob = json.dumps({"components": data["components"], "security": data["security"]}, ensure_ascii=False)
    assert "workflow" not in blob.lower()


# ---------------------------------------------------------------------------
# 9) Every remaining (non-workflow) path is untouched -- same key set, same
#    order, same content, as the pre-cleanup git ref.
# ---------------------------------------------------------------------------


def test_all_remaining_paths_are_byte_identical_to_pre_cleanup_git_ref() -> None:
    before_data = json.loads(_git_show(PRE_CLEANUP_REF, "docs/api/openapi_draft.json"))
    after_data = _load_openapi()

    before_keys = [p for p in before_data["paths"] if p not in DEAD_WORKFLOW_PATHS]
    after_keys = list(after_data["paths"])
    assert after_keys == before_keys, "Path order/key-set drifted beyond the 12 removed workflow paths."

    for key in after_keys:
        assert after_data["paths"][key] == before_data["paths"][key], f"{key} content changed unexpectedly."


def test_total_path_and_operation_counts() -> None:
    data = _load_openapi()
    total_paths = len(data["paths"])
    total_operations = sum(len(ops) for ops in data["paths"].values())
    assert total_paths == EXPECTED_TOTAL_PATHS, total_paths
    assert total_operations == EXPECTED_TOTAL_OPERATIONS, total_operations


def test_info_and_servers_unchanged() -> None:
    before_data = json.loads(_git_show(PRE_CLEANUP_REF, "docs/api/openapi_draft.json"))
    after_data = _load_openapi()
    assert after_data["info"] == before_data["info"]
    assert after_data["servers"] == before_data["servers"]
    assert after_data["openapi"] == before_data["openapi"]


# ---------------------------------------------------------------------------
# 10) Route snapshot / route_registry consistency: no lingering workflow
#     entries anywhere that this wave's own doc cleanup should have caught.
# ---------------------------------------------------------------------------


def test_route_snapshot_and_route_registry_have_no_workflow_entries() -> None:
    snapshot_path = REPO_ROOT / "tests" / "architecture" / "snapshots" / "phase2b_route_snapshot_baseline.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    workflow_keys = [k for k in snapshot["contract_keys"] if "workflow" in k.lower()]
    assert not workflow_keys, workflow_keys

    route_registry_text = (REPO_ROOT / "app" / "route_registry.py").read_text(encoding="utf-8")
    assert '"app.workflow.routes"' not in route_registry_text


# ---------------------------------------------------------------------------
# 11) Style/CSP inventory completely unaffected (this wave touches only a
#     docs/ JSON file, outside the Jinja template scan scope entirely).
#
#     NOTE: EXPECTED_STYLE_BLOCK_TOTAL reflects the LIVE repo-wide total, not
#     a frozen snapshot of this wave's own diff -- a later, unrelated wave
#     (style3c_meeting_family_group_a) extracted 8 more <style> blocks from 8
#     active templates (no static/dynamic attributes touched), dropping the
#     total from 233 to 225. See tests/security/test_csp_style_migration_
#     cumulative_inventory_contract.py's
#     STYLE_MIGRATION_WAVES["style3c_meeting_family_group_a"]. A further,
#     unrelated later wave (weights_orphan_template_cleanup) deleted the
#     orphan app/templates/weights.html, which independently carried its own
#     one static style="..." attribute and one <style> block, dropping the
#     totals from 1035/225 to 1034/224 -- see that same cumulative file's
#     FORWARD-COMPATIBILITY FOLLOW-UP 7. A further, unrelated later wave
#     (weight_create_edit_orphan_cleanup) deleted the two sibling orphans
#     app/templates/weight_create.html and app/templates/weight_edit.html,
#     each independently carrying one static style="..." attribute and one
#     <style> block, dropping the totals from 1034/224 to 1032/222 -- see
#     that same cumulative file's FORWARD-COMPATIBILITY FOLLOW-UP 8.
# ---------------------------------------------------------------------------

# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): four new
# templates (app/templates/settings_center/_shell.html, home.html,
# module.html, plus a shared partial) were added to back the new
# /settings-center/* routes. Their CSS is authored directly as an external
# stylesheet (app/static/css/settings_center.css, not an inline <style>
# block) and all 4 spot-style needs use named classes instead of
# style="..." attributes, so this wave contributes 0 to every bucket.
# ACTIVE_STATIC_TOTAL, DYNAMIC_STYLE_TOTAL and STYLE_BLOCK_TOTAL are all
# unchanged from FORWARD-COMPATIBILITY FOLLOW-UP 8's 1032/64/222.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2, orphan-auth-
# key closure): app/templates/about_bys360.html was deleted along with the
# confirmed-dead app/about/routes.py it backed, independently carrying 0
# static/1 block/0 dynamic -- STYLE_BLOCK_TOTAL drops 222 -> 221.
EXPECTED_ACTIVE_STYLE_TOTAL = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL = 64
EXPECTED_STYLE_BLOCK_TOTAL = 221


def test_style_and_handler_inventory_is_completely_unaffected() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL
    assert inventory.inline_handler_total == 0
    assert inventory.javascript_url_total == 0


# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): AQ-2 kaldirdi
# /performans/baskan-onaylari icin main.president_low_score_approvals_center'in
# kendi route kaydini (app/performance/president_low_score_card_routes.py) --
# bu URL zaten her zaman main.performance_president_approvals tarafindan
# kazaniliyordu (bkz. tests/quality/test_route_conflict_runtime_contract.py
# KNOWN_CONFLICTS guncellemesi). Bu, url_map'ten tam olarak bir Rule kaldirdi
# ve main.president_low_score_approvals_center endpoint'ini tamamen kayitsiz
# birakti, ROUTE_COUNT'u 985'ten 984'e dusurdu ve ENDPOINT_SHA256'yi degistirdi
# -- bilincli baseline guncellemesi.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): registered 11
# new GET-only routes on main_bp (app/settings_center/routes.py: /settings-
# center plus one page per active module), each gated by
# @menu_key_required(...) using the existing live menu-visibility resolver.
# ROUTE_COUNT rose from 984 to 995 (+11, exactly matching the 11 new routes)
# and ENDPOINT_SHA256 changed accordingly -- bilinçli baseline güncellemesi.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive endpoint (POST /ai-agent/api/v2/ask, endpoint
# ai_agent.ai_agent_v2_ask, app/ai_agent/routes.py) raised ROUTE_COUNT from
# 995 to 996 and changed ENDPOINT_SHA256 accordingly -- mechanically
# re-derived from a fresh, isolated create_app() run, unrelated to this
# wave's own OpenAPI-drift-cleanup change.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 B2-F06 private uploads): one new,
# additive endpoint (GET /portal/attachments/<int:attachment_id>, endpoint
# main.portal_attachment_file, app/portal/routes.py) raised ROUTE_COUNT from
# 996 to 997 and changed ENDPOINT_SHA256 accordingly -- mechanically
# re-derived from a fresh, isolated create_app() run.
def test_url_map_route_count_and_hash_are_unaffected() -> None:
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
    assert values.get("ROUTE_COUNT") == "997"
    assert values.get("ENDPOINT_SHA256") == "269dc9216997f412a6323e22a365605535f4214aab4fdb87c0dabb74e7820e4e"


# ---------------------------------------------------------------------------
# 12) No new xfail/skip introduced by this file; this file never writes to
#     application source paths.
# ---------------------------------------------------------------------------

_XFAIL_CALL_RE_PARTS = ("pytest", ".xfail(")
_XFAIL_MARK_RE_PARTS = ("@pytest", ".mark.xfail")
_SKIP_MARK_RE_PARTS = ("@pytest", ".mark.skip")


def test_this_file_introduces_no_xfail_or_unconditional_skip_usage() -> None:
    own_text = Path(__file__).read_text(encoding="utf-8")
    assert "".join(_XFAIL_CALL_RE_PARTS) not in own_text
    assert "".join(_XFAIL_MARK_RE_PARTS) not in own_text
    assert "".join(_SKIP_MARK_RE_PARTS) not in own_text


def test_this_file_never_writes_to_application_or_doc_source_paths() -> None:
    forbidden_write_markers = (
        "write_text(",
        "shutil.copy",
        "shutil.move",
        "shutil.rmtree",
        "os.rename(",
        "os.remove(",
        "os.unlink(",
        "open(OPENAPI_PATH, \"w\"",
        "open(OPENAPI_PATH, 'w'",
    )
    own_text = Path(__file__).read_text(encoding="utf-8")
    marker_def_start = own_text.index("forbidden_write_markers = (")
    marker_def_end = own_text.index(")\n", marker_def_start) + 1
    scan_text = own_text[:marker_def_start] + own_text[marker_def_end:]
    hits = [marker for marker in forbidden_write_markers if marker in scan_text]
    assert hits == [], f"Unexpected file-write/mutation call trace found in this file: {hits!r}"
