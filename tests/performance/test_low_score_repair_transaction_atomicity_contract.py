"""BYS360 PERFORMANCE P0.2D: low-score lock repair transaction contract.

Transaction timeline of run_meeting_rule_enforcement(period_id), verified at
0662b1c0f066d08c54ecb23234cacad3207429ca:

1. ensure_meeting_rule_foundation(): runtime schema + module_settings/category
   seeding, then its OWN db.session.commit() (on error: rollback + raise).
   Rule/settings work is therefore durable before any low-score step runs.
2. Inner try, new transaction: period lookup, then
   ensure_low_score_processes_for_period() creates/updates low-score process
   and event rows (flushed, not committed) -> ``generated``.
3. repair_published_low_score_locks(): per low-score evaluation
   ensure_low_score_process_for_evaluation(flush=True), a publish block reason
   (ensure=True) and, when still published, is_published_to_employee=False /
   published_to_employee_at=None; final flush. No commit/rollback of its own.
4. Inner except (any Exception from 2-3): logs, appends "Düşük performans
   süreç kontrolü uygulanamadı.", NO rollback.
5. db.session.commit() of the transaction opened in step 2.
6. Outer except: rollback, ok=False, "Kural uygulama sırasında hata oluştu."

Since P0.2D, step 3 runs inside one SAVEPOINT (db.session.begin_nested()):
any failure rolls back everything the repair did (process/event rows,
unpublish changes) and re-raises; steps 1-2 are unaffected.

Since P0.2D-R1, the inner except still records the warning but re-raises a
sqlalchemy.exc.SQLAlchemyError, so database failures keep their pre-P0.2D
meaning: outer rollback of the whole low-score transaction, ok=False. Non-DB
failures (e.g. RuntimeError) keep the warning path with ok=True.

These tests run the real rule foundation and the real low-score service on a
file-backed SQLite test database only; failures are injected at the
service boundary the repair calls.
"""
from __future__ import annotations

import importlib
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

_MRE_MODULE = "app.services.performance.meeting_rule_enforcement"
_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_LOW_SCORE_WARNING = "Düşük performans süreç kontrolü uygulanamadı."
_SUCCESS_MESSAGE = "Toplantı kararları çalışan kural olarak uygulandı."
_FAILURE_MESSAGE = "Kural uygulama sırasında hata oluştu."
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02d_atomicity")
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
        "SECRET_KEY": "test-secret-key-for-p02d-atomicity-contract",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02d_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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


def _user(*, role: str = "personel") -> Any:
    from app.models import User

    n = _next()
    user = User(
        sicil_no=f"P2D{n:06d}",
        email=f"p02d-atomicity-{n}@bys360.test",
        ad="P02D",
        soyad=f"User{n}",
        role=role,
        is_active=True,
        must_change_password=False,
        must_set_security_question=False,
    )
    user.set_password("AtomicityContract1!")
    return user


