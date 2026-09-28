"""BYS360 PERFORMANCE P0.2G: publish block reason database error contract.

get_low_score_publish_block_reason(evaluation, ensure=True) in
app/services/performance/low_score_process_service.py first calls
ensure_low_score_process_for_evaluation(evaluation). Callers with ensure=True:
meeting_rule_enforcement.repair_published_low_score_locks (inside its P0.2D
SAVEPOINT) and publish_preflight_rules.validate_evaluation_for_publish (reached
from publish/operations.publish_evaluation, publish_guard and visibility_guard).

Verified at c20f011ce6a7763e46ebe5c09a7c04d6f9a2311f: the ensure call was
wrapped in ``except Exception``, which logged and returned the generic lock
reason, so every error became a normal publish block reason:

- IntegrityError (flush): swallowed; the session was left in
  PendingRollbackError. run_meeting_rule_enforcement still ended ok=False, but
  only through a secondary PendingRollbackError that masked the real error.
- OperationalError (statement): swallowed; the session stayed usable, so the
  repair re-locked a released (president-approved, warning-recorded) card with
  the fabricated reason and the run committed it with ok=True and no warning.

Since P0.2G a sqlalchemy.exc.SQLAlchemyError from that ensure call is
re-raised (classified by exception class): the repair's SAVEPOINT is rolled
back and, through the P0.2D-R1 re-raise, the whole low-score transaction (T2)
is rolled back with ok=False; the self-committed rule foundation (T1) is kept.
Non-DB errors keep the existing fail-closed behaviour: logged, generic lock
reason.

Real Flask app + file-backed SQLite test database only.
"""
from __future__ import annotations

import importlib
import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import StaticPool

_MRE_MODULE = "app.services.performance.meeting_rule_enforcement"
_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_LOW_SCORE_WARNING = "Düşük performans süreç kontrolü uygulanamadı."
_SUCCESS_MESSAGE = "Toplantı kararları çalışan kural olarak uygulandı."
_FAILURE_MESSAGE = "Kural uygulama sırasında hata oluştu."
_UNEXPECTED_ERROR_LOG = "BYS360 performans modülünde beklenmeyen hata yakalandı."
# Reason returned when no process could be resolved (also the non-DB error fallback).
_GENERIC_LOCK_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay tamamlanmadan 70 altı karne yayınlanamaz. Başkan/Üst Onay Yayın Kilidi"
# Reason computed from an existing, not yet approved process.
_PRESIDENT_PENDING_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay şartı tamamlanmadan yayın yapılamaz. Başkan/Üst Onay Yayın Kilidi"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02g_block_reason")
_counter = 0


# ---------------------------------------------------------------------------
# Real Flask app + file-backed SQLite (same pattern as
# tests/behavior/test_low_score_process_service_workflow_contract.py::_make_app).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p02g-block-reason-contract",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02g_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
    from app.services import runtime_schema

    with flask_app.app_context():

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
    return flask_app


