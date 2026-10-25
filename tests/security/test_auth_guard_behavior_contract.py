"""BYS360 RBAC / authorization guard behavior contract (TD-016).

Closes a real coverage/assurance gap in two production modules, neither of
which is touched or modified by this file:

- ``app/security/decorators.py`` (``role_required``, ``menu_visible_required``)
- ``app/route_support.py`` -- the security-critical subset only (this file's
  own scope is deliberately narrow, see ``SECURITY_RELEVANT_SYMBOLS`` below;
  unrelated helpers in the same large module -- form parsing, DB rollback
  wrappers, menu-registry bridges unrelated to access control -- are out of
  scope for TD-016 and are not exercised here on purpose):
  ``admin_required``, ``manager_required``, ``portal_editor_required``,
  ``_require_role_family``, ``user_has_any_role``, ``is_admin_family_user``,
  ``is_manager_family_user``, ``is_portal_editor_user``,
  ``normalize_role_name``, ``menu_key_required``, ``is_safe_redirect_target``,
  ``redirect_to_next_or``, ``render_access_denied``.

METHOD: every route-level assertion drives a REAL Flask `test_client()`
request against the REAL decorator/helper (registered on a throwaway
test-only probe route -- the same pattern already established in
``tests/security/test_csp_style3a_duplicate_block_extraction_contract.py``),
never a mock of the decorator itself. Pure-function helpers
(``user_has_any_role``, ``normalize_role_name``, role-family set membership)
are additionally exercised directly for precise edge-case coverage.

This file writes NOTHING to any production source file -- only its own
isolated, temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360_pytest_tmp_final" / "auth_guard_behavior_contract" / "test_dbs"

_PROBE_ROLE_REQUIRED_PATH = "/bys360-test-only/auth-guard/role-required-admin"
_PROBE_MENU_VISIBLE_PATH = "/bys360-test-only/auth-guard/menu-visible-required"
_PROBE_MENU_VISIBLE_RAISING_PATH = "/bys360-test-only/auth-guard/menu-visible-required-raising"
_PROBE_ADMIN_REQUIRED_PATH = "/bys360-test-only/auth-guard/admin-required"
_PROBE_MANAGER_REQUIRED_PATH = "/bys360-test-only/auth-guard/manager-required"
_PROBE_PORTAL_EDITOR_REQUIRED_PATH = "/bys360-test-only/auth-guard/portal-editor-required"
_PROBE_MENU_KEY_REQUIRED_PATH = "/bys360-test-only/auth-guard/menu-key-required"
_PROBE_REDIRECT_NEXT_PATH = "/bys360-test-only/auth-guard/redirect-next"

_MENU_KEY_UNDER_TEST = "bys360_test_only_menu_key_for_auth_guard_contract"

_PASSWORD = "AuthGuardContractTestKey1!"


class _RaisingPermsQuery:
    """Stand-in for a SQLAlchemy dynamic relationship whose `.all()` raises --
    proves menu_visible_required's real `except Exception` fallback branch."""

    def all(self):
        raise RuntimeError("auth-guard-contract: forced exception to prove fallback branch")


