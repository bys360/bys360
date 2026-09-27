"""BYS360 Settings Center V2 -- Blocker 3 repo-wide menu/authorization
integrity audit ("PRE-COMMIT CLOSURE / REMEDIATION PHASE").

A single regex against `menu_key_required("...")` produces heavy false-
positive "orphan" noise in this codebase, because real authorization checks
use several different call patterns:

  1. `menu_key_required("key")` route decorators
  2. `can_access_menu(user, "key")` direct calls
  3. `<menu_map/visibility>.get("key")` / `[...]["key"]` dict lookups
  4. keys embedded in a tuple/list assigned to a `required`/`*_keys`-named
     variable, later iterated with `.get(` on a menu-like map (see
     app/ai_agent/routes.py's `required: tuple[str, ...] = (...)`)
  5. membership in `ROLE_MENU_DEFAULTS` (role -> keys)
  6. membership in `FORCE_VISIBLE_MENU_ROLES`
  7. membership in `app.live_scope.LIVE_SETTINGS_MENU_KEYS`
  8. membership in `module_registry.py`'s `anchor_menu_key` values

A key with any hit from patterns 1-8 is REGISTERED_AND_CONSUMED. Everything
else declared in MENU_SECTIONS is ORPHAN_MENU_KEY (utility links like
"account"/"logout" turned out to already be REGISTERED_AND_CONSUMED via
ROLE_MENU_DEFAULTS membership -- no separate exemption list was needed).

Every `menu_key_required(...)`/`can_access_menu(..., "key")` literal that
does NOT correspond to a declared MENU_SECTIONS key is ORPHAN_AUTH_KEY.
Every `module_registry.py` `anchor_menu_key` with no matching MENU_SECTIONS
key is ORPHAN_SETTINGS_CENTER.

CLOSURE (BYS360 FINAL ORPHAN AUTHORIZATION CLOSURE): the 5 ORPHAN_AUTH_KEYs
this file originally found and documented (`about_bys360`, `executive_
summary`, `support`, `reports`, `performance_history_import`) are now all
resolved. None of the fixes invented policy -- each was recovered
mechanically from existing project evidence:

  - `about_bys360`: DEAD_UNREGISTERED. app/about/routes.py used
    @main_bp.route directly but was never imported anywhere (repo-wide
    grep, zero hits) -- the exact same defect class as this codebase's own
    prior "Workflow Orphan Presentation Subsystem" cleanup wave. Deleted
    (app/about/routes.py, app/about/__init__.py, app/main_handlers/
    about_handlers.py, app/templates/about_bys360.html) rather than
    resurrected, per this mandate's own "do not resurrect dead features."

  - `executive_summary`: MISSING_REGISTRATION. The blueprint IS registered
    and the route IS live (/dashboard/yonetici-ozeti); a prior wave
    (test_executive_summary_dead_route_module_cleanup_contract.py)
    explicitly preserved it as legitimate. A MENU_SECTIONS *section* with
    this exact key/label/icon/required_roles already existed (with only
    its sibling "daily_weather_mail" item), and app/menu_registry.py's own
    _BYS360_DAILY_WEATHER_MAIL_EXEC_ROLE_DEFAULTS_V1_0_7 block already
    granted admin-tier roles this key via ROLE_MENU_DEFAULTS -- only the
    section's own home item was missing. Added it, reusing the section's
    own label/icon/roles verbatim. Separately found and fixed a real,
    pre-existing bug this exposed: app/services/settings/effective_menu_
    parts/build_context.py's own admin-only override used
    `globals().get("_BYS360_EXEC_ADMIN_ONLY_ROLES", set())`, which reads
    the WRONG module's namespace (that constant only ever lived in
    app/menu_registry.py) and always evaluated to the empty-set default,
    unconditionally forcing "executive_summary" (and its whole exec-only
    key family) to False for every user regardless of role. Fixed with a
    deferred cross-module import, matching this file's own established
    pattern elsewhere.

  - `support`: DUPLICATE_OF_EXISTING_CAPABILITY. All 10 usages across
    app/communication/phase3_routes.py, phase4_routes.py, phase5_routes.py
    operate on the identical SupportTicket/SupportTicketMessage/
    SupportTicketStatusHistory models as the already-registered,
    already-working "support_all" key (app/support/routes.py). Repointed
    the decorators to reuse "support_all" rather than inventing a parallel
    authorization surface for the same data.

  - `reports`: MISSING_REGISTRATION. 13 live routes across phase4_routes.py
    (dashboard/reports/export-center/governance) and phase5_routes.py
    (health/audit-logs) had no existing equivalent key. Registered using
    this module's own pre-authored, never-wired app/templates/
    communication/phase4_base_menu_snippet.txt for label/icon ("İletişim
    Faz 4 Paneli") and communication_phase4_service.py's own MANAGER_ROLES
    constant (the exact set its internal is_manager() check already
    enforces inside these same routes) for required_roles.

  - `performance_history_import`: MISSING_REGISTRATION. Already
    @admin_required at the Python level (app/route_support.py's
    ADMIN_FAMILY_ROLES). Registered using that exact, already-enforced
    role set and the route's own embedded page title ("Geçmiş Dönem Sonuç
    Aktarımı") for the label.

Verified via real HTTP requests (see
test_all_five_orphan_auth_keys_are_now_resolved_for_admin below): a
logged-in admin gets 200 on every route that used to 403; a non-manager
role (personel) still correctly gets 403 on all of them -- zero broadened
access, zero weakened fail-closed behavior.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

# Final pre-live audit P2-07: this authorization integrity audit carried no
# ci_safe marker, so `pytest tests/quality -m ci_safe` never ran it in CI.
pytestmark = pytest.mark.ci_safe

REPO_ROOT = Path(__file__).resolve().parents[2]

_PY_FILES = [
    p for p in (REPO_ROOT / "app").rglob("*.py")
    if "__pycache__" not in p.parts
]
_ALL_TEXT: dict[Path, str] = {p: p.read_text(encoding="utf-8", errors="replace") for p in _PY_FILES}

_MENU_KEY_REQUIRED_RE = re.compile(r'menu_key_required\(\s*["\']([^"\']+)["\']')
_CAN_ACCESS_MENU_RE = re.compile(r'can_access_menu\(\s*[^,]+,\s*["\']([^"\']+)["\']')
_MENU_MAP_GET_RE = re.compile(
    r'\b\w*(?:menu|visibility|menu_map)\w*\s*(?:\.get\(|\[)\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_TUPLE_LIST_REQUIRED_RE = re.compile(
    r'\b\w*(?:required|menu_keys?|assistant_path)\w*\s*(?::\s*[\w\[\], .]+)?\s*=\s*[\(\[]\s*((?:["\'][\w.\-]+["\']\s*,?\s*)+)[\)\]]',
    re.IGNORECASE,
)
_STR_LITERAL_RE = re.compile(r'["\']([\w.\-]+)["\']')


def _find_menu_key_required_keys() -> set[str]:
    hits: set[str] = set()
    for text in _ALL_TEXT.values():
        hits.update(_MENU_KEY_REQUIRED_RE.findall(text))
    return hits


def _find_can_access_menu_keys() -> set[str]:
    hits: set[str] = set()
    for text in _ALL_TEXT.values():
        hits.update(_CAN_ACCESS_MENU_RE.findall(text))
    return hits


def _find_menu_map_get_keys() -> set[str]:
    hits: set[str] = set()
    for text in _ALL_TEXT.values():
        hits.update(_MENU_MAP_GET_RE.findall(text))
    return hits


def _find_tuple_list_required_keys() -> set[str]:
    hits: set[str] = set()
    for text in _ALL_TEXT.values():
        for block in _TUPLE_LIST_REQUIRED_RE.findall(text):
            hits.update(_STR_LITERAL_RE.findall(block))
    return hits


def _find_role_menu_defaults_keys() -> set[str]:
    from app.menu_registry import ROLE_MENU_DEFAULTS

    hits: set[str] = set()
    for keys in ROLE_MENU_DEFAULTS.values():
        hits.update(keys)
    return hits


def _find_force_visible_keys() -> set[str]:
    from app.menu_registry import FORCE_VISIBLE_MENU_ROLES

    return set(FORCE_VISIBLE_MENU_ROLES.keys())


def _find_live_scope_keys() -> set[str]:
    from app.live_scope import LIVE_SETTINGS_MENU_KEYS

    return set(LIVE_SETTINGS_MENU_KEYS)


def _find_module_registry_anchor_keys() -> set[str]:
    from app.services.settings.module_registry import get_module_registry

    return {e.anchor_menu_key for e in get_module_registry() if e.anchor_menu_key}


def _declared_menu_keys() -> dict[str, list[str]]:
    from app.menu_registry import MENU_SECTIONS

    declared: dict[str, list[str]] = {}
    for section in MENU_SECTIONS:
        for item in section.get("items", []):
            key = item.get("key")
            if key:
                declared.setdefault(key, []).append(str(section.get("key")))
    return declared


def _consumed_key_sets() -> dict[str, set[str]]:
    return {
        "menu_key_required": _find_menu_key_required_keys(),
        "can_access_menu": _find_can_access_menu_keys(),
        "menu_map_get": _find_menu_map_get_keys(),
        "tuple_list_required": _find_tuple_list_required_keys(),
        "role_menu_defaults": _find_role_menu_defaults_keys(),
        "force_visible": _find_force_visible_keys(),
        "live_scope": _find_live_scope_keys(),
        "module_registry_anchor": _find_module_registry_anchor_keys(),
    }


def test_zero_duplicate_menu_keys_repo_wide() -> None:
    from collections import Counter

    from app.menu_registry_data_sections import MENU_SECTIONS

    keys = [
        item.get("key")
        for section in MENU_SECTIONS
        for item in section.get("items", [])
        if item.get("key")
    ]
    duplicates = {k: c for k, c in Counter(keys).items() if c > 1}
    assert not duplicates, f"repo-wide duplicate menu keys found: {duplicates}"


def test_zero_orphan_menu_keys_repo_wide() -> None:
    """Every declared MENU_SECTIONS key must be consumed by at least one of
    the 8 real authorization patterns this codebase actually uses."""
    declared = _declared_menu_keys()
    consumed_sets = _consumed_key_sets()
    all_consumed: set[str] = set()
    for s in consumed_sets.values():
        all_consumed.update(s)

    orphans = sorted(k for k in declared if k not in all_consumed)
    assert orphans == [], (
        f"ORPHAN_MENU_KEYS found (declared in MENU_SECTIONS, consumed nowhere): {orphans}"
    )


def test_settings_center_v2_own_keys_are_registered_and_consumed() -> None:
    """The 11 keys this project introduced must each hit at least one real
    consumption pattern -- narrower, stronger version of the repo-wide
    check above, scoped to prove THIS project's own contribution is clean."""
    declared = _declared_menu_keys()
    consumed_sets = _consumed_key_sets()
    all_consumed: set[str] = set()
    for s in consumed_sets.values():
        all_consumed.update(s)

    own_keys = {
        "settings_center_home", "settings_center_personnel_hr", "settings_center_portal",
        "settings_center_communication", "settings_center_surveys", "settings_center_support",
        "settings_center_virtual_assistant", "settings_center_dashboard",
        "settings_center_notifications", "settings_center_scheduled_jobs", "settings_center_security",
    }
    assert own_keys <= declared.keys()
    unconsumed = sorted(own_keys - all_consumed)
    assert unconsumed == [], f"Settings Center V2 keys with zero consumption: {unconsumed}"


