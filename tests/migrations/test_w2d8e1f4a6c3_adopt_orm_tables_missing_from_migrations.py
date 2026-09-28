"""Drives migrations/versions/w2d8e1f4a6c3 (ORM tables/columns that no migration created).

- a migration-built database gains the 29 ORM tables, special_scenario_type and the
  ORM columns of the empty phase-6 shaped low-score events table;
- tables and columns that already exist are left unchanged, rows preserved;
- a non-empty phase-6 events table is left unchanged;
- a second upgrade and the downgrade are no-ops.
PostgreSQL behaviour is proven by scripts/quality/bys360_postgres_migration_integrity_gate.py
(POSTGRES15_ORM_PARITY).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "w2d8e1f4a6c3_adopt_orm_tables_missing_from_migrations.py"
EVENTS = "performance_low_score_process_events"
EVENT_ORM_COLUMNS = {"process_id", "step_key", "title", "status", "actor_user_id", "note"}


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("w2d8e1f4a6c3_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection: sa.Connection, step: str) -> None:
    module = _module()
    original = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        getattr(module, step)()
    finally:
        module.op = original


def _columns(connection: sa.Connection, table: str) -> dict[str, Any]:
    return {c["name"]: c for c in sa.inspect(connection).get_columns(table)}


def _legacy_database(connection: sa.Connection) -> None:
    """The tables a migration-built database has before w2d8e1f4a6c3, as far as the migration reads them."""
    connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(120) NOT NULL)"))
    connection.execute(sa.text("CREATE TABLE performance_periods (id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL)"))
    connection.execute(sa.text(
        f"CREATE TABLE {EVENTS} (id INTEGER PRIMARY KEY, employee_id INTEGER, period_id INTEGER, scorecard_id INTEGER, "
        "final_score NUMERIC(10, 2), calendar_year INTEGER, repeat_level VARCHAR(32), approval_status VARCHAR(64), "
        "process_status VARCHAR(64), publish_blocked BOOLEAN, created_at DATETIME, updated_at DATETIME, sort_order INTEGER)"
    ))
    connection.execute(sa.text("INSERT INTO performance_periods (id, title) VALUES (7, '2026 Dönemi')"))


def test_revision_extends_wave1_and_is_the_single_head():
    module = _module()
    assert module.revision == "w2d8e1f4a6c3"
    assert module.down_revision == "w1c5a7d2e9b4"
    config = Config(str(ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == ["w2d8e1f4a6c3"]


def test_migration_built_database_gains_every_adopted_object():
    module = _module()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_database(connection)
        _run(connection, "upgrade")
        tables = set(sa.inspect(connection).get_table_names())
        assert {name for name, _ in module.ADOPTED_TABLES} <= tables
        assert len(module.ADOPTED_TABLES) == 29
        assert "special_scenario_type" in _columns(connection, "performance_periods")
        events = _columns(connection, EVENTS)
        assert set(events) >= EVENT_ORM_COLUMNS
        assert events["process_id"]["nullable"] is False
        unique = {tuple(u["column_names"]) for u in sa.inspect(connection).get_unique_constraints(EVENTS)}
        assert ("process_id", "step_key") in unique
        assert connection.execute(sa.text("SELECT title FROM performance_periods WHERE id = 7")).scalar() == "2026 Dönemi"


def test_existing_tables_and_rows_are_left_unchanged():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_database(connection)
        connection.execute(sa.text("CREATE TABLE publication_issues (id INTEGER PRIMARY KEY, legacy_note TEXT)"))
        connection.execute(sa.text("INSERT INTO publication_issues (id, legacy_note) VALUES (3, 'kurum verisi')"))
        before = _columns(connection, "publication_issues")
        _run(connection, "upgrade")
        assert set(_columns(connection, "publication_issues")) == set(before)
        assert connection.execute(sa.text("SELECT legacy_note FROM publication_issues WHERE id = 3")).scalar() == "kurum verisi"


def test_non_empty_phase6_events_table_is_left_unchanged():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_database(connection)
        connection.execute(sa.text(f"INSERT INTO {EVENTS} (id, employee_id, period_id, final_score) VALUES (1, 5, 7, 61.5)"))
        before = set(_columns(connection, EVENTS))
        _run(connection, "upgrade")
        assert set(_columns(connection, EVENTS)) == before
        assert not EVENT_ORM_COLUMNS & before
        row = connection.execute(sa.text(f"SELECT employee_id, period_id FROM {EVENTS} WHERE id = 1")).one()
        assert tuple(row) == (5, 7)


def test_second_upgrade_and_downgrade_are_no_ops():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_database(connection)
        _run(connection, "upgrade")

        def shape() -> dict[str, set[str]]:
            inspector = sa.inspect(connection)
            return {t: {c["name"] for c in inspector.get_columns(t)} for t in inspector.get_table_names()}

        once = shape()
        _run(connection, "upgrade")
        _run(connection, "downgrade")
        assert shape() == once
