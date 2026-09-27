"""BYS360 PERFORMANCE P0.2E: low-score pre-step transaction contract.

ensure_low_score_processes_for_period(period) in
app/services/performance/low_score_process_service.py loops over the
period's evaluations and, per low-score evaluation, calls
ensure_low_score_process_for_evaluation(flush=False): a new process row is
added and flushed immediately, its step events are added, and the loop
flushes again after each evaluation. The function never commits or rolls
back. Callers verified at ea82de9f117707aa05170d5ed5c2fd37fc24e4af:
low_score_process_routes (view + sync, commit only on success),
v2_routes publish (except logs, no commit), publish.operations and
performance_v2.publish_workspace (exception propagates), and
meeting_rule_enforcement.run_meeting_rule_enforcement, whose inner except
turns a non-DB error into a warning and then COMMITS the transaction.

Idempotency: one process per evaluation (UNIQUE evaluation_id, looked up
first) and one event per step key (_add_event skips existing keys).

Since P0.2E the loop runs inside one SAVEPOINT (db.session.begin_nested()):
a failure mid-loop rolls back every process/event row this call created or
updated and re-raises; the caller's earlier changes and its transaction are
kept. Database errors still reach run_meeting_rule_enforcement's outer except
through the P0.2D-R1 SQLAlchemyError re-raise (ok=False, T2 rolled back).

Real Flask app + file-backed SQLite test database only.
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
_EVENTS_PER_FIRST_LOW_SCORE = 5  # completed, detected, president, first warning, publish release
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02e_prestep")
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
        "SECRET_KEY": "test-secret-key-for-p02e-prestep-contract",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02e_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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


def _seed(ls_app, rows: list[tuple[float, bool]]) -> tuple[int, list[int]]:
    """One period, one employee per row: (final_total_100, is_published_to_employee)."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod, User

    with ls_app.app_context():
        period = PerformancePeriod(
            title=f"P0.2E Dönem {_next()}",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            results_published=True,
        )
        db.session.add(period)
        db.session.flush()
        ids = []
        for score, published in rows:
            n = _next()
            employee = User(
                sicil_no=f"P2E{n:06d}",
                email=f"p02e-prestep-{n}@bys360.test",
                ad="P02E",
                soyad=f"User{n}",
                role="personel",
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            employee.set_password("PreStepContract1!")
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


def _scalar(sql: str, **params: Any) -> Any:
    from app.extensions import db

    return db.session.execute(text(sql), params).scalar()


def _db_state(ls_app, evaluation_ids: list[int]) -> dict[str, Any]:
    """Committed state as a fresh transaction sees it."""
    from app.extensions import db

    with ls_app.app_context():
        db.session.remove()
        published = {
            row[0]: bool(row[1])
            for row in db.session.execute(text("SELECT id, is_published_to_employee FROM performance_evaluations")).all()
        }
        state = {
            "published": [published[eid] for eid in evaluation_ids],
            "processes": _scalar("SELECT COUNT(*) FROM performance_low_score_processes"),
            "events": _scalar("SELECT COUNT(*) FROM performance_low_score_process_events"),
            "settings": _scalar("SELECT COUNT(*) FROM module_settings WHERE module_key='performance'"),
        }
        db.session.remove()
    return state


def _inject_on_second_ensure(monkeypatch: pytest.MonkeyPatch, fail) -> dict[str, Any]:
    """Wrap the per-evaluation ensure the pre-step loop calls. On exactly its
    2nd call, record the flushed-but-uncommitted state and call ``fail``;
    every other call passes through (so a later retry can succeed)."""
    svc = importlib.import_module(_SERVICE_MODULE)
    real = svc.ensure_low_score_process_for_evaluation
    seen: dict[str, Any] = {"calls": 0, "first_evaluation": None}

    def _wrapped(evaluation, *args, **kwargs):
        seen["calls"] += 1
        if seen["calls"] == 1:
            seen["first_evaluation"] = evaluation
        if seen["calls"] == 2:
            seen["processes_in_tx_at_failure"] = _scalar("SELECT COUNT(*) FROM performance_low_score_processes")
            seen["events_in_tx_at_failure"] = _scalar("SELECT COUNT(*) FROM performance_low_score_process_events")
            fail(seen)
        return real(evaluation, *args, **kwargs)

    monkeypatch.setattr(svc, "ensure_low_score_process_for_evaluation", _wrapped)
    return seen


def _raise_runtime(seen: dict[str, Any]) -> None:
    raise RuntimeError("simulated policy runtime failure in the pre-step")


def _raise_integrity(seen: dict[str, Any]) -> None:
    """A real DB error: a second process row for the first evaluation
    (UNIQUE evaluation_id) flushed."""
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    first = seen["first_evaluation"]
    db.session.add(
        PerformanceLowScoreProcess(
            period_id=first.period_id,
            evaluation_id=first.id,
            employee_id=first.employee_id,
            calendar_year=2026,
        )
    )
    db.session.flush()


def _raise_operational(seen: dict[str, Any]) -> None:
    """A real driver error from a statement."""
    from app.extensions import db

    db.session.execute(text("SELECT no_such_column FROM performance_evaluations"))


def _run(ls_app, period_id: int) -> Any:
    mre = importlib.import_module(_MRE_MODULE)
    with ls_app.app_context():
        return mre.run_meeting_rule_enforcement(period_id=period_id)


# ---------------------------------------------------------------------------
# B. Normal path (direct call, caller commits)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "expected_created"),
    [
        ([(88.0, True), (72.0, False)], 0),
        ([(57.0, True)], 1),
        ([(57.0, True), (44.0, False), (66.0, True), (88.0, True)], 3),
    ],
)
def test_prestep_normal_path_counts(ls_app, rows, expected_created) -> None:
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance import low_score_process_service as svc

    period_id, ids = _seed(ls_app, rows)
    with ls_app.app_context():
        result = svc.ensure_low_score_processes_for_period(db.session.get(PerformancePeriod, period_id))
        db.session.commit()
    assert result["created_or_updated"] == expected_created
    assert len(result["process_ids"]) == expected_created
    state = _db_state(ls_app, ids)
    assert state["processes"] == expected_created
    assert state["events"] == expected_created * _EVENTS_PER_FIRST_LOW_SCORE
    assert state["published"] == [published for _score, published in rows]  # pre-step never unpublishes


