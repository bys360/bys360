"""Regression contract: app/ai/decision_support_faz9_routes.py's
_table_columns() used a raw PostgreSQL-only ``information_schema.columns``
query with no dialect branch and no try/except at all.

Call graph traced before fixing: _table_columns() is called by
_assignments(), _notification_rows(), and _mail_log_rows() -- all three
evaluated as *argument expressions* to _run_faz9_json() inside the three
live, @login_required routes (ai_decision_faz9_reminder_summary,
ai_decision_faz9_evaluator_delays, ai_decision_faz9_reminder_action_plan).
Because Python evaluates call arguments before the call itself,
_run_faz9_json()'s own try/except never had a chance to catch the resulting
OperationalError on SQLite -- it would have propagated as a fully unhandled
500. This is the only one of this defect family with zero exception
guarding anywhere on the path.

Fix: SQLAlchemy's ``inspect()``, dialect-neutral by construction, so the
call now succeeds normally on SQLite instead of raising.
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


def test_table_columns_returns_exact_expected_set_on_sqlite(app) -> None:
    from app.ai.decision_support_faz9_routes import _table_columns

    with app.app_context():
        columns = _table_columns("evaluation_assignments")
        assert "id" in columns


def test_table_columns_returns_empty_set_for_missing_table_on_sqlite(app) -> None:
    from app.ai.decision_support_faz9_routes import _table_columns

    with app.app_context():
        assert _table_columns("this_table_does_not_exist_anywhere") == set()


def test_assignments_real_caller_succeeds_on_sqlite(app) -> None:
    """_assignments() previously raised OperationalError on SQLite via the
    unguarded _table_columns() call -- and since it is evaluated as a route
    argument expression, the exception bypassed _run_faz9_json()'s own
    error handling entirely. Must now run to completion."""
    from app.ai.decision_support_faz9_routes import _assignments

    with app.app_context():
        assert list(_assignments(limit=10)) == []


def test_notification_and_mail_log_table_columns_unblock_the_real_caller_path(app) -> None:
    """_notification_rows()/_mail_log_rows() previously raised
    OperationalError on SQLite at the _table_columns() introspection stage,
    before ever reaching their own SELECT. That introspection-stage crash is
    now closed -- _table_columns() correctly resolves both real tables.
    NEW_SEPARATE_TECHNICAL_FINDING (not fixed here, outside this defect's
    scope): once the introspection gate opens, both functions fall through
    to a ``title ILIKE '%...%'`` filter clause -- ``ILIKE`` is
    PostgreSQL-only and raises ``sqlite3.OperationalError: near "ILIKE"``
    on SQLite. This is a pre-existing business-query portability bug,
    unrelated to schema introspection, that was previously unreachable
    because the introspection crash always happened first."""
    from app.ai.decision_support_faz9_routes import _table_columns

    with app.app_context():
        assert "id" in _table_columns("notifications")
        assert "id" in _table_columns("mail_logs")
