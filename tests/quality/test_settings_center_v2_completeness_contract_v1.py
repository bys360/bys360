"""BYS360 SETTINGS CENTER V2 -- completeness / fail-closed authorization contract.

Proves the invariants the Settings Center V2 project exists to guarantee:

  - every module in the new registry (app.services.settings.module_registry)
    has a real Settings Center page, and that page actually resolves via
    url_for (no orphan settings_endpoint names);
  - every new Settings Center route is gated by menu_key_required, using the
    SAME live menu-visibility resolver that drives the sidebar (not a
    separate, competing authorization mechanism) -- so denying a menu key
    denies both the sidebar item and the route, and a fully undefined
    menu_key is always denied, never silently allowed, even for admin;
  - no duplicate module_key or menu_key entered the registries this project
    touched;
  - a DB-level override (RoleMenuDefault) still wins over the static
    code-level default this project seeded, proving the existing
    role->unit->user precedence chain was not bypassed by this addition.

This file does NOT re-test or re-verify the pre-existing ~15-function
effective_menu_parts resolution pipeline itself (see
app/services/settings/module_registry.py's module docstring for why that
was deliberately left untouched) -- only the NEW registry/routes/menu
entries this project added, and their observable behavior through the
existing resolver.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

pytestmark = pytest.mark.ci_safe

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "settings_center_v2_tmp" / "test_dbs"
_PASSWORD = "SettingsCenterV2Test1!"


# ---------------------------------------------------------------------------
# A: pure-registry contracts (no app required).
# ---------------------------------------------------------------------------


def test_no_duplicate_module_keys_in_registry() -> None:
    from app.services.settings.module_registry import find_duplicate_module_keys

    assert find_duplicate_module_keys() == []


def test_no_orphan_settings_endpoints_in_registry() -> None:
    """Every module claiming settings_available=True must name a real
    endpoint -- settings_available=True with settings_endpoint=None would be
    exactly the kind of fabricated completeness this project must not produce."""
    from app.services.settings.module_registry import find_orphan_settings_endpoints

    assert find_orphan_settings_endpoints() == []


def test_no_active_module_missing_a_settings_center() -> None:
    """MISSING_SETTINGS_CENTERS_AFTER = 0 -- the project's own target."""
    from app.services.settings.module_registry import list_modules_missing_settings_center

    missing = list_modules_missing_settings_center()
    assert missing == [], f"active modules still missing a Settings Center: {[m.module_key for m in missing]}"


def test_registry_covers_the_discovered_real_modules() -> None:
    """Every module_key this project's own inventory confirmed as real,
    active source code must be present -- not a hint-list name that was
    never verified against actual code (e.g. no 'reporting' module_key,
    since no standalone Raporlama blueprint exists)."""
    from app.services.settings.module_registry import get_module_registry

    keys = {m.module_key for m in get_module_registry()}
    expected = {
        "personnel_hr", "performance_mgmt", "portal", "file_center", "communication",
        "surveys", "support_help", "ai_decision_support", "virtual_assistant", "dashboard",
        "settings_auth", "notifications", "email_automation", "scheduled_jobs",
        "security_session", "audit",
    }
    assert expected.issubset(keys)
    assert "reporting" not in keys, "no standalone Raporlama module exists in real source -- must not be fabricated"


def test_settings_center_v2_introduces_no_duplicate_menu_keys() -> None:
    """Regression guard for the exact class of bug this project's own
    research found real instances of elsewhere (two functions sharing a
    name): none of this project's 11 new settings_center_* menu_key entries
    may collide with each other or with any pre-existing menu_key.

    Scoped to keys this project added. See
    test_repo_wide_menu_sections_have_zero_duplicate_keys below for the
    blanket "zero duplicates anywhere in MENU_SECTIONS" assertion -- that
    broader check used to fail on one real, PRE-EXISTING duplicate
    ("ai_agent_panel", defined once in the "genel" section and again,
    separately, in a section named "assistant"); closed by removing the
    "genel" section's copy (see app/menu_registry.py's
    _BYS360_AY1_AI_AGENT_MENU_ITEMS, "Blocker 2" comment) since both copies
    pointed at the exact same endpoint/href and had already converged to the
    same effective required_roles -- one capability, registered once."""
    from app.menu_registry_data_sections import MENU_SECTIONS

    new_keys = {
        "settings_center_home", "settings_center_personnel_hr", "settings_center_portal",
        "settings_center_communication", "settings_center_surveys", "settings_center_support",
        "settings_center_virtual_assistant", "settings_center_dashboard",
        "settings_center_notifications", "settings_center_scheduled_jobs", "settings_center_security",
    }

    counts: dict[str, int] = {}
    for section in MENU_SECTIONS:
        for item in section.get("items", []):
            key = item.get("key")
            if key:
                counts[key] = counts.get(key, 0) + 1

    offending = {k: n for k, n in counts.items() if k in new_keys and n > 1}
    assert offending == {}, f"Settings Center V2 keys duplicated: {offending}"


