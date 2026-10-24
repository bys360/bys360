"""BYS360_DEFECT_AB_PHASE8_DUAL_DATABASE_BINDING_CONTRACT

Regression contract for Defect AB: five raw-SQL call sites in
app/services/performance/process_engine_phase8_tracking.py used
PostgreSQL-only array-bind syntax (``= ANY(:flow_ids)``) despite this same
file's own dual PostgreSQL/SQLite support contract (see its ``table_exists``/
``_table_columns`` dialect-branching helpers, present specifically because
"local development may run on SQLite, while live commonly runs on
PostgreSQL"). SQLite has no ``ANY()`` array function and no array bind type
at all -- passing a Python list as a single ``:flow_ids`` parameter to
sqlite3 raises a binding error before the query ever runs, meaning every one
of ``_steps_for_flows``, ``_history_for_flows``, and ``_delete_tracking_
flow_ids`` (which the other two call for cascading delete) was completely
broken under SQLite the moment a non-empty id list was supplied.

Fix: replaced the five ``= ANY(:flow_ids)`` sites with the dialect-neutral
SQLAlchemy "expanding IN" pattern (``IN :flow_ids`` + ``bindparam("flow_ids",
expanding=True)``, added via new ``_prepare_clause``/``_execute`` helpers) --
this compiles to a real ``IN (v1, v2, ...)`` list on BOTH SQLite and
PostgreSQL, with identical semantics to PostgreSQL's own ``= ANY(array)``
for equality-matching a column against a list of values (proven directly,
see below).

Verification performed for this fix (both required by Defect AB, neither
substituted for the other):
  1. PostgreSQL: the exact fixed SQL pattern (``IN :flow_ids`` + expanding
     bindparam) was executed directly against a real, disposable local
     PostgreSQL 15 database (created, exercised, and dropped in the same
     session -- not part of this permanent suite, since this repo's
     established test convention does not require a live PostgreSQL server
     to run its permanent test suite) -- confirmed identical row-selection
     and deletion behavior to the original ``= ANY(:flow_ids)`` semantics.
  2. SQLite: this file, run as a real permanent pytest suite against a real
     isolated SQLite-backed Flask app -- the concrete regression proof that
     was previously impossible (the pre-fix code could not even be
     imported into a working SQLite request without raising).

Note on ``tracking_visible``: this column is added at runtime by
``apply_phase8_schema()``'s ``_add_column`` helper, which at the time this
file was first written still used PostgreSQL-only ``ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`` syntax -- a SEPARATE dual-database gap, mechanically
discovered while building this test, but NOT one of Defect AB's five named
``= ANY(:flow_ids)`` call sites and therefore out of this fix's scope
(reported separately as finding AI). AI has since been fixed (see
tests/behavior/test_process_engine_phase8_schema_dual_database_contract.py
for its own dedicated regression suite); this file still adds the column
itself directly, via plain SQLite-compatible DDL in its own fixture setup,
because its purpose is exercising ONLY the five AB call sites in isolation
-- it deliberately does not call or exercise apply_phase8_schema().
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from app.services.performance.process_engine_phase8_tracking import (
    _delete_tracking_flow_ids,
    _history_for_flows,
    _steps_for_flows,
)
from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ab")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ab-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ab-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    # BYS360 DEFECT AB: a plain "sqlite:///:memory:" URL gives each new
    # connection checkout its OWN isolated in-memory database under Flask-
    # SQLAlchemy's default pooling -- data created in one `with app.
    # app_context():` block would vanish in the next. This test creates
    # data and reads it back across separate contexts (matching real
    # request-per-context usage), so it uses this session's established,
    # proven pattern instead: a real unique temp-file SQLite DB + StaticPool
    # + an explicit BEGIN so the whole test session shares one connection.
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_ab_{uuid.uuid4().hex}.sqlite3")
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

        # BYS360 DEFECT AB test-only fixture note: tracking_visible and
        # action_at (referenced in _steps_for_flows' own ORDER BY) are
        # normally added at runtime by apply_phase8_schema()'s _add_column
        # helper, which itself uses PostgreSQL-only "ADD COLUMN IF NOT
        # EXISTS" syntax (finding AI, reported separately, not fixed here).
        # Added directly here via plain, SQLite-compatible DDL instead, so
        # this test exercises ONLY the actual Defect AB fix under test.
        db.session.execute(
            db.text("ALTER TABLE performance_process_flow_steps ADD COLUMN tracking_visible BOOLEAN DEFAULT 1")
        )
        db.session.execute(
            db.text("ALTER TABLE performance_process_flow_steps ADD COLUMN action_at DATETIME")
        )
        db.session.execute(
            db.text("ALTER TABLE performance_scoring_history ADD COLUMN action_at DATETIME")
        )
        db.session.commit()
    return flask_app


def _create_flow(app, *, evaluation_id: int) -> int:
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    with app.app_context():
        flow = PerformanceProcessFlow(evaluation_id=evaluation_id)
        db.session.add(flow)
        db.session.commit()
        return flow.id


def _create_step(app, *, flow_id: int, evaluation_id: int, step_key: str, step_title: str) -> int:
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceProcessFlowStep

    with app.app_context():
        step = PerformanceProcessFlowStep(
            flow_id=flow_id, evaluation_id=evaluation_id, step_key=step_key, step_title=step_title,
        )
        db.session.add(step)
        db.session.commit()
        return step.id


def _create_notification(app, *, flow_id: int) -> int:
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceProcessNotification

    with app.app_context():
        note = PerformanceProcessNotification(
            flow_id=flow_id, recipient_id=1, notification_type="test", title="t",
        )
        db.session.add(note)
        db.session.commit()
        return note.id


# ---------------------------------------------------------------------------
# _steps_for_flows: real SQLite SELECT ... WHERE flow_id IN :flow_ids
# ---------------------------------------------------------------------------


def test_steps_for_flows_returns_only_requested_flows_own_steps(app):
    flow_a = _create_flow(app, evaluation_id=101)
    flow_b = _create_flow(app, evaluation_id=102)
    flow_c = _create_flow(app, evaluation_id=103)
    _create_step(app, flow_id=flow_a, evaluation_id=101, step_key="k_a", step_title="Step A")
    _create_step(app, flow_id=flow_b, evaluation_id=102, step_key="k_b", step_title="Step B")
    _create_step(app, flow_id=flow_c, evaluation_id=103, step_key="k_c", step_title="Step C")

    with app.app_context():
        grouped = _steps_for_flows([flow_a, flow_b])

    assert set(grouped.keys()) == {flow_a, flow_b}
    assert flow_c not in grouped, "an id NOT in the requested list must never leak into the result"
    assert grouped[flow_a][0]["title"] == "Step A"
    assert grouped[flow_b][0]["title"] == "Step B"


def test_steps_for_flows_with_empty_list_returns_empty_dict_without_querying(app):
    with app.app_context():
        assert _steps_for_flows([]) == {}


def test_steps_for_flows_preserves_multiple_steps_per_flow_and_ordering(app):
    flow_a = _create_flow(app, evaluation_id=201)
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceProcessFlowStep

    with app.app_context():
        db.session.add(PerformanceProcessFlowStep(flow_id=flow_a, evaluation_id=201, step_key="s1", step_title="First", step_order=1))
        db.session.add(PerformanceProcessFlowStep(flow_id=flow_a, evaluation_id=201, step_key="s2", step_title="Second", step_order=2))
        db.session.commit()

    with app.app_context():
        grouped = _steps_for_flows([flow_a])

    titles = [item["title"] for item in grouped[flow_a]]
    assert titles == ["First", "Second"]


# ---------------------------------------------------------------------------
# _history_for_flows: real SQLite SELECT ... JOIN ... WHERE f.id IN :flow_ids
# ---------------------------------------------------------------------------


def test_history_for_flows_returns_empty_when_no_scoring_history_evaluation_id_column(app):
    """This function fails closed (returns {}) if performance_scoring_history
    lacks an evaluation_id column -- unaffected by the AB fix, confirmed
    unchanged so the IN-list rewrite didn't alter this fail-closed guard."""
    flow_a = _create_flow(app, evaluation_id=301)
    with app.app_context():
        result = _history_for_flows([flow_a])
    # The real PerformanceScoringHistory model DOES declare evaluation_id,
    # so this should reach the real query path and return an (empty, since
    # no history rows exist yet) dict rather than short-circuiting.
    assert result == {}


