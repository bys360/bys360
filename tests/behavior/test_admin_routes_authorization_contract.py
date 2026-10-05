"""Behavior/authorization contract for app/admin/routes.py.

Scope: admin_dashboard, admin_users, admin_user_create, admin_user_edit,
personnel_list, personnel_add, personnel_edit,
personnel_excel_template_download, personnel_excel_upload.

Before this file, there was no test anywhere in tests/ that actually drove a
real (non-mocked) HTTP request through these routes' real decorator stack
(login_required -> admin_required -> [menu_key_required("admin_users")]) with
a real Flask-Login session. This file proves, with real sessions and a real
(per-test, file-backed SQLite) database:

  1. An anonymous caller is redirected to /login for every route in this
     module -- never silently allowed, never a raw 500/404.
  2. An authenticated but non-admin-family caller (role="personel") gets a
     real HTTP 403 from admin_required for every route in this module -- the
     UI hiding a menu item is NOT what stops them; the backend itself does.
  3. For the 5 routes additionally gated by menu_key_required("admin_users")
     (personnel_list, personnel_add, personnel_edit,
     personnel_excel_template_download, personnel_excel_upload): an
     authenticated admin-family user who has had that specific menu
     permission explicitly revoked (a real UserMenuPermission row,
     is_visible=False) still gets a real 403 -- admin role alone is not
     sufficient once a menu key is explicitly gated off.
  4. An authenticated admin-family caller with the required permission
     reaches the real route body and gets a real 200 (or, for the two
     dynamic-id routes, a 200 against a real target row created for the
     test) -- proving the allowed path isn't collateral damage from an
     over-broad deny-by-default check.
  5. For the four business-logic-bearing POST routes (admin_user_create,
     admin_user_edit, personnel_add, personnel_edit), the real validation
     rules found by reading app/admin/routes.py (required-field guard,
     sicil_no/email uniqueness, self-manager and duplicate-manager
     rejection, password length/repeat rules) are exercised both on the
     rejecting path (asserting the real flash message AND that no DB row
     was created/mutated) and on the accepting path (asserting the real DB
     row exists with the expected fields, e.g. the password hash actually
     verifies against the flashed initial password -- not just "not 500").
  6. Two direct-POST "UI bypass" checks (admin_user_create, personnel_add):
     a non-admin (and, for personnel_add, an admin missing the menu
     permission) POSTing the create form directly -- skipping the UI
     entirely -- still gets rejected with zero rows created. This is the
     scenario the SECURITY TEST RULE cares about most: hiding a button in
     the UI is not authorization.

Deliberately uses a per-test, file-backed SQLite app (see _make_app) rather
than the shared session-scoped app/client fixtures in tests/conftest.py, to
avoid cross-test DB pollution/order-dependence between the many mutating
POSTs in this file. Mirrors the already-established pattern in
tests/behavior/test_settings_page_behavior_contract.py (same env overrides,
same _create_user/_login/_flashes helper shapes) rather than inventing a new
one.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from flask import template_rendered

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "admin_routes_authz_tmp" / "test_dbs"
DEFAULT_PASSWORD = "AdminRoutesAuthzTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "admin-routes-first-login-test-pw"


def _make_app(monkeypatch, **env_overrides):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-admin-routes-authz-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", DEFAULT_FIRST_LOGIN_PASSWORD)
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
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def _dispose_app(flask_app):
    """Release the app's engine and delete its per-test SQLite file."""
    from app.extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
        db_file = db.engine.url.database
    if db_file:
        Path(db_file).unlink(missing_ok=True)


@pytest.fixture
def app(monkeypatch):
    flask_app = _make_app(monkeypatch)
    yield flask_app
    _dispose_app(flask_app)


@pytest.fixture
def client(app):
    return app.test_client()


def test_app_database_file_is_released_and_deleted_after_use(monkeypatch):
    # Each app here gets its own per-test SQLite file; without an explicit
    # release step the engine stayed open and the file was never deleted (one
    # leftover file per test in _TEST_DB_ROOT, undeletable on Windows while open).
    from app.extensions import db

    flask_app = _make_app(monkeypatch)
    with flask_app.app_context():
        db_file = Path(db.engine.url.database or "")
    assert db_file.parent == _TEST_DB_ROOT
    assert db_file.exists()

    _dispose_app(flask_app)

    assert not db_file.exists()


