"""Regression contract: app/services/performance_v2/reporting_workspace.py's
_get_process_flow_columns() used a raw PostgreSQL-only
``information_schema.columns`` query filtered by the PostgreSQL-only
``current_schemas(false)`` search-path function.

Call graph traced before fixing: _get_process_flow_columns() gates
_load_latest_process_flow(), reached from build_publish_workspace_context()
(re-exported via app/services/performance_v2/__init__.py and imported by
app/services/ui_context/dashboard.py, app/services/performance/
go_live_service.py, and app/services/performance/ops_center.py -- genuinely
production-reachable dashboard/ops-center code).

Prior risk shape (different from a crash): the whole query was wrapped in
``try/except Exception: ... _FLOW_STATUS_COLUMN_CACHE = set()``, so on
SQLite this did not raise -- it silently degraded, caching an empty set at
module scope for the remaining life of the worker process, permanently
disabling process-flow status enrichment. Fix: SQLAlchemy's ``inspect()``,
dialect-neutral by construction, so the real column set is now returned (and
cached) instead of an empty one.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_al")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-al-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-al-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_al_{uuid.uuid4().hex}.sqlite3")
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

    import app.services.performance_v2.reporting_workspace as reporting_workspace_module

    reporting_workspace_module._FLOW_STATUS_COLUMN_CACHE = None
    yield flask_app
    reporting_workspace_module._FLOW_STATUS_COLUMN_CACHE = None


def test_get_process_flow_columns_returns_real_columns_not_empty_set_on_sqlite(app) -> None:
    """Before the fix, this returned an empty set on SQLite every time
    (caught exception, cached forever) -- proving the silent-degradation
    defect is closed means the real column set now comes back."""
    from app.services.performance_v2.reporting_workspace import (
        _get_process_flow_columns,
    )

    with app.app_context():
        columns = _get_process_flow_columns()
        assert "id" in columns
        assert "evaluation_id" in columns
        assert columns != set()


def test_get_process_flow_columns_is_cached_across_calls(app) -> None:
    from app.services.performance_v2.reporting_workspace import (
        _get_process_flow_columns,
    )

    with app.app_context():
        first = _get_process_flow_columns()
        second = _get_process_flow_columns()
        assert first == second
        assert first is second  # same cached object, not recomputed


def test_load_latest_process_flow_real_caller_succeeds_on_sqlite(app) -> None:
    """_load_latest_process_flow() must no longer be permanently disabled on
    SQLite -- it should return None for a non-existent evaluation without
    raising, and without depending on a poisoned empty-column cache."""
    from app.services.performance_v2.reporting_workspace import (
        _load_latest_process_flow,
    )

    with app.app_context():
        result = _load_latest_process_flow(999999)
        assert result is None
