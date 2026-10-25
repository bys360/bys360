"""BYS360_DEFECT_S_REMEDIATION_HEALTH_REPORT_EMPTY_SCOPE_FAIL_CLOSED_CONTRACT

Permanent regression contract for DEFECT S (app/services/performance/
health_report.py::build_performance_task_health_report). Asserts the FIXED
behavior only -- it does not characterize, freeze, or otherwise exercise
the prior buggy shape.

Prior defect (fixed by this same change), confirmed by disposable
reproduction before implementing: the function collapsed None input and
an explicitly empty `scope_user_ids` into the same "unscoped" User query
(`scope_user_ids = {int(v) for v in (scope_user_ids or []) if v}` then
`if scoped:`), so an explicit empty scope returned the full active-user
roster and every employee-identity-bearing row (assignments, evaluations,
duplicate/mismatch/orphan rows, manager-pressure rows, hierarchy health
rows) byte-identical to an unrestricted call.

A SECOND, independent collapse existed one layer down
(`if scoped_user_ids:` gating the evaluation/assignment queries): even
when a real, non-empty input scope resolved to zero actually-matched
users (e.g. a nonexistent id), the resulting `scoped_user_ids` was empty
and the evaluation/assignment query filters were skipped entirely --
leaking every assignment/evaluation row for the period even though the
correctly-computed `employee_count` was 0. The fix addresses both layers:
it distinguishes "scope not provided" (`None`, unrestricted) from "scope
provided" (fails closed to `employee_id == -1` -- the same zero-rows
sentinel this codebase's already-fixed Defect R sibling
(`app/services/performance/task_management_service.py::
_apply_assignment_scope`) uses -- whenever the resolved, provided scope
turns up zero real matches, whether the caller's original input was
`set()` or simply matched no one).

Fixture pattern: service-boundary style (real Flask app_context/
test_request_context + real ORM + real SQLite DB, no mocking of any
function under test), matching this repository's existing precedent for
this same file's sibling module
(tests/behavior/test_task_management_dashboard_reporting_contract.py).
Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_defect_s_health) so it shares no state with any
other wave/agent/test file running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_s_health")

DEFAULT_PASSWORD = "DefectSHealthReportTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "defect-s-health-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-s-health-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"defect_s_health_{uuid.uuid4().hex}.sqlite3")
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
        SERVER_NAME="defect-s-health.test",
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


def _create_user(app, *, ad="Zeynep", soyad=None):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"DSHR{n:06d}",
            email=f"defect-s-health-{n}@bys360.test",
            ad=ad,
            soyad=soyad or f"HealthReport{n}",
            role="personel",
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
            title=f"DefectS Health Period {n}",
            name=f"DefectS Health Period {n}",
            period_type="yillik",
            start_date=_dt.date(2026, 1, 1),
            end_date=_dt.date(2026, 12, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _get_period(app, period_id):
    from app.models import PerformancePeriod

    with app.app_context():
        return PerformancePeriod.query.get(period_id)


def _create_assignment(app, *, period_id, employee_id, evaluator_id, manager_level=1, status="bekliyor"):
    from app.extensions import db
    from app.models import EvaluationAssignment

    with app.app_context():
        row = EvaluationAssignment(
            period_id=period_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            manager_level=manager_level,
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_evaluation(app, *, period_id, employee_id):
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        row = PerformanceEvaluation(period_id=period_id, employee_id=employee_id)
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_coverage_log(app, *, period_id, employee_id, event_type="uncovered", severity="warning"):
    from app.extensions import db
    from app.models import AssignmentCoverageLog

    with app.app_context():
        row = AssignmentCoverageLog(
            period_id=period_id,
            employee_id=employee_id,
            manager_level=1,
            event_scope="generation",
            event_type=event_type,
            severity=severity,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# 1-4. None / matching / mismatching / empty-set scope
# ---------------------------------------------------------------------------


def test_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance.health_report import build_performance_task_health_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_evaluation(app, period_id=period_id, employee_id=employee_id)

    with app.test_request_context():
        report = build_performance_task_health_report(_get_period(app, period_id), None)

    assert report["summary"]["employee_count"] == 2
    assert report["summary"]["assignment_count"] == 1
    assert report["summary"]["evaluation_count"] == 1


def test_matching_nonempty_scope_sees_only_matching_employee(app):
    from app.services.performance.health_report import build_performance_task_health_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    other_employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_assignment(app, period_id=period_id, employee_id=other_employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        report = build_performance_task_health_report(_get_period(app, period_id), {employee_id})

    assert report["summary"]["employee_count"] == 1
    assert report["summary"]["assignment_count"] == 1
    assert [row.employee_id for row in report["assignments"]] == [employee_id]


def test_mismatching_nonexistent_scope_returns_zero_rows_second_layer(app):
    """Proves the SECOND-layer fix: a real, non-empty input scope that
    resolves to zero actually-matched users must still fail closed on the
    assignment/evaluation queries, not silently skip the filter."""
    from app.services.performance.health_report import build_performance_task_health_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_evaluation(app, period_id=period_id, employee_id=employee_id)

    with app.test_request_context():
        report = build_performance_task_health_report(_get_period(app, period_id), {999999})

    assert report["summary"]["employee_count"] == 0
    assert report["summary"]["assignment_count"] == 0, "a non-empty scope matching zero real users must not leak unfiltered assignment rows"
    assert report["summary"]["evaluation_count"] == 0
    assert report["assignments"] == []
    assert report["evaluations"] == []


def test_empty_set_scope_returns_zero_rows(app):
    from app.services.performance.health_report import build_performance_task_health_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_evaluation(app, period_id=period_id, employee_id=employee_id)

    with app.test_request_context():
        report = build_performance_task_health_report(_get_period(app, period_id), set())

    assert report["summary"]["employee_count"] == 0, "an explicitly empty authorization scope must never fall back to the global/unrestricted roster"
    assert report["summary"]["assignment_count"] == 0
    assert report["assignments"] == []


# ---------------------------------------------------------------------------
# 5-7. empty-scope aggregate zero + no identity leak
# ---------------------------------------------------------------------------


def test_empty_set_scope_all_employee_scoped_counts_zero(app):
    from app.services.performance.health_report import build_performance_task_health_report

    evaluator_id = _create_user(app)
    employee_a = _create_user(app)
    employee_b = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_a, evaluator_id=evaluator_id, manager_level=1)
    _create_assignment(app, period_id=period_id, employee_id=employee_a, evaluator_id=evaluator_id, manager_level=2)
    _create_evaluation(app, period_id=period_id, employee_id=employee_a)
    _create_evaluation(app, period_id=period_id, employee_id=employee_b)

    with app.test_request_context():
        report = build_performance_task_health_report(_get_period(app, period_id), set())

    assert report["summary"] == {
        "employee_count": 0, "evaluation_count": 0, "assignment_count": 0,
        "duplicate_level_count": 0, "mismatch_count": 0,
        "orphan_evaluation_count": 0, "orphan_assignment_count": 0,
        "delegated_count": 0, "uncovered_count": 0, "overdue_count": 0,
        "chain_issue_count": 0, "chain_conflict_count": 0, "balanced_chain_count": 0,
    }
    assert report["duplicate_rows"] == []
    assert report["mismatch_rows"] == []
    assert report["orphan_evaluations"] == []
    assert report["orphan_assignments"] == []
    assert report["manager_pressure_rows"] == []
    assert report["health_rows"] == []


def test_empty_set_scope_leaks_no_employee_name_or_unit(app):
    from app.services.performance.health_report import build_performance_task_health_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app, ad="Aylin", soyad="Kaya")
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        report = build_performance_task_health_report(_get_period(app, period_id), set())

    serialized = repr(report["assignments"]) + repr(report["duplicate_rows"]) + repr(report["manager_pressure_rows"])
    assert "Aylin" not in serialized
    assert "Kaya" not in serialized


# ---------------------------------------------------------------------------
# 8. generation-log employee scoping
# ---------------------------------------------------------------------------


def test_empty_set_scope_generation_logs_are_empty(app):
    from app.services.performance.health_report import build_performance_task_health_report

    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")

    with app.test_request_context():
        report_none = build_performance_task_health_report(_get_period(app, period_id), None)
        report_empty = build_performance_task_health_report(_get_period(app, period_id), set())

    assert report_none["coverage_log_rows"] != []
    assert report_empty["coverage_log_rows"] == [], "generation-log rows must obey the explicit empty scope, not fall back to the unrestricted log set"
    assert report_empty["coverage_summary"]["uncovered"] == 0


# ---------------------------------------------------------------------------
# 9. matching-scope legitimate calculations preserved
# ---------------------------------------------------------------------------


def test_matching_scope_preserves_duplicate_row_detection(app):
    from app.services.performance.health_report import build_performance_task_health_report

    evaluator_id = _create_user(app)
    second_evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, manager_level=1)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=second_evaluator_id, manager_level=1)

    with app.test_request_context():
        report = build_performance_task_health_report(_get_period(app, period_id), {employee_id})

    assert report["summary"]["duplicate_level_count"] == 1
    assert len(report["duplicate_rows"]) == 1
    assert report["duplicate_rows"][0]["employee_name"] != "-"