def test_ai_agent_panel_duplicate_is_fixed_to_exactly_one_registration() -> None:
    """Regression guard for the pre-existing 'ai_agent_panel' duplicate found
    during this project's own completeness work: it used to appear twice
    (once in the "genel" section, label "BYS360 Asistanı"; once in the
    "assistant" section, label "Asistan Paneli"), both resolving to the same
    endpoint/href with the same effective required_roles. Fixed by removing
    the "genel" section's copy (app/menu_registry.py's
    _BYS360_AY1_AI_AGENT_MENU_ITEMS). This test pins the key stays at
    exactly 1 registration, in the "assistant" section, with its
    authorization unchanged from before the fix."""
    from app.menu_registry_data_sections import MENU_SECTIONS

    matches = [
        (section.get("key"), item)
        for section in MENU_SECTIONS
        for item in section.get("items", [])
        if item.get("key") == "ai_agent_panel"
    ]
    assert len(matches) == 1, (
        f"expected 'ai_agent_panel' to resolve to exactly 1 registration after the Blocker 2 fix, "
        f"found {len(matches)}: {matches}"
    )
    section_key, item = matches[0]
    assert section_key == "assistant"
    assert item.get("endpoint") == "ai_agent.ai_agent_panel"
    assert item.get("href") == "/ai-agent/panel"
    assert set(item.get("required_roles") or []) == {
        "admin", "baskan", "baskan_yardimcisi", "grup_baskani",
        "mali_musavir", "koordinator", "birim_sorumlusu", "personel",
    }


def test_repo_wide_menu_sections_have_zero_duplicate_keys() -> None:
    """Blanket 'zero duplicates anywhere in MENU_SECTIONS' assertion. This
    used to fail on the pre-existing 'ai_agent_panel' duplicate (see the
    test above); now that it's fixed, this holds repo-wide, not just for
    this project's own 11 new keys."""
    from collections import Counter

    from app.menu_registry_data_sections import MENU_SECTIONS

    keys = [
        item.get("key")
        for section in MENU_SECTIONS
        for item in section.get("items", [])
        if item.get("key")
    ]
    duplicates = {key: count for key, count in Counter(keys).items() if count > 1}
    assert not duplicates, f"repo-wide duplicate menu keys found: {duplicates}"


def test_ai_agent_panel_visibility_preserved_after_duplicate_fix(app) -> None:
    """Proves the Blocker 2 duplicate-key fix caused no lockout and no
    accidental permission expansion, through the REAL resolver (not just
    the static required_roles list): a role that was authorized before the
    fix ("personel") is still authorized; a role that was already denied by
    the pre-fix override ("super_admin", never actually granted since
    _BYS360_ALL_MENU_ROLE_MATRIX_MENU_ATTRS downgraded both pre-fix copies
    to the same 8-role set) remains denied."""
    from app.route_support import can_access_menu

    personnel_id = _create_user(app, sicil_no="SCV2AIPANEL1", role="personel")
    super_admin_id = _create_user(app, sicil_no="SCV2AIPANEL2", role="super_admin")
    with app.app_context():
        from app.models import User

        personnel = User.query.get(personnel_id)
        super_admin = User.query.get(super_admin_id)

        assert can_access_menu(personnel, "ai_agent_panel") is True, (
            "personel role lost access to ai_agent_panel after the duplicate-key fix"
        )
        assert can_access_menu(super_admin, "ai_agent_panel") is False, (
            "super_admin role unexpectedly gained access to ai_agent_panel -- "
            "this role was already excluded by the pre-fix role-matrix override, "
            "so the duplicate-key fix must not have changed that"
        )


