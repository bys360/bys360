"""BYS360 PERFORMANCE P0.2F: low-score audit actor contract.

Audit fields of the low-score workflow:

- PerformanceLowScoreProcess.created_by_user_id: set once, when
  ensure_low_score_process_for_evaluation() creates the process.
- PerformanceLowScoreProcess.updated_by_user_id: the last user who ran the
  low-score sync for the process (set on creation and on every later sync).
- PerformanceLowScoreProcessEvent.actor_user_id: who performed the step;
  _add_event() writes it only when the event is inserted and never touches an
  existing event.

actor_user_id=None means "the caller does not know the actor": it is the
parameter default, and every caller passes either a real user id or
getattr(<user>, "id", None). No caller passes None to clear the field and no
code reads a cleared value.

Verified at 0c49ab7d003c1a952cc9b7335b1beef7b61395c0: the existing-process
branch of ensure_low_score_process_for_evaluation() assigned
``process.updated_by_user_id = actor_user_id`` unconditionally.
repair_published_low_score_locks() reaches it twice per low-score evaluation
without an actor: directly, and through
get_low_score_publish_block_reason(ensure=True). So every repair set
updated_by_user_id to None, even on rows it did not otherwise change (one
UPDATE of only that field). It did so even right after the pre-step of the
same run_meeting_rule_enforcement(actor_user_id=Y) call had written Y.

Since P0.2F an unknown actor (None) leaves the existing value unchanged; a
real actor still replaces it, and creation is unchanged.

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
_SYNC_EVENT_KEYS = ("evaluation_completed", "low_score_detected")  # events that receive the sync actor
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02f_audit")
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
        "SECRET_KEY": "test-secret-key-for-p02f-audit-contract",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02f_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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


def _user(ls_app, *, role: str = "personel") -> int:
    from app.extensions import db
    from app.models import User

    with ls_app.app_context():
        n = _next()
        user = User(
            sicil_no=f"P2F{n:06d}",
            email=f"p02f-audit-{n}@bys360.test",
            ad="P02F",
            soyad=f"User{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("AuditContract1!")
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
            title=f"P0.2F Dönem {_next()}",
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


def _sync(ls_app, period_id: int, actor_id: int | None) -> None:
    """The real period sync (low_score_process_routes / publish callers), committed."""
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance import low_score_process_service as svc

    with ls_app.app_context():
        svc.ensure_low_score_processes_for_period(db.session.get(PerformancePeriod, period_id), actor_user_id=actor_id)
        db.session.commit()


def _audit(ls_app, evaluation_id: int) -> dict[str, Any]:
    """Committed audit state of one evaluation's process, as a fresh transaction sees it."""
    from app.extensions import db

    with ls_app.app_context():
        db.session.remove()
        row = db.session.execute(
            text(
                "SELECT id, created_by_user_id, updated_by_user_id, updated_at "
                "FROM performance_low_score_processes WHERE evaluation_id = :e"
            ),
            {"e": evaluation_id},
        ).one()
        events = {
            step_key: actor
            for step_key, actor in db.session.execute(
                text("SELECT step_key, actor_user_id FROM performance_low_score_process_events WHERE process_id = :p"),
                {"p": row[0]},
            ).all()
        }
        published = db.session.execute(
            text("SELECT is_published_to_employee FROM performance_evaluations WHERE id = :e"), {"e": evaluation_id}
        ).scalar()
        db.session.remove()
    return {
        "created_by": row[1],
        "updated_by": row[2],
        "updated_at": row[3],
        "events": events,
        "published": bool(published),
    }


def _run(ls_app, period_id: int, actor_id: int | None) -> Any:
    mre = importlib.import_module(_MRE_MODULE)
    with ls_app.app_context():
        return mre.run_meeting_rule_enforcement(period_id=period_id, actor_user_id=actor_id)


