"""Regression contract: app/performance/interim_notes_manager_routes.py's
_cols() hand-rolled a dialect branch (raw PostgreSQL-only
``information_schema.columns`` vs. SQLite ``PRAGMA table_info``) instead of
using SQLAlchemy's dialect-neutral ``inspect()``.

The prior implementation already worked correctly on both dialects (this was
never a crash-risk defect) -- the fix is a consolidation onto the same
``inspect()`` idiom already used by process_engine_phase4_flow.py/
phase6_president_approvals.py/phase7_president_rule.py, dropping the
duplicate branch. This contract proves the SQLite-facing behavior is
unchanged after that consolidation.
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

    from app.performance.interim_notes_manager_routes import _cols

    _cols.cache_clear()
    yield flask_app
    _cols.cache_clear()


def test_cols_returns_exact_expected_set_on_sqlite(app) -> None:
    from app.extensions import db
    from app.performance.interim_notes_manager_routes import _cols

    with app.app_context():
        db.session.execute(
            db.text("CREATE TABLE al_probe_table_interim_notes (id INTEGER PRIMARY KEY, gamma VARCHAR(10))")
        )
        db.session.commit()
        assert _cols("al_probe_table_interim_notes") == {"id", "gamma"}


def test_cols_returns_empty_set_for_missing_table_on_sqlite(app) -> None:
    from app.performance.interim_notes_manager_routes import _cols

    with app.app_context():
        assert _cols("this_table_does_not_exist_anywhere") == set()


def test_cols_covers_a_real_performance_table_on_sqlite(app) -> None:
    from app.performance.interim_notes_manager_routes import _cols

    with app.app_context():
        columns = _cols("performance_interim_notes")
        assert isinstance(columns, set)
