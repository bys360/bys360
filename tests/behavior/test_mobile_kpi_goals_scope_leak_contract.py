"""BYS360_SECURITY_REMEDIATION_DEFECT_P_MOBILE_KPI_GOALS_SCOPE_LEAK

Regression contract for a mechanically-confirmed org-wide read leak in
GET /api/mobile/kpi/goals (app/api/mobile/utility_routes.py::mobile_kpi_goals).

DEFECT P (fixed): the route ran ``PerformanceTarget.query.order_by(...)``
with zero caller filter, for both the returned row list AND the "Aktif
Hedef" active-count metric derived from the same query -- any authenticated
"personel" caller could read every ``PerformanceTarget`` row in the
organization (including unrelated employees' KPI/goal cards) and the total
active-target count leaked organization-wide alongside them.

The sibling route in the same domain (GET /api/mobile/kpi/target-management,
app/api/mobile/domains/kpi_target_management.py::
_bys360_legacy_mobile_kpi_target_management_v2853) already correctly scoped
its query on the identical model:
    if not _has_global_scope(user) and hasattr(Target, 'owner_user_id'):
        q = q.filter(Target.owner_user_id == user.id)

Fix (reviewed contract, reused verbatim from that existing canonical policy
-- not invented): the exact same guard is now applied in mobile_kpi_goals,
before both the row list and the active-count metric are derived from the
query. Global-scope callers keep their exact prior (unscoped) behavior.

Fixture pattern: proven per this remediation wave's mandatory rule -- copied
from tests/behavior/test_mobile_performance_read_scope_leak_contract.py's
``_make_app`` (Config class attributes monkeypatched BEFORE create_app(),
StaticPool + pysqlite isolation_level=None + explicit BEGIN event listener)
and the mobile bearer-token helper shape used throughout the Defect N/O
regression suites (real app.api.mobile.shared._issue_token(user), no
hand-rolled tokens, no mocking of the authorization check itself). Uses its
own dedicated tmp DB directory (C:\\bys360_pytest_tmp_secfix_p) so it shares
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

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_secfix_p")

DEFAULT_PASSWORD = "SecFixPContractTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "secfix-p-first-login-test-pw"

_user_counter = 0

_ROUTE_GOALS = "/api/mobile/kpi/goals"
_ROUTE_TARGET_MANAGEMENT = "/api/mobile/kpi/target-management"


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-secfix-p-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"secfix_p_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # BYS360_SECFIX_P: Config.SQLALCHEMY_DATABASE_URI is a class attribute
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


def _create_user(app, *, role="personel", ad=None, soyad=None, is_active=True, password=DEFAULT_PASSWORD):
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"SECP{suffix:06d}",
            email=f"secfix-p-{suffix}@bys360.test",
            ad=ad or "SecFixP",
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


def _create_target(app, *, owner_user_id, title, status="ongoing", risk_level="medium", completion_rate=42):
    from app.extensions import db
    from app.modules.strategic_performance.models import PerformanceTarget

    with app.app_context():
        target = PerformanceTarget(
            target_code=f"SECFIXP-{uuid.uuid4().hex[:10]}",
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
            risk_level=risk_level,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
            created_by=owner_user_id,
        )
        db.session.add(target)
        db.session.commit()
        return target.id


def _get_json(client, path, headers):
    resp = client.get(path, headers=headers)
    return resp.status_code, (resp.get_json() or {})


def _titles(body):
    return [item.get("title") for item in (body.get("items") or [])]


def _metric_value(body, title):
    for metric in body.get("metrics") or []:
        if metric.get("title") == title:
            return metric.get("value")
    return None


# ---------------------------------------------------------------------------
# 1: unauthenticated -> 401
# ---------------------------------------------------------------------------


def test_unauthenticated_denied(app, client):
    resp = client.get(_ROUTE_GOALS)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2/3: personnel sees own target, not the unrelated one
# ---------------------------------------------------------------------------


def test_personnel_sees_own_target_and_not_unrelated_target(app, client):
    user_a_id = _create_user(app, role="personel", ad="RouteP", soyad="UserA")
    user_b_id = _create_user(app, role="personel", ad="RouteP", soyad="UserB")
    target_a_title = f"SECFIXP-OWN-{uuid.uuid4().hex}"
    target_b_title = f"SECFIXP-UNRELATED-{uuid.uuid4().hex}"
    _create_target(app, owner_user_id=user_a_id, title=target_a_title)
    _create_target(app, owner_user_id=user_b_id, title=target_b_title)

    headers_a = _auth_headers(app, user_a_id)
    status, body = _get_json(client, _ROUTE_GOALS, headers_a)

    assert status == 200
    titles = _titles(body)
    assert target_a_title in titles, "personnel must still see their own KPI/goal target"
    assert target_b_title not in titles, "personnel must not see an unrelated user's KPI/goal target"


# ---------------------------------------------------------------------------
# 4: personnel active-count metric is scoped, not organization-wide
# ---------------------------------------------------------------------------


def test_personnel_active_count_is_scoped_not_organization_wide(app, client):
    user_a_id = _create_user(app, role="personel", ad="RouteP", soyad="CountA")
    user_b_id = _create_user(app, role="personel", ad="RouteP", soyad="CountB")
    _create_target(app, owner_user_id=user_a_id, title=f"SECFIXP-COUNT-OWN-{uuid.uuid4().hex}", status="ongoing")
    _create_target(app, owner_user_id=user_b_id, title=f"SECFIXP-COUNT-UNRELATED-{uuid.uuid4().hex}", status="ongoing")

    headers_a = _auth_headers(app, user_a_id)
    status, body = _get_json(client, _ROUTE_GOALS, headers_a)

    assert status == 200
    active_metric = _metric_value(body, "Aktif Hedef")
    assert active_metric == "1", (
        "non-global caller's active-target count must reflect only their own "
        f"authorized target(s), not the organization-wide total; got {active_metric!r}"
    )


# ---------------------------------------------------------------------------
# 5/6: global-scope caller sees all targets and an unscoped count
# ---------------------------------------------------------------------------


def test_global_scope_sees_all_targets_and_unscoped_count(app, client):
    user_a_id = _create_user(app, role="personel", ad="RouteP", soyad="GlobalOwnerA")
    user_b_id = _create_user(app, role="personel", ad="RouteP", soyad="GlobalOwnerB")
    target_a_title = f"SECFIXP-GLOBAL-A-{uuid.uuid4().hex}"
    target_b_title = f"SECFIXP-GLOBAL-B-{uuid.uuid4().hex}"
    _create_target(app, owner_user_id=user_a_id, title=target_a_title, status="ongoing")
    _create_target(app, owner_user_id=user_b_id, title=target_b_title, status="ongoing")

    global_user_id = _create_user(app, role="admin")
    headers_g = _auth_headers(app, global_user_id)
    status, body = _get_json(client, _ROUTE_GOALS, headers_g)

    assert status == 200
    titles = _titles(body)
    assert target_a_title in titles
    assert target_b_title in titles, "global-scope caller's unscoped visibility must remain exactly as before the fix"
    assert _metric_value(body, "Aktif Hedef") == "2"


# ---------------------------------------------------------------------------
# 7: empty personal scope fails closed -- no organization-wide fallback
# ---------------------------------------------------------------------------


def test_empty_personal_scope_fails_closed_not_organization_wide_fallback(app, client):
    user_a_id = _create_user(app, role="personel", ad="RouteP", soyad="EmptyScope")
    other_user_id = _create_user(app, role="personel", ad="RouteP", soyad="OtherOwner")
    unrelated_title = f"SECFIXP-EMPTY-UNRELATED-{uuid.uuid4().hex}"
    _create_target(app, owner_user_id=other_user_id, title=unrelated_title, status="ongoing")

    headers_a = _auth_headers(app, user_a_id)
    status, body = _get_json(client, _ROUTE_GOALS, headers_a)

    assert status == 200
    titles = _titles(body)
    assert unrelated_title not in titles, "caller with zero owned targets must not fall back to organization-wide data"
    assert titles == []
    assert _metric_value(body, "Aktif Hedef") == "0"


# ---------------------------------------------------------------------------
# 8: serialization / response contract preserved for an authorized row
# ---------------------------------------------------------------------------


def test_serialization_contract_preserved_for_authorized_row(app, client):
    user_a_id = _create_user(app, role="personel", ad="RouteP", soyad="SerializeA")
    title = f"SECFIXP-SERIALIZE-{uuid.uuid4().hex}"
    target_id = _create_target(
        app, owner_user_id=user_a_id, title=title, status="ongoing", risk_level="high", completion_rate=77,
    )

    headers_a = _auth_headers(app, user_a_id)
    status, body = _get_json(client, _ROUTE_GOALS, headers_a)

    assert status == 200
    items = body.get("items") or []
    assert len(items) == 1
    item = items[0]
    assert item["id"] == str(target_id)
    assert item["title"] == title
    assert item["subtitle"] == title  # description falls back is target_name here
    assert item["status"] == "ongoing"
    assert item["meta"] == "high"
    assert item["value"] == "%77"
    assert item["progress"] == 77
    assert set(item.keys()) == {"id", "title", "subtitle", "status", "meta", "value", "progress"}


# ---------------------------------------------------------------------------
# Control route: /kpi/target-management agrees with /kpi/goals on the caller
# visibility boundary for the same PerformanceTarget records.
# ---------------------------------------------------------------------------


def test_control_route_target_management_agrees_with_goals_route_scope(app, client):
    user_a_id = _create_user(app, role="personel", ad="RouteP", soyad="ControlA")
    user_b_id = _create_user(app, role="personel", ad="RouteP", soyad="ControlB")
    target_a_title = f"SECFIXP-CONTROL-A-{uuid.uuid4().hex}"
    target_b_title = f"SECFIXP-CONTROL-B-{uuid.uuid4().hex}"
    _create_target(app, owner_user_id=user_a_id, title=target_a_title)
    _create_target(app, owner_user_id=user_b_id, title=target_b_title)

    headers_a = _auth_headers(app, user_a_id)

    status_goals, body_goals = _get_json(client, _ROUTE_GOALS, headers_a)
    status_tm, body_tm = _get_json(client, _ROUTE_TARGET_MANAGEMENT, headers_a)

    assert status_goals == 200
    assert status_tm == 200
    titles_goals = set(_titles(body_goals))
    titles_tm = set(_titles(body_tm))

    assert target_a_title in titles_goals and target_a_title in titles_tm
    assert target_b_title not in titles_goals and target_b_title not in titles_tm
