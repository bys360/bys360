"""BYS360_PHASE5_COVERAGE_WAVE5_AGENT3_FILE_CENTER_QUOTA_ROLE_MATRIX_CONTRACT

Behavioral, route-boundary contract for the 5 route functions given verbatim
in this wave's scope (app/file_center/routes.py):

    file_center_quota_policy_save        POST /file-center/quota/policy
    file_center_quota_policy_deactivate  POST /file-center/quota/policy/<id>/deactivate
    file_center_role_matrix              GET  /file-center/settings/roles
    file_center_role_matrix_save         POST /file-center/settings/roles
    file_center_role_matrix_defaults     POST /file-center/settings/roles/defaults

(The scope header says "exactly 4 routes" but the verbatim source block that
follows it contains all 5 of the above -- the GET role-matrix view is gated
by the same `can_manage_file_center_role_matrix` check as its two POST
siblings and has an explicitly required test of its own (the defaults-reseed
side effect of a GET). All 5 are treated as in scope; nothing outside this
exact source block is touched.)

Division of labor: a separate specialist (Agent 2,
test_file_center_permission_engine_contract.py) owns direct unit tests of
update_role_matrix_from_form / ensure_file_center_role_matrix_defaults /
permission-resolution internals (_effective_role_key, _permission_from_matrix,
etc). This file never calls those internals directly -- every assertion here
goes through a real Flask test-client HTTP request, the route's real
`can_manage_file_center_quota_policy` / `can_manage_file_center_role_matrix`
gate (never monkeypatched), the real service functions, and a real follow-up
DB read.

Judgment calls, documented rather than silently baked in:

1. Defect I (already known/deferred): app/file_center/permissions.py's
   `_effective_role_key` misclassifies ANY identity whose joined
   role/username/email/title/department/unit/job_title text contains the
   substring "admin" as an admin. Positive tests use a real, unambiguous
   `role="admin"` user (the genuine explicit-match path). Negative tests use
   a clean personnel identity with no substring collision anywhere:
   sicil_no="FCR000001"-style, email="fcr-personel-N@bys360.test",
   ad="Deniz", soyad="Yildiz" -- nothing containing "admin", "baskan",
   "yonetici", "koordinator", "amir", or "mudur". DEFECT_I_COLLISION_AVOIDED.

2. `file_center_enabled()` defaults to False (`_db_bool(..., False)`), and
   with an empty (freshly created) `file_center_settings` table,
   `get_setting_raw` falls through to that same default -- so
   `monkeypatch.setenv("FILE_CENTER_ENABLED", "true")` is required for every
   test in this file (verified by reading app/file_center/services.py's
   `_db_bool`/`env_bool` and settings_service.py's `get_setting_raw`) or the
   `_enabled_or_message()` gate would redirect home before the
   authorization gate under test is even reached.

3. `update_role_matrix_from_form`'s per-row loop has no "keep current value"
   fallback for `is_active` or any PERMISSION_FIELDS checkbox: it is
   `form.get(prefix + field) in {"on", ...}` with no default, unlike
   `role_label`/`description` which fall back to the row's current value.
   Reading the real template (app/templates/file_center/role_matrix.html)
   confirms this is not a route defect: the single settings page renders one
   `<form>` covering every row's checkboxes together, so a real browser
   submission always carries full current state for every row. This file's
   `_role_matrix_form_payload` helper mirrors that real full-page submission
   shape (every existing row's current state, plus explicit overrides) so
   the "valid update" test proves a real, realistic save -- not an artifact
   of an incomplete test payload silently wiping every other role's
   permissions. The "valid update" test explicitly asserts every untouched
   row is byte-for-byte unchanged to prove this.

4. Flask's `session["_flashes"]` is not consumed by a raw redirect response
   (only `get_flashed_messages()` in a rendered template pops it), so
   `_flashes()` after two sequential POSTs in the same test returns BOTH
   flashes. Assertions use `any(...)` with distinguishing substrings so this
   accumulation cannot produce a false positive.

Fixture pattern: this wave's mandatory proven shape, copied from
tests/behavior/test_admin_ops_user_actions_destructive_operations_contract.py
lines 110-183 (Config class-attribute patch BEFORE create_app(), StaticPool +
pysqlite isolation_level=None + explicit BEGIN event listener). Uses its own
dedicated tmp DB directory (C:\\bys360_pytest_tmp_agent3_filecenter) so this
file shares no state with any other wave/agent running concurrently.
Filesystem: this route scope (quota policy CRUD + role matrix CRUD) is pure
ORM against FileQuotaPolicy / FileCenterRolePermission -- no storage/
filesystem access anywhere in the 5 routes or the service functions they
call, confirmed by reading app/file_center/services.py's
create_or_update_quota_policy/deactivate_quota_policy bodies.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent3_filecenter")

DEFAULT_PASSWORD = "FileCenterQuotaRoleTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "file-center-quota-role-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-file-center-quota-role-contract")
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
    # See module docstring judgment call 2: file_center_enabled() defaults to
    # False and this test DB's file_center_settings table starts empty, so
    # the env fallback is the only way to flip it on for these tests.
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"agent3_fc_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
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
# User / login helpers
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role, sicil_no, email, ad, soyad, is_active=True, password=DEFAULT_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad=ad,
            soyad=soyad,
            role=role,
            is_active=is_active,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_admin(app):
    """Genuine, unambiguous admin: role="admin" exactly (real explicit-match path)."""
    n = _next_suffix()
    sicil = f"FCRADM{n:06d}"
    uid = _create_user(
        app,
        role="admin",
        sicil_no=sicil,
        email=f"fcr-admin-{n}@bys360.test",
        ad="Admin",
        soyad=f"Test{n}",
    )
    return uid, sicil


def _create_personnel(app):
    """Clean ordinary personnel identity -- see module docstring judgment call 1."""
    n = _next_suffix()
    sicil = f"FCR{n:06d}"
    uid = _create_user(
        app,
        role="personel",
        sicil_no=sicil,
        email=f"fcr-personel-{n}@bys360.test",
        ad="Deniz",
        soyad="Yildiz",
    )
    return uid, sicil


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


# ---------------------------------------------------------------------------
# DB read helpers -- always fully materialize primitives inside their own
# app_context so returned data survives outside the `with` block.
# ---------------------------------------------------------------------------


def _quota_policy_snapshot(app):
    from app.models.file_center_models import FileQuotaPolicy

    with app.app_context():
        rows = FileQuotaPolicy.query.order_by(FileQuotaPolicy.id.asc()).all()
        return [
            {
                "id": r.id,
                "scope_type": r.scope_type,
                "scope_value": r.scope_value,
                "label": r.label,
                "max_storage_gb": r.max_storage_gb,
                "max_single_file_gb": r.max_single_file_gb,
                "max_transfer_gb": r.max_transfer_gb,
                "warning_threshold_percent": r.warning_threshold_percent,
                "hard_stop_enabled": r.hard_stop_enabled,
                "is_active": r.is_active,
                "notes": r.notes,
                "created_by_user_id": r.created_by_user_id,
            }
            for r in rows
        ]


def _role_matrix_snapshot(app):
    from app.file_center.permissions import PERMISSION_FIELDS
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        rows = FileCenterRolePermission.query.order_by(FileCenterRolePermission.id.asc()).all()
        out = []
        for r in rows:
            item = {
                "id": r.id,
                "role_key": r.role_key,
                "role_label": r.role_label,
                "description": r.description,
                "is_active": bool(r.is_active),
                "updated_by_user_id": r.updated_by_user_id,
            }
            for field in PERMISSION_FIELDS:
                item[field] = bool(getattr(r, field))
            out.append(item)
        return out


def _audit_log_count(app, action=None):
    from app.models.file_center_models import FileAuditLog

    with app.app_context():
        query = FileAuditLog.query
        if action:
            query = query.filter_by(action=action)
        return query.count()


def _snapshot_all(app):
    return (_quota_policy_snapshot(app), _role_matrix_snapshot(app), _audit_log_count(app))


# ---------------------------------------------------------------------------
# Form-payload builders
# ---------------------------------------------------------------------------


def _valid_quota_form(**overrides):
    data = {
        "scope_type": "global",
        "scope_value": "",
        "label": "Test Kota Politikası",
        "max_storage_gb": "50",
        "max_single_file_gb": "10",
        "max_transfer_gb": "30",
        "warning_threshold_percent": "75",
        "hard_stop_enabled": "on",
        "notes": "ilk not",
    }
    data.update(overrides)
    return data


def _role_matrix_form_payload(snapshot, overrides=None):
    """Build a full-page-realistic role-matrix-save payload: every row's
    current checkbox state, plus explicit per-row overrides. See module
    docstring judgment call 3 for why "full page" matters here.
    """
    from app.file_center.permissions import PERMISSION_FIELDS

    overrides = overrides or {}
    data = {}
    for row in snapshot:
        prefix = f"role_{row['id']}_"
        row_overrides = overrides.get(row["id"], {})
        data[prefix + "role_label"] = row_overrides.get("role_label", row["role_label"] or "")
        data[prefix + "description"] = row_overrides.get("description", row["description"] or "")
        is_active = row_overrides.get("is_active", row["is_active"])
        if is_active:
            data[prefix + "is_active"] = "on"
        for field in PERMISSION_FIELDS:
            value = row_overrides.get(field, row[field])
            if value:
                data[prefix + field] = "on"
    return data


# ---------------------------------------------------------------------------
# Authorization + zero-mutation contract across all 5 in-scope routes
# ---------------------------------------------------------------------------


PROTECTED_ROUTE_REQUESTS = [
    pytest.param(
        lambda c: c.post("/file-center/quota/policy", data=_valid_quota_form(), follow_redirects=False),
        id="quota-policy-save",
    ),
    pytest.param(
        lambda c: c.post("/file-center/quota/policy/1/deactivate", data={}, follow_redirects=False),
        id="quota-policy-deactivate",
    ),
    pytest.param(
        lambda c: c.get("/file-center/settings/roles", follow_redirects=False),
        id="role-matrix-get",
    ),
    pytest.param(
        lambda c: c.post("/file-center/settings/roles", data={}, follow_redirects=False),
        id="role-matrix-save",
    ),
    pytest.param(
        lambda c: c.post("/file-center/settings/roles/defaults", data={}, follow_redirects=False),
        id="role-matrix-defaults",
    ),
]


@pytest.mark.parametrize("make_request", PROTECTED_ROUTE_REQUESTS)
def test_protected_route_rejects_personnel_with_zero_mutation(app, client, make_request):
    _uid, sicil = _create_personnel(app)
    _login(client, sicil)
    before = _snapshot_all(app)

    response = make_request(client)

    assert response.status_code == 403
    assert _snapshot_all(app) == before


# ---------------------------------------------------------------------------
# Quota policy contract
# ---------------------------------------------------------------------------


def test_quota_policy_admin_create_and_reupsert_same_scope_updates_single_row(app, client):
    admin_id, sicil = _create_admin(app)
    _login(client, sicil)

    resp1 = client.post(
        "/file-center/quota/policy",
        data=_valid_quota_form(label="İlk Politika", max_storage_gb="40"),
        follow_redirects=False,
    )
    assert resp1.status_code == 302
    assert resp1.headers["Location"].endswith("/file-center/quota")
    assert any(cat == "success" for cat, _msg in _flashes(client))

    rows1 = _quota_policy_snapshot(app)
    assert len(rows1) == 1
    assert rows1[0]["scope_type"] == "global"
    assert rows1[0]["scope_value"] is None
    assert rows1[0]["label"] == "İlk Politika"
    assert rows1[0]["max_storage_gb"] == 40.0
    assert rows1[0]["hard_stop_enabled"] is True
    assert rows1[0]["created_by_user_id"] == admin_id

    resp2 = client.post(
        "/file-center/quota/policy",
        data=_valid_quota_form(label="Güncellenmiş Politika", max_storage_gb="60"),
        follow_redirects=False,
    )
    assert resp2.status_code == 302

    rows2 = _quota_policy_snapshot(app)
    assert len(rows2) == 1  # upsert by (scope_type, scope_value, is_active) -- not a duplicate
    assert rows2[0]["id"] == rows1[0]["id"]
    assert rows2[0]["label"] == "Güncellenmiş Politika"
    assert rows2[0]["max_storage_gb"] == 60.0


def test_quota_policy_admin_deactivate_valid_id_flips_is_active(app, client):
    admin_id, sicil = _create_admin(app)
    _login(client, sicil)
    client.post("/file-center/quota/policy", data=_valid_quota_form(), follow_redirects=False)
    rows = _quota_policy_snapshot(app)
    assert len(rows) == 1
    assert rows[0]["is_active"] is True
    policy_id = rows[0]["id"]

    resp = client.post(f"/file-center/quota/policy/{policy_id}/deactivate", data={}, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/file-center/quota")
    rows_after = _quota_policy_snapshot(app)
    assert len(rows_after) == 1
    assert rows_after[0]["id"] == policy_id
    assert rows_after[0]["is_active"] is False
    assert any(cat == "success" for cat, _msg in _flashes(client))


def test_quota_policy_admin_deactivate_missing_id_is_caught_not_a_raw_404(app, client):
    admin_id, sicil = _create_admin(app)
    _login(client, sicil)
    client.post("/file-center/quota/policy", data=_valid_quota_form(), follow_redirects=False)
    rows_before = _quota_policy_snapshot(app)
    assert len(rows_before) == 1

    # Flask-SQLAlchemy's get_or_404 raises werkzeug NotFound here, which the
    # route's own `except Exception` (Flask's own 404-abort mechanism, not
    # app logic) catches -- so this resolves as a normal redirect with a
    # danger flash, never a raw 404 response.
    missing_id = rows_before[0]["id"] + 999999
    resp = client.post(f"/file-center/quota/policy/{missing_id}/deactivate", data={}, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/file-center/quota")
    assert any(cat == "danger" for cat, _msg in _flashes(client))
    rows_after = _quota_policy_snapshot(app)
    assert rows_after == rows_before  # zero further mutation


def test_quota_policy_admin_invalid_numeric_field_rolls_back_with_zero_mutation(app, client):
    admin_id, sicil = _create_admin(app)
    _login(client, sicil)
    assert _quota_policy_snapshot(app) == []

    resp = client.post(
        "/file-center/quota/policy",
        data=_valid_quota_form(max_storage_gb="not-a-number"),
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/file-center/quota")
    assert _quota_policy_snapshot(app) == []
    assert any(cat == "danger" for cat, _msg in _flashes(client))


# ---------------------------------------------------------------------------
# Role matrix contract
# ---------------------------------------------------------------------------


def test_role_matrix_get_as_admin_seeds_defaults_on_first_visit(app, client):
    from app.file_center.permissions import DEFAULT_ROLE_MATRIX

    admin_id, sicil = _create_admin(app)
    _login(client, sicil)
    assert _role_matrix_snapshot(app) == []

    resp = client.get("/file-center/settings/roles", follow_redirects=False)

    assert resp.status_code == 200
    rows = _role_matrix_snapshot(app)
    assert len(rows) == len(DEFAULT_ROLE_MATRIX)
    assert {r["role_key"] for r in rows} == {item.role_key for item in DEFAULT_ROLE_MATRIX}


def test_role_matrix_save_admin_updates_row_logs_audit_and_preserves_other_rows(app, client):
    admin_id, sicil = _create_admin(app)
    _login(client, sicil)
    client.get("/file-center/settings/roles", follow_redirects=False)  # seed defaults
    before = _role_matrix_snapshot(app)
    audit_before = _audit_log_count(app, action="file_center_role_matrix_updated")

    personnel_row = next(r for r in before if r["role_key"] == "personel")
    assert personnel_row["can_view_logs"] is False  # real starting default, prove the flip below

    payload = _role_matrix_form_payload(
        before,
        overrides={
            personnel_row["id"]: {
                "role_label": "Personel (Güncellendi)",
                "description": "Test amaçlı güncellenmiş açıklama.",
                "can_view_logs": True,
            }
        },
    )

    resp = client.post("/file-center/settings/roles", data=payload, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/file-center/settings/roles")

    after = _role_matrix_snapshot(app)
    updated = next(r for r in after if r["id"] == personnel_row["id"])
    assert updated["role_label"] == "Personel (Güncellendi)"
    assert updated["description"] == "Test amaçlı güncellenmiş açıklama."
    assert updated["can_view_logs"] is True

    for row in after:
        if row["id"] == personnel_row["id"]:
            continue
        original = next(r for r in before if r["id"] == row["id"])
        assert row == original  # every other role's state untouched by this save

    assert any(cat == "success" for cat, _msg in _flashes(client))
    audit_after = _audit_log_count(app, action="file_center_role_matrix_updated")
    assert audit_after == audit_before + 1


def test_role_matrix_defaults_admin_idempotent_second_call_creates_nothing(app, client):
    from app.file_center.permissions import DEFAULT_ROLE_MATRIX

    admin_id, sicil = _create_admin(app)
    _login(client, sicil)
    assert _role_matrix_snapshot(app) == []

    resp1 = client.post("/file-center/settings/roles/defaults", data={}, follow_redirects=False)
    assert resp1.status_code == 302
    rows_after_first = _role_matrix_snapshot(app)
    assert len(rows_after_first) == len(DEFAULT_ROLE_MATRIX)
    flashes1 = _flashes(client)
    assert any(
        cat == "success" and f"Yeni: {len(DEFAULT_ROLE_MATRIX)}" in msg and "Güncellenen: 0" in msg
        for cat, msg in flashes1
    )

    resp2 = client.post("/file-center/settings/roles/defaults", data={}, follow_redirects=False)
    assert resp2.status_code == 302
    rows_after_second = _role_matrix_snapshot(app)
    assert rows_after_second == rows_after_first  # no duplication, no drift

    flashes2 = _flashes(client)
    assert any(
        cat == "success" and "Yeni: 0" in msg and "Güncellenen: 0" in msg
        for cat, msg in flashes2
    )


def test_role_matrix_save_admin_ignores_unknown_row_id_and_incomplete_new_role(app, client):
    admin_id, sicil = _create_admin(app)
    _login(client, sicil)
    client.get("/file-center/settings/roles", follow_redirects=False)  # seed defaults
    before = _role_matrix_snapshot(app)

    payload = _role_matrix_form_payload(before)  # full realistic unmodified state
    payload["role_999999_role_label"] = "Hayalet Rol"  # nonexistent row id -- must be ignored
    payload["role_999999_is_active"] = "on"
    payload["new_role_key"] = "yalnizca_anahtar"  # label missing -- malformed combo, must not create a row

    resp = client.post("/file-center/settings/roles", data=payload, follow_redirects=False)

    assert resp.status_code == 302  # no crash, no 500
    assert resp.headers["Location"].endswith("/file-center/settings/roles")
    after = _role_matrix_snapshot(app)
    assert after == before  # unknown id ignored, incomplete new-role combo ignored, zero drift
    assert any(cat == "success" and "Değişen alan: 0" in msg for cat, msg in _flashes(client))


# ---------------------------------------------------------------------------
# Baseline sanity: the plain-GET quota dashboard (login_required only, no
# can_manage_* gate) is reachable for any authenticated role. Not the focus
# of this file, but proves the fixture/login/enabled-flag wiring end to end.
# ---------------------------------------------------------------------------


def test_quota_dashboard_get_is_reachable_for_authenticated_personnel(app, client):
    _uid, sicil = _create_personnel(app)
    _login(client, sicil)

    resp = client.get("/file-center/quota", follow_redirects=False)

    assert resp.status_code == 200