def test_settings_center_v2_menu_keys_are_registered_and_admin_gated() -> None:
    from app.menu_registry_data_sections import MENU_SECTIONS

    section = next((s for s in MENU_SECTIONS if s.get("key") == "settings_center_v2"), None)
    assert section is not None, "settings_center_v2 section missing from MENU_SECTIONS"
    keys = {item["key"] for item in section["items"]}
    assert keys == {
        "settings_center_home", "settings_center_personnel_hr", "settings_center_portal",
        "settings_center_communication", "settings_center_surveys", "settings_center_support",
        "settings_center_virtual_assistant", "settings_center_dashboard",
        "settings_center_notifications", "settings_center_scheduled_jobs", "settings_center_security",
    }
    for item in section["items"]:
        assert item.get("required_roles"), f"{item['key']} has no required_roles restriction"
        assert "admin" in item["required_roles"]
        assert "personel" not in item["required_roles"]


def test_settings_center_v2_menu_keys_are_in_live_scope() -> None:
    """Regression guard for the exact defect found and fixed mid-project:
    a menu_key absent from LIVE_SETTINGS_MENU_KEYS is silently filtered out
    of flatten_menu_definitions()/get_grouped_menu_definitions(), which
    means role defaults are NEVER applied to it -- even a role explicitly
    granted the key in ROLE_MENU_DEFAULTS stays permanently denied."""
    from app.live_scope import LIVE_SETTINGS_MENU_KEYS

    expected = {
        "settings_center_home", "settings_center_personnel_hr", "settings_center_portal",
        "settings_center_communication", "settings_center_surveys", "settings_center_support",
        "settings_center_virtual_assistant", "settings_center_dashboard",
        "settings_center_notifications", "settings_center_scheduled_jobs", "settings_center_security",
    }
    assert expected.issubset(LIVE_SETTINGS_MENU_KEYS)


def test_settings_center_v2_route_paths_do_not_collide_with_assistant_gate() -> None:
    """Regression guard for the real bug found and fixed mid-project:
    app.services.assistant_module_access.ASSISTANT_PATH_KEYWORDS matches
    any request path containing "/virtual-assistant" (among others) and
    redirects it away for any user without assistant-module access -- a
    completely unrelated Settings Center V2 page must never collide with
    that substring."""
    from app.menu_registry_data_sections import MENU_SECTIONS
    from app.services.assistant_module_access import ASSISTANT_PATH_KEYWORDS

    section = next(s for s in MENU_SECTIONS if s.get("key") == "settings_center_v2")
    for item in section["items"]:
        for prefix in item.get("active_path_prefixes", []) or []:
            lowered = prefix.lower()
            colliding = [kw for kw in ASSISTANT_PATH_KEYWORDS if kw in lowered]
            assert colliding == [], f"{item['key']}'s path {prefix!r} collides with assistant gate keyword(s) {colliding}"


# ---------------------------------------------------------------------------
# B: app/DB-backed contracts.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-settings-center-v2-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "settings-center-v2-first-login-test-pw")
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
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role, password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="SettingsCenterV2",
            soyad="Contract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


_SETTINGS_CENTER_ROUTES = [
    "/settings-center",
    "/settings-center/personnel-hr",
    "/settings-center/portal",
    "/settings-center/communication",
    "/settings-center/surveys",
    "/settings-center/support",
    "/settings-center/ai-agent",
    "/settings-center/dashboard",
    "/settings-center/notifications",
    "/settings-center/scheduled-jobs",
    "/settings-center/security",
]


def test_admin_can_reach_every_settings_center_v2_route(app, client):
    _create_user(app, sicil_no="SCV2ADMIN", role="admin")
    _login(client, "SCV2ADMIN")
    for path in _SETTINGS_CENTER_ROUTES:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}, expected 200 for admin"
        assert "Bu sayfa gösterilirken bir hata oluştu" not in response.get_data(as_text=True), (
            f"{path} silently fell back to the generic template-error page"
        )


def test_non_admin_is_denied_every_settings_center_v2_route(app, client):
    """H: direct route access is denied when menu permission is false --
    proven for every single new route, not just a sample."""
    _create_user(app, sicil_no="SCV2PERS", role="personel")
    _login(client, "SCV2PERS")
    for path in _SETTINGS_CENTER_ROUTES:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 403, f"{path} -> {response.status_code}, expected 403 for a non-admin role"


def test_anonymous_is_redirected_to_login_for_every_settings_center_v2_route(app, client):
    for path in _SETTINGS_CENTER_ROUTES:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("Location", "")


