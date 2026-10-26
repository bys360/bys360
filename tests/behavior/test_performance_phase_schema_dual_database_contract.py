"""BYS360_DEFECT_AJ_PERFORMANCE_PHASE_SCHEMA_DUAL_DATABASE_CONTRACT

Regression contract for Defect AJ (performance-phase family): the same
PostgreSQL-only ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` defect Defect
AI fixed in app/services/performance/process_engine_phase8_tracking.py's
``_add_column`` was independently reimplemented in four sibling schema-
repair functions:

  - process_engine_phase3_history.py::ensure_phase3_columns()
  - process_engine_phase4_flow.py::apply_phase4_schema() (plus its
    table_exists/column_exists/_table_columns helpers, which were ALSO
    PostgreSQL-only raw information_schema queries with no dialect branch
    at all -- these failed even earlier than the ADD COLUMN statements)
  - process_engine_phase6_president_approvals.py::apply_phase6_schema()
    (identical structure/bug to phase4)
  - process_engine_phase7_president_rule.py::ensure_phase7_schema() (raw
    literal ALTER strings, not routed through a shared _add_column helper)

Mechanical SQLite reproduction (real, disposable, real Flask app + real
SQLite -- performed once during AJ triage, not part of this permanent
suite):

    >>> apply_phase4_schema()
    sqlite3.OperationalError: no such table: information_schema.tables
    >>> ensure_phase7_schema()
    sqlite3.OperationalError: near "EXISTS": syntax error

CLASSIFICATION: AJ_CONFIRMED_DEFECT for all four files.

Fix (same shape as Defect AI, applied consistently): each file's own
existence-check helper (table_exists/column_exists, or a small local
existence-check for phase7, which had none) is now dialect-neutral --
phase4/phase6's raw ``information_schema`` queries were replaced with
SQLAlchemy's ``inspect()`` (dialect-neutral by construction, the same
pattern already proven safe in phase3's own ``_table_exists``/``_columns``
and in Defect AI's fix). Every ``ADD COLUMN IF NOT EXISTS`` was replaced
with an explicit existence check followed by a plain ``ADD COLUMN`` only
when the column is actually missing. ``CREATE INDEX IF NOT EXISTS``
statements (valid, dialect-portable syntax on both databases) were left
untouched everywhere -- they were never part of this defect.

Cross-phase dependency note (discovered while building this test, not a
new defect): these four functions assume a real deployment calls them in
order -- phase3, then phase4, then phase6, then phase7 -- each adding
columns (e.g. phase3 adds performance_process_flow_steps.owner_user_id
and .status; phase4's own CREATE INDEX statements reference them) that a
LATER phase's schema function assumes already exist. This mirrors the
same cross-phase dependency already documented for Defect AI's own test
fixture (tests/behavior/test_process_engine_phase8_schema_dual_database_
contract.py). This file therefore always calls the phase functions in
that same real order, never in isolation.

Shared-helper decision: each file keeps its OWN local existence-check
implementation (not a new shared cross-module utility) -- these four
files (plus phase8) have always maintained independent, self-contained
schema-repair helpers; introducing a new shared module purely for this
fix would be exactly the "broad refactor" this closure explicitly avoids,
and importing phase8's private helpers into earlier-numbered phase files
would be a backwards, confusing dependency direction.

A one-time real, disposable local PostgreSQL 15 database verification
(created, exercised, dropped in the same session, matching the
established convention used throughout this project's AA-AI closure)
confirmed the identical guarded-ALTER pattern still works correctly
against real PostgreSQL, in both the missing-column and idempotent-second-
call cases -- this repo's permanent suite does not require a live
PostgreSQL server.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_aj")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-aj-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-aj-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_aj_{uuid.uuid4().hex}.sqlite3")
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
    return flask_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    with flask_app.app_context():
        from sqlalchemy import event

        from app.extensions import db

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
        db.session.commit()
    yield flask_app


def _run_all_phases_in_real_order() -> None:
    """The real intended call sequence -- see module docstring's
    "Cross-phase dependency note"."""
    from app.services.performance.process_engine_phase3_history import ensure_phase3_columns
    from app.services.performance.process_engine_phase4_flow import apply_phase4_schema
    from app.services.performance.process_engine_phase6_president_approvals import (
        apply_phase6_schema,
    )
    from app.services.performance.process_engine_phase7_president_rule import ensure_phase7_schema

    ensure_phase3_columns()
    apply_phase4_schema()
    apply_phase6_schema()
    ensure_phase7_schema()


def test_all_four_phase_schema_functions_run_to_completion_on_sqlite(app) -> None:
    """1: table present + columns absent -> every phase function completes
    without raising, in the real call order, against a genuinely fresh
    SQLite database."""
    with app.app_context():
        _run_all_phases_in_real_order()  # must not raise


def test_phase_schema_functions_are_idempotent_on_second_invocation(app) -> None:
    """2 + 3: table present + columns already present -> no error/no
    duplicate; second invocation -> idempotent. A pre-fix duplicate-column
    ALTER would raise sqlite3.OperationalError: duplicate column name --
    this proves the guard genuinely prevents that."""
    with app.app_context():
        _run_all_phases_in_real_order()
        _run_all_phases_in_real_order()  # must not raise a second time


def test_phase4_and_phase7_column_definitions_match_expected(app) -> None:
    """6: schema resulting columns match expected definitions -- checked
    against columns not already declared by the current SQLAlchemy ORM
    models (those are created with the model's own type by db.create_all()
    regardless of these legacy DDL strings, which is correct: an existing
    column's type must never be silently overridden by a repair helper)."""
    with app.app_context():
        _run_all_phases_in_real_order()
        from app.services.performance.process_engine_phase4_flow import _rows

        flow_info = {row["name"]: row for row in _rows("PRAGMA table_info(performance_process_flows)")}
        assert flow_info["flow_locked"]["type"] == "BOOLEAN"
        assert flow_info["waiting_days"]["dflt_value"] == "0"
        assert flow_info["phase7_rule_version"]["type"] == "VARCHAR(120)"
        assert flow_info["president_required"]["type"] == "BOOLEAN"


def test_phase3_scoring_history_and_flow_step_columns_added(app) -> None:
    from app.services.performance.process_engine_phase3_history import (
        _columns,
        ensure_phase3_columns,
    )

    with app.app_context():
        ensure_phase3_columns()
        scoring_cols = _columns("performance_scoring_history")
        step_cols = _columns("performance_process_flow_steps")
        for expected in ("evaluation_id", "scorer_user_id", "event_key", "action_at"):
            assert expected in scoring_cols
        for expected in ("step_code", "status", "owner_user_id", "event_key"):
            assert expected in step_cols


def test_phase_schema_functions_preserve_existing_flow_data(app) -> None:
    """7: existing row/data preservation."""
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    with app.app_context():
        flow = PerformanceProcessFlow(evaluation_id=1, period_id=1, employee_id=1, current_status="takipte")
        db.session.add(flow)
        db.session.commit()
        flow_id = flow.id

        _run_all_phases_in_real_order()

        db.session.expire_all()
        reloaded = db.session.get(PerformanceProcessFlow, flow_id)
        assert reloaded is not None
        assert reloaded.current_status == "takipte"


def test_apply_phase4_schema_on_a_table_absent_state_is_a_safe_noop(app) -> None:
    """If the helper legitimately handles table-absent state, also prove
    canonical behavior there: apply_phase4_schema()'s own required_tables
    guard must reject cleanly (RuntimeError), not raise a raw SQL error,
    when the Phase2/3 prerequisite tables genuinely do not exist yet."""
    from app.extensions import db
    from app.services.performance.process_engine_phase4_flow import apply_phase4_schema

    with app.app_context():
        db.session.execute(db.text("DROP TABLE performance_process_flows"))
        db.session.commit()
        with pytest.raises(RuntimeError):
            apply_phase4_schema()
