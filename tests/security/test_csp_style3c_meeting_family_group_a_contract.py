"""CSP "Style-3C" active meeting-family duplicate-`<style>`-block extraction
wave -- this wave's own contract test.

CONTEXT: Style-3C is a coordinated, test-only wave that verifies work already
applied to the working tree: ONE group of 8 templates, all raw-byte-identical
387-line `<style>...</style>` blocks, each replaced with exactly one
`<link rel="stylesheet" href="{{ url_for('static', filename='css/<file>.css') }}">`
pointing at a brand-new shared CSS file:

    app/templates/performance/meeting_development_faz3.html
    app/templates/performance/meeting_development_faz4.html
    app/templates/performance/meeting_development_scenarios.html
    app/templates/performance/meeting_final_closure.html
    app/templates/performance/meeting_p0_completion.html
    app/templates/performance/meeting_p1_scope.html
    app/templates/performance/meeting_p2_archive_notes.html
    app/templates/performance/meeting_rule_enforcement.html
    -> app/static/css/meeting_development_c_shared.css

NAMING NOTE: the coordinator's original suggested filename was
`meeting_development_group_a_shared.css`. This repo already has a
`meeting_development_b_shared.css` (Style-3B's own 2-template shared file,
see test_csp_style3b_low_risk_duplicate_extraction_contract.py) -- the
established convention in this template family is a single-letter suffix,
not a "group_a"/"group_b" pair (which would also collide in spirit with
Style-3A's own, unrelated, already-reverted "Group A" executive-mail naming
from a completely different template family -- see that file's own module
docstring HISTORY NOTE). `meeting_development_c_shared.css` (the next letter
after "_b") was used instead to stay consistent with the one real precedent
in this repo and avoid reusing a name history already retired.

All 8 templates are independently confirmed runtime-ACTIVE below (section 6):
each has its own `app/performance/<name>_routes.py` module registered in
`app/performance/__init__.py::OPTIONAL_ROUTE_MODULES`, a real `@main_bp.route`
GET endpoint guarded by `@login_required` + `@manager_required`, and a real
`render_template()` call referencing the template.

This file writes NOTHING to app/template/CSS/config sources -- only
`Path.read_text()`, `git show`/`git status`/`git diff` (read-only), and real
Flask test-client requests against its own isolated, temporary SQLite DB.

BYTE-PARITY NORMALIZATION: identical methodology to
test_csp_style3a_duplicate_block_extraction_contract.py's own
`_normalize_style_block` (line-based rstrip + leading/trailing empty-line
trim) -- see that file's docstring for the full empirical justification.

HEAD_REF: a fixed, historical commit SHA (not the literal string "HEAD") --
the tip of `phase5-critical-lint-clean-v1` immediately before this wave's own
templates/CSS/test changes were written. Using a pinned SHA rather than
"HEAD" means the pre-wave byte-parity evidence below stays correct forever,
even after this wave's own commit lands and later, unrelated commits are
added on top -- see test_csp_style3a_duplicate_block_extraction_contract.py's
own module docstring "BYS360 KOORDINATOR DUZELTMESI" note for the full
history of why this matters in this repo.
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

# Tip of phase5-critical-lint-clean-v1 immediately before Style-3C's own
# template/CSS/test changes -- the repo state where all 8 templates still
# carried their inline <style> block. Fixed, historical; never affected by
# any later commit.
HEAD_REF = "7a605b228ab27f0b7048391ff9a672b9e9ee5d33"

GROUP_CSS = "meeting_development_c_shared"

GROUP_TEMPLATES: dict[str, dict[str, str]] = {
    "app/templates/performance/meeting_development_faz3.html": {
        "route": "/performance/meeting-development/faz3",
        "view_file": "app/performance/meeting_development_faz3_routes.py",
        "view_name": "performance_meeting_development_faz3",
    },
    "app/templates/performance/meeting_development_faz4.html": {
        "route": "/performance/meeting-development/final-gate",
        "view_file": "app/performance/meeting_development_faz4_routes.py",
        "view_name": "performance_meeting_final_gate",
    },
    "app/templates/performance/meeting_development_scenarios.html": {
        "route": "/performance/meeting-development/test-scenarios",
        "view_file": "app/performance/meeting_test_routes.py",
        "view_name": "performance_meeting_test_scenarios",
    },
    "app/templates/performance/meeting_final_closure.html": {
        "route": "/performance/meeting-development/final-closure",
        "view_file": "app/performance/meeting_final_closure_routes.py",
        "view_name": "performance_meeting_final_closure",
    },
    "app/templates/performance/meeting_p0_completion.html": {
        "route": "/performance/meeting-development/p0",
        "view_file": "app/performance/meeting_p0_completion_routes.py",
        "view_name": "performance_meeting_p0_completion",
    },
    "app/templates/performance/meeting_p1_scope.html": {
        "route": "/performance/meeting-development/p1",
        "view_file": "app/performance/meeting_p1_scope_routes.py",
        "view_name": "performance_meeting_p1_scope",
    },
    "app/templates/performance/meeting_p2_archive_notes.html": {
        "route": "/performance/meeting-development/p2",
        "view_file": "app/performance/meeting_p2_archive_notes_routes.py",
        "view_name": "performance_meeting_p2_archive_notes",
    },
    "app/templates/performance/meeting_rule_enforcement.html": {
        "route": "/performance/meeting-development/rules",
        "view_file": "app/performance/meeting_rule_enforcement_routes.py",
        "view_name": "performance_meeting_rule_enforcement",
    },
}
assert len(GROUP_TEMPLATES) == 8

_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_STYLE_TAG_RE = re.compile(r"<style\b", re.IGNORECASE)
_LINK_STYLESHEET_RE = re.compile(
    r"""<link\s+rel=["']stylesheet["']\s+href=["']\{\{\s*url_for\(\s*"""
    r"""["']static["']\s*,\s*filename=["']css/""" + re.escape(GROUP_CSS) + r"""\.css["']\s*\)\s*\}\}["']\s*/?>"""
)


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
# 1) Byte-parity proof: the OLD <style> block content (at HEAD_REF, before
#    this wave) normalized-hashes identically to the NEW shared CSS file's
#    normalized hash, independently for each of the 8 templates.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_old_style_block_byte_parity_with_new_css_file(relative_path: str) -> None:
    old_text = _git_show(HEAD_REF, relative_path)
    old_block = _extract_style_block_text(old_text, relative_path)
    new_css_text = _css_path(GROUP_CSS).read_text(encoding="utf-8")

    old_hash = _sha256_of_normalized(old_block)
    new_hash = _sha256_of_normalized(new_css_text)
    assert old_hash == new_hash, (
        f"{relative_path}: normalized SHA-256 of the pre-wave <style> block "
        f"({old_hash}) does not match the normalized SHA-256 of "
        f"app/static/css/{GROUP_CSS}.css ({new_hash})."
    )


def test_all_eight_templates_pre_wave_blocks_were_raw_byte_identical_to_each_other() -> None:
    """Independent proof the ORIGINAL duplicate-block claim was correct --
    not just normalize-equal, but byte-for-byte identical before any
    normalization, across all 8 templates (not merely pairwise)."""
    paths = sorted(GROUP_TEMPLATES)
    raw_blocks = {p: _extract_style_block_text(_git_show(HEAD_REF, p), p) for p in paths}
    first_path = paths[0]
    first_block = raw_blocks[first_path]
    mismatches = [p for p in paths[1:] if raw_blocks[p] != first_block]
    assert mismatches == [], (
        f"Templates whose pre-wave <style> block was NOT raw byte-identical to "
        f"{first_path}'s: {mismatches!r}"
    )


def test_pre_wave_block_line_count_is_387() -> None:
    old_text = _git_show(HEAD_REF, "app/templates/performance/meeting_development_faz3.html")
    old_block = _extract_style_block_text(
        old_text, "app/templates/performance/meeting_development_faz3.html"
    )
    line_count = old_block.count("\n") + 1
    assert line_count == 387, f"Expected pre-wave <style> block to be 387 lines, found {line_count}."


# ---------------------------------------------------------------------------
# 2) The OLD <style> block (at HEAD_REF) was fully static -- no Jinja, no
#    url(), no @media print, no @font-face, no !important-driven data
#    dependency.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_old_style_block_was_fully_static(relative_path: str) -> None:
    old_text = _git_show(HEAD_REF, relative_path)
    old_block = _extract_style_block_text(old_text, relative_path)
    assert "{{" not in old_block, f"{relative_path}: pre-wave <style> block contains a Jinja expression."
    assert "{%" not in old_block, f"{relative_path}: pre-wave <style> block contains a Jinja statement."
    assert "url(" not in old_block, f"{relative_path}: pre-wave <style> block contains a url() reference."
    assert "@media print" not in old_block, f"{relative_path}: pre-wave <style> block contains @media print."
    assert "@font-face" not in old_block, f"{relative_path}: pre-wave <style> block contains @font-face."


# ---------------------------------------------------------------------------
# 3) The CURRENT (post-wave) template source has ZERO <style> blocks.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_target_template_now_has_zero_style_blocks(relative_path: str) -> None:
    current_text = _read(relative_path)
    count = len(_STYLE_TAG_RE.findall(current_text))
    assert count == 0, f"{relative_path}: expected 0 <style> blocks post-wave, found {count}."


# ---------------------------------------------------------------------------
# 4) Each template contains EXACTLY ONE <link rel="stylesheet" ...> pointing
#    at the shared CSS file (no duplicates), and no OTHER template in the
#    repo accidentally links this wave's CSS file.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_target_template_links_shared_stylesheet_exactly_once(relative_path: str) -> None:
    current_text = _read(relative_path)
    matches = _LINK_STYLESHEET_RE.findall(current_text)
    assert len(matches) == 1, (
        f"{relative_path}: expected exactly one <link rel=\"stylesheet\"> for "
        f"css/{GROUP_CSS}.css, found {len(matches)}."
    )


def test_no_other_template_in_the_repo_links_this_waves_css_file() -> None:
    scope_roots = [REPO_ROOT / "app" / "templates", REPO_ROOT / "app" / "workflow" / "templates"]
    modules_root = REPO_ROOT / "app" / "modules"
    if modules_root.is_dir():
        scope_roots.extend(p for p in modules_root.glob("*/templates") if p.is_dir())

    offenders: list[str] = []
    expected = {str((REPO_ROOT / p).resolve()) for p in GROUP_TEMPLATES}
    for root in scope_roots:
        for html_path in root.rglob("*.html"):
            resolved = str(html_path.resolve())
            text = html_path.read_text(encoding="utf-8", errors="replace")
            if _LINK_STYLESHEET_RE.search(text) and resolved not in expected:
                offenders.append(str(html_path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        f"Template(s) outside this wave's own 8-template group unexpectedly link "
        f"css/{GROUP_CSS}.css: {offenders!r}"
    )


# ---------------------------------------------------------------------------
# 5) The new shared CSS file exists and its content matches the byte-parity
#    hash independently derived for ALL 8 templates.
# ---------------------------------------------------------------------------


def test_group_css_file_exists_and_matches_every_member_template() -> None:
    css_path = _css_path(GROUP_CSS)
    assert css_path.is_file(), f"{css_path} does not exist."
    css_hash = _sha256_of_normalized(css_path.read_text(encoding="utf-8"))
    for relative_path in sorted(GROUP_TEMPLATES):
        old_block = _extract_style_block_text(_git_show(HEAD_REF, relative_path), relative_path)
        assert _sha256_of_normalized(old_block) == css_hash, (
            f"{relative_path}'s pre-wave <style> block does not match "
            f"app/static/css/{GROUP_CSS}.css."
        )


def test_css_content_has_no_jinja_url_or_print_dependency() -> None:
    css_text = _css_path(GROUP_CSS).read_text(encoding="utf-8")
    assert "{{" not in css_text
    assert "{%" not in css_text
    assert "url(" not in css_text
    assert "@media print" not in css_text
    assert "@font-face" not in css_text


# ---------------------------------------------------------------------------
# 6) Route/view function evidence -- grep-based SOURCE evidence that a route
#    decorator + render_template() call referencing the template exists in
#    the claimed view file, AND that the owning module is genuinely
#    registered for import at startup via
#    app/performance/__init__.py::OPTIONAL_ROUTE_MODULES (not just
#    source-level decorator presence).
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


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_template_has_route_and_render_evidence_in_owning_file(relative_path: str) -> None:
    meta = GROUP_TEMPLATES[relative_path]
    view_file_text = (REPO_ROOT / meta["view_file"]).read_text(encoding="utf-8")
    body = _extract_function_body(view_file_text, meta["view_name"])
    basename = Path(relative_path).name
    assert basename in body, f"{meta['view_name']}() in {meta['view_file']} does not reference '{basename}'."
    assert "render_template(" in body, f"{meta['view_name']}() in {meta['view_file']} has no render_template() call."
    decorator_block = _decorator_block_before(view_file_text, meta["view_name"])
    assert re.search(r"@\w+(?:_bp)?\.route\(", decorator_block), (
        f"{meta['view_name']}() in {meta['view_file']} has no '.route(...)' decorator."
    )
    assert "login_required" in decorator_block, f"{meta['view_name']}() is missing @login_required."
    assert "manager_required" in decorator_block, f"{meta['view_name']}() is missing @manager_required."


def test_all_eight_route_modules_are_registered_in_optional_route_modules() -> None:
    init_text = (REPO_ROOT / "app" / "performance" / "__init__.py").read_text(encoding="utf-8")
    expected_modules = {Path(meta["view_file"]).stem for meta in GROUP_TEMPLATES.values()}
    missing = [m for m in expected_modules if f'"{m}"' not in init_text]
    assert missing == [], (
        f"Route module(s) not found in app/performance/__init__.py's "
        f"OPTIONAL_ROUTE_MODULES: {missing!r}"
    )


# ---------------------------------------------------------------------------
# 7) Real Flask/Jinja render checks via genuine HTTP requests through the
#    ACTUAL route (not a direct render_template() bypass) -- module-scoped
#    isolated Flask app with a real admin user + real login, matching the
#    established Wave2/phase13b/Style-2A/2B/3A/3B fixture pattern (UUID-based
#    temp SQLite, pytest.MonkeyPatch + mp.undo(), WTF_CSRF_ENABLED=False).
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "csp_style3c" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("\u015fablonunda hata var", "\u015fablonu hatal\u0131")
_BASE_TEMPLATE_MARKER = "topbarNotificationBadge"


@pytest.fixture(scope="module")
def style3c_env():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-csp-style3c-contract-min-length-ok")
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
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db
    from app.models import User
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
        user = User(
            sicil_no="style3c001",
            email="style3c.contract@ktb.gov.tr",
            ad="Style3C",
            soyad="Kontrat",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("Style3CTestContractKey1!")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    login_response = client.post(
        "/login",
        data={"sicil_or_email": "style3c001", "password": "Style3CTestContractKey1!"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302, f"Test admin login failed: status={login_response.status_code}"
    assert "/login" not in (login_response.headers.get("Location") or ""), (
        "Still redirected to /login after POST -- authentication may have failed."
    )

    yield app, client

    mp.undo()


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_template_route_renders_successfully_via_real_http_get(style3c_env, relative_path: str) -> None:
    _app, client = style3c_env
    meta = GROUP_TEMPLATES[relative_path]
    response = client.get(meta["route"], follow_redirects=True)
    assert response.status_code == 200, (
        f"{meta['route']} ({relative_path}) returned unexpected status {response.status_code}."
    )
    body = response.get_data(as_text=True)
    assert f"css/{GROUP_CSS}.css" in body, f"{meta['route']}: response does not reference css/{GROUP_CSS}.css."
    assert _BASE_TEMPLATE_MARKER in body, f"{meta['route']}: response missing base.html's own marker."
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, f"{meta['route']}: response looks like a safe_render() fallback stub."
    # base.html (extended by every page) legitimately carries its own,
    # unrelated <style> blocks -- so this checks that the EXTRACTED CSS's
    # own distinctive selector is not ALSO duplicated inline (i.e. the link
    # tag is the only place this content appears), not that <style> is
    # absent from the page entirely.
    for style_match in re.finditer(r"<style\b[^>]*>(.*?)</style>", body, re.IGNORECASE | re.DOTALL):
        assert ".bys-md-shell" not in style_match.group(1), (
            f"{meta['route']}: the extracted CSS's own selector is still duplicated inline "
            "in a <style> block on the rendered page."
        )


def test_static_css_file_is_served_with_200(style3c_env) -> None:
    _app, client = style3c_env
    response = client.get(f"/static/css/{GROUP_CSS}.css")
    assert response.status_code == 200, (
        f"/static/css/{GROUP_CSS}.css returned unexpected status {response.status_code}."
    )


# ---------------------------------------------------------------------------
# 8) Repo-wide inline-handler / javascript: URL counts are still 0.
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
# 9) Global active/dynamic style ATTRIBUTE totals unchanged (this wave only
#    touched <style> BLOCKS, never style="..." attributes anywhere) --
#    global <style> block total dropped by EXACTLY 8 (233 -> 225). See
#    tests/security/test_csp_style_migration_cumulative_inventory_contract.py
#    ::STYLE_MIGRATION_WAVES["style3c_meeting_family_group_a"] for the
#    manifest entry this cross-checks against. A further, unrelated later
#    wave (weights_orphan_template_cleanup) deleted the orphan
#    app/templates/weights.html, which independently carried its own one
#    static style="..." attribute and one <style> block: 1035 - 1 = 1034,
#    225 - 1 = 224. See that same ledger file's FORWARD-COMPATIBILITY
#    FOLLOW-UP 7. A further, unrelated later wave
#    (weight_create_edit_orphan_cleanup) deleted the two sibling orphans
#    app/templates/weight_create.html and app/templates/weight_edit.html,
#    each independently carrying one static style="..." attribute and one
#    <style> block: 1034 - 2 = 1032, 224 - 2 = 222. See that same ledger
#    file's FORWARD-COMPATIBILITY FOLLOW-UP 8. A further, unrelated later
#    wave (BYS360 Settings Center V2) added 4 new templates, but their CSS
#    is an external stylesheet with no inline style="..." attributes or
#    <style> blocks -- 0 contribution, totals remain 1032/222. See that
#    same ledger file's FORWARD-COMPATIBILITY FOLLOW-UP 9.
# ---------------------------------------------------------------------------

EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3C = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3C = 64
EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3C = 221


def test_repo_wide_active_and_dynamic_style_attribute_totals_are_unchanged() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3C, (
        f"Repo-wide active (static) style attribute total is "
        f"{inventory.active_static_total}; expected "
        f"{EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3C} (unchanged -- Style-3C must not "
        "touch any style=\"...\" attribute)."
    )
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3C, (
        f"Repo-wide Jinja-dynamic style attribute total is {inventory.dynamic_total}; "
        f"expected {EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3C} (unchanged)."
    )


def test_repo_wide_style_block_total_dropped_by_exactly_8() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3C, (
        f"Repo-wide <style> block total is {inventory.style_block_total}; expected "
        f"233 - 8 = {EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3C} (Style-3C removed "
        "exactly one <style> block from each of its 8 templates and added none)."
    )


# ---------------------------------------------------------------------------
# 10) CSP header style directives are byte-identical to Style-1's end state,
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
# 11) Static PWA/service-worker files are byte-identical to git HEAD -- this
#     wave should not have touched app/static/pwa/ or service-worker files
#     at all.
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
        f"app/static/pwa/ has uncommitted changes; Style-3C must not touch it:\n{result.stdout}"
    )


def test_service_worker_files_are_untouched_by_this_wave() -> None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI not available in this environment.")

    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--stat", "HEAD", "--", "service-worker.js", "sw.js"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"'git diff --stat' failed: {result.stderr!r}"
    assert result.stdout.strip() == "", (
        f"service-worker.js/sw.js has uncommitted changes; Style-3C must not touch it:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# 12) Plan-scope guard: a FIXED two-ref range (HEAD_REF..STYLE3C_CLOSURE_REF)
#     touches ONLY the 8 templates + the new CSS file under app/templates/
#     and app/static/css/ -- nothing else.
#
#     KOORDINATOR DUZELTMESI: this test originally used a single-ref
#     `git diff --name-status HEAD_REF` (pre-wave ref vs. CURRENT worktree/
#     index) plus a live `git status --porcelain` fallback for the
#     not-yet-committed CSS file. That was correct only up until Style-3C's
#     own commit landed -- exactly the same class of bug already documented
#     in test_csp_style3a_duplicate_block_extraction_contract.py's and
#     test_csp_style3b_low_risk_duplicate_extraction_contract.py's own
#     "KOORDINATOR DUZELTMESI" notes (this test's own prior docstring even
#     predicted it: "if a LATER, unrelated wave touches app/templates/ ...
#     this test would need that same follow-up correction then"). The later,
#     unrelated "BYS360 Duplicate Template Dalga 1" wave (9 confirmed-orphan
#     template deletions, none of them Style-3C's own 8 templates) did touch
#     app/templates/ again, which made the single-ref live-diff form report
#     those 9 unrelated deletions as "unexpected changes" under this test's
#     scope. Fixed the same way as Style-3A/3B: pinned BOTH ends to fixed,
#     historical refs -- STYLE3C_CLOSURE_REF is Style-3C's own already-
#     pushed closure commit, so this range can never again see any later
#     wave's changes, no matter how many more land under app/templates/.
# ---------------------------------------------------------------------------

STYLE3C_CLOSURE_REF = "d4ee2043931b37cef6df2ceef898094e0eebb04d"  # Style-3C'nin KENDI kapanis commit'i


def test_style3c_diff_scoped_to_wave_files_only() -> None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI not available in this environment.")

    diff_result = subprocess.run(
        [
            "git", "-C", str(REPO_ROOT), "diff", "--name-status",
            f"{HEAD_REF}..{STYLE3C_CLOSURE_REF}", "--", "app/templates/", "app/static/css/",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert diff_result.returncode == 0, f"'git diff --name-status' failed: {diff_result.stderr!r}"

    expected_modified = set(GROUP_TEMPLATES)
    expected_added = {f"app/static/css/{GROUP_CSS}.css"}

    modified: set[str] = set()
    added: set[str] = set()
    unexpected: list[str] = []
    for line in diff_result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code, path = parts[0].strip(), parts[-1].replace("\\", "/")
        if code == "M" and path in expected_modified:
            modified.add(path)
        elif code == "A" and path in expected_added:
            added.add(path)
        else:
            unexpected.append(f"diff:{code} {path}")

    assert unexpected == [], (
        f"Unexpected changes under app/templates/ or app/static/css/ outside this "
        f"wave's own footprint: {unexpected!r}"
    )
    assert modified == expected_modified, (
        f"Modified-template set does not match: missing={expected_modified - modified!r}, "
        f"extra={modified - expected_modified!r}"
    )
    assert added == expected_added, (
        f"New CSS file set does not match: missing={expected_added - added!r}, extra={added - expected_added!r}"
    )


# ---------------------------------------------------------------------------
# 13) No new xfail introduced by this file.
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
# 14) This file never writes to any application/template/CSS source path --
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