def test_zero_orphan_settings_centers() -> None:
    """Every module_registry.py anchor_menu_key must correspond to a real,
    declared MENU_SECTIONS key -- no settings-center page may point at a
    menu key that doesn't exist."""
    declared = _declared_menu_keys()
    anchors = _find_module_registry_anchor_keys()
    orphans = sorted(k for k in anchors if k not in declared)
    assert orphans == [], f"ORPHAN_SETTINGS_CENTERS found: {orphans}"


def test_zero_active_orphan_auth_keys_repo_wide() -> None:
    """CLOSURE: all 5 previously-documented ORPHAN_AUTH_KEYs
    (about_bys360, executive_summary, support, reports,
    performance_history_import) are now resolved -- about_bys360's dead
    code was deleted (excluded by that canonical removal, not an ad hoc
    test exception), support now reuses the existing support_all key, and
    executive_summary/reports/performance_history_import are registered
    using only pre-existing project evidence (see module docstring). This
    is the blanket, unscoped assertion -- ACTIVE_ORPHAN_AUTH_KEYS must stay
    at 0 for every current and future menu_key_required(...)/
    can_access_menu(...) literal in the repo, not just the 5 originally
    found."""
    declared = _declared_menu_keys()
    consumed_sets = _consumed_key_sets()
    auth_keys = consumed_sets["menu_key_required"] | consumed_sets["can_access_menu"]
    orphan_auth_keys = sorted(k for k in auth_keys if k not in declared)

    assert orphan_auth_keys == [], (
        f"ACTIVE_ORPHAN_AUTH_KEYS found: {orphan_auth_keys} -- a route decorator or direct "
        "authorization call references a menu key with no matching MENU_SECTIONS declaration, "
        "meaning it fail-closes to 403 for every role including admin. Either register the key "
        "(reusing an existing semantically-equivalent one if the capability already exists "
        "elsewhere) or remove the dead reference -- do not leave it undefined."
    )


