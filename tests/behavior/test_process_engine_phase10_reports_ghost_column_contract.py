"""Regression contract: app/performance/process_engine_phase10_reports_routes.py's
_bys360_process_reports_advanced_context() referenced columns that no
migration and no reachable runtime schema path ever creates, plus
PostgreSQL-only ``CONCAT_WS()``/``::numeric`` syntax with no SQLite
equivalent -- confirmed against a real, migration-built database. Because
every query is wrapped in a broad try/except that returns an empty result
on any error, the live /performance/process-reports route never crashed --
it silently rendered an empty, all-zero report page even when real process
data existed. That silent-failure shape is exactly what makes this defect
easy to miss: it looks like "no data" rather than "broken query".

current_owner_user_id/president_required map to their real, canonical
equivalents (current_owner_id/president_approval_required). CONCAT_WS() is
replaced with the ANSI-portable ``||`` operator; the PostgreSQL-only
``::numeric`` cast is dropped (unnecessary on either dialect). Every other
ghost field degrades to a safe neutral value, the same way the sibling
Phase6/Phase8 contracts in this same wave do.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_an")
# These contracts check column/SQL shape, not authorization: use an
# institution-wide viewer (P0-01 made an unresolved viewer fail closed).
_ADMIN_VIEWER = SimpleNamespace(id=1, role="admin", unvan="")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-an-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-an-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_an_{uuid.uuid4().hex}.sqlite3")
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
        db.session.commit()
    yield flask_app


def _insert_flow(db, **overrides):
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    row = PerformanceProcessFlow(**overrides)
    db.session.add(row)
    db.session.commit()
    return row


def _insert_user(db, **overrides):
    from app.models.core_models import User

    defaults = {
        "sicil_no": f"AN-{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "test-hash",
        "ad": "Test",
        "soyad": "Kullanici",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db.session.add(user)
    db.session.commit()
    return user


def test_context_real_caller_succeeds_when_no_flows_exist(app) -> None:
    from app.performance.process_engine_phase10_reports_routes import (
        _bys360_process_reports_advanced_context,
    )

    with app.app_context():
        context = _bys360_process_reports_advanced_context(viewer=_ADMIN_VIEWER, status_filter="")
        assert context["summary"]["total"] == 0
        assert context["recent_rows"] == []


def test_context_real_caller_returns_real_counts_instead_of_silent_empty(app) -> None:
    """Before the fix, this always returned an all-zero/empty context (the
    query itself failed and was swallowed) even with real flow rows
    present. It must now return the real, correct counts."""
    from app.extensions import db
    from app.performance.process_engine_phase10_reports_routes import (
        _bys360_process_reports_advanced_context,
    )

    with app.app_context():
        _insert_flow(
            db,
            evaluation_id=10001,
            current_owner_id=1,
            current_status="bekliyor",
            is_finalized=False,
            president_approval_required=True,
            final_score=Decimal("58.00"),
        )
        _insert_flow(
            db,
            evaluation_id=10002,
            current_owner_id=1,
            current_status="tamamlandi",
            is_finalized=True,
            final_score=Decimal("92.00"),
        )
        context = _bys360_process_reports_advanced_context(viewer=_ADMIN_VIEWER, status_filter="")
        assert context["summary"]["total"] == 2
        assert context["summary"]["finalized"] == 1
        assert context["summary"]["president_required"] == 1
        assert len(context["recent_rows"]) == 2


def test_context_owner_rows_group_by_real_owner_name(app) -> None:
    """Exercises the CONCAT_WS-replacement expression -- must not raise
    ``near \"::\": syntax error`` (the dropped PostgreSQL cast) or
    ``no such function: concat_ws`` (the old PostgreSQL-only call)."""
    from app.extensions import db
    from app.performance.process_engine_phase10_reports_routes import (
        _bys360_process_reports_advanced_context,
    )

    with app.app_context():
        owner = _insert_user(db, ad="Ayşe", soyad="Yılmaz")
        _insert_flow(db, evaluation_id=10003, current_owner_id=owner.id, current_status="bekliyor")
        context = _bys360_process_reports_advanced_context(viewer=_ADMIN_VIEWER, status_filter="")
        assert len(context["owner_rows"]) == 1
        assert "Ayşe" in context["owner_rows"][0]["owner_name"]


def test_context_president_status_filter_executes_without_crashing(app) -> None:
    from app.extensions import db
    from app.performance.process_engine_phase10_reports_routes import (
        _bys360_process_reports_advanced_context,
    )

    with app.app_context():
        _insert_flow(db, evaluation_id=10004, president_approval_required=True, final_score=Decimal("40.00"))
        context = _bys360_process_reports_advanced_context(viewer=_ADMIN_VIEWER, status_filter="president")
        assert len(context["president_rows"]) == 1
