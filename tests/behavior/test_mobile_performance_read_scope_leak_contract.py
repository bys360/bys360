"""BYS360_SECURITY_REMEDIATION_DEFECT_O_MOBILE_PERFORMANCE_READ_SCOPE_LEAK

Regression contract for a mechanically-confirmed org-wide read leak across
three mobile performance GET routes, all backed by the shared helper
``_v2852_items_from_models`` (defined in
app/api/mobile/performance_routes.py). That helper's inner
``_v2852_query(model)`` runs ``model.query.order_by(...)`` with ZERO filter
of any kind -- before this fix, an ordinary "personel" caller with no
relationship to a record could retrieve it anyway, because each of the three
callers below tried the unscoped helper FIRST and only fell back to a
scoped query (or an empty state) when the unscoped call returned nothing.

Exactly three callers exist anywhere in the codebase (verified via
``grep -rn "_v2852_items_from_models(" app/``):

  O1: app/api/mobile/performance_routes.py ::
      _bys360_legacy_mobile_performance_development_suggestions
      -> GET /api/mobile/performance/development-suggestions
      Its model list resolves, in this schema, to the real
      ``FeedbackActionPlan`` model (the other three names in its list do not
      exist as mapped classes) -- so the pre-fix leak surfaced arbitrary
      ``FeedbackActionPlan.title`` rows to any caller.

  O2: app/api/mobile/services/performance_summary_risk_route_services.py ::
      phase3c_mobile_performance_publish_preapproval_service
      -> GET /api/mobile/performance/publish-preapproval
      Its model list resolves to the real ``PerformancePublishLog`` model
      (the other four names do not exist as mapped classes) -- the pre-fix
      leak surfaced arbitrary ``PerformancePublishLog.note`` rows (via the
      subtitle field) to any caller.

  O3: app/api/mobile/services/performance_compact_route_services.py ::
      phase3c_mobile_performance_in_period_notes_legacy_service
      -> GET /api/mobile/performance/in-period-notes
      Its model list also resolves to ``FeedbackActionPlan`` (last entry;
      the other four names do not exist as mapped classes). Unlike O1, this
      function has NO pre-existing scoped fallback at all -- only a generic
      empty-state placeholder.

Fix (reviewed contract, reused verbatim from the existing canonical
``_has_global_scope`` / ``_snapshot_query_for`` checks used elsewhere in this
same mobile performance domain -- not invented): the unscoped
``_v2852_items_from_models(...)`` call at each of the three call sites is now
gated behind ``_has_global_scope(user)``. Global-scope callers keep their
exact prior (unscoped) behavior. Non-global callers skip the unscoped call
entirely:
  - O1 falls through to its pre-existing ``_snapshot_query_for(user)``-based
    scored-rows fallback (already filtered to the caller's own employee_id).
  - O2 falls through to its pre-existing ``_snapshot_query_for(user)``-based
    fallback the same way.
  - O3 has no scoped alternative for this exact legacy multi-model lookup,
    so non-global callers now see only the pre-existing empty-state
    placeholder. The separate, already-correctly-scoped
    GET /performance/in-period-notes/v2 route remains fully functional and
    unaffected.

Fixture pattern: proven per this remediation wave's mandatory rule -- copied
from tests/behavior/test_admin_ops_user_actions_destructive_operations_
contract.py's ``_make_app`` (Config class attributes monkeypatched BEFORE
create_app(), StaticPool + pysqlite isolation_level=None + explicit BEGIN
event listener) and the mobile bearer-token helper shape from
tests/behavior/test_mobile_performance_note_creation_authorization_contract.py
(real app.api.mobile.shared._issue_token(user), no hand-rolled tokens). Uses
its own dedicated tmp DB directory (C:\\bys360_pytest_tmp_secfix_o) so it
shares no state with any other wave/agent running concurrently.
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

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_secfix_o")

DEFAULT_PASSWORD = "SecFixOContractTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "secfix-o-first-login-test-pw"

_user_counter = 0

_ROUTE_1_DEV_SUGGESTIONS = "/api/mobile/performance/development-suggestions"
_ROUTE_2_PUBLISH_PREAPPROVAL = "/api/mobile/performance/publish-preapproval"
_ROUTE_3_IN_PERIOD_NOTES_LEGACY = "/api/mobile/performance/in-period-notes"


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-secfix-o-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"secfix_o_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # BYS360_SECFIX_O: Config.SQLALCHEMY_DATABASE_URI is a class attribute
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
            sicil_no=f"SECO{suffix:06d}",
            email=f"secfix-o-{suffix}@bys360.test",
            ad=ad or "SecFixO",
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


def _create_period(app, *, name=None, is_active=True):
    from app.extensions import db
    from app.models import PerformancePeriod

    label = name or f"SecFixO Period {uuid.uuid4().hex[:8]}"
    with app.app_context():
        period = PerformancePeriod(
            title=label,
            name=label,
            period_type="monthly",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            is_active=is_active,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _create_snapshot(app, *, period_id, employee_id, final_total_100=55):
    from app.extensions import db
    from app.models import PerformanceResultSnapshot

    with app.app_context():
        snapshot = PerformanceResultSnapshot(
            period_id=period_id,
            employee_id=employee_id,
            employee_name_snapshot=f"Snapshot Employee {employee_id}",
            sicil_no_snapshot=f"SNAP{employee_id:06d}",
            final_total_100=final_total_100,
            published_at=datetime.datetime.utcnow(),
        )
        db.session.add(snapshot)
        db.session.commit()
        return snapshot.id


def _create_feedback_action_plan(app, *, title, status="open"):
    from app.extensions import db
    from app.models import FeedbackActionPlan

    with app.app_context():
        plan = FeedbackActionPlan(title=title, status=status)
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _create_publish_log(app, *, period_id, actor_user_id, note, employee_id=None, action_type="publish"):
    from app.extensions import db
    from app.models import PerformancePublishLog

    with app.app_context():
        row = PerformancePublishLog(
            period_id=period_id,
            actor_user_id=actor_user_id,
            employee_id=employee_id,
            action_type=action_type,
            note=note,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _items_text_blob(body) -> str:
    """Flattens every string value across every response item for a simple
    'does this leaked marker appear anywhere' substring check."""
    items = (body or {}).get("items") or []
    parts = []
    for item in items:
        for value in item.values():
            parts.append(str(value))
    return " || ".join(parts)


# ---------------------------------------------------------------------------
# O1 -- GET /api/mobile/performance/development-suggestions
# ---------------------------------------------------------------------------


def test_o1_route1_development_suggestions_non_global_user_cannot_see_unrelated_org_wide_record(app, client):
    other_user_id = _create_user(app, role="personel")
    _ = other_user_id
    leak_marker = f"LEAK-O1-FEEDBACK-ACTION-PLAN-{uuid.uuid4().hex}"
    _create_feedback_action_plan(app, title=leak_marker)

    caller_id = _create_user(app, role="personel", ad="RouteOne", soyad="Caller")
    headers = _auth_headers(app, caller_id)

    resp = client.get(_ROUTE_1_DEV_SUGGESTIONS, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker not in blob, "non-global caller must not see the unrelated org-wide FeedbackActionPlan record"


def test_o1_route1_development_suggestions_non_global_user_still_sees_own_scoped_snapshot(app, client):
    leak_marker = f"LEAK-O1B-FEEDBACK-ACTION-PLAN-{uuid.uuid4().hex}"
    _create_feedback_action_plan(app, title=leak_marker)

    caller_id = _create_user(app, role="personel", ad="RouteOneOwn", soyad="Caller")
    period_id = _create_period(app)
    # Score must be in (0, 70) to surface via the scoped fallback's
    # "0 < score < 70" filter (read directly from
    # _bys360_legacy_mobile_performance_development_suggestions).
    _create_snapshot(app, period_id=period_id, employee_id=caller_id, final_total_100=55)
    headers = _auth_headers(app, caller_id)

    resp = client.get(_ROUTE_1_DEV_SUGGESTIONS, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker not in blob
    assert "RouteOneOwn" in blob, "caller's own low-score snapshot must still surface via the scoped fallback"


def test_o1_route1_development_suggestions_global_scope_still_sees_org_wide_record(app, client):
    leak_marker = f"LEAK-O1C-FEEDBACK-ACTION-PLAN-{uuid.uuid4().hex}"
    _create_feedback_action_plan(app, title=leak_marker)

    # "admin" is a member of _GLOBAL_ROLES in app/api/mobile/shared.py.
    global_user_id = _create_user(app, role="admin")
    headers = _auth_headers(app, global_user_id)

    resp = client.get(_ROUTE_1_DEV_SUGGESTIONS, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker in blob, "global-scope caller's unscoped visibility must remain exactly as before the fix"


# ---------------------------------------------------------------------------
# O2 -- GET /api/mobile/performance/publish-preapproval
# ---------------------------------------------------------------------------


def test_o2_route2_publish_preapproval_non_global_user_cannot_see_unrelated_org_wide_record(app, client):
    other_user_id = _create_user(app, role="personel")
    period_id = _create_period(app)
    leak_marker = f"LEAK-O2-PUBLISH-LOG-NOTE-{uuid.uuid4().hex}"
    _create_publish_log(app, period_id=period_id, actor_user_id=other_user_id, employee_id=other_user_id, note=leak_marker)

    caller_id = _create_user(app, role="personel", ad="RouteTwo", soyad="Caller")
    headers = _auth_headers(app, caller_id)

    resp = client.get(_ROUTE_2_PUBLISH_PREAPPROVAL, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker not in blob, "non-global caller must not see the unrelated org-wide PerformancePublishLog note"


def test_o2_route2_publish_preapproval_non_global_user_still_sees_own_scoped_snapshot(app, client):
    other_user_id = _create_user(app, role="personel")
    period_id = _create_period(app)
    leak_marker = f"LEAK-O2B-PUBLISH-LOG-NOTE-{uuid.uuid4().hex}"
    _create_publish_log(app, period_id=period_id, actor_user_id=other_user_id, employee_id=other_user_id, note=leak_marker)

    caller_id = _create_user(app, role="personel", ad="RouteTwoOwn", soyad="Caller")
    # Route 2's scoped fallback (_snapshot_query_for) has no score filter --
    # any snapshot belonging to the caller surfaces.
    _create_snapshot(app, period_id=period_id, employee_id=caller_id, final_total_100=90)
    headers = _auth_headers(app, caller_id)

    resp = client.get(_ROUTE_2_PUBLISH_PREAPPROVAL, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker not in blob
    assert "RouteTwoOwn" in blob, "caller's own scoped snapshot must still surface via the fallback"


def test_o2_route2_publish_preapproval_global_scope_still_sees_org_wide_record(app, client):
    other_user_id = _create_user(app, role="personel")
    period_id = _create_period(app)
    leak_marker = f"LEAK-O2C-PUBLISH-LOG-NOTE-{uuid.uuid4().hex}"
    _create_publish_log(app, period_id=period_id, actor_user_id=other_user_id, employee_id=other_user_id, note=leak_marker)

    global_user_id = _create_user(app, role="admin")
    headers = _auth_headers(app, global_user_id)

    resp = client.get(_ROUTE_2_PUBLISH_PREAPPROVAL, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker in blob, "global-scope caller's unscoped visibility must remain exactly as before the fix"


# ---------------------------------------------------------------------------
# O3 -- GET /api/mobile/performance/in-period-notes (legacy)
# ---------------------------------------------------------------------------


def test_o3_route3_in_period_notes_legacy_non_global_user_cannot_see_unrelated_org_wide_record(app, client):
    leak_marker = f"LEAK-O3-FEEDBACK-ACTION-PLAN-{uuid.uuid4().hex}"
    _create_feedback_action_plan(app, title=leak_marker)

    caller_id = _create_user(app, role="personel", ad="RouteThree", soyad="Caller")
    headers = _auth_headers(app, caller_id)

    resp = client.get(_ROUTE_3_IN_PERIOD_NOTES_LEGACY, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker not in blob, "non-global caller must not see the unrelated org-wide FeedbackActionPlan record"

    # This legacy route has no scoped alternative for this exact multi-model
    # lookup, so a non-global caller with no matching real data correctly
    # falls through to the pre-existing empty-state placeholder rather than
    # any fabricated scoped result.
    items = body.get("items") or []
    assert len(items) == 1
    assert items[0].get("id") == "note-empty"


def test_o3_route3_in_period_notes_legacy_global_scope_still_sees_org_wide_record(app, client):
    leak_marker = f"LEAK-O3B-FEEDBACK-ACTION-PLAN-{uuid.uuid4().hex}"
    _create_feedback_action_plan(app, title=leak_marker)

    global_user_id = _create_user(app, role="admin")
    headers = _auth_headers(app, global_user_id)

    resp = client.get(_ROUTE_3_IN_PERIOD_NOTES_LEGACY, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    blob = _items_text_blob(body)
    assert leak_marker in blob, "global-scope caller's unscoped visibility must remain exactly as before the fix"


# ---------------------------------------------------------------------------
# Sanity: unauthenticated calls to all three routes still 401 (pre-existing
# require_mobile_user behavior must stay intact; this fix touches only the
# authorization-scoped data path, not authentication).
# ---------------------------------------------------------------------------


def test_unauthenticated_requests_to_all_three_routes_are_rejected_with_401(app, client):
    for path in (_ROUTE_1_DEV_SUGGESTIONS, _ROUTE_2_PUBLISH_PREAPPROVAL, _ROUTE_3_IN_PERIOD_NOTES_LEGACY):
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} must reject an unauthenticated request with 401"
