"""CSP "Style-3B" low-risk duplicate-`<style>`-block extraction wave -- this
wave's own contract test.

CONTEXT: Style-3B is a coordinated, test-only wave that verifies work already
applied to the working tree: ONE group of 2 templates, both byte-identical
340-line `<style>...</style>` blocks, each replaced with exactly one
`<link rel="stylesheet" href="{{ url_for('static', filename='css/<file>.css') }}">`
pointing at a brand-new shared CSS file:

    app/templates/performance/meeting_development.html
    app/templates/performance/meeting_p3_reminders.html
    -> app/static/css/meeting_development_b_shared.css

HISTORY NOTE -- SCOPE CORRECTION (micro-wave scope exception, user-approved):
the pre-implementation candidate analysis for Style-3B originally identified
4 templates across 2 groups for this "low risk" wave: the 2 above, PLUS
app/templates/executive_summary/daily_weather_mail_tasks.html and
app/templates/communication/daily_weather_mail_settings.html (claimed
byte-identical to each other). Before touching any file, a mandatory
re-verification step (independent of the candidate analysis) proved BOTH of
those two templates are ORPHAN, not active:

  - app/templates/communication/daily_weather_mail_settings.html: the real
    `/communication/daily-weather-mail` GET route
    (app/communication/daily_weather_mail_routes.py::daily_weather_mail_
    settings()) renders a COMPLETELY DIFFERENT template,
    "executive_summary/mail_center/overview.html" -- confirmed by this
    repo's own pre-existing test_csp_wave8_weather_mail_contract.py, whose
    docstring already documents this file as "ORPHAN" (the filename
    coincidentally matches the route's Python FUNCTION name, not its actual
    render target -- two similar but unrelated names).
  - app/templates/executive_summary/daily_weather_mail_tasks.html: its only
    claimed renderer, app/dashboard/executive_summary_routes.py, is never
    imported anywhere in the application (verified with a real, isolated
    `create_app()` subprocess: absent from `sys.modules`, and a repo-wide
    grep for any import of this module returns zero hits outside the file's
    own self-referential logging strings). The SAME
    test_csp_wave8_weather_mail_contract.py's docstring incorrectly labels
    this file "CANLI" (live) based only on source-level decorator evidence
    (a `@route` existing in the file), not on real import/`url_map`
    verification -- that existing claim is WRONG. This is a pre-existing
    test-documentation defect in this repo, independent of and NOT fixed by
    this wave (no application code was changed to investigate or correct
    it; this file only documents the discrepancy for a future, separate
    follow-up).

Because 2 of the original 4 candidate templates are confirmed dead, the user
explicitly narrowed Style-3B's scope to ONLY the meeting_development pair --
below this repo's usual 3-6-template "low risk" floor, approved as a
one-off "Style-3B micro-wave scope exception". The daily_weather_mail pair
was NOT touched in any way (no template edit, no CSS extraction, no route
change) and remains fully out of scope for this wave.

This file writes NOTHING to app/template/CSS/config sources -- only
`Path.read_text()`, `git show`/`git status`/`git diff` (read-only), and real
Flask test-client requests against its own isolated, temporary SQLite DB.

BYTE-PARITY NORMALIZATION: identical methodology to
test_csp_style3a_duplicate_block_extraction_contract.py's own
`_normalize_style_block` (line-based rstrip + leading/trailing empty-line
trim) -- see that file's docstring for the full empirical justification.
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

# The commit immediately BEFORE this wave's own (not-yet-created) commit --
# i.e. the repo state where both templates still had their inline <style>
# block. Fixed, historical; never affected by any later commit.
HEAD_REF = "f37a3132ed88921e8389970a6210489111f18c8a"

GROUP_CSS = "meeting_development_b_shared"

GROUP_TEMPLATES: dict[str, dict[str, str]] = {
    "app/templates/performance/meeting_development.html": {
        "route": "/performance/meeting-development",
        "view_file": "app/performance/meeting_development_routes.py",
        "view_name": "performance_meeting_development",
    },
    "app/templates/performance/meeting_p3_reminders.html": {
        "route": "/performance/meeting-development/faz9",
        "view_file": "app/performance/meeting_p3_reminders_routes.py",
        "view_name": "performance_meeting_p3_reminders",
    },
}

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
#    normalized hash, independently for each template.
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


def test_both_templates_pre_wave_blocks_were_raw_byte_identical_to_each_other() -> None:
    """Independent proof the ORIGINAL duplicate-block claim was correct --
    not just normalize-equal, but byte-for-byte identical before any
    normalization."""
    paths = sorted(GROUP_TEMPLATES)
    raw_blocks = [
        _extract_style_block_text(_git_show(HEAD_REF, p), p) for p in paths
    ]
    assert raw_blocks[0] == raw_blocks[1], (
        f"{paths[0]} and {paths[1]}: pre-wave <style> blocks were not raw "
        "byte-identical at HEAD_REF."
    )


# ---------------------------------------------------------------------------
# 2) The OLD <style> block (at HEAD_REF) was fully static -- no Jinja, no
#    url(), no @media print.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_old_style_block_was_fully_static_no_jinja_no_url_no_print(relative_path: str) -> None:
    old_text = _git_show(HEAD_REF, relative_path)
    old_block = _extract_style_block_text(old_text, relative_path)
    assert "{{" not in old_block, f"{relative_path}: pre-wave <style> block contains a Jinja expression."
    assert "{%" not in old_block, f"{relative_path}: pre-wave <style> block contains a Jinja statement."
    assert "url(" not in old_block, f"{relative_path}: pre-wave <style> block contains a url() reference."
    assert "@media print" not in old_block, f"{relative_path}: pre-wave <style> block contains @media print."


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
#    at the shared CSS file (no duplicates).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_target_template_links_shared_stylesheet_exactly_once(relative_path: str) -> None:
    current_text = _read(relative_path)
    matches = _LINK_STYLESHEET_RE.findall(current_text)
    assert len(matches) == 1, (
        f"{relative_path}: expected exactly one <link rel=\"stylesheet\"> for "
        f"css/{GROUP_CSS}.css, found {len(matches)}."
    )


# ---------------------------------------------------------------------------
# 5) The new shared CSS file exists and its content matches the byte-parity
#    hash independently derived for BOTH templates.
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


# ---------------------------------------------------------------------------
# 6) Route/view function evidence -- grep-based SOURCE evidence that a route
#    decorator + render_template() call referencing the template exists in
#    the claimed view file, AND that the owning module is genuinely imported
#    at startup (not just source-level decorator presence -- see this file's
#    own module docstring history note on why that distinction matters).
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
    basename_with_dir = "/".join(relative_path.split("/")[-2:])  # e.g. "performance/meeting_development.html"
    assert basename_with_dir in body or Path(relative_path).name in body, (
        f"{meta['view_name']}() in {meta['view_file']} does not reference '{relative_path}'."
    )
    assert "render_template(" in body, f"{meta['view_name']}() in {meta['view_file']} has no render_template() call."
    decorator_block = _decorator_block_before(view_file_text, meta["view_name"])
    assert re.search(r"@\w+(?:_bp)?\.route\(", decorator_block), (
        f"{meta['view_name']}() in {meta['view_file']} has no '.route(...)' decorator."
    )
    assert "login_required" in decorator_block, f"{meta['view_name']}() is missing @login_required."
    assert "manager_required" in decorator_block, f"{meta['view_name']}() is missing @manager_required."


# ---------------------------------------------------------------------------
# 7) Real Flask/Jinja render checks via genuine HTTP requests through the
#    ACTUAL route (not a direct render_template() bypass) -- module-scoped
#    isolated Flask app with a real admin user + real login, matching the
#    established Wave2/phase13b/Style-2A/2B/3A fixture pattern (UUID-based
#    temp SQLite, pytest.MonkeyPatch + mp.undo(), WTF_CSRF_ENABLED=False).
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "csp_style3b" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("\u015fablonunda hata var", "\u015fablonu hatal\u0131")
_BASE_TEMPLATE_MARKER = "topbarNotificationBadge"


@pytest.fixture(scope="module")
def style3b_env():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-csp-style3b-contract-min-length-ok")
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
            sicil_no="style3b001",
            email="style3b.contract@ktb.gov.tr",
            ad="Style3B",
            soyad="Kontrat",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("Style3BTestContractKey1!")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    login_response = client.post(
        "/login",
        data={"sicil_or_email": "style3b001", "password": "Style3BTestContractKey1!"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302, f"Test admin login failed: status={login_response.status_code}"
    assert "/login" not in (login_response.headers.get("Location") or ""), (
        "Still redirected to /login after POST -- authentication may have failed."
    )

    yield app, client

    mp.undo()


@pytest.mark.parametrize("relative_path", sorted(GROUP_TEMPLATES))
def test_template_route_renders_successfully_via_real_http_get(style3b_env, relative_path: str) -> None:
    """Real end-to-end HTTP GET through the actual registered route (not a
    render_template() bypass) -- both context builders (build_meeting_
    development_context / build_p3_reminders_context) guard every DB query
    with `_has_table(...)`, so they run cleanly against a freshly-created,
    empty schema."""
    _app, client = style3b_env
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
        assert ".bys-rem-shell" not in style_match.group(1), (
            f"{meta['route']}: the extracted CSS's own selector is still duplicated inline "
            "in a <style> block on the rendered page."
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
#    global <style> block total dropped by EXACTLY 2.
# ---------------------------------------------------------------------------

# BYS360 KOORDINATOR DUZELTMESI: was 1060/252 as of Style-3B's own closure.
# A later, unrelated wave (BYS360 Daily Weather/Mail Orphan Template
# Temizliği) deleted 4 more confirmed-orphan templates, removing 20 more
# static style="..." attributes and 4 more <style> blocks: 1060 - 20 = 1040,
# 252 - 4 = 248. A further later wave (BYS360 Executive Summary Artık
# Servis/Template Temizliği) deleted 1 more confirmed-orphan template
# (app/templates/dashboard/executive_summary.html), removing 3 more static
# style="..." attributes and 1 more <style> block: 1040 - 3 = 1037,
# 248 - 1 = 247. A further later wave (BYS360 Workflow Orphan Presentation
# Subsystem Temizliği) deleted 14 more confirmed-orphan templates (2 full
# trees of 7), removing 2 more static style="..." attributes, 2 dynamic
# style="..." attributes, and 14 more <style> blocks: 1037 - 2 = 1035,
# 66 - 2 = 64, 247 - 14 = 233. See tests/security/test_csp_style_migration_
# cumulative_inventory_contract.py's
# DELETED_TEMPLATE_WAVES["daily_weather_mail_cleanup"],
# DELETED_TEMPLATE_WAVES["executive_summary_dashboard_cleanup"], and
# DELETED_TEMPLATE_WAVES["workflow_orphan_presentation_cleanup"]. A further
# later wave (style3c_meeting_family_group_a) extracted 8 more <style> blocks
# from 8 active templates (no static/dynamic attributes touched): 233 - 8 =
# 225. See that same ledger file's
# STYLE_MIGRATION_WAVES["style3c_meeting_family_group_a"]. A further,
# unrelated later wave (weights_orphan_template_cleanup) deleted the orphan
# app/templates/weights.html, which independently carried its own one static
# style="..." attribute and one <style> block: 1035 - 1 = 1034, 225 - 1 = 224.
# See that same ledger file's FORWARD-COMPATIBILITY FOLLOW-UP 7. A further,
# unrelated later wave (weight_create_edit_orphan_cleanup) deleted the two
# sibling orphans app/templates/weight_create.html and
# app/templates/weight_edit.html, each independently carrying one static
# style="..." attribute and one <style> block: 1034 - 2 = 1032, 224 - 2 = 222.
# See that same ledger file's FORWARD-COMPATIBILITY FOLLOW-UP 8. A further,
# unrelated later wave (BYS360 Settings Center V2) added 4 new templates,
# but their CSS is an external stylesheet with no inline style="..."
# attributes or <style> blocks -- 0 contribution, totals remain 1032/222.
# See that same ledger file's FORWARD-COMPATIBILITY FOLLOW-UP 9.
EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3B = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3B = 64
EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3B = 221


def test_repo_wide_active_and_dynamic_style_attribute_totals_are_unchanged() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3B, (
        f"Repo-wide active (static) style attribute total is "
        f"{inventory.active_static_total}; expected "
        f"{EXPECTED_ACTIVE_STYLE_TOTAL_AFTER_STYLE3B} (unchanged -- Style-3B must not "
        "touch any style=\"...\" attribute)."
    )
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3B, (
        f"Repo-wide Jinja-dynamic style attribute total is {inventory.dynamic_total}; "
        f"expected {EXPECTED_DYNAMIC_STYLE_TOTAL_AFTER_STYLE3B} (unchanged)."
    )


def test_repo_wide_style_block_total_dropped_by_exactly_2() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3B, (
        f"Repo-wide <style> block total is {inventory.style_block_total}; expected "
        f"254 - 2 = {EXPECTED_STYLE_BLOCK_TOTAL_AFTER_STYLE3B} (Style-3B removed "
        "exactly one <style> block from each of its 2 templates and added none)."
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
#     wave should not have touched app/static/pwa/ at all.
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
        f"app/static/pwa/ has uncommitted changes; Style-3B must not touch it:\n{result.stdout}"
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
        f"service-worker.js/sw.js has uncommitted changes; Style-3B must not touch it:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# 12) Plan-scope guard: this wave's OWN closure commit range touches ONLY
#     the 2 templates + the new CSS file under app/templates/ and
#     app/static/css/ -- nothing else, and specifically NOT the two
#     confirmed-orphan daily_weather_mail files.
#
#     BYS360 KOORDINATOR DUZELTMESI: bu test ilk yazildiginda HENUZ
#     commit'lenmemis calisma agacini `git diff HEAD` ile kontrol
#     ediyordu -- bu, Style-3B HENUZ commit'lenmemisken DOGRUYDU. Style-3B
#     commit'lendikten (1d20cde) SONRA, bir SONRAKI dalga (BYS360 Daily
#     Weather/Mail Orphan Template Temizligi) app/templates/ altinda 4 daha
#     dosya sildi -- bu, "HEAD"'e karsi live diff kontrolunun artik
#     Style-3B'nin KENDI degisikligini degil, SONRAKI dalganin degisikligini
#     de gormesine yol aciyordu (sahte FAIL). Ayni sinif hata, Style-3A'nin
#     kendi HEAD_REF/STYLE3A_CLOSURE_REF KOORDINATOR NOTU'nda ve bu dosyanin
#     kendi list_users sozlesme dosyasinda daha once de gorulmustu. Artik
#     SABIT, Style-3B'nin KENDI commit araligina (HEAD_REF..STYLE3B_CLOSURE_
#     REF) kilitlendi -- bu, "Style-3B hicbir sey degistirmedi" iddiasini
#     SONSUZA KADAR dogru sekilde kanitlar, sonraki hicbir commit/dalgadan
#     (ornegin 4 orphan daily-weather-mail template'ini silen commit'ten)
#     etkilenmez.
# ---------------------------------------------------------------------------

STYLE3B_CLOSURE_REF = "1d20cdeffdd1f20fe24c3f5414fa5d7ba498df47"  # Style-3B'nin KENDI kapanis commit'i


def test_style3b_closure_commit_scoped_to_wave_files_only() -> None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI not available in this environment.")

    result = subprocess.run(
        [
            "git", "-C", str(REPO_ROOT), "diff", "--name-status",
            f"{HEAD_REF}..{STYLE3B_CLOSURE_REF}", "--", "app/templates/", "app/static/css/",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"'git diff --name-status' failed: {result.stderr!r}"

    expected_modified = set(GROUP_TEMPLATES)
    expected_added = {f"app/static/css/{GROUP_CSS}.css"}
    orphan_files_must_not_appear = {
        "app/templates/executive_summary/daily_weather_mail_tasks.html",
        "app/templates/communication/daily_weather_mail_settings.html",
    }

    modified: set[str] = set()
    added: set[str] = set()
    unexpected: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code, path = parts[0].strip(), parts[-1].replace("\\", "/")
        if code == "M" and path in expected_modified:
            modified.add(path)
        elif code == "A" and path in expected_added:
            added.add(path)
        else:
            unexpected.append(f"{code} {path}")

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
    for orphan in orphan_files_must_not_appear:
        assert orphan not in modified and orphan not in added, (
            f"{orphan} appears in this wave's diff -- it is a confirmed orphan and must "
            "remain completely untouched by Style-3B."
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
