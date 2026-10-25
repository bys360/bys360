"""BYS360_DEFECT_T_REMEDIATION_GO_LIVE_EMPTY_SCOPE_FAIL_CLOSED_CONTRACT

Permanent regression contract for DEFECT T
(app/services/performance/go_live_service.py::
build_performance_go_live_center). Asserts the FIXED behavior only -- it
does not characterize, freeze, or otherwise exercise the prior buggy
shape.

Prior defect (fixed by this same change): the function normalized its own
`scope_employee_ids` with `sorted({int(item) for item in
(scope_employee_ids or []) if item is not None})`, collapsing `None` and
an explicit empty scope into the identical value, then gated the
`EvaluationAssignment`/`PerformanceEvaluation` query filters with a bare
`if scoped_employee_ids:` and NO fail-closed else branch -- an explicit
empty scope (or a real non-empty scope resolving to no matches) silently
fell back to unfiltered, organization-wide assignment/evaluation counts
feeding `cards`, `blockers`, `release_checks`, and `readiness_score`.

The fix distinguishes `scope_employee_ids is None` (unrestricted, no
filter) from "provided" (always filters, using the same `employee_id ==
-1` zero-rows sentinel this codebase's fixed Defect R/S siblings already
established as canonical) whenever the resolved scope comes back empty.

Fixture pattern: service-boundary style, matching this file's sibling
Defect T contract (tests/behavior/
test_performance_operations_center_scope_fail_closed_contract.py) and
the established Wave 6/7 precedent. Uses its own dedicated tmp DB
directory (C:\\bys360_pytest_tmp_defect_t_go_live) so it shares no state
with any other wave/agent/test file running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_t_go_live")

DEFAULT_PASSWORD = "DefectTGoLiveTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "defect-t-go-live-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-t-go-live-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"defect_t_go_live_{uuid.uuid4().hex}.sqlite3")
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
        SERVER_NAME="defect-t-go-live.test",
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


def _create_user(app):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"DTGL{n:06d}",
            email=f"defect-t-go-live-{n}@bys360.test",
            ad="Defect",
            soyad=f"GoLive{n}",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_period(app, *, level_1_weight=50.0, level_2_weight=50.0, level_3_weight=0.0):
    import datetime as _dt

    from app.extensions import db
    from app.models import PerformancePeriod

    n = _next_suffix()
    with app.app_context():
        period = PerformancePeriod(
            title=f"DefectT GoLive Period {n}",
            name=f"DefectT GoLive Period {n}",
            period_type="yillik",
            start_date=_dt.date(2026, 1, 1),
            end_date=_dt.date(2026, 12, 31),
            is_active=True,
            level_1_weight=level_1_weight,
            level_2_weight=level_2_weight,
            level_3_weight=level_3_weight,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _get_period(app, period_id):
    from app.models import PerformancePeriod

    with app.app_context():
        return PerformancePeriod.query.get(period_id)


def _create_assignment(app, *, period_id, employee_id, evaluator_id, status="bekliyor", overdue=False):
    import datetime as _dt

    from app.extensions import db
    from app.models import EvaluationAssignment

    with app.app_context():
        row = EvaluationAssignment(
            period_id=period_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            manager_level=1,
            status=status,
            due_date=_dt.datetime(2026, 1, 1) if overdue else None,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_evaluation(app, *, period_id, employee_id, status="bekliyor"):
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        row = PerformanceEvaluation(period_id=period_id, employee_id=employee_id, status=status)
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# 1-4. None / matching / nonmatching / empty scope
# ---------------------------------------------------------------------------


def test_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance.go_live_service import build_performance_go_live_center

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, overdue=True)

    with app.app_context():
        dashboard = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=None,
        )

    assert dashboard["cards"]["open_assignments"] == 1
    assert dashboard["cards"]["overdue_assignments"] == 1


def test_matching_scope_returns_matching_assignment_data(app):
    from app.services.performance.go_live_service import build_performance_go_live_center

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    other_employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_assignment(app, period_id=period_id, employee_id=other_employee_id, evaluator_id=evaluator_id, overdue=True)

    with app.app_context():
        dashboard = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=[employee_id],
        )

    assert dashboard["cards"]["open_assignments"] == 1
    assert dashboard["cards"]["overdue_assignments"] == 0, "the scoped-out employee's overdue assignment must not be counted"


def test_nonmatching_scope_returns_zero_employee_derived_data(app):
    from app.services.performance.go_live_service import build_performance_go_live_center

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, overdue=True)

    with app.app_context():
        dashboard = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=[999999],
        )

    assert dashboard["cards"]["open_assignments"] == 0
    assert dashboard["cards"]["overdue_assignments"] == 0


def test_empty_scope_returns_zero_employee_derived_data(app):
    from app.services.performance.go_live_service import build_performance_go_live_center

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, overdue=True)
    _create_evaluation(app, period_id=period_id, employee_id=employee_id, status="tamamlandi")

    with app.app_context():
        dashboard = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=[],
        )

    assert dashboard["cards"]["open_assignments"] == 0, "an explicitly empty authorization scope must never fall back to the organization-wide dataset"
    assert dashboard["cards"]["overdue_assignments"] == 0
    assert dashboard["cards"]["completed_evaluations"] == 0


# ---------------------------------------------------------------------------
# 5-6. blockers derive only from scoped data
# ---------------------------------------------------------------------------


def test_matching_scope_excludes_unrelated_employee_blockers(app):
    from app.services.performance.go_live_service import build_performance_go_live_center

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    other_employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    _create_assignment(app, period_id=period_id, employee_id=other_employee_id, evaluator_id=evaluator_id, overdue=True)

    with app.app_context():
        dashboard = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=[employee_id],
        )

    assert not any("Geciken" in b["title"] for b in dashboard["blockers"]), "the scoped-out employee's overdue assignment must not surface as a blocker for this scope"


def test_empty_scope_does_not_inherit_organization_wide_blocker_counts(app):
    from app.services.performance.go_live_service import build_performance_go_live_center

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, overdue=True)

    with app.app_context():
        dashboard_empty = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=[],
        )
        dashboard_none = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=None,
        )

    assert not any("Geciken" in b["title"] for b in dashboard_empty["blockers"])
    assert any("Geciken" in b["title"] for b in dashboard_none["blockers"]), "sanity check: the real seeded overdue assignment does surface as a blocker under the unrestricted (None) scope"


# ---------------------------------------------------------------------------
# 7. deterministic scoped readiness result
# ---------------------------------------------------------------------------


def test_empty_scope_produces_deterministic_scoped_readiness_result(app):
    from app.services.performance.go_live_service import build_performance_go_live_center

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, overdue=True)

    with app.app_context():
        dashboard = build_performance_go_live_center(
            active_period=_get_period(app, period_id),
            requests_list=[],
            meetings=[],
            scope_employee_ids=[],
        )

    assert dashboard["cards"]["release_score"] == 100
    assert any(row["ok"] for row in dashboard["release_checks"] if row["label"] == "Görev gecikmesi")
