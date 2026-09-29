"""BYS360_DEFECT_AD_APPLICATION_LEVEL_DB_CONSTRAINT_PROOF

Defect AD closes a genuine concurrency gap: every activation code path
(app/performance/admin_core_routes.py::performance_period_toggle_active,
app/services/performance/v2_1_6_category_period_integration.py::
create_or_update_period_from_plan) only enforces "at most one active
PerformancePeriod" inside its OWN transaction/session. Nothing stopped two
independent sessions from each committing an active row without ever
seeing each other's in-flight change -- the classic check-then-act race,
which no single-session test can expose.

This test proves the fix is real at the layer that actually matters: the
real PerformancePeriod ORM model, against a real file-based SQLite database
with the new migrations/versions/v1a2d3e4f5b6_...  partial unique index
applied, using TWO INDEPENDENT Flask app_contexts (matching real per-
request session isolation -- the same pattern already established and
documented in test_process_engine_phase8_dual_database_binding_contract.py
for why a shared temp-file DB, not sqlite:///:memory:, is required here).
Session A commits an active period first. Session B then attempts to
commit its OWN active period -- deliberately NOT running any of this
codebase's own deactivation logic, i.e. simulating exactly the race a
lost/interleaved deactivation step would produce -- and must fail with a
real IntegrityError raised BY THE DATABASE, not by any Python-level guard.
This is the actual property AD adds: the invariant now holds even when
application code does nothing to protect it.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ad")

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "v1a2d3e4f5b6_add_performance_period_single_active_constraint.py"
)


def _apply_single_active_index(engine: sa.engine.Engine) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("v1a2d3e4f5b6_ad_index", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ad-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ad-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_ad_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app


def test_two_independent_sessions_racing_to_activate_different_periods_the_second_commit_fails_at_the_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app(monkeypatch)
    from app.extensions import db
    from app.models.performance_models import PerformancePeriod
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
        _apply_single_active_index(db.engine)

    # Session A: a normal, successful activation -- commits cleanly.
    with app.app_context():
        period_a = PerformancePeriod(
            title="Period A",
            name="Period A",
            period_type="special",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
        )
        db.session.add(period_a)
        db.session.commit()

    # Session B: an INDEPENDENT session/context (models a second, concurrent
    # request) that -- by construction of this test -- skips this
    # codebase's own "deactivate every other active period first" step,
    # standing in for exactly the interleaving a real race could produce.
    # Only the DB-level constraint added by Defect AD can stop this.
    with app.app_context():
        period_b = PerformancePeriod(
            title="Period B",
            name="Period B",
            period_type="special",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
            is_active=True,
        )
        db.session.add(period_b)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    # Final state: exactly one active period (A), proving the race never
    # produced two -- not because application code prevented it here (it
    # deliberately didn't), but because the database itself refused.
    with app.app_context():
        active_titles = [
            row.title
            for row in PerformancePeriod.query.filter_by(is_active=True).all()
        ]
        assert active_titles == ["Period A"]
        assert PerformancePeriod.query.count() == 1, "the losing insert must be fully rolled back, not persisted as inactive"


# ---------------------------------------------------------------------------
# The specific AD ordering fix: create_or_update_period_from_plan's
# NEW-period branch used to construct+flush a brand-new PerformancePeriod
# with is_active already True, before its own deactivate-others step ran.
# Under the AD unique index that premature flush would IntegrityError
# whenever another period is already active -- exactly the scenario this
# test drives, using the real plan-integration entrypoint end to end.
# ---------------------------------------------------------------------------


def _make_app_with_static_pool(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ad-plan-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ad-plan-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_ad_plan_{uuid.uuid4().hex}.sqlite3")
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
    from app.services import runtime_schema

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
        _apply_single_active_index(db.engine)

    return flask_app


def test_activating_new_plan_period_while_another_period_is_active_succeeds_under_the_db_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app_with_static_pool(monkeypatch)
    from app.extensions import db
    from app.models.performance_models import PerformancePeriod
    from app.services.performance.v2_1_5_category_period_scope import (
        upsert_category_period_scope_plan,
    )
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    with app.app_context():
        existing_active = PerformancePeriod(
            title="Existing Active",
            name="Existing Active",
            period_type="monthly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            is_active=True,
        )
        db.session.add(existing_active)
        db.session.commit()
        existing_active_id = existing_active.id

        plan_result = upsert_category_period_scope_plan(
            category_key="guvenlik", start_date="2026-02-01", end_date="2026-02-28"
        )
        assert plan_result["ok"] is True
        plan_key = plan_result["plan_key"]

        # This is exactly the NEW-period branch (no PerformancePeriod row
        # exists for this plan_key yet). Before the AD reordering fix, the
        # construction-time is_active=True + immediate flush here would
        # raise IntegrityError against the just-created unique index,
        # because `existing_active` is still active at that flush point.
        result = create_or_update_period_from_plan(plan_key, activate_period=True)
        assert result["ok"] is True
        new_period_id = result["period_id"]
        assert new_period_id != existing_active_id

        active_ids = {p.id for p in PerformancePeriod.query.filter_by(is_active=True).all()}
        assert active_ids == {new_period_id}, "exactly the new period must end up active, the old one deactivated"
