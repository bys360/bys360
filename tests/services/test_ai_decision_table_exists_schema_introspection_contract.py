"""Regression contract: app/services/ai_decision/development_guidance_integration.py
and app/services/ai_decision/interim_feedback_integration.py each define an
identical (copy-pasted, not shared) ``_table_exists(db_session, table_name)``
helper using a raw PostgreSQL-only ``information_schema.tables`` query
filtered by the PostgreSQL-only ``current_schema()`` SQL function.

Prior risk shape (not a crash): both wrap the query in
``except Exception: return False``, so on SQLite this fails closed rather
than raising -- but silently, permanently (per call) disables the entire
Faz 10/Faz 11 decision-support feature, exactly as documented verbatim in
tests/services/test_development_guidance_integration_recommendations_fix.py,
which monkeypatches _table_exists to work around this rather than proving it
works for real. This contract proves the real function now returns True for
an existing table on SQLite instead of unconditionally False.

Fix: both now use SQLAlchemy's ``inspect()``, dialect-neutral by
construction. Not consolidated into one shared helper module (this
codebase's own established precedent, per process_engine_phase4_flow.py/
phase6_president_approvals.py, is to fix each file's local helper
independently rather than introduce a new shared abstraction).
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


def test_development_guidance_table_exists_true_for_real_table_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.ai_decision.development_guidance_integration import _table_exists

    with app.app_context():
        assert _table_exists(db.session, "performance_evaluations") is True


def test_development_guidance_table_exists_false_for_missing_table_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.ai_decision.development_guidance_integration import _table_exists

    with app.app_context():
        assert _table_exists(db.session, "this_table_does_not_exist_anywhere") is False


def test_fetch_evaluation_summary_real_caller_succeeds_on_sqlite(app) -> None:
    """Before the fix, _table_exists() always returned False on SQLite
    (fail-closed, not a crash), so fetch_evaluation_summary() always
    short-circuited to {} even when the table exists. Proving the fix means
    proving the table-exists gate now correctly opens."""
    from app.extensions import db
    from app.services.ai_decision.development_guidance_integration import (
        _table_exists,
        fetch_evaluation_summary,
    )

    with app.app_context():
        assert _table_exists(db.session, "performance_evaluations") is True
        result = fetch_evaluation_summary(db.session, evaluation_id=999999)
        assert result == {}  # no such evaluation row -- empty, not an exception


def test_interim_feedback_table_exists_true_for_real_table_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.ai_decision.interim_feedback_integration import _table_exists

    with app.app_context():
        assert _table_exists(db.session, "performance_evaluations") is True


def test_interim_feedback_table_exists_false_for_missing_table_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.ai_decision.interim_feedback_integration import _table_exists

    with app.app_context():
        assert _table_exists(db.session, "this_table_does_not_exist_anywhere") is False


def test_fetch_interim_notes_real_caller_succeeds_on_sqlite(app) -> None:
    from app.extensions import db
    from app.services.ai_decision.interim_feedback_integration import fetch_interim_notes

    with app.app_context():
        result = fetch_interim_notes(db.session, personnel_id=999999)
        assert result == []
