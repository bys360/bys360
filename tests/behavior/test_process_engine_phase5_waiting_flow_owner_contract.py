"""Regression contract: app/services/performance/process_engine_phase5_notifications.py's
_waiting_flow_rows() referenced a column, ``current_owner_user_id``, that
does not exist on performance_process_flows -- the real column (per the
model and every migration that owns this table) is ``current_owner_id``.

The same query also referenced ``current_owner_name``/``current_stage``
(never real columns anywhere) and ``flow_summary``/``last_action_title``
(real-or-not, never read by any caller) -- the first two are now read with
column-presence gating (falling back to NULL, exactly like sibling
functions in president_card_review_service.py already do for the same
class of schema drift), the last two were dropped outright since nothing
consumes them.

Mechanical reproduction of the prior defect: the raw query raised
``sqlite3.OperationalError: no such column: current_owner_user_id``
unconditionally, once an unrelated earlier fix (introspection helper
portability) let table_exists() stop crashing first and let execution
reach this query for the first time.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_am")


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


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
    yield flask_app


def _insert_flow(db, **overrides):
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    defaults = dict(
        evaluation_id=overrides.pop("evaluation_id"),
        current_status="bekliyor",
    )
    defaults.update(overrides)
    flow = PerformanceProcessFlow(**defaults)
    db.session.add(flow)
    db.session.commit()
    return flow


def test_waiting_flow_rows_real_caller_succeeds_on_sqlite(app) -> None:
    """Before the fix this raised OperationalError unconditionally; it must
    now execute successfully."""
    from app.services.performance.process_engine_phase5_notifications import (
        _waiting_flow_rows,
    )

    with app.app_context():
        assert _waiting_flow_rows() == []


def test_row_with_valid_owner_is_returned_with_correct_key(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase5_notifications import (
        _waiting_flow_rows,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=1001, current_owner_id=55, current_status="bekliyor")
        rows = _waiting_flow_rows()
        assert len(rows) == 1
        assert rows[0]["current_owner_id"] == 55
        assert "current_owner_user_id" not in rows[0]


def test_row_with_no_owner_is_excluded(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase5_notifications import (
        _waiting_flow_rows,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=1002, current_owner_id=None, current_status="bekliyor")
        assert _waiting_flow_rows() == []


def test_row_with_non_waiting_status_is_excluded(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase5_notifications import (
        _waiting_flow_rows,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=1003, current_owner_id=55, current_status="completed")
        assert _waiting_flow_rows() == []


def test_sync_phase5_notifications_real_caller_picks_up_the_correct_recipient(app) -> None:
    """sync_phase5_notifications() reads row.get("current_owner_id") as the
    notification recipient -- the query and the caller must agree on the
    same key."""
    from app.extensions import db
    from app.services.performance.process_engine_phase5_notifications import (
        sync_phase5_notifications,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=1004, current_owner_id=77, current_status="bekliyor")
        result = sync_phase5_notifications()
        assert result.process_notifications_created == 1
        assert result.skipped == 0


def test_sync_phase5_notifications_skips_rows_with_no_owner_without_crashing(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase5_notifications import (
        sync_phase5_notifications,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=1005, current_owner_id=None, current_status="bekliyor")
        result = sync_phase5_notifications()
        assert result.process_notifications_created == 0
        assert result.skipped == 0  # excluded by the WHERE clause, never reaches the skip-counter path
