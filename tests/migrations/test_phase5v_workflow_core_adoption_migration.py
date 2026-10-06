from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "5a7c9e1f2b30_adopt_workflow_core_runtime_schema.py"
)
EXPECTED_TABLES = {
    "workflow_instances",
    "workflow_steps",
    "workflow_logs",
    "workflow_notifications",
}


def _load_migration() -> Any:
    # The loaded migration module's op/upgrade/downgrade/revision attributes
    # are dynamically defined by whichever versions/*.py file is loaded, and
    # `op` is deliberately reassigned below before each upgrade/downgrade
    # call -- there is no fixed static contract to type against.
    spec = importlib.util.spec_from_file_location("phase5v_workflow_adoption", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(connection: sa.Connection) -> None:
    module = _load_migration()
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


def _run_downgrade(connection: sa.Connection) -> None:
    module = _load_migration()
    module.op = Operations(MigrationContext.configure(connection))
    module.downgrade()


def _column_names(connection: sa.Connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table_name)}


def _index_names(connection: sa.Connection, table_name: str) -> set[str]:
    # Real indexes always have a real string name (SQLite/Postgres both
    # require one); ReflectedIndex.name is only str | None in SQLAlchemy's
    # generic reflection stub for dialects that could theoretically omit it.
    return {cast(str, index["name"]) for index in sa.inspect(connection).get_indexes(table_name)}


def test_phase5v_empty_database_gets_complete_workflow_core_schema() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        _run_upgrade(connection)

        assert EXPECTED_TABLES.issubset(set(sa.inspect(connection).get_table_names()))
        assert {"workflow_family", "delayed_step_count", "payload_json"}.issubset(
            _column_names(connection, "workflow_instances")
        )
        assert {
            "step_type",
            "is_active",
            "is_required",
            "visible_to_user_id",
            "delay_state",
            "delay_days",
            "escalation_level",
            "last_reminded_at",
            "reminder_count",
            "notification_status",
        }.issubset(_column_names(connection, "workflow_steps"))
        assert {
            "ix_workflow_instances_module_status",
            "ix_workflow_instances_subject_period",
        }.issubset(_index_names(connection, "workflow_instances"))
        assert {
            "ix_workflow_steps_workflow_order",
            "ix_workflow_steps_status",
        }.issubset(_index_names(connection, "workflow_steps"))
        assert {
            "ix_workflow_notifications_status",
            "ix_workflow_notifications_target",
        }.issubset(_index_names(connection, "workflow_notifications"))

        step_fks = sa.inspect(connection).get_foreign_keys("workflow_steps")
        notification_fks = sa.inspect(connection).get_foreign_keys("workflow_notifications")
        assert any(fk["referred_table"] == "workflow_instances" for fk in step_fks)
        assert {fk["referred_table"] for fk in notification_fks} == {
            "workflow_instances",
            "workflow_steps",
        }


def test_phase5v_adopts_legacy_runtime_tables_without_losing_rows() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE workflow_instances (
                id INTEGER PRIMARY KEY,
                module VARCHAR(80) NOT NULL,
                entity_type VARCHAR(120),
                entity_id INTEGER,
                title VARCHAR(255) NOT NULL,
                subject_user_id INTEGER,
                period_id INTEGER,
                score NUMERIC(8,2),
                status VARCHAR(40) NOT NULL DEFAULT 'ACTIVE',
                current_step_name VARCHAR(255),
                priority VARCHAR(30) NOT NULL DEFAULT 'NORMAL',
                created_by_id INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                payload_json JSON
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE workflow_steps (
                id INTEGER PRIMARY KEY,
                workflow_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                step_code VARCHAR(80),
                step_name VARCHAR(255) NOT NULL,
                assigned_user_id INTEGER,
                status VARCHAR(40) NOT NULL DEFAULT 'PENDING',
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                due_at TIMESTAMP,
                duration_minutes INTEGER,
                note TEXT
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO workflow_instances (id, module, title) VALUES (7, 'performance', 'Korunacak kayıt')"
        )
        connection.exec_driver_sql(
            "INSERT INTO workflow_steps (id, workflow_id, step_order, step_name) VALUES (9, 7, 1, 'İlk adım')"
        )

        _run_upgrade(connection)
        _run_upgrade(connection)

        instance = connection.execute(
            sa.text("SELECT id, module, title, workflow_family, delayed_step_count FROM workflow_instances WHERE id=7")
        ).mappings().one()
        step = connection.execute(
            sa.text(
                "SELECT id, workflow_id, step_name, delay_state, reminder_count, notification_status "
                "FROM workflow_steps WHERE id=9"
            )
        ).mappings().one()

        assert dict(instance) == {
            "id": 7,
            "module": "performance",
            "title": "Korunacak kayıt",
            "workflow_family": "GENERAL",
            "delayed_step_count": 0,
        }
        assert dict(step) == {
            "id": 9,
            "workflow_id": 7,
            "step_name": "İlk adım",
            "delay_state": "NORMAL",
            "reminder_count": 0,
            "notification_status": "READY",
        }
        assert EXPECTED_TABLES.issubset(set(sa.inspect(connection).get_table_names()))


def test_phase5v_downgrade_is_non_destructive_for_adopted_tables() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _run_upgrade(connection)
        connection.execute(
            sa.text(
                "INSERT INTO workflow_instances (id, module, title) "
                "VALUES (1, 'performance', 'Korunacak süreç')"
            )
        )

        _run_downgrade(connection)

        assert EXPECTED_TABLES.issubset(set(sa.inspect(connection).get_table_names()))
        assert connection.execute(sa.text("SELECT title FROM workflow_instances WHERE id=1")).scalar_one() == (
            "Korunacak süreç"
        )


def test_phase5v_revision_extends_the_single_current_head() -> None:
    module = _load_migration()
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    script = ScriptDirectory.from_config(config)

    assert module.revision == "5a7c9e1f2b30"
    assert module.down_revision == "bys360_portal_v2121"
    # x1f3a9c5e7b2 (adopt performance_interim_notes into Alembic ownership)
    # extends w2d8e1f4a6c3 and is now the single current head.
    assert script.get_heads() == ["x1f3a9c5e7b2"]