def test_about_bys360_dead_code_was_removed_not_resurrected() -> None:
    """Pins the about_bys360 removal so it can never silently reappear:
    the route, its handler, and its template must all stay absent."""
    assert not (REPO_ROOT / "app" / "about").exists(), "app/about/ was deleted as confirmed dead code -- must stay removed"
    assert not (REPO_ROOT / "app" / "main_handlers" / "about_handlers.py").exists()
    assert not (REPO_ROOT / "app" / "templates" / "about_bys360.html").exists()
    for text in _ALL_TEXT.values():
        assert "about_bys360_handler" not in text, "about_bys360_handler must not be reintroduced"


def test_settings_center_v2_introduces_zero_orphan_auth_keys() -> None:
    """None of this project's own 11 new /settings-center/* routes may use
    an undefined menu_key_required(...) key -- the project-scoped guarantee
    underlying the repo-wide pin above."""
    settings_center_routes_text = (REPO_ROOT / "app" / "settings_center" / "routes.py").read_text(encoding="utf-8")
    used_keys = set(_MENU_KEY_REQUIRED_RE.findall(settings_center_routes_text))
    assert used_keys, "expected at least one menu_key_required(...) call in app/settings_center/routes.py"

    declared = _declared_menu_keys()
    orphans = sorted(k for k in used_keys if k not in declared)
    assert orphans == [], f"app/settings_center/routes.py uses undefined menu key(s): {orphans}"


