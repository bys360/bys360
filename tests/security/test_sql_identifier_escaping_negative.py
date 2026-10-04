"""BYS360 Test Integration Expansion Wave 1 — SQL identifier escaping security.

Exercises the REAL identifier-quoting helper (`_qident`) and the REAL
table-existence guard (`_has_table`) from
``app/routes_president_scorecard_v2.py`` against a real in-memory SQLite
database and a real SQLAlchemy session — not a regex/string search. Proves
that hostile "table name" input cannot reach raw SQL execution and that the
quoting function itself neutralizes embedded quote characters.
"""
from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text


def _make_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-sql-identifier-flows")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    # Config froze its values when config.py was first imported, possibly by
    # another test pointing at its own SQLite file; pin them so every app here
    # gets its own empty in-memory database.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch):
    flask_app = _make_app(monkeypatch)
    yield flask_app
    from app.extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


# --- SECURITY-NEGATIVE: the real _qident() escaping function ---


def test_qident_wraps_a_normal_identifier_in_double_quotes():
    from app.routes_president_scorecard_v2 import _qident

    assert _qident("users") == '"users"'


def test_qident_doubles_an_embedded_double_quote():
    from app.routes_president_scorecard_v2 import _qident

    # A naive f"\"{name}\"" would let an embedded quote close the identifier
    # early; the real function must double it per standard SQL escaping.
    assert _qident('users"; DROP TABLE users; --') == '"users""; DROP TABLE users; --"'


def test_qident_output_always_starts_and_ends_with_a_single_quote_char():
    from app.routes_president_scorecard_v2 import _qident

    for hostile in ["users", 'a"b', "a; DROP TABLE x; --", "a b", "a'b", "üniteler"]:
        quoted = _qident(hostile)
        assert quoted[0] == '"'
        assert quoted[-1] == '"'


def test_qident_keeps_semicolon_and_comment_markers_inert_inside_quotes():
    """A semicolon/comment marker embedded in the raw name must remain part
    of ONE quoted identifier string, not become executable SQL syntax."""
    from app.routes_president_scorecard_v2 import _qident

    quoted = _qident("x; DROP TABLE users; --")
    # The whole hostile payload must appear literally inside a single pair of
    # quotes with no unescaped quote character splitting it into two tokens.
    assert quoted.count('"') == 2
    assert quoted == '"x; DROP TABLE users; --"'


# --- SECURITY-NEGATIVE: the real _has_table() guard, against the real DB ---


def test_has_table_returns_true_for_a_real_table(app):
    from app.routes_president_scorecard_v2 import _has_table

    with app.app_context():
        assert _has_table("users") is True


@pytest.mark.parametrize(
    "hostile_name",
    [
        "users; DROP TABLE users; --",
        "users' OR '1'='1",
        "users\" OR \"1\"=\"1",
        "nonexistent_table_xyz",
        "",
        "users -- comment",
        "1=1",
    ],
)
def test_has_table_rejects_hostile_or_nonexistent_names(app, hostile_name):
    from app.routes_president_scorecard_v2 import _has_table

    with app.app_context():
        assert _has_table(hostile_name) is False


# --- SECURITY-NEGATIVE: end-to-end through _row(), real session, no injection ---


def test_row_with_hostile_table_name_returns_none_without_executing_sql(app, monkeypatch):
    """The real _row() helper must short-circuit on _has_table() and never
    reach db.session.execute() for a table name that doesn't exist —
    including one crafted to look like an injection attempt."""
    from app.extensions import db
    from app.routes_president_scorecard_v2 import _row

    executed = {"called": False}
    original_execute = db.session.execute

    def _tracking_execute(*args, **kwargs):
        executed["called"] = True
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(db.session, "execute", _tracking_execute)

    with app.app_context():
        result = _row("users; DROP TABLE users; --", "id = :id", {"id": 1})

    assert result is None
    assert executed["called"] is False


def test_row_against_real_table_returns_real_data(app):
    """Positive control: _row() against a genuine table and a genuine row
    actually returns the row, proving the guard doesn't just block
    everything indiscriminately."""
    from app.extensions import db
    from app.models import User
    from app.routes_president_scorecard_v2 import _row

    with app.app_context():
        user = User(
            sicil_no="70001",
            email="w1.sqlident@bys360.test",
            ad="Wave1",
            soyad="SqlIdent",
            role="personel",
            is_active=True,
        )
        user.set_password("SqlIdentTest1!")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        row = _row("users", "id = :id", {"id": user_id})

        assert row is not None
        assert row["sicil_no"] == "70001"


def test_users_table_survives_hostile_table_name_probe(app):
    """Full end-to-end proof: after probing _row() with a DROP-TABLE-shaped
    hostile table name, the real users table (and any data in it) is
    completely intact."""
    from app.extensions import db
    from app.models import User
    from app.routes_president_scorecard_v2 import _row

    with app.app_context():
        user = User(
            sicil_no="70002",
            email="w1.sqlident.survive@bys360.test",
            ad="Wave1",
            soyad="Survive",
            role="personel",
            is_active=True,
        )
        user.set_password("SurviveTest1!")
        db.session.add(user)
        db.session.commit()

        _row("users; DROP TABLE users; --", "1=1", {})
        _row("users' OR '1'='1", "1=1", {})

        remaining = db.session.query(User).filter_by(sicil_no="70002").first()
        assert remaining is not None


# --- isolation from a stale process-global Config database URI ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported. If an earlier test imported it while DATABASE_URL pointed at
# its own SQLite file, setting DATABASE_URL here came too late: this module's
# apps silently used that file and collided on users.email when run again in
# the same process.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "sql_identifier_negative_stale_config"


def test_app_does_not_inherit_a_stale_frozen_config_database_uri(monkeypatch):
    from app.extensions import db
    from config import Config

    _STALE_DB_ROOT.mkdir(parents=True, exist_ok=True)
    stale_path = _STALE_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    conn = sqlite3.connect(stale_path)
    conn.execute("CREATE TABLE stale_config_marker (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + stale_path.as_posix())

    app = _make_app(monkeypatch)
    counts = {}
    try:
        with app.app_context():
            engine_url = str(db.engine.url)
            on_stale_db = inspect(db.engine).has_table("stale_config_marker")
            counts["users"] = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        stale_path.unlink(missing_ok=True)

    assert engine_url == "sqlite:///:memory:"
    assert not on_stale_db
    assert counts == {"users": 0}
