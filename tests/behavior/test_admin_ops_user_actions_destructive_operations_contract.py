"""BYS360_PHASE5_COVERAGE_WAVE3_AGENT1_ADMIN_OPS_DESTRUCTIVE_CONTRACT

Behavioral contract for app/admin/ops_user_action_services.py (the real
implementation bodies) + the route authorization/wiring for those same
functions in app/admin/ops_routes.py:

    ensure_not_self_target, admin_user_delete_impl,
    admin_users_bulk_delete_impl, admin_user_archive_impl,
    admin_users_bulk_archive_impl, admin_user_toggle_active_impl,
    admin_users_bulk_passive_impl, admin_user_change_photo_impl,
    admin_users_reset_all_impl

All 8 corresponding routes (POST /admin/users/<id>/photo, .../toggle-active,
.../archive, .../delete, .../bulk-delete, .../bulk-archive, .../bulk-passive,
.../reset-all) share the exact same decorator stack:
`login_required` -> `admin_required` -> `menu_key_required("admin_users")`.
Since every one of these paths is also under `/admin/*`, they are additionally
gated -- BEFORE that decorator stack ever runs -- by the central
`_enforce_admin_path_guard` before_request hook in
app/bootstrap/operational_guards.py (confirmed by reading that file): an
unauthenticated caller or a caller whose role is not in
`ADMIN_FAMILY_ROLES` ({"admin", "baskan", "baskan_yardimcisi",
"grup_baskani", "mali_musavir"}) gets a direct 403 for any `/admin/*` path,
never a 302-to-/login. This matches the already-proven behavior in
tests/behavior/test_admin_routes_authorization_contract.py for the sibling
admin routes in the same file family, and this file follows that same
_make_app / _login / _flashes helper shape rather than inventing a new one.

Three deliberate judgment calls, documented here rather than silently baked
into individual tests:

1. `admin_users_reset_all_impl` (the highest-risk function in scope) is never
   exercised end-to-end against a real cascade. Its target,
   `reset_all_personnel_and_related_data`, deletes across ~30 tables in
   dependency order (read directly from
   app/services/hierarchy_admin_service.py). Per this wave's own safety
   instruction, its authorization gate is proven thoroughly (anonymous/
   non-admin rejected, confirmed via a spy that the cascade function is
   never even called), and its *own* body (invoke -> commit -> success flash;
   exception -> rollback -> danger flash, not a raw 500) is proven by
   monkeypatching the imported `reset_all_personnel_and_related_data` name
   with a spy/fault -- never by running a real cascade.

2. A genuine sqlite `IntegrityError` from `safe_delete_user_by_id` could not
   be reliably reproduced through real schema + real data alone: that
   service (app/services/safe_user_delete_service.py) proactively
   NULLs/deletes every real FK reference to users.id (introspected from the
   live DB) *before* issuing the raw `DELETE FROM users`, specifically to
   avoid ever tripping a FK violation -- and this project's SQLite test
   databases do not enable `PRAGMA foreign_keys=ON` in the first place (only
   tests/migrations/test_phase5y_*/test_phase5v_*.py do that, confirmed via
   grep). `admin_user_delete_impl`'s real "delete a target that is itself an
   admin" path (safe_delete_user_by_id's own `role == "admin"` guard raising
   ValueError) is exercised with zero mocking and proves the equivalent
   "blocked deletion is caught, rolled back, and surfaced as a clean failure"
   behavior. The distinct `except IntegrityError:` branch (as literally
   written in ops_user_action_services.py, separate from the generic
   `except Exception:` branch) is additionally proven with one test that
   injects a real `sqlalchemy.exc.IntegrityError` instance at the exact call
   site it wraps, then proves the session is still healthy afterward via a
   genuine follow-up write.

3. `admin_user_archive_impl` / `admin_users_bulk_archive_impl` guard their
   `is_archived` / `archived_at` field writes with `hasattr(user, ...)`
   checks. Reading app/models/core_models.py's real `User` class confirms
   neither column exists on the model today -- so those guards always
   no-op, and the "already archived" short-circuit
   (`bool(getattr(user, "is_archived", False)) and not
   bool(getattr(user, "is_active", True))`) can never be True for a real
   User row (the first getattr always returns the False default). This is
   not treated as a production defect: nothing crashes, nothing corrupts,
   and the real, observable, verified behavior --archiving only ever flips
   `is_active` to False and is safely idempotent on repeat calls-- is
   exactly what is asserted below, without asserting a nonexistent field.

Fixture pattern: proven per this wave's mandatory rule, copied from
tests/behavior/test_low_score_process_service_workflow_contract.py's
`_make_app` (monkeypatch Config class attributes BEFORE create_app(),
StaticPool + pysqlite isolation_level=None + explicit BEGIN event listener),
combined with the test-client/login/flash helper shapes from
tests/behavior/test_admin_routes_authorization_contract.py. Uses its own
dedicated tmp DB directory (C:\\bys360_pytest_tmp_agent_adminops) so this file
shares no state with any other wave/agent running concurrently.
"""
from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent_adminops")
_TMP_PHOTO_DIR = os.path.join(_TMP_DB_DIR, "photos")

