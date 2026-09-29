"""Drives migrations/versions/w1c5a7d2e9b4 (adopt runtime-added users / performance_periods columns).

- a migration-built database (columns absent) gains the ORM columns, rows preserved;
- a production-shaped database (columns already present) is left unchanged;
- a second upgrade and the downgrade are no-ops.
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
MIGRATION = ROOT / "migrations" / "versions" / "w1c5a7d2e9b4_adopt_user_and_period_runtime_columns.py"
USER_COLUMNS = {"birth_date", "hire_date", "celebration_opt_out"}
PERIOD_COLUMNS = {"evaluation_start_date", "evaluation_end_date", "evaluation_due_days"}


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("w1c5a7d2e9b4_migration", MIGRATION)
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


def _legacy_tables(connection: sa.Connection, *, with_adopted: bool) -> None:
    user_extra = ", birth_date DATE, hire_date DATE, celebration_opt_out BOOLEAN NOT NULL DEFAULT 0" if with_adopted else ""
    period_extra = ", evaluation_start_date DATE, evaluation_end_date DATE, evaluation_due_days INTEGER" if with_adopted else ""
    connection.execute(sa.text(f"CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(120) NOT NULL{user_extra})"))
    connection.execute(sa.text(f"CREATE TABLE performance_periods (id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL{period_extra})"))
    connection.execute(sa.text("INSERT INTO users (id, email) VALUES (1, 'a@example.gov.tr'), (2, 'b@example.gov.tr')"))
    connection.execute(sa.text("INSERT INTO performance_periods (id, title) VALUES (7, '2026 Dönemi')"))


def test_revision_extends_the_production_head():
    module = _module()
    assert module.revision == "w1c5a7d2e9b4"
    assert module.down_revision == "v1a2d3e4f5b6"
    config = Config(str(ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    assert ScriptDirectory.from_config(config).get_revision("w2d8e1f4a6c3").down_revision == "w1c5a7d2e9b4"


def test_migration_built_database_gains_the_orm_columns_and_keeps_rows():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_tables(connection, with_adopted=False)
        _run(connection, "upgrade")
        users = _columns(connection, "users")
        periods = _columns(connection, "performance_periods")
        assert set(users) >= USER_COLUMNS
        assert set(periods) >= PERIOD_COLUMNS
        assert users["celebration_opt_out"]["nullable"] is False
        rows = connection.execute(sa.text("SELECT id, email, celebration_opt_out FROM users ORDER BY id")).all()
        assert [(r[0], r[1], bool(r[2])) for r in rows] == [(1, "a@example.gov.tr", False), (2, "b@example.gov.tr", False)]
        assert connection.execute(sa.text("SELECT title FROM performance_periods WHERE id = 7")).scalar() == "2026 Dönemi"


def test_production_shaped_database_is_left_unchanged():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_tables(connection, with_adopted=True)
        before = (_columns(connection, "users"), _columns(connection, "performance_periods"))
        _run(connection, "upgrade")
        after = (_columns(connection, "users"), _columns(connection, "performance_periods"))
        assert {k: str(v["type"]) for k, v in before[0].items()} == {k: str(v["type"]) for k, v in after[0].items()}
        assert {k: str(v["type"]) for k, v in before[1].items()} == {k: str(v["type"]) for k, v in after[1].items()}


def test_second_upgrade_and_downgrade_are_no_ops():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_tables(connection, with_adopted=False)
        _run(connection, "upgrade")
        once = set(_columns(connection, "users")) | {f"p.{c}" for c in _columns(connection, "performance_periods")}
        _run(connection, "upgrade")
        _run(connection, "downgrade")
        twice = set(_columns(connection, "users")) | {f"p.{c}" for c in _columns(connection, "performance_periods")}
        assert once == twice