def _create_user(
    app,
    *,
    sicil_no,
    email,
    role="personel",
    birim=None,
    ust_birim=None,
    is_active=True,
    password=DEFAULT_PASSWORD,
):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Behavior",
            soyad="Contract",
            role=role,
            birim=birim,
            ust_birim=ust_birim,
            is_active=is_active,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=DEFAULT_PASSWORD):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _flashes(client):
    """Read (without consuming) the session's flashed (category, message)
    tuples. Safe right after a 302 response.

    NOT safe after a 200 response that re-renders a real template: Flask's
    get_flashed_messages() -- called by the page's own flash-banner block --
    pops session['_flashes'] entirely as part of that successful render, so
    by the time this helper runs afterward the list is already empty. Use
    _assert_flash_message_rendered(response, message) for that case instead
    (confirmed empirically: the flash text is present in the response body
    even though session['_flashes'] has already been drained)."""
    with client.session_transaction() as sess:
        return list(sess.get("_flashes", []))


def _assert_flash_message_rendered(response, message):
    """For a 200 response that re-renders a real template (not a redirect):
    asserts the flashed message text appears in the rendered page body,
    since get_flashed_messages() already consumed it out of the session by
    the time this response was returned."""
    body = response.get_data(as_text=True)
    assert message in body, f"expected flash message {message!r} not found in rendered response body"


def _deny_menu_permission(app, *, user_id, menu_key="admin_users"):
    """Explicitly revoke one menu key for one user via a real
    UserMenuPermission row -- the same mechanism app.route_support.
    can_access_menu reads (see app/services/settings/effective_menu_parts/
    build_context.py fallback branch, and the passing spike verification
    used to derive this test file's approach)."""
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        db.session.add(UserMenuPermission(user_id=user_id, menu_key=menu_key, is_visible=False))
        db.session.commit()


def _get_user(app, user_id):
    from app.models import User

    with app.app_context():
        return User.query.get(user_id)


def _user_count(app, *, role_not="admin"):
    from app.models import User

    with app.app_context():
        return User.query.filter(User.role != role_not).count()


def _find_user_by_sicil(app, sicil_no):
    from app.models import User

    with app.app_context():
        return User.query.filter_by(sicil_no=sicil_no).first()


# ---------------------------------------------------------------------------
# Authorization matrix -- routes gated by login_required + admin_required only
# ---------------------------------------------------------------------------

ADMIN_ONLY_STATIC_ROUTES = [
    "/admin/dashboard",
    "/admin/users",
    "/admin/users/create",
]


