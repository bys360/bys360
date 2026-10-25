"""Regression contract: app/services/performance/president_card_review_service.py's
_approval() query.

Two distinct, previously-conflated issues:

1. ``pa.score`` -- NOT a defect. It is a real column, actively kept in sync
   with ``pa.final_score`` by process_engine_phase7_president_rule.py's
   _ensure_approval() (see that file's own "PHASE7_SCORE_REPAIR_COMPAT"
   marker), created by migrations/versions/
   6f2b8c4d1a90_adopt_workflow_president_approval_schema.py (an active
   migration in the current head chain). An earlier, unrelated
   introspection-portability wave reported this column missing, but that
   test built its SQLite fixture with ``db.create_all()`` -- which reflects
   only the SQLAlchemy model, not migration-only columns -- and never
   exercised the real, migration-built schema. This contract builds a real
   migration-built table (not a model-only one) specifically to prove
   ``pa.score`` genuinely exists and the query's COALESCE expression was
   never wrong. It is intentionally left untouched.

2. Eight OTHER columns in the same query
   (pa.visible_status, f.current_stage, f.current_owner_name,
   f.last_action_title, f.publish_lock_status, f.publish_lock_reason,
   f.publish_lock_required_action, f.publish_allowed) genuinely do not
   exist on any real, migration-built schema -- confirmed by direct
   execution, not just static analysis. These are now read with
   column-presence gating (falling back to NULL), the same pattern this
   file already uses in _history_from_scoring_table()/_flow_steps().
   f.current_owner_name was dropped entirely (never read by any caller).

Fixture strategy: db.create_all() gives the ORM-model baseline (this is
what performance_president_approvals looks like *without* the
score-adopting migration -- i.e. AL's original, misleading fixture), then
the actual 6f2b8c4d1a90 migration's upgrade() is executed for real via a
live Alembic Operations context bound to the same connection, adding
`score` (among other real columns) exactly as it would on any properly
migrated database. This does not run the full migration chain (an
unrelated, pre-existing early migration has its own SQLite-incompatibility
bug -- out of scope here) -- only the one migration whose column contract
this test exists to prove.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_am")
_MIGRATION_FILE = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "6f2b8c4d1a90_adopt_workflow_president_approval_schema.py"
)


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-am-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-am-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_am_{uuid.uuid4().hex}.sqlite3")
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


def _run_real_score_adopting_migration(connection) -> None:
    """Execute migrations/versions/6f2b8c4d1a90_...py's real upgrade()
    against a live connection, via a genuine Alembic Operations context --
    this is real Alembic DDL execution, not a hand-written stand-in."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("_am3_migration_6f2b8c4d1a90", _MIGRATION_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ctx = MigrationContext.configure(connection)
    with Operations.context(ctx):
        module.upgrade()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
        _run_real_score_adopting_migration(db.session.connection())
        db.session.commit()
    yield flask_app


def test_score_column_genuinely_exists_on_a_real_migrated_schema(app) -> None:
    """Decisive proof that pa.score is real -- not an assumption."""
    from sqlalchemy import inspect

    from app.extensions import db

    with app.app_context():
        columns = {c["name"] for c in inspect(db.engine).get_columns("performance_president_approvals")}
        assert "score" in columns
        assert "final_score" in columns


def test_the_eight_other_columns_genuinely_do_not_exist(app) -> None:
    """Decisive proof of the real defect this contract closes."""
    from sqlalchemy import inspect

    from app.extensions import db

    with app.app_context():
        pa_columns = {c["name"] for c in inspect(db.engine).get_columns("performance_president_approvals")}
        flow_columns = {c["name"] for c in inspect(db.engine).get_columns("performance_process_flows")}
        assert "visible_status" not in pa_columns
        for missing in (
            "current_stage",
            "current_owner_name",
            "last_action_title",
            "publish_lock_status",
            "publish_lock_reason",
            "publish_lock_required_action",
            "publish_allowed",
        ):
            assert missing not in flow_columns


def test_approval_real_caller_succeeds_on_a_real_migrated_schema(app) -> None:
    """_approval() previously raised OperationalError on this exact schema
    shape (real score column present, the 8 others genuinely absent) -- it
    must now run to completion."""
    from app.services.performance.president_card_review_service import _approval

    with app.app_context():
        assert _approval(999999) is None


def test_approval_returns_final_score_from_the_real_score_column(app) -> None:
    """Proves the COALESCE expression's pa.score fallback still works
    correctly now that the column is confirmed real -- this is the
    behavior AL's flawed test would have broken had anyone "fixed" it."""
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformancePresidentApproval

    with app.app_context():
        approval = PerformancePresidentApproval(evaluation_id=3001, final_score=None, status="pending")
        db.session.add(approval)
        db.session.commit()
        # BYS360 DEFECT AM test note: pa.score is not an ORM-model field
        # (it is migration-only), so it is set with a raw UPDATE, exactly
        # matching how a real legacy row would carry a value in `score`
        # without `final_score` yet populated.
        db.session.execute(
            db.text("UPDATE performance_president_approvals SET score = :s WHERE id = :id"),
            {"s": 61.5, "id": approval.id},
        )
        db.session.commit()

        from app.services.performance.president_card_review_service import _approval

        row = _approval(approval.id)
        assert row is not None
        assert float(row["final_score"]) == 61.5


def test_approval_prefers_final_score_over_legacy_score_when_both_present(app) -> None:
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformancePresidentApproval

    with app.app_context():
        from decimal import Decimal

        approval = PerformancePresidentApproval(evaluation_id=3002, final_score=Decimal("72.00"), status="pending")
        db.session.add(approval)
        db.session.commit()
        db.session.execute(
            db.text("UPDATE performance_president_approvals SET score = :s WHERE id = :id"),
            {"s": 40.0, "id": approval.id},
        )
        db.session.commit()

        from app.services.performance.president_card_review_service import _approval

        row = _approval(approval.id)
        assert row is not None
        assert float(row["final_score"]) == 72.0


def test_approval_missing_flow_related_columns_fall_back_to_none_not_a_crash(app) -> None:
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformancePresidentApproval

    with app.app_context():
        approval = PerformancePresidentApproval(evaluation_id=3003, status="pending")
        db.session.add(approval)
        db.session.commit()

        from app.services.performance.president_card_review_service import _approval

        row = _approval(approval.id)
        assert row is not None
        assert row["current_stage"] is None
        assert row["publish_lock_status"] is None
        assert row["publish_allowed"] is None
        assert row["visible_status"] is None


def test_build_president_card_review_context_real_caller_succeeds_and_denies_unauthorized_viewer(app) -> None:
    """Cross-user/authorization regression: an unauthenticated/non-admin
    viewer must be denied before any approval row is even read."""
    from app.services.performance.president_card_review_service import (
        build_president_card_review_context,
    )

    class _AnonymousViewer:
        is_authenticated = False
        is_admin = False
        is_superuser = False

    with app.app_context():
        context = build_president_card_review_context(1, _AnonymousViewer())
        assert context["authorized"] is False
        assert context["approval"] is None


def test_build_president_card_review_context_authorized_admin_gets_no_leaked_data_for_missing_approval(app) -> None:
    from app.services.performance.president_card_review_service import (
        build_president_card_review_context,
    )

    class _AdminViewer:
        is_authenticated = True
        is_admin = True
        is_superuser = False

    with app.app_context():
        context = build_president_card_review_context(999999, _AdminViewer())
        assert context["authorized"] is True
        assert context["approval"] is None
