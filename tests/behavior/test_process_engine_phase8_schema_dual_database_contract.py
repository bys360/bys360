"""BYS360_DEFECT_AI_PHASE8_SCHEMA_DUAL_DATABASE_CONTRACT

Regression contract for Defect AI: app/services/performance/
process_engine_phase8_tracking.py's ``apply_phase8_schema()`` runtime
schema-repair helper called ``_add_column()``, which issued raw
``ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {type}`` --
PostgreSQL-only syntax, despite this same file's own dual PostgreSQL/SQLite
support contract (``table_exists``/``_table_columns``/``column_exists``
dialect-branching helpers already present for exactly this reason).

Mechanical SQLite reproduction (real, disposable, in-memory sqlite3 --
performed once during triage, not part of this permanent suite):

    >>> import sqlite3
    >>> conn = sqlite3.connect(":memory:")
    >>> conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    >>> conn.execute("ALTER TABLE t ADD COLUMN IF NOT EXISTS foo VARCHAR(80)")
    sqlite3.OperationalError: near "EXISTS": syntax error

This fails UNCONDITIONALLY on SQLite -- not merely "when the column already
exists" -- so every one of ``apply_phase8_schema()``'s 11 ``_add_column``
calls (9 on performance_process_flows, 2 on performance_process_flow_steps)
made the whole function completely unusable under a SQLite-backed app.
CLASSIFICATION: CONFIRMED DEFECT (not NOT_A_DEFECT).

Fix: ``_add_column`` now calls this same module's own dialect-neutral
``column_exists()`` first and only issues a plain ``ALTER TABLE ... ADD
COLUMN`` (portable to both dialects -- SQLite has supported this exact
subset since long before any version this project targets) when the column
is actually absent -- preserving idempotency without depending on
PostgreSQL-only ``IF NOT EXISTS``. Column types/defaults/nullability strings
themselves are byte-for-byte unchanged; only the existence-check mechanism
changed. No other Phase8 schema behavior was touched.

A one-time real, disposable local PostgreSQL 15 database verification
(created, exercised -- including a full second idempotent pass -- and
dropped in the same session, matching the established convention already
used for Defects AB/AC/AD in this same phase; this repo's permanent suite
does not require a live PostgreSQL server) confirmed the identical guarded
ALTER pattern adds every column on the first pass and is a clean no-op on
the second, both against real PostgreSQL syntax/semantics.

This file is the SQLite half of that same two-part verification -- the
concrete regression proof that was previously impossible (calling
apply_phase8_schema() under SQLite could not even complete without raising).

NEW FINDING AJ (reported, NOT fixed here -- out of AI's exact named scope,
"process_engine_phase8_tracking.py" only): while building this test's
fixture, apply_phase8_schema()'s own (pre-existing, unchanged) UPDATE
statement was found to reference several performance_process_flows /
performance_process_flow_steps columns (president_status,
current_owner_user_id, current_stage, last_action_title, process_version,
status, step_code) that the current SQLAlchemy ORM model classes do not
declare at all. Tracing where these actually come from surfaced the SAME
"ADD COLUMN IF NOT EXISTS" defect class, independently reimplemented, at
several more call sites not named in AI's ledger entry:
  - app/services/performance/process_engine_phase3_history.py (status,
    step_code on performance_process_flow_steps)
  - app/services/performance/process_engine_phase4_flow.py (current_stage,
    current_owner_user_id, last_action_title, process_version, and others)
  - app/services/performance/process_engine_phase6_president_approvals.py
  - app/services/performance/process_engine_phase7_president_rule.py
    (raw literal ALTER TABLE ... ADD COLUMN IF NOT EXISTS strings, not even
    routed through a shared _add_column helper)
A repo-wide grep for the same literal pattern also found it in
app/schema_guard_patches.py, app/schema_guard_core_maintenances.py,
app/services/cic/celebration_service.py, app/services/cic/cic_context.py,
and app/api/mobile/services/performance_note_route_services.py -- none of
these were individually triaged for SQLite-compatibility intent in this
pass (schema_guard_*.py in particular were previously documented, in
migration c51c29032d4f's own docstring, as an intentionally PostgreSQL-
production-only legacy self-heal fallback -- that framing was NOT
independently re-verified here and should not be assumed). This test's
fixture works around the phase3/4/6/7 gap by adding the prerequisite
columns directly via plain SQLite DDL (see the `app` fixture below), so it
exercises ONLY the actual AI fix (_add_column / apply_phase8_schema()
itself) under test.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ai")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ai-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ai-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_ai_{uuid.uuid4().hex}.sqlite3")
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

        # apply_phase8_schema()'s own UPDATE statement (pre-existing, NOT
        # touched by the AI fix -- AI is scoped exactly to _add_column's
        # ADD COLUMN IF NOT EXISTS syntax) reads several columns that this
        # repo's current SQLAlchemy ORM model for PerformanceProcessFlow
        # does NOT declare: president_status, current_owner_user_id,
        # current_stage, last_action_title, process_version. In a real
        # deployment these are added earlier in the pipeline by phase4's
        # apply_phase4_schema(), phase6's apply_phase6_schema()-equivalent,
        # and phase7's own runtime schema patch (process_engine_phase4_flow.py
        # / process_engine_phase6_president_approvals.py / process_engine_
        # phase7_president_rule.py) -- each of which, discovered while
        # building THIS test, independently reimplements the exact same
        # PostgreSQL-only "ADD COLUMN IF NOT EXISTS" pattern AI just fixed
        # in process_engine_phase8_tracking.py, at call sites NOT named in
        # AI's ledger entry (which named only process_engine_phase8_
        # tracking.py). Reported separately as finding AJ, NOT fixed here
        # -- exactly the same "discovered while testing, out of this
        # defect's named scope" precedent AB used for AI itself. These
        # columns are added directly here via plain, SQLite-compatible DDL
        # so this test exercises ONLY the actual AI fix (_add_column /
        # apply_phase8_schema()) under test, matching how phase4/6/7 would
        # have already shaped this table by the time phase8 ever runs.
        db.session.execute(db.text("ALTER TABLE performance_process_flows ADD COLUMN president_status VARCHAR(80)"))
        db.session.execute(db.text("ALTER TABLE performance_process_flows ADD COLUMN current_owner_user_id INTEGER"))
        db.session.execute(db.text("ALTER TABLE performance_process_flows ADD COLUMN current_stage VARCHAR(120)"))
        db.session.execute(db.text("ALTER TABLE performance_process_flows ADD COLUMN last_action_title VARCHAR(255)"))
        db.session.execute(db.text("ALTER TABLE performance_process_flows ADD COLUMN process_version VARCHAR(120)"))
        # performance_process_flow_steps.status/step_code: same story, added
        # in real deployments by process_engine_phase3_history.py's own
        # (also-PostgreSQL-only, also part of finding AJ) schema patch.
        db.session.execute(db.text("ALTER TABLE performance_process_flow_steps ADD COLUMN status VARCHAR(80)"))
        db.session.execute(db.text("ALTER TABLE performance_process_flow_steps ADD COLUMN step_code VARCHAR(120)"))
        db.session.commit()
    yield flask_app


_FLOW_COLUMNS = {
    "tracking_status": "VARCHAR(80)",
    "tracking_bucket": "VARCHAR(80)",
    "tracking_priority": "VARCHAR(40) DEFAULT 'normal'",
    "tracking_label": "VARCHAR(255)",
    "tracking_url": "VARCHAR(500)",
    "is_overdue": "BOOLEAN DEFAULT FALSE",
    "overdue_days": "INTEGER DEFAULT 0",
    "last_visible_action": "VARCHAR(255)",
    "tracking_updated_at": "TIMESTAMP",
}
_STEP_COLUMNS = {
    "tracking_visible": "BOOLEAN DEFAULT TRUE",
    "tracking_group": "VARCHAR(80)",
}


def test_apply_phase8_schema_adds_every_missing_column_on_sqlite(app) -> None:
    """1/4: SQLite missing column -> column added; also proves the whole
    function (previously impossible to even call under SQLite) now runs
    to completion and commits."""
    from app.services.performance.process_engine_phase8_tracking import (
        _table_columns,
        apply_phase8_schema,
    )

    with app.app_context():
        before_flow_cols = _table_columns("performance_process_flows")
        before_step_cols = _table_columns("performance_process_flow_steps")
        for col in _FLOW_COLUMNS:
            assert col not in before_flow_cols
        for col in _STEP_COLUMNS:
            assert col not in before_step_cols

        apply_phase8_schema()  # must not raise

        after_flow_cols = _table_columns("performance_process_flows")
        after_step_cols = _table_columns("performance_process_flow_steps")
        for col in _FLOW_COLUMNS:
            assert col in after_flow_cols
        for col in _STEP_COLUMNS:
            assert col in after_step_cols


def test_apply_phase8_schema_is_idempotent_on_sqlite(app) -> None:
    """2/4 + 3/4: SQLite existing column -> no error / no duplicate; second
    invocation -> idempotent. A pre-fix duplicate-column ALTER would raise
    sqlite3.OperationalError: duplicate column name -- this proves the
    guard genuinely prevents that, not merely that no exception happens to
    occur."""
    from app.services.performance.process_engine_phase8_tracking import (
        _table_columns,
        apply_phase8_schema,
    )

    with app.app_context():
        apply_phase8_schema()
        first_flow_cols = _table_columns("performance_process_flows")
        first_step_cols = _table_columns("performance_process_flow_steps")

        apply_phase8_schema()  # must not raise a second time

        second_flow_cols = _table_columns("performance_process_flows")
        second_step_cols = _table_columns("performance_process_flow_steps")
        assert second_flow_cols == first_flow_cols
        assert second_step_cols == first_step_cols


def test_apply_phase8_schema_column_types_match_expected_definitions(app) -> None:
    """6/... : schema resulting columns match expected definitions (SQLite
    PRAGMA table_info reports the declared type/default for each added
    column)."""
    from app.services.performance.process_engine_phase8_tracking import (
        _rows,
        apply_phase8_schema,
    )

    with app.app_context():
        apply_phase8_schema()

        flow_info = {row["name"]: row for row in _rows("PRAGMA table_info(performance_process_flows)")}
        assert flow_info["tracking_status"]["type"] == "VARCHAR(80)"
        assert flow_info["is_overdue"]["type"] == "BOOLEAN"
        assert flow_info["overdue_days"]["type"] == "INTEGER"
        assert flow_info["tracking_priority"]["dflt_value"] == "'normal'"

        step_info = {row["name"]: row for row in _rows("PRAGMA table_info(performance_process_flow_steps)")}
        assert step_info["tracking_group"]["type"] == "VARCHAR(80)"


def test_apply_phase8_schema_preserves_existing_flow_data(app) -> None:
    """7/... : existing Phase8 data preserved -- a real ORM-created flow row
    (with real, non-null pre-existing columns) survives apply_phase8_schema()
    unchanged in its original fields, and gets sensible backfilled tracking
    values from the function's own UPDATE ... COALESCE pass."""
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceProcessFlow
    from app.services.performance.process_engine_phase8_tracking import _rows, apply_phase8_schema

    with app.app_context():
        flow = PerformanceProcessFlow(
            evaluation_id=1,
            period_id=1,
            employee_id=1,
            current_status="takipte",
            is_finalized=False,
        )
        db.session.add(flow)
        db.session.commit()
        flow_id = flow.id

        apply_phase8_schema()

        db.session.expire_all()
        reloaded = db.session.get(PerformanceProcessFlow, flow_id)
        assert reloaded is not None
        assert reloaded.current_status == "takipte"
        assert reloaded.is_finalized is False

        # tracking_status/is_overdue/overdue_days are added at runtime by
        # apply_phase8_schema() itself -- not declared on the ORM model
        # class, so read back via raw SQL rather than an ORM attribute.
        row = _rows(
            "SELECT tracking_status, is_overdue, overdue_days FROM performance_process_flows WHERE id = :id",
            {"id": flow_id},
        )[0]
        assert row["tracking_status"] == "takipte"
        assert row["is_overdue"] in (0, False)
        assert row["overdue_days"] == 0
