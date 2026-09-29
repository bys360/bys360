"""BYS360 Meeting Development P0 Navigation -- real navigation/visibility contract.

CONTEXT: a prior audit (`test_meeting_final_gate_ui_context_adapter_contract.py`'s
own "CRITICAL FINDING") established that a real, isolated
`build_final_gate_context()` call reported 9 real errors: 4 Meeting
Development screens -- Toplantı Geliştirme (`main.performance_meeting_
development`), Toplantı Testleri (`main.performance_meeting_test_scenarios`),
Toplantı Derinleştirme (`main.performance_meeting_development_faz3`) and
Final Kontrol (`main.performance_meeting_final_gate`) -- were fully built,
routed and auth-protected (`@login_required` + `@manager_required` on every
one of them), but had ZERO navigation entry point anywhere in the app:
`app/templates/base.html` never rendered a sidebar link for any of the 4,
and `app/menu_registry.py` never declared any of the 4 menu keys. This is
exactly the class of defect `REQUIRED_TOKENS` in `app/services/performance/
meeting_development_final_gate.py` exists to catch (5 missing base.html
tokens + 4 missing menu_registry.py tokens = 9).

A navigation-wiring wave then wired all 4 screens into the REAL navigation/
visibility system -- `app/templates/base.html`, `app/menu_registry.py`,
`app/menu_registry_data_sections.py`, `app/menu_registry_data_performance.py`,
`app/live_scope.py`, `app/services/settings/effective_menu_parts/*.py`,
`app/services/role_matrix_ui_service.py` and `app/main_handlers/account_
communication_helpers.py` -- mirroring, key-for-key and role-for-role, the
exact same mechanism already used by two working sibling screens:
`performance_meeting_p3_reminders` (Hatırlatma ve Aksatan Amirler,
`main.performance_meeting_p3_reminders`, `/performance/meeting-development/
faz9`) and `performance_development_guidance` (Gelişim Rehberi, `main.
performance_meeting_p4_development_guidance`, `/performance/meeting-
development/faz10`). No new route was added and no auth behavior was
changed -- only navigation/visibility registrations. This file is that
wave's own regression contract: it proves the real, unmocked `build_final_
gate_context()` no longer reports those 9 errors, that the 4 screens are
now genuinely reachable (real url_map, real `build_menu_visibility_map()`,
real authenticated GET, real rendered sidebar HTML) for manager-family
roles and genuinely hidden for `personel`, that unauthenticated access is
still gated exactly as before (302 -> `/login`, not weakened to a 404/403
or strengthened/broken in any other way), and that the two ground-truth
sibling screens the new wiring was modeled on were not disturbed by this
wave.

`PRE_WAVE_REF` (`a752c5d31655c65fd42d99f0152c6fef962d3ce9`) is this
worktree's own current HEAD -- i.e. the tip immediately BEFORE the
navigation-wiring wave's own (still uncommitted at the time this file was
written) changes. All 13 changed files listed above are staged only in the
working tree, never committed to that ref, so `git show <ref>:<path>`
against it is a stable, historical comparison point for the "untouched by
this wave" assertions below (the Final Gate/P0 templates and the other 6
meeting-family templates), independent of whether this wave's changes have
since been committed on top of it.

This file uses real, isolated Flask apps (module-scoped, UUID-based temp
SQLite under `C:/bys360/audit_tmp/meeting_dev_nav_fix/test_dbs`, matching
this repo's established fixture pattern) and real ORM writes -- never
string-interpolated SQL, never `|safe`.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

BASE_TEMPLATE_FILE = "app/templates/base.html"
MENU_REGISTRY_FILE = "app/menu_registry.py"
P0_TEMPLATE_FILE = "app/templates/performance/meeting_p0_completion.html"
FINAL_GATE_TEMPLATE_FILE = "app/templates/performance/meeting_development_faz4.html"
OTHER_SIX_MEETING_TEMPLATES: tuple[str, ...] = (
    "app/templates/performance/meeting_development_faz3.html",
    "app/templates/performance/meeting_development_scenarios.html",
    "app/templates/performance/meeting_final_closure.html",
    "app/templates/performance/meeting_p1_scope.html",
    "app/templates/performance/meeting_p2_archive_notes.html",
    "app/templates/performance/meeting_rule_enforcement.html",
)

# This worktree's own current HEAD -- the tip immediately before the
# navigation-wiring wave's own (uncommitted at authoring time) changes. See
# module docstring for why this is stable regardless of later commits.
PRE_WAVE_REF = "a752c5d31655c65fd42d99f0152c6fef962d3ce9"

MANAGER_FAMILY_ROLES = frozenset(
    {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"}
)

# The 4 newly-wired Meeting Development screens (label/key/endpoint/url taken
# directly from this wave's own task spec, independently re-verified against
# the real route decorators in app/performance/meeting_development_routes.py,
# meeting_test_routes.py, meeting_development_faz3_routes.py and
# meeting_development_faz4_routes.py, and against the real url_map below).
SCREENS: tuple[dict[str, Any], ...] = (
    {
        "label": "Toplantı Geliştirme",
        "key": "performance_meeting_development",
        "endpoint": "main.performance_meeting_development",
        "url": "/performance/meeting-development",
    },
    {
        "label": "Toplantı Testleri",
        "key": "performance_meeting_test_scenarios",
        "endpoint": "main.performance_meeting_test_scenarios",
        "url": "/performance/meeting-development/test-scenarios",
    },
    {
        "label": "Toplantı Derinleştirme",
        "key": "performance_meeting_development_faz3",
        "endpoint": "main.performance_meeting_development_faz3",
        "url": "/performance/meeting-development/faz3",
    },
    {
        "label": "Final Kontrol",
        "key": "performance_meeting_final_gate",
        "endpoint": "main.performance_meeting_final_gate",
        "url": "/performance/meeting-development/final-gate",
    },
)
SCREEN_KEYS: tuple[str, ...] = tuple(screen["key"] for screen in SCREENS)

# The 2 working, ground-truth sibling screens this wave's wiring mechanism
# was modeled on -- a regression guard proving this wave did not disturb the
# pre-existing, already-correct pattern while extending it.
SIBLING_SCREENS: tuple[dict[str, Any], ...] = (
    {
        "label": "Hatırlatma ve Aksatan Amirler",
        "key": "performance_meeting_p3_reminders",
        "endpoint": "main.performance_meeting_p3_reminders",
        "url": "/performance/meeting-development/faz9",
    },
    {
        "label": "Gelişim Rehberi",
        "key": "performance_development_guidance",
        "endpoint": "main.performance_meeting_p4_development_guidance",
        "url": "/performance/meeting-development/faz10",
    },
)

# The 9 original, literal error strings `build_final_gate_context()` used to
# emit (5 missing app/templates/base.html tokens + 4 missing app/menu_
# registry.py tokens -- see REQUIRED_TOKENS in app/services/performance/
# meeting_development_final_gate.py and its `f"Eksik işaret: {rel} -> {token}"`
# format). Hardcoded historically (not re-derived from the live REQUIRED_
# TOKENS dict) so this regression check keeps meaning what it says even if
# REQUIRED_TOKENS itself is edited later. Independently verified absent from
# `git show a752c5d3:...` pre-wave and present in the current working files.
ORIGINAL_NINE_ERROR_MESSAGES: tuple[str, ...] = (
    "Eksik işaret: app/templates/base.html -> Toplantı Geliştirme",
    "Eksik işaret: app/templates/base.html -> Toplantı Testleri",
    "Eksik işaret: app/templates/base.html -> Toplantı Derinleştirme",
    "Eksik işaret: app/templates/base.html -> Final Kontrol",
    "Eksik işaret: app/templates/base.html -> meeting-development/final-gate",
    "Eksik işaret: app/menu_registry.py -> performance_meeting_development",
    "Eksik işaret: app/menu_registry.py -> performance_meeting_test_scenarios",
    "Eksik işaret: app/menu_registry.py -> performance_meeting_development_faz3",
    "Eksik işaret: app/menu_registry.py -> performance_meeting_final_gate",
)

# Documented old baseline (pre-wave, real repo state) vs the new, real,
# re-verified-this-session state.
OLD_BASELINE_PASSED_COUNT = 27
EXPECTED_PASSED_COUNT = 36
EXPECTED_FINAL_CHECKS_COUNT = 6
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): an unrelated later
# wave (AQ-2) removed the /performans/baskan-onaylari route registration
# that always lost that URL's dispatch conflict anyway (see
# tests/quality/test_route_conflict_runtime_contract.py's KNOWN_CONFLICTS
# update), dropping the real url_map route count from 985 to 984.
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): 11 new
# GET-only /settings-center/* routes raised the count 984->995 -- mechanically
# re-verified against a fresh app.url_map, unrelated to this wave.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive route (POST /ai-agent/api/v2/ask) raised the count 995->996
# -- mechanically re-verified against a fresh app.url_map, unrelated to
# this wave.
EXPECTED_URL_MAP_TOTAL = 996


def _normalize_line_endings(data: bytes) -> bytes:
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


def _git_diff_added_lines(ref: str, relative_path: str) -> list[str]:
    """Lines added (working tree vs `ref`) to `relative_path`, without the
    leading '+' -- used for diff-scoped (not whole-file) safety checks."""
    result = subprocess.run(
        ["git", "diff", ref, "--", relative_path],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"'git diff {ref} -- {relative_path}' failed: {result.stderr!r}"
    added: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
    return added


# ---------------------------------------------------------------------------
# 17/18) Template files this wave must NOT have touched -- byte-identical to
# their state at this worktree's own pre-wave HEAD.
# ---------------------------------------------------------------------------


def test_p0_and_final_gate_templates_are_untouched_by_this_wave() -> None:
    for relative_path in (P0_TEMPLATE_FILE, FINAL_GATE_TEMPLATE_FILE):
        current = _normalize_line_endings((REPO_ROOT / relative_path).read_bytes())
        pre_wave = _normalize_line_endings(_git_show(PRE_WAVE_REF, relative_path))
        assert current == pre_wave, (
            f"{relative_path}: byte content changed since pre-wave ref {PRE_WAVE_REF} -- "
            "this navigation wave must not touch template bodies."
        )


# A LATER, separate wave (the stale-endpoint navigation fix -- see
# tests/services/test_meeting_stale_navigation_endpoint_fix_contract.py for
# its own full regression contract) corrected exactly two safe_url_for()
# endpoint strings per file in these same 6 templates:
# main.performance_development_guidance and main.performance_interim_notes_
# manager never existed as real Flask endpoints anywhere in this repo's git
# history (confirmed via `git log -S/-G` across `--all`: 0 hits for either
# function definition -- not a rename, the reference was simply wrong from
# day one), silently rendering "#" via the real safe_url_for context-
# processor's BuildError fallback. They were corrected to their live,
# independently-confirmed successors (main.performance_meeting_p4_
# development_guidance and main.performance_interim_notes_tr -- the same
# mapping this file's own SIBLING_SCREENS already documents for the first
# one, at lines 133-138 above). This assertion now allows exactly those two
# known substitutions and nothing else, preserving this test's original
# scope-creep guard for every other byte in these 6 files.
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


@pytest.mark.parametrize("relative_path", OTHER_SIX_MEETING_TEMPLATES)
def test_other_six_meeting_templates_are_untouched_by_this_wave(relative_path: str) -> None:
    current = _normalize_line_endings((REPO_ROOT / relative_path).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_WAVE_REF, relative_path))
    expected = pre_wave
    for old, new in _STALE_ENDPOINT_FIX_SUBSTITUTIONS:
        assert old in expected, (
            f"{relative_path}: expected pre-wave stale pattern {old!r} not found -- "
            "the stale-endpoint-fix substitution table may be out of date."
        )
        expected = expected.replace(old, new)
    assert current == expected, (
        f"{relative_path}: content differs from pre-wave ref {PRE_WAVE_REF} by more than the "
        "known, documented stale-endpoint navigation fix substitutions -- "
        "other 6 meeting templates must be untouched by anything else in this wave."
    )


# ---------------------------------------------------------------------------
# 14) No inline onclick=/javascript: URL anywhere in base.html.
# 16) No new <style>/<script> block introduced by this wave's own added
#     lines in base.html (diff-scoped, not whole-file, since base.html
#     legitimately carries its own pre-existing <script>/<style> blocks).
# ---------------------------------------------------------------------------


def test_base_html_has_no_inline_event_handlers_or_javascript_urls() -> None:
    """Whole-file check, scoped to actual href/src-style javascript: URLs --
    NOT a bare 'javascript:' substring search, because base.html legitimately
    contains a pre-existing, unrelated defensive JS snippet
    (`.startsWith('javascript:')`) that guards AGAINST javascript: URLs; a
    naive substring check would false-positive on that guard itself."""
    text = (REPO_ROOT / BASE_TEMPLATE_FILE).read_text(encoding="utf-8")
    assert not re.search(r'\bon\w+\s*=\s*"', text, re.IGNORECASE), (
        "app/templates/base.html must not contain an inline onXXX= event handler."
    )
    assert not re.search(r'(?:href|src)\s*=\s*["\']javascript:', text, re.IGNORECASE), (
        "app/templates/base.html must not contain an href/src javascript: URL."
    )


def test_base_html_new_lines_introduce_no_style_or_script_block_and_no_unsafe_sinks() -> None:
    added_lines = _git_diff_added_lines(PRE_WAVE_REF, BASE_TEMPLATE_FILE)
    assert added_lines, "Expected this wave to have added lines to app/templates/base.html."
    added_text = "\n".join(added_lines)
    assert "<style" not in added_text.lower(), "This wave's new base.html lines must not add a <style> block."
    assert "<script" not in added_text.lower(), "This wave's new base.html lines must not add a <script> block."
    assert "|safe" not in added_text, "This wave's new base.html lines must not use the |safe filter."
    assert not re.search(r'\bon\w+\s*=\s*"', added_text, re.IGNORECASE), (
        "This wave's new base.html lines must not add an inline event handler."
    )
    assert "javascript:" not in added_text.lower(), "This wave's new base.html lines must not add a javascript: URL."


# ---------------------------------------------------------------------------
# 19) This file itself introduces no skip/xfail marker (lightweight,
#     file-local check; the repo-wide diff check lives in the coordinator's
#     Part 2 node-ID diff).
# ---------------------------------------------------------------------------


_FORBIDDEN_SKIP_XFAIL_MARKERS = ("@pytest.mark.skip", "@pytest.mark.xfail", "pytest.skip(", "pytest.xfail(")


def test_this_file_introduces_no_skip_or_xfail_usage() -> None:
    own_text = Path(__file__).read_text(encoding="utf-8")
    marker_def_start = own_text.index("_FORBIDDEN_SKIP_XFAIL_MARKERS = (")
    marker_def_end = own_text.index(")\n", marker_def_start) + 1
    scan_text = own_text[:marker_def_start] + own_text[marker_def_end:]
    hits = [marker for marker in _FORBIDDEN_SKIP_XFAIL_MARKERS if marker in scan_text]
    assert hits == [], f"Found forbidden skip/xfail usage marker(s) in this file: {hits}"


# ---------------------------------------------------------------------------
# Real, isolated, multi-role Flask app.
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "meeting_dev_nav_fix" / "test_dbs"
_PASSWORD = "MeetingDevNavFixTestKey1!"


@pytest.fixture(scope="module")
def nav_env():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-meeting-dev-nav-fix-contract-min-length-ok")
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
        for sicil_no, role in (
            ("navfixadm1", "admin"),
            ("navfixkrd1", "koordinator"),
            ("navfixstf1", "personel"),
        ):
            user = User(
                sicil_no=sicil_no,
                email=f"{sicil_no}@ktb.gov.tr",
                ad="NavFix",
                soyad=role.capitalize(),
                role=role,
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            user.set_password(_PASSWORD)
            db.session.add(user)
        db.session.commit()

    yield app

    mp.undo()


def _login_new_client(app, sicil_no: str):
    client = app.test_client()
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": _PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302, f"Login failed for {sicil_no}: status={response.status_code}"
    assert "/login" not in (response.headers.get("Location") or ""), (
        f"Still redirected to /login for {sicil_no} after POST -- authentication may have failed."
    )
    return client


@pytest.fixture(scope="module")
def admin_client(nav_env):
    return _login_new_client(nav_env, "navfixadm1")


@pytest.fixture(scope="module")
def manager_client(nav_env):
    """A non-admin manager-family role (koordinator)."""
    return _login_new_client(nav_env, "navfixkrd1")


@pytest.fixture(scope="module")
def personel_client(nav_env):
    """A non-manager role -- must NOT see or gain any of the 4 new screens."""
    return _login_new_client(nav_env, "navfixstf1")


@pytest.fixture(scope="module")
def anon_client(nav_env):
    return nav_env.test_client()


@pytest.fixture(scope="module")
def real_gate_context(nav_env):
    """Real, unmocked `build_final_gate_context()` output against the actual
    repo -- ground truth for the error/passed-count assertions below."""
    with nav_env.app_context():
        from app.services.performance.meeting_development_final_gate import build_final_gate_context

        return build_final_gate_context()


# ---------------------------------------------------------------------------
# 1/2/3) All 4 routes exist in the real url_map with the exact documented
#        endpoint name and URL.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("screen", SCREENS, ids=[s["key"] for s in SCREENS])
def test_all_four_routes_exist_in_url_map_with_exact_endpoint_and_url(nav_env, screen: dict[str, Any]) -> None:
    rules_by_endpoint = {rule.endpoint: rule for rule in nav_env.url_map.iter_rules()}
    assert screen["endpoint"] in rules_by_endpoint, (
        f"Expected endpoint {screen['endpoint']!r} to exist in the real url_map."
    )
    rule = rules_by_endpoint[screen["endpoint"]]
    assert rule.rule == screen["url"], (
        f"Endpoint {screen['endpoint']!r}: expected URL {screen['url']!r}, got {rule.rule!r}."
    )
    assert "GET" in rule.methods


def test_all_four_endpoint_names_are_exact() -> None:
    expected = {
        "main.performance_meeting_development",
        "main.performance_meeting_test_scenarios",
        "main.performance_meeting_development_faz3",
        "main.performance_meeting_final_gate",
    }
    assert {screen["endpoint"] for screen in SCREENS} == expected


def test_all_four_urls_are_exact() -> None:
    expected = {
        "/performance/meeting-development",
        "/performance/meeting-development/test-scenarios",
        "/performance/meeting-development/faz3",
        "/performance/meeting-development/final-gate",
    }
    assert {screen["url"] for screen in SCREENS} == expected


# ---------------------------------------------------------------------------
# 13) Real create_app() url_map total route count is unchanged (no new
#     routes -- only navigation/visibility registrations).
# ---------------------------------------------------------------------------


def test_url_map_route_count_is_unchanged(nav_env) -> None:
    total = len(list(nav_env.url_map.iter_rules()))
    assert total == EXPECTED_URL_MAP_TOTAL, f"url_map route count is {total}; expected {EXPECTED_URL_MAP_TOTAL}."


# ---------------------------------------------------------------------------
# 4) All 4 menu entries resolve from the real build_menu_visibility_map()
#    (app.route_support.build_menu_visibility_map -- the exact function the
#    real inject_menu_visibility() context processor calls) for real User
#    ORM instances, not a hardcoded assumption.
# ---------------------------------------------------------------------------


def test_real_build_menu_visibility_map_grants_manager_family_roles_all_four_keys(nav_env) -> None:
    from app.models import User
    from app.route_support import build_menu_visibility_map

    with nav_env.app_context():
        for sicil_no in ("navfixadm1", "navfixkrd1"):
            user = User.query.filter_by(sicil_no=sicil_no).one()
            assert user.role in MANAGER_FAMILY_ROLES
            visibility = build_menu_visibility_map(user)
            for key in SCREEN_KEYS:
                assert visibility.get(key) is True, (
                    f"Expected build_menu_visibility_map() to grant {key!r} to role {user.role!r} (sicil={sicil_no})."
                )


def test_real_build_menu_visibility_map_denies_personel_role_all_four_keys(nav_env) -> None:
    from app.models import User
    from app.route_support import build_menu_visibility_map

    with nav_env.app_context():
        user = User.query.filter_by(sicil_no="navfixstf1").one()
        assert user.role == "personel"
        visibility = build_menu_visibility_map(user)
        for key in SCREEN_KEYS:
            assert not visibility.get(key, False), (
                f"Expected build_menu_visibility_map() to deny {key!r} to role 'personel'."
            )


# ---------------------------------------------------------------------------
# 5) No duplicate menu definitions -- each of the 4 keys appears exactly
#    once across app.menu_registry_data_sections.MENU_SECTIONS's flattened
#    item list.
# ---------------------------------------------------------------------------


def test_no_duplicate_menu_definitions_for_the_four_new_keys(nav_env) -> None:
    # Import app.menu_registry (already imported as part of create_app(), but
    # explicit here so this test is meaningful even if run in isolation) --
    # it mutates the SAME MENU_SECTIONS list object via in-place .append()
    # calls, so the real, fully-assembled runtime state is what gets checked.
    import app.menu_registry  # noqa: F401
    from app.menu_registry_data_sections import MENU_SECTIONS

    flat_keys: list[str] = []
    for section in MENU_SECTIONS:
        for item in section.get("items", []):
            key = item.get("key")
            if key is not None:
                flat_keys.append(key)

    for key in SCREEN_KEYS:
        occurrences = flat_keys.count(key)
        assert occurrences == 1, f"Menu key {key!r} appears {occurrences} times in MENU_SECTIONS; expected exactly 1."


# ---------------------------------------------------------------------------
# 6/7) Rendered sidebar: manager-family roles see all 4 nav links, personel
#      sees none, in a real authenticated GET of the main shell page
#      (/dashboard, which extends base.html).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_fixture", ["admin_client", "manager_client"])
def test_manager_family_roles_see_all_four_nav_links_in_dashboard_sidebar(request, client_fixture: str) -> None:
    client = request.getfixturevalue(client_fixture)
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    for screen in SCREENS:
        marker = f'data-menu-key="{screen["key"]}"'
        assert marker in body, f"Expected nav link marker {marker!r} in dashboard sidebar for {client_fixture}."
        assert screen["label"] in body, f"Expected label {screen['label']!r} in dashboard sidebar for {client_fixture}."


def test_personel_role_does_not_see_any_of_the_four_nav_links_in_dashboard_sidebar(personel_client) -> None:
    response = personel_client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    for screen in SCREENS:
        marker = f'data-menu-key="{screen["key"]}"'
        assert marker not in body, (
            f"personel must NOT see nav link marker {marker!r} in the dashboard sidebar."
        )


# ---------------------------------------------------------------------------
# 8) Authenticated manager GET on all 4 URLs returns 200.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_fixture", ["admin_client", "manager_client"])
@pytest.mark.parametrize("screen", SCREENS, ids=[s["key"] for s in SCREENS])
def test_authenticated_manager_get_on_each_url_returns_200(request, client_fixture: str, screen: dict[str, Any]) -> None:
    client = request.getfixturevalue(client_fixture)
    response = client.get(screen["url"], follow_redirects=False)
    assert response.status_code == 200, (
        f"{client_fixture} GET {screen['url']!r} returned {response.status_code}; expected 200."
    )


# ---------------------------------------------------------------------------
# 9) Unauthenticated direct GET on all 4 URLs still redirects to /login
#    (302) -- proves auth behavior is unchanged by this wave (not weakened
#    to a public 200, not accidentally turned into a 404/403).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("screen", SCREENS, ids=[s["key"] for s in SCREENS])
def test_unauthenticated_get_on_each_url_redirects_to_login(anon_client, screen: dict[str, Any]) -> None:
    response = anon_client.get(screen["url"], follow_redirects=False)
    assert response.status_code == 302, (
        f"Unauthenticated GET {screen['url']!r} returned {response.status_code}; expected 302 redirect to /login."
    )
    location = response.headers.get("Location") or ""
    assert "/login" in location, f"Unauthenticated GET {screen['url']!r} redirected to {location!r}, not /login."


# ---------------------------------------------------------------------------
# 10/11/12) build_final_gate_context() (real, unmocked) now reports 0
#           errors, none of the 9 original literal error messages remain,
#           final_checks is still exactly 6 (static, unchanged structure),
#           and passed reflects the new tokens (36 = old baseline 27 + 9).
# ---------------------------------------------------------------------------


def test_build_final_gate_context_now_reports_zero_errors(real_gate_context) -> None:
    assert real_gate_context["errors"] == []
    assert real_gate_context["status"] == "GEÇTİ"


@pytest.mark.parametrize("message", ORIGINAL_NINE_ERROR_MESSAGES)
def test_none_of_the_nine_original_error_messages_remain(real_gate_context, message: str) -> None:
    assert message not in real_gate_context["errors"], (
        f"Original pre-wave error message still present: {message!r}"
    )


def test_final_checks_list_is_still_exactly_six_items_unchanged(real_gate_context) -> None:
    final_checks = real_gate_context["final_checks"]
    assert len(final_checks) == EXPECTED_FINAL_CHECKS_COUNT
    for item in final_checks:
        assert set(item.keys()) >= {"code", "title", "expected", "priority"}


def test_passed_count_reflects_the_new_tokens(real_gate_context) -> None:
    passed = real_gate_context["passed"]
    assert len(passed) == EXPECTED_PASSED_COUNT, (
        f"passed count is {len(passed)}; expected {EXPECTED_PASSED_COUNT} "
        f"(documented old baseline {OLD_BASELINE_PASSED_COUNT} + 9 newly-passing navigation tokens)."
    )
    assert len(passed) - OLD_BASELINE_PASSED_COUNT == 9, (
        "Expected exactly 9 more passed entries than the documented pre-wave baseline of "
        f"{OLD_BASELINE_PASSED_COUNT}."
    )
    # BYS360_NAV_CANONICAL_SOURCE_FIX: the 4 menu_registry.py-targeted
    # tokens are no longer produced by a raw-text scan of that file (which
    # was only satisfied by a dead FORCE_VISIBLE_MENU_ROLES literal --
    # removed in a follow-up correction wave, see
    # test_meeting_final_gate_canonical_menu_source_contract.py). They are
    # now produced by a real behavioral check against the canonical
    # MENU_SECTIONS registry, with a distinct "Menü kaydı doğrulandı: "
    # message prefix.
    for token in (
        "İşaret hazır: Toplantı Geliştirme",
        "İşaret hazır: Toplantı Testleri",
        "İşaret hazır: Toplantı Derinleştirme",
        "İşaret hazır: Final Kontrol",
        "İşaret hazır: meeting-development/final-gate",
        "Menü kaydı doğrulandı: performance_meeting_development",
        "Menü kaydı doğrulandı: performance_meeting_test_scenarios",
        "Menü kaydı doğrulandı: performance_meeting_development_faz3",
        "Menü kaydı doğrulandı: performance_meeting_final_gate",
    ):
        assert token in passed, f"Expected newly-passing token {token!r} in passed list."


def test_real_gate_warnings_are_still_empty(real_gate_context) -> None:
    """Sanity guard: this wave only wires navigation, it does not touch the
    settings-table warnings path -- warnings must remain exactly as
    documented (0), independent of the errors fix."""
    assert real_gate_context["warnings"] == []


# ---------------------------------------------------------------------------
# 20) Ground-truth sibling screens (performance_meeting_p3_reminders,
#     performance_development_guidance) still work exactly as before --
#     regression guard proving this wave did not disturb the existing
#     working pattern while extending it.
# ---------------------------------------------------------------------------


def test_sibling_screens_are_still_granted_to_manager_family_roles(nav_env) -> None:
    from app.models import User
    from app.route_support import build_menu_visibility_map

    with nav_env.app_context():
        for sicil_no in ("navfixadm1", "navfixkrd1"):
            user = User.query.filter_by(sicil_no=sicil_no).one()
            visibility = build_menu_visibility_map(user)
            for sibling in SIBLING_SCREENS:
                assert visibility.get(sibling["key"]) is True, (
                    f"Sibling screen {sibling['key']!r} regressed: no longer granted to role {user.role!r}."
                )


def test_sibling_screens_are_still_denied_to_personel(nav_env) -> None:
    from app.models import User
    from app.route_support import build_menu_visibility_map

    with nav_env.app_context():
        user = User.query.filter_by(sicil_no="navfixstf1").one()
        visibility = build_menu_visibility_map(user)
        for sibling in SIBLING_SCREENS:
            assert not visibility.get(sibling["key"], False), (
                f"Sibling screen {sibling['key']!r} regressed: unexpectedly granted to role 'personel'."
            )


@pytest.mark.parametrize("client_fixture", ["admin_client", "manager_client"])
@pytest.mark.parametrize("sibling", SIBLING_SCREENS, ids=[s["key"] for s in SIBLING_SCREENS])
def test_sibling_screens_still_return_200_for_manager_family_roles(request, client_fixture: str, sibling: dict[str, Any]) -> None:
    client = request.getfixturevalue(client_fixture)
    response = client.get(sibling["url"], follow_redirects=False)
    assert response.status_code == 200, (
        f"Sibling screen regression: {client_fixture} GET {sibling['url']!r} returned "
        f"{response.status_code}; expected 200."
    )


@pytest.mark.parametrize("client_fixture", ["admin_client", "manager_client"])
def test_sibling_screens_still_visible_in_dashboard_sidebar(request, client_fixture: str) -> None:
    client = request.getfixturevalue(client_fixture)
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    for sibling in SIBLING_SCREENS:
        assert sibling["label"] in body, (
            f"Sibling screen regression: label {sibling['label']!r} no longer in dashboard sidebar "
            f"for {client_fixture}."
        )


def test_sibling_screens_endpoint_and_url_are_unchanged(nav_env) -> None:
    rules_by_endpoint = {rule.endpoint: rule for rule in nav_env.url_map.iter_rules()}
    for sibling in SIBLING_SCREENS:
        assert sibling["endpoint"] in rules_by_endpoint
        assert rules_by_endpoint[sibling["endpoint"]].rule == sibling["url"]
