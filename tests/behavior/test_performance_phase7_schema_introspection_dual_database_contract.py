"""BYS360_DEFECT_AK_PHASE7_SCHEMA_INTROSPECTION_DUAL_DATABASE_CONTRACT

Regression contract for Defect AK: app/services/performance/
process_engine_phase7_president_rule.py's ``_table_exists()``/``_columns()``
schema-introspection helpers used raw PostgreSQL-only ``information_schema``
queries filtered by the PostgreSQL-only ``current_schema()`` SQL function --
deliberately left untouched by Defect AJ (which fixed only this same file's
``ensure_phase7_schema()``, a genuinely separate call path).

Call graph traced before any fix (not assumed): ``_table_exists``/
``_columns`` have zero direct app-side (route/service) callers of their
own, but ARE called by ``_evaluation_columns()``, which is called by
``_evaluation_row()`` and ``candidate_evaluation_ids()``; ``_table_exists``
is also called directly by ``manager_chain_completed()``,
``find_president_user()``, and ``candidate_evaluation_ids()``. The whole
process_engine_phase7_president_rule.py module itself currently has zero
importers anywhere else in app/ (confirmed by repo-wide search) -- the
same "no current live-route caller, but real exported production code
within this app's own supported dual-database architecture" profile
already established for Defects AI/AJ's phase3/phase4/phase6/phase8
schema helpers.

SQLite is unambiguously part of this application's supported contract,
not an incidental convenience: config.py's own DATABASE_URL resolution
falls back to ``sqlite:///:memory:`` when unset (the app's literal
default), and tests/conftest.py's own test fixture defaults every test's
database to a real SQLite file. Every sibling schema-repair helper in this
exact file family (phase3/4/6/8, and this same file's own AJ-fixed
``_add_column_if_missing``) is dialect-neutral for exactly this reason.

Mechanical SQLite reproduction (real, disposable, real Flask app + real
SQLite -- performed once during AK triage through five independent call
paths, not part of this permanent suite):

    >>> _table_exists("performance_evaluations")
    sqlite3.OperationalError: no such table: information_schema.tables
    >>> candidate_evaluation_ids()
    sqlite3.OperationalError: no such table: information_schema.tables
    >>> manager_chain_completed(1)
    sqlite3.OperationalError: no such table: information_schema.tables
    >>> find_president_user()
    sqlite3.OperationalError: no such table: information_schema.tables

CLASSIFICATION: CONFIRMED_CROSS_DATABASE_DEFECT.

Fix: both helpers now use SQLAlchemy's ``inspect()`` -- dialect-neutral by
construction, the identical pattern already proven safe in phase3/phase4/
phase6/phase8 and in this same file's own AJ fix. ``_table_exists``'s
missing-table contract (``False``, not an exception) and ``_columns``'s
missing-table contract (empty set, not an exception) are both preserved
exactly. No change was made to ``ensure_phase7_schema()`` (Defect AJ's own
fix, unrelated call path).

A one-time real, disposable local PostgreSQL 15 database verification
(created, exercised, dropped in the same session) confirmed BOTH the
original raw-SQL behavior (captured as the exact baseline this fix must
match) and the new inspect()-based implementation produce identical
results: missing table -> False/empty set, existing table -> True/correct
column set, and the real ``candidate_evaluation_ids()`` service function
runs end to end -- this repo's permanent suite does not require a live
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

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ak")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ak-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ak-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_ak_{uuid.uuid4().hex}.sqlite3")
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


def test_table_exists_true_for_a_real_existing_table_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase7_president_rule import _table_exists

    with app.app_context():
        assert _table_exists("performance_evaluations") is True


def test_table_exists_false_for_a_missing_table_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase7_president_rule import _table_exists

    with app.app_context():
        assert _table_exists("this_table_does_not_exist_anywhere") is False


def test_columns_returns_exact_expected_set_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase7_president_rule import _columns

    with app.app_context():
        db.session.execute(
            db.text("CREATE TABLE ak_probe_table (id INTEGER PRIMARY KEY, alpha VARCHAR(10), beta INTEGER)")
        )
        db.session.commit()
        cols = _columns("ak_probe_table")
        assert cols == {"id", "alpha", "beta"}


def test_columns_returns_empty_set_for_a_missing_table_on_sqlite(app) -> None:
    """Preserves the original query's exact missing-table contract: an
    absent table returns an empty set, never an exception."""
    from app.services.performance.process_engine_phase7_president_rule import _columns

    with app.app_context():
        assert _columns("this_table_does_not_exist_anywhere") == set()


def test_candidate_evaluation_ids_real_caller_succeeds_on_sqlite(app) -> None:
    """The actual, unmocked, higher-level Phase7 caller (not a copy of the
    helper's SQL) must run end to end -- this is what was previously
    impossible under SQLite."""
    from app.services.performance.process_engine_phase7_president_rule import (
        candidate_evaluation_ids,
    )

    with app.app_context():
        result = candidate_evaluation_ids(limit=10)
        assert result == []  # empty performance_evaluations table -- no candidates, but no exception


def test_manager_chain_completed_real_caller_succeeds_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase7_president_rule import (
        manager_chain_completed,
    )

    with app.app_context():
        result = manager_chain_completed(999999)
        assert result is False  # no such evaluation -- graceful False, not an exception


def test_find_president_user_real_caller_succeeds_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase7_president_rule import (
        PresidentUser,
        find_president_user,
    )

    with app.app_context():
        result = find_president_user()
        assert isinstance(result, PresidentUser)


def test_helpers_are_idempotent_across_repeated_calls(app) -> None:
    from app.services.performance.process_engine_phase7_president_rule import (
        _columns,
        _table_exists,
    )

    with app.app_context():
        first = _table_exists("performance_evaluations")
        second = _table_exists("performance_evaluations")
        assert first == second is True

        first_cols = _columns("performance_evaluations")
        second_cols = _columns("performance_evaluations")
        assert first_cols == second_cols


def test_columns_reflects_real_data_without_altering_it(app) -> None:
    """Existing data preservation: introspecting a table's columns must
    never touch its rows."""
    from app.extensions import db
    from app.models.performance_models import PerformanceEvaluation
    from app.services.performance.process_engine_phase7_president_rule import _columns

    with app.app_context():
        evaluation = PerformanceEvaluation(
            employee_id=1,
            period_id=1,
        )
        db.session.add(evaluation)
        db.session.commit()
        evaluation_id = evaluation.id

        cols = _columns("performance_evaluations")
        assert "id" in cols

        reloaded = db.session.get(PerformanceEvaluation, evaluation_id)
        assert reloaded is not None
        assert reloaded.employee_id == 1