# ---------------------------------------------------------------------------
# A/C/D. Mid-loop non-DB failure, caller's earlier change, session usability
# ---------------------------------------------------------------------------


def test_prestep_mid_loop_runtime_error_leaves_no_partial_rows(ls_app, monkeypatch) -> None:
    """The 1st evaluation's process and events are flushed when the 2nd one
    fails. Since P0.2E the pre-step's SAVEPOINT is rolled back, so none of it
    survives the caller's commit, while the caller's earlier change and a
    change made after the failure (the session stays usable) both commit.
    Before P0.2E the partial pre-step (1 process + 5 events) was committed."""
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance import low_score_process_service as svc

    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    seen = _inject_on_second_ensure(monkeypatch, _raise_runtime)
    with ls_app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        period.title = "P0.2E önceki bağımsız değişiklik"
        db.session.flush()
        with pytest.raises(RuntimeError):
            svc.ensure_low_score_processes_for_period(period)
        # The session is still usable: a new, independent change flushes and commits.
        db.session.add(
            PerformancePeriod(title="P0.2E sonraki bağımsız değişiklik", period_type="quarterly", start_date=date(2026, 4, 1), end_date=date(2026, 6, 30))
        )
        db.session.flush()
        db.session.commit()
    assert (seen["processes_in_tx_at_failure"], seen["events_in_tx_at_failure"]) == (1, _EVENTS_PER_FIRST_LOW_SCORE)
    state = _db_state(ls_app, ids)
    assert (state["processes"], state["events"]) == (0, 0)  # no partial pre-step
    with ls_app.app_context():
        titles = {row[0] for row in db.session.execute(text("SELECT title FROM performance_periods")).all()}
    assert {"P0.2E önceki bağımsız değişiklik", "P0.2E sonraki bağımsız değişiklik"} <= titles


