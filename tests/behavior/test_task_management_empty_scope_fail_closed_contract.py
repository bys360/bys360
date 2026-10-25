"""BYS360_DEFECT_R_REMEDIATION_EMPTY_SCOPE_FAIL_CLOSED_CONTRACT

Permanent regression contract for DEFECT R (app/services/performance/
task_management_service.py). Asserts the FIXED behavior only -- it does
not characterize, freeze, or otherwise exercise the prior buggy shape.

Prior defect (fixed by this same change): `build_task_management_dashboard_
payload`, `build_assignment_recommendation_payload`, and
`build_audit_employee_options` each normalized their `scope_user_ids`
parameter with a truthy idiom (`scope_user_ids or set()`, `scope_user_ids
if scope_user_ids else None`, `if scope_user_ids:`). This collapsed an
EXPLICITLY EMPTY scope (`set()` -- "this caller is authorized for zero
employees") into the SAME thing as `None` (a real, legitimate
unrestricted/global-view contract for callers that never receive a scope
at all), before the value ever reached `_apply_assignment_scope` /
`_active_personnel_count` / `get_latest_assignment_generation_logs` --
each of which already implements the correct fail-closed contract for
this exact distinction (`if scope_user_ids is not None and not scope_ids:
... employee_id == -1` / `... return 0` / `... return {"rows": []}`).

The fix removes the truthy collapse at every call site inside this module
and instead forwards the caller's `scope_user_ids` (None, empty, or
non-empty) unchanged into those already-correct lower-level helpers. This
file proves all three states stay distinct end-to-end from each public
entry point, and specifically that an explicitly empty scope now yields
zero rows/zero counts/zero identity leakage instead of silently falling
back to the full/global dataset.

Fixture pattern: copied from this same module's existing Wave 7 contract
file (tests/behavior/test_task_management_dashboard_reporting_contract.py)
-- Config class-attribute patch BEFORE create_app(), StaticPool + pysqlite
isolation_level=None + explicit BEGIN event listener, real ORM rows, no
mocking of any function under test. Uses its own dedicated tmp DB
directory (C:\\bys360_pytest_tmp_qr_final_r) so it shares no state with
any other wave/agent/test file running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_qr_final_r")

DEFAULT_PASSWORD = "QrFinalR EmptyScopeTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "qr-final-r-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-qr-final-r-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", DEFAULT_FIRST_LOGIN_PASSWORD)
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"qr_final_r_{uuid.uuid4().hex}.sqlite3")
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
        SERVER_NAME="qr-final-r.test",
    )

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


# ---------------------------------------------------------------------------
# Fixture builders (real DB rows)
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role="personel", is_active=True):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"QRFR{n:06d}",
            email=f"qr-final-r-{n}@bys360.test",
            ad="QrFinalR",
            soyad=f"EmptyScope{n}",
            role=role,
            is_active=is_active,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_period(app):
    import datetime as _dt

    from app.extensions import db
    from app.models import PerformancePeriod

    n = _next_suffix()
    with app.app_context():
        period = PerformancePeriod(
            title=f"QrFinalR Period {n}",
            name=f"QrFinalR Period {n}",
            period_type="yillik",
            start_date=_dt.date(2026, 1, 1),
            end_date=_dt.date(2026, 12, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _get_period(app, period_id):
    from app.models import PerformancePeriod

    with app.app_context():
        return PerformancePeriod.query.get(period_id)


def _create_assignment(app, *, period_id, employee_id, evaluator_id, manager_level=1, status="bekliyor", assignment_source="direct"):
    from app.extensions import db
    from app.models import EvaluationAssignment

    with app.app_context():
        row = EvaluationAssignment(
            period_id=period_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            manager_level=manager_level,
            status=status,
            assignment_source=assignment_source,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_exempt_evaluation(app, *, period_id, employee_id):
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        row = PerformanceEvaluation(
            period_id=period_id,
            employee_id=employee_id,
            evaluation_exempted=True,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_coverage_log(app, *, period_id, employee_id, event_type, severity="warning"):
    from app.extensions import db
    from app.models import AssignmentCoverageLog

    with app.app_context():
        row = AssignmentCoverageLog(
            period_id=period_id,
            employee_id=employee_id,
            manager_level=1,
            event_scope="generation",
            event_type=event_type,
            severity=severity,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# 1-6. build_task_management_dashboard_payload -- None / non-empty / empty
# ---------------------------------------------------------------------------


def test_dashboard_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids=None)

    assert payload["stats"]["total"] == 1


def test_dashboard_matching_nonempty_scope_sees_authorized_records(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids={employee_id})

    assert payload["stats"]["total"] == 1
    assert payload["assignments"][0].employee_id == employee_id


def test_dashboard_unrelated_nonempty_scope_sees_zero_records(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    unrelated_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids={unrelated_id})

    assert payload["stats"]["total"] == 0
    assert payload["assignments"] == []


def test_dashboard_empty_set_scope_sees_zero_records(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids=set())

    assert payload["stats"]["total"] == 0, "an explicitly empty authorization scope must never fall back to the global/unrestricted dataset"
    assert payload["assignments"] == []


def test_dashboard_empty_set_scope_all_aggregates_zero_and_no_identity_leak(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, assignment_source="delegated")
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, manager_level=2, assignment_source="uncovered")
    _create_exempt_evaluation(app, period_id=period_id, employee_id=employee_id)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids=set())

    assert payload["stats"] == {
        "total": 0, "pending": 0, "partial": 0, "completed": 0,
        "level_1": 0, "level_2": 0, "level_3": 0,
    }
    assert payload["coverage_summary"] == {"direct": 0, "delegated": 0, "uncovered": 0}
    assert payload["delegated_assignments"] == []
    assert payload["uncovered_assignments"] == []
    assert payload["exempt_evaluations"] == []
    assert payload["latest_assignment_logs"] == []
    assert payload["alert_summary"]["total_users"] == 0
    assert payload["alert_summary"]["ok_users"] == 0
    all_visible_employee_ids = {getattr(row, "employee_id", None) for row in payload["assignments"]}
    assert employee_id not in all_visible_employee_ids, "the scoped-out employee's records must not leak into any dashboard collection"


# ---------------------------------------------------------------------------
# 7-10. build_assignment_recommendation_payload -- None / non-empty / empty
# ---------------------------------------------------------------------------


def test_recommendation_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance.task_management_service import (
        build_assignment_recommendation_payload,
    )

    period_id = _create_period(app)
    employee_id = _create_user(app)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")

    with app.test_request_context():
        payload = build_assignment_recommendation_payload(_get_period(app, period_id), "", scope_user_ids=None)

    assert payload["summary"]["uncovered"] == 1


def test_recommendation_matching_scope_includes_authorized_data(app):
    from app.services.performance.task_management_service import (
        build_assignment_recommendation_payload,
    )

    period_id = _create_period(app)
    employee_id = _create_user(app)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")

    with app.test_request_context():
        payload = build_assignment_recommendation_payload(_get_period(app, period_id), "", scope_user_ids={employee_id})

    assert payload["summary"]["uncovered"] == 1
    assert any("Açıkta" in row["title"] for row in payload["recommendation_rows"])


def test_recommendation_unrelated_scope_excludes_data(app):
    from app.services.performance.task_management_service import (
        build_assignment_recommendation_payload,
    )

    period_id = _create_period(app)
    employee_id = _create_user(app)
    unrelated_id = _create_user(app)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")

    with app.test_request_context():
        payload = build_assignment_recommendation_payload(_get_period(app, period_id), "", scope_user_ids={unrelated_id})

    assert payload["summary"]["uncovered"] == 0
    assert payload["recommendation_rows"] == []


def test_recommendation_empty_set_scope_returns_deterministic_empty_payload(app):
    from app.services.performance.task_management_service import (
        build_assignment_recommendation_payload,
    )

    period_id = _create_period(app)
    employee_id = _create_user(app)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")

    with app.test_request_context():
        payload = build_assignment_recommendation_payload(_get_period(app, period_id), "", scope_user_ids=set())

    assert payload["summary"]["uncovered"] == 0, "an explicitly empty authorization scope must never fall back to the global/unrestricted recommendation dataset"
    assert payload["recommendation_rows"] == []
    assert payload["action_plan_rows"] == []
    assert payload["visible_rows"] == []


# ---------------------------------------------------------------------------
# 11. build_audit_employee_options -- same-module blast-radius proof
# ---------------------------------------------------------------------------


def test_build_audit_employee_options_empty_set_scope_returns_zero_not_full_roster(app):
    from app.services.performance.task_management_service import build_audit_employee_options

    _create_user(app)
    _create_user(app)

    with app.app_context():
        options = build_audit_employee_options(scope_user_ids=set())

    assert options == [], "an explicitly empty authorization scope must never leak the full active-employee roster"