def _repair(ls_app, period_id: int) -> int:
    from app.extensions import db
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    with ls_app.app_context():
        changed = repair_published_low_score_locks(period_id)
        db.session.commit()
    return changed


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


def _inject_on_second_call(monkeypatch: pytest.MonkeyPatch, name: str, fail) -> dict[str, Any]:
    """Wrap a service function the pre-step / repair looks up at call time; on
    its 2nd call, call ``fail(evaluation)``."""
    svc = importlib.import_module(_SERVICE_MODULE)
    real = getattr(svc, name)
    seen: dict[str, Any] = {"calls": 0}

    def _wrapped(*args, **kwargs):
        seen["calls"] += 1
        if seen["calls"] == 2:
            fail(args[0] if args else kwargs.get("evaluation"))
        return real(*args, **kwargs)

    monkeypatch.setattr(svc, name, _wrapped)
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


def _raise_operational(evaluation) -> None:
    """A real driver error from a statement."""
    from app.extensions import db

    db.session.execute(text("SELECT no_such_column FROM performance_evaluations"))


# ---------------------------------------------------------------------------
# A. Existing updated_by_user_id + repair without an actor -> preserved
# ---------------------------------------------------------------------------


def test_repair_without_actor_preserves_existing_updated_by(ls_app) -> None:
    """Before P0.2F the repair re-locked the card and set updated_by_user_id
    from X to None."""
    x = _user(ls_app, role="ik")
    period_id, ids = _seed(ls_app, [(57.0, True)])
    _sync(ls_app, period_id, x)
    assert _audit(ls_app, ids[0])["updated_by"] == x

    assert _repair(ls_app, period_id) == 1
    after = _audit(ls_app, ids[0])
    assert after["published"] is False  # the repair itself still works
    assert (after["created_by"], after["updated_by"]) == (x, x)