def _seed(ls_app, rows: list[tuple[float, bool]]) -> tuple[int, list[int]]:
    """One period, one employee per row: (final_total_100, is_published_to_employee)."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    with ls_app.app_context():
        period = PerformancePeriod(
            title=f"P0.2D Dönem {_next()}",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            results_published=True,
        )
        db.session.add(period)
        db.session.flush()
        ids = []
        for score, published in rows:
            employee = _user()
            db.session.add(employee)
            db.session.flush()
            evaluation = PerformanceEvaluation(
                period_id=period.id,
                employee_id=employee.id,
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


def _release(ls_app, evaluation_id: int) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    with ls_app.app_context():
        president = _user(role="baskan")
        db.session.add(president)
        db.session.flush()
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        assert process is not None
        svc.president_approve_process(process, actor=president.id)
        db.session.commit()


def _db_state(ls_app, evaluation_ids: list[int]) -> dict[str, Any]:
    """Committed state as a fresh transaction sees it."""
    from app.extensions import db

    with ls_app.app_context():
        db.session.remove()
        published = {
            row[0]: bool(row[1])
            for row in db.session.execute(
                text("SELECT id, is_published_to_employee FROM performance_evaluations")
            ).all()
        }
        processes = db.session.execute(text("SELECT COUNT(*) FROM performance_low_score_processes")).scalar()
        events = db.session.execute(text("SELECT COUNT(*) FROM performance_low_score_process_events")).scalar()
        settings = db.session.execute(
            text("SELECT COUNT(*) FROM module_settings WHERE module_key='performance'")
        ).scalar()
        db.session.remove()
    return {
        "published": [published[eid] for eid in evaluation_ids],
        "processes": processes,
        "events": events,
        "settings": settings,
    }


def _inject_on_second_block_reason(monkeypatch: pytest.MonkeyPatch, fail) -> dict[str, Any]:
    """Wrap the service function the repair calls; on its 2nd call record the
    flushed-but-uncommitted state, then call ``fail``."""
    svc = importlib.import_module(_SERVICE_MODULE)
    real = svc.get_low_score_publish_block_reason
    seen: dict[str, Any] = {"calls": 0}

    def _wrapped(*args, **kwargs):
        seen["calls"] += 1
        if seen["calls"] == 2:
            from app.extensions import db

            seen["unpublished_in_tx_at_failure"] = db.session.execute(
                text("SELECT COUNT(*) FROM performance_evaluations WHERE is_published_to_employee = 0")
            ).scalar()
            seen["processes_in_tx_at_failure"] = db.session.execute(
                text("SELECT COUNT(*) FROM performance_low_score_processes")
            ).scalar()
            fail(args[0] if args else kwargs.get("evaluation"))
        return real(*args, **kwargs)

    monkeypatch.setattr(svc, "get_low_score_publish_block_reason", _wrapped)
    return seen


def _raise_runtime(evaluation) -> None:
    raise RuntimeError("simulated policy runtime failure")


def _raise_integrity(evaluation) -> None:
    """A real DB error: UNIQUE(evaluation_id) violation on flush."""
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
    db.session.flush()


def _run(ls_app, period_id: int) -> Any:
    mre = importlib.import_module(_MRE_MODULE)
    with ls_app.app_context():
        return mre.run_meeting_rule_enforcement(period_id=period_id)


# ---------------------------------------------------------------------------
# 1-3, 8-10. Normal path through the real foundation + real repair
# ---------------------------------------------------------------------------


def test_nothing_to_repair(ls_app) -> None:
    period_id, ids = _seed(ls_app, [(88.0, True), (72.0, True)])
    result = _run(ls_app, period_id)
    assert (result.ok, result.repaired_low_score_locks, result.generated_low_score_processes) == (True, 0, 0)
    assert (result.message, result.warnings) == (_SUCCESS_MESSAGE, [])
    assert _db_state(ls_app, ids) == {"published": [True, True], "processes": 0, "events": 0, "settings": 7}


def test_single_repair_is_committed(ls_app) -> None:
    period_id, ids = _seed(ls_app, [(57.0, True)])
    result = _run(ls_app, period_id)
    assert (result.ok, result.repaired_low_score_locks, result.generated_low_score_processes) == (True, 1, 1)
    assert (result.message, result.warnings) == (_SUCCESS_MESSAGE, [])
    state = _db_state(ls_app, ids)
    assert state["published"] == [False]
    assert (state["processes"], state["settings"]) == (1, 7)
    assert state["events"] > 0


def test_multiple_repairs_are_committed_and_released_or_non_low_rows_untouched(ls_app) -> None:
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True), (66.0, True), (88.0, True), (61.0, True)])
    _release(ls_app, ids[4])
    result = _run(ls_app, period_id)
    assert (result.ok, result.repaired_low_score_locks, result.warnings) == (True, 3, [])
    state = _db_state(ls_app, ids)
    assert state["published"] == [False, False, False, True, True]
    assert (state["processes"], state["settings"]) == (4, 7)


# ---------------------------------------------------------------------------
# 4-7. Failure inside the repair step
# ---------------------------------------------------------------------------


def test_runtime_error_after_first_row_changed_and_flushed(ls_app, monkeypatch) -> None:
    """The first evaluation is already re-locked and flushed when the 2nd one
    fails. Since P0.2D the repair's SAVEPOINT is rolled back, so none of that
    partial repair survives; the process rows generated in step 2 (before the
    repair) and the self-committed rule foundation are kept, as before.
    Before P0.2D the partial repair was committed."""
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    seen = _inject_on_second_block_reason(monkeypatch, _raise_runtime)
    result = _run(ls_app, period_id)
    assert seen["unpublished_in_tx_at_failure"] == 1  # flushed before the failure
    assert (result.ok, result.repaired_low_score_locks, result.warnings) == (True, 0, [_LOW_SCORE_WARNING])
    assert result.message == _SUCCESS_MESSAGE
    state = _db_state(ls_app, ids)
    assert state["published"] == [True, True]  # no partial repair
    assert (state["processes"], state["settings"]) == (2, 7)


def _database_failure_assertions(ls_app, ids: list[int], seen: dict[str, Any], result: Any) -> None:
    assert seen["unpublished_in_tx_at_failure"] == 1  # a flushed change existed at failure time
    assert (result.ok, result.repaired_low_score_locks) == (False, 0)
    assert result.message == _FAILURE_MESSAGE
    assert result.warnings == [_LOW_SCORE_WARNING]
    # Whole low-score transaction (T2) rolled back, including the step-2
    # process/event rows created before the repair; the self-committed rule
    # foundation (T1) is kept.
    assert _db_state(ls_app, ids) == {"published": [True, True], "processes": 0, "events": 0, "settings": 7}


def test_integrity_error_inside_repair(ls_app, monkeypatch) -> None:
    """A real DB error (UNIQUE violation on flush) fails the run. The repair's
    SAVEPOINT is rolled back and, since P0.2D-R1, the SQLAlchemyError is
    re-raised by the inner except to the outer one, which rolls T2 back and
    returns ok=False. This is the pre-P0.2D outcome (there the poisoned
    session made the commit raise). The first P0.2D revision had contained
    the error and returned ok=True with the step-2 rows committed."""
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    seen = _inject_on_second_block_reason(monkeypatch, _raise_integrity)
    result = _run(ls_app, period_id)
    _database_failure_assertions(ls_app, ids, seen, result)


def _raise_operational(evaluation) -> None:
    """A real driver error from a statement (not from a flush)."""
    from app.extensions import db

    db.session.execute(text("SELECT no_such_column FROM performance_evaluations"))


def test_operational_error_inside_repair_is_also_a_database_failure(ls_app, monkeypatch) -> None:
    """Classification is by exception class (sqlalchemy.exc.SQLAlchemyError),
    not by whether the error poisoned the session: a statement-level
    OperationalError is handled exactly like the IntegrityError above. Before
    P0.2D such an error did not poison the SQLite session, so the partial
    repair was committed with ok=True."""
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    seen = _inject_on_second_block_reason(monkeypatch, _raise_operational)
    result = _run(ls_app, period_id)
    _database_failure_assertions(ls_app, ids, seen, result)


def test_direct_repair_failure_after_creating_process_rows(ls_app, monkeypatch) -> None:
    """Direct call inside a caller-owned transaction that already holds an
    independent change. The repair creates process + event rows and re-locks
    the 1st row before failing. Since P0.2D all of that is rolled back with
    the repair's SAVEPOINT while the caller's earlier change is kept. Before
    P0.2D the caller's commit persisted the partial repair."""
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    seen = _inject_on_second_block_reason(monkeypatch, _raise_runtime)
    with ls_app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        period.title = "P0.2D bağımsız değişiklik"
        db.session.flush()
        with pytest.raises(RuntimeError):
            repair_published_low_score_locks(period_id)
        db.session.commit()
    assert seen["processes_in_tx_at_failure"] == 2
    state = _db_state(ls_app, ids)
    assert state["published"] == [True, True]
    assert (state["processes"], state["events"]) == (0, 0)
    with ls_app.app_context():
        assert db.session.execute(text("SELECT title FROM performance_periods WHERE id = :i"), {"i": period_id}).scalar() == "P0.2D bağımsız değişiklik"
