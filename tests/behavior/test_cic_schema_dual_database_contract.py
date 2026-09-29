"""BYS360_DEFECT_AJ_CIC_SCHEMA_DUAL_DATABASE_CONTRACT

History: Defect AJ proved that the CIC helpers'
``ADD COLUMN IF NOT EXISTS`` ALTERs failed silently on SQLite. Schema wave 1
removed request-time schema mutation instead: the users celebration columns
(birth_date, hire_date, celebration_opt_out) are owned by Alembic revision
w1c5a7d2e9b4, and both helpers now only verify them.

  - app/services/cic/celebration_service.py::ensure_celebration_schema()
    reports missing columns (ok=False, migration warning), never alters.
  - app/services/cic/cic_context.py::_cic_v45_ensure_schema()
    raises RuntimeSchemaMissing (controlled 503 on a request), never alters.

The legacy fixture replaces the model-driven ``users`` table with one that
lacks the three columns (raw DDL, NOT db.create_all(), which would create
them), so the missing-column path is genuinely exercised on SQLite.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_aj_cic")
CELEBRATION_COLUMNS = {"birth_date", "hire_date", "celebration_opt_out"}


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-aj-cic-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-aj-cic-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_aj_cic_{uuid.uuid4().hex}.sqlite3")
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
        from app.extensions import db

        db.create_all()
    yield flask_app


@pytest.fixture
def legacy_app(monkeypatch: pytest.MonkeyPatch):
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
        # Replace the model-driven 'users' table with a legacy-shaped one
        # lacking birth_date/hire_date/celebration_opt_out entirely.
        db.session.execute(db.text("DROP TABLE users"))
        db.session.execute(db.text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255))"))
        db.session.commit()
    yield flask_app


def _cols(db, table_name: str) -> set[str]:
    from sqlalchemy import inspect
    return {c["name"] for c in inspect(db.engine).get_columns(table_name)}


def _no_ddl_listener(db, statements: list[str]):
    from sqlalchemy import event

    @event.listens_for(db.engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().upper().startswith(("ALTER", "CREATE", "DROP")):
            statements.append(statement)

    return _capture


def test_celebration_service_reports_missing_columns_without_altering(legacy_app) -> None:
    from sqlalchemy import event

    from app.extensions import db
    from app.services.cic.celebration_service import ensure_celebration_schema

    with legacy_app.app_context():
        ddl: list[str] = []
        listener = _no_ddl_listener(db, ddl)
        try:
            result = ensure_celebration_schema()
        finally:
            event.remove(db.engine, "before_cursor_execute", listener)
        assert result["ok"] is False
        assert result["added"] == []
        assert all(f"users.{c}" in result["warnings"][0] for c in CELEBRATION_COLUMNS)
        assert ddl == []
        assert not CELEBRATION_COLUMNS & _cols(db, "users")


def test_cic_context_ensure_schema_fails_closed_without_altering(legacy_app) -> None:
    from app.extensions import db
    from app.services.cic.cic_context import _cic_v45_ensure_schema
    from app.services.runtime_schema import RuntimeSchemaMissing

    with legacy_app.app_context():
        with pytest.raises(RuntimeSchemaMissing) as excinfo:
            _cic_v45_ensure_schema()
        assert set(excinfo.value.missing) == {f"users.{c}" for c in CELEBRATION_COLUMNS}
        assert not CELEBRATION_COLUMNS & _cols(db, "users")


def test_both_helpers_accept_a_complete_users_table_repeatedly(app) -> None:
    from app.services.cic.celebration_service import ensure_celebration_schema
    from app.services.cic.cic_context import _cic_v45_ensure_schema

    with app.app_context():
        for _ in range(2):
            assert ensure_celebration_schema() == {"ok": True, "added": [], "warnings": []}
            _cic_v45_ensure_schema()
