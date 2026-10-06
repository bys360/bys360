"""BYS360_DEFECT_AJ_MOBILE_PERFORMANCE_NOTE_SCHEMA_DUAL_DATABASE_CONTRACT

Regression contract for Defect AJ's mobile candidate:
app/api/mobile/services/performance_note_route_services.py::
phase3c_mobile_performance_note_scorecard_v2863a_service() unconditionally
executed six ``ALTER TABLE performance_interim_notes ADD COLUMN IF NOT
EXISTS ...`` statements on every call, with no existence-check guard at
all, wrapped in a broad ``except Exception: ...log...rollback`` that
silently swallowed the resulting SQLite syntax error.

This is a real, live code path: the service function is imported and
wired into a real mobile API route via app/api/mobile/performance_routes.py
(``_phase3c_note_scorecard_v2863a_service`` / ``_phase3c_note_route_deps``).

Mechanical SQLite reproduction (real, disposable, real Flask app -- the
exact literal SQL string from the function, executed against a real
SQLite connection, performed during AJ triage):

    >>> conn.execute("ALTER TABLE performance_interim_notes "
    ...               "ADD COLUMN IF NOT EXISTS include_in_scorecard "
    ...               "BOOLEAN DEFAULT FALSE")
    sqlite3.OperationalError: near "EXISTS": syntax error

CLASSIFICATION: AJ_CONFIRMED_DEFECT.

Fix: existence is now checked first via SQLAlchemy's dialect-neutral
``inspect()``, then a plain ``ADD COLUMN`` (portable to both dialects)
runs only for columns actually missing. Column names/types/defaults are
byte-for-byte unchanged; only the existence-check mechanism changed.

This test calls the real, unmocked service function (not a copy of its
SQL), with a genuinely legacy-shaped performance_interim_notes table
(created via raw DDL lacking all six target columns) so the ADD COLUMN
path is truly exercised rather than skipped as a no-op. The primary
schema-setup call the function makes first
(_v2853_ensure_interim_notes_table, which already correctly delegates to
the dialect-safe app.services.performance.interim_notes_runtime module)
is deliberately stubbed to a no-op here, isolating exactly the function's
OWN redundant six-statement block under test -- not a mock of the
database, a mock of one unrelated collaborator so the code path under
test runs against real SQL.

G3-A (performance_interim_notes Alembic ownership, revision x1f3a9c5e7b2):
the six-column retrofit block is removed outright -- the migration provides
those columns, so this read path must no longer alter the table at all. The
same legacy-shaped table now proves the opposite contract: zero DDL, columns
unchanged, the service still answers.
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_aj_mobile")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-aj-mobile-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-aj-mobile-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_aj_mobile_{uuid.uuid4().hex}.sqlite3")
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
def app(monkeypatch: pytest.MonkeyPatch):
    flask_app = _make_app(monkeypatch)
    with flask_app.app_context():
        from sqlalchemy import event

        from app.extensions import db

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
        db.session.execute(
            db.text(
                "CREATE TABLE performance_interim_notes ("
                "id INTEGER PRIMARY KEY, period_id INTEGER, employee_id INTEGER, "
                "employee_user_id INTEGER, manager_id INTEGER, created_by INTEGER, "
                "created_by_id INTEGER, created_at DATETIME)"
            )
        )
        db.session.commit()
    yield flask_app


def _call_service(app):
    from app.api.mobile.services.performance_note_route_services import (
        phase3c_mobile_performance_note_scorecard_v2863a_service,
    )
    from app.extensions import db
    from app.models import PerformancePeriod, User

    class _FakeUser:
        id = 1

    deps = {
        "PerformancePeriod": PerformancePeriod,
        "User": User,
        "_full_name": lambda u: "Test",
        "_has_global_scope": lambda u: True,
        "_item": lambda *a, **k: {},
        "_metric": lambda *a, **k: {},
        "_mobile_perf_safe_get": lambda *a, **k: None,
        "_module_payload": lambda *a, **k: {},
        "_period_name": lambda *a, **k: "",
        "_v2853_ensure_interim_notes_table": lambda: True,
        "_v2853_note_type_label": str,
        "db": db,
        "logger": logging.getLogger("test_aj_mobile"),
    }
    return phase3c_mobile_performance_note_scorecard_v2863a_service(_FakeUser(), deps)


def _cols(db) -> set[str]:
    from sqlalchemy import inspect
    return {c["name"] for c in inspect(db.engine).get_columns("performance_interim_notes")}


def _call_service_capturing_ddl(app):
    import re

    from sqlalchemy import event

    from app.extensions import db

    ddl: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if re.match(r"^\s*(CREATE|ALTER|DROP)\b", statement or "", re.I):
            ddl.append(statement)

    event.listen(db.engine, "before_cursor_execute", _capture)
    try:
        result = _call_service(app)
    finally:
        event.remove(db.engine, "before_cursor_execute", _capture)
    return result, ddl


LEGACY_COLUMNS = {"id", "period_id", "employee_id", "employee_user_id", "manager_id", "created_by", "created_by_id", "created_at"}


def test_mobile_scorecard_service_does_not_add_missing_columns_on_sqlite(app) -> None:
    """The real, unmocked service against a legacy table missing the six columns adds none of them."""
    from app.extensions import db

    with app.app_context():
        result, ddl = _call_service_capturing_ddl(app)
        assert result == {}
        assert ddl == []
        assert _cols(db) == LEGACY_COLUMNS


def test_mobile_scorecard_service_stays_read_only_on_second_invocation(app) -> None:
    from app.extensions import db

    with app.app_context():
        _call_service_capturing_ddl(app)
        _, ddl = _call_service_capturing_ddl(app)
        assert ddl == []
        assert _cols(db) == LEGACY_COLUMNS
