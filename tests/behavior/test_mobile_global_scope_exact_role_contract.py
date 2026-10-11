"""BYS360_DEFECT_V_MOBILE_GLOBAL_SCOPE_OVERGRANT

Regression contract for a mechanically-confirmed authorization overgrant in
``app.api.mobile.shared._has_global_scope``.

Root cause (confirmed by reading the source before this fix): the function
already had an exact-membership check against the canonical ``_GLOBAL_ROLES``
set, but ALSO fell back to substring membership --
``"admin" in role or "başkan" in role or "baskan" in role``. Because Python's
``in`` on strings is substring containment, any role whose normalized text
merely *contains* one of those fragments was granted global (org-wide) scope
regardless of the exact-role policy. The concrete, real, currently-defined
role this breaks is ``grup_baskani`` ("Grup Başkanı" / Group Head) --
confirmed via ``app/admin/routes.py`` (role choice list) and
``app/menu_registry_data_performance.py`` (module role sets), where
``grup_baskani`` is listed as a distinct, narrower role alongside
``birim_sorumlusu``/``koordinator``/``mali_musavir`` -- never alongside
``admin``/``baskan``/``baskan_yardimcisi`` as an equivalent. The substring
``"baskan" in "grup_baskani"`` is True, so every grup_baskani caller silently
received the exact same unrestricted, organization-wide mobile data scope as
an actual ``baskan`` (President), across every one of ``_has_global_scope``'s
~30 call sites.

Fix (reviewed contract, reused verbatim from the pre-existing exact
``_GLOBAL_ROLES`` set already defined at the top of
``app/api/mobile/shared.py`` -- not invented): the substring fallback is
removed. ``_has_global_scope`` now grants global scope if and only if the
caller's normalized ``role`` or ``role_label`` is an exact member of
``_GLOBAL_ROLES``.

This file is split into two parts:

1. Direct unit-level assertions against ``_has_global_scope`` itself (no
   mocking of the function under test -- real ``User`` model instances with
   varied ``role``/``role_label`` combinations), covering the canonical
   exact-role contract end to end including normalization and the
   substring-overgrant regression.
2. Two representative end-to-end mobile route assertions (collateral review,
   not exhaustive -- ~30 call sites exist across the mobile API, per the
   remediation wave's own scope instruction not to test all of them):
   - GET /api/mobile/kpi/goals: a row-level query gate (reuses the Defect P
     regression endpoint, see
     tests/behavior/test_mobile_kpi_goals_scope_leak_contract.py).
   - GET /api/mobile/dashboard/summary: a count/aggregate + performance
     (PerformancePresidentApproval) gate in the same request.
   Both prove a grup_baskani caller is confined to personal scope exactly
   like an ordinary "personel" caller, and that a real global role (baskan)
   keeps its full unscoped access unchanged.

Fixture pattern: proven per this remediation wave's mandatory rule -- copied
from tests/behavior/test_mobile_kpi_goals_scope_leak_contract.py's
``_make_app`` (Config class attributes monkeypatched BEFORE create_app(),
StaticPool + pysqlite isolation_level=None + explicit BEGIN event listener)
and the mobile bearer-token helper shape used throughout the Defect N/O/P
regression suites (real app.api.mobile.shared._issue_token(user), no
hand-rolled tokens, no mocking of the authorization check itself). Uses its
own dedicated tmp DB directory (C:\\bys360_pytest_tmp_defect_v) so it shares
no state with any other wave/agent running concurrently.
"""
from __future__ import annotations

import datetime
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_v")

DEFAULT_PASSWORD = "DefectVContractTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "defect-v-first-login-test-pw"

_user_counter = 0

_ROUTE_KPI_GOALS = "/api/mobile/kpi/goals"
_ROUTE_DASHBOARD_SUMMARY = "/api/mobile/dashboard/summary"


# ---------------------------------------------------------------------------
# Part 1: direct unit-level contract for _has_global_scope
# ---------------------------------------------------------------------------


def test_exact_global_roles_grant_global_scope():
    from app.api.mobile.shared import _GLOBAL_ROLES, _has_global_scope
    from app.models import User

    for role in sorted(_GLOBAL_ROLES):
        user = User(role=role)
        assert _has_global_scope(user) is True, f"canonical global role {role!r} must grant global scope"


@pytest.mark.parametrize(
    "role",
    ["grup_baskani", "birim_sorumlusu", "koordinator", "mali_musavir", "personel"],
)
def test_unit_and_group_scoped_roles_are_not_global(role):
    from app.api.mobile.shared import _has_global_scope
    from app.models import User

    assert _has_global_scope(User(role=role)) is False, f"{role!r} must NOT be global scope"


