"""BYS360 PERFORMANCE P0.2B: visibility_guard low-score lock contract.

app/services/performance/visibility_guard.py imports
get_low_score_employee_publish_lock_reason from low_score_process_service in
a module-level ``try/except Exception`` and, when that import fails, binds a
same-signature fallback.

Call contract (verified at c0cc5670750105e94ce4beb75d1b404ccbece78a):

- the real service returns ``None`` when nothing blocks the scorecard and a
  non-empty Turkish reason string when the low-score publish lock holds; it
  never returns ``""``;
- both in-module callers read the value by truthiness (is_employee_visible,
  get_evaluation_visibility_state) and get_evaluation_visibility_state also
  passes it through verbatim as ``low_score_publish_lock_reason`` and, for the
  employee's own view, as ``reason``;
- the fallback is bound only when the import itself raises; runtime policy
  errors never reach it. Before P0.2B the fallback returned ``""`` (fail-open);
  it now returns LOW_SCORE_LOCK_UNAVAILABLE_REASON (fail-closed).

Normal-path tests run the real service against a real file-backed SQLite DB.
Failure-path tests execute a fresh copy of visibility_guard with the service
import made to fail; the real module and sys.modules are left untouched.
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
import tempfile
import types
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool

_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_GUARD_MODULE = "app.services.performance.visibility_guard"
_PENDING_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay şartı tamamlanmadan yayın yapılamaz. Başkan/Üst Onay Yayın Kilidi"
_REJECTED_REASON = "Başkan/Üst Onay tarafından iade edildi. Yayın kilidi devam ediyor."
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02b_visibility")
_counter = 0


# ---------------------------------------------------------------------------
# Real Flask app + file-backed SQLite (same pattern as
# tests/behavior/test_low_score_process_service_workflow_contract.py::_make_app;
# see that file for why each step is needed).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p02b-visibility-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "test-password",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02b_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        SQLALCHEMY_ENGINE_OPTIONS={"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
    )

    from sqlalchemy import event

    from app.extensions import db

    with flask_app.app_context():

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
    return flask_app


@pytest.fixture
def ls_app(monkeypatch: pytest.MonkeyPatch):
    return _make_app(monkeypatch)


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _published_evaluation(ls_app, *, final_total_100: float) -> tuple[int, int]:
    """(evaluation_id, employee_id) for a completed evaluation whose period and
    employee publish flags are both on, i.e. visible unless the low-score lock
    holds."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod, User

    n = _next()
    with ls_app.app_context():
        employee = User(
            sicil_no=f"P2B{n:06d}",
            email=f"p02b-visibility-{n}@bys360.test",
            ad="P02B",
            soyad=f"User{n}",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        employee.set_password("VisibilityContract1!")
        period = PerformancePeriod(
            title=f"P0.2B Dönem {n}",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            results_published=True,
        )
        db.session.add_all([employee, period])
        db.session.flush()
        evaluation = PerformanceEvaluation(
            period_id=period.id,
            employee_id=employee.id,
            final_total_100=final_total_100,
            status="completed",
            workflow_status="tamamlandi",
            level_1_completed=True,
            is_published_to_employee=True,
        )
        db.session.add(evaluation)
        db.session.commit()
        return evaluation.id, employee.id


def _president(ls_app) -> int:
    from app.extensions import db
    from app.models import User

    n = _next()
    with ls_app.app_context():
        user = User(
            sicil_no=f"P2P{n:06d}",
            email=f"p02b-president-{n}@bys360.test",
            ad="P02B",
            soyad=f"Baskan{n}",
            role="baskan",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("VisibilityContract1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _self_viewer(employee_id: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(id=employee_id, role="personel", is_authenticated=True)


# ---------------------------------------------------------------------------
# 1. Normal import path
# ---------------------------------------------------------------------------


def test_guard_binds_the_live_service_function_with_the_same_signature() -> None:
    guard = importlib.import_module(_GUARD_MODULE)
    svc = importlib.import_module(_SERVICE_MODULE)
    assert guard.get_low_score_employee_publish_lock_reason is svc.get_low_score_employee_publish_lock_reason
    assert str(inspect.signature(guard.get_low_score_employee_publish_lock_reason)) == "(evaluation=None, *, ensure=False)"


# ---------------------------------------------------------------------------
# 2-5. Normal path through the real service and a real DB
# ---------------------------------------------------------------------------


def test_non_low_score_evaluation_is_not_locked_and_is_visible(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import visibility_guard

    evaluation_id, employee_id = _published_evaluation(ls_app, final_total_100=88.0)
    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert visibility_guard.get_low_score_employee_publish_lock_reason(evaluation, ensure=False) is None
        assert visibility_guard.is_employee_visible(evaluation) is True
        state = visibility_guard.get_evaluation_visibility_state(evaluation, _self_viewer(employee_id))
        assert state["low_score_publish_locked"] is False
        assert state["low_score_publish_lock_reason"] is None
        assert state["employee_visible"] is True
        assert state["publish_state"] == "published"


def test_low_score_pending_president_approval_is_locked_with_current_reason(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc, visibility_guard

    evaluation_id, employee_id = _published_evaluation(ls_app, final_total_100=57.0)
    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        assert visibility_guard.get_low_score_employee_publish_lock_reason(evaluation, ensure=False) == _PENDING_REASON
        assert visibility_guard.is_employee_visible(evaluation) is False
        state = visibility_guard.get_evaluation_visibility_state(evaluation, _self_viewer(employee_id))
        assert state["low_score_publish_locked"] is True
        assert state["low_score_publish_lock_reason"] == _PENDING_REASON
        assert state["publish_state"] == "low_score_publish_locked"
        assert state["reason"] == _PENDING_REASON
        assert state["reason_code"] == "low_score_publish_lock"


def test_low_score_rejected_by_president_is_locked_with_current_reason(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc, visibility_guard

    evaluation_id, employee_id = _published_evaluation(ls_app, final_total_100=55.0)
    president_id = _president(ls_app)
    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        svc.president_reject_process(process, actor=president_id, note="Eksik gerekçe")
        db.session.commit()
        assert visibility_guard.get_low_score_employee_publish_lock_reason(evaluation, ensure=False) == _REJECTED_REASON
        assert visibility_guard.is_employee_visible(evaluation) is False
        state = visibility_guard.get_evaluation_visibility_state(evaluation, _self_viewer(employee_id))
        assert state["low_score_publish_lock_reason"] == _REJECTED_REASON
        assert state["publish_state"] == "low_score_publish_locked"
        assert state["reason"] == _REJECTED_REASON


def test_low_score_released_after_president_approval_is_visible(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc, visibility_guard

    evaluation_id, employee_id = _published_evaluation(ls_app, final_total_100=61.0)
    president_id = _president(ls_app)
    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        assert process is not None
        svc.president_approve_process(process, actor=president_id)
        db.session.commit()
        assert process.is_finalized_for_publish is True
        assert visibility_guard.get_low_score_employee_publish_lock_reason(evaluation, ensure=False) is None
        assert visibility_guard.is_employee_visible(evaluation) is True
        state = visibility_guard.get_evaluation_visibility_state(evaluation, _self_viewer(employee_id))
        assert state["low_score_publish_locked"] is False
        assert state["publish_state"] == "published"


# ---------------------------------------------------------------------------
# 7. How the in-module callers read the value
# ---------------------------------------------------------------------------


def _visible_duck_evaluation(employee_id: int = 501) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        employee_id=employee_id,
        status="completed",
        is_published_to_employee=True,
        period=types.SimpleNamespace(results_published=True),
    )


@pytest.mark.parametrize(
    ("value", "locked"),
    [(None, False), ("", False), ("Başkan onayı bekliyor.", True)],
)
def test_callers_read_lock_value_by_truthiness_and_pass_it_through(monkeypatch, value, locked) -> None:
    from app.services.performance import visibility_guard

    monkeypatch.setattr(visibility_guard, "get_low_score_employee_publish_lock_reason", lambda evaluation=None, *, ensure=False: value)
    evaluation = _visible_duck_evaluation()
    assert visibility_guard.is_employee_visible(evaluation) is (not locked)
    state = visibility_guard.get_evaluation_visibility_state(evaluation, _self_viewer(501))
    assert state["low_score_publish_locked"] is locked
    assert state["employee_visible"] is (not locked)
    assert state["low_score_publish_lock_reason"] == value
    if locked:
        assert state["publish_state"] == "low_score_publish_locked"
        assert state["reason"] == value


# ---------------------------------------------------------------------------
# 6. Service import failure path
# ---------------------------------------------------------------------------


class _ExplodingServiceModule(types.ModuleType):
    """Stands in for a service module whose import raised something other
    than ImportError (``from X import name`` propagates a non-AttributeError
    raised by the module's attribute lookup as-is)."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("simulated service import-time failure")


def _load_guard_with_failing_service_import(monkeypatch, failure: str) -> types.ModuleType:
    spec = importlib.util.find_spec(_GUARD_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if failure == "import_error":
        monkeypatch.setitem(sys.modules, _SERVICE_MODULE, None)  # -> ImportError on import
    else:
        monkeypatch.setitem(sys.modules, _SERVICE_MODULE, _ExplodingServiceModule(_SERVICE_MODULE))
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure", ["import_error", "runtime_error"])
def test_service_import_failure_is_logged_and_falls_back_with_same_signature(monkeypatch, caplog, failure) -> None:
    real_function = importlib.import_module(_SERVICE_MODULE).get_low_score_employee_publish_lock_reason
    with caplog.at_level(logging.ERROR, logger=_GUARD_MODULE):
        guard = _load_guard_with_failing_service_import(monkeypatch, failure)
    assert any(record.name == _GUARD_MODULE and record.exc_info for record in caplog.records)
    fallback = guard.get_low_score_employee_publish_lock_reason
    assert fallback is not real_function
    assert str(inspect.signature(fallback)) == str(inspect.signature(real_function))
    # The real, already-imported module is untouched.
    assert sys.modules[_GUARD_MODULE].get_low_score_employee_publish_lock_reason is real_function


@pytest.mark.parametrize("failure", ["import_error", "runtime_error"])
def test_service_import_failure_fallback_is_fail_closed(monkeypatch, failure) -> None:
    """P0.2B: when the low-score policy cannot be loaded, the fallback returns a
    non-empty lock reason, so no scorecard is opened to its employee without
    the low-score check. Before P0.2B it returned "" and every completed,
    published scorecard became visible (fail-open)."""
    guard = _load_guard_with_failing_service_import(monkeypatch, failure)
    evaluation = _visible_duck_evaluation()
    reason = guard.get_low_score_employee_publish_lock_reason(evaluation, ensure=False)
    assert reason == guard.LOW_SCORE_LOCK_UNAVAILABLE_REASON
    assert reason
    assert not any(token in reason.lower() for token in ("error", "exception", "traceback", "import"))
    assert guard.is_employee_visible(evaluation) is False
    state = guard.get_evaluation_visibility_state(evaluation, _self_viewer(501))
    assert state["low_score_publish_locked"] is True
    assert state["employee_visible"] is False
    assert state["publish_state"] == "low_score_publish_locked"
    assert state["reason"] == reason
    # Only the employee's own view is closed; an authorized, in-scope manager
    # keeps the internal preview exactly as with a real low-score lock.
    manager = types.SimpleNamespace(id=777, role="birim_sorumlusu", is_authenticated=True)
    manager_state = guard.get_evaluation_visibility_state(evaluation, manager, allowed_employee_ids={501})
    assert manager_state["can_view_unpublished"] is True
    assert manager_state["publish_state"] == "internal_preview"
