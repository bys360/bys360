"""BYS360_DEFECT_U_REMEDIATION_REPORTING_WORKSPACE_EMPTY_SCOPE_FAIL_CLOSED_CONTRACT

Permanent regression contract for DEFECT U
(app/services/performance_v2/reporting_workspace.py::
build_period_scorecard_context, build_publish_workspace_context, and
their shared _coerce_employee_ids / _load_period_evaluations helpers).
Asserts the FIXED behavior only -- it does not characterize, freeze, or
otherwise exercise the prior buggy shape.

Prior defect (fixed by this same change), confirmed by disposable
reproduction before implementing: `_coerce_employee_ids` always returned
a plain `list[int]` (`[]` for both `None` and an explicit empty scope),
and `_load_period_evaluations` gated its query filter with a bare
`if employee_ids:` and no fail-closed else branch. An explicitly empty
`allowed_employee_ids` therefore returned every `PerformanceEvaluation`
row for the period -- including employee names, sicil numbers, unit
names, and actual performance scores (`final_total`) -- byte-identical to
`allowed_employee_ids=None`.

A second, distinct finding from triage: `build_period_scorecard_context`
has a per-row compensating visibility check
(`get_evaluation_visibility_state`), but it does NOT protect an
admin-role viewer -- `phase3_general_roles` in
`app/services/performance/visibility_guard.py` grants unconditional
`in_scope=True` for admin/baskan/baskan_yardimcisi, exactly the role
class `@admin_required` permits onto `/performance/operations-center`.
This file's fix does not touch `visibility_guard.py` at all (per the
coordinator's explicit boundary) -- once `_load_period_evaluations` fails
closed at the query layer, the per-row visibility check is no longer
load-bearing for this defect: an empty scope now returns zero
evaluations before the visibility check ever runs. `build_publish_
workspace_context` has no compensating check of any kind, so its own
fix at the query layer is the only protection for that function.

The fix distinguishes `allowed_employee_ids is None` (unrestricted --
`_coerce_employee_ids` now returns `None`, not `[]`) from "provided"
(fails closed to `employee_id == -1` -- the same zero-rows sentinel this
codebase's fixed Defect R/S/T siblings already established as canonical
-- whenever the resolved, provided scope is empty, whether because the
caller's original input was `set()`/`[]` or because every id in a
non-empty input failed integer normalization).

Also included: end-to-end proof through
`app/services/performance/ops_center.py::build_performance_operations_
snapshot` (the already-committed Defect T fix, NOT modified here) that
Operations Center now correctly forwards scope all the way through to
these two functions with no re-collapse at either boundary.

Fixture pattern: service-boundary style (real Flask app_context/
test_request_context + real ORM + real SQLite DB, no mocking of any
function under test, no mocking of get_evaluation_visibility_state or
any other visibility/authorization helper), matching this codebase's
established Wave 6/7 and Defect R/S/T precedent. Uses its own dedicated
tmp DB directory (C:\\bys360_pytest_tmp_defect_u_reporting_workspace) so
it shares no state with any other wave/agent/test file running
concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_u_reporting_workspace")

DEFAULT_PASSWORD = "DefectUReportingWorkspaceTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "defect-u-reporting-workspace-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-u-reporting-workspace-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"defect_u_reporting_workspace_{uuid.uuid4().hex}.sqlite3")
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
        SERVER_NAME="defect-u-reporting-workspace.test",
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


# ---------------------------------------------------------------------------
# Fixture builders (real DB rows)
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, ad="Deniz", soyad=None, role="personel"):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"DURW{n:06d}",
            email=f"defect-u-rw-{n}@bys360.test",
            ad=ad,
            soyad=soyad or f"ReportingWorkspace{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_period(app):
    import datetime as _dt

    from app.extensions import db
    from app.models import PerformancePeriod

    n = _next_suffix()
    with app.app_context():
        period = PerformancePeriod(
            title=f"DefectU RW Period {n}",
            name=f"DefectU RW Period {n}",
            period_type="yillik",
            start_date=_dt.date(2026, 1, 1),
            end_date=_dt.date(2026, 12, 31),
            is_active=True,
            results_published=True,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _get_period(app, period_id):
    from app.models import PerformancePeriod

    with app.app_context():
        return PerformancePeriod.query.get(period_id)


def _create_evaluation(app, *, period_id, employee_id, final_total_100=75.0, status="tamamlandi", is_published_to_employee=True):
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        row = PerformanceEvaluation(
            period_id=period_id,
            employee_id=employee_id,
            status=status,
            final_total_100=final_total_100,
            is_published_to_employee=is_published_to_employee,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# 1-6. build_period_scorecard_context -- None / matching / nonmatching / empty
# ---------------------------------------------------------------------------


def test_scorecard_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance_v2.reporting_workspace import build_period_scorecard_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    employee_b = _create_user(app, ad="Baris", soyad="ScoreB")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)
    _create_evaluation(app, period_id=period_id, employee_id=employee_b, final_total_100=42.0)

    with app.test_request_context():
        result = build_period_scorecard_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=None)

    assert result["count"] == 2
    assert sorted(row["final_total"] for row in result["rows"]) == [42.0, 87.5]


def test_scorecard_matching_scope_returns_only_matching_employee(app):
    from app.services.performance_v2.reporting_workspace import build_period_scorecard_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    employee_b = _create_user(app, ad="Baris", soyad="ScoreB")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)
    _create_evaluation(app, period_id=period_id, employee_id=employee_b, final_total_100=42.0)

    with app.test_request_context():
        result = build_period_scorecard_context(_get_period(app, period_id), viewer=None, allowed_employee_ids={employee_a})

    assert result["count"] == 1
    assert result["rows"][0]["final_total"] == 87.5
    assert result["rows"][0]["display_name"] == "Aylin ScoreA"


def test_scorecard_nonmatching_scope_returns_zero_rows(app):
    from app.services.performance_v2.reporting_workspace import build_period_scorecard_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)

    with app.test_request_context():
        result = build_period_scorecard_context(_get_period(app, period_id), viewer=None, allowed_employee_ids={999999})

    assert result["count"] == 0
    assert result["rows"] == []


def test_scorecard_empty_set_scope_returns_zero_rows(app):
    from app.services.performance_v2.reporting_workspace import build_period_scorecard_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)

    with app.test_request_context():
        result = build_period_scorecard_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=set())

    assert result["count"] == 0, "an explicitly empty authorization scope must never fall back to the global/unrestricted dataset"
    assert result["rows"] == []


def test_scorecard_empty_set_scope_leaks_no_employee_fields(app):
    from app.services.performance_v2.reporting_workspace import build_period_scorecard_context

    employee_a = _create_user(app, ad="Aylin", soyad="GizliIsim")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)

    with app.test_request_context():
        result = build_period_scorecard_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=set())

    serialized = repr(result)
    assert "Aylin" not in serialized
    assert "GizliIsim" not in serialized
    assert "87.5" not in serialized


def test_scorecard_empty_set_scope_aggregate_counts_zero(app):
    from app.services.performance_v2.reporting_workspace import build_period_scorecard_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=95.0, status="tamamlandi")

    with app.test_request_context():
        result = build_period_scorecard_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=set())

    assert result["count"] == 0
    assert result["published_count"] == 0
    assert result["completed_count"] == 0
    assert result["high_count"] == 0
    assert result["avg_score"] == 0.0


# ---------------------------------------------------------------------------
# 7-12. build_publish_workspace_context -- None / matching / nonmatching / empty
# ---------------------------------------------------------------------------


def test_publish_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance_v2.reporting_workspace import build_publish_workspace_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    employee_b = _create_user(app, ad="Baris", soyad="ScoreB")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)
    _create_evaluation(app, period_id=period_id, employee_id=employee_b, final_total_100=42.0)

    with app.test_request_context():
        result = build_publish_workspace_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=None)

    assert result["total_count"] == 2
    assert result["completed_count"] == 2


def test_publish_matching_scope_returns_only_matching_employee(app):
    from app.services.performance_v2.reporting_workspace import build_publish_workspace_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    employee_b = _create_user(app, ad="Baris", soyad="ScoreB")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)
    _create_evaluation(app, period_id=period_id, employee_id=employee_b, final_total_100=42.0)

    with app.test_request_context():
        result = build_publish_workspace_context(_get_period(app, period_id), viewer=None, allowed_employee_ids={employee_a})

    assert result["total_count"] == 1
    assert result["completed_count"] == 1


def test_publish_nonmatching_scope_returns_zero_employee_derived_data(app):
    from app.services.performance_v2.reporting_workspace import build_publish_workspace_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)

    with app.test_request_context():
        result = build_publish_workspace_context(_get_period(app, period_id), viewer=None, allowed_employee_ids={999999})

    assert result["total_count"] == 0
    assert result["completed_count"] == 0


def test_publish_empty_set_scope_returns_zero_rows_and_counts(app):
    from app.services.performance_v2.reporting_workspace import build_publish_workspace_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    period_id = _create_period(app)
    # not publishable-eligible on its own terms (missing required upstream state) -- forces a blocked row
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5, status="bekliyor", is_published_to_employee=False)

    with app.test_request_context():
        result = build_publish_workspace_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=set())

    assert result["total_count"] == 0, "an explicitly empty authorization scope must never fall back to the global/unrestricted dataset"
    assert result["completed_count"] == 0
    assert result["blocked_count"] == 0
    assert result["blocked_rows"] == [], "no unrelated employee's blocked row may surface under an explicitly empty authorization scope"


def test_publish_empty_set_scope_leaks_no_employee_fields(app):
    from app.services.performance_v2.reporting_workspace import build_publish_workspace_context

    employee_a = _create_user(app, ad="Aylin", soyad="GizliIsim")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5, status="bekliyor", is_published_to_employee=False)

    with app.test_request_context():
        result = build_publish_workspace_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=set())

    serialized = repr(result)
    assert "Aylin" not in serialized
    assert "GizliIsim" not in serialized


def test_publish_matching_scope_eligibility_based_only_on_supplied_scope(app):
    from app.services.performance_v2.reporting_workspace import build_publish_workspace_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    other_employee = _create_user(app, ad="Cem", soyad="Disari")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5, status="bekliyor", is_published_to_employee=False)
    _create_evaluation(app, period_id=period_id, employee_id=other_employee, final_total_100=60.0, status="bekliyor", is_published_to_employee=False)

    with app.test_request_context():
        result = build_publish_workspace_context(_get_period(app, period_id), viewer=None, allowed_employee_ids={employee_a})

    assert result["total_count"] == 1
    assert result["blocked_count"] + result["ready_count"] == 1
    assert all(row["display_name"] != "Cem Disari" for row in result["blocked_rows"])


# ---------------------------------------------------------------------------
# Second-layer: non-empty input that normalizes to zero valid ids
# ---------------------------------------------------------------------------


def test_scorecard_nonempty_input_normalizing_to_empty_fails_closed(app):
    """A non-empty caller-supplied scope containing only unparsable values
    must still fail closed (zero rows), not fall back to unrestricted --
    the None-vs-provided distinction is governed by the original input,
    not by whether normalization happened to produce a non-empty list."""
    from app.services.performance_v2.reporting_workspace import build_period_scorecard_context

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)

    with app.test_request_context():
        result = build_period_scorecard_context(_get_period(app, period_id), viewer=None, allowed_employee_ids=["not-a-real-id", None])

    assert result["count"] == 0
    assert result["rows"] == []


# ---------------------------------------------------------------------------
# Ops Center end-to-end (T's committed fix, not modified here)
# ---------------------------------------------------------------------------


def test_ops_center_scorecard_and_publish_summary_preserve_scope_end_to_end(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    employee_b = _create_user(app, ad="Baris", soyad="ScoreB")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5)
    _create_evaluation(app, period_id=period_id, employee_id=employee_b, final_total_100=42.0)

    with app.test_request_context("/performance/operations-center"):
        snapshot_none = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=None)
        snapshot_match = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids={employee_a})
        snapshot_nonmatch = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids={999999})
        snapshot_empty = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())

    assert snapshot_none["scorecard"]["count"] == 2
    assert snapshot_none["publish_summary"]["total_count"] == 2

    assert snapshot_match["scorecard"]["count"] == 1
    assert snapshot_match["publish_summary"]["total_count"] == 1

    assert snapshot_nonmatch["scorecard"]["count"] == 0
    assert snapshot_nonmatch["publish_summary"]["total_count"] == 0

    assert snapshot_empty["scorecard"]["count"] == 0, "Operations Center must not re-collapse an explicit empty scope into unrestricted scorecard data"
    assert snapshot_empty["publish_summary"]["total_count"] == 0, "Operations Center must not re-collapse an explicit empty scope into unrestricted publish-summary data"
    assert snapshot_empty["scorecard"]["count"] != snapshot_none["scorecard"]["count"]


def test_ops_center_empty_scope_readiness_inputs_exclude_unrelated_blockers(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    employee_a = _create_user(app, ad="Aylin", soyad="ScoreA")
    period_id = _create_period(app)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a, final_total_100=87.5, status="bekliyor", is_published_to_employee=False)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())

    assert snapshot["publish_summary"]["blocked_rows"] == []
    assert not any("Aylin" in str(row) for row in snapshot["publish_preflight"].get("blockers") or [])