def test_grup_baskani_case_and_whitespace_variants_stay_non_global():
    from app.api.mobile.shared import _has_global_scope
    from app.models import User

    for variant in ("GRUP_BASKANI", " grup_baskani ", "Grup_Baskani", "grup_başkanı"):
        assert _has_global_scope(User(role=variant)) is False, (
            f"normalized variant {variant!r} of grup_baskani must not be granted global scope"
        )


def test_baskan_case_and_whitespace_variants_still_resolve_global_via_normalization():
    from app.api.mobile.shared import _has_global_scope
    from app.models import User

    for variant in ("BASKAN", " baskan ", "Baskan"):
        assert _has_global_scope(User(role=variant)) is True, (
            f"canonical normalization (strip+lower) must still recognize {variant!r} as baskan"
        )


def test_substring_overgrant_regression_synthetic_roles_stay_non_global():
    """Adversarial probe: before the fix, ANY role text merely containing the
    fragments "admin"/"başkan"/"baskan" was granted global scope, not just
    grup_baskani. These are not real BYS360 roles -- they exist only to prove
    the substring path itself is gone, not just patched for one string."""
    from app.api.mobile.shared import _has_global_scope
    from app.models import User

    for role in ("eski_baskan_danismani", "baskan_ofisi_uzmani", "grup_baskani_yardimcisi"):
        assert _has_global_scope(User(role=role)) is False, (
            f"synthetic non-member role {role!r} containing a global-role fragment "
            "must not be granted global scope by substring matching"
        )


def test_role_label_never_grants_global_scope_when_role_itself_is_not():
    # B1-F1 decision 3 (HUMAN_POLICY_APPROVED, 2026-10-09): role_label is display text and never
    # grants institution-wide scope on its own, also when the stored role is empty.
    from app.api.mobile.shared import _has_global_scope
    from app.models import User

    for label in ("baskan", "admin", "Admin", "sistem_yoneticisi"):
        assert _has_global_scope(User(role="personel", role_label=label)) is False, label
        assert _has_global_scope(User(role="", role_label=label)) is False, label


def test_role_label_grup_baskani_does_not_grant_global_scope():
    from app.api.mobile.shared import _has_global_scope
    from app.models import User

    user = User(role="personel", role_label="grup_baskani")
    assert _has_global_scope(user) is False


def test_empty_or_missing_role_is_not_global():
    from app.api.mobile.shared import _has_global_scope
    from app.models import User

    assert _has_global_scope(User(role="")) is False
    assert _has_global_scope(User(role=None)) is False


# ---------------------------------------------------------------------------
# Part 2: end-to-end mobile route collateral review
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-v-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"defect_v_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # BYS360_DEFECT_V: Config.SQLALCHEMY_DATABASE_URI is a class attribute
    # frozen the first time config.py is imported anywhere in this pytest
    # process. Flask-SQLAlchemy 3.x lazily binds AND CACHES the per-app
    # Engine on first access, read from app.config at that exact moment.
    # Patching Config's class attributes BEFORE create_app() (not updating
    # flask_app.config afterward) is required for this test's own unique
    # file-backed SQLite DB to actually take effect.
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
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role="personel", ad=None, soyad=None, is_active=True, password=DEFAULT_PASSWORD):
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"DFCTV{suffix:06d}",
            email=f"defect-v-{suffix}@bys360.test",
            ad=ad or "DefectV",
            soyad=soyad or f"User{suffix}",
            role=role,
            is_active=is_active,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _bearer_token(app, user_id):
    from app.api.mobile.shared import _issue_token
    from app.models import User

    with app.app_context():
        user = User.query.get(user_id)
        return _issue_token(user)


def _auth_headers(app, user_id):
    return {"Authorization": f"Bearer {_bearer_token(app, user_id)}"}


def _create_target(app, *, owner_user_id, title, status="ongoing", completion_rate=42):
    from app.extensions import db
    from app.modules.strategic_performance.models import PerformanceTarget

    with app.app_context():
        target = PerformanceTarget(
            target_code=f"DEFECTV-{uuid.uuid4().hex[:10]}",
            target_name=title,
            description=title,
            target_type="personnel",
            category="KPI",
            owner_user_id=owner_user_id,
            weight=0,
            target_value=100,
            current_value=completion_rate,
            completion_rate=completion_rate,
            status=status,
            risk_level="medium",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
            created_by=owner_user_id,
        )
        db.session.add(target)
        db.session.commit()
        return target.id


