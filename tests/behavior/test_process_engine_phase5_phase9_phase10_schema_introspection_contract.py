"""Regression contract: raw PostgreSQL-only schema-introspection helpers in
app/services/performance/process_engine_phase5_notifications.py,
process_engine_phase9_publish_lock.py, and process_engine_phase10_reports.py
replaced with SQLAlchemy's dialect-neutral inspect().

Call graph traced before fixing: phase5_notifications.table_exists()/
column_exists()/_table_columns() gate _application_notification_exists(),
_mirror_to_application_notifications(), _waiting_flow_rows(), and
_president_waiting_rows(), all reached from sync_phase5_notifications();
phase9_publish_lock._table_exists()/_column_exists() gate _latest_approval()
and _latest_flow(), reached from evaluate_publish_lock() and
synchronize_publish_locks(); phase10_reports._table_exists() (previously a
raw ``to_regclass`` catalog lookup) and _columns() gate _fetch_rows(),
reached from build_phase10_report_context().

Mechanical SQLite reproduction of the prior behavior (real, disposable, real
Flask app + real SQLite): the raw ``information_schema.tables``/
``information_schema.columns``/``to_regclass`` queries all raise
``sqlite3.OperationalError`` unconditionally, since SQLite has none of
these. Fix: every helper now uses SQLAlchemy's ``inspect()``, dialect-neutral
by construction, matching the same proven pattern already used in
process_engine_phase4_flow.py/phase6_president_approvals.py/
phase7_president_rule.py. Each function's missing-table/missing-column
contract (False / empty set, never an exception) is preserved exactly.

NEW_SEPARATE_TECHNICAL_FINDINGs surfaced while proving the fix (not fixed
here -- outside this defect's scope, pre-existing business-query bugs
unrelated to schema introspection, previously unreachable only because the
introspection crash always happened first):
- phase5_notifications._waiting_flow_rows()'s raw SELECT hardcodes column
  name ``current_owner_user_id``, which does not exist on the real
  performance_process_flows table (this same file's own
  ``_PHASE5_REQUIRED_SCHEMA`` lists the real column as ``current_owner_id``).
- phase9_publish_lock._latest_flow()'s raw SELECT hardcodes column name
  ``president_required``, which does not exist on the real table (the real
  column is ``president_approval_required``, per the phase5 file's own
  schema map).
These do not block proving the introspection fix itself: table_exists()/
column_exists()/_table_columns() are exercised and proven directly below.
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


# --- process_engine_phase5_notifications ------------------------------------------------


def test_phase5_table_exists_true_for_a_real_table_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase5_notifications import table_exists

    with app.app_context():
        assert table_exists("performance_process_flows") is True


def test_phase5_table_exists_false_for_a_missing_table_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase5_notifications import table_exists

    with app.app_context():
        assert table_exists("this_table_does_not_exist_anywhere") is False


def test_phase5_column_exists_true_and_false_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase5_notifications import column_exists

    with app.app_context():
        assert column_exists("performance_process_flows", "id") is True
        assert column_exists("performance_process_flows", "this_column_does_not_exist") is False
        assert column_exists("this_table_does_not_exist_anywhere", "id") is False


# --- process_engine_phase9_publish_lock -------------------------------------------------


def test_phase9_table_exists_true_and_false_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase9_publish_lock import _table_exists

    with app.app_context():
        assert _table_exists("performance_process_flows") is True
        assert _table_exists("this_table_does_not_exist_anywhere") is False


def test_phase9_column_exists_true_and_false_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase9_publish_lock import _column_exists

    with app.app_context():
        assert _column_exists("performance_process_flows", "id") is True
        assert _column_exists("performance_process_flows", "this_column_does_not_exist") is False


# --- process_engine_phase10_reports ------------------------------------------------------


def test_phase10_table_exists_true_and_false_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase10_reports import _table_exists

    with app.app_context():
        assert _table_exists("performance_process_flows") is True
        assert _table_exists("this_table_does_not_exist_anywhere") is False


def test_phase10_columns_returns_exact_expected_set_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase10_reports import _columns

    with app.app_context():
        db.session.execute(
            db.text("CREATE TABLE al_probe_table_phase10 (id INTEGER PRIMARY KEY, alpha VARCHAR(10))")
        )
        db.session.commit()
        assert _columns("al_probe_table_phase10") == {"id", "alpha"}


def test_phase10_columns_returns_empty_set_for_a_missing_table_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase10_reports import _columns

    with app.app_context():
        assert _columns("this_table_does_not_exist_anywhere") == set()


def test_phase10_build_report_context_real_caller_succeeds_on_sqlite(app) -> None:
    """build_phase10_report_context() previously raised OperationalError on
    SQLite via the raw to_regclass()/information_schema calls; it must now
    return an empty-but-valid report shape."""
    from app.services.performance.process_engine_phase10_reports import (
        build_phase10_report_context,
    )

    with app.app_context():
        context = build_phase10_report_context()
        assert context["summary"]["total"] == 0
        assert context["rows"] == []
