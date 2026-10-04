"""EC-AUD-016B-1 contract: a complete interim-note schema is never altered.

``app.services.performance.interim_notes_runtime.ensure_interim_notes_table()``
is called by ordinary requests (mobile in-period-note GET/POST, mobile
note-scorecard, web scorecard detail/PDF, the v2 scoring workspace). Before
this slice it executed ``CREATE TABLE IF NOT EXISTS`` and two
``CREATE INDEX IF NOT EXISTS`` statements on every call, even when the table,
every column it repairs and both indexes already existed.

Scope of this contract (deliberately narrow):

* complete schema -> zero CREATE / ALTER / DROP statements, same return value;
* incomplete schema (missing table, column or index) -> the existing
  create/repair behavior is preserved, not redesigned;
* the helper's existing ``db.session.commit()`` boundary is preserved
  (characterization only: whether it should stay is a separate decision).

Every assertion is made on SQL actually executed against a disposable SQLite
file, captured with SQLAlchemy's ``before_cursor_execute`` event.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, text

TABLE = "performance_interim_notes"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "ec_aud_016b1" / "dbs"
_DDL = re.compile(r"^\s*(CREATE|ALTER|DROP)\b", re.IGNORECASE)

# Columns the helper adds when missing (its ``desired_columns``), with the
# SQLite shape its own CREATE TABLE produces.
REPAIRABLE_COLUMNS = {
    "period_id": "INTEGER",
    "employee_id": "INTEGER",
    "employee_user_id": "INTEGER",
    "manager_id": "INTEGER",
    "created_by": "INTEGER",
    "created_by_id": "INTEGER",
    "note_type": "VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem'",
    "title": "VARCHAR(255)",
    "note_title": "VARCHAR(255)",
    "note": "TEXT",
    "note_body": "TEXT",
    "note_text": "TEXT",
    "content": "TEXT",
    "description": "TEXT",
    "visibility_level": "VARCHAR(80) DEFAULT 'manager_scope'",
    "visibility_scope": "VARCHAR(80) DEFAULT 'manager_scope'",
    "remind_in_evaluation": "INTEGER DEFAULT 1",
    "remind_during_scoring": "INTEGER DEFAULT 1",
    "include_in_scorecard": "INTEGER DEFAULT 0",
    "visible_on_scorecard": "INTEGER DEFAULT 0",
    "is_active": "INTEGER DEFAULT 1",
    "active": "INTEGER DEFAULT 1",
    "occurred_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
}
INDEXES = {
    "ix_perf_interim_notes_employee_period": "employee_id, period_id",
    "ix_perf_interim_notes_employee_user_period": "employee_user_id, period_id",
}


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_path.as_posix()
    for key, value in {
        "APP_ENV": "testing", "FLASK_ENV": "testing", "SECRET_KEY": "test-secret-key-ec-aud-016b1-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "ec-aud-016b1-first-login", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false", "DATABASE_URL": uri,
        "MAIL_SUPPRESS_SEND": "true", "SCHEDULER_ENABLED": "false", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db

    with flask_app.app_context():
        # The database must be this test's own throwaway SQLite file.
        assert db.engine.url.get_backend_name() == "sqlite"
        database = db.engine.url.database
        assert database is not None
        assert Path(database).resolve().is_relative_to(_DB_ROOT.resolve())
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_path.unlink(missing_ok=True)


def _create_table(*, omit_column: str | None = None, omit_index: str | None = None) -> None:
    from app.extensions import db

    columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
    columns += [f"{name} {ddl}" for name, ddl in REPAIRABLE_COLUMNS.items() if name != omit_column]
    db.session.execute(text(f"CREATE TABLE {TABLE} ({', '.join(columns)})"))
    for name, cols in INDEXES.items():
        if name != omit_index:
            db.session.execute(text(f"CREATE INDEX {name} ON {TABLE}({cols})"))
    db.session.commit()


def _ensure_capturing_sql():
    from app.extensions import db
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join((statement or "").split()))

    event.listen(db.engine, "before_cursor_execute", _capture)
    try:
        result = ensure_interim_notes_table()
    finally:
        event.remove(db.engine, "before_cursor_execute", _capture)
    return result, statements


def _ddl(statements: list[str]) -> list[str]:
    return [s for s in statements if _DDL.match(s)]


def _assert_schema_complete() -> None:
    from app.extensions import db

    inspector = inspect(db.engine)
    assert inspector.has_table(TABLE)
    assert {"id", *REPAIRABLE_COLUMNS} <= {c["name"] for c in inspector.get_columns(TABLE)}
    assert set(INDEXES) <= {ix["name"] for ix in inspector.get_indexes(TABLE)}


@pytest.mark.parametrize("built_by", ["explicit_ddl", "helper_itself"])
def test_complete_schema_executes_no_ddl(app, built_by):
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    with app.app_context():
        if built_by == "explicit_ddl":
            _create_table()
        else:
            assert ensure_interim_notes_table() == (True, [])
        _assert_schema_complete()

        result, statements = _ensure_capturing_sql()

        assert _ddl(statements) == [], f"complete schema was altered: {_ddl(statements)}"
        assert result == (True, [])
        _assert_schema_complete()


@pytest.mark.parametrize("path", [
    "/api/mobile/performance/in-period-notes/v2",
    "/api/mobile/performance/note-scorecard",
])
def test_mobile_note_get_on_complete_schema_executes_no_ddl(app, path):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        _create_table()
        user = User(sicil_no="EC016B1", email="ec016b1@example.gov.tr", ad="Interim", soyad="Notes",
                    role="personel", is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password("EcAud016b1Test!")
        db.session.add(user)
        db.session.commit()
        headers = {"Authorization": f"Bearer {_issue_token(user)}"}
        engine = db.engine

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join((statement or "").split()))

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        response = app.test_client().get(path, headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert _ddl(statements) == [], f"GET {path} altered a complete schema: {_ddl(statements)}"
    with app.app_context():
        _assert_schema_complete()


# --- incomplete schema: existing behavior must be preserved -----------------


def test_missing_table_is_still_created(app):
    from app.extensions import db

    with app.app_context():
        assert not inspect(db.engine).has_table(TABLE)
        result, statements = _ensure_capturing_sql()

        assert any(re.match(rf"CREATE TABLE IF NOT EXISTS {TABLE}\b", s, re.I) for s in statements), statements
        assert result == (True, [])
        _assert_schema_complete()


def test_missing_repairable_column_is_still_added(app):
    from app.extensions import db

    with app.app_context():
        _create_table(omit_column="note_text")
        result, statements = _ensure_capturing_sql()

        assert f"ALTER TABLE {TABLE} ADD COLUMN note_text TEXT NULL" in statements, _ddl(statements)
        assert result == (True, [])
        assert "note_text" in {c["name"] for c in inspect(db.engine).get_columns(TABLE)}
        _assert_schema_complete()


def test_missing_index_is_still_created(app):
    with app.app_context():
        _create_table(omit_index="ix_perf_interim_notes_employee_user_period")
        result, statements = _ensure_capturing_sql()

        assert any(
            re.match(r"CREATE INDEX IF NOT EXISTS ix_perf_interim_notes_employee_user_period\b", s, re.I)
            for s in statements
        ), _ddl(statements)
        assert result == (True, [])
        _assert_schema_complete()


def test_complete_schema_keeps_the_existing_commit_boundary(app):
    """Characterization, not approval: the helper still commits pending session work."""
    from app.extensions import db
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    with app.app_context():
        _create_table()
        db.session.execute(text(
            f"INSERT INTO {TABLE} (employee_id, note_type, note) VALUES (1, 'genel_gozlem', 'pending-before-ensure')"
        ))
        assert ensure_interim_notes_table() == (True, [])
        db.session.rollback()
        persisted = db.session.execute(
            text(f"SELECT COUNT(*) FROM {TABLE} WHERE note = 'pending-before-ensure'")
        ).scalar()
    assert persisted == 1
