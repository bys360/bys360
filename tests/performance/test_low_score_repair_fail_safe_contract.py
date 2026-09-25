"""BYS360 PERFORMANCE P0.2C: low-score publish-lock repair contract.

repair_published_low_score_locks(period_id) in
app/services/performance/meeting_rule_enforcement.py re-locks employee
scorecards that are published although the low-score publish lock still
holds. Contract, verified at 0aa34cf624d7b3096cef1c8da6dc4c4acf44d874:

- Only caller: run_meeting_rule_enforcement (same module), reached from the
  manager-only POST /performance/meeting-development/rules/apply route and
  from meeting_p0_completion.run_p0_completion. Both copy
  ``repaired_low_score_locks`` and surface ``message``/``warnings`` as flashes.
- Return value: number of evaluations it unpublished (final_total_100 < 70,
  a truthy publish block reason, currently is_published_to_employee). Writes:
  low-score process rows/events via ensure_low_score_process_for_evaluation,
  is_published_to_employee=False, published_to_employee_at=None, then a
  flush. It never commits or rolls back itself.
- run_meeting_rule_enforcement runs the low-score block in an inner
  ``try/except Exception`` that appends the warning "Düşük performans süreç
  kontrolü uygulanamadı." WITHOUT a rollback and then commits; its outer
  ``except`` rolls back and returns ok=False.
- Policy import failure inside the repair: before P0.2C it logged a generic
  message and returned 0 (indistinguishable from "nothing to repair", and the
  run reported success with no warning). Since P0.2C it logs
  BYS360_LOW_SCORE_LOCK_REPAIR_UNAVAILABLE and re-raises, so the caller's
  inner except surfaces the standard warning.
- visibility_guard's fail-closed fallback (P0.2B) now logs
  BYS360_LOW_SCORE_VISIBILITY_FAIL_CLOSED once, with the traceback.

Real Flask app + file-backed SQLite only; ensure_meeting_rule_foundation
(runtime DDL + settings seeding, unrelated to the lock) is stubbed in the
caller-level tests.
"""
from __future__ import annotations

import importlib
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool

_MRE_MODULE = "app.services.performance.meeting_rule_enforcement"
_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_LOW_SCORE_WARNING = "Düşük performans süreç kontrolü uygulanamadı."
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02c_repair")
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
        "SECRET_KEY": "test-secret-key-for-p02c-repair-contract",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02c_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no=f"P2C{n:06d}",
        email=f"p02c-repair-{n}@bys360.test",
        ad="P02C",
        soyad=f"User{n}",
        role=role,
        is_active=True,
        must_change_password=False,
        must_set_security_question=False,
    )
    user.set_password("RepairContract1!")
    return user