def _titles(body):
    return [item.get("title") for item in (body.get("items") or [])]


# --- Row-level query representative: GET /api/mobile/kpi/goals -------------


def test_grup_baskani_cannot_see_unrelated_org_wide_kpi_target(app, client):
    other_user_id = _create_user(app, role="personel", ad="DefectV", soyad="OtherOwner")
    leak_title = f"DEFECTV-LEAK-{uuid.uuid4().hex}"
    _create_target(app, owner_user_id=other_user_id, title=leak_title)

    caller_id = _create_user(app, role="grup_baskani", ad="DefectV", soyad="GrupBaskani")
    headers = _auth_headers(app, caller_id)

    resp = client.get(_ROUTE_KPI_GOALS, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    titles = _titles(body)
    assert leak_title not in titles, (
        "grup_baskani must be confined to personal scope on GET /api/mobile/kpi/goals, "
        "not granted organization-wide visibility via the substring overgrant"
    )


def test_grup_baskani_still_sees_own_kpi_target(app, client):
    caller_id = _create_user(app, role="grup_baskani", ad="DefectV", soyad="OwnScope")
    own_title = f"DEFECTV-OWN-{uuid.uuid4().hex}"
    _create_target(app, owner_user_id=caller_id, title=own_title)
    headers = _auth_headers(app, caller_id)

    resp = client.get(_ROUTE_KPI_GOALS, headers=headers)
    assert resp.status_code == 200
    assert own_title in _titles(resp.get_json())


def test_real_global_role_baskan_still_sees_org_wide_kpi_target(app, client):
    other_user_id = _create_user(app, role="personel", ad="DefectV", soyad="OtherOwnerB")
    org_wide_title = f"DEFECTV-GLOBAL-{uuid.uuid4().hex}"
    _create_target(app, owner_user_id=other_user_id, title=org_wide_title)

    global_user_id = _create_user(app, role="baskan", ad="DefectV", soyad="President")
    headers = _auth_headers(app, global_user_id)

    resp = client.get(_ROUTE_KPI_GOALS, headers=headers)
    assert resp.status_code == 200
    assert org_wide_title in _titles(resp.get_json()), (
        "a real global role (baskan) must keep its unscoped visibility unchanged by this fix"
    )


# --- Count/aggregate + performance-adjacent representative: dashboard ------


def test_grup_baskani_gets_scoped_dashboard_counts_not_org_wide(app, client):
    _create_user(app, role="personel", ad="DefectV", soyad="OrgFillerA", is_active=True)
    _create_user(app, role="personel", ad="DefectV", soyad="OrgFillerB", is_active=True)
    caller_id = _create_user(app, role="grup_baskani", ad="DefectV", soyad="DashboardCaller")

    headers = _auth_headers(app, caller_id)
    resp = client.get(_ROUTE_DASHBOARD_SUMMARY, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["active_personnel"] == 1, (
        "grup_baskani must see the non-global 'self only' active_personnel count (1), "
        f"not the organization-wide total; got {body['active_personnel']!r}"
    )
    assert body["pending_approvals"] == 0, (
        "grup_baskani must not receive the organization-wide pending performance "
        f"approvals count; got {body['pending_approvals']!r}"
    )


def test_real_global_role_baskan_yardimcisi_gets_org_wide_dashboard_counts(app, client):
    _create_user(app, role="personel", ad="DefectV", soyad="OrgFillerC", is_active=True)
    _create_user(app, role="personel", ad="DefectV", soyad="OrgFillerD", is_active=True)
    global_user_id = _create_user(app, role="baskan_yardimcisi", ad="DefectV", soyad="VicePresident")

    headers = _auth_headers(app, global_user_id)
    resp = client.get(_ROUTE_DASHBOARD_SUMMARY, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["active_personnel"] >= 3, (
        "a real global role (baskan_yardimcisi) must keep its unscoped, organization-wide "
        f"active_personnel count unchanged by this fix; got {body['active_personnel']!r}"
    )


# ---------------------------------------------------------------------------
# Sanity: unauthenticated calls stay rejected (this fix touches only the
# scope-decision logic, not authentication).
# ---------------------------------------------------------------------------


def test_unauthenticated_requests_to_both_routes_are_rejected_with_401(app, client):
    for path in (_ROUTE_KPI_GOALS, _ROUTE_DASHBOARD_SUMMARY):
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} must reject an unauthenticated request with 401"