def test_publish_block_reason_with_ensure_preserves_existing_updated_by(ls_app) -> None:
    """The repair's second path to the write site (also used by
    publish_preflight_rules): get_low_score_publish_block_reason(ensure=True).
    Before P0.2F it set updated_by_user_id from X to None."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    x = _user(ls_app, role="ik")
    period_id, ids = _seed(ls_app, [(57.0, False)])
    _sync(ls_app, period_id, x)
    with ls_app.app_context():
        reason = svc.get_low_score_publish_block_reason(db.session.get(PerformanceEvaluation, ids[0]), ensure=True)
        db.session.commit()
    assert reason  # still locked: president approval pending
    assert _audit(ls_app, ids[0])["updated_by"] == x


def test_rule_enforcement_without_actor_preserves_existing_updated_by(ls_app) -> None:
    """run_meeting_rule_enforcement(actor_user_id=None): neither the pre-step
    nor the repair knows the actor. Before P0.2F the value became None."""
    x = _user(ls_app, role="ik")
    period_id, ids = _seed(ls_app, [(57.0, True)])
    _sync(ls_app, period_id, x)

    result = _run(ls_app, period_id, None)
    assert (result.ok, result.repaired_low_score_locks, result.warnings) == (True, 1, [])
    after = _audit(ls_app, ids[0])
    assert (after["published"], after["created_by"], after["updated_by"]) == (False, x, x)


# ---------------------------------------------------------------------------
# B. Existing event actor_user_id + repair -> preserved (never overwritten)
# ---------------------------------------------------------------------------


def test_repair_preserves_existing_event_actors(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    x = _user(ls_app, role="ik")
    president = _user(ls_app, role="baskan")
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    _sync(ls_app, period_id, x)
    with ls_app.app_context():
        process = svc.ensure_low_score_process_for_evaluation(db.session.get(PerformanceEvaluation, ids[0]), actor_user_id=x)
        svc.president_approve_process(process, actor=president)
        db.session.commit()
    before = [_audit(ls_app, eid)["events"] for eid in ids]
    assert before[0]["president_approval"] == president
    assert all(events[key] == x for events in before for key in _SYNC_EVENT_KEYS)

    assert _repair(ls_app, period_id) == 1  # only the unapproved card is re-locked
    assert [_audit(ls_app, eid)["events"] for eid in ids] == before


# ---------------------------------------------------------------------------
# C. Existing updated_by_user_id + real incoming actor -> replaced
# ---------------------------------------------------------------------------


def test_rule_enforcement_with_actor_records_that_actor_on_existing_process(ls_app) -> None:
    """The pre-step writes the run's actor Y (existing contract: a real actor
    replaces the value); before P0.2F the repair of the same run then set it
    to None."""
    x = _user(ls_app, role="ik")
    y = _user(ls_app, role="admin")
    period_id, ids = _seed(ls_app, [(57.0, True)])
    _sync(ls_app, period_id, x)

    result = _run(ls_app, period_id, y)
    assert (result.ok, result.repaired_low_score_locks, result.warnings) == (True, 1, [])
    after = _audit(ls_app, ids[0])
    assert (after["published"], after["created_by"], after["updated_by"]) == (False, x, y)


def test_direct_sync_with_real_actor_replaces_updated_by(ls_app) -> None:
    x = _user(ls_app, role="ik")
    y = _user(ls_app, role="admin")
    period_id, ids = _seed(ls_app, [(57.0, False)])
    _sync(ls_app, period_id, x)
    _sync(ls_app, period_id, y)
    after = _audit(ls_app, ids[0])
    assert (after["created_by"], after["updated_by"]) == (x, y)
    assert all(after["events"][key] == x for key in _SYNC_EVENT_KEYS)  # step provenance stays with X


# ---------------------------------------------------------------------------
# D/E. New records
# ---------------------------------------------------------------------------


def test_rule_enforcement_without_actor_creates_process_with_no_actor(ls_app) -> None:
    """No actor is invented: no system/placeholder user, no 0/-1 ids."""
    from app.extensions import db

    period_id, ids = _seed(ls_app, [(57.0, True)])
    with ls_app.app_context():
        users_before = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()

    result = _run(ls_app, period_id, None)
    assert (result.ok, result.generated_low_score_processes, result.repaired_low_score_locks) == (True, 1, 1)
    after = _audit(ls_app, ids[0])
    assert (after["created_by"], after["updated_by"]) == (None, None)
    assert set(after["events"].values()) == {None}
    with ls_app.app_context():
        assert db.session.execute(text("SELECT COUNT(*) FROM users")).scalar() == users_before


def test_rule_enforcement_with_actor_creates_process_with_that_actor(ls_app) -> None:
    """Before P0.2F the new process kept created_by=Y but the repair of the same
    run set updated_by to None."""
    y = _user(ls_app, role="admin")
    period_id, ids = _seed(ls_app, [(57.0, True)])

    result = _run(ls_app, period_id, y)
    assert (result.ok, result.generated_low_score_processes, result.repaired_low_score_locks) == (True, 1, 1)
    after = _audit(ls_app, ids[0])
    assert (after["published"], after["created_by"], after["updated_by"]) == (False, y, y)
    assert all(after["events"][key] == y for key in _SYNC_EVENT_KEYS)


# ---------------------------------------------------------------------------
# F. No-op repair -> no audit mutation, no write at all
# ---------------------------------------------------------------------------


def test_noop_repair_writes_nothing(ls_app) -> None:
    """Card already locked, process in sync. Before P0.2F the repair issued one
    UPDATE whose only effect was updated_by_user_id=None (plus updated_at)."""
    x = _user(ls_app, role="ik")
    period_id, ids = _seed(ls_app, [(57.0, False)])
    _sync(ls_app, period_id, x)
    before = _audit(ls_app, ids[0])

    with _WriteRecorder(ls_app) as recorder:
        assert _repair(ls_app, period_id) == 0
    assert recorder.statements == []
    assert _audit(ls_app, ids[0]) == before


def test_noop_rule_enforcement_without_actor_writes_nothing_to_low_score_tables(ls_app) -> None:
    x = _user(ls_app, role="ik")
    period_id, ids = _seed(ls_app, [(57.0, False)])
    _sync(ls_app, period_id, x)
    before = _audit(ls_app, ids[0])

    with _WriteRecorder(ls_app) as recorder:
        result = _run(ls_app, period_id, None)
    assert (result.ok, result.generated_low_score_processes, result.repaired_low_score_locks) == (True, 1, 0)
    assert recorder.statements == []
    assert _audit(ls_app, ids[0]) == before


# ---------------------------------------------------------------------------
# G. Non-DB failure -> audit writes rolled back with the SAVEPOINT
# ---------------------------------------------------------------------------


def test_prestep_runtime_error_rolls_back_audit_update(ls_app, monkeypatch) -> None:
    """P0.2E pre-step SAVEPOINT: the 1st process was already re-stamped with Y
    when the 2nd evaluation fails; after the caller's commit both keep X."""
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance import low_score_process_service as svc

    x = _user(ls_app, role="ik")
    y = _user(ls_app, role="admin")
    period_id, ids = _seed(ls_app, [(57.0, False), (44.0, False)])
    _sync(ls_app, period_id, x)
    seen = _inject_on_second_call(monkeypatch, "ensure_low_score_process_for_evaluation", _raise_runtime)
    with ls_app.app_context():
        with pytest.raises(RuntimeError):
            svc.ensure_low_score_processes_for_period(db.session.get(PerformancePeriod, period_id), actor_user_id=y)
        db.session.commit()
    assert seen["calls"] == 2
    assert [_audit(ls_app, eid)["updated_by"] for eid in ids] == [x, x]