@pytest.fixture
def ls_app(monkeypatch: pytest.MonkeyPatch):
    return _make_app(monkeypatch)


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _user(ls_app, *, role: str = "personel") -> int:
    from app.extensions import db
    from app.models import User

    with ls_app.app_context():
        n = _next()
        user = User(
            sicil_no=f"P2G{n:06d}",
            email=f"p02g-block-reason-{n}@bys360.test",
            ad="P02G",
            soyad=f"User{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("BlockReasonContract1!")
        db.session.add(user)
        db.session.commit()
        return int(user.id)


def _seed(ls_app, rows: list[tuple[float, bool]]) -> tuple[int, list[int]]:
    """One period, one employee per row: (final_total_100, is_published_to_employee)."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    employee_ids = [_user(ls_app) for _row in rows]
    with ls_app.app_context():
        period = PerformancePeriod(
            title=f"P0.2G Dönem {_next()}",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            results_published=True,
        )
        db.session.add(period)
        db.session.flush()
        ids = []
        for (score, published), employee_id in zip(rows, employee_ids, strict=True):
            evaluation = PerformanceEvaluation(
                period_id=period.id,
                employee_id=employee_id,
                final_total_100=score,
                status="completed",
                workflow_status="tamamlandi",
                level_1_completed=True,
                is_published_to_employee=published,
            )
            db.session.add(evaluation)
            db.session.flush()
            ids.append(evaluation.id)
        db.session.commit()
        return period.id, ids


def _sync(ls_app, period_id: int, actor_id: int) -> None:
    """The real period sync (low_score_process_routes / publish callers), committed."""
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance import low_score_process_service as svc

    with ls_app.app_context():
        svc.ensure_low_score_processes_for_period(db.session.get(PerformancePeriod, period_id), actor_user_id=actor_id)
        db.session.commit()


def _release(ls_app, evaluation_id: int, president_id: int) -> None:
    """President approval of a first low score also records the warning, so the card is released."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    with ls_app.app_context():
        process = svc.ensure_low_score_process_for_evaluation(db.session.get(PerformanceEvaluation, evaluation_id), actor_user_id=president_id)
        assert process is not None
        svc.president_approve_process(process, actor=president_id)
        db.session.commit()


def _db_state(ls_app, evaluation_ids: list[int]) -> dict[str, Any]:
    """Committed state as a fresh transaction sees it."""
    from app.extensions import db

    with ls_app.app_context():
        db.session.remove()
        rows = {
            row[0]: (bool(row[1]), row[2])
            for row in db.session.execute(
                text(
                    "SELECT e.id, e.is_published_to_employee, p.updated_by_user_id FROM performance_evaluations e "
                    "LEFT JOIN performance_low_score_processes p ON p.evaluation_id = e.id"
                )
            ).all()
        }
        state = {
            "published": [rows[eid][0] for eid in evaluation_ids],
            "updated_by": [rows[eid][1] for eid in evaluation_ids],
            "processes": db.session.execute(text("SELECT COUNT(*) FROM performance_low_score_processes")).scalar(),
            "events": db.session.execute(text("SELECT COUNT(*) FROM performance_low_score_process_events")).scalar(),
            "settings": db.session.execute(text("SELECT COUNT(*) FROM module_settings WHERE module_key='performance'")).scalar(),
        }
        db.session.remove()
    return state


def _run(ls_app, period_id: int, actor_id: int) -> Any:
    mre = importlib.import_module(_MRE_MODULE)
    with ls_app.app_context():
        return mre.run_meeting_rule_enforcement(period_id=period_id, actor_user_id=actor_id)


def _inject_in_block_reason_ensure(monkeypatch: pytest.MonkeyPatch, fail, *, on_call: int = 1) -> dict[str, Any]:
    """Make ``fail(evaluation)`` run at the start of the ``on_call``-th
    ensure_low_score_process_for_evaluation call made from inside
    get_low_score_publish_block_reason; every other ensure call (pre-step,
    the repair's own direct call) passes through untouched."""
    svc = importlib.import_module(_SERVICE_MODULE)
    real_ensure = svc.ensure_low_score_process_for_evaluation
    real_block_reason = svc.get_low_score_publish_block_reason
    seen: dict[str, Any] = {"inside_block_reason": False, "calls": 0}

    def _block_reason(*args, **kwargs):
        seen["inside_block_reason"] = True
        try:
            return real_block_reason(*args, **kwargs)
        finally:
            seen["inside_block_reason"] = False

    def _ensure(evaluation, *args, **kwargs):
        if seen["inside_block_reason"]:
            seen["calls"] += 1
            if seen["calls"] == on_call:
                fail(evaluation)
        return real_ensure(evaluation, *args, **kwargs)

    monkeypatch.setattr(svc, "get_low_score_publish_block_reason", _block_reason)
    monkeypatch.setattr(svc, "ensure_low_score_process_for_evaluation", _ensure)
    return seen


def _add_duplicate_process(evaluation) -> None:
    """A real flush error inside the real ensure: a second process row for the
    same evaluation (UNIQUE evaluation_id) is autoflushed by ensure's own query."""
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    db.session.add(
        PerformanceLowScoreProcess(
            period_id=evaluation.period_id,
            evaluation_id=evaluation.id,
            employee_id=evaluation.employee_id,
            calendar_year=2026,
        )
    )


def _execute_invalid_statement(evaluation) -> None:
    """A real driver error from a statement."""
    from app.extensions import db

    db.session.execute(text("SELECT no_such_column FROM performance_evaluations"))


def _raise_runtime(evaluation) -> None:
    raise RuntimeError("simulated policy runtime failure")


def _logged_errors(caplog: pytest.LogCaptureFixture, module: str) -> list[str]:
    """Exception class names logged (logger.exception) by ``module``, in order."""
    names = []
    for record in caplog.records:
        exc_type = record.exc_info[0] if record.exc_info else None
        if record.name == module and exc_type is not None:
            names.append(exc_type.__name__)
    return names


class _WriteRecorder:
    """Records INSERT/UPDATE statements sent to the low-score tables."""

    _TABLES = {"performance_low_score_processes", "performance_low_score_process_events"}

    def __init__(self, ls_app) -> None:
        from app.extensions import db

        with ls_app.app_context():
            self._engine = db.engine
        self.statements: list[str] = []

    def _listener(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ARG002
        tokens = statement.split()
        verb = tokens[0].upper() if tokens else ""
        if verb == "UPDATE" and len(tokens) > 1:
            table = tokens[1]
        elif verb == "INSERT" and len(tokens) > 2:
            table = tokens[2]
        else:
            return
        if table.strip('"').lower() in self._TABLES:
            self.statements.append(statement)

    def __enter__(self) -> _WriteRecorder:
        from sqlalchemy import event

        event.listen(self._engine, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *exc_info: object) -> None:
        from sqlalchemy import event

        event.remove(self._engine, "before_cursor_execute", self._listener)


# ---------------------------------------------------------------------------
# A/B. Database error inside ensure=True -> propagated, not a lock reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fail", "expected"),
    [(_add_duplicate_process, IntegrityError), (_execute_invalid_statement, OperationalError)],
    ids=["integrity_error", "operational_error"],
)
def test_block_reason_ensure_database_error_propagates(ls_app, monkeypatch, caplog, fail, expected) -> None:
    """Before P0.2G both errors were logged and turned into the generic lock
    reason; after an IntegrityError the caller also got a session that could
    only raise PendingRollbackError."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    x = _user(ls_app, role="ik")
    period_id, ids = _seed(ls_app, [(57.0, False)])
    _sync(ls_app, period_id, x)
    before = _db_state(ls_app, ids)
    seen = _inject_in_block_reason_ensure(monkeypatch, fail)

    with caplog.at_level(logging.ERROR), ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, ids[0])
        with pytest.raises(expected):
            svc.get_low_score_publish_block_reason(evaluation, ensure=True)
        db.session.rollback()
    assert seen["calls"] == 1
    assert _logged_errors(caplog, _SERVICE_MODULE) == []  # not swallowed with a log
    assert _db_state(ls_app, ids) == before


# ---------------------------------------------------------------------------
# C. Non-DB error inside ensure=True -> unchanged fail-closed lock reason
# ---------------------------------------------------------------------------


def test_block_reason_ensure_runtime_error_keeps_generic_lock_reason(ls_app, monkeypatch, caplog) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    x = _user(ls_app, role="ik")
    period_id, ids = _seed(ls_app, [(57.0, False)])
    _sync(ls_app, period_id, x)
    _inject_in_block_reason_ensure(monkeypatch, _raise_runtime)

    with caplog.at_level(logging.ERROR), ls_app.app_context():
        reason = svc.get_low_score_publish_block_reason(db.session.get(PerformanceEvaluation, ids[0]), ensure=True)
        assert db.session.execute(text("SELECT 1")).scalar() == 1  # session still usable
        db.session.rollback()
    assert reason == _GENERIC_LOCK_REASON
    assert _logged_errors(caplog, _SERVICE_MODULE) == ["RuntimeError"]
    assert [record.getMessage() for record in caplog.records if record.name == _SERVICE_MODULE] == [_UNEXPECTED_ERROR_LOG]


# ---------------------------------------------------------------------------
# D/E/H. Through run_meeting_rule_enforcement (the repair's block reason)
# ---------------------------------------------------------------------------


def _seed_locked_and_released(ls_app) -> tuple[int, list[int], dict[str, int]]:
    """Card 1: not approved, published (must be re-locked). Card 2: approved and
    warning recorded, published (released, must stay published)."""
    actors = {"x": _user(ls_app, role="ik"), "y": _user(ls_app, role="admin"), "president": _user(ls_app, role="baskan")}
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    _sync(ls_app, period_id, actors["x"])
    _release(ls_app, ids[1], actors["president"])
    return period_id, ids, actors


@pytest.mark.parametrize(
    ("fail", "expected"),
    [(_add_duplicate_process, "IntegrityError"), (_execute_invalid_statement, "OperationalError")],
    ids=["integrity_error", "operational_error"],
)
def test_rule_enforcement_block_reason_database_error_fails_the_run(ls_app, monkeypatch, caplog, fail, expected) -> None:
    """The error hits card 2 after card 1 was already re-locked and flushed.
    Before P0.2G the OperationalError was swallowed: ok=True, no warning, and
    the released card 2 was re-locked with the generic reason and committed;
    the IntegrityError ended ok=False only via a secondary PendingRollbackError."""
    period_id, ids, actors = _seed_locked_and_released(ls_app)
    before = _db_state(ls_app, ids)
    assert before["published"] == [True, True]
    seen = _inject_in_block_reason_ensure(monkeypatch, fail, on_call=2)

    with caplog.at_level(logging.ERROR):
        result = _run(ls_app, period_id, actors["y"])
    assert seen["calls"] == 2
    assert (result.ok, result.message, result.warnings) == (False, _FAILURE_MESSAGE, [_LOW_SCORE_WARNING])
    assert (result.repaired_low_score_locks, result.generated_low_score_processes) == (0, 0)
    # The original error reaches the rule-enforcement handlers (inner, then outer).
    assert _logged_errors(caplog, _SERVICE_MODULE) == []
    assert _logged_errors(caplog, _MRE_MODULE) == [expected, expected]
    # T2 fully rolled back (repair and the pre-step's actor stamp); the rule
    # foundation (T1) committed by this run itself is kept.
    assert before["settings"] == 0
    assert _db_state(ls_app, ids) == {**before, "settings": 7}


def test_rule_enforcement_block_reason_runtime_error_keeps_fail_closed_lock(ls_app, monkeypatch) -> None:
    """Unchanged non-DB contract: the policy error becomes the generic lock
    reason, so card 2 is re-locked too, and the run succeeds."""
    period_id, ids, actors = _seed_locked_and_released(ls_app)
    _inject_in_block_reason_ensure(monkeypatch, _raise_runtime, on_call=2)

    result = _run(ls_app, period_id, actors["y"])
    assert (result.ok, result.message, result.warnings) == (True, _SUCCESS_MESSAGE, [])
    assert (result.repaired_low_score_locks, result.generated_low_score_processes) == (2, 2)
    state = _db_state(ls_app, ids)
    assert state["published"] == [False, False]
    assert state["updated_by"] == [actors["y"], actors["y"]]


# ---------------------------------------------------------------------------
# F/G. Normal block reasons, existing in-sync processes (no-op path)
# ---------------------------------------------------------------------------


def test_rule_enforcement_normal_path_relocks_only_unreleased_card(ls_app) -> None:
    period_id, ids, actors = _seed_locked_and_released(ls_app)
    result = _run(ls_app, period_id, actors["y"])
    assert (result.ok, result.message, result.warnings) == (True, _SUCCESS_MESSAGE, [])
    assert (result.repaired_low_score_locks, result.generated_low_score_processes) == (1, 2)
    state = _db_state(ls_app, ids)
    assert state["published"] == [False, True]
    assert (state["processes"], state["settings"]) == (2, 7)


def test_block_reason_normal_values_and_no_op_writes_nothing(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    period_id, ids, _actors = _seed_locked_and_released(ls_app)
    _unused_period, (non_low_id,) = _seed(ls_app, [(88.0, True)])
    before = _db_state(ls_app, ids)

    with _WriteRecorder(ls_app) as recorder, ls_app.app_context():
        reasons = [
            svc.get_low_score_publish_block_reason(db.session.get(PerformanceEvaluation, eid), ensure=True)
            for eid in (*ids, non_low_id)
        ]
        db.session.commit()
    assert reasons == [_PRESIDENT_PENDING_REASON, None, None]
    assert recorder.statements == []
    assert _db_state(ls_app, ids) == before
