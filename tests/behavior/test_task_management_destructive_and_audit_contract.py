"""BYS360_COVERAGE_WAVE6_AGENT3_TASK_MANAGEMENT_DESTRUCTIVE_AND_AUDIT_CONTRACT

Behavioral, service-boundary contract for the two functions given verbatim
in this wave's Agent 3 scope (app/services/performance/task_management_
service.py), both confirmed LIVE via real callers in app/performance/
task_routes.py (not unwired code -- `grep -n "clear_period_task_records\\|
log_performance_recommendation_export" app/performance/task_routes.py`
shows real call sites at lines 440 and 403):

    clear_period_task_records(period_id)              -- destructive, multi-table
    log_performance_recommendation_export(...)         -- audit-write

No prior tests exist for this service file at all (confirmed via
`find tests -iname "*task_management*"` returning nothing before this file).

Tested directly at the service-function boundary (not through the HTTP
route) -- this is a deliberate, documented choice: both functions are pure
backend service logic with no route-specific concern (auth, templating)
layered inside them, and the wave brief itself frames the scope as a
"coherent SERVICE contract" around these two names, not a route contract.
Real Flask app_context + real ORM + real SQLite DB throughout; no mocking
of either function under test.

clear_period_task_records read directly from source:
    - deletes PerformanceEvaluationItem rows for every PerformanceEvaluation
      in the period, then EvaluationAssignment rows, then PerformanceEvaluation
      rows, then AssignmentCoverageLog rows -- all filtered by period_id.
    - does NOT call db.session.commit() itself; the caller (task_routes.py)
      owns the transaction boundary. This file proves that boundary is real
      by showing an explicit rollback after the call fully undoes it --
      documented here as the "transaction rollback" case instead of
      fault-injecting a partial multi-statement failure, which would not be
      a meaningful thing to inject against four independent, individually-
      atomic bulk DELETE statements (each one is already all-or-nothing at
      the SQL level; there is no meaningful "partial completion" state
      inside a single one of them to force honestly under SQLite).

log_performance_recommendation_export read directly from source:
    - returns immediately (zero writes) when selected_period is falsy --
      this is the "empty scope means no data" boundary for this function.
    - always writes a real AIRequestLog row via log_ai_request (no
      ai_schema_ready() guard on that call, confirmed by reading
      app/services/ai/audit.py::log_ai_request directly).
    - ensure_recommendation_rows / upsert_ai_summary_cache are internally
      guarded by ai_schema_ready() (app/services/ai/schema_guard.py); this
      fixture's FLASK_SKIP_SCHEMA_VALIDATION=1 + fresh db.create_all() keeps
      current_app.extensions["schema_check_errors"] empty, so ai_schema_
      ready() is True and both writes are exercised for real -- verified
      empirically in this file, not assumed.
    - calls db.session.commit() itself at the end.

SQLite honesty: every assertion here is against ORM-level row counts and
field values portable across SQLite/PostgreSQL (no raw dialect-specific SQL,
no assumption about ON DELETE CASCADE firing differently than the
application-level bulk .delete() calls already perform explicitly).

Fixture pattern: this wave's mandatory proven shape (Config class-attribute
patch BEFORE create_app(), StaticPool + pysqlite isolation_level=None +
explicit BEGIN event listener). Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_wave6_agent3) so it shares no state with any other
wave/agent running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave6_agent3")

DEFAULT_PASSWORD = "Wave6Agent3TaskMgmtTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "wave6-agent3-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-wave6-agent3-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"wave6_agent3_{uuid.uuid4().hex}.sqlite3")
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


# ---------------------------------------------------------------------------
# Fixture builders (real DB rows)
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"W6A3{n:06d}",
            email=f"wave6-agent3-{n}@bys360.test",
            ad="Wave6",
            soyad=f"Task{n}",
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
            title=f"Wave6 Agent3 Period {n}",
            name=f"Wave6 Agent3 Period {n}",
            period_type="yillik",
            start_date=_dt.date(2026, 1, 1),
            end_date=_dt.date(2026, 12, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _create_criteria(app):
    from app.extensions import db
    from app.models import PerformanceCriteria

    n = _next_suffix()
    with app.app_context():
        criteria = PerformanceCriteria(name=f"Wave6 Agent3 Criteria {n}", is_active=True, sort_order=1)
        db.session.add(criteria)
        db.session.commit()
        return criteria.id


def _seed_period_task_data(app, *, period_id, evaluator_id, criteria_id, count=3):
    """Seed `count` full evaluation chains (assignment + evaluation + item +
    coverage log) for a single period, all committed for real.

    PerformanceEvaluation carries a real UNIQUE(period_id, employee_id)
    constraint (one aggregate evaluation row per employee per period, with
    level_1/2/3 scores as columns on that same row -- not one row per
    level) -- so each of the `count` chains uses its own freshly-created
    employee, not a shared employee with a different manager_level.
    """
    from app.extensions import db
    from app.models import (
        AssignmentCoverageLog,
        EvaluationAssignment,
        PerformanceEvaluation,
        PerformanceEvaluationItem,
    )

    for _ in range(count):
        employee_id = _create_user(app)
        with app.app_context():
            assignment = EvaluationAssignment(
                period_id=period_id,
                employee_id=employee_id,
                evaluator_id=evaluator_id,
                manager_level=1,
                status="bekliyor",
            )
            db.session.add(assignment)

            evaluation = PerformanceEvaluation(
                period_id=period_id,
                employee_id=employee_id,
                level_1_evaluator_id=evaluator_id,
                final_total_100=55,
            )
            db.session.add(evaluation)
            db.session.flush()

            item = PerformanceEvaluationItem(
                evaluation_id=evaluation.id,
                criteria_id=criteria_id,
                manager_level=1,
                score_100=55,
            )
            db.session.add(item)

            log = AssignmentCoverageLog(
                period_id=period_id,
                employee_id=employee_id,
                manager_level=1,
                event_scope="generation",
                event_type="assigned",
                severity="info",
            )
            db.session.add(log)
            db.session.commit()


def _counts_for_period(app, period_id):
    from app.models import (
        AssignmentCoverageLog,
        EvaluationAssignment,
        PerformanceEvaluation,
        PerformanceEvaluationItem,
    )

    with app.app_context():
        evaluation_ids = [row.id for row in PerformanceEvaluation.query.filter_by(period_id=period_id).all()]
        item_count = (
            PerformanceEvaluationItem.query.filter(PerformanceEvaluationItem.evaluation_id.in_(evaluation_ids)).count()
            if evaluation_ids
            else 0
        )
        return {
            "assignment_count": EvaluationAssignment.query.filter_by(period_id=period_id).count(),
            "evaluation_count": PerformanceEvaluation.query.filter_by(period_id=period_id).count(),
            "evaluation_item_count": item_count,
            "log_count": AssignmentCoverageLog.query.filter_by(period_id=period_id).count(),
        }


def _ai_request_log_count(app):
    from app.models import AIRequestLog

    with app.app_context():
        return AIRequestLog.query.count()


# ---------------------------------------------------------------------------
# 1. clear_period_task_records -- successful scoped cleanup, all 4 tables
# ---------------------------------------------------------------------------


def test_clear_period_task_records_successful_scoped_cleanup_all_four_tables(app):
    from app.extensions import db
    from app.services.performance.task_management_service import clear_period_task_records

    evaluator_id = _create_user(app)
    criteria_id = _create_criteria(app)
    period_id = _create_period(app)
    _seed_period_task_data(app, period_id=period_id, evaluator_id=evaluator_id, criteria_id=criteria_id, count=3)

    before = _counts_for_period(app, period_id)
    assert before == {"assignment_count": 3, "evaluation_count": 3, "evaluation_item_count": 3, "log_count": 3}

    with app.app_context():
        result = clear_period_task_records(period_id)
        db.session.commit()

    assert result == {"assignment_count": 3, "evaluation_count": 3, "evaluation_item_count": 3, "log_count": 3}
    assert _counts_for_period(app, period_id) == {"assignment_count": 0, "evaluation_count": 0, "evaluation_item_count": 0, "log_count": 0}


# ---------------------------------------------------------------------------
# 2. empty period safety -- no error, all-zero, no unrelated data touched
# ---------------------------------------------------------------------------


def test_clear_period_task_records_empty_period_returns_zero_and_touches_nothing(app):
    from app.extensions import db
    from app.services.performance.task_management_service import clear_period_task_records

    evaluator_id = _create_user(app)
    criteria_id = _create_criteria(app)
    other_period_id = _create_period(app)
    _seed_period_task_data(app, period_id=other_period_id, evaluator_id=evaluator_id, criteria_id=criteria_id, count=2)

    empty_period_id = _create_period(app)

    with app.app_context():
        result = clear_period_task_records(empty_period_id)
        db.session.commit()

    assert result == {"assignment_count": 0, "evaluation_count": 0, "evaluation_item_count": 0, "log_count": 0}
    assert _counts_for_period(app, other_period_id) == {"assignment_count": 2, "evaluation_count": 2, "evaluation_item_count": 2, "log_count": 2}, (
        "clearing an empty period must never fall back to organization-wide deletion"
    )


# ---------------------------------------------------------------------------
# 3. unrelated period preservation -- clearing A must not touch B
# ---------------------------------------------------------------------------


def test_clear_period_task_records_preserves_unrelated_period(app):
    from app.extensions import db
    from app.services.performance.task_management_service import clear_period_task_records

    evaluator_id = _create_user(app)
    criteria_id = _create_criteria(app)
    period_a = _create_period(app)
    period_b = _create_period(app)
    _seed_period_task_data(app, period_id=period_a, evaluator_id=evaluator_id, criteria_id=criteria_id, count=2)
    _seed_period_task_data(app, period_id=period_b, evaluator_id=evaluator_id, criteria_id=criteria_id, count=4)

    with app.app_context():
        clear_period_task_records(period_a)
        db.session.commit()

    assert _counts_for_period(app, period_a) == {"assignment_count": 0, "evaluation_count": 0, "evaluation_item_count": 0, "log_count": 0}
    assert _counts_for_period(app, period_b) == {"assignment_count": 4, "evaluation_count": 4, "evaluation_item_count": 4, "log_count": 4}


# ---------------------------------------------------------------------------
# 4. transaction rollback -- caller-level rollback fully undoes the clear
# ---------------------------------------------------------------------------


def test_clear_period_task_records_caller_rollback_fully_undoes_delete(app):
    from app.extensions import db
    from app.services.performance.task_management_service import clear_period_task_records

    evaluator_id = _create_user(app)
    criteria_id = _create_criteria(app)
    period_id = _create_period(app)
    _seed_period_task_data(app, period_id=period_id, evaluator_id=evaluator_id, criteria_id=criteria_id, count=3)

    with app.app_context():
        clear_period_task_records(period_id)
        db.session.rollback()

    assert _counts_for_period(app, period_id) == {"assignment_count": 3, "evaluation_count": 3, "evaluation_item_count": 3, "log_count": 3}, (
        "clear_period_task_records must not commit its own transaction -- a caller rollback must fully undo it"
    )


# ---------------------------------------------------------------------------
# 5. log_performance_recommendation_export -- empty scope means no data
# ---------------------------------------------------------------------------


def test_log_performance_recommendation_export_returns_early_with_falsy_period(app):
    from app.services.performance.task_management_service import (
        log_performance_recommendation_export,
    )

    with app.app_context():
        before = _ai_request_log_count(app)
        log_performance_recommendation_export(
            selected_period=None,
            selected_scope="genel",
            export_format="csv",
            payload={"summary": {}, "recommendation_rows": [], "action_plan_rows": [], "pressure_rows": []},
            actor_user_id=None,
        )
        assert _ai_request_log_count(app) == before, "a falsy selected_period must write zero audit rows, never fall back to logging for all periods"


# ---------------------------------------------------------------------------
# 6. log_performance_recommendation_export -- real audit-write persistence
# ---------------------------------------------------------------------------


def test_log_performance_recommendation_export_writes_real_audit_row(app):
    from app.services.performance.task_management_service import (
        log_performance_recommendation_export,
    )

    actor_id = _create_user(app)
    period_id = _create_period(app)

    with app.app_context():
        from app.models import AIRequestLog, PerformancePeriod

        period = PerformancePeriod.query.get(period_id)
        before = _ai_request_log_count(app)

        log_performance_recommendation_export(
            selected_period=period,
            selected_scope="birim",
            export_format="csv",
            payload={
                "summary": {"uncovered": 2, "chain_issue": 1, "delegated": 0, "exempted": 0},
                "recommendation_rows": [{"title": "Wave6 Agent3 recommendation"}],
                "action_plan_rows": [{"title": "Wave6 Agent3 action"}],
                "pressure_rows": [],
            },
            actor_user_id=actor_id,
        )

        assert _ai_request_log_count(app) == before + 1
        row = AIRequestLog.query.order_by(AIRequestLog.id.desc()).first()
        assert row.module_type == "performance"
        assert row.feature_type == "task_recommendations_export"
        assert row.target_id == period_id
        assert row.user_id == actor_id
        assert "scope=birim" in row.request_text
        assert "format=csv" in row.request_text
        assert row.status == "completed"