def test_disabled_module_is_unreachable_even_with_menu_permission_granted(app, client, monkeypatch):
    """F: disabled module resolves FALSE at the ROUTE level, not just the
    sidebar -- an admin who still has the menu_key granted must not be able
    to reach a module the registry marks inactive via direct URL."""
    from app.services.settings.module_registry import MODULE_REGISTRY, ModuleRegistryEntry

    original = list(MODULE_REGISTRY)
    try:
        for i, entry in enumerate(MODULE_REGISTRY):
            if entry.module_key == "personnel_hr":
                MODULE_REGISTRY[i] = ModuleRegistryEntry(**{**entry.__dict__, "active": False})
                break
        else:
            pytest.fail("personnel_hr not found in MODULE_REGISTRY")

        _create_user(app, sicil_no="SCV2ADMIN4", role="admin")
        _login(client, "SCV2ADMIN4")
        response = client.get("/settings-center/personnel-hr", follow_redirects=False)
        assert response.status_code == 404, (
            f"expected 404 for a disabled module even with admin's menu_key granted, got {response.status_code}"
        )
    finally:
        MODULE_REGISTRY[:] = original
        assert original == MODULE_REGISTRY


def test_undefined_menu_key_resolves_false_even_for_admin(app):
    """E + I: an unregistered menu_key must resolve to denied -- for
    EVERY role, including admin. Undefined must never mean allowed."""
    from app.route_support import can_access_menu

    with app.test_request_context("/"):
        pass

    admin_id = _create_user(app, sicil_no="SCV2ADMIN2", role="admin")
    with app.app_context():
        from app.models import User

        admin = User.query.get(admin_id)
        assert can_access_menu(admin, "this_menu_key_was_never_registered_anywhere_xyz") is False


def test_db_role_override_wins_over_static_default_for_new_keys(app):
    """J: proves role->unit->user precedence was not bypassed by this
    project's additions -- an explicit DB-level RoleMenuDefault row set to
    False for admin on one of the new keys must actually deny admin,
    overriding the static code-level default this project seeded in
    menu_registry_data_performance.py."""
    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault
    from app.route_support import can_access_menu

    admin_id = _create_user(app, sicil_no="SCV2ADMIN3", role="admin")
    with app.app_context():
        from app.models import User

        admin = User.query.get(admin_id)
        # Precondition: the static default grants this key.
        assert can_access_menu(admin, "settings_center_security") is True

        db.session.add(RoleMenuDefault(role_name="admin", menu_key="settings_center_security", is_visible=False, source_type="test_override"))
        db.session.commit()

        assert can_access_menu(admin, "settings_center_security") is False, (
            "an explicit DB role-default override must win over the static code-level default"
        )


def test_settings_center_v2_section_hidden_from_sidebar_when_all_children_denied(app):
    """G: parent group with zero visible children must not render."""
    from app.menu_registry import build_sidebar_menu_sections
    from app.services.settings.effective_menu import build_menu_visibility_map

    _create_user(app, sicil_no="SCV2PERS2", role="personel")
    with app.test_request_context("/dashboard"):
        from app.models import User

        personnel = User.query.filter_by(sicil_no="SCV2PERS2").first()
        visibility = build_menu_visibility_map(personnel)
        sections = build_sidebar_menu_sections(visibility, "main.dashboard", "/dashboard", user=personnel)
        section_keys = {s.get("key") for s in sections}
        assert "settings_center_v2" not in section_keys, (
            "settings_center_v2 sidebar section rendered even though every child menu_key is denied for this role"
        )


def test_settings_center_v2_endpoints_all_resolve_via_url_for(app):
    """M: no orphan settings center -- every settings_endpoint named in the
    registry must be a real, resolvable Flask endpoint."""
    from app.services.settings.module_registry import get_module_registry

    with app.test_request_context("/"):
        from flask import url_for

        for entry in get_module_registry():
            if entry.settings_available and entry.settings_endpoint:
                url_for(entry.settings_endpoint)  # raises BuildError if orphaned


def test_registry_anchor_menu_keys_exist_in_menu_sections(app):
    """N: no orphan authorization key -- every anchor_menu_key the registry
    names must be a real, registered menu_key."""
    from app.menu_registry_data_sections import MENU_SECTIONS
    from app.services.settings.module_registry import get_module_registry

    all_menu_keys: set[str] = set()
    for section in MENU_SECTIONS:
        for item in section.get("items", []):
            if item.get("key"):
                all_menu_keys.add(item["key"])

    for entry in get_module_registry():
        if entry.anchor_menu_key:
            assert entry.anchor_menu_key in all_menu_keys, (
                f"{entry.module_key}'s anchor_menu_key {entry.anchor_menu_key!r} is not a registered menu_key"
            )
