"""Regression contract: app/performance/process_engine_phase10_reports_routes.py's
_bys360_process_reports_advanced_context()'s nested _table_exists() closure
hand-rolled a dialect branch (SQLite ``sqlite_master`` vs. raw
PostgreSQL-only ``information_schema``/``current_schema()``) instead of using
SQLAlchemy's dialect-neutral ``inspect()``.

The prior implementation already worked correctly on both dialects (this was
never a crash-risk defect, and was already covered by a real try/except
fallback) -- the fix is a consolidation onto the ``inspect()`` idiom. The
existing smoke test
(tests/performance/test_critical_performance_routes_smoke.py::
test_process_reports_no_500) monkeypatches this entire context builder away,
so it never actually exercised the real dialect-branching code; this
contract exercises the real, unmocked function directly against SQLite.
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
    yield flask_app


def test_context_builder_real_unmocked_call_succeeds_when_table_missing(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """No performance_process_flows table at all -- table_exists() must
    return False without raising, and the function returns the documented
    empty-context shape."""
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    with flask_app.app_context():
        from app.performance.process_engine_phase10_reports_routes import (
            _bys360_process_reports_advanced_context,
        )

        context = _bys360_process_reports_advanced_context(viewer=None, status_filter="")
        assert context["summary"] == {}
        assert context["recent_rows"] == []


def test_context_builder_real_unmocked_call_succeeds_when_table_present(app) -> None:
    """Real table present, empty rows -- table_exists() must return True and
    the query pipeline must run to completion on SQLite."""
    with app.app_context():
        from app.performance.process_engine_phase10_reports_routes import (
            _bys360_process_reports_advanced_context,
        )

        context = _bys360_process_reports_advanced_context(viewer=None, status_filter="")
        assert context["summary"]["total"] == 0
        assert context["recent_rows"] == []
