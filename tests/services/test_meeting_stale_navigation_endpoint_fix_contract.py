"""BYS360 meeting workflow "Hızlı İşlemler" stale endpoint fix -- regression contract.

Six meeting-workflow templates (faz3, test-scenarios, final-closure, p1,
p2, rule-enforcement) each carry an identical "Hızlı İşlemler" quick-action
card with two links:

  - "Gelişim Rehberi"    -> safe_url_for('main.performance_development_guidance')
  - "Dönem İçi Notlar"   -> safe_url_for('main.performance_interim_notes_manager')

Neither ``main.performance_development_guidance`` nor ``main.performance_
interim_notes_manager`` has ever existed as a real Flask endpoint anywhere
in this repo's git history (``git log -S/-G`` across ``--all``: 0 hits for
either function definition) -- this was never a rename, the reference was
simply wrong from the start. Because both links go through the real
``safe_url_for`` context-processor helper (``app/route_support.py``, wired
in app-wide via ``app.routes.inject_route_helpers`` -- see the prior
session's live-render investigation), the app never crashes; it silently
renders ``href="#"`` on every one of the 6 pages.

Live, independently-confirmed successors (matched via ``app/menu_registry.py``'s
own canonical navigation data -- the exact same label/icon/menu-group pairing
already used elsewhere in the live app -- not Werkzeug's fuzzy "did you
mean" name-similarity suggestion, and not a git-history rename):

  - "Gelişim Rehberi"   -> main.performance_meeting_p4_development_guidance
                            (/performance/meeting-development/faz10)
  - "Dönem İçi Notlar"  -> main.performance_interim_notes_tr
                            (/performans/donem-ici-notlar)

Both candidates were independently verified: real ``app.url_map`` entries,
GET-supported, permission sets that are equal to or a strict superset of
the meeting pages' own ``@login_required`` + ``@manager_required`` gate (so
no user who can see these buttons is denied by the target), and matching
UI semantics (interim-notes NOTE_TYPES literally include "gelisim_ihtiyaci"/
"basari"/"genel_gozlem", matching the button's own subtitle text).

This file proves, via real authenticated HTTP GETs against the real routes
that render these 6 templates (not a synthetic Jinja string, not a bare
grep), that the two links resolve to real URLs -- and, before the fix is
applied, that they genuinely render "#" (the TDD failure this file was
authored against).
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

DEVELOPMENT_GUIDANCE_ENDPOINT = "main.performance_meeting_p4_development_guidance"
DEVELOPMENT_GUIDANCE_URL = "/performance/meeting-development/faz10"
INTERIM_NOTES_ENDPOINT = "main.performance_interim_notes_tr"
INTERIM_NOTES_URL = "/performans/donem-ici-notlar"

STALE_DEVELOPMENT_GUIDANCE_ENDPOINT = "main.performance_development_guidance"
STALE_INTERIM_NOTES_ENDPOINT = "main.performance_interim_notes_manager"

# The 6 real pages carrying the shared "Hızlı İşlemler" action card, each
# with its own real, auth-gated route.
MEETING_SCREENS: tuple[dict[str, str], ...] = (
    {
        "template": "app/templates/performance/meeting_development_faz3.html",
        "url": "/performance/meeting-development/faz3",
    },
    {
        "template": "app/templates/performance/meeting_development_scenarios.html",
        "url": "/performance/meeting-development/test-scenarios",
    },
    {
        "template": "app/templates/performance/meeting_final_closure.html",
        "url": "/performance/meeting-development/final-closure",
    },
    {
        "template": "app/templates/performance/meeting_p1_scope.html",
        "url": "/performance/meeting-development/p1",
    },
    {
        "template": "app/templates/performance/meeting_p2_archive_notes.html",
        "url": "/performance/meeting-development/p2",
    },
    {
        "template": "app/templates/performance/meeting_rule_enforcement.html",
        "url": "/performance/meeting-development/rules",
    },
)

# weights.html's 4 stale endpoints -- confirmed NO_SUCCESSOR / orphan template
# in the same investigation. A LATER wave ("BYS360 Orphan Template + Dead
# Helper Micro-Cleanup") independently re-confirmed ORPHAN_CONFIRMED (three
# agents, cross-checked, plus a live create_app()/url_map probe) and deleted
# the file outright -- see
# tests/security/test_weights_orphan_template_and_dead_safe_url_for_cleanup_contract.py
# for that wave's full evidence chain. The tests below were converted from
# "file still contains the stale references, byte for byte" (meaningless once
# the file no longer exists) to a "file is gone / stale strings are gone from
# ALL active presentation code / route registry unaffected" negative contract
# -- see that section's own comments for the exact rationale.
WEIGHTS_TEMPLATE = "app/templates/weights.html"
WEIGHTS_STALE_ENDPOINTS: tuple[str, ...] = (
    "main.performance_weight_create",
    "main.performance_weight_edit",
    "main.performance_weight_toggle_active",
    "main.performance_weight_delete",
)

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360_pytest_tmp_final" / "meeting_stale_endpoint_fix" / "test_dbs"
_PASSWORD = "MeetingStaleEndpointFixTestKey1!"


def _href_for_label(html: str, label: str) -> str:
    """Extract the href of the "Hızlı İşlemler" action link whose visible
    label is exactly `label`, matching this card's real, consistent markup:
    <a class="bys-md-action" href="HREF"><div><strong>LABEL</strong>..."""
    match = re.search(
        r'<a class="bys-md-action" href="([^"]*)">\s*<div>\s*<strong>' + re.escape(label) + r"</strong>",
        html,
    )
    assert match is not None, f"Could not find an action link labeled {label!r} in the rendered page."
    return match.group(1)


@pytest.fixture(scope="module")
def nav_app():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    db_uri = "sqlite:///" + db_path.as_posix()

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-meeting-stale-endpoint-fix-min-length-ok")
    mp.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    mp.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    mp.setenv("AUTO_REPAIR_SCHEMA", "false")
    mp.setenv("STRICT_SCHEMA_CHECK", "false")
    mp.setenv("REQUIRE_DOTENV_FILE", "false")
    mp.setenv("STRICT_ENV_VALIDATION", "false")
    mp.setenv("WTF_CSRF_ENABLED", "false")
    mp.setenv("DATABASE_URL", db_uri)
    mp.setenv("MAIL_SUPPRESS_SEND", "true")
    mp.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    mp.setattr(Config, "APP_ENV", "testing")
    mp.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    mp.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

    from app.extensions import db
    from app.models import User
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
        user = User(
            sicil_no="msenfx01",
            email="msenfx01@ktb.gov.tr",
            ad="MeetingStale",
            soyad="FixManager",
            role="koordinator",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(_PASSWORD)
        db.session.add(user)
        db.session.commit()

    yield app
    mp.undo()


@pytest.fixture(scope="module")
def manager_client(nav_app):
    client = nav_app.test_client()
    resp = client.post(
        "/login",
        data={"sicil_or_email": "msenfx01", "password": _PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" not in (resp.headers.get("Location") or "")
    return client


@pytest.fixture(scope="module")
def anon_client(nav_app):
    return nav_app.test_client()


# ---------------------------------------------------------------------------
# Real, authenticated GET of each of the 6 real pages -- proves the ACTUAL
# rendered href for both action links, not a synthetic string.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("screen", MEETING_SCREENS, ids=[s["url"] for s in MEETING_SCREENS])
def test_gelisim_rehberi_link_is_not_hash_on_real_rendered_page(manager_client, screen: dict[str, str]) -> None:
    response = manager_client.get(screen["url"], follow_redirects=False)
    assert response.status_code == 200, f"GET {screen['url']} returned {response.status_code}, expected 200."
    body = response.get_data(as_text=True)
    href = _href_for_label(body, "Gelişim Rehberi")
    assert href != "#", f"{screen['template']}: 'Gelişim Rehberi' link still renders href=\"#\"."
    assert href == DEVELOPMENT_GUIDANCE_URL, (
        f"{screen['template']}: 'Gelişim Rehberi' href is {href!r}, expected {DEVELOPMENT_GUIDANCE_URL!r}."
    )


@pytest.mark.parametrize("screen", MEETING_SCREENS, ids=[s["url"] for s in MEETING_SCREENS])
def test_donem_ici_notlar_link_is_not_hash_on_real_rendered_page(manager_client, screen: dict[str, str]) -> None:
    response = manager_client.get(screen["url"], follow_redirects=False)
    assert response.status_code == 200, f"GET {screen['url']} returned {response.status_code}, expected 200."
    body = response.get_data(as_text=True)
    href = _href_for_label(body, "Dönem İçi Notlar")
    assert href != "#", f"{screen['template']}: 'Dönem İçi Notlar' link still renders href=\"#\"."
    assert href == INTERIM_NOTES_URL, (
        f"{screen['template']}: 'Dönem İçi Notlar' href is {href!r}, expected {INTERIM_NOTES_URL!r}."
    )


# ---------------------------------------------------------------------------
# Route / auth verification for both successor endpoints -- registered,
# GET-supported, and still auth-gated (no permission weakening).
# ---------------------------------------------------------------------------


def test_both_successor_endpoints_are_registered_with_expected_urls(nav_app) -> None:
    rules_by_endpoint = {rule.endpoint: rule for rule in nav_app.url_map.iter_rules()}
    assert DEVELOPMENT_GUIDANCE_ENDPOINT in rules_by_endpoint
    assert rules_by_endpoint[DEVELOPMENT_GUIDANCE_ENDPOINT].rule == DEVELOPMENT_GUIDANCE_URL
    assert "GET" in rules_by_endpoint[DEVELOPMENT_GUIDANCE_ENDPOINT].methods
    assert INTERIM_NOTES_ENDPOINT in rules_by_endpoint
    assert rules_by_endpoint[INTERIM_NOTES_ENDPOINT].rule == INTERIM_NOTES_URL
    assert "GET" in rules_by_endpoint[INTERIM_NOTES_ENDPOINT].methods


@pytest.mark.parametrize("url", [DEVELOPMENT_GUIDANCE_URL, INTERIM_NOTES_URL])
def test_successor_endpoints_still_redirect_unauthenticated_requests_to_login(anon_client, url: str) -> None:
    response = anon_client.get(url, follow_redirects=False)
    assert response.status_code == 302, f"Unauthenticated GET {url} returned {response.status_code}; expected 302."
    location = response.headers.get("Location") or ""
    assert "/login" in location, f"Unauthenticated GET {url} redirected to {location!r}, not /login."


def test_stale_endpoints_still_do_not_exist_in_url_map(nav_app) -> None:
    """Sanity guard: the OLD, never-real endpoint names must still not be
    registered -- this test's whole premise (a genuine BuildError-triggered
    "#" fallback, not a coincidence) depends on that staying true."""
    endpoint_names = {rule.endpoint for rule in nav_app.url_map.iter_rules()}
    assert STALE_DEVELOPMENT_GUIDANCE_ENDPOINT not in endpoint_names
    assert STALE_INTERIM_NOTES_ENDPOINT not in endpoint_names


# ---------------------------------------------------------------------------
# Negative contract: weights.html was confirmed orphan (NO_SUCCESSOR) by this
# wave's own investigation and later DELETED outright by the follow-up
# "Orphan Template + Dead Helper Micro-Cleanup" wave. These tests were
# converted from "the dead references are still there, untouched" (which
# would raise FileNotFoundError once the file is gone) to the canonical
# deleted-template negative contract: the file must be genuinely absent, its
# 4 stale endpoint strings must have zero references anywhere in active
# presentation code, and the route registry must remain unaffected.
# ---------------------------------------------------------------------------


def test_weights_html_template_file_no_longer_exists() -> None:
    assert not (REPO_ROOT / WEIGHTS_TEMPLATE).exists(), (
        f"{WEIGHTS_TEMPLATE} still exists -- expected deleted (confirmed ORPHAN_CONFIRMED, "
        "see tests/security/test_weights_orphan_template_and_dead_safe_url_for_cleanup_contract.py)."
    )


def test_stale_weight_endpoint_strings_have_zero_presentation_references() -> None:
    """Repo-wide guard: none of weights.html's 4 stale endpoint strings may
    reappear in any active template or Python presentation code -- covers
    both the deleted template's own resurrection and an accidental copy-paste
    into a different file."""
    offenders: list[str] = []
    for root, suffixes in ((REPO_ROOT / "app" / "templates", (".html",)), (REPO_ROOT / "app", (".py",))):
        for suffix in suffixes:
            for path in root.rglob(f"*{suffix}"):
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(endpoint in text for endpoint in WEIGHTS_STALE_ENDPOINTS):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"Stale weight endpoint string(s) unexpectedly found in: {offenders!r}"


def test_weights_html_was_not_mapped_to_period_endpoints(nav_app) -> None:
    # Confirms no weight->period rename was ever wrongly wired into the real
    # url_map (weights.html itself is now deleted, but this closes the loop).
    endpoint_names = {rule.endpoint for rule in nav_app.url_map.iter_rules()}
    for endpoint in WEIGHTS_STALE_ENDPOINTS:
        assert endpoint not in endpoint_names, (
            f"{endpoint!r} unexpectedly registered in url_map -- weights.html's stale endpoints were "
            "classified NO_SUCCESSOR and must remain unregistered."
        )


def test_weights_html_still_renders_no_route_at_all() -> None:
    """weights.html is confirmed orphaned -- no render_template() call for it
    anywhere in the app. Guards against this fix accidentally wiring it up
    as an unintended side effect."""
    hits: list[str] = []
    for py_file in (REPO_ROOT / "app").rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="replace")
        if "weights.html" in text:
            hits.append(str(py_file.relative_to(REPO_ROOT)))
    assert hits == [], f"weights.html unexpectedly referenced by render_template in: {hits}"