DEFAULT_PASSWORD = "AdminOpsDestructiveTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "admin-ops-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture -- see module docstring for why this exact shape is
# mandatory (Config class-attribute caching + Flask-SQLAlchemy 3.x engine
# caching means the URI must be patched onto Config BEFORE create_app()).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-admin-ops-destructive-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", DEFAULT_FIRST_LOGIN_PASSWORD)
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"agent1_adminops_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # BYS360_COVERAGE_WAVE3_AGENT1: Config.SQLALCHEMY_DATABASE_URI is a class
    # attribute frozen the first time config.py is imported anywhere in this
    # pytest process. create_app() itself touches db.engine/db.session during
    # its own bootstrap, and Flask-SQLAlchemy 3.x lazily binds AND CACHES the
    # per-app Engine on that first access, read from app.config at that exact
    # moment. Patching Config's class attributes BEFORE create_app() (not
    # updating flask_app.config afterward) is the only way to make this
    # test's own unique file-backed SQLite DB actually take effect. Proven
    # pattern, copied from test_low_score_process_service_workflow_contract.py.
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
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role="personel", is_active=True, password=DEFAULT_PASSWORD, sicil_no=None, email=None):
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    sicil = sicil_no or f"AOPS{suffix:06d}"
    mail = email or f"adminops-{suffix}@bys360.test"
    with app.app_context():
        user = User(
            sicil_no=sicil,
            email=mail,
            ad="Ops",
            soyad=f"User{suffix}",
            role=role,
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
    with client.session_transaction() as sess:
        return list(sess.get("_flashes", []))


def _get_user(app, user_id):
    from app.models import User

    with app.app_context():
        return User.query.get(user_id)


def _user_count(app):
    from app.models import User

    with app.app_context():
        return User.query.count()


# ---------------------------------------------------------------------------
# Central authorization matrix -- all 8 endpoints in scope, same decorator
# stack + same central /admin/* before_request guard. Proves, for EVERY
# endpoint: an anonymous direct POST and an authenticated non-admin-family
# direct POST are both rejected with zero DB mutation (the "UI bypass"
# threat model from Wave 1/2).
# ---------------------------------------------------------------------------


def _photo_path(uid):
    return f"/admin/users/{uid}/photo"


def _toggle_path(uid):
    return f"/admin/users/{uid}/toggle-active"


def _archive_path(uid):
    return f"/admin/users/{uid}/archive"


def _delete_path(uid):
    return f"/admin/users/{uid}/delete"


def _bulk_payload(uid):
    return {"user_ids": [str(uid)]}


def _empty_payload(uid):  # noqa: ARG001
    return {}


AUTH_MATRIX = [
    pytest.param("photo", _photo_path, _empty_payload, id="photo"),
    pytest.param("toggle-active", _toggle_path, _empty_payload, id="toggle-active"),
    pytest.param("archive", _archive_path, _empty_payload, id="archive"),
    pytest.param("delete", _delete_path, _empty_payload, id="delete"),
    pytest.param("bulk-delete", lambda uid: "/admin/users/bulk-delete", _bulk_payload, id="bulk-delete"),
    pytest.param("bulk-archive", lambda uid: "/admin/users/bulk-archive", _bulk_payload, id="bulk-archive"),
    pytest.param("bulk-passive", lambda uid: "/admin/users/bulk-passive", _bulk_payload, id="bulk-passive"),
    pytest.param("reset-all", lambda uid: "/admin/users/reset-all", _empty_payload, id="reset-all"),
]


@pytest.mark.parametrize("name,path_fn,payload_fn", AUTH_MATRIX)
def test_admin_ops_endpoint_rejects_anonymous_with_zero_mutation(app, client, name, path_fn, payload_fn):
    target_id = _create_user(app, role="personel")
    before = _user_count(app)

    response = client.post(path_fn(target_id), data=payload_fn(target_id), follow_redirects=False)

    assert response.status_code == 403
    assert _user_count(app) == before
    unchanged = _get_user(app, target_id)
    assert unchanged.is_active is True


@pytest.mark.parametrize("name,path_fn,payload_fn", AUTH_MATRIX)
def test_admin_ops_endpoint_rejects_authenticated_non_admin_with_zero_mutation(app, client, name, path_fn, payload_fn):
    target_id = _create_user(app, role="personel")
    actor_sicil = f"aopsna_{name}".replace("-", "_")
    _create_user(app, role="personel", sicil_no=actor_sicil)
    _login(client, actor_sicil)
    before = _user_count(app)

    response = client.post(path_fn(target_id), data=payload_fn(target_id), follow_redirects=False)

    assert response.status_code == 403
    assert _user_count(app) == before
    unchanged = _get_user(app, target_id)
    assert unchanged.is_active is True


# ---------------------------------------------------------------------------
# admin_user_delete_impl
# ---------------------------------------------------------------------------


def test_admin_user_delete_success_removes_real_row(app, client):
    admin_id = _create_user(app, role="admin", sicil_no="del_ok_admin")
    target_id = _create_user(app, role="personel", sicil_no="del_ok_target")
    _login(client, "del_ok_admin")
    before = _user_count(app)

    response = client.post(f"/admin/users/{target_id}/delete", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/users")
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Kullanıcı silindi.")
    assert _user_count(app) == before - 1
    assert _get_user(app, target_id) is None
    # The actor itself is untouched.
    assert _get_user(app, admin_id) is not None


def test_admin_user_delete_blocks_self_target_with_zero_mutation(app, client):
    admin_id = _create_user(app, role="admin", sicil_no="del_self_admin")
    _login(client, "del_self_admin")
    before = _user_count(app)

    response = client.post(f"/admin/users/{admin_id}/delete", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Kendi hesabınızı silemezsiniz.")
    assert _user_count(app) == before
    assert _get_user(app, admin_id) is not None


def test_admin_user_delete_nonexistent_target_is_clean_no_op(app, client):
    _create_user(app, role="admin", sicil_no="del_missing_admin")
    _login(client, "del_missing_admin")
    before = _user_count(app)

    response = client.post("/admin/users/999999/delete", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("danger", "Kullanıcı bulunamadı.")
    assert _user_count(app) == before


def test_admin_user_delete_blocks_deleting_another_admin_via_safe_delete_guard(app, client):
    """safe_delete_user_by_id (app/services/safe_user_delete_service.py) has
    its own real guard: `if getattr(user, "role", None) == "admin" and not
    allow_admin: raise ValueError(...)`. admin_user_delete_impl calls it
    without allow_admin=True, so this ValueError -- a real production
    exception from a real production guard, no mocking -- falls into the
    generic `except Exception as exc:` branch (NOT the IntegrityError
    branch) and is surfaced as a clean, rolled-back failure.

    BYS360 H1F (exception-display hardening): this branch's flash used to
    append the raw exception's own text after a colon
    (f"Bu kullanici silinemedi: {exc}") -- a real production ValueError
    message leaking to the admin verbatim. Fixed to a fixed safe message;
    this assertion was updated to match (see
    tests/behavior/test_h1f_final_audit_second_pass_exception_leak_contract.py
    for the sentinel-injection proof)."""
    actor_id = _create_user(app, role="admin", sicil_no="del_blkadm_actor")
    target_admin_id = _create_user(app, role="admin", sicil_no="del_blkadm_target")
    _login(client, "del_blkadm_actor")
    before = _user_count(app)

    response = client.post(f"/admin/users/{target_admin_id}/delete", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("danger", "Bu kullanıcı silinemedi.")
    assert _user_count(app) == before
    survivor = _get_user(app, target_admin_id)
    assert survivor is not None and survivor.role == "admin"
    assert _get_user(app, actor_id) is not None


def test_admin_user_delete_integrity_error_branch_is_caught_rolled_back_and_session_stays_usable(app, client, monkeypatch):
    """Proves the DISTINCT `except IntegrityError:` branch in
    admin_user_delete_impl (separate from the generic `except Exception:`
    branch exercised above) -- see module docstring judgment call #2 for why
    a real sqlite IntegrityError could not be reproduced through genuine
    schema/data here. Injects a real sqlalchemy.exc.IntegrityError at the
    exact call site the branch wraps, then proves the session is not left in
    a broken/half-open transactional state by performing a genuine,
    unrelated follow-up mutation in the same app/session lifecycle."""
    from sqlalchemy.exc import IntegrityError

    _create_user(app, role="admin", sicil_no="del_ie_admin")
    target_id = _create_user(app, role="personel", sicil_no="del_ie_target")
    _login(client, "del_ie_admin")
    before = _user_count(app)

    def _boom(*args, **kwargs):
        raise IntegrityError("DELETE FROM users", {}, Exception("FOREIGN KEY constraint failed"))

    monkeypatch.setattr("app.admin.ops_user_action_services.safe_delete_user_by_id", _boom)

    response = client.post(f"/admin/users/{target_id}/delete", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("danger", "Bu kullanıcı ilişkili kayıtlar nedeniyle silinemedi.")
    assert _user_count(app) == before
    survivor = _get_user(app, target_id)
    assert survivor is not None and survivor.is_active is True

    # Session-health proof: a real, unrelated follow-up POST (archive) must
    # still succeed and genuinely mutate state after the injected failure +
    # rollback above.
    archive_response = client.post(f"/admin/users/{target_id}/archive", follow_redirects=False)
    assert archive_response.status_code == 302
    reloaded = _get_user(app, target_id)
    assert reloaded.is_active is False


# ---------------------------------------------------------------------------
# admin_users_bulk_delete_impl
# ---------------------------------------------------------------------------


def test_admin_users_bulk_delete_empty_selection_is_safe_no_op(app, client):
    _create_user(app, role="admin", sicil_no="bdel_empty_admin")
    _login(client, "bdel_empty_admin")
    before = _user_count(app)

    response = client.post("/admin/users/bulk-delete", data={}, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Lütfen en az bir personel seçin.")
    assert _user_count(app) == before


def test_admin_users_bulk_delete_all_success_uses_success_flash_variant(app, client):
    _create_user(app, role="admin", sicil_no="bdel_allok_admin")
    t1 = _create_user(app, role="personel", sicil_no="bdel_allok_t1")
    t2 = _create_user(app, role="personel", sicil_no="bdel_allok_t2")
    _login(client, "bdel_allok_admin")

    response = client.post(
        "/admin/users/bulk-delete", data={"user_ids": [str(t1), str(t2)]}, follow_redirects=False
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Toplu silme tamamlandı. Silinen kayıt: 2")
    assert _get_user(app, t1) is None
    assert _get_user(app, t2) is None


def test_admin_users_bulk_delete_mixed_batch_counts_correctly_without_miscounting_nonexistent_ids(app, client):
    """Real, verified counting logic: a nonexistent id is silently `continue`d
    -- counted in NEITHER deleted_count nor blocked_count. Self-targeting is
    counted as blocked (not deleted, not silently ignored)."""
    actor_id = _create_user(app, role="admin", sicil_no="bdel_mix_admin")
    t1 = _create_user(app, role="personel", sicil_no="bdel_mix_t1")
    t2 = _create_user(app, role="personel", sicil_no="bdel_mix_t2")
    _login(client, "bdel_mix_admin")

    response = client.post(
        "/admin/users/bulk-delete",
        data={"user_ids": [str(t1), str(t2), "999999", str(actor_id)]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == (
        "warning",
        "Toplu silme tamamlandı. Silinen: 2, silinemeyen: 1. "
        "Silinemeyen kayıtlar ilişkili veri içeriyor olabilir.",
    )
    assert _get_user(app, t1) is None
    assert _get_user(app, t2) is None
    assert _get_user(app, actor_id) is not None  # self not deleted


def test_admin_users_bulk_delete_blocks_admin_targets_via_safe_delete_guard(app, client):
    """Another real (unmocked) failure path counted as blocked: an admin
    role in the id list hits safe_delete_user_by_id's own admin guard
    (ValueError), caught by bulk_delete's generic `except Exception:` and
    counted as blocked, not deleted, not crashed."""
    _create_user(app, role="admin", sicil_no="bdel_adm_actor")
    other_admin = _create_user(app, role="admin", sicil_no="bdel_adm_other")
    personnel = _create_user(app, role="personel", sicil_no="bdel_adm_personnel")
    _login(client, "bdel_adm_actor")

    response = client.post(
        "/admin/users/bulk-delete",
        data={"user_ids": [str(other_admin), str(personnel)]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == (
        "warning",
        "Toplu silme tamamlandı. Silinen: 1, silinemeyen: 1. "
        "Silinemeyen kayıtlar ilişkili veri içeriyor olabilir.",
    )
    assert _get_user(app, other_admin) is not None  # blocked, not deleted
    assert _get_user(app, personnel) is None  # actually deleted


# ---------------------------------------------------------------------------
# admin_user_archive_impl
# ---------------------------------------------------------------------------


def test_admin_user_archive_success_deactivates_real_row(app, client):
    _create_user(app, role="admin", sicil_no="arc_ok_admin")
    target_id = _create_user(app, role="personel", sicil_no="arc_ok_target", is_active=True)
    _login(client, "arc_ok_admin")

    response = client.post(f"/admin/users/{target_id}/archive", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/users")
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Kullanıcı arşive alındı.")
    reloaded = _get_user(app, target_id)
    assert reloaded.is_active is False


def test_admin_user_archive_blocks_self_target_with_zero_mutation(app, client):
    admin_id = _create_user(app, role="admin", sicil_no="arc_self_admin")
    _login(client, "arc_self_admin")

    response = client.post(f"/admin/users/{admin_id}/archive", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Kendi kullanıcı kaydınız üzerinde bu işlem yapılamaz.")
    reloaded = _get_user(app, admin_id)
    assert reloaded.is_active is True


def test_admin_user_archive_nonexistent_target_is_clean_no_op(app, client):
    _create_user(app, role="admin", sicil_no="arc_missing_admin")
    _login(client, "arc_missing_admin")

    response = client.post("/admin/users/999999/archive", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("danger", "Kullanıcı bulunamadı.")


def test_admin_user_archive_is_idempotent_on_repeated_calls(app, client):
    """See module docstring judgment call #3: is_archived/archived_at do not
    exist on the real User model, so the "already archived" short-circuit
    can never fire -- calling archive twice is real, verified, harmless
    idempotent behavior (is_active stays False, success flash both times),
    not a crash or state corruption."""
    _create_user(app, role="admin", sicil_no="arc_idem_admin")
    target_id = _create_user(app, role="personel", sicil_no="arc_idem_target", is_active=True)
    _login(client, "arc_idem_admin")

    first = client.post(f"/admin/users/{target_id}/archive", follow_redirects=False)
    second = client.post(f"/admin/users/{target_id}/archive", follow_redirects=False)

    assert first.status_code == 302
    assert second.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Kullanıcı arşive alındı.")
    reloaded = _get_user(app, target_id)
    assert reloaded.is_active is False


# ---------------------------------------------------------------------------
# admin_users_bulk_archive_impl
# ---------------------------------------------------------------------------


def test_admin_users_bulk_archive_empty_selection_is_safe_no_op(app, client):
    _create_user(app, role="admin", sicil_no="barc_empty_admin")
    _login(client, "barc_empty_admin")

    response = client.post("/admin/users/bulk-archive", data={}, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Lütfen en az bir personel seçin.")


def test_admin_users_bulk_archive_mixed_batch_counts_correctly_and_only_touches_listed_rows(app, client):
    actor_id = _create_user(app, role="admin", sicil_no="barc_mix_admin")
    t1 = _create_user(app, role="personel", sicil_no="barc_mix_t1", is_active=True)
    t2 = _create_user(app, role="personel", sicil_no="barc_mix_t2", is_active=True)
    bystander = _create_user(app, role="personel", sicil_no="barc_mix_bystander", is_active=True)
    _login(client, "barc_mix_admin")

    response = client.post(
        "/admin/users/bulk-archive",
        data={"user_ids": [str(t1), str(t2), str(actor_id), "999999"]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Toplu arşivleme tamamlandı. Güncellenen kayıt: 2")
    assert _get_user(app, t1).is_active is False
    assert _get_user(app, t2).is_active is False
    assert _get_user(app, actor_id).is_active is True  # self skipped, not archived
    assert _get_user(app, bystander).is_active is True  # never listed, never touched


# ---------------------------------------------------------------------------
# admin_user_toggle_active_impl
# ---------------------------------------------------------------------------


def test_admin_user_toggle_active_default_flip_only_mutates_intended_target(app, client):
    _create_user(app, role="admin", sicil_no="tog_flip_admin")
    target_id = _create_user(app, role="personel", sicil_no="tog_flip_target", is_active=True)
    bystander_id = _create_user(app, role="personel", sicil_no="tog_flip_bystander", is_active=True)
    _login(client, "tog_flip_admin")

    response = client.post(f"/admin/users/{target_id}/toggle-active", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Kullanıcı durumu güncellendi.")
    assert _get_user(app, target_id).is_active is False
    assert _get_user(app, bystander_id).is_active is True  # untouched


def test_admin_user_toggle_active_blocks_self_target_with_zero_mutation(app, client):
    admin_id = _create_user(app, role="admin", sicil_no="tog_self_admin", is_active=True)
    _login(client, "tog_self_admin")

    response = client.post(f"/admin/users/{admin_id}/toggle-active", follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Kendi kullanıcı kaydınız üzerinde bu işlem yapılamaz.")
    assert _get_user(app, admin_id).is_active is True


def test_admin_user_toggle_active_explicit_target_state_matching_current_is_rejected_boundary(app, client):
    """ensure_boolean_toggle raises ValueError when the requested explicit
    state already matches the current state -- a real boundary the route
    surfaces as a clean warning, not a silent no-op or a crash, and with
    zero mutation."""
    _create_user(app, role="admin", sicil_no="tog_same_admin")
    target_id = _create_user(app, role="personel", sicil_no="tog_same_target", is_active=True)
    _login(client, "tog_same_admin")

    response = client.post(
        f"/admin/users/{target_id}/toggle-active", data={"target_state": "aktif"}, follow_redirects=False
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Kullanıcı zaten aktif durumda.")
    assert _get_user(app, target_id).is_active is True


def test_admin_user_toggle_active_explicit_target_state_pasif_deactivates(app, client):
    _create_user(app, role="admin", sicil_no="tog_pasif_admin")
    target_id = _create_user(app, role="personel", sicil_no="tog_pasif_target", is_active=True)
    _login(client, "tog_pasif_admin")

    response = client.post(
        f"/admin/users/{target_id}/toggle-active", data={"target_state": "pasif"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert _get_user(app, target_id).is_active is False


def test_admin_user_toggle_active_explicit_target_state_aktif_activates(app, client):
    _create_user(app, role="admin", sicil_no="tog_aktif_admin")
    target_id = _create_user(app, role="personel", sicil_no="tog_aktif_target", is_active=False)
    _login(client, "tog_aktif_admin")

    response = client.post(
        f"/admin/users/{target_id}/toggle-active", data={"target_state": "aktif"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert _get_user(app, target_id).is_active is True


# ---------------------------------------------------------------------------
# admin_users_bulk_passive_impl
# ---------------------------------------------------------------------------


def test_admin_users_bulk_passive_empty_selection_is_safe_no_op(app, client):
    _create_user(app, role="admin", sicil_no="bpas_empty_admin")
    _login(client, "bpas_empty_admin")

    response = client.post("/admin/users/bulk-passive", data={}, follow_redirects=False)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Lütfen en az bir personel seçin.")


def test_admin_users_bulk_passive_mixed_batch_skips_already_passive_without_miscounting(app, client):
    actor_id = _create_user(app, role="admin", sicil_no="bpas_mix_admin")
    active1 = _create_user(app, role="personel", sicil_no="bpas_mix_active1", is_active=True)
    active2 = _create_user(app, role="personel", sicil_no="bpas_mix_active2", is_active=True)
    already_passive = _create_user(app, role="personel", sicil_no="bpas_mix_passive", is_active=False)
    _login(client, "bpas_mix_admin")

    response = client.post(
        "/admin/users/bulk-passive",
        data={
            "user_ids": [str(active1), str(active2), str(already_passive), str(actor_id), "999999"]
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Toplu pasif yapma tamamlandı. Güncellenen kayıt: 2")
    assert _get_user(app, active1).is_active is False
    assert _get_user(app, active2).is_active is False
    assert _get_user(app, already_passive).is_active is False  # unchanged, not double-counted
    assert _get_user(app, actor_id).is_active is True  # self skipped


# ---------------------------------------------------------------------------
# admin_user_change_photo_impl
# ---------------------------------------------------------------------------


def test_admin_user_change_photo_nonexistent_target_is_clean_no_op(app, client):
    _create_user(app, role="admin", sicil_no="photo_missing_admin")
    _login(client, "photo_missing_admin")

    response = client.post("/admin/users/999999/photo", data={}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/users")
    flashes = _flashes(client)
    assert flashes[-1] == ("danger", "Kullanıcı bulunamadı.")


def test_admin_user_change_photo_no_file_no_remove_flag_rejected_no_mutation(app, client):
    _create_user(app, role="admin", sicil_no="photo_nofile_admin")
    target_id = _create_user(app, role="personel", sicil_no="photo_nofile_target")
    _login(client, "photo_nofile_admin")

    response = client.post(f"/admin/users/{target_id}/photo", data={}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith(f"/admin/users/{target_id}/edit")
    flashes = _flashes(client)
    assert flashes[-1] == ("warning", "Lütfen bir fotoğraf seçin.")
    reloaded = _get_user(app, target_id)
    assert reloaded.profile_photo_path is None


def test_admin_user_change_photo_remove_flag_mutates_real_row(app, client):
    _create_user(app, role="admin", sicil_no="photo_remove_admin")
    target_id = _create_user(app, role="personel", sicil_no="photo_remove_target")
    _login(client, "photo_remove_admin")

    response = client.post(
        f"/admin/users/{target_id}/photo", data={"remove_profile_photo": "1"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith(f"/admin/users/{target_id}/edit")
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Profil fotoğrafı kaldırıldı.")
    reloaded = _get_user(app, target_id)
    assert reloaded.profile_photo_path is None
    assert reloaded.profile_photo_updated_at is not None


def test_admin_user_change_photo_invalid_extension_rejected_with_no_mutation(app, client):
    """save_profile_photo (app/services/profile_photo_service.py) raises a
    real ValueError for a disallowed extension, before touching the file
    system or the user row. admin_user_change_photo_impl's generic
    `except Exception` branch catches it, rolls back, and flashes the real
    message -- exercised here with zero mocking."""
    _create_user(app, role="admin", sicil_no="photo_badext_admin")
    target_id = _create_user(app, role="personel", sicil_no="photo_badext_target")
    _login(client, "photo_badext_admin")

    response = client.post(
        f"/admin/users/{target_id}/photo",
        data={"profile_photo": (io.BytesIO(b"not-a-real-image"), "malware.exe")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes[-1] == (
        "danger",
        "Profil fotoğrafı güncellenirken hata oluştu: Sadece PNG, JPG, JPEG veya WEBP dosyaları yükleyebilirsiniz.",
    )
    reloaded = _get_user(app, target_id)
    assert reloaded.profile_photo_path is None


def test_admin_user_change_photo_valid_upload_succeeds_and_mutates_real_row(app, client, monkeypatch):
    """Exercises the full real save_profile_photo path (secure_filename,
    extension check, private-root containment, DB field updates) with the
    private upload root pointed at this file's own scratch temp directory --
    never the repo's app/static or instance/ folders. B2-F06 refuses any write
    outside the private root, so the root itself is redirected rather than the
    upload directory."""
    os.makedirs(_TMP_PHOTO_DIR, exist_ok=True)
    monkeypatch.setitem(app.config, "PRIVATE_UPLOAD_FOLDER", _TMP_PHOTO_DIR)

    _create_user(app, role="admin", sicil_no="photo_ok_admin")
    target_id = _create_user(app, role="personel", sicil_no="photo_ok_target")
    _login(client, "photo_ok_admin")

    response = client.post(
        f"/admin/users/{target_id}/photo",
        data={"profile_photo": (io.BytesIO(b"\x89PNG\r\n\x1a\nfake-but-harmless-bytes"), "photo.png")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith(f"/admin/users/{target_id}/edit")
    flashes = _flashes(client)
    assert flashes[-1] == ("success", "Profil fotoğrafı güncellendi.")
    reloaded = _get_user(app, target_id)
    assert reloaded.profile_photo_path is not None
    assert reloaded.profile_photo_path.startswith("uploads/profile_photos/")
    assert reloaded.profile_photo_path.endswith(".png")
    assert reloaded.profile_photo_updated_at is not None

    saved_name = reloaded.profile_photo_path.rsplit("/", 1)[-1]
    assert os.path.isfile(os.path.join(_TMP_PHOTO_DIR, "profile_photos", saved_name))
    static_copy = os.path.join(app.static_folder, "uploads", "profile_photos", saved_name)
    assert not os.path.exists(static_copy)


# ---------------------------------------------------------------------------
# admin_users_reset_all_impl -- highest-risk function in scope. See module
# docstring judgment call #1: never run against a real cascade here.
# ---------------------------------------------------------------------------


def test_admin_users_reset_all_rejects_anonymous_without_invoking_cascade(app, client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.admin.ops_user_action_services.reset_all_personnel_and_related_data",
        lambda: calls.append(1),
    )

    response = client.post("/admin/users/reset-all", follow_redirects=False)

    assert response.status_code == 403
    assert calls == []


def test_admin_users_reset_all_rejects_non_admin_without_invoking_cascade(app, client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.admin.ops_user_action_services.reset_all_personnel_and_related_data",
        lambda: calls.append(1),
    )
    _create_user(app, role="personel", sicil_no="reset_na")
    _login(client, "reset_na")

    response = client.post("/admin/users/reset-all", follow_redirects=False)

    assert response.status_code == 403
    assert calls == []


def test_admin_users_reset_all_admin_success_invokes_cascade_exactly_once(app, client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.admin.ops_user_action_services.reset_all_personnel_and_related_data",
        lambda: calls.append(1),
    )
    _create_user(app, role="admin", sicil_no="reset_admin_ok")
    _login(client, "reset_admin_ok")

    response = client.post("/admin/users/reset-all", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/users")
    flashes = _flashes(client)
    assert flashes[-1] == (
        "success",
        "Personel, hiyerarşi ve ilişkili performans verileri tamamen sıfırlandı.",
    )
    assert calls == [1]


def test_admin_users_reset_all_exception_from_cascade_is_rolled_back_not_a_raw_500(app, client, monkeypatch):
    """BYS360 H1F (exception-display hardening): this branch's flash used to
    append the raw exception's own text after a colon
    (f"Sifirlama islemi sirasinda hata olustu: {exc}") -- a genuinely
    unexpected RuntimeError's message leaking to the admin verbatim. Fixed
    to a fixed safe message; this assertion was updated to match (see
    tests/behavior/test_h1f_final_audit_second_pass_exception_leak_contract.py
    for the sentinel-injection proof)."""

    def _boom():
        raise RuntimeError("simulated cascade failure")

    monkeypatch.setattr(
        "app.admin.ops_user_action_services.reset_all_personnel_and_related_data",
        _boom,
    )
    admin_id = _create_user(app, role="admin", sicil_no="reset_admin_fail")
    _login(client, "reset_admin_fail")

    response = client.post("/admin/users/reset-all", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/users")
    flashes = _flashes(client)
    assert flashes[-1] == ("danger", "Sıfırlama işlemi sırasında hata oluştu.")

    # Session-health proof after rollback: the acting admin's own row is
    # still readable and consistent, not corrupted by the failed cascade.
    survivor = _get_user(app, admin_id)
    assert survivor is not None and survivor.role == "admin"