def test_rule_enforcement_repair_runtime_error_keeps_prestep_actor(ls_app, monkeypatch) -> None:
    """P0.2D repair SAVEPOINT: the repair fails on the 2nd card; nothing of the
    repair is kept (both cards stay published) and the committed pre-step
    stamp Y is intact (ok=True + warning, unchanged non-DB semantics)."""
    x = _user(ls_app, role="ik")
    y = _user(ls_app, role="admin")
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    _sync(ls_app, period_id, x)
    _inject_on_second_call(monkeypatch, "get_low_score_publish_block_reason", _raise_runtime)

    result = _run(ls_app, period_id, y)
    assert (result.ok, result.message, result.warnings) == (True, _SUCCESS_MESSAGE, [_LOW_SCORE_WARNING])
    assert result.repaired_low_score_locks == 0
    after = [_audit(ls_app, eid) for eid in ids]
    assert [row["published"] for row in after] == [True, True]  # no partial repair
    assert [(row["created_by"], row["updated_by"]) for row in after] == [(x, y), (x, y)]


# ---------------------------------------------------------------------------
# H. Database failure -> audit writes rolled back with T2 (P0.2D-R1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail", [_raise_integrity, _raise_operational], ids=["integrity_error", "operational_error"])
def test_rule_enforcement_repair_database_error_rolls_back_audit_update(ls_app, monkeypatch, fail) -> None:
    x = _user(ls_app, role="ik")
    y = _user(ls_app, role="admin")
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    _sync(ls_app, period_id, x)
    _inject_on_second_call(monkeypatch, "get_low_score_publish_block_reason", fail)

    result = _run(ls_app, period_id, y)
    assert (result.ok, result.message, result.warnings) == (False, _FAILURE_MESSAGE, [_LOW_SCORE_WARNING])
    after = [_audit(ls_app, eid) for eid in ids]
    assert [row["published"] for row in after] == [True, True]
    # The pre-step's Y stamp is part of T2 and is rolled back with it.
    assert [(row["created_by"], row["updated_by"]) for row in after] == [(x, x), (x, x)]
