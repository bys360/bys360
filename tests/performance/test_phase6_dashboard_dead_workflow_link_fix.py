"""BYS360 Performance V2 Faz6 -- dead workflow link fix contract.

CONTEXT: `app/templates/performance_v2_phase6_dashboard.html` carried an
UNCONDITIONAL `<a href="{{ url_for('main.workflow_executive_dashboard') }}">`
("İş Akış Paneli" button) -- unlike its sibling action links on the same row,
which all guard with `if period else ...`. `main.workflow_executive_dashboard`
does not exist in the live `url_map` (it would only exist if the dead
`app/workflow/routes.py` module were ever imported, which it is not -- see
the separate "BYS360 Workflow Alt Sistemi" read-only audit in this repo's
history for the full independent proof that the entire `app/workflow/`
route/template subsystem is unreachable at runtime).

This meant every real request to the LIVE, registered `/performance/v2/faz6`
and `/performans/v2/faz6` routes (`app/performance/v2_routes.py::
performance_v2_phase6_dashboard`, `@main_bp.route`, `@login_required`,
`@admin_required`) raised `werkzeug.routing.exceptions.BuildError` at
template-render time -- a 500 for every visitor, regardless of whether a
period was selected. No existing test rendered this page via a real HTTP
GET (confirmed by grep across `tests/` before this fix), which is why it
went undetected.

FIX DECISION: no active endpoint serves the same "İş Akış Paneli" (workflow/
process-tracking panel) purpose -- Executive Summary
(`executive_summary.yonetici_ozeti`) is a different concept (system health/
mail, not process workflow); Team Compare already has its own adjacent
button; President Approvals (`main.performance_president_approvals`) covers
only a narrow subset of what a workflow panel implied. Per the "don't match
on name similarity alone" rule, none of these were repurposed. The dead
button was removed entirely (not replaced with `#`/`javascript:void(0)`/a
new redirect/a new inline handler) -- the safest, smallest fix. The action
row's CSS (`.bys-pro-hero-actions{display:flex;gap:10px;flex-wrap:wrap}`,
`app/static/css/bys360_reports_ai_pro.css`) is a wrapping flex row, not a
fixed-column grid, so removing one button leaves no visual gap.

ISOLATION -- TWO DIFFERENT LEVELS, DELIBERATELY: this file avoids the
shared, session-scoped `app`/`client` fixtures from `tests/conftest.py`
throughout. Most tests below build one throwaway, fully isolated Flask app
per test (same pattern as `tests/security/test_account_change_photo_
redirect_guard.py::_make_app`), with a real SQLite schema and a real admin
user logged in via a real `/login` POST -- not `LOGIN_DISABLED`, not a raw
`render_template()` call. That level of isolation is sufficient for the
HTTP-response/HTML-content/style-inventory checks.

It is NOT sufficient for the two `sys.modules`-absence / `url_map` route-
count-and-hash checks, and building a fresh `Flask` app object per test does
NOT protect them either: `app.workflow.routes`'s `@main_bp.route(...)`
decorators run once, at IMPORT time, as a permanent side effect on the
module-level singleton `main_bp` Blueprint object in `app.route_registry`
(shared by every `Flask` app built in the same process afterwards, since
`create_app()` always registers that same object). If ANY other test module
in the same pytest process imports `app.workflow.routes` -- which
`tests/workflow/test_phase5w_workflow_schema_readiness.py` and
`tests/workflow/test_generic_sync_sql_identifier_phase5u.py` both do, at
MODULE level, meaning pytest's own COLLECTION phase (which imports every
test file up front, before any test function runs) triggers it regardless
of file/test ordering -- every `create_app()` call for the REST OF THAT
PROCESS, including inside a brand-new `Flask` app object built by this
file's own `_make_app()`, ends up with 997 routes instead of 985. This was
independently reproduced while writing this file: running just
`test_workflow_modules_are_absent_from_sys_modules_at_clean_startup`
together with `tests/workflow/` in the same `pytest` invocation made it
fail, even though this file never imports `app.workflow` itself. So those
two specific checks run in a genuinely separate OS subprocess (`subprocess.
run([sys.executable, "-c", probe])`) -- the same pattern already established
by `tests/security/test_executive_summary_dead_route_module_cleanup_
contract.py::_run_isolated_create_app_probe` and `tests/quality/test_
phase12b_route_ownership_contract.py::test_source_only_route_candidates_
are_absent_from_fresh_production_runtime` -- which is immune to this class
of contamination because it starts a brand-new Python interpreter with no
test modules imported at all.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360_pytest_tmp" / "phase6_dead_link_fix_dbs"

# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): an unrelated later
# wave (AQ-2) removed the /performans/baskan-onaylari route registration
# that always lost that URL's dispatch conflict anyway (see
# tests/quality/test_route_conflict_runtime_contract.py's KNOWN_CONFLICTS
# update), dropping the real url_map route count from 985 to 984 and
# changing the endpoint-list hash. This wave's own change (dead workflow
# link removal from a template) remains unrelated to routes; the baseline
# below is updated to the new, correct values.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): 11 new
# GET-only /settings-center/* routes (app/settings_center/routes.py) raised
# the count 984->995 and changed the endpoint-list hash accordingly --
# mechanically re-verified against a fresh app.url_map, unrelated to this
# wave's own dead-link-removal change.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive route (POST /ai-agent/api/v2/ask) raised the count 995->996
# and changed the endpoint-list hash accordingly -- mechanically re-verified
# against a fresh app.url_map, unrelated to this wave's own dead-link-
# removal change.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 B2-F06 private uploads): one new,
# additive route (GET /portal/attachments/<int:attachment_id>) raised the
# count 996->997 and changed the endpoint-list hash accordingly --
# mechanically re-verified against a fresh app.url_map, unrelated to this wave.
EXPECTED_ROUTE_COUNT = 997
EXPECTED_ENDPOINT_LIST_SHA256 = "269dc9216997f412a6323e22a365605535f4214aab4fdb87c0dabb74e7820e4e"

TEMPLATE_PATH = REPO_ROOT / "app" / "templates" / "performance_v2_phase6_dashboard.html"


def _make_app(monkeypatch, **config_overrides):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase6-dead-link-fix")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    app.config.update(config_overrides)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def _create_admin_user(app, *, sicil_no="p6dlf-admin", email="p6dlf-admin@example.test", password="Phase6DeadLinkTestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Phase6",
            soyad="Admin",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no="p6dlf-admin", password="Phase6DeadLinkTestKey1!"):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302, f"Login did not redirect as expected: {response.status_code}"
    assert "/login" not in response.headers.get("Location", ""), "Login failed -- redirected back to /login."
    return response


@pytest.fixture()
def isolated_admin_app(monkeypatch):
    app = _make_app(monkeypatch)
    _create_admin_user(app)
    return app


# ---------------------------------------------------------------------------
# 1) Clean-startup invariants: workflow modules never imported, url_map
#    route count/hash unchanged. Genuinely isolated subprocess -- see module
#    docstring for why an in-process fresh Flask app is NOT sufficient here.
# ---------------------------------------------------------------------------


def _run_isolated_create_app_probe(probe_script: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", probe_script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, {"stdout": result.stdout, "stderr": result.stderr}
    return result.stdout.strip().splitlines()


def test_workflow_modules_are_absent_from_sys_modules_at_clean_startup() -> None:
    probe_script = (
        "import sys, json\n"
        "from app import create_app\n"
        "app = create_app()\n"
        "print(json.dumps({\n"
        "    'workflow': 'app.workflow' in sys.modules,\n"
        "    'workflow_routes': 'app.workflow.routes' in sys.modules,\n"
        "    'workflow_dashboard_upgrade_routes': 'app.workflow.dashboard_upgrade_routes' in sys.modules,\n"
        "}))\n"
    )
    output_lines = _run_isolated_create_app_probe(probe_script)
    result = json.loads(output_lines[-1])
    assert result == {
        "workflow": False,
        "workflow_routes": False,
        "workflow_dashboard_upgrade_routes": False,
    }, result


def test_url_map_route_count_and_endpoint_hash_are_unchanged() -> None:
    probe_script = (
        "import hashlib\n"
        "from app import create_app\n"
        "app = create_app()\n"
        "endpoint_list = sorted(rule.endpoint for rule in app.url_map.iter_rules())\n"
        "print('ROUTE_COUNT=%d' % len(endpoint_list))\n"
        "print('ENDPOINT_SHA256=%s' % hashlib.sha256(chr(10).join(endpoint_list).encode()).hexdigest())\n"
    )
    output_lines = _run_isolated_create_app_probe(probe_script)
    values = dict(line.split("=", 1) for line in output_lines if line.startswith(("ROUTE_COUNT=", "ENDPOINT_SHA256=")))
    assert values.get("ROUTE_COUNT") == str(EXPECTED_ROUTE_COUNT), (
        f"Isolated create_app() url_map route count is {values.get('ROUTE_COUNT')}; "
        f"expected {EXPECTED_ROUTE_COUNT}. This fix must not add, remove, or otherwise change any route."
    )
    assert values.get("ENDPOINT_SHA256") == EXPECTED_ENDPOINT_LIST_SHA256, (
        f"Isolated create_app() url_map sorted-endpoint-list SHA-256 is "
        f"{values.get('ENDPOINT_SHA256')}; expected {EXPECTED_ENDPOINT_LIST_SHA256}."
    )


def test_phase6_route_is_registered(isolated_admin_app):
    endpoints = {rule.endpoint for rule in isolated_admin_app.url_map.iter_rules()}
    assert "main.performance_v2_phase6_dashboard" in endpoints


# ---------------------------------------------------------------------------
# 2) Real, authenticated HTTP GET: 500 -> 200, no BuildError, no dead-link
#    remnant in the rendered HTML.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/performance/v2/faz6", "/performans/v2/faz6"])
def test_authenticated_get_returns_200_not_500(isolated_admin_app, path):
    client = isolated_admin_app.test_client()
    _login(client)
    response = client.get(path)
    assert response.status_code == 200, (
        f"GET {path} returned {response.status_code}; expected 200. A non-200 here most likely means "
        "the BuildError regressed (a still-dead url_for() target in the template)."
    )


def test_rendered_html_no_longer_references_the_dead_workflow_endpoint_or_url(isolated_admin_app):
    client = isolated_admin_app.test_client()
    _login(client)
    response = client.get("/performance/v2/faz6")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "workflow_executive_dashboard" not in body, (
        "The rendered page still references the dead 'workflow_executive_dashboard' endpoint."
    )
    assert "/workflow/executive-dashboard" not in body, (
        "The rendered page still references the dead '/workflow/executive-dashboard' URL."
    )


def test_unauthenticated_get_is_redirected_not_500(isolated_admin_app):
    """Regression safety net: confirms the fix did not weaken the route's
    existing auth guard (unauthenticated access must still redirect to
    login, never 200 and never a raw 500)."""
    client = isolated_admin_app.test_client()
    response = client.get("/performance/v2/faz6", follow_redirects=False)
    assert response.status_code in (302, 401, 403), (
        f"Unauthenticated GET returned {response.status_code}; expected a redirect/deny, not a raw 200/500."
    )


# ---------------------------------------------------------------------------
# 3) Template source: no dead-link remnant, no fake '#'/javascript:void(0)
#    placeholder, no new inline handler introduced by this fix.
# ---------------------------------------------------------------------------


def test_template_source_has_no_dead_workflow_reference() -> None:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "workflow_executive_dashboard" not in text
    assert "/workflow/executive-dashboard" not in text
    assert "İş Akış Paneli" not in text


def test_template_source_introduces_no_placeholder_href_or_new_handler() -> None:
    """The fix must not paper over the dead link with a fake '#' /
    'javascript:void(0)' placeholder, nor add a new inline event handler --
    the removed button's entire <a> element is simply gone."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "javascript:void(0)" not in text
    assert 'href="#"' not in text
    assert "fa-route" not in text  # the removed button's icon class


