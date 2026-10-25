"""Regression contract: raw PostgreSQL-only schema-introspection helpers in
app/services/performance/president_card_review_service.py and
app/performance/president_low_score_card_routes.py replaced with
SQLAlchemy's dialect-neutral inspect().

Call graph traced before fixing:
- president_card_review_service.table_exists()/table_columns() gate
  _approval(), _history_from_scoring_table(), _items_summary(), _flow_steps(),
  and _criteria_scorecard(), all reached from build_president_card_review_context(),
  which is called by performance_president_card_review() at the live,
  unshadowed route /performance/president-approvals/<id>/card.
- president_low_score_card_routes._table_exists()/_columns() gate
  _display_name()/_fetch_approvals()/_fetch_history(), reached from
  president_low_score_approvals_center() and president_low_score_report_card().
  Both routes are shadowed at the Flask URL-map level by
  process_engine_phase6_president_approvals_routes.py's winning handlers
  (see tests/quality/test_route_conflict_runtime_contract.py's
  KNOWN_CONFLICTS), so this module's raw-SQL functions are not reachable via
  HTTP today -- fixed anyway for defense-in-depth and consistency, since the
  functions themselves are real, importable, exported code.

Mechanical SQLite reproduction of the prior behavior: raw
``information_schema.tables``/``information_schema.columns`` queries raise
``sqlite3.OperationalError`` unconditionally on SQLite. Fix: both modules now
use SQLAlchemy's ``inspect()``. Each function's missing-table/missing-column
contract (False / empty set, never an exception) is preserved exactly.

NEW_SEPARATE_TECHNICAL_FINDING surfaced while proving the fix (not fixed
here -- outside this defect's scope, a pre-existing business-query bug
unrelated to schema introspection, previously unreachable only because the
introspection crash always happened first): president_card_review_service.
_approval()'s raw SELECT hardcodes a column ``pa.score`` on
performance_president_approvals that does not exist on the real table. This
does not block proving the introspection fix itself: table_exists() and
table_columns() are exercised and proven directly below.
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


# --- president_card_review_service -------------------------------------------------------


def test_card_review_table_exists_true_and_false_on_sqlite(app) -> None:
    from app.services.performance.president_card_review_service import table_exists

    with app.app_context():
        assert table_exists("performance_president_approvals") is True
        assert table_exists("this_table_does_not_exist_anywhere") is False


def test_card_review_table_columns_returns_exact_expected_set_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.performance.president_card_review_service import table_columns

    with app.app_context():
        db.session.execute(
            db.text("CREATE TABLE al_probe_table_card_review (id INTEGER PRIMARY KEY, alpha VARCHAR(10))")
        )
        db.session.commit()
        assert table_columns("al_probe_table_card_review") == {"id", "alpha"}


def test_card_review_table_columns_returns_empty_set_for_missing_table_on_sqlite(app) -> None:
    from app.services.performance.president_card_review_service import table_columns

    with app.app_context():
        assert table_columns("this_table_does_not_exist_anywhere") == set()


def test_table_exists_and_table_columns_unblock_the_real_caller_path(app) -> None:
    """build_president_card_review_context() previously raised
    OperationalError on SQLite at the table_exists()/table_columns()
    introspection stage, before ever reaching its own SELECT. That
    introspection-stage crash is now closed -- table_exists() correctly
    resolves the real table, matching what _approval() checks first.
    NEW_SEPARATE_TECHNICAL_FINDING (not fixed here, outside this defect's
    scope): _approval()'s raw SELECT hardcodes a column ``pa.score`` on
    performance_president_approvals that does not exist on the real table --
    a pre-existing business-query bug, unrelated to schema introspection,
    that was previously unreachable because the introspection crash always
    happened first."""
    from app.services.performance.president_card_review_service import (
        table_columns,
        table_exists,
    )

    with app.app_context():
        assert table_exists("performance_president_approvals") is True
        assert "id" in table_columns("performance_president_approvals")


# --- president_low_score_card_routes ------------------------------------------------------


def test_low_score_card_table_exists_true_and_false_on_sqlite(app) -> None:
    from app.performance.president_low_score_card_routes import _table_exists

    with app.app_context():
        assert _table_exists("performance_president_approvals") is True
        assert _table_exists("this_table_does_not_exist_anywhere") is False


def test_low_score_card_columns_returns_exact_expected_set_on_sqlite(app) -> None:
    from app.extensions import db
    from app.performance.president_low_score_card_routes import _columns

    with app.app_context():
        db.session.execute(
            db.text("CREATE TABLE al_probe_table_low_score (id INTEGER PRIMARY KEY, beta VARCHAR(10))")
        )
        db.session.commit()
        assert _columns("al_probe_table_low_score") == {"id", "beta"}


def test_low_score_card_columns_returns_empty_set_for_missing_table_on_sqlite(app) -> None:
    from app.performance.president_low_score_card_routes import _columns

    with app.app_context():
        assert _columns("this_table_does_not_exist_anywhere") == set()


def test_fetch_approvals_real_caller_succeeds_on_sqlite(app) -> None:
    """_fetch_approvals() previously raised OperationalError on SQLite via
    _table_exists()/_columns(); the real, unmocked caller must now run to
    completion (even though this module's own HTTP routes are shadowed by
    process_engine_phase6_president_approvals_routes.py, the functions
    themselves are real, importable, exported code)."""
    from app.performance.president_low_score_card_routes import _fetch_approvals

    with app.app_context():
        assert _fetch_approvals() == []
