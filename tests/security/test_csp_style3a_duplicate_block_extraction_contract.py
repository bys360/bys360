"""CSP "Style-3A" duplicate-`<style>`-block extraction wave -- this wave's own
contract test.

CONTEXT: Style-3A is a coordinated, test-only wave that verifies work already
applied to the working tree: two independent, unrelated groups of templates,
10 templates total, each getting its single `<style>...</style>` block
removed and replaced with exactly one
`<link rel="stylesheet" href="{{ url_for('static', filename='css/<file>.css') }}">`
pointing at a brand-new shared CSS file:

    Group B -- Error pages (3 templates, app/static/css/error_pages_shared.css):
        app/templates/errors/400.html
        app/templates/errors/401.html
        app/templates/errors/405.html
    Group C -- Strategic performance (5 templates, app/static/css/strategic_performance_sp3x_shared.css):
        app/templates/strategic_performance/ai_kpi_analysis.html
        app/templates/strategic_performance/competency_library.html
        app/templates/strategic_performance/kpi_dashboard.html
        app/templates/strategic_performance/self_review_form.html
        app/templates/strategic_performance/target_list.html
    Group D -- Error pages 404/500 (2 templates, app/static/css/error_pages_404_500_shared.css):
        app/templates/errors/404.html
        app/templates/errors/500.html

HISTORY NOTE -- a third group, "Group A" (executive mail, 6 templates under
app/templates/executive_summary/executive_mail_*.html, intended CSS file
app/static/css/executive_mail_center_shared.css), was originally planned and
applied as part of this wave, then INDEPENDENTLY VERIFIED AND REVERTED before
this file was finalized. Its claimed view file,
app/communication/executive_mail_center_routes.py, is dead code in this
application: it is absent from app/communication/route_manifest.py's
REQUIRED_ROUTE_MODULES/OPTIONAL_ROUTE_MODULES, absent from `sys.modules`
after `create_app()`, and 5 of its 6 claimed URLs return 404 in a real
running app (the 6th, `/executive-summary/daily-weather-mail`, resolves to a
completely different, unrelated view function). Because none of Group A's
claimed routes are actually live, all 6 templates and the would-be shared CSS
file were reverted/deleted via `git checkout --` and `Group A` was replaced
by `Group D` below, whose route evidence -- app/error_handlers.py's dedicated
`@app.errorhandler(404)` (`not_found`) and catch-all `@app.errorhandler
(Exception)` (`handle_generic_error`), both wired through the shared
`render_error_page()` helper -- is genuinely, always-active, live production
code (a 404 fires for any unmatched URL; the generic Exception handler fires
for any uncaught exception reaching Flask's dispatcher).

This file writes NOTHING to app/template/CSS/config sources -- only
`Path.read_text()`, `git show`/`git status`/`git diff` (read-only), and real
Flask test-client requests against its own isolated, temporary SQLite DB.

BYTE-PARITY NORMALIZATION (the single most important correctness check in
this file): raw string extraction of the old `<style>...</style>` block via
regex leaves a trailing, whitespace-only "line" immediately before the
closing `</style>` tag whenever (as in all 10 templates here) that tag sits
on its own, indented line right after the CSS's last real content line --
e.g. `app/templates/errors/400.html` at HEAD has `    }\n  </style>`, so a
naive `<style>(.*?)</style>` capture ends in `...}\n  ` (two trailing spaces,
no newline). A naive `.strip("\n")` normalization does NOT remove that
trailing `"  "` line, so it would incorrectly report a byte-parity MISMATCH
against the new CSS file (which has no such artifact). This was verified
empirically (both the failure of the naive approach and the success of the
line-based approach were reproduced against the real HEAD content before
writing any assertion below -- see `_normalize_style_block` and its
docstring). The correct normalization: split into lines, `rstrip()` each
line (trailing whitespace only, never leading), then drop leading/trailing
EMPTY lines (not just newline characters) before hashing.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

REPO_ROOT = Path(__file__).resolve().parents[2]

# BYS360 KOORDINATOR DUZELTMESI (ileri-uyumluluk, ayni sinif hata Style-2A'nin
# repo-genelinde testinde, Style-2B'nin "dosya dokunulmadi" testinde ve bir
# sonraki bugfix dalgasinin iki "git diff HEAD" testinde de bulunup
# duzeltilmisti -- bkz. o dosyalarin kendi KOORDINATOR NOTU bolumleri): bu
# dosya ilk yazildiginda HEAD_REF = "HEAD" idi -- bu, Style-3A HENUZ
# commit'lenmemisken DOGRUYDU (o an HEAD = onceki bugfix'in kapanis commit'i,
# yani "dalga oncesi" durumdu). Style-3A commit'lendikten (3b3a5f8) SONRA,
# "HEAD" artik Style-3A'nin KENDI commit'ini isaret ediyor -- yani
# `git show HEAD:<path>` artik "dalga oncesi" degil, "dalga SONRASI" (zaten
# duzeltilmis, <style> blogu OLMAYAN) icerigi donduruyor, bu da byte-parity/
# no-Jinja/CSS-eslesme testlerinin sahte FAIL vermesine yol aciyordu. Artik
# SABIT, tarihsel bir commit'e kilitlendi -- bu, "dalga oncesi" anlamini
# SONSUZA KADAR koruyacak sekilde dogru kalir, sonraki hicbir commit/dalgadan
# etkilenmez.
HEAD_REF = "e0340cbaba6f7fd439d4420b2c88bcdcc7031968"  # Style-3A'nin ebeveyni (bugfix'in kapanis commit'i)
STYLE3A_CLOSURE_REF = "3b3a5f8496076dcc36a195c66ddf2cbc2775160c"  # Style-3A'nin KENDI kapanis commit'i

from tests.security._bys360_style_inventory import (  # noqa: E402
    compute_inventory_from_worktree,
)

# ---------------------------------------------------------------------------
# Per-group template manifests (relative_path -> metadata). Evidence for each
# field is verified by the tests below, not merely asserted from this table.
# ---------------------------------------------------------------------------

GROUP_B_CSS = "error_pages_shared"
GROUP_C_CSS = "strategic_performance_sp3x_shared"
GROUP_D_CSS = "error_pages_404_500_shared"

GROUP_B_TEMPLATES: dict[str, dict[str, object]] = {
    "app/templates/errors/400.html": {"status_code": 400, "title_marker": "Hata 400"},
    "app/templates/errors/401.html": {"status_code": 401, "title_marker": "Hata 401"},
    "app/templates/errors/405.html": {"status_code": 405, "title_marker": "Hata 405"},
}

GROUP_C_TEMPLATES: dict[str, dict[str, str]] = {
    "app/templates/strategic_performance/ai_kpi_analysis.html": {
        "route": "/performans/stratejik/ai-kpi-analiz",
        "primary_view": "ai_kpi_analysis",
        "secondary_view": "sp1_ai_kpi_analysis",
    },
    "app/templates/strategic_performance/competency_library.html": {
        "route": "/performans/stratejik/yetkinlik-kutuphanesi",
        "primary_view": "competency_library",
        "secondary_view": "sp1_competency_library",
    },
    "app/templates/strategic_performance/kpi_dashboard.html": {
        "route": "/performans/stratejik/kpi-dashboard",
        "primary_view": "kpi_dashboard",
        "secondary_view": "sp1_kpi_dashboard",
    },
    "app/templates/strategic_performance/self_review_form.html": {
        "route": "/performans/stratejik/oz-degerlendirme",
        "primary_view": "self_review",
        "secondary_view": "sp1_self_review",
    },
    "app/templates/strategic_performance/target_list.html": {
        "route": "/performans/stratejik/hedefler",
        "primary_view": "target_list",
        "secondary_view": "sp1_kpi_targets",
    },
}
GROUP_C_PRIMARY_VIEW_FILE = "app/modules/strategic_performance/routes.py"
GROUP_C_SECONDARY_VIEW_FILE = "app/performance/sp1_sidebar_routes.py"

GROUP_D_TEMPLATES: dict[str, dict[str, object]] = {
    "app/templates/errors/404.html": {
        "status_code": 404,
        "error_code_marker": "BYS360 \u00b7 404",
        "other_group_error_code_marker": "BYS360 \u00b7 500",
    },
    "app/templates/errors/500.html": {
        "status_code": 500,
        "error_code_marker": "BYS360 \u00b7 500",
        "other_group_error_code_marker": "BYS360 \u00b7 404",
    },
}

# relative_path -> css filename stem (without extension), all 10 templates.
ALL_TEMPLATE_CSS: dict[str, str] = {
    **{t: GROUP_B_CSS for t in GROUP_B_TEMPLATES},
    **{t: GROUP_C_CSS for t in GROUP_C_TEMPLATES},
    **{t: GROUP_D_CSS for t in GROUP_D_TEMPLATES},
}
assert len(ALL_TEMPLATE_CSS) == 10

# The two templates with a PRE-EXISTING, UNRELATED, fully-dynamic
# `style="width: {{ ... }}%"` progress-bar attribute that this wave must
# never touch (it only touches <style> BLOCKS, never style="..." attributes).
PROGRESS_BAR_TEMPLATES = (
    "app/templates/strategic_performance/kpi_dashboard.html",
    "app/templates/strategic_performance/target_list.html",
)

_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_STYLE_TAG_RE = re.compile(r"<style\b", re.IGNORECASE)
_LINK_STYLESHEET_RE_PREFIX = (
    r"""<link\s+rel=["']stylesheet["']\s+href=["']\{\{\s*url_for\(\s*"""
    r"""["']static["']\s*,\s*filename=["']css/"""
)
_LINK_STYLESHEET_RE_SUFFIX = r"""\.css["']\s*\)\s*\}\}["']\s*/?>"""
_FORM_OPEN_TAG_RE = re.compile(r"<form\b[^>]*>")


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


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


def _normalize_style_block(text: str) -> str:
    """rstrip() every line, then drop leading/trailing EMPTY lines.

    Deliberately NOT `text.strip("\\n")` on the raw string -- that fails to
    remove a trailing whitespace-only "line" that sits between the last real
    CSS declaration and an indented closing `</style>` tag on its own line
    (a real, verified pattern in this repo's error-page templates: HEAD's
    app/templates/errors/400.html ends its <style> block with
    `...font-weight: 700;\\n    }\\n  ` -- the final "  " is the indentation
    of the `</style>` tag itself, captured as part of the regex group because
    it precedes the closing tag on the same line). Splitting into lines and
    rstripping each one turns that into an empty string, which the
    leading/trailing-empty-line trim below then discards, matching the new,
    plain CSS file's content (which has no such artifact).
    """
    lines = [line.rstrip() for line in text.split("\n")]
    start = 0
    end = len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return "\n".join(lines[start:end])


def _sha256_of_normalized(text: str) -> str:
    return hashlib.sha256(_normalize_style_block(text).encode("utf-8")).hexdigest()


def _extract_style_block_text(html_text: str, relative_path: str) -> str:
    match = _STYLE_BLOCK_RE.search(html_text)
    assert match, f"No <style>...</style> block found in the given text for {relative_path}."
    return match.group(1)


def _css_path(css_stem: str) -> Path:
    return REPO_ROOT / "app" / "static" / "css" / f"{css_stem}.css"


# ---------------------------------------------------------------------------
# Self-test of the normalization function itself: prove empirically (not by
# assumption) that a naive `.strip("\n")` normalization would report a FALSE
# mismatch for the trailing-whitespace-line edge case, while the line-based
# normalization used everywhere below reports a correct match. This locks in
# the reasoning from the module docstring as an executable, permanent check.
# ---------------------------------------------------------------------------


def test_normalization_edge_case_naive_strip_would_have_falsely_mismatched() -> None:
    old_text = _git_show(HEAD_REF, "app/templates/errors/400.html")
    old_block = _extract_style_block_text(old_text, "app/templates/errors/400.html")
    naive_old = old_block.strip("\n")
    naive_css = _css_path(GROUP_B_CSS).read_text(encoding="utf-8").strip("\n")
    assert naive_old != naive_css, (
        "Expected the naive `.strip('\\n')` normalization to demonstrate a FALSE "
        "mismatch for this known trailing-whitespace-line edge case; it did not, "
        "which means the edge case this test locks in may no longer apply and the "
        "module docstring's reasoning should be re-verified."
    )
    assert _normalize_style_block(old_block) == _normalize_style_block(
        _css_path(GROUP_B_CSS).read_text(encoding="utf-8")
    ), "The line-based normalization should resolve the same edge case to a real match."


# ---------------------------------------------------------------------------
# 1) Byte-parity proof: for all 10 templates, the OLD <style> block content
#    (at HEAD, before this wave) normalized-hashes identically to the NEW
#    shared CSS file's normalized hash.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(ALL_TEMPLATE_CSS))
def test_old_style_block_byte_parity_with_new_css_file(relative_path: str) -> None:
    css_stem = ALL_TEMPLATE_CSS[relative_path]
    old_text = _git_show(HEAD_REF, relative_path)
    old_block = _extract_style_block_text(old_text, relative_path)
    new_css_text = _css_path(css_stem).read_text(encoding="utf-8")

    old_hash = _sha256_of_normalized(old_block)
    new_hash = _sha256_of_normalized(new_css_text)
    assert old_hash == new_hash, (
        f"{relative_path}: normalized SHA-256 of the pre-wave <style> block "
        f"({old_hash}) does not match the normalized SHA-256 of "
        f"app/static/css/{css_stem}.css ({new_hash}). This is a genuine content "
        "discrepancy -- investigate before assuming a normalization bug."
    )


# ---------------------------------------------------------------------------
# 2) The OLD <style> block (at HEAD) was fully static -- no Jinja anywhere.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(ALL_TEMPLATE_CSS))
def test_old_style_block_was_fully_static_no_jinja(relative_path: str) -> None:
    old_text = _git_show(HEAD_REF, relative_path)
    old_block = _extract_style_block_text(old_text, relative_path)
    assert "{{" not in old_block, f"{relative_path}: pre-wave <style> block contains a Jinja expression ('{{{{')."
    assert "{%" not in old_block, f"{relative_path}: pre-wave <style> block contains a Jinja statement ('{{%')."


# ---------------------------------------------------------------------------
# 3) The CURRENT (post-wave) template source has ZERO <style> blocks.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(ALL_TEMPLATE_CSS))
def test_target_template_now_has_zero_style_blocks(relative_path: str) -> None:
    current_text = _read(relative_path)
    count = len(_STYLE_TAG_RE.findall(current_text))
    assert count == 0, f"{relative_path}: expected 0 <style> blocks post-wave, found {count}."


# ---------------------------------------------------------------------------
# 4) Each template contains EXACTLY ONE <link rel="stylesheet" ...> pointing
#    at its own group's CSS file (no duplicates).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(ALL_TEMPLATE_CSS))
def test_target_template_links_its_group_stylesheet_exactly_once(relative_path: str) -> None:
    css_stem = ALL_TEMPLATE_CSS[relative_path]
    current_text = _read(relative_path)
    pattern = re.compile(_LINK_STYLESHEET_RE_PREFIX + re.escape(css_stem) + _LINK_STYLESHEET_RE_SUFFIX)
    matches = pattern.findall(current_text)
    assert len(matches) == 1, (
        f"{relative_path}: expected exactly one <link rel=\"stylesheet\"> for "
        f"css/{css_stem}.css, found {len(matches)}."
    )


# ---------------------------------------------------------------------------
# 5) Each new shared CSS file exists and its content matches the byte-parity
#    hash independently derived for EVERY template in its group (i.e. all
#    templates in a group truly share byte-identical old content, and the
#    new file is not just matching one of them by coincidence).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "css_stem,templates",
    [
        (GROUP_B_CSS, tuple(GROUP_B_TEMPLATES)),
        (GROUP_C_CSS, tuple(GROUP_C_TEMPLATES)),
        (GROUP_D_CSS, tuple(GROUP_D_TEMPLATES)),
    ],
    ids=["group_b", "group_c", "group_d"],
)
def test_group_css_file_exists_and_matches_every_member_template(
    css_stem: str, templates: tuple[str, ...]
) -> None:
    css_path = _css_path(css_stem)
    assert css_path.is_file(), f"{css_path} does not exist."
    css_hash = _sha256_of_normalized(css_path.read_text(encoding="utf-8"))
    for relative_path in templates:
        old_block = _extract_style_block_text(_git_show(HEAD_REF, relative_path), relative_path)
        assert _sha256_of_normalized(old_block) == css_hash, (
            f"{relative_path}'s pre-wave <style> block does not match "
            f"app/static/css/{css_stem}.css."
        )


# ---------------------------------------------------------------------------
# 6A) Route/view function evidence -- Group C: grep-based SOURCE evidence
#     that a route decorator + render_template() call referencing the
#     template exists in the claimed view file(s). Group C's routes are
#     genuinely live (confirmed with a real app.test_client(), see section
#     7B), so this is corroborating source-level evidence, not the only
#     proof.
# ---------------------------------------------------------------------------


def _extract_function_body(file_text: str, function_name: str) -> str:
    def_match = re.search(rf"^def {re.escape(function_name)}\(", file_text, re.MULTILINE)
    assert def_match, f"'def {function_name}(' not found in file."
    body_start = def_match.end()
    next_def = re.search(r"^def ", file_text[body_start:], re.MULTILINE)
    body_end = body_start + next_def.start() if next_def else len(file_text)
    return file_text[body_start:body_end]


def _decorator_block_before(file_text: str, function_name: str) -> str:
    def_match = re.search(rf"^def {re.escape(function_name)}\(", file_text, re.MULTILINE)
    assert def_match, f"'def {function_name}(' not found in file."
    pre_text = file_text[: def_match.start()]
    decorator_match = re.search(r"((?:@\S.*\n)+)$", pre_text)
    assert decorator_match, f"No decorator block found immediately before 'def {function_name}('."
    return decorator_match.group(1)


_GROUP_C_EVIDENCE_CASES = [
    (rp, "primary_view", GROUP_C_PRIMARY_VIEW_FILE) for rp in sorted(GROUP_C_TEMPLATES)
] + [
    (rp, "secondary_view", GROUP_C_SECONDARY_VIEW_FILE) for rp in sorted(GROUP_C_TEMPLATES)
]


@pytest.mark.parametrize(
    "relative_path,view_key,view_file",
    _GROUP_C_EVIDENCE_CASES,
    ids=[f"{Path(rp).stem}::{key}" for rp, key, _f in _GROUP_C_EVIDENCE_CASES],
)
def test_group_c_template_has_route_and_render_evidence_in_both_owning_files(
    relative_path: str, view_key: str, view_file: str
) -> None:
    meta = GROUP_C_TEMPLATES[relative_path]
    view_name = meta[view_key]
    view_file_text = (REPO_ROOT / view_file).read_text(encoding="utf-8")
    body = _extract_function_body(view_file_text, view_name)
    basename = Path(relative_path).name
    assert basename in body, f"{view_name}() in {view_file} does not reference '{basename}'."
    assert "render_template(" in body or "safe_render(" in body, (
        f"{view_name}() in {view_file} has no render_template()/safe_render() call."
    )
    decorator_block = _decorator_block_before(view_file_text, view_name)
    assert re.search(r"@\w+(?:_bp)?\.route\(", decorator_block), (
        f"{view_name}() in {view_file} has no '.route(...)' decorator: {decorator_block!r}"
    )


# ---------------------------------------------------------------------------
# 6B) Group B: error-handler registration evidence in app/error_handlers.py.
# ---------------------------------------------------------------------------


def test_group_b_error_handlers_module_wires_up_all_three_status_codes() -> None:
    text = (REPO_ROOT / "app" / "error_handlers.py").read_text(encoding="utf-8")
    assert 'render_template(\n            f"errors/{status_code}.html",' in text or re.search(
        r'render_template\(\s*f"errors/\{status_code\}\.html"', text
    ), "render_error_page() no longer renders 'errors/{status_code}.html'."
    assert re.search(r"@app\.errorhandler\(HTTPException\)", text), (
        "No generic '@app.errorhandler(HTTPException)' registration found -- this is "
        "what serves 400 and 401 (neither has its own dedicated handler)."
    )
    assert re.search(r"@app\.errorhandler\(MethodNotAllowed\)", text), (
        "No '@app.errorhandler(MethodNotAllowed)' registration found -- this is what "
        "serves 405."
    )
    # 400/401 must NOT have their own more-specific handler (that would change
    # which code path serves them and invalidate the module docstring's claim).
    assert not re.search(r"@app\.errorhandler\(400\)", text), (
        "A dedicated @app.errorhandler(400) now exists -- 400 no longer falls "
        "through to the generic HTTPException handler; re-verify this file's "
        "Group B assumptions."
    )
    assert not re.search(r"@app\.errorhandler\(401\)", text), (
        "A dedicated @app.errorhandler(401) now exists -- 401 no longer falls "
        "through to the generic HTTPException handler; re-verify this file's "
        "Group B assumptions."
    )


# ---------------------------------------------------------------------------
# 6C) Group D: error-handler registration evidence in app/error_handlers.py
#     -- a dedicated `@app.errorhandler(404)` (`not_found`) and a generic,
#     catch-all `@app.errorhandler(Exception)` (`handle_generic_error`), both
#     wired through the same `render_error_page()` helper used by Group B.
#     Unlike Group C's `_extract_function_body`/`_decorator_block_before`
#     helpers (which require the `def` to sit at column 0), these two
#     handlers are nested inside `register_error_handlers(app)` at 4-space
#     indentation, so this section uses direct text-window checks instead.
# ---------------------------------------------------------------------------


def test_group_d_error_handlers_module_wires_up_404_and_generic_exception_handlers() -> None:
    text = (REPO_ROOT / "app" / "error_handlers.py").read_text(encoding="utf-8")
    assert re.search(
        r'render_template\(\s*f"errors/\{status_code\}\.html"', text
    ), "render_error_page() no longer renders 'errors/{status_code}.html'."

    assert re.search(r"@app\.errorhandler\(404\)\s*\n\s*def not_found\(", text), (
        "No '@app.errorhandler(404)' immediately followed by 'def not_found(' found -- "
        "Group D's dedicated 404 handler is expected to look like this."
    )
    not_found_window = re.search(r"def not_found\(.*?\n(?:    @app\.errorhandler|def register_)", text, re.DOTALL)
    assert not_found_window, "Could not isolate not_found()'s handler body from the rest of the file."
    assert "render_error_page(404," in not_found_window.group(0), (
        "not_found() handler body does not call render_error_page(404, ...)."
    )

    assert re.search(r"@app\.errorhandler\(Exception\)\s*\n\s*def handle_generic_error\(", text), (
        "No '@app.errorhandler(Exception)' immediately followed by 'def handle_generic_error(' "
        "found -- Group D's catch-all 500 handler is expected to look like this."
    )
    generic_window = re.search(r"def handle_generic_error\(.*", text, re.DOTALL)
    assert generic_window, "Could not find handle_generic_error()'s body."
    assert re.search(r"render_error_page\(\s*\n?\s*500,", generic_window.group(0)), (
        "handle_generic_error() handler body does not call render_error_page(500, ...)."
    )


def test_group_d_route_manifest_and_dead_group_a_route_file_remain_unreferenced() -> None:
    """Companion check to the module docstring's history note: the dead
    Group A view file must still be absent from route_manifest.py (i.e. the
    revert genuinely stuck and nobody has since wired it up for real, which
    would make Group D's own docstring claim about Group A stale)."""
    manifest_text = (
        REPO_ROOT / "app" / "communication" / "route_manifest.py"
    ).read_text(encoding="utf-8")
    assert "executive_mail_center_routes" not in manifest_text, (
        "app/communication/route_manifest.py now references "
        "executive_mail_center_routes -- Group A's routes may have been wired up; "
        "revisit this test file's module docstring history note."
    )


# ---------------------------------------------------------------------------
# 7) Real Flask/Jinja render checks. Module-scoped isolated Flask app with a
#    real admin user + real login, matching the established
#    Wave2/phase13b/Style-2A/Style-2B fixture pattern (UUID-based temp
#    SQLite, pytest.MonkeyPatch + mp.undo(), WTF_CSRF_ENABLED=False).
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "csp_style3a" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("\u015fablonunda hata var", "\u015fablonu hatal\u0131")
_BASE_TEMPLATE_MARKER = "topbarNotificationBadge"

# A confirmed-live, GET-only production route (Group C's own kpi_dashboard)
# used ONLY to trigger a real 405 for Group B.
_LIVE_GET_ONLY_ROUTE_FOR_405_PROBE = "/performans/stratejik/kpi-dashboard"

# Test-only probe route paths registered directly on the isolated app object
# (in-memory `app.route(...)`, never written to any source file) to exercise
# REAL production code paths that have no reachable production route of
# their own with a predictable, guaranteed status in this app: a bare
# abort(400), the real, existing (but currently uncalled-by-any-live-route)
# app.security.decorators.role_required() decorator's own abort(401) branch
# for an unauthenticated request, and a bare `raise RuntimeError(...)` for
# Group D's generic-exception (500) handler. Group D's 404 probe path is
# simply a nonexistent URL under this same test-only prefix -- no special
# route registration is needed for a 404, it is Flask's own default
# behavior for any unmatched rule.
_PROBE_400_PATH = "/bys360-style3a-test-only/abort-400-probe"
_PROBE_401_PATH = "/bys360-style3a-test-only/role-required-401-probe"
_PROBE_404_PATH = "/bys360-style3a-test-only/definitely-does-not-exist-404-probe"
_PROBE_500_PATH = "/bys360-style3a-test-only/generic-exception-500-probe"


@pytest.fixture(scope="module")
def style3a_env(request):
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-csp-style3a-contract-min-length-ok")
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
    mp.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    mp.setenv("FILE_CENTER_ENABLED", "true")

    from app import create_app
    from config import Config

    mp.setattr(Config, "APP_ENV", "testing")
    mp.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    mp.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    request.addfinalizer(lambda: release_sqlite_app(app))
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    # Register test-only probe routes BEFORE the first request is dispatched
    # (Flask forbids add_url_rule() after the app has served a request).
    from flask import abort as _flask_abort

    from app.security.decorators import role_required

    @app.route(_PROBE_400_PATH, methods=["GET"])
    def _style3a_abort_400_probe():
        _flask_abort(400)

    @app.route(_PROBE_401_PATH, methods=["GET"])
    @role_required("admin")
    def _style3a_role_required_401_probe():  # pragma: no cover - unreachable when 401 fires
        return "unreachable-if-401-triggers-correctly", 200

    @app.route(_PROBE_500_PATH, methods=["GET"])
    def _style3a_generic_exception_500_probe():
        raise RuntimeError("style3a-test-only-forced-exception-for-500-probe")

    from app.extensions import db
    from app.models import User

    with app.app_context():
        db.create_all()
        user = User(
            sicil_no="style3a001",
            email="style3a.contract@ktb.gov.tr",
            ad="Style3A",
            soyad="Kontrat",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("Style3ATestContractKey1!")
        db.session.add(user)
        db.session.commit()
        admin_user_id = user.id

    client = app.test_client()
    login_response = client.post(
        "/login",
        data={"sicil_or_email": "style3a001", "password": "Style3ATestContractKey1!"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302, (
        f"Test admin login failed: status={login_response.status_code}"
    )
    assert "/login" not in (login_response.headers.get("Location") or ""), (
        "Still redirected to /login after POST -- authentication may have failed."
    )

    anon_client = app.test_client()

    yield app, client, anon_client, admin_user_id

    mp.undo()


# ---------------------------------------------------------------------------
# 7A) Group C: real HTTP GET, confirmed live (module docstring / manual
#     verification: all 5 routes return 200 for an authenticated admin).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(GROUP_C_TEMPLATES))
def test_group_c_template_route_renders_successfully_when_authenticated(
    style3a_env, relative_path: str
) -> None:
    _app, client, _anon_client, _admin_user_id = style3a_env
    route = GROUP_C_TEMPLATES[relative_path]["route"]
    response = client.get(route, follow_redirects=True)
    assert response.status_code == 200, (
        f"{route} ({relative_path}) returned unexpected status {response.status_code}."
    )
    body = response.get_data(as_text=True)
    assert f"css/{GROUP_C_CSS}" in body, f"{route}: response does not reference css/{GROUP_C_CSS}."
    assert _BASE_TEMPLATE_MARKER in body, f"{route}: response missing base.html's own marker."
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, f"{route}: response looks like a safe_render() fallback stub."


# ---------------------------------------------------------------------------
# 7B) Group B: real HTTP triggers for 400 / 401 / 405 -- must NOT accidentally
#     render 200 for what should be an error status.
# ---------------------------------------------------------------------------


def test_group_b_400_error_page_renders_via_real_abort(style3a_env) -> None:
    _app, client, _anon_client, _admin_user_id = style3a_env
    response = client.get(_PROBE_400_PATH)
    assert response.status_code == 400, f"Expected 400, got {response.status_code}."
    assert response.status_code != 200
    body = response.get_data(as_text=True)
    assert f"css/{GROUP_B_CSS}" in body
    assert GROUP_B_TEMPLATES["app/templates/errors/400.html"]["title_marker"] in body


def test_group_b_401_error_page_renders_via_real_role_required_decorator(style3a_env) -> None:
    _app, _client, anon_client, _admin_user_id = style3a_env
    response = anon_client.get(_PROBE_401_PATH)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}."
    assert response.status_code != 200
    body = response.get_data(as_text=True)
    assert f"css/{GROUP_B_CSS}" in body
    assert GROUP_B_TEMPLATES["app/templates/errors/401.html"]["title_marker"] in body
    assert "unreachable-if-401-triggers-correctly" not in body, (
        "The probe view's own body leaked through -- abort(401) did not actually fire."
    )


@pytest.mark.parametrize("use_authenticated_client", [True, False], ids=["authed", "anonymous"])
def test_group_b_405_error_page_renders_via_real_method_not_allowed(
    style3a_env, use_authenticated_client: bool
) -> None:
    _app, client, anon_client, _admin_user_id = style3a_env
    active_client = client if use_authenticated_client else anon_client
    response = active_client.post(_LIVE_GET_ONLY_ROUTE_FOR_405_PROBE)
    assert response.status_code == 405, f"Expected 405, got {response.status_code}."
    assert response.status_code != 200
    body = response.get_data(as_text=True)
    assert f"css/{GROUP_B_CSS}" in body
    assert GROUP_B_TEMPLATES["app/templates/errors/405.html"]["title_marker"] in body


# ---------------------------------------------------------------------------
# 7C) Group D: real HTTP triggers for 404 / 500 -- a genuine unmatched URL
#     and a genuine uncaught exception, both dispatched through the app's
#     real error-handling machinery (see section 6C for the source-level
#     evidence that these handlers exist). Must not accidentally render 200,
#     and each page's own body must show ONLY its own status code's marker
#     (404 and 500 share the same CSS classes/selectors but have different
#     `title`/`message` Jinja variables and different
#     `<p class="error-code">BYS360 \u00b7 404</p>` vs `\u00b7 500` markers).
# ---------------------------------------------------------------------------


def test_group_d_404_error_page_renders_via_real_unmatched_url(style3a_env) -> None:
    _app, client, _anon_client, _admin_user_id = style3a_env
    response = client.get(_PROBE_404_PATH)
    assert response.status_code == 404, f"Expected 404, got {response.status_code}."
    assert response.status_code != 200
    body = response.get_data(as_text=True)
    meta = GROUP_D_TEMPLATES["app/templates/errors/404.html"]
    assert f"css/{GROUP_D_CSS}" in body, f"404 response does not reference css/{GROUP_D_CSS}."
    assert meta["error_code_marker"] in body, "404 response missing its own 'BYS360 \u00b7 404' marker."
    assert meta["other_group_error_code_marker"] not in body, (
        "404 response unexpectedly contains the 500 page's own error-code marker."
    )
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, "404 response looks like a safe_render()/generic fallback stub."


def test_group_d_500_error_page_renders_via_real_generic_exception_handler(style3a_env) -> None:
    _app, client, _anon_client, _admin_user_id = style3a_env
    response = client.get(_PROBE_500_PATH)
    assert response.status_code == 500, f"Expected 500, got {response.status_code}."
    assert response.status_code != 200
    body = response.get_data(as_text=True)
    meta = GROUP_D_TEMPLATES["app/templates/errors/500.html"]
    assert f"css/{GROUP_D_CSS}" in body, f"500 response does not reference css/{GROUP_D_CSS}."
    assert meta["error_code_marker"] in body, "500 response missing its own 'BYS360 \u00b7 500' marker."
    assert meta["other_group_error_code_marker"] not in body, (
        "500 response unexpectedly contains the 404 page's own error-code marker."
    )
    assert "style3a-test-only-forced-exception-for-500-probe" not in body, (
        "The probe view's own raised exception message leaked into the response body -- "
        "the generic Exception handler's safe fallback should never expose it."
    )


# ---------------------------------------------------------------------------
# 8) Form/action/method/CSRF byte-identical check for the template (out of
#    10) that contains a <form ...> tag. This wave should never have touched
#    any form.
# ---------------------------------------------------------------------------

FORM_BEARING_TEMPLATES = ("app/templates/strategic_performance/self_review_form.html",)


def _extract_attr(tag_text: str, attr_name: str) -> str | None:
    match = re.search(rf'{attr_name}\s*=\s*"([^"]*)"', tag_text)
    return match.group(1) if match else None


@pytest.mark.parametrize("relative_path", sorted(set(ALL_TEMPLATE_CSS) - set(FORM_BEARING_TEMPLATES)))
def test_non_form_bearing_template_confirmed_to_have_no_form_tag(relative_path: str) -> None:
    """Independent verification that FORM_BEARING_TEMPLATES above is complete
    (not just trusted): every OTHER template genuinely has zero <form> tags,
    in both the pre-wave (HEAD) and current content."""
    assert _FORM_OPEN_TAG_RE.findall(_git_show(HEAD_REF, relative_path)) == []
    assert _FORM_OPEN_TAG_RE.findall(_read(relative_path)) == []


@pytest.mark.parametrize("relative_path", FORM_BEARING_TEMPLATES)
def test_form_tag_method_and_action_are_byte_identical_before_and_after(relative_path: str) -> None:
    before_text = _git_show(HEAD_REF, relative_path)
    after_text = _read(relative_path)

    before_forms = _FORM_OPEN_TAG_RE.findall(before_text)
    after_forms = _FORM_OPEN_TAG_RE.findall(after_text)
    assert before_forms, f"{relative_path}: no <form ...> tag found at HEAD."
    assert len(before_forms) == len(after_forms), (
        f"{relative_path}: <form> tag count changed: {len(before_forms)} -> {len(after_forms)}"
    )
    for index, (before_tag, after_tag) in enumerate(zip(before_forms, after_forms, strict=True)):
        before_method = _extract_attr(before_tag, "method")
        after_method = _extract_attr(after_tag, "method")
        before_action = _extract_attr(before_tag, "action")
        after_action = _extract_attr(after_tag, "action")
        assert before_method == after_method, (
            f"{relative_path}: form[{index}] method changed: {before_method!r} -> {after_method!r}"
        )
        assert before_action == after_action, (
            f"{relative_path}: form[{index}] action changed: {before_action!r} -> {after_action!r}"
        )


# ---------------------------------------------------------------------------
# 9) Repo-wide inline-handler / javascript: URL counts are still 0 (canonical
#    HTMLParser-based helper, not a hand-rolled regex).
# ---------------------------------------------------------------------------


def test_repo_wide_inline_handler_and_javascript_url_totals_are_zero() -> None:
    inventory = compute_inventory_from_worktree()
    assert inventory.inline_handler_total == 0, (
        f"Repo-wide inline event-handler total is {inventory.inline_handler_total}; expected 0."
    )
    assert inventory.javascript_url_total == 0, (
        f"Repo-wide javascript: URL total is {inventory.javascript_url_total}; expected 0."
    )


# ---------------------------------------------------------------------------
# 10) Global active/dynamic style ATTRIBUTE totals unchanged (this wave only
#     touched <style> BLOCKS, never style="..." attributes anywhere) -- and
#     the two pre-existing progress-bar dynamic style attributes are still
#     present, byte-for-byte, in their two templates.
# ---------------------------------------------------------------------------

# Was 1068 as of Style-3A's own closure. A later, unrelated wave (the "BYS360
# Executive Mail Orphan Alt Sistemi" cleanup) deleted 6 dead, unreachable
# app/templates/executive_summary/executive_mail_*.html templates (their only
# renderer, app/communication/executive_mail_center_routes.py, was proven
# absent from sys.modules/route_manifest.py/the real url_map), removing 8
# static style="..." attributes with them: 1068 - 8 = 1060. A further later
# wave (BYS360 Daily Weather/Mail Orphan Template Temizliği) deleted 4 more
# confirmed-orphan templates, removing 20 more static style="..." attributes
# (5 each, byte-identical): 1060 - 20 = 1040. A further later wave (BYS360
# Executive Summary Artık Servis/Template Temizliği) deleted 1 more
# confirmed-orphan template (app/templates/dashboard/executive_summary.html),
# removing 3 more static style="..." attributes: 1040 - 3 = 1037. A further
# later wave (BYS360 Workflow Orphan Presentation Subsystem Temizliği)
# deleted 14 more confirmed-orphan templates (2 full trees of 7), removing 2
# more static style="..." attributes and (the first wave ever to do so) 2
# dynamic style="..." attributes: 1037 - 2 = 1035, 66 - 2 = 64. A further,
# unrelated later wave (weights_orphan_template_cleanup) deleted the orphan
# app/templates/weights.html, which independently carried its own one static
# style="..." attribute: 1035 - 1 = 1034. A further, unrelated later wave
# (weight_create_edit_orphan_cleanup) deleted the two sibling orphans
# app/templates/weight_create.html and app/templates/weight_edit.html, each
# independently carrying one static style="..." attribute: 1034 - 2 = 1032.
# See
# tests/security/test_csp_style_migration_cumulative_inventory_contract.py's
# DELETED_TEMPLATE_WAVES["orphan_mail_cleanup"],
# DELETED_TEMPLATE_WAVES["daily_weather_mail_cleanup"],
# DELETED_TEMPLATE_WAVES["executive_summary_dashboard_cleanup"], and
# DELETED_TEMPLATE_WAVES["workflow_orphan_presentation_cleanup"] for the
# independently re-derived evidence. A further, unrelated later wave
# (BYS360 Settings Center V2) added 4 new templates, but their CSS is an
# external stylesheet with no inline style="..." attributes -- 0
# contribution, total remains 1032. See that same ledger file's
# FORWARD-COMPATIBILITY FOLLOW-UP 9.
# FORWARD-COMPATIBILITY FOLLOW-UP 13 (BYS360 UX wave 4, support/index.html --
# Yardım Merkezi): the help-center template's 13 static style="..." attributes
# were replaced by classes in bys360_components.css -- 1032 -> 1019 (0 blocks,
# 0 dynamic). See STYLE_MIGRATION_WAVES["ux_wave4_help_center"].
# FORWARD-COMPATIBILITY FOLLOW-UP 14 (BYS360 UX wave 5, support/help_article,
# help_category, help_role, help_search): their 2 + 3 + 1 + 3 = 9 static
# style="..." attributes were replaced by classes in bys360_components.css --
# 1019 -> 1010 (0 blocks, 0 dynamic). See
# STYLE_MIGRATION_WAVES["ux_wave5_help_pages"].
# FORWARD-COMPATIBILITY FOLLOW-UP 15 (BYS360 UX wave 6, support/help_admin_form.html
# and support/setup.html): 4 + 3 = 7 static style="..." attributes and both
# templates' single page-level <style> blocks moved into bys360_components.css --
# active static 1010 -> 1003, <style> blocks 219 -> 217. See
# STYLE_MIGRATION_WAVES["ux_wave6_help_form_setup"].
EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3A = 1003
EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3A = 64


def test_repo_wide_active_and_dynamic_style_attribute_totals_are_unchanged() -> None:
    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3A, (
        f"Repo-wide active (static) style attribute total is "
        f"{inventory.active_static_total}; expected "
        f"{EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3A} (unchanged from the pre-Style-3A "
        "cumulative baseline -- see test_csp_style_migration_cumulative_inventory_"
        "contract.py). Style-3A must not touch any style=\"...\" attribute."
    )
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3A, (
        f"Repo-wide Jinja-dynamic style attribute total is {inventory.dynamic_total}; "
        f"expected {EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3A} (unchanged)."
    )


@pytest.mark.parametrize("relative_path", PROGRESS_BAR_TEMPLATES)
def test_pre_existing_dynamic_progress_bar_style_attribute_is_still_present(
    relative_path: str,
) -> None:
    current_text = _read(relative_path)
    match = re.search(r'style="width: \{\{[^"]*%"', current_text)
    assert match, (
        f"{relative_path}: expected its pre-existing, unrelated dynamic "
        "'style=\"width: {{ ... }}%\"' progress-bar attribute to still be present "
        "byte-for-byte; it was not found. This wave must only touch <style> BLOCKS, "
        "never style=\"...\" attributes."
    )
    # Also present, byte-for-byte, at HEAD (i.e. genuinely pre-existing, not
    # something this wave (or this test) introduced).
    before_text = _git_show(HEAD_REF, relative_path)
    assert match.group(0) in before_text, (
        f"{relative_path}: the current dynamic progress-bar style attribute value "
        "does not appear verbatim at HEAD -- it may not be genuinely pre-existing."
    )


# ---------------------------------------------------------------------------
# 11) Global <style> block total dropped by EXACTLY 10 relative to the
#     pre-wave (Style-2B end state) count of 270 -- i.e. is now 260. The
#     coordinator independently confirmed the pre-wave total was 270 (see
#     tests/security/test_csp_style_migration_cumulative_inventory_contract.py
#     ::INITIAL_STYLE_BLOCK_TOTAL, which is itself re-derived from a fixed
#     historical git ref by that file's own test).
# ---------------------------------------------------------------------------

PRE_STYLE3A_STYLE_BLOCK_TOTAL = 270
# -10 from Style-3A itself. -6 from the later orphan_mail_cleanup wave (see
# EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3A's comment above): its 6 deleted
# templates each carried exactly one <style> block. -2 from the later
# style3b_low_risk wave (2 templates, performance/meeting_development.html +
# performance/meeting_p3_reminders.html, each carried exactly one <style>
# block, extracted to app/static/css/meeting_development_b_shared.css -- see
# tests/security/test_csp_style_migration_cumulative_inventory_contract.py's
# STYLE_MIGRATION_WAVES["style3b_low_risk"]). -4 from the later
# daily_weather_mail_cleanup wave (4 confirmed-orphan templates deleted, each
# carried exactly one <style> block -- see that same ledger file's
# DELETED_TEMPLATE_WAVES["daily_weather_mail_cleanup"]). -1 from the later
# executive_summary_dashboard_cleanup wave (1 confirmed-orphan template
# deleted, carried exactly one <style> block -- see that same ledger file's
# DELETED_TEMPLATE_WAVES["executive_summary_dashboard_cleanup"]). -14 from
# the later workflow_orphan_presentation_cleanup wave (14 confirmed-orphan
# templates deleted -- two full 7-template trees -- each carried exactly one
# <style> block -- see that same ledger file's
# DELETED_TEMPLATE_WAVES["workflow_orphan_presentation_cleanup"]). -8 from
# the later style3c_meeting_family_group_a wave (8 active templates, each
# carried exactly one <style> block, extracted to app/static/css/
# meeting_development_c_shared.css -- see that same ledger file's
# STYLE_MIGRATION_WAVES["style3c_meeting_family_group_a"]). -1 from the later
# weights_orphan_template_cleanup wave (deleted app/templates/weights.html,
# which independently carried exactly one <style> block -- see that same
# ledger file's FORWARD-COMPATIBILITY FOLLOW-UP 7). -2 from the later
# weight_create_edit_orphan_cleanup wave (deleted app/templates/
# weight_create.html and app/templates/weight_edit.html, each independently
# carrying exactly one <style> block -- see that same ledger file's
# FORWARD-COMPATIBILITY FOLLOW-UP 8). +0 from the later BYS360 Settings
# Center V2 wave (4 new templates added, but their CSS is an external
# stylesheet with no <style> blocks -- see that same ledger file's
# FORWARD-COMPATIBILITY FOLLOW-UP 9). -1 from the further later BYS360
# Settings Center V2 orphan-auth-key closure wave (deleted the confirmed-
# dead app/templates/about_bys360.html, which independently carried
# exactly one <style> block -- see that same ledger file's FORWARD-
# COMPATIBILITY FOLLOW-UP 10).
# -1 from the later BYS360 UX pilot wave (support/new.html's page-level
# <style> block moved to the scoped external stylesheet
# app/static/css/bys360_components.css -- see that same ledger file's
# STYLE_MIGRATION_WAVES["ux_pilot_support_new"]).
# -1 from the later BYS360 UX wave 2 (support/list.html's page-level
# <style> block moved to the same scoped external stylesheet -- see
# STYLE_MIGRATION_WAVES["ux_wave2_support_list"]).
# -2 from the later BYS360 UX wave 6 (support/help_admin_form.html and
# support/setup.html page-level <style> blocks moved to the same scoped
# external stylesheet -- see STYLE_MIGRATION_WAVES["ux_wave6_help_form_setup"]).
# 270 - 10 - 6 - 2 - 4 - 1 - 14 - 8 - 1 - 2 - 1 - 1 - 1 - 2 = 217.
EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3A = PRE_STYLE3A_STYLE_BLOCK_TOTAL - 10 - 6 - 2 - 4 - 1 - 14 - 8 - 1 - 2 - 1 - 1 - 1 - 2


def test_repo_wide_style_block_total_dropped_by_exactly_10() -> None:
    inventory = compute_inventory_from_worktree()
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3A, (
        f"Repo-wide <style> block total is {inventory.style_block_total}; expected "
        f"{PRE_STYLE3A_STYLE_BLOCK_TOTAL} - 10 - 6 - 2 - 4 - 1 - 14 - 8 - 1 - 2 - 1 - 1 - 1 - 2 = "
        f"{EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3A} (Style-3A removed exactly one "
        "<style> block from each of its 10 templates and added none; the later "
        "orphan_mail_cleanup wave deleted 6 more dead templates each with exactly "
        "one <style> block; the later style3b_low_risk wave extracted 2 more "
        "<style> blocks from 2 active templates; the later daily_weather_mail_"
        "cleanup wave deleted 4 more dead templates each with exactly one "
        "<style> block)."
    )


# ---------------------------------------------------------------------------
# 12) CSP header style directives are byte-identical to Style-1's end state,
#     with no 'nonce-' token anywhere -- wave-agnostic, copied logic (see
#     test_csp_style2a_repo_wide_contract.py / test_csp_style2b_target_
#     templates_contract.py, section 4/13 respectively).
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
# 13) Static PWA/service-worker files are byte-identical to git HEAD -- this
#     wave should not have touched app/static/pwa/ at all. Skips ONLY if the
#     git binary itself is unavailable (environment limitation), never on a
#     clean/empty diff (a genuinely-empty diff here is the PASSING case).
# ---------------------------------------------------------------------------


def test_pwa_static_directory_is_untouched_by_this_wave() -> None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI not available in this environment.")

    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--stat", "HEAD", "--", "app/static/pwa/"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"'git diff --stat' failed: {result.stderr!r}"
    assert result.stdout.strip() == "", (
        f"app/static/pwa/ has uncommitted changes; Style-3A must not touch it:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# 14) Plan-scope guard: Style-3A's OWN closure commit (HEAD_REF..
#     STYLE3A_CLOSURE_REF, a FIXED historical range) touches ONLY the 10
#     templates + 3 new CSS files under app/templates/ and app/static/css/
#     -- nothing else.
#
#     BYS360 KOORDINATOR DUZELTMESI: bu test ilk yazildiginda live `git
#     status --porcelain` (commit'lenmemis calisma agaci durumu) kullaniyordu
#     -- bu, Style-3A HENUZ commit'lenmemisken dogruydu, ama commit'lendikten
#     SONRA `git status` HER ZAMAN bos doner (degisiklikler zaten HEAD'in bir
#     PARCASI), bu da "degisen sablon seti bos, 10 bekleniyordu" seklinde
#     sahte FAIL'e yol aciyordu. Artik SABIT bir tarihsel commit araligina
#     (`git diff --name-status HEAD_REF..STYLE3A_CLOSURE_REF`) kilitlendi --
#     bu, Style-3A'nin KENDI commit'inin GERCEKTEN neyi degistirdigini
#     SONSUZA KADAR dogru sekilde kanitlar, sonraki hicbir dalga/commit'ten
#     etkilenmez.
# ---------------------------------------------------------------------------


def _git_diff_name_status_lines(pre_ref: str, post_ref: str, scope_paths: tuple[str, ...]) -> list[str] | None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        return None
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--name-status", f"{pre_ref}..{post_ref}", "--", *scope_paths],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def test_style3a_closure_commit_scoped_to_wave_directories_touches_only_the_10_templates_and_3_css_files() -> None:
    lines = _git_diff_name_status_lines(HEAD_REF, STYLE3A_CLOSURE_REF, ("app/templates/", "app/static/css/"))
    if lines is None:
        pytest.skip("git CLI not available in this environment.")

    modified_templates: set[str] = set()
    new_css_files: set[str] = set()
    unexpected: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        code, path = parts[0], parts[-1].replace("\\", "/")
        if code.strip() == "M" and path in ALL_TEMPLATE_CSS:
            modified_templates.add(path)
        elif code.strip() == "A" and path.startswith("app/static/css/") and path.endswith(".css"):
            new_css_files.add(path)
        else:
            unexpected.append(f"{code} {path}")

    assert unexpected == [], (
        f"Unexpected changes found under app/templates/ or app/static/css/ outside "
        f"this wave's own footprint: {unexpected!r}"
    )
    assert modified_templates == set(ALL_TEMPLATE_CSS), (
        "Modified-template set does not match the expected 10: "
        f"missing={set(ALL_TEMPLATE_CSS) - modified_templates!r}, "
        f"extra={modified_templates - set(ALL_TEMPLATE_CSS)!r}"
    )
    expected_css_files = {f"app/static/css/{stem}.css" for stem in (GROUP_B_CSS, GROUP_C_CSS, GROUP_D_CSS)}
    assert new_css_files == expected_css_files, (
        f"New CSS file set does not match the expected 3: "
        f"missing={expected_css_files - new_css_files!r}, extra={new_css_files - expected_css_files!r}"
    )


# ---------------------------------------------------------------------------
# 15) No new xfail introduced by this file.
# ---------------------------------------------------------------------------


_XFAIL_CALL_RE = re.compile(r"pytest" + r"\.xfail\(")
_XFAIL_MARK_RE = re.compile(r"@pytest" + r"\.mark\.xfail")


def test_this_file_introduces_no_xfail_usage() -> None:
    """Scans this file's OWN source for real xfail usage. The two regex
    patterns above are deliberately built via string concatenation so that,
    when THIS FILE's own raw source text is later scanned by those same
    patterns, the pattern-definition line itself does not falsely self-match
    (the target call/decorator substrings never appear contiguously in the
    source at that line -- each is split across a string-concatenation
    boundary). No exclusion slicing is needed as a result; verified
    empirically while writing this test."""
    own_text = Path(__file__).read_text(encoding="utf-8")
    call_count = len(_XFAIL_CALL_RE.findall(own_text))
    mark_count = len(_XFAIL_MARK_RE.findall(own_text))
    assert call_count + mark_count == 0, (
        f"This test-only file must not introduce any real xfail usage (found "
        f"{call_count} xfail-call usages and {mark_count} xfail-mark-decorator usages)."
    )


# ---------------------------------------------------------------------------
# 16) This file never writes to any application/template/CSS source path --
#     only Path.read_text(), git show/status/diff (read-only), and its own
#     isolated, temporary test SQLite DB.
# ---------------------------------------------------------------------------


def test_this_file_never_writes_to_application_or_template_or_css_source_paths() -> None:
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
    assert hits == [], (
        f"Unexpected file-write/mutation call trace found in this file (it should only "
        f"read + write to its own isolated temp test DB): {hits!r}"
    )
