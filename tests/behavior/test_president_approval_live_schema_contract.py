"""Regression contract: PerformancePresidentApproval matches the canonical
performance_president_approvals schema (BYS360 live evidence remediation V1).

The model mapped a ``rule_version`` column that no migration creates (the
table's schema owner, migration 6f2b8c4d1a90, uses ``process_version``) and
that the verified production table (Alembic head v1a2d3e4f5b6) does not have.
Every ORM read of the entity therefore failed on both schemas; the mobile
approval counters swallowed the error and showed 0.

These tests build the table the way the real schema does -- through the
adoption migration itself -- instead of from the ORM, so a ghost column in the
model fails them.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

ADOPTION_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "6f2b8c4d1a90_adopt_workflow_president_approval_schema.py"
)

# ORM columns the live validation (2026-09-28) found present on production:
# 13 of the model's former 14, the missing one being rule_version.
LIVE_VERIFIED_ORM_COLUMNS = {
    "id", "flow_id", "evaluation_id", "period_id", "employee_id", "final_score", "status",
    "president_user_id", "requested_at", "decided_at", "decision_note", "created_at", "updated_at",
}

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_live_schema_a")


def _orm_columns() -> set[str]:
    from app.models.performance_process_engine_models import PerformancePresidentApproval

    return {column.name for column in PerformancePresidentApproval.__table__.columns}


def _run_adoption_migration(connection: sa.Connection) -> None:
    spec = importlib.util.spec_from_file_location("live_schema_a_migration", ADOPTION_MIGRATION)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_op = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        module.upgrade()
    finally:
        module.op = original_op


def _ensure_workflow_instances(connection: sa.Connection) -> None:
    # The adoption migration's workflow_id FK targets this migration-only table.
    connection.execute(sa.text("CREATE TABLE IF NOT EXISTS workflow_instances (id INTEGER PRIMARY KEY)"))


def test_model_maps_exactly_the_live_verified_columns() -> None:
    assert "rule_version" not in _orm_columns()
    assert _orm_columns() == LIVE_VERIFIED_ORM_COLUMNS


def test_fresh_migration_built_table_covers_every_orm_column() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _ensure_workflow_instances(connection)
        _run_adoption_migration(connection)
        migrated = {column["name"] for column in sa.inspect(connection).get_columns("performance_president_approvals")}

    assert _orm_columns() - migrated == set()


def _make_app(monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "APP_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-live-schema-a-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "live-schema-a-first-login-test-pw",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"live_schema_a_{uuid.uuid4().hex}.sqlite3")
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
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
    )
    return flask_app


@pytest.fixture
def production_shaped_app(monkeypatch: pytest.MonkeyPatch):
    """App whose performance_president_approvals comes from the adoption migration, not the ORM."""
    flask_app = _make_app(monkeypatch)
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        with db.engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE performance_president_approvals"))
            _ensure_workflow_instances(connection)
            _run_adoption_migration(connection)
            connection.execute(
                sa.text(
                    "INSERT INTO performance_president_approvals (evaluation_id, period_id, status) "
                    "VALUES (4101, 7, 'pending'), (4102, 7, 'approved')"
                )
            )
        db.session.remove()
    yield flask_app
    with flask_app.app_context():
        from app.extensions import db

        db.session.remove()


def test_orm_reads_succeed_on_production_shaped_table(production_shaped_app) -> None:
    from app.models.performance_process_engine_models import PerformancePresidentApproval

    with production_shaped_app.app_context():
        columns = {c["name"] for c in sa.inspect(PerformancePresidentApproval.query.session.get_bind()).get_columns("performance_president_approvals")}
        assert "rule_version" not in columns

        assert PerformancePresidentApproval.query.filter_by(status="pending").count() == 1
        rows = PerformancePresidentApproval.query.order_by(PerformancePresidentApproval.id.desc()).limit(30).all()
        assert [row.evaluation_id for row in rows] == [4102, 4101]


def test_mobile_pending_counter_is_not_silently_zero(production_shaped_app) -> None:
    """The mobile counter swallows query errors and returns 0; it must see the real pending row."""
    from app.api.mobile.performance_routes import _mobile_perf_safe_count
    from app.models.performance_process_engine_models import PerformancePresidentApproval

    with production_shaped_app.app_context():
        assert _mobile_perf_safe_count(PerformancePresidentApproval.query.filter_by(status="pending")) == 1