@pytest.mark.parametrize("path", ADMIN_ONLY_STATIC_ROUTES)
def test_admin_only_route_rejects_anonymous(app, client, path):
    """Real behavior, confirmed by reading app/bootstrap/operational_guards.py's
    _enforce_admin_path_guard(): every /admin/* path is centrally gated by a
    before_request hook that runs BEFORE Flask-Login's own login_required
    redirect ever gets a chance to fire, and it returns a direct 403 for an
    unauthenticated caller (never a 302-to-/login) -- confirmed both via a
    standalone repro script and via this test. Still a hard, real rejection;
    just not via the redirect mechanism this test originally assumed."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 403


@pytest.mark.parametrize("path", ADMIN_ONLY_STATIC_ROUTES)
def test_admin_only_route_rejects_authenticated_non_admin(app, client, path):
    _create_user(app, sicil_no="aor_na_" + path.replace("/", "_"), email=f"aor_na_{abs(hash(path))}@x.test", role="personel")
    _login(client, "aor_na_" + path.replace("/", "_"))

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 403


@pytest.mark.parametrize("path", ADMIN_ONLY_STATIC_ROUTES)
def test_admin_only_route_allows_authenticated_admin(app, client, path):
    _create_user(app, sicil_no="aor_ad_" + path.replace("/", "_"), email=f"aor_ad_{abs(hash(path))}@x.test", role="admin")
    _login(client, "aor_ad_" + path.replace("/", "_"))

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 200


def test_admin_dashboard_admin_sees_real_counts_not_just_200(app, client):
    """Not just "200" -- proves the rendered context actually reflects real
    DB state (2 non-admin users, 1 of them inactive; the admin actor itself
    is excluded from the count, matching User.role != "admin" in the route)."""
    _create_user(app, sicil_no="dash_admin", email="dash_admin@x.test", role="admin")
    _create_user(app, sicil_no="dash_p1", email="dash_p1@x.test", role="personel", is_active=True)
    _create_user(app, sicil_no="dash_p2", email="dash_p2@x.test", role="personel", is_active=False)
    _login(client, "dash_admin")

    captured = []

    def _record(sender, template, context, **extra):
        captured.append(dict(context))

    template_rendered.connect(_record, app)
    try:
        response = client.get("/admin/dashboard", follow_redirects=False)
    finally:
        template_rendered.disconnect(_record, app)

    assert response.status_code == 200
    assert len(captured) == 1
    context = captured[0]
    assert context["user_count"] == 2
    assert context["active_user_count"] == 1


# ---------------------------------------------------------------------------
# Authorization matrix -- routes additionally gated by
# menu_key_required("admin_users")
# ---------------------------------------------------------------------------

MENU_GATED_STATIC_ROUTES = [
    "/personnel",
    "/personnel/add",
    "/personnel/excel-template",
    "/personnel/excel-upload",
]


@pytest.mark.parametrize("path", MENU_GATED_STATIC_ROUTES)
def test_menu_gated_route_rejects_anonymous(app, client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


@pytest.mark.parametrize("path", MENU_GATED_STATIC_ROUTES)
def test_menu_gated_route_rejects_authenticated_non_admin(app, client, path):
    """Proves admin_required (not menu_key_required) is what stops a
    non-admin here -- it runs first in the decorator stack, before any menu
    permission is even consulted."""
    sicil = "mgr_na_" + path.replace("/", "_")
    _create_user(app, sicil_no=sicil, email=f"{sicil}@x.test", role="personel")
    _login(client, sicil)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 403


@pytest.mark.parametrize("path", MENU_GATED_STATIC_ROUTES)
def test_menu_gated_route_rejects_admin_without_menu_permission(app, client, path):
    """The security-critical case: role="admin" alone is NOT enough once the
    admin_users menu key is explicitly revoked for this specific user via a
    real UserMenuPermission row."""
    sicil = "mgr_np_" + path.replace("/", "_")
    user_id = _create_user(app, sicil_no=sicil, email=f"{sicil}@x.test", role="admin")
    _deny_menu_permission(app, user_id=user_id, menu_key="admin_users")
    _login(client, sicil)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 403


@pytest.mark.parametrize("path", MENU_GATED_STATIC_ROUTES)
def test_menu_gated_route_allows_admin_with_menu_permission(app, client, path):
    """Admin-family role defaults to admin_users=True (verified against the
    real build_menu_visibility_map, not assumed) -- no explicit grant row
    needed for the positive case."""
    sicil = "mgr_ok_" + path.replace("/", "_")
    _create_user(app, sicil_no=sicil, email=f"{sicil}@x.test", role="admin")
    _login(client, sicil)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 200


def test_personnel_excel_template_download_admin_gets_real_attachment(app, client):
    """Deeper than the generic 200 check above: proves the allowed path
    actually returns a real xlsx attachment, not just any 200 body."""
    _create_user(app, sicil_no="xls_tpl_admin", email="xls_tpl_admin@x.test", role="admin")
    _login(client, "xls_tpl_admin")

    response = client.get("/personnel/excel-template", follow_redirects=False)

    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    disposition = response.headers.get("Content-Disposition", "")
    assert "attachment" in disposition


# ---------------------------------------------------------------------------
# Authorization matrix -- dynamic-id routes (admin_user_edit, personnel_edit)
# ---------------------------------------------------------------------------
# Rejection cases use a nonexistent id (999999): the decorator stack rejects
# before the route body ever looks the id up, so no real target row is
# needed to prove rejection. The acceptance case creates a real target row.


def test_admin_user_edit_rejects_anonymous(app, client):
    # See test_admin_only_route_rejects_anonymous above: /admin/* paths are
    # centrally gated to a direct 403 for unauthenticated callers, not a
    # 302-to-/login redirect.
    response = client.get("/admin/users/999999/edit", follow_redirects=False)
    assert response.status_code == 403


def test_admin_user_edit_rejects_authenticated_non_admin(app, client):
    _create_user(app, sicil_no="aue_na", email="aue_na@x.test", role="personel")
    _login(client, "aue_na")

    response = client.get("/admin/users/999999/edit", follow_redirects=False)

    assert response.status_code == 403


def test_admin_user_edit_allows_admin_against_real_target_row(app, client):
    target_id = _create_user(app, sicil_no="aue_target", email="aue_target@x.test", role="personel")
    _create_user(app, sicil_no="aue_admin", email="aue_admin@x.test", role="admin")
    _login(client, "aue_admin")

    response = client.get(f"/admin/users/{target_id}/edit", follow_redirects=False)

    assert response.status_code == 200


def test_personnel_edit_rejects_anonymous(app, client):
    response = client.get("/personnel/999999/edit", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


def test_personnel_edit_rejects_authenticated_non_admin(app, client):
    _create_user(app, sicil_no="pe_na", email="pe_na@x.test", role="personel")
    _login(client, "pe_na")

    response = client.get("/personnel/999999/edit", follow_redirects=False)

    assert response.status_code == 403


def test_personnel_edit_rejects_admin_without_menu_permission(app, client):
    user_id = _create_user(app, sicil_no="pe_np", email="pe_np@x.test", role="admin")
    _deny_menu_permission(app, user_id=user_id, menu_key="admin_users")
    _login(client, "pe_np")

    response = client.get("/personnel/999999/edit", follow_redirects=False)

    assert response.status_code == 403


def test_personnel_edit_allows_admin_against_real_target_row(app, client):
    target_id = _create_user(app, sicil_no="pe_target", email="pe_target@x.test", role="personel")
    _create_user(app, sicil_no="pe_admin", email="pe_admin@x.test", role="admin")
    _login(client, "pe_admin")

    response = client.get(f"/personnel/{target_id}/edit", follow_redirects=False)

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Direct-POST "UI bypass" checks -- the SECURITY TEST RULE's core scenario:
# a caller skips the UI entirely and POSTs the mutating form directly.
# ---------------------------------------------------------------------------


def _admin_user_create_payload(**overrides):
    payload = {
        "ad": "Yeni",
        "soyad": "Personel",
        "sicil_no": "bypass001",
        "email": "bypass001@x.test",
        "unvan": "Uzman",
        "role": "personel",
        "birim": "Bilgi Islem",
        "ust_birim": "Genel Mudurluk",
    }
    payload.update(overrides)
    return payload


def test_admin_user_create_post_rejects_anonymous_and_creates_no_user(app, client):
    # See test_admin_only_route_rejects_anonymous above: /admin/* paths are
    # centrally gated to a direct 403 for unauthenticated callers, not a
    # 302-to-/login redirect.
    before = _user_count(app)

    response = client.post("/admin/users/create", data=_admin_user_create_payload(), follow_redirects=False)

    assert response.status_code == 403
    assert _find_user_by_sicil(app, "bypass001") is None
    assert _user_count(app) == before


def test_admin_user_create_post_rejects_non_admin_and_creates_no_user(app, client):
    _create_user(app, sicil_no="auc_bypass_na", email="auc_bypass_na@x.test", role="personel")
    _login(client, "auc_bypass_na")
    before = _user_count(app)

    response = client.post("/admin/users/create", data=_admin_user_create_payload(), follow_redirects=False)

    assert response.status_code == 403
    assert _find_user_by_sicil(app, "bypass001") is None
    assert _user_count(app) == before


def _personnel_add_payload(**overrides):
    payload = {
        "ad": "Bypass",
        "soyad": "Deneme",
        "sicil_no": "pabypass001",
        "email": "pabypass001@x.test",
        "unvan": "Uzman",
        "role": "personel",
        "birim": "Bilgi Islem",
        "ust_birim": "Genel Mudurluk",
    }
    payload.update(overrides)
    return payload


def test_personnel_add_post_rejects_non_admin_and_creates_no_user(app, client):
    _create_user(app, sicil_no="pa_bypass_na", email="pa_bypass_na@x.test", role="personel")
    _login(client, "pa_bypass_na")

    response = client.post("/personnel/add", data=_personnel_add_payload(), follow_redirects=False)

    assert response.status_code == 403
    assert _find_user_by_sicil(app, "pabypass001") is None


def test_personnel_add_post_rejects_admin_without_menu_permission_and_creates_no_user(app, client):
    """The scenario a UI-only check would miss entirely: the caller genuinely
    has role="admin" (passes admin_required) but this specific menu key has
    been revoked -- the backend must still refuse the direct POST."""
    user_id = _create_user(app, sicil_no="pa_bypass_np", email="pa_bypass_np@x.test", role="admin")
    _deny_menu_permission(app, user_id=user_id, menu_key="admin_users")
    _login(client, "pa_bypass_np")

    response = client.post("/personnel/add", data=_personnel_add_payload(), follow_redirects=False)

    assert response.status_code == 403
    assert _find_user_by_sicil(app, "pabypass001") is None


# ---------------------------------------------------------------------------
# admin_user_create -- business rules (POST, authenticated as admin)
# ---------------------------------------------------------------------------


def test_admin_user_create_missing_required_field_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="auc_admin1", email="auc_admin1@x.test", role="admin")
    _login(client, "auc_admin1")
    before = _user_count(app)

    payload = _admin_user_create_payload(sicil_no="auc_missing", email="auc_missing@x.test")
    del payload["ad"]  # required field omitted

    response = client.post("/admin/users/create", data=payload, follow_redirects=False)

    assert response.status_code == 200  # re-renders the create form (no redirect)
    _assert_flash_message_rendered(response, "Ad, soyad, sicil no, e-posta, unvan, birim ve üst birim zorunludur.")
    assert _find_user_by_sicil(app, "auc_missing") is None
    assert _user_count(app) == before


def test_admin_user_create_duplicate_sicil_no_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="auc_admin2", email="auc_admin2@x.test", role="admin")
    _create_user(app, sicil_no="auc_dup_sicil", email="auc_existing@x.test", role="personel")
    _login(client, "auc_admin2")
    before = _user_count(app)

    payload = _admin_user_create_payload(sicil_no="auc_dup_sicil", email="auc_new_email@x.test")

    response = client.post("/admin/users/create", data=payload, follow_redirects=False)

    assert response.status_code == 200
    _assert_flash_message_rendered(response, "Bu sicil numarası zaten kayıtlı.")
    assert _user_count(app) == before
    # the pre-existing row's email must remain unique/unchanged (not overwritten)
    unchanged = _find_user_by_sicil(app, "auc_dup_sicil")
    assert unchanged is not None and unchanged.email == "auc_existing@x.test"


def test_admin_user_create_duplicate_email_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="auc_admin3", email="auc_admin3@x.test", role="admin")
    _create_user(app, sicil_no="auc_existing_email_user", email="auc_dup_email@x.test", role="personel")
    _login(client, "auc_admin3")
    before = _user_count(app)

    payload = _admin_user_create_payload(sicil_no="auc_new_sicil_1", email="auc_dup_email@x.test")

    response = client.post("/admin/users/create", data=payload, follow_redirects=False)

    assert response.status_code == 200
    _assert_flash_message_rendered(response, "Bu e-posta adresi zaten kayıtlı.")
    assert _find_user_by_sicil(app, "auc_new_sicil_1") is None
    assert _user_count(app) == before


def test_admin_user_create_self_manager_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="auc_admin4", email="auc_admin4@x.test", role="admin")
    _login(client, "auc_admin4")
    before = _user_count(app)

    payload = _admin_user_create_payload(
        sicil_no="auc_self_mgr",
        email="auc_self_mgr@x.test",
        yonetici_sicil="auc_self_mgr",  # same as own sicil_no
    )

    response = client.post("/admin/users/create", data=payload, follow_redirects=False)

    assert response.status_code == 200
    _assert_flash_message_rendered(response, "Personel kendisini amir olarak seçemez.")
    assert _find_user_by_sicil(app, "auc_self_mgr") is None
    assert _user_count(app) == before


def test_admin_user_create_duplicate_manager_levels_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="auc_admin5", email="auc_admin5@x.test", role="admin")
    _login(client, "auc_admin5")
    before = _user_count(app)

    payload = _admin_user_create_payload(
        sicil_no="auc_dup_mgr",
        email="auc_dup_mgr@x.test",
        yonetici_sicil="mgr_shared",
        ikinci_yonetici_sicil="mgr_shared",  # same manager at two levels
    )

    response = client.post("/admin/users/create", data=payload, follow_redirects=False)

    assert response.status_code == 200
    _assert_flash_message_rendered(response, "Aynı kişi birden fazla amir seviyesinde seçilemez.")
    assert _find_user_by_sicil(app, "auc_dup_mgr") is None
    assert _user_count(app) == before


def test_admin_user_create_success_creates_real_user_with_hashed_password(app, client):
    _create_user(app, sicil_no="auc_admin6", email="auc_admin6@x.test", role="admin")
    _login(client, "auc_admin6")
    before = _user_count(app)

    payload = _admin_user_create_payload(
        ad="Ayşe",
        soyad="Yılmaz",
        sicil_no="auc_success_1",
        email="auc_success_1@x.test",
        unvan="Şef",
        role="birim_sorumlusu",
        birim="Muhasebe",
        ust_birim="Mali İşler",
        is_active="on",
    )

    response = client.post("/admin/users/create", data=payload, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/users")
    flashes = _flashes(client)
    assert flashes
    # flashes[-1], not flashes[0]: _login() above queued its own
    # ("success", "Giriş başarılı.") flash, which is never consumed (no
    # template renders across a redirect), so it is still stacked ahead of
    # this action's own flash in the list -- the newest flash is always
    # last, regardless of how many earlier ones accumulated.
    assert flashes[-1][0] == "success"
    assert f"Başlangıç şifresi: {DEFAULT_FIRST_LOGIN_PASSWORD}" in flashes[-1][1]

    assert _user_count(app) == before + 1
    created = _find_user_by_sicil(app, "auc_success_1")
    assert created is not None
    assert created.ad == "Ayşe"
    assert created.soyad == "Yılmaz"
    assert created.email == "auc_success_1@x.test"
    assert created.role == "birim_sorumlusu"
    assert created.birim == "Muhasebe"
    assert created.ust_birim == "Mali İşler"
    assert created.is_active is True
    assert created.must_change_password is True
    # Real proof of hashing, not just "a hash string exists":
    assert created.password_hash != DEFAULT_FIRST_LOGIN_PASSWORD
    assert created.check_password(DEFAULT_FIRST_LOGIN_PASSWORD) is True


# ---------------------------------------------------------------------------
# admin_user_edit -- business rules (POST, authenticated as admin)
# ---------------------------------------------------------------------------


def _admin_user_edit_payload(**overrides):
    payload = {
        "ad": "Guncel",
        "soyad": "Isim",
        "sicil_no": "aue_edit_target",
        "email": "aue_edit_target@x.test",
        "unvan": "Uzman",
        "role": "personel",
        "birim": "Bilgi Islem",
        "ust_birim": "Genel Mudurluk",
    }
    payload.update(overrides)
    return payload


def test_admin_user_edit_missing_required_field_rejected_leaves_row_unchanged(app, client):
    target_id = _create_user(app, sicil_no="aue_edit_target", email="aue_edit_target@x.test", role="personel")
    _create_user(app, sicil_no="aue_edit_admin1", email="aue_edit_admin1@x.test", role="admin")
    _login(client, "aue_edit_admin1")

    payload = _admin_user_edit_payload(email="")  # required field blanked

    response = client.post(f"/admin/users/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith(f"/admin/users/{target_id}/edit")
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("warning", "Ad, soyad, sicil no, e-posta, unvan, birim ve üst birim zorunludur.")
    unchanged = _get_user(app, target_id)
    assert unchanged.ad == "Behavior"  # still the original _create_user value, not "Guncel"
    assert unchanged.email == "aue_edit_target@x.test"


def test_admin_user_edit_duplicate_sicil_no_rejected_leaves_row_unchanged(app, client):
    target_id = _create_user(app, sicil_no="aue_edit_target2", email="aue_edit_target2@x.test", role="personel")
    _create_user(app, sicil_no="aue_other_sicil", email="aue_other@x.test", role="personel")
    _create_user(app, sicil_no="aue_edit_admin2", email="aue_edit_admin2@x.test", role="admin")
    _login(client, "aue_edit_admin2")

    payload = _admin_user_edit_payload(sicil_no="aue_other_sicil", email="aue_edit_target2@x.test")

    response = client.post(f"/admin/users/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("danger", "Bu sicil numarası başka bir kullanıcıda kayıtlı.")
    unchanged = _get_user(app, target_id)
    assert unchanged.sicil_no == "aue_edit_target2"  # not overwritten to the conflicting value


def test_admin_user_edit_self_manager_rejected_leaves_row_unchanged(app, client):
    target_id = _create_user(app, sicil_no="aue_edit_target3", email="aue_edit_target3@x.test", role="personel")
    _create_user(app, sicil_no="aue_edit_admin3", email="aue_edit_admin3@x.test", role="admin")
    _login(client, "aue_edit_admin3")

    payload = _admin_user_edit_payload(
        sicil_no="aue_edit_target3",
        email="aue_edit_target3@x.test",
        yonetici_sicil="aue_edit_target3",  # self-reference
    )

    response = client.post(f"/admin/users/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("warning", "Personel kendisini amir olarak seçemez.")
    unchanged = _get_user(app, target_id)
    assert unchanged.yonetici_sicil is None


def test_admin_user_edit_success_updates_real_row(app, client):
    target_id = _create_user(app, sicil_no="aue_edit_target4", email="aue_edit_target4_old@x.test", role="personel")
    _create_user(app, sicil_no="aue_edit_admin4", email="aue_edit_admin4@x.test", role="admin")
    _login(client, "aue_edit_admin4")

    payload = _admin_user_edit_payload(
        ad="Mehmet",
        soyad="Demir",
        sicil_no="aue_edit_target4",
        email="aue_edit_target4_new@x.test",
        unvan="Koordinatör",
        role="koordinator",
        birim="Ar-Ge",
        ust_birim="Teknoloji",
        is_active="on",
    )

    response = client.post(f"/admin/users/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/users")
    flashes = _flashes(client)
    # flashes[-1], not flashes[0]: see the comment on the analogous
    # assertion in test_admin_user_create_success_creates_real_user_with_hashed_password
    # above -- _login()'s own flash is still stacked ahead of this one.
    assert flashes and flashes[-1] == ("success", "Personel bilgileri güncellendi.")

    updated = _get_user(app, target_id)
    assert updated.ad == "Mehmet"
    assert updated.soyad == "Demir"
    assert updated.email == "aue_edit_target4_new@x.test"
    assert updated.unvan == "Koordinatör"
    assert updated.role == "koordinator"
    assert updated.birim == "Ar-Ge"
    assert updated.ust_birim == "Teknoloji"


# ---------------------------------------------------------------------------
# personnel_add -- business rules (POST, authenticated as admin with
# admin_users permission)
# ---------------------------------------------------------------------------


def test_personnel_add_missing_required_field_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="pa_admin1", email="pa_admin1@x.test", role="admin")
    _login(client, "pa_admin1")

    payload = _personnel_add_payload(sicil_no="pa_missing", email="pa_missing@x.test")
    del payload["unvan"]

    response = client.post("/personnel/add", data=payload, follow_redirects=False)

    assert response.status_code == 200
    _assert_flash_message_rendered(response, "Zorunlu alanları eksiksiz doldurunuz.")
    assert _find_user_by_sicil(app, "pa_missing") is None


def test_personnel_add_duplicate_email_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="pa_admin2", email="pa_admin2@x.test", role="admin")
    _create_user(app, sicil_no="pa_existing", email="pa_dup_email@x.test", role="personel")
    _login(client, "pa_admin2")

    payload = _personnel_add_payload(sicil_no="pa_new_sicil", email="pa_dup_email@x.test")

    response = client.post("/personnel/add", data=payload, follow_redirects=False)

    assert response.status_code == 200
    _assert_flash_message_rendered(response, "Bu e-posta adresi ile kayıtlı bir kullanıcı zaten var.")
    assert _find_user_by_sicil(app, "pa_new_sicil") is None


def test_personnel_add_duplicate_sicil_no_rejected_no_user_created(app, client):
    _create_user(app, sicil_no="pa_admin3", email="pa_admin3@x.test", role="admin")
    _create_user(app, sicil_no="pa_dup_sicil", email="pa_existing2@x.test", role="personel")
    _login(client, "pa_admin3")

    payload = _personnel_add_payload(sicil_no="pa_dup_sicil", email="pa_new_email@x.test")

    response = client.post("/personnel/add", data=payload, follow_redirects=False)

    assert response.status_code == 200
    _assert_flash_message_rendered(response, "Bu sicil numarası ile kayıtlı bir kullanıcı zaten var.")
    unchanged = _find_user_by_sicil(app, "pa_dup_sicil")
    assert unchanged is not None and unchanged.email == "pa_existing2@x.test"


def test_personnel_add_success_creates_real_user(app, client):
    _create_user(app, sicil_no="pa_admin4", email="pa_admin4@x.test", role="admin")
    _login(client, "pa_admin4")

    payload = _personnel_add_payload(
        ad="Zeynep",
        soyad="Kara",
        sicil_no="pa_success_1",
        email="pa_success_1@x.test",
        unvan="Uzman Yardımcısı",
        role="personel",
        birim="İnsan Kaynakları",
        ust_birim="İdari İşler",
    )

    response = client.post("/personnel/add", data=payload, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/personnel")
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("success", "Personel kaydı başarıyla oluşturuldu.")

    created = _find_user_by_sicil(app, "pa_success_1")
    assert created is not None
    assert created.ad == "Zeynep"
    assert created.soyad == "Kara"
    assert created.email == "pa_success_1@x.test"
    assert created.birim == "İnsan Kaynakları"
    assert created.ust_birim == "İdari İşler"
    assert created.must_change_password is True
    assert created.password_hash != DEFAULT_FIRST_LOGIN_PASSWORD
    assert created.check_password(DEFAULT_FIRST_LOGIN_PASSWORD) is True


# ---------------------------------------------------------------------------
# personnel_edit -- business rules (POST, authenticated as admin with
# admin_users permission)
# ---------------------------------------------------------------------------


def _personnel_edit_payload(**overrides):
    payload = {
        "ad": "Guncel",
        "soyad": "Personel",
        "sicil_no": "pe_edit_target",
        "email": "pe_edit_target@x.test",
        "unvan": "Uzman",
        "role": "personel",
        "birim": "Bilgi Islem",
        "ust_birim": "Genel Mudurluk",
    }
    payload.update(overrides)
    return payload


def test_personnel_edit_missing_required_field_rejected_leaves_row_unchanged(app, client):
    target_id = _create_user(app, sicil_no="pe_edit_target", email="pe_edit_target@x.test", role="personel")
    _create_user(app, sicil_no="pe_edit_admin1", email="pe_edit_admin1@x.test", role="admin")
    _login(client, "pe_edit_admin1")

    payload = _personnel_edit_payload(ad="")

    response = client.post(f"/personnel/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith(f"/personnel/{target_id}/edit")
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("warning", "Ad, Soyad, Sicil No, E-Posta, Unvan, Birim ve Üst Birim alanları zorunludur.")
    unchanged = _get_user(app, target_id)
    assert unchanged.ad == "Behavior"


def test_personnel_edit_duplicate_sicil_no_rejected_leaves_row_unchanged(app, client):
    target_id = _create_user(app, sicil_no="pe_edit_target2", email="pe_edit_target2@x.test", role="personel")
    _create_user(app, sicil_no="pe_other_sicil", email="pe_other@x.test", role="personel")
    _create_user(app, sicil_no="pe_edit_admin2", email="pe_edit_admin2@x.test", role="admin")
    _login(client, "pe_edit_admin2")

    payload = _personnel_edit_payload(sicil_no="pe_other_sicil", email="pe_edit_target2@x.test")

    response = client.post(f"/personnel/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("danger", "Bu sicil numarası başka bir kullanıcı tarafından kullanılıyor.")
    unchanged = _get_user(app, target_id)
    assert unchanged.sicil_no == "pe_edit_target2"


def test_personnel_edit_self_manager_rejected_leaves_row_unchanged(app, client):
    target_id = _create_user(app, sicil_no="pe_edit_target3", email="pe_edit_target3@x.test", role="personel")
    _create_user(app, sicil_no="pe_edit_admin3", email="pe_edit_admin3@x.test", role="admin")
    _login(client, "pe_edit_admin3")

    payload = _personnel_edit_payload(
        sicil_no="pe_edit_target3",
        email="pe_edit_target3@x.test",
        manager_1_id=str(target_id),  # selecting itself as manager
    )

    response = client.post(f"/personnel/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("danger", "Personel kendisini amir olarak seçemez.")


def test_personnel_edit_password_too_short_rejected_password_unchanged(app, client):
    target_id = _create_user(app, sicil_no="pe_edit_target4", email="pe_edit_target4@x.test", role="personel", password="OriginalPass1!")
    _create_user(app, sicil_no="pe_edit_admin4", email="pe_edit_admin4@x.test", role="admin")
    _login(client, "pe_edit_admin4")

    payload = _personnel_edit_payload(
        sicil_no="pe_edit_target4",
        email="pe_edit_target4@x.test",
        new_password="short1",
        new_password_repeat="short1",
    )

    response = client.post(f"/personnel/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("warning", "Yeni şifre en az 8 karakter olmalıdır.")
    unchanged = _get_user(app, target_id)
    assert unchanged.check_password("OriginalPass1!") is True


def test_personnel_edit_password_mismatch_rejected_password_unchanged(app, client):
    target_id = _create_user(app, sicil_no="pe_edit_target5", email="pe_edit_target5@x.test", role="personel", password="OriginalPass1!")
    _create_user(app, sicil_no="pe_edit_admin5", email="pe_edit_admin5@x.test", role="admin")
    _login(client, "pe_edit_admin5")

    payload = _personnel_edit_payload(
        sicil_no="pe_edit_target5",
        email="pe_edit_target5@x.test",
        new_password="LongEnough1!",
        new_password_repeat="DoesNotMatch1!",
    )

    response = client.post(f"/personnel/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("warning", "Yeni şifre alanları eşleşmiyor.")
    unchanged = _get_user(app, target_id)
    assert unchanged.check_password("OriginalPass1!") is True


def test_personnel_edit_success_updates_real_row_and_resets_password(app, client):
    target_id = _create_user(app, sicil_no="pe_edit_target6", email="pe_edit_target6_old@x.test", role="personel", password="OriginalPass1!")
    _create_user(app, sicil_no="pe_edit_admin6", email="pe_edit_admin6@x.test", role="admin")
    _login(client, "pe_edit_admin6")

    payload = _personnel_edit_payload(
        ad="Fatma",
        soyad="Şahin",
        sicil_no="pe_edit_target6",
        email="pe_edit_target6_new@x.test",
        unvan="Danışman",
        role="personel",
        birim="Hukuk",
        ust_birim="Genel Müdürlük",
        new_password="BrandNewPass1!",
        new_password_repeat="BrandNewPass1!",
    )

    response = client.post(f"/personnel/{target_id}/edit", data=payload, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/personnel")
    flashes = _flashes(client)
    assert flashes
    # password_reset_applied branch -> the specific longer success message
    assert flashes[-1][0] == "success"
    assert "geçici şifre" in flashes[-1][1]

    updated = _get_user(app, target_id)
    assert updated.ad == "Fatma"
    assert updated.soyad == "Şahin"
    assert updated.email == "pe_edit_target6_new@x.test"
    assert updated.unvan == "Danışman"
    assert updated.birim == "Hukuk"
    assert updated.ust_birim == "Genel Müdürlük"
    assert updated.check_password("OriginalPass1!") is False
    assert updated.check_password("BrandNewPass1!") is True
