"""Regression contract: app/services/performance/process_engine_phase9_publish_lock.py's
_latest_flow() referenced a column, ``president_required``, that does not
exist on performance_process_flows -- the real column (per the model and
every migration that owns this table) is ``president_approval_required``.
The output dict key stays ``president_required`` (via ``AS``), since
evaluate_publish_lock() reads that exact key -- only the underlying column
reference changed, not the caller-visible contract.

``current_stage`` was dropped from the SELECT: it is not a real column and
is never read by any caller in this module.

Also closes a second, related defect discovered while proving this one:
_latest_approval() (called by evaluate_publish_lock() right after
_latest_flow()) referenced ``decision_status``/``visible_status``, neither
of which is a real column on performance_president_approvals -- the
COALESCE already listed the real column (``status``) first, so the two
non-existent identifiers were simply dropped. That same function also
reads ``pa.score``, which -- like the sibling contract in
test_president_card_review_score_and_column_contract.py explains in
detail -- is a real, migration-only column (added by migrations/versions/
6f2b8c4d1a90_adopt_workflow_president_approval_schema.py), not present on
a plain ``db.create_all()`` fixture. Tests that exercise
evaluate_publish_lock() end-to-end therefore run the same migration for
real, exactly like that sibling contract does.

Mechanical reproduction of the prior defect: the raw query raised
``sqlite3.OperationalError: no such column: president_required``
unconditionally, once an unrelated earlier fix (introspection helper
portability) let table_exists() stop crashing first and let execution
reach this query for the first time.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_am")
_MIGRATION_FILE = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "6f2b8c4d1a90_adopt_workflow_president_approval_schema.py"
)


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-am-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-am-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_am_{uuid.uuid4().hex}.sqlite3")
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


def _run_real_score_adopting_migration(connection) -> None:
    """Execute migrations/versions/6f2b8c4d1a90_...py's real upgrade()
    against a live connection, via a genuine Alembic Operations context, so
    performance_president_approvals gets its real, migration-only ``score``
    column (see the module docstring)."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("_am_migration_6f2b8c4d1a90", _MIGRATION_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ctx = MigrationContext.configure(connection)
    with Operations.context(ctx):
        module.upgrade()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
        _run_real_score_adopting_migration(db.session.connection())
        db.session.commit()
    yield flask_app


def _insert_flow(db, **overrides):
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    flow = PerformanceProcessFlow(**overrides)
    db.session.add(flow)
    db.session.commit()
    return flow


def test_latest_flow_real_caller_succeeds_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase9_publish_lock import _latest_flow

    with app.app_context():
        assert _latest_flow(999999) is None


def test_latest_flow_output_key_is_president_required_when_true(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase9_publish_lock import _latest_flow

    with app.app_context():
        _insert_flow(
            db,
            evaluation_id=2001,
            president_approval_required=True,
            final_score=Decimal("65.00"),
        )
        flow = _latest_flow(2001)
        assert flow is not None
        # BYS360 test note: a raw text() query returns SQLite's native 0/1
        # for a boolean column, not a Python bool -- evaluate_publish_lock()
        # already wraps this in bool(), so a truthy check is the correct
        # contract to assert, not identity to the True singleton.
        assert bool(flow["president_required"]) is True


def test_latest_flow_output_key_is_president_required_when_false(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase9_publish_lock import _latest_flow

    with app.app_context():
        _insert_flow(
            db,
            evaluation_id=2002,
            president_approval_required=False,
            final_score=Decimal("85.00"),
        )
        flow = _latest_flow(2002)
        assert flow is not None
        assert bool(flow["president_required"]) is False


def test_latest_flow_isolates_by_evaluation_id(app) -> None:
    """performance_process_flows.evaluation_id is unique (one flow per
    evaluation), so "latest among duplicates" cannot occur -- this proves
    the WHERE clause correctly isolates one evaluation's flow from another's
    instead."""
    from app.extensions import db
    from app.services.performance.process_engine_phase9_publish_lock import _latest_flow

    with app.app_context():
        _insert_flow(db, evaluation_id=2003, president_approval_required=False)
        other = _insert_flow(db, evaluation_id=2103, president_approval_required=True)
        flow = _latest_flow(2103)
        assert flow is not None
        assert flow["id"] == other.id
        assert bool(flow["president_required"]) is True


def test_evaluate_publish_lock_real_caller_succeeds_and_blocks_when_required(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase9_publish_lock import (
        evaluate_publish_lock,
    )

    with app.app_context():
        _insert_flow(
            db,
            evaluation_id=2004,
            president_approval_required=True,
            final_score=Decimal("60.00"),
        )
        result = evaluate_publish_lock(2004)
        assert result.publish_allowed is False
        assert result.lock_status == "blocked_president_pending"


def test_evaluate_publish_lock_allows_when_not_required(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase9_publish_lock import (
        evaluate_publish_lock,
    )

    with app.app_context():
        _insert_flow(
            db,
            evaluation_id=2005,
            president_approval_required=False,
            final_score=Decimal("90.00"),
        )
        result = evaluate_publish_lock(2005)
        assert result.publish_allowed is True
