"""BYS360_DEFECT_S_REMEDIATION_PREFLIGHT_EMPTY_SCOPE_FAIL_CLOSED_CONTRACT

Permanent regression contract for DEFECT S
(app/services/performance/preflight.py::
build_task_management_preflight_report). Asserts the FIXED behavior only
-- it does not characterize, freeze, or otherwise exercise the prior
buggy shape.

Prior defect (fixed by this same change): the function normalized its own
`scope_user_ids` with the same truthy idiom as the (now-fixed) sibling
`build_performance_task_health_report`
(`scope_ids = {int(v) for v in (scope_user_ids or []) if v}` then
`if scope_ids:`), collapsing an explicitly empty scope into "no filter"
for its own `evaluations_query` (feeding `period_validation`'s issue
list). It then called
`build_performance_task_health_report(period, scope_ids or None)` --
re-collapsing the caller's original None-vs-empty distinction a second
time before handing it to the nested health report, so the row-level
identity leak already fixed in that sibling function would still have
resurfaced here even after that sibling fix landed, had this call site
not also been corrected.

The fix preserves whether the original `scope_user_ids` argument was
`None` end-to-end: `None` stays unrestricted, a real empty scope fails
closed on this function's own `evaluations_query` (using the same
`employee_id == -1` zero-rows sentinel this codebase's already-fixed
Defect R/S sibling code uses) and is passed through unchanged (not
`or None`-collapsed) into the nested, already-fixed health report call.

Fixture pattern: service-boundary style, matching this file's sibling
Defect S contract (tests/behavior/
test_performance_health_report_empty_scope_fail_closed_contract.py) and
the existing Wave 7 precedent for this same service family. Uses its own
dedicated tmp DB directory (C:\\bys360_pytest_tmp_defect_s_preflight) so
it shares no state with any other wave/agent/test file running
concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_s_preflight")

DEFAULT_PASSWORD = "DefectSPreflightTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "defect-s-preflight-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-s-preflight-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"defect_s_preflight_{uuid.uuid4().hex}.sqlite3")
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
        SERVER_NAME="defect-s-preflight.test",
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


def _create_user(app, *, ad="Deniz", soyad=None):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"DSPR{n:06d}",
            email=f"defect-s-preflight-{n}@bys360.test",
            ad=ad,
            soyad=soyad or f"Preflight{n}",
            role="personel",
            is_active=True,
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
            title=f"DefectS Preflight Period {n}",
            name=f"DefectS Preflight Period {n}",
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


def _create_assignment(app, *, period_id, employee_id, evaluator_id, manager_level=1, status="bekliyor"):
    from app.extensions import db
    from app.models import EvaluationAssignment

    with app.app_context():
        row = EvaluationAssignment(
            period_id=period_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            manager_level=manager_level,
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_evaluation(app, *, period_id, employee_id, is_published_to_employee=False):
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        row = PerformanceEvaluation(
            period_id=period_id,
            employee_id=employee_id,
            is_published_to_employee=is_published_to_employee,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# 1-4. None / matching / unrelated / empty scope
# ---------------------------------------------------------------------------


def test_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        report = build_task_management_preflight_report(_get_period(app, period_id), None)

    assert report["health_report"]["summary"]["employee_count"] == 2
    assert report["health_report"]["summary"]["assignment_count"] == 1


def test_matching_nonempty_scope_produces_scoped_data(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    other_employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_assignment(app, period_id=period_id, employee_id=other_employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        report = build_task_management_preflight_report(_get_period(app, period_id), {employee_id})

    assert report["health_report"]["summary"]["employee_count"] == 1
    assert report["health_report"]["summary"]["assignment_count"] == 1


def test_unrelated_nonexistent_scope_excludes_all_data(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_evaluation(app, period_id=period_id, employee_id=employee_id, is_published_to_employee=True)

    with app.test_request_context():
        report = build_task_management_preflight_report(_get_period(app, period_id), {999999})

    assert report["health_report"]["summary"]["employee_count"] == 0
    assert report["health_report"]["summary"]["assignment_count"] == 0
    assert not any("yayımlanmadan" in str(issue) for issue in report["period_validation"]["issues"]), "the unrelated scope's evaluations_query must not see the other employee's unpublished-result issue"


def test_empty_set_scope_returns_zero_employee_scoped_counts(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        report = build_task_management_preflight_report(_get_period(app, period_id), set())

    assert report["health_report"]["summary"]["employee_count"] == 0, "an explicitly empty authorization scope must never fall back to the global/unrestricted dataset"
    assert report["health_report"]["summary"]["assignment_count"] == 0
    assert report["summary"]["duplicate_level_count"] == 0
    assert report["summary"]["mismatch_count"] == 0
    assert report["summary"]["uncovered_count"] == 0


# ---------------------------------------------------------------------------
# 5. nested health_report fail-closed under empty scope
# ---------------------------------------------------------------------------


def test_empty_set_scope_nested_health_report_is_fail_closed(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    second_evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, manager_level=1)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=second_evaluator_id, manager_level=1)

    with app.test_request_context():
        report = build_task_management_preflight_report(_get_period(app, period_id), set())

    nested = report["health_report"]
    assert nested["assignments"] == []
    assert nested["duplicate_rows"] == []
    assert nested["summary"]["duplicate_level_count"] == 0


# ---------------------------------------------------------------------------
# 6. readiness/blocker calculations do not use unscoped data under empty scope
# ---------------------------------------------------------------------------


def test_empty_set_scope_blockers_do_not_reflect_unrelated_org_data(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    second_evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, manager_level=1)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=second_evaluator_id, manager_level=1)

    with app.test_request_context():
        report_empty = build_task_management_preflight_report(_get_period(app, period_id), set())
        report_none = build_task_management_preflight_report(_get_period(app, period_id), None)

    assert not any("Mükerrer görev satırı" in b["title"] for b in report_empty["blockers"]), "an empty scope must not surface a blocker sourced from data outside its (zero) authorized scope"
    assert any("Mükerrer görev satırı" in b["title"] for b in report_none["blockers"]), "sanity check: the same real duplicate data does surface as a blocker under the unrestricted (None) scope"


# ---------------------------------------------------------------------------
# 7. matching-scope behavior unchanged
# ---------------------------------------------------------------------------


def test_matching_scope_blockers_still_reflect_own_scoped_data(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    second_evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, manager_level=1)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=second_evaluator_id, manager_level=1)

    with app.test_request_context():
        report = build_task_management_preflight_report(_get_period(app, period_id), {employee_id})

    assert any("Mükerrer görev satırı" in b["title"] for b in report["blockers"])


# ---------------------------------------------------------------------------
# 8. no row-level identity leakage through nested report under empty scope
# ---------------------------------------------------------------------------


def test_empty_set_scope_leaks_no_employee_identity_through_nested_report(app):
    from app.services.performance.preflight import build_task_management_preflight_report

    evaluator_id = _create_user(app)
    employee_id = _create_user(app, ad="Baran", soyad="Erturk")
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        report = build_task_management_preflight_report(_get_period(app, period_id), set())

    serialized = repr(report["health_report"])
    assert "Baran" not in serialized
    assert "Erturk" not in serialized