def test_remaining_hero_action_buttons_are_still_present_and_unchanged() -> None:
    """The other 3 action buttons on the same row must be untouched --
    this was a single-line removal, not a broader edit."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "main.performance_v2_phase6_export_xlsx" in text
    assert "main.performance_v2_phase6_print" in text
    assert "main.performance_team_compare" in text


# ---------------------------------------------------------------------------
# 4) Style/CSP/handler inventory unchanged (the removed line carried no
#    style="..." attribute or inline handler to begin with).
#
#    NOTE: these totals reflect the state as of THIS fix's own commit
#    (1037/66/247). A later, separate wave (BYS360 Workflow Orphan
#    Presentation Subsystem Temizliği) deleted 14 more confirmed-orphan
#    templates unrelated to this fix, dropping the live repo-wide totals to
#    1035/64/233 -- see tests/security/test_csp_style_migration_cumulative_
#    inventory_contract.py's DELETED_TEMPLATE_WAVES["workflow_orphan_
#    presentation_cleanup"]. Updated here to match, since this test asserts
#    against the live worktree, not a frozen snapshot of this fix's own
#    diff. A further later wave (style3c_meeting_family_group_a) extracted 8
#    more <style> blocks from 8 active templates (no static/dynamic
#    attributes touched), dropping the block total to 225 -- see that same
#    ledger file's STYLE_MIGRATION_WAVES["style3c_meeting_family_group_a"].
#    A further, unrelated later wave (weights_orphan_template_cleanup)
#    deleted the orphan app/templates/weights.html, which independently
#    carried its own one static style="..." attribute and one <style> block,
#    dropping the totals to 1034/224 -- see that same ledger file's FORWARD-
#    COMPATIBILITY FOLLOW-UP 7. A further, unrelated later wave
#    (weight_create_edit_orphan_cleanup) deleted the two sibling orphans
#    app/templates/weight_create.html and app/templates/weight_edit.html,
#    each independently carrying one static style="..." attribute and one
#    <style> block, dropping the totals to 1032/222 -- see that same ledger
#    file's FORWARD-COMPATIBILITY FOLLOW-UP 8. A further, unrelated later
#    wave (BYS360 Settings Center V2) added 4 new templates under
#    app/templates/settings_center/ (_shell.html, home.html, module.html,
#    plus the shared partial), but its CSS was authored directly as an
#    external stylesheet (app/static/css/settings_center.css) and its 4
#    inline style="..." spots were replaced with named classes -- 0 static,
#    0 blocks, 0 dynamic contributed. Totals remain 1032/222/64 -- see that
#    same ledger file's FORWARD-COMPATIBILITY FOLLOW-UP 9.
# ---------------------------------------------------------------------------

EXPECTED_ACTIVE_STYLE_TOTAL = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL = 64
EXPECTED_STYLE_BLOCK_TOTAL = 221


def test_canonical_style_and_handler_inventory_is_unchanged() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL
    assert inventory.inline_handler_total == 0
    assert inventory.javascript_url_total == 0


def test_csp_style_directives_unchanged(isolated_admin_app) -> None:
    client = isolated_admin_app.test_client()
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
        assert directives.get(directive) == expected_value
        assert "'nonce-" not in directives.get(directive, "")


# ---------------------------------------------------------------------------
# 5) No new xfail/skip introduced by this file.
# ---------------------------------------------------------------------------

_XFAIL_MARK_RE_PARTS = ("@pytest", ".mark.xfail")
_SKIP_MARK_RE_PARTS = ("@pytest", ".mark.skip")
_XFAIL_CALL_RE_PARTS = ("pytest", ".xfail(")
_SKIP_CALL_RE_PARTS = ("pytest", ".skip(")


def test_this_file_introduces_no_xfail_or_skip_usage() -> None:
    own_text = Path(__file__).read_text(encoding="utf-8")
    assert "".join(_XFAIL_MARK_RE_PARTS) not in own_text
    assert "".join(_SKIP_MARK_RE_PARTS) not in own_text
    assert "".join(_XFAIL_CALL_RE_PARTS) not in own_text
    assert "".join(_SKIP_CALL_RE_PARTS) not in own_text