@pytest.fixture(scope="module")
def auth_guard_env(request):
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    db_uri = "sqlite:///" + db_path.as_posix()

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-auth-guard-behavior-contract-min-length-ok")
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
    request.addfinalizer(lambda: release_sqlite_app(app))
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

    from app.route_support import (
        admin_required,
        manager_required,
        menu_key_required,
        portal_editor_required,
        redirect_to_next_or,
    )
    from app.security.decorators import menu_visible_required, role_required

    @app.route(_PROBE_ROLE_REQUIRED_PATH, methods=["GET"])
    @role_required("admin")
    def _probe_role_required():
        return "role-required-ok", 200

    @app.route(_PROBE_MENU_VISIBLE_PATH, methods=["GET"])
    @menu_visible_required(_MENU_KEY_UNDER_TEST)
    def _probe_menu_visible_required():
        return "menu-visible-ok", 200

    @app.route(_PROBE_MENU_VISIBLE_RAISING_PATH, methods=["GET"])
    @menu_visible_required(_MENU_KEY_UNDER_TEST)
    def _probe_menu_visible_required_raising():
        return "menu-visible-fallback-ok", 200

    @app.route(_PROBE_ADMIN_REQUIRED_PATH, methods=["GET"])
    @admin_required
    def _probe_admin_required():
        return "admin-required-ok", 200

    @app.route(_PROBE_MANAGER_REQUIRED_PATH, methods=["GET"])
    @manager_required
    def _probe_manager_required():
        return "manager-required-ok", 200

    @app.route(_PROBE_PORTAL_EDITOR_REQUIRED_PATH, methods=["GET"])
    @portal_editor_required
    def _probe_portal_editor_required():
        return "portal-editor-required-ok", 200

    @app.route(_PROBE_MENU_KEY_REQUIRED_PATH, methods=["GET"])
    @menu_key_required(_MENU_KEY_UNDER_TEST)
    def _probe_menu_key_required():
        return "menu-key-required-ok", 200

    @app.route(_PROBE_REDIRECT_NEXT_PATH, methods=["GET", "POST"])
    def _probe_redirect_next():
        return redirect_to_next_or(default_endpoint="main.dashboard")

    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        db.create_all()

        def _make_user(sicil_no: str, role: str) -> int:
            user = User(
                sicil_no=sicil_no,
                email=f"{sicil_no}@ktb.gov.tr",
                ad="AuthGuard",
                soyad="Contract",
                role=role,
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            user.set_password(_PASSWORD)
            db.session.add(user)
            db.session.commit()
            return user.id

        admin_id = _make_user("authguard_admin", "admin")
        manager_id = _make_user("authguard_koord", "koordinator")
        birim_id = _make_user("authguard_birim", "birim_sorumlusu")
        personel_id = _make_user("authguard_pers", "personel")
        menu_hidden_id = _make_user("authguard_hidden", "personel")
        menu_visible_id = _make_user("authguard_visible", "personel")

        db.session.add(
            UserMenuPermission(user_id=menu_hidden_id, menu_key=_MENU_KEY_UNDER_TEST, is_visible=False, source_type="user_override")
        )
        db.session.add(
            UserMenuPermission(user_id=menu_visible_id, menu_key=_MENU_KEY_UNDER_TEST, is_visible=True, source_type="user_override")
        )
        db.session.commit()

    def _login(sicil_no: str):
        c = app.test_client()
        resp = c.post("/login", data={"sicil_or_email": sicil_no, "password": _PASSWORD}, follow_redirects=False)
        assert resp.status_code == 302, f"login failed for {sicil_no}: status={resp.status_code}"
        assert "/login" not in (resp.headers.get("Location") or ""), f"login failed for {sicil_no}: still redirected to /login"
        return c

    clients = {
        "admin": _login("authguard_admin"),
        "manager": _login("authguard_koord"),
        "birim": _login("authguard_birim"),
        "personel": _login("authguard_pers"),
        "menu_hidden": _login("authguard_hidden"),
        "menu_visible": _login("authguard_visible"),
        "anon": app.test_client(),
    }

    yield app, clients, {
        "admin": admin_id,
        "manager": manager_id,
        "birim": birim_id,
        "personel": personel_id,
    }

    mp.undo()


# ---------------------------------------------------------------------------
# app/security/decorators.py :: role_required
# ---------------------------------------------------------------------------


def test_role_required_unauthenticated_returns_401(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["anon"].get(_PROBE_ROLE_REQUIRED_PATH)
    assert response.status_code == 401


def test_role_required_authenticated_wrong_role_returns_403(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["personel"].get(_PROBE_ROLE_REQUIRED_PATH)
    assert response.status_code == 403


def test_role_required_authenticated_correct_role_returns_200(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(_PROBE_ROLE_REQUIRED_PATH)
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "role-required-ok"


# ---------------------------------------------------------------------------
# app/security/decorators.py :: menu_visible_required
# ---------------------------------------------------------------------------


def test_menu_visible_required_unauthenticated_returns_401(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["anon"].get(_PROBE_MENU_VISIBLE_PATH)
    assert response.status_code == 401


def test_menu_visible_required_no_permission_row_defaults_to_visible(auth_guard_env) -> None:
    """A user with zero UserMenuPermission rows for this key must be let
    through -- the source's `if menu_key in visible and not visible[menu_key]`
    only blocks when the key is EXPLICITLY present and False."""
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(_PROBE_MENU_VISIBLE_PATH)
    assert response.status_code == 200


def test_menu_visible_required_explicit_hidden_row_returns_403(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["menu_hidden"].get(_PROBE_MENU_VISIBLE_PATH)
    assert response.status_code == 403


def test_menu_visible_required_explicit_visible_row_returns_200(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["menu_visible"].get(_PROBE_MENU_VISIBLE_PATH)
    assert response.status_code == 200


def test_menu_visible_required_exception_during_iteration_falls_back_to_visible(auth_guard_env) -> None:
    """Negative/mutation contract: temporarily replaces the User model's
    `menu_permissions` class-level relationship with a plain property whose
    `.all()` raises -- proves the real `except Exception` branch in
    menu_visible_required falls back to an empty iterable (visible-by-
    default), not an unhandled 500. If this except branch were removed or
    the fallback broke, this request would 500 instead of 200."""
    _app, clients, _ids = auth_guard_env
    from app.models import User

    mp = pytest.MonkeyPatch()
    mp.setattr(User, "menu_permissions", property(lambda self: _RaisingPermsQuery()))
    try:
        response = clients["admin"].get(_PROBE_MENU_VISIBLE_RAISING_PATH)
        assert response.status_code == 200, (
            f"Expected graceful fallback to visible-by-default (200), got {response.status_code} -- "
            "the except Exception branch in menu_visible_required may have regressed."
        )
    finally:
        mp.undo()


# ---------------------------------------------------------------------------
# app/route_support.py :: admin_required / manager_required (role-family
# hierarchy: ADMIN_FAMILY_ROLES subset-of MANAGER_FAMILY_ROLES)
# ---------------------------------------------------------------------------


def test_admin_required_unauthenticated_redirects_to_login(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["anon"].get(_PROBE_ADMIN_REQUIRED_PATH, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in (response.headers.get("Location") or "")


def test_admin_required_insufficient_role_returns_403(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["personel"].get(_PROBE_ADMIN_REQUIRED_PATH)
    assert response.status_code == 403


def test_admin_required_admin_role_returns_200(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(_PROBE_ADMIN_REQUIRED_PATH)
    assert response.status_code == 200


def test_admin_required_manager_family_only_role_is_denied(auth_guard_env) -> None:
    """Proves the family boundary is real: birim_sorumlusu is in
    MANAGER_FAMILY_ROLES but NOT in ADMIN_FAMILY_ROLES -- if admin_required
    accidentally used the broader manager set, this would wrongly pass."""
    _app, clients, _ids = auth_guard_env
    response = clients["birim"].get(_PROBE_ADMIN_REQUIRED_PATH)
    assert response.status_code == 403


def test_manager_required_admin_role_passes(auth_guard_env) -> None:
    """ADMIN_FAMILY_ROLES is a subset of MANAGER_FAMILY_ROLES -- an admin
    must also pass the (broader) manager gate."""
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(_PROBE_MANAGER_REQUIRED_PATH)
    assert response.status_code == 200


def test_manager_required_birim_sorumlusu_passes(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["birim"].get(_PROBE_MANAGER_REQUIRED_PATH)
    assert response.status_code == 200


def test_manager_required_personel_denied(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["personel"].get(_PROBE_MANAGER_REQUIRED_PATH)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# app/route_support.py :: portal_editor_required
# ---------------------------------------------------------------------------


def test_portal_editor_required_admin_passes(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(_PROBE_PORTAL_EDITOR_REQUIRED_PATH)
    assert response.status_code == 200


def test_portal_editor_required_koordinator_passes(auth_guard_env) -> None:
    """PORTAL_EDITOR_ROLES = ADMIN_FAMILY_ROLES | {koordinator}."""
    _app, clients, _ids = auth_guard_env
    response = clients["manager"].get(_PROBE_PORTAL_EDITOR_REQUIRED_PATH)
    assert response.status_code == 200


def test_portal_editor_required_birim_sorumlusu_denied(auth_guard_env) -> None:
    """birim_sorumlusu is in MANAGER_FAMILY_ROLES but NOT in
    PORTAL_EDITOR_ROLES -- proves this is a genuinely narrower set, not an
    alias for manager_required."""
    _app, clients, _ids = auth_guard_env
    response = clients["birim"].get(_PROBE_PORTAL_EDITOR_REQUIRED_PATH)
    assert response.status_code == 403


def test_portal_editor_required_unauthenticated_redirects_to_login(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["anon"].get(_PROBE_PORTAL_EDITOR_REQUIRED_PATH, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in (response.headers.get("Location") or "")


# ---------------------------------------------------------------------------
# app/route_support.py :: menu_key_required (boundary only -- the full menu
# visibility resolution chain belongs to app/services/settings/effective_menu.py,
# out of this wave's TD-016 scope)
# ---------------------------------------------------------------------------


def test_menu_key_required_unauthenticated_redirects_to_login(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["anon"].get(_PROBE_MENU_KEY_REQUIRED_PATH, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in (response.headers.get("Location") or "")


# ---------------------------------------------------------------------------
# app/route_support.py :: is_safe_redirect_target / redirect_to_next_or
# ---------------------------------------------------------------------------


def test_redirect_to_next_or_preserves_safe_relative_next(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(f"{_PROBE_REDIRECT_NEXT_PATH}?next=/some/safe/internal/path", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers.get("Location") == "/some/safe/internal/path"


def test_redirect_to_next_or_rejects_protocol_relative_next_and_falls_back(auth_guard_env) -> None:
    """Negative contract: a `//evil.example.com/phish` next target must NEVER
    be honored -- if is_safe_redirect_target's safety check regressed to
    accept protocol-relative URLs, this test would fail."""
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(f"{_PROBE_REDIRECT_NEXT_PATH}?next=//evil.example.com/phish", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers.get("Location") or ""
    assert "evil.example.com" not in location, f"Unsafe next target was honored: {location!r}"


def test_redirect_to_next_or_rejects_absolute_external_url_and_falls_back(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(f"{_PROBE_REDIRECT_NEXT_PATH}?next=https://evil.example.com/phish", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers.get("Location") or ""
    assert "evil.example.com" not in location, f"Unsafe next target was honored: {location!r}"


def test_redirect_to_next_or_missing_next_falls_back_to_default(auth_guard_env) -> None:
    _app, clients, _ids = auth_guard_env
    response = clients["admin"].get(_PROBE_REDIRECT_NEXT_PATH, follow_redirects=False)
    assert response.status_code == 302
    location = response.headers.get("Location") or ""
    assert "evil" not in location
    assert location != ""


# ---------------------------------------------------------------------------
# Direct pure-function edge cases (no HTTP layer needed) -- precise coverage
# of user_has_any_role / normalize_role_name / role-family set membership.
# ---------------------------------------------------------------------------


def test_normalize_role_name_lowercases_and_strips_whitespace() -> None:
    from app.route_support import normalize_role_name

    assert normalize_role_name("  Admin  ") == "admin"
    assert normalize_role_name("KOORDINATOR") == "koordinator"
    assert normalize_role_name(None) == ""


def test_user_has_any_role_rejects_unauthenticated_namespace_object() -> None:
    import types

    from app.route_support import user_has_any_role

    fake_user = types.SimpleNamespace(is_authenticated=False, role="admin")
    assert user_has_any_role(fake_user, {"admin"}) is False


def test_user_has_any_role_matches_case_insensitively() -> None:
    import types

    from app.route_support import user_has_any_role

    fake_user = types.SimpleNamespace(is_authenticated=True, role="  ADMIN  ")
    assert user_has_any_role(fake_user, {"admin"}) is True


def test_user_has_any_role_rejects_role_outside_allowed_set() -> None:
    import types

    from app.route_support import user_has_any_role

    fake_user = types.SimpleNamespace(is_authenticated=True, role="personel")
    assert user_has_any_role(fake_user, {"admin", "koordinator"}) is False


def test_admin_family_roles_role_hierarchy_membership_lock() -> None:
    """Mutation-like lock on the role-family sets themselves: if any of
    these memberships silently changed, this fails before any route-level
    symptom would ever be noticed."""
    from app.route_support import ADMIN_FAMILY_ROLES, MANAGER_FAMILY_ROLES, PORTAL_EDITOR_ROLES

    assert {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir"} == ADMIN_FAMILY_ROLES
    assert ADMIN_FAMILY_ROLES.issubset(MANAGER_FAMILY_ROLES)
    assert {"birim_sorumlusu", "koordinator"} == MANAGER_FAMILY_ROLES - ADMIN_FAMILY_ROLES
    assert {"koordinator"} == PORTAL_EDITOR_ROLES - ADMIN_FAMILY_ROLES
    assert "birim_sorumlusu" not in PORTAL_EDITOR_ROLES


def test_is_admin_family_and_is_manager_family_helpers_agree_with_role_sets() -> None:
    import types

    from app.route_support import is_admin_family_user, is_manager_family_user

    admin_like = types.SimpleNamespace(is_authenticated=True, role="admin")
    birim_like = types.SimpleNamespace(is_authenticated=True, role="birim_sorumlusu")
    personel_like = types.SimpleNamespace(is_authenticated=True, role="personel")

    assert is_admin_family_user(admin_like) is True
    assert is_manager_family_user(admin_like) is True

    assert is_admin_family_user(birim_like) is False
    assert is_manager_family_user(birim_like) is True

    assert is_admin_family_user(personel_like) is False
    assert is_manager_family_user(personel_like) is False