_ORPHAN_AUTH_CLOSURE_ROUTES = (
    "/dashboard/yonetici-ozeti",          # executive_summary
    "/communication/faz4",                # reports (dashboard)
    "/communication/faz5/health",         # reports
    "/communication/faz5/audit-logs",     # reports
    "/performance/import/history",        # performance_history_import
    "/communication/faz3/support/queue",  # support -> support_all
    "/communication/faz5/support-operations",  # support -> support_all
)


def test_all_five_orphan_auth_keys_are_now_resolved_for_admin(app) -> None:
    """CLOSURE proof: a real logged-in admin gets 200 (not 403) on every
    route that used to be locked out by an undefined menu key, through
    this project's own established _make_app/_create_user test pattern --
    not just trusting the registry-level assertions above."""
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no="ORPHANAUTHADMIN1",
            email="orphanauthadmin1@ktb.gov.tr",
            ad="OrphanAuth",
            soyad="Contract",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("orphan-auth-test-pw-1")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    login = client.post(
        "/login",
        data={"sicil_or_email": "ORPHANAUTHADMIN1", "password": "orphan-auth-test-pw-1"},
        follow_redirects=False,
    )
    assert login.status_code == 302, "test admin login must succeed before probing the fixed routes"

    for path in _ORPHAN_AUTH_CLOSURE_ROUTES:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, (
            f"{path}: expected 200 for admin now that its menu key is registered; got "
            f"{resp.status_code}. If this regresses to 403, the orphan-auth-key closure broke."
        )


def test_orphan_auth_closure_did_not_broaden_access_beyond_manager_tier(app) -> None:
    """SECURITY DELTA proof: a non-manager role (personel) must still get
    403 on every route the closure fixed for admin -- proves the fix was
    NARROWER-than-open (registers the already-documented/already-enforced
    role policy) rather than accidentally granting everyone access."""
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no="ORPHANAUTHPERS1",
            email="orphanauthpers1@ktb.gov.tr",
            ad="OrphanAuth",
            soyad="Personnel",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("orphan-auth-test-pw-2")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    login = client.post(
        "/login",
        data={"sicil_or_email": "ORPHANAUTHPERS1", "password": "orphan-auth-test-pw-2"},
        follow_redirects=False,
    )
    assert login.status_code == 302, "test personnel login must succeed before probing the fixed routes"

    for path in _ORPHAN_AUTH_CLOSURE_ROUTES:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 403, (
            f"{path}: expected 403 for a non-manager role (personel) -- if this is now 200, "
            "the orphan-auth-key closure broadened access beyond the documented/already-enforced "
            "policy, which is exactly what this mandate prohibited."
        )

    for path in ("/communication/faz4", "/performance/import/history"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 403, (
            f"{path}: expected 403 (documented pre-existing lockout via an undefined menu key); "
            f"got {resp.status_code}. If this is no longer 403, the pre-existing defect may have "
            "been fixed elsewhere -- update this test and the module docstring/pin above rather "
            "than leaving stale documentation."
        )


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-menu-authorization-integrity-audit")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    tmp_dir = Path(os.environ.get("TEMP") or "C:/pytest_short_tmp") / "bys360_menu_auth_audit"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_dir / f"menu_auth_audit_{uuid.uuid4().hex}.sqlite3"
    db_uri = "sqlite:///" + str(db_path).replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )

    from app.extensions import db

    with flask_app.app_context():
        db.create_all()

    return flask_app