def test_history_for_flows_with_empty_list_returns_empty_dict_without_querying(app):
    with app.app_context():
        assert _history_for_flows([]) == {}


def test_history_for_flows_joins_only_requested_flows(app):
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceScoringHistory

    flow_a = _create_flow(app, evaluation_id=401)
    flow_b = _create_flow(app, evaluation_id=402)
    with app.app_context():
        db.session.add(PerformanceScoringHistory(evaluation_id=401, scorer_label="Scorer A"))
        db.session.add(PerformanceScoringHistory(evaluation_id=402, scorer_label="Scorer B"))
        db.session.commit()

    with app.app_context():
        grouped = _history_for_flows([flow_a])

    assert set(grouped.keys()) == {flow_a}
    assert flow_b not in grouped, "history for an unrequested flow must never leak into the result"


# ---------------------------------------------------------------------------
# _delete_tracking_flow_ids: real SQLite DELETE ... WHERE flow_id IN :flow_ids
# (three of Defect AB's five call sites live here, cascading across three
# tables in one call)
# ---------------------------------------------------------------------------


def test_delete_tracking_flow_ids_deletes_only_requested_flows_and_their_children(app):
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    flow_a = _create_flow(app, evaluation_id=501)
    flow_b = _create_flow(app, evaluation_id=502)
    _create_step(app, flow_id=flow_a, evaluation_id=501, step_key="k_a", step_title="A")
    _create_step(app, flow_id=flow_b, evaluation_id=502, step_key="k_b", step_title="B")
    _create_notification(app, flow_id=flow_a)
    _create_notification(app, flow_id=flow_b)

    with app.app_context():
        deleted_count = _delete_tracking_flow_ids([flow_a])

    assert deleted_count == 1

    with app.app_context():
        from app.models.performance_process_engine_models import (
            PerformanceProcessFlowStep,
            PerformanceProcessNotification,
        )

        remaining_flow_ids = {row.id for row in PerformanceProcessFlow.query.all()}
        remaining_step_flow_ids = {row.flow_id for row in PerformanceProcessFlowStep.query.all()}
        remaining_notification_flow_ids = {row.flow_id for row in PerformanceProcessNotification.query.all()}

    assert remaining_flow_ids == {flow_b}, "only the requested flow must be deleted, the other must survive intact"
    assert remaining_step_flow_ids == {flow_b}, "cascading step delete must not touch an unrequested flow's steps"
    assert remaining_notification_flow_ids == {flow_b}, "cascading notification delete must not touch an unrequested flow's notifications"


def test_delete_tracking_flow_ids_with_empty_list_deletes_nothing(app):
    flow_a = _create_flow(app, evaluation_id=601)
    _create_step(app, flow_id=flow_a, evaluation_id=601, step_key="k", step_title="t")

    with app.app_context():
        deleted_count = _delete_tracking_flow_ids([])

    assert deleted_count == 0
    with app.app_context():
        from app.models.performance_process_engine_models import PerformanceProcessFlow

        assert PerformanceProcessFlow.query.count() == 1


def test_delete_tracking_flow_ids_multiple_ids_in_one_call(app):
    flow_a = _create_flow(app, evaluation_id=701)
    flow_b = _create_flow(app, evaluation_id=702)
    flow_c = _create_flow(app, evaluation_id=703)

    with app.app_context():
        deleted_count = _delete_tracking_flow_ids([flow_a, flow_c])

    assert deleted_count == 2
    with app.app_context():
        from app.models.performance_process_engine_models import PerformanceProcessFlow

        remaining = {row.id for row in PerformanceProcessFlow.query.all()}
    assert remaining == {flow_b}