def _seed(ls_app, rows: list[tuple[float, bool]]) -> tuple[int, list[int]]:
    """One period, one employee per row: (final_total_100, is_published_to_employee)."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    with ls_app.app_context():
        period = PerformancePeriod(
            title=f"P0.2C Dönem {_next()}",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            results_published=True,
        )
        db.session.add(period)
        db.session.flush()
        evaluation_ids = []
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
            evaluation_ids.append(evaluation.id)
        db.session.commit()
        return period.id, evaluation_ids


def _release(ls_app, evaluation_id: int) -> None:
    """Başkan/Üst Onay + auto-recorded first warning: publish lock released."""
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
        assert process.is_finalized_for_publish is True


def _published_flags(ls_app, evaluation_ids: list[int]) -> list[bool]:
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with ls_app.app_context():
        db.session.expire_all()
        flags = []
        for eid in evaluation_ids:
            evaluation = db.session.get(PerformanceEvaluation, eid)
            assert evaluation is not None
            flags.append(bool(evaluation.is_published_to_employee))
        return flags


def _process_count(ls_app) -> int:
    from app.models import PerformanceLowScoreProcess

    with ls_app.app_context():
        return PerformanceLowScoreProcess.query.count()


def _break_policy_import(monkeypatch: pytest.MonkeyPatch, trigger: str) -> None:
    if trigger == "missing_name":
        # The service module loads, but a name the repair imports is gone
        # (e.g. renamed by a refactor): ``from ... import name`` -> ImportError.
        svc = importlib.import_module(_SERVICE_MODULE)
        monkeypatch.delattr(svc, "get_low_score_publish_block_reason")
    else:
        monkeypatch.setitem(sys.modules, _SERVICE_MODULE, None)


def _stub_rule_foundation(monkeypatch: pytest.MonkeyPatch) -> Any:
    mre = importlib.import_module(_MRE_MODULE)
    monkeypatch.setattr(mre, "ensure_meeting_rule_foundation", lambda seed_categories=True: 0)
    return mre


# ---------------------------------------------------------------------------
# 1-5. Normal repair path (policy imports fine)
# ---------------------------------------------------------------------------


def test_repair_returns_zero_when_nothing_is_low_score(ls_app) -> None:
    from app.extensions import db
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    period_id, ids = _seed(ls_app, [(88.0, True), (72.5, True)])
    with ls_app.app_context():
        assert repair_published_low_score_locks(period_id) == 0
        db.session.commit()
    assert _published_flags(ls_app, ids) == [True, True]


def test_repair_unpublishes_a_single_published_blocked_low_score(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    period_id, ids = _seed(ls_app, [(57.0, True)])
    with ls_app.app_context():
        assert repair_published_low_score_locks(period_id) == 1
        db.session.commit()
    assert _published_flags(ls_app, ids) == [False]
    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, ids[0])
        assert evaluation is not None
        assert evaluation.published_to_employee_at is None
        assert evaluation.low_score_process is not None
        assert evaluation.low_score_process.status == "president_approval_pending"


def test_repair_counts_only_published_blocked_low_scores(ls_app) -> None:
    from app.extensions import db
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True), (66.0, True), (88.0, True), (61.0, True)])
    _release(ls_app, ids[4])
    with ls_app.app_context():
        assert repair_published_low_score_locks(period_id) == 3
        db.session.commit()
    # Blocked low scores re-locked; non-low and released low score untouched.
    assert _published_flags(ls_app, ids) == [False, False, False, True, True]


def test_repair_leaves_already_locked_low_scores_unchanged(ls_app) -> None:
    from app.extensions import db
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    period_id, ids = _seed(ls_app, [(57.0, False), (49.0, False)])
    with ls_app.app_context():
        assert repair_published_low_score_locks(period_id) == 0
        db.session.commit()
    assert _published_flags(ls_app, ids) == [False, False]


def test_repair_is_scoped_to_the_given_period(ls_app) -> None:
    from app.extensions import db
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    period_a, ids_a = _seed(ls_app, [(57.0, True)])
    _period_b, ids_b = _seed(ls_app, [(55.0, True)])
    with ls_app.app_context():
        assert repair_published_low_score_locks(period_a) == 1
        db.session.commit()
    assert _published_flags(ls_app, ids_a + ids_b) == [False, True]


# ---------------------------------------------------------------------------
# 6. Policy import failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", ["missing_name", "module_unavailable"])
def test_repair_policy_import_failure_raises_and_logs_distinctly(ls_app, monkeypatch, caplog, trigger) -> None:
    """P0.2C: an import failure no longer returns 0 (indistinguishable from
    "nothing to repair"); it is logged with a distinct marker and re-raised.
    Nothing is changed before the failure, so no partial repair exists."""
    from app.extensions import db
    from app.services.performance.meeting_rule_enforcement import repair_published_low_score_locks

    period_id, ids = _seed(ls_app, [(57.0, True)])
    with ls_app.app_context():
        _break_policy_import(monkeypatch, trigger)
        with caplog.at_level(logging.ERROR, logger=_MRE_MODULE), pytest.raises(ImportError):
            repair_published_low_score_locks(period_id)
        db.session.commit()
    records = [r for r in caplog.records if r.name == _MRE_MODULE and r.exc_info]
    assert any("BYS360_LOW_SCORE_LOCK_REPAIR_UNAVAILABLE" in r.getMessage() for r in records)
    assert any("hiçbir kayıt onarılmadı" in r.getMessage() for r in records)
    assert _published_flags(ls_app, ids) == [True]
    assert _process_count(ls_app) == 0


def test_rule_enforcement_surfaces_a_warning_when_repair_import_fails(ls_app, monkeypatch) -> None:
    """P0.2C: the caller's existing inner except turns the re-raised import
    failure into the standard low-score warning, so the run is no longer
    reported as a silent success. Before P0.2C: ok=True, no warning."""
    period_id, ids = _seed(ls_app, [(57.0, True)])
    mre = _stub_rule_foundation(monkeypatch)
    with ls_app.app_context():
        _break_policy_import(monkeypatch, "missing_name")
        result = mre.run_meeting_rule_enforcement(period_id=period_id)
    assert result.ok is True
    assert result.repaired_low_score_locks == 0
    assert result.warnings == [_LOW_SCORE_WARNING]
    assert _published_flags(ls_app, ids) == [True]


def test_rule_enforcement_warns_when_the_service_module_itself_cannot_load(ls_app, monkeypatch) -> None:
    """If the whole service module is unavailable, run_meeting_rule_enforcement's
    own import (before the repair is reached) fails and is surfaced as a
    warning. Unchanged by P0.2C."""
    period_id, ids = _seed(ls_app, [(57.0, True)])
    mre = _stub_rule_foundation(monkeypatch)
    with ls_app.app_context():
        _break_policy_import(monkeypatch, "module_unavailable")
        result = mre.run_meeting_rule_enforcement(period_id=period_id)
    assert result.ok is True
    assert result.warnings == [_LOW_SCORE_WARNING]
    assert _published_flags(ls_app, ids) == [True]


# ---------------------------------------------------------------------------
# 7. Failure inside the repair loop: transaction behavior (unchanged by P0.2C)
# ---------------------------------------------------------------------------


def _fail_on_second_block_reason(monkeypatch: pytest.MonkeyPatch, make_error) -> None:
    svc = importlib.import_module(_SERVICE_MODULE)
    real = svc.get_low_score_publish_block_reason
    calls = {"n": 0}

    def _wrapped(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            make_error(args[0] if args else kwargs.get("evaluation"))
        return real(*args, **kwargs)

    monkeypatch.setattr(svc, "get_low_score_publish_block_reason", _wrapped)


def test_runtime_error_mid_repair_commits_the_partial_repair_with_a_warning(ls_app, monkeypatch) -> None:
    """Characterizes current behavior (reported as a P0.2C finding): the inner
    except of run_meeting_rule_enforcement does not roll back, so rows already
    re-locked before the failure are committed and the run reports ok=True."""
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    mre = _stub_rule_foundation(monkeypatch)

    def _raise(evaluation):
        raise RuntimeError("simulated policy runtime failure")

    _fail_on_second_block_reason(monkeypatch, _raise)
    with ls_app.app_context():
        result = mre.run_meeting_rule_enforcement(period_id=period_id)
    assert result.ok is True
    assert result.warnings == [_LOW_SCORE_WARNING]
    assert result.repaired_low_score_locks == 0
    assert sorted(_published_flags(ls_app, ids)) == [False, True]
    assert _process_count(ls_app) == 2


def test_database_error_mid_repair_rolls_back_everything_and_reports_failure(ls_app, monkeypatch) -> None:
    """A real DB error (UNIQUE violation on flush) leaves the session needing a
    rollback, so the commit raises, the outer except rolls back and the run
    reports ok=False; nothing from the run is persisted."""
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True)])
    mre = _stub_rule_foundation(monkeypatch)

    def _duplicate_process(evaluation):
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

    _fail_on_second_block_reason(monkeypatch, _duplicate_process)
    with ls_app.app_context():
        result = mre.run_meeting_rule_enforcement(period_id=period_id)
    assert result.ok is False
    assert result.message == "Kural uygulama sırasında hata oluştu."
    assert result.repaired_low_score_locks == 0
    assert _published_flags(ls_app, ids) == [True, True]
    assert _process_count(ls_app) == 0


# ---------------------------------------------------------------------------
# 8. How callers read the result
# ---------------------------------------------------------------------------


def test_rule_enforcement_propagates_the_repair_count_and_commits(ls_app, monkeypatch) -> None:
    period_id, ids = _seed(ls_app, [(57.0, True), (44.0, True), (88.0, True)])
    mre = _stub_rule_foundation(monkeypatch)
    with ls_app.app_context():
        result = mre.run_meeting_rule_enforcement(period_id=period_id)
    assert result.ok is True
    assert result.repaired_low_score_locks == 2
    assert result.generated_low_score_processes == 2
    assert result.warnings == []
    assert result.as_dict()["repaired_low_score_locks"] == 2
    assert _published_flags(ls_app, ids) == [False, False, True]


def test_p0_completion_surfaces_the_repair_import_failure_warning(ls_app, monkeypatch) -> None:
    from app.services.performance import meeting_p0_completion

    period_id, _ids = _seed(ls_app, [(57.0, True)])
    mre = _stub_rule_foundation(monkeypatch)
    real_run = mre.run_meeting_rule_enforcement
    monkeypatch.setattr(mre, "run_meeting_rule_enforcement", lambda actor_user_id=None: real_run(period_id=period_id))
    monkeypatch.setattr(meeting_p0_completion, "ensure_p0_foundation", lambda: {"warnings": []})
    monkeypatch.setattr(meeting_p0_completion, "p0_test_scenarios", lambda: [])
    with ls_app.app_context():
        _break_policy_import(monkeypatch, "missing_name")
        result = meeting_p0_completion.run_p0_completion(actor_user_id=1)
    assert result.repaired_low_score_locks == 0
    assert result.warnings == [_LOW_SCORE_WARNING]


def test_p0_completion_copies_repair_count_and_warnings(monkeypatch) -> None:
    from app.services.performance import meeting_p0_completion
    from app.services.performance.meeting_rule_enforcement import RuleEnforcementResult

    fake = RuleEnforcementResult(True, "v", 1, 3, 0, 0, "m", ["w1"])
    monkeypatch.setattr(meeting_p0_completion, "ensure_p0_foundation", lambda: {"warnings": ["f1"]})
    monkeypatch.setattr(meeting_p0_completion, "p0_test_scenarios", lambda: [])
    monkeypatch.setattr(_MRE_MODULE + ".run_meeting_rule_enforcement", lambda actor_user_id=None: fake)
    result = meeting_p0_completion.run_p0_completion(actor_user_id=1)
    assert result.repaired_low_score_locks == 3
    assert result.warnings == ["f1", "w1"]


# ---------------------------------------------------------------------------
# visibility_guard fail-closed fallback: log observability
# ---------------------------------------------------------------------------

_GUARD_MODULE = "app.services.performance.visibility_guard"
_FAIL_CLOSED_MARKER = "BYS360_LOW_SCORE_VISIBILITY_FAIL_CLOSED"


def _exec_fresh_guard(monkeypatch: pytest.MonkeyPatch, *, break_service: bool) -> Any:
    """Execute a fresh copy of visibility_guard; sys.modules and the real
    module are left untouched."""
    import importlib.util

    spec = importlib.util.find_spec(_GUARD_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if break_service:
        monkeypatch.setitem(sys.modules, _SERVICE_MODULE, None)
    spec.loader.exec_module(module)
    return module


def test_visibility_fallback_logs_a_distinct_fail_closed_message(monkeypatch, caplog) -> None:
    with caplog.at_level(logging.ERROR, logger=_GUARD_MODULE):
        guard = _exec_fresh_guard(monkeypatch, break_service=True)
    records = [r for r in caplog.records if r.name == _GUARD_MODULE and _FAIL_CLOSED_MARKER in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    for fragment in ("yüklenemedi", "fail-closed", "kilitli", "yeniden başlatılana kadar"):
        assert fragment in message
    assert records[0].exc_info is not None  # traceback stays in the server log
    # What the employee sees is unchanged by the log change (P0.2B contract).
    reason = guard.get_low_score_employee_publish_lock_reason(None, ensure=False)
    assert reason == guard.LOW_SCORE_LOCK_UNAVAILABLE_REASON
    assert _FAIL_CLOSED_MARKER not in reason


def test_visibility_normal_import_path_logs_nothing(monkeypatch, caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger=_GUARD_MODULE):
        guard = _exec_fresh_guard(monkeypatch, break_service=False)
    assert [r for r in caplog.records if r.name == _GUARD_MODULE] == []
    svc = importlib.import_module(_SERVICE_MODULE)
    assert guard.get_low_score_employee_publish_lock_reason is svc.get_low_score_employee_publish_lock_reason