"""Regression contract: app/services/performance/process_engine_phase6_president_approvals.py's
live Başkan Onayları (President Approvals) call path referenced columns
that no migration and no reachable runtime schema path ever creates --
confirmed against a real, migration-built database. Every request to
/performans/baskan-onaylari raised OperationalError, and every
approve/return decision silently failed.

Four distinct queries are covered:
- _approval_base_rows() (the SELECT feeding the list/summary screen), plus
  its own _status_filter_sql() WHERE fragment
- decide_president_approval()'s UPDATE (the approve/return action)
- _flow_steps() (the per-record timeline)
- delete_president_approval_record() (record cleanup)

Each is now read/written with this file's own column-presence gating
(_table_columns()), the same pattern it already used for the flow UPDATE
inside decide_president_approval() and for _insert_step_for_decision().
decide_president_approval() also no longer attempts to insert a timeline
step for a legacy flow-less approval record (performance_president_approvals.
flow_id is nullable; performance_process_flow_steps.flow_id is not), which
previously raised IntegrityError and silently failed every such decision.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_an")


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
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
    yield flask_app


class _Admin:
    id = 1
    is_admin = True
    is_superuser = False


def _insert_approval(db, **overrides):
    from app.models.performance_process_engine_models import PerformancePresidentApproval

    row = PerformancePresidentApproval(**overrides)
    db.session.add(row)
    db.session.commit()
    return row


def test_approval_base_rows_real_caller_succeeds_on_sqlite(app) -> None:
    from app.services.performance.process_engine_phase6_president_approvals import (
        _approval_base_rows,
    )

    with app.app_context():
        assert _approval_base_rows(viewer=_Admin(), status_filter="all") == []


def test_build_president_approval_workspace_real_caller_succeeds_with_pending_record(app) -> None:
    """Before the fix, every request to this workspace raised
    OperationalError; it must now run to completion and surface a real
    pending low-score record."""
    from app.extensions import db
    from app.services.performance.process_engine_phase6_president_approvals import (
        build_president_approval_workspace,
    )

    with app.app_context():
        _insert_approval(db, evaluation_id=9001, final_score=Decimal("60.00"), status="pending")
        context = build_president_approval_workspace(_Admin(), status_filter="pending")
        assert context["authorized"] is True
        assert len(context["rows"]) == 1
        assert context["rows"][0]["current_owner_name"]  # never raises, always a string


def test_build_president_approval_workspace_denies_unauthorized_viewer(app) -> None:
    from app.services.performance.process_engine_phase6_president_approvals import (
        build_president_approval_workspace,
    )

    class _Nobody:
        id = 999
        is_admin = False
        is_superuser = False
        role = "personel"
        role_name = None
        user_type = None

    with app.app_context():
        context = build_president_approval_workspace(_Nobody(), status_filter="pending")
        assert context["authorized"] is False
        assert context["rows"] == []


def test_decide_president_approval_real_caller_approves_successfully(app) -> None:
    """Before the fix, this UPDATE always raised OperationalError inside a
    try/except, so decide_president_approval() always returned ok=False and
    the row was never actually updated -- no president could ever approve a
    record. Must now succeed and persist the real status."""
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformancePresidentApproval
    from app.services.performance.process_engine_phase6_president_approvals import (
        decide_president_approval,
    )

    with app.app_context():
        approval = _insert_approval(db, evaluation_id=9002, final_score=Decimal("55.00"), status="pending")
        result = decide_president_approval(approval.id, _Admin(), "approved", note="onaylandı")
        assert result.ok is True

        reloaded = db.session.get(PerformancePresidentApproval, approval.id)
        assert reloaded is not None
        assert reloaded.status == "approved"
        assert reloaded.decided_at is not None
        assert reloaded.decision_note == "onaylandı"


def test_decide_president_approval_real_caller_returns_successfully(app) -> None:
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformancePresidentApproval
    from app.services.performance.process_engine_phase6_president_approvals import (
        decide_president_approval,
    )

    with app.app_context():
        approval = _insert_approval(db, evaluation_id=9003, final_score=Decimal("58.00"), status="pending")
        result = decide_president_approval(approval.id, _Admin(), "returned", note="iade")
        assert result.ok is True

        reloaded = db.session.get(PerformancePresidentApproval, approval.id)
        assert reloaded is not None
        assert reloaded.status == "returned"


def test_decide_president_approval_rejects_unauthorized_actor(app) -> None:
    from app.extensions import db
    from app.services.performance.process_engine_phase6_president_approvals import (
        decide_president_approval,
    )

    class _Nobody:
        id = 999
        is_admin = False
        is_superuser = False
        role = "personel"
        role_name = None
        user_type = None
        unvan = None
        title = None

    with app.app_context():
        approval = _insert_approval(db, evaluation_id=9005, final_score=Decimal("50.00"), status="pending")
        result = decide_president_approval(approval.id, _Nobody(), "approved")
        assert result.ok is False


def test_flow_steps_real_caller_succeeds_on_sqlite(app) -> None:
    """Before the fix, this SELECT raised OperationalError the moment the
    (now-fixed) Finding 1 crash was resolved."""
    from app.services.performance.process_engine_phase6_president_approvals import (
        _flow_steps,
    )

    with app.app_context():
        assert _flow_steps(flow_id=999999, evaluation_id=None) == []


def test_decide_president_approval_real_caller_approves_flow_less_record(app) -> None:
    """performance_president_approvals.flow_id is nullable and legacy
    flow-less records genuinely exist; before the fix, approving one always
    raised IntegrityError (performance_process_flow_steps.flow_id is NOT
    NULL) inside _insert_step_for_decision(), silently failing the whole
    decision."""
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformancePresidentApproval
    from app.services.performance.process_engine_phase6_president_approvals import (
        decide_president_approval,
    )

    with app.app_context():
        approval = _insert_approval(db, evaluation_id=9006, final_score=Decimal("62.00"), status="pending")
        assert approval.flow_id is None
        result = decide_president_approval(approval.id, _Admin(), "approved", note="onaylandı")
        assert result.ok is True

        reloaded = db.session.get(PerformancePresidentApproval, approval.id)
        assert reloaded is not None
        assert reloaded.status == "approved"


def test_delete_president_approval_record_real_caller_succeeds_on_sqlite(app) -> None:
    """Before the fix, this SELECT's unused decision_status column raised
    OperationalError on every delete attempt."""
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformancePresidentApproval
    from app.services.performance.process_engine_phase6_president_approvals import (
        delete_president_approval_record,
    )

    with app.app_context():
        approval = _insert_approval(db, evaluation_id=9007, final_score=Decimal("45.00"), status="pending")
        approval_id = approval.id
        result = delete_president_approval_record(approval_id, _Admin())
        assert result.ok is True
        db.session.expire_all()
        assert db.session.get(PerformancePresidentApproval, approval_id) is None
