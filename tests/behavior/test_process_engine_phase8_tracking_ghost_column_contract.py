"""Regression contract: app/services/performance/process_engine_phase8_tracking.py's
live Süreç Takibi (Process Tracking) call path referenced columns that no
migration and no reachable runtime schema path ever creates -- confirmed
against a real, migration-built database. Every request to
/performance/process-tracking raised OperationalError.

The prior test suite's own fixture manually ran raw ``ALTER TABLE``
statements to manufacture these columns on its ``db.create_all()``-only
test database -- a shape production never produces -- which is why those
tests passed despite the real defect. This contract deliberately does NOT
patch the schema that way, so it proves the real, unmodified functions
against the real, model/migration-backed schema.

current_owner_user_id/president_required are mapped to their real,
canonical equivalents (current_owner_id/president_approval_required).
Every other tracking-specific field (waiting_days, is_overdue,
tracking_bucket, tracking_priority, tracking_label, last_action_title,
current_owner_name, ...) has no real column under any name today; these
now degrade to a safe neutral value (0 / False / generic label) instead of
raising. Restoring real tracking data for those fields needs a genuine
schema migration -- a separate, larger item, not attempted here.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_an")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-an-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-an-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_an_{uuid.uuid4().hex}.sqlite3")
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
        from app.extensions import db

        db.create_all()
        db.session.commit()
    yield flask_app


class _Admin:
    id = 1
    is_admin = True
    is_superuser = False
    role = "admin"
    unvan = None


def _insert_flow(db, **overrides):
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    row = PerformanceProcessFlow(**overrides)
    db.session.add(row)
    db.session.commit()
    return row


def test_flow_base_rows_real_caller_succeeds_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase8_tracking import _flow_base_rows

    with app.app_context():
        assert _flow_base_rows(viewer=_Admin(), status_filter="all", search="") == []


def test_flow_base_rows_returns_real_owner_id_not_a_crash(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase8_tracking import _flow_base_rows

    with app.app_context():
        _insert_flow(db, evaluation_id=8001, current_owner_id=42, current_status="bekliyor")
        rows = _flow_base_rows(viewer=_Admin(), status_filter="all", search="")
        assert len(rows) == 1
        assert rows[0]["current_owner_id"] == 42


def test_flow_base_rows_status_filters_execute_without_crashing(app) -> None:
    """These filters build WHERE fragments referencing the same ghost
    columns -- each branch must be exercised directly, not just the
    default 'all' case."""
    from app.services.performance.process_engine_phase8_tracking import _flow_base_rows

    with app.app_context():
        for status_filter in ("waiting", "president", "overdue", "completed", "returned"):
            assert _flow_base_rows(viewer=_Admin(), status_filter=status_filter, search="") == []


def test_flow_base_rows_search_executes_without_crashing(app) -> None:
    from app.services.performance.process_engine_phase8_tracking import _flow_base_rows

    with app.app_context():
        assert _flow_base_rows(viewer=_Admin(), status_filter="all", search="performans") == []


def test_build_process_tracking_workspace_real_caller_succeeds_with_real_data(app) -> None:
    """Before the fix, this raised OperationalError on every request; it
    must now run to completion and show a real flow with safe defaults for
    the fields that have no real column under any name today."""
    from app.extensions import db
    from app.services.performance.process_engine_phase8_tracking import (
        build_process_tracking_workspace,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=8002, current_owner_id=42, current_status="bekliyor")
        context = build_process_tracking_workspace(_Admin(), status_filter="all", search="")
        assert context["counts"]["total"] == 1
        item = context["items"][0]
        assert item["waiting_days"] == 0
        assert item["is_overdue"] is False
        assert item["owner_user_id"] == 42


def test_synchronize_phase8_tracking_real_caller_succeeds_without_writing_ghost_columns(app) -> None:
    """Before the AN fix, both the SELECT and the UPDATE inside this
    function raised OperationalError. AO's own field-by-field schema
    investigation then established that none of the tracking_*/is_overdue/
    overdue_days values need a persisted column at all -- every one is
    safely derivable at read time (see build_process_tracking_workspace()
    and its own real-data tests). This function now only verifies the
    flows are present and readable; it writes nothing, so flows_updated
    is always 0."""
    from app.extensions import db
    from app.services.performance.process_engine_phase8_tracking import (
        synchronize_phase8_tracking,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=8003, current_owner_id=42, current_status="bekliyor")
        result = synchronize_phase8_tracking()
        assert result.flows_checked == 1
        assert result.flows_updated == 0