def test_rule_enforcement_prestep_runtime_error_commits_no_partial_rows(ls_app, monkeypatch) -> None:
    """Through the only committing caller: the inner except still turns the
    RuntimeError into the warning (ok=True, unchanged non-DB semantics) and
    commits, but since P0.2E the half-done pre-step was already rolled back by
    its SAVEPOINT, so nothing from it is committed; the repair never runs.
    Before P0.2E the partial pre-step (1 process + 5 events) was committed."""
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    seen = _inject_on_second_ensure(monkeypatch, _raise_runtime)
    result = _run(ls_app, period_id)
    assert (seen["processes_in_tx_at_failure"], seen["events_in_tx_at_failure"]) == (1, _EVENTS_PER_FIRST_LOW_SCORE)
    assert (result.ok, result.warnings, result.message) == (True, [_LOW_SCORE_WARNING], _SUCCESS_MESSAGE)
    assert (result.generated_low_score_processes, result.repaired_low_score_locks) == (0, 0)
    assert _db_state(ls_app, ids) == {"published": [True, True], "processes": 0, "events": 0, "settings": 7}


# ---------------------------------------------------------------------------
# E. Retry / idempotency after a non-DB failure (same, still-valid session)
# ---------------------------------------------------------------------------


def test_prestep_retry_after_runtime_error_is_idempotent(ls_app, monkeypatch) -> None:
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance import low_score_process_service as svc

    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    _inject_on_second_ensure(monkeypatch, _raise_runtime)  # fails only on the 2nd call overall
    with ls_app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        with pytest.raises(RuntimeError):
            svc.ensure_low_score_processes_for_period(period)
        first = svc.ensure_low_score_processes_for_period(period)
        second = svc.ensure_low_score_processes_for_period(period)
        db.session.commit()
    assert first["created_or_updated"] == second["created_or_updated"] == 2
    assert sorted(first["process_ids"]) == sorted(second["process_ids"])
    state = _db_state(ls_app, ids)
    assert (state["processes"], state["events"]) == (2, 2 * _EVENTS_PER_FIRST_LOW_SCORE)
    with ls_app.app_context():
        assert _scalar("SELECT COUNT(*) FROM (SELECT evaluation_id FROM performance_low_score_processes GROUP BY evaluation_id HAVING COUNT(*) > 1) d") == 0
        assert _scalar("SELECT COUNT(*) FROM (SELECT process_id, step_key FROM performance_low_score_process_events GROUP BY process_id, step_key HAVING COUNT(*) > 1) d") == 0


# ---------------------------------------------------------------------------
# F. Database errors in the pre-step keep the P0.2D-R1 semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail", [_raise_integrity, _raise_operational], ids=["integrity_error", "operational_error"])
def test_rule_enforcement_prestep_database_error_fails_the_run(ls_app, monkeypatch, fail) -> None:
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    seen = _inject_on_second_ensure(monkeypatch, fail)
    result = _run(ls_app, period_id)
    assert seen["processes_in_tx_at_failure"] == 1
    assert (result.ok, result.message, result.warnings) == (False, _FAILURE_MESSAGE, [_LOW_SCORE_WARNING])
    # Whole low-score transaction (T2) rolled back; rule foundation (T1) kept.
    assert _db_state(ls_app, ids) == {"published": [True, True], "processes": 0, "events": 0, "settings": 7}


def test_rule_enforcement_retry_after_database_error_is_clean(ls_app, monkeypatch) -> None:
    """After a failed run (fully rolled back), a fresh run in a new request
    context completes the pre-step and the repair without duplicates."""
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    _inject_on_second_ensure(monkeypatch, _raise_integrity)
    failed = _run(ls_app, period_id)
    assert failed.ok is False
    monkeypatch.undo()
    retried = _run(ls_app, period_id)
    assert (retried.ok, retried.generated_low_score_processes, retried.repaired_low_score_locks) == (True, 2, 2)
    assert _db_state(ls_app, ids) == {
        "published": [False, False],
        "processes": 2,
        "events": 2 * _EVENTS_PER_FIRST_LOW_SCORE,
        "settings": 7,
    }
