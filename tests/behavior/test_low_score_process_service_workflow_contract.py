"""BYS360_PHASE5_AGENT1_WORKFLOW_CONTRACT

Behavioral contract tests for app/services/performance/low_score_process_service.py,
focused on the state-transition surface that
tests/services/test_low_score_process_service_phase4t.py does not already cover:

- The live, currently-imported president approve/reject entry points
  (`president_approve_process`, `president_reject_process`) and the auto-escalation
  they trigger (`auto_record_first_low_score_warning` /
  `auto_start_second_low_score_process`) for a genuine first-offense vs.
  second-offense (repeat) low score, exercised through a real Flask app context +
  real SQLite database -- not mocks. These are the exact functions
  app/performance/low_score_process_routes.py imports and calls for the
  Başkan/Üst Onay approve/reject screens; the module's numerous
  `_legacy_*_phase1/phase2/phase3` twins are NOT imported by any route or other
  service (confirmed via `grep -rn "president_approve_process\\|president_reject_process\\|
  record_first_warning\\|start_second_repeat_admin_process" app/ --include=*.py`), so
  they are intentionally not exercised here as a second, redundant layer.
- Real state-transition behavior when president approve/reject is called against a
  process that is NOT in the "fresh, pending" state (reject-after-approve,
  approve-after-reject) -- documenting what the real code actually does (transitions
  unconditionally, no raise, no silent no-op) rather than assuming a guard exists.
- `record_first_warning` / `start_second_repeat_admin_process` called directly
  (as the "/record-warning" and "/start-admin-process" admin routes do) against a
  process whose `sequence_no`/`president_approved_at` do not match the scenario the
  function name implies -- these two primitives carry no such guard themselves (only
  the `auto_*` wrappers do), which is real, non-obvious behavior worth locking in.
- `calculate_sequence_no`'s documented fallback (always 1) when the low-score schema
  is not deployed yet.
- The real end-to-end publish-lock release flow through the live
  `get_low_score_employee_publish_lock_reason` / `is_low_score_employee_publish_released`
  aliases (used by app/services/performance/visibility_guard.py and
  app/services/performance/personnel_support_publish_approval_service.py).

A confirmed, separate production defect was found in the `ensure=False`
path of `get_low_score_publish_block_reason` while writing this file (it
never looked up an already-existing PerformanceLowScoreProcess row for that
path, so a genuinely finalized low-score evaluation could stay reported as
locked). It was deliberately NOT characterized by any test in this file at
the time -- doing so would have asserted the then-current, incorrect
behavior as the expected passing outcome, which would break the moment the
defect was correctly fixed. It has since been fixed and is now covered by
test_publish_lock_reason_with_ensure_false_finds_already_finalized_process
and test_publish_lock_reason_with_ensure_false_still_blocks_when_no_process_exists
below (BYS360 DEFECT AR).
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

# Deliberately NOT imported at module level: `app.models` / `app.services...`
# get imported (transitively pulling in config.py) at pytest COLLECTION time
# if done here -- i.e. before _make_app()'s monkeypatch.setenv("DATABASE_URL",
# ...) ever runs for any test in this process. config.py's
# SQLALCHEMY_DATABASE_URI is a class attribute computed once at config.py's
# first import (see _make_app's own comment below), so an early import here
# bakes in a stale/default URI for the rest of the pytest process, which
# silently breaks db.create_all()'s target database for every test in this
# file (empirically confirmed: moving these two imports into _make_app(),
# after the env vars are set, is what makes `no such table:
# role_menu_defaults` / `user_menu_permissions` disappear entirely).
PerformanceEvaluation: Any = None
svc: Any = None


def _import_low_score_symbols() -> None:
    global PerformanceEvaluation, svc
    if svc is not None:
        return
    from app.models import PerformanceEvaluation as _PerformanceEvaluation
    from app.services.performance import low_score_process_service as _svc

    PerformanceEvaluation = _PerformanceEvaluation
    svc = _svc

# ---------------------------------------------------------------------------
# DB fixture: same real-Flask-app-context + real-file-backed-SQLite pattern as
# tests/services/test_low_score_process_service_phase4t.py's `_phase5_make_app`
# (see that file's block comment for the full root-caused history of why a
# plain sqlite:///:memory: engine is unsafe for this module's
# flush()-without-commit call pattern, and why config.py's cached
# SQLALCHEMY_DATABASE_URI class attribute means the URI must be set directly
# on app.config rather than only via the DATABASE_URL env var). Reproduced
# here with an independent tmp-db directory (outside the worktree, non-git,
# short path -- avoids the Windows-username PermissionError described in
# tests/quality/test_rollback_live_release_contract_v1.py) so this file has
# zero shared state with any test file another parallel wave/agent may be
# running against this same module concurrently.
# ---------------------------------------------------------------------------

_PHASE5_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent1_workflow")
_user_counter = 0


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-low-score-workflow-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")

    os.makedirs(_PHASE5_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_PHASE5_TMP_DB_DIR, f"agent1_workflow_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    _import_low_score_symbols()

    # BYS360_PHASE5_COVERAGE_WAVE1_FORENSIC_CLOSURE: config.py bakes
    # SQLALCHEMY_DATABASE_URI in as a *class attribute* on Config, computed
    # once from os.getenv("DATABASE_URL") the very first time config.py is
    # imported anywhere in this pytest process. In a full-suite run that
    # first import has already happened (by an earlier test file or by
    # pytest's own collection phase) long before this fixture's own
    # monkeypatch.setenv("DATABASE_URL", ...) above ever runs, typically
    # with DATABASE_URL unset at that point -- freezing
    # Config.SQLALCHEMY_DATABASE_URI at "sqlite:///:memory:" for the rest of
    # the process. create_app() itself touches db.engine/db.session during
    # its own internal bootstrap (before this function gets a chance to
    # override anything), and Flask-SQLAlchemy 3.x lazily binds AND CACHES
    # the per-app Engine on that first access -- reading app.config at that
    # exact moment (populated via app.config.from_object(Config), i.e. from
    # the frozen class attribute). The later flask_app.config.update(...)
    # below only changes the per-instance config dict; it does not recreate
    # an already-cached Engine, so without this monkeypatch the app is
    # silently left bound to sqlite:///:memory: instead of this test's own
    # unique file-backed database for its entire lifetime. Empirically
    # proven: db.engine.url and post-commit attribute persistence were both
    # wrong (":memory:", and a written value reading back as None) without
    # this patch, and correct with it, reproduced with
    # tests/services/test_assignment_launch_exception_narrowing_wave6.py::
    # test_dialect_name_returns_real_dialect_on_success run immediately
    # before this fixture in the same pytest process. Matches the existing,
    # proven pattern already used by tests/behavior/
    # test_admin_routes_authorization_contract.py's own _make_app.
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

    from app.extensions import db

    with flask_app.app_context():
        # Disables pysqlite's implicit per-connection transaction so
        # _table_exists()'s ad-hoc inspect(db.engine).has_table(...) calls
        # (each of which checks out its own connection from the pool) cannot
        # silently roll back a still-open, not-yet-committed ORM session
        # write on the same shared StaticPool connection. See
        # test_low_score_process_service_phase4t.py's block comment for the
        # full empirical root cause.
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
def ls_app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(ls_app, *, role: str = "personel") -> int:
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    with ls_app.app_context():
        user = User(
            sicil_no=f"WF{suffix:06d}",
            email=f"workflow-contract-{suffix}@bys360.test",
            ad="Contract",
            soyad=f"User{suffix}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("WorkflowContractTest1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_period(ls_app, *, start: date, end: date, title: str | None = None) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod

    suffix = _next_suffix()
    with ls_app.app_context():
        period = PerformancePeriod(
            title=title or f"Workflow Contract Dönem {suffix}",
            period_type="quarterly",
            start_date=start,
            end_date=end,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _create_evaluation(
    ls_app,
    *,
    period_id: int,
    employee_id: int,
    final_total_100: float,
    status: str = "completed",
    workflow_status: str = "tamamlandi",
    level_1_completed: bool = True,
) -> int:
    from app.extensions import db

    with ls_app.app_context():
        evaluation = PerformanceEvaluation(
            period_id=period_id,
            employee_id=employee_id,
            final_total_100=final_total_100,
            status=status,
            workflow_status=workflow_status,
            level_1_completed=level_1_completed,
        )
        db.session.add(evaluation)
        db.session.commit()
        return evaluation.id


def _events_by_key(process_id: int):
    from app.models import PerformanceLowScoreProcessEvent

    return {
        event.step_key: event
        for event in PerformanceLowScoreProcessEvent.query.filter_by(process_id=process_id).all()
    }


# ---------------------------------------------------------------------------
# president_approve_process: real first-offense vs. repeat-offense escalation
# ---------------------------------------------------------------------------


def test_president_approve_process_first_offense_auto_records_warning_and_finalizes_publish(ls_app) -> None:
    from app.extensions import db
    from app.models import PersonnelStatusHistory

    employee_id = _create_user(ls_app)
    president_id = _create_user(ls_app, role="baskan")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=63.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        assert process is not None
        assert process.sequence_no == 1
        process_id = process.id

        result = svc.president_approve_process(process, actor=president_id, note="Başkan onayladı")
        db.session.commit()

        # Approval itself.
        assert result.president_approved_at is not None
        assert result.president_approved_by_id == president_id
        assert result.president_approval_note == "Başkan onayladı"
        assert result.president_rejected_at is None
        assert result.president_rejected_by_id is None
        assert result.president_rejection_note is None

        # First-offense escalation: approve auto-fires
        # auto_record_first_low_score_warning (not the second-repeat admin
        # process, since sequence_no == 1 means is_second_or_later is False).
        assert result.warning_recorded_at is not None
        assert result.administrative_process_started_at is None
        assert result.status == "first_low_warning"
        assert result.current_stage_key == "first_low_warning"

        # Both the approval and the auto-recorded warning are now satisfied,
        # so the record is fully finalized for publish.
        assert result.is_finalized_for_publish is True

    with ls_app.app_context():
        events = _events_by_key(process_id)
        assert events["president_approval"].status == "done"
        assert events["president_approval"].actor_user_id == president_id
        assert events["first_warning_record"].status == "done"
        assert events["publish_release"].status == "ready"

        # record_first_warning (called internally by
        # auto_record_first_low_score_warning) also writes a personnel status
        # history row as a real side effect of the approve call chain.
        history = PersonnelStatusHistory.query.filter_by(
            user_id=employee_id, event_type="performans_70_alti"
        ).first()
        assert history is not None
        assert history.previous_value == str(evaluation_id)


def test_president_approve_process_second_offense_auto_starts_admin_process_not_warning(ls_app) -> None:
    from app.extensions import db

    employee_id = _create_user(ls_app)
    president_id = _create_user(ls_app, role="baskan")

    period_a = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    eval_a = _create_evaluation(ls_app, period_id=period_a, employee_id=employee_id, final_total_100=64.0)
    period_b = _create_period(ls_app, start=date(2026, 4, 1), end=date(2026, 6, 30))
    eval_b = _create_evaluation(ls_app, period_id=period_b, employee_id=employee_id, final_total_100=52.0)

    with ls_app.app_context():
        evaluation_a = db.session.get(PerformanceEvaluation, eval_a)
        svc.ensure_low_score_process_for_evaluation(evaluation_a)
        db.session.commit()

    with ls_app.app_context():
        evaluation_b = db.session.get(PerformanceEvaluation, eval_b)
        process_b = svc.ensure_low_score_process_for_evaluation(evaluation_b)
        db.session.commit()
        # Second low score for this employee in the same calendar year -> real
        # repeat-offense sequencing.
        assert process_b is not None
        assert process_b.sequence_no == 2
        assert process_b.process_type == "second_low_score_admin_process"
        process_b_id = process_b.id

        result = svc.president_approve_process(process_b, actor=president_id)
        db.session.commit()

        assert result.president_approved_at is not None
        # Repeat-offense escalation: approve auto-fires
        # auto_start_second_low_score_process instead of the warning path.
        assert result.administrative_process_started_at is not None
        assert result.warning_recorded_at is None
        assert result.process_type == "second_low_score_admin_process"
        assert result.status == "second_low_repeat"
        assert result.current_stage_key == "second_low_repeat"
        assert result.is_finalized_for_publish is True

    with ls_app.app_context():
        events = _events_by_key(process_b_id)
        assert events["second_repeat_admin_process"].status == "done"
        assert "first_warning_record" not in events or events["first_warning_record"].status != "done"
        assert events["publish_release"].status == "ready"


def test_president_approve_process_is_idempotent_on_repeated_calls(ls_app) -> None:
    """Calling approve twice must not move the original approval timestamp,
    must not duplicate events, and must not re-clear/re-fire the already
    satisfied auto-warning."""
    from app.extensions import db

    employee_id = _create_user(ls_app)
    first_actor = _create_user(ls_app, role="baskan")
    second_actor = _create_user(ls_app, role="baskan")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=61.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        process_id = process.id

        first_result = svc.president_approve_process(process, actor=first_actor, note="İlk onay")
        db.session.commit()
        first_approved_at = first_result.president_approved_at
        first_warning_at = first_result.warning_recorded_at
        assert first_approved_at is not None
        assert first_warning_at is not None

        second_result = svc.president_approve_process(process, actor=second_actor, note="İkinci çağrı")
        db.session.commit()

        # Real behavior: president_approved_at is only ever set once
        # (`getattr(process, "president_approved_at", None) or utc_now()`),
        # but president_approved_by_id and the note are NOT similarly
        # guarded -- they get overwritten on every call. Documenting exactly
        # what happens rather than assuming full idempotency.
        assert second_result.president_approved_at == first_approved_at
        assert second_result.president_approved_by_id == second_actor
        assert second_result.president_approval_note == "İkinci çağrı"
        # The already-recorded warning is untouched (auto_record_first_low_score_warning
        # short-circuits once warning_recorded_at is set).
        assert second_result.warning_recorded_at == first_warning_at

    with ls_app.app_context():
        from app.models import PerformanceLowScoreProcessEvent

        events = PerformanceLowScoreProcessEvent.query.filter_by(
            process_id=process_id, step_key="president_approval"
        ).all()
        # _mark_event() updates the existing row in place rather than
        # inserting a second one.
        assert len(events) == 1
        assert events[0].note == "İkinci çağrı"


# ---------------------------------------------------------------------------
# president_reject_process: real state transitions, including
# reject-after-approve and approve-after-reject reversal.
# ---------------------------------------------------------------------------


def test_president_reject_process_on_fresh_pending_process_blocks_publish(ls_app) -> None:
    from app.extensions import db

    employee_id = _create_user(ls_app)
    president_id = _create_user(ls_app, role="baskan")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=58.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        process_id = process.id

        result = svc.president_reject_process(process, actor=president_id, note="Eksik gerekçe")
        db.session.commit()

        assert result.president_rejected_at is not None
        assert result.president_rejected_by_id == president_id
        assert result.president_rejection_note == "Eksik gerekçe"
        assert result.president_approved_at is None
        assert result.status == "president_rejected"
        assert result.current_stage_key == "president_returned"
        assert result.is_finalized_for_publish is False

    with ls_app.app_context():
        events = _events_by_key(process_id)
        assert events["president_rejected"].status == "returned"
        assert events["publish_release"].status == "blocked"


def test_president_reject_process_after_approval_clears_approval_but_keeps_recorded_warning(ls_app) -> None:
    """A real state-transition-rejection scenario: reject a process that was
    already approved (and therefore already auto-warned). The live code has
    no guard preventing this -- it transitions unconditionally. Document what
    it actually does: approval fields are cleared, but the warning already
    recorded during the earlier approval is NOT rolled back."""
    from app.extensions import db

    employee_id = _create_user(ls_app)
    president_id = _create_user(ls_app, role="baskan")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=59.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()

        svc.president_approve_process(process, actor=president_id)
        db.session.commit()
        assert process.president_approved_at is not None
        recorded_warning_at = process.warning_recorded_at
        assert recorded_warning_at is not None
        assert process.is_finalized_for_publish is True
        process_id = process.id

        result = svc.president_reject_process(process, actor=president_id, note="Sonradan iade")
        db.session.commit()

        assert result.president_rejected_at is not None
        assert result.president_approved_at is None
        assert result.president_approved_by_id is None
        # Real (perhaps surprising) behavior: the warning timestamp set by the
        # earlier approval is left exactly as it was.
        assert result.warning_recorded_at == recorded_warning_at
        assert result.status == "president_rejected"
        # is_finalized_for_publish checks rejection FIRST, so even though
        # warning_recorded_at is still populated, the record is no longer
        # considered finalized.
        assert result.is_finalized_for_publish is False

    with ls_app.app_context():
        from app.models import PerformanceLowScoreProcess

        reloaded = db.session.get(PerformanceLowScoreProcess, process_id)
        block_reason = svc.get_low_score_publish_block_reason(process=reloaded, ensure=False)
        assert block_reason is not None
        assert "iade" in block_reason.lower()


def test_president_approve_process_reverses_prior_rejection_and_completes_first_offense_flow(ls_app) -> None:
    """The reverse transition: reject a fresh process first, then approve it.
    Real behavior -- rejection fields are cleared and the normal first-offense
    auto-warning fires on the (now successful) approval, same as a clean
    first-time approve."""
    from app.extensions import db

    employee_id = _create_user(ls_app)
    president_id = _create_user(ls_app, role="baskan")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=66.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()

        svc.president_reject_process(process, actor=president_id, note="İlk iade")
        db.session.commit()
        assert process.president_rejected_at is not None
        assert process.is_finalized_for_publish is False

        result = svc.president_approve_process(process, actor=president_id, note="Yeniden onay")
        db.session.commit()

        assert result.president_rejected_at is None
        assert result.president_rejected_by_id is None
        assert result.president_rejection_note is None
        assert result.president_approved_at is not None
        assert result.president_approval_note == "Yeniden onay"
        assert result.warning_recorded_at is not None
        assert result.status == "first_low_warning"
        assert result.is_finalized_for_publish is True


# ---------------------------------------------------------------------------
# record_first_warning / start_second_repeat_admin_process called directly
# (as the manual admin routes call them) against process states that do not
# match the "normal" pre-condition their `auto_*` wrappers would enforce.
# ---------------------------------------------------------------------------


def test_record_first_warning_and_start_second_repeat_admin_process_carry_no_precondition_guard(ls_app) -> None:
    from app.extensions import db

    employee_id = _create_user(ls_app)
    admin_id = _create_user(ls_app, role="ik")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=64.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        process_id = process.id

        # Real behavior: record_first_warning does not check
        # president_approved_at at all -- calling it before Başkan approval
        # (which the "/record-warning" admin route can do, since that route
        # has no server-side precondition check either) still records the
        # warning.
        assert process.president_approved_at is None
        result = svc.record_first_warning(process, actor=admin_id, note="Erken uyarı kaydı")
        db.session.commit()

        assert result.warning_recorded_at is not None
        # Real behavior: record_first_warning's own body sets
        # process.status = "first_low_warning" directly (line ~1323), but
        # then unconditionally calls _sync_current_stage(process), whose own
        # state-machine logic checks president_approved_at FIRST -- since
        # that is still None here, _sync_current_stage overwrites status
        # right back to "president_approval_pending", discarding the value
        # record_first_warning had just set two lines earlier. So the
        # *final* status after this call is still "president_approval_pending",
        # not "first_low_warning" -- the warning IS recorded
        # (warning_recorded_at proves it), but the process's own status/stage
        # labels still reflect "awaiting Başkan/Üst Onay" until that
        # approval actually happens.
        assert result.status == "president_approval_pending"
        assert result.current_stage_key == "president_approval_pending"
        # But is_finalized_for_publish still requires president approval
        # FIRST (checked before warning_recorded_at in the model property),
        # so the record is still not considered finalized even though the
        # warning step itself now shows "done".
        assert result.is_finalized_for_publish is False

    with ls_app.app_context():
        events = _events_by_key(process_id)
        assert events["first_warning_record"].status == "done"

    # Second, independent process: sequence_no stays 1 (first offense), but
    # start_second_repeat_admin_process is invoked directly anyway (as the
    # "/start-admin-process" admin route would if used out of its intended
    # sequence). Real behavior: it does not check is_second_or_later/
    # sequence_no either -- it unconditionally sets
    # administrative_process_started_at and forces process_type/status to the
    # "second repeat" labels.
    period_2 = _create_period(ls_app, start=date(2026, 4, 1), end=date(2026, 6, 30))
    other_employee = _create_user(ls_app)
    eval_2 = _create_evaluation(ls_app, period_id=period_2, employee_id=other_employee, final_total_100=67.0)

    with ls_app.app_context():
        evaluation_2 = db.session.get(PerformanceEvaluation, eval_2)
        process_2 = svc.ensure_low_score_process_for_evaluation(evaluation_2)
        db.session.commit()
        assert process_2.sequence_no == 1

        result_2 = svc.start_second_repeat_admin_process(process_2, actor=admin_id, note="Erken idari süreç")
        db.session.commit()

        assert result_2.administrative_process_started_at is not None
        assert result_2.process_type == "second_low_score_admin_process"
        # Same _sync_current_stage overwrite as record_first_warning above:
        # start_second_repeat_admin_process's own body sets
        # process.status = "second_low_repeat" directly, but then
        # unconditionally calls _sync_current_stage(process), which checks
        # president_approved_at FIRST -- still None for process_2 here -- and
        # overwrites status/current_stage_key right back to
        # "president_approval_pending".
        assert result_2.status == "president_approval_pending"
        assert result_2.current_stage_key == "president_approval_pending"
        # sequence_no itself is left untouched by this call, so
        # is_second_or_later (which reads sequence_no, not process_type/
        # status) still reports False for this genuinely-first-offense row.
        assert result_2.sequence_no == 1
        assert result_2.is_second_or_later is False
        # Consequently is_finalized_for_publish -- which branches on
        # is_second_or_later, not on process_type/status text -- still checks
        # for warning_recorded_at (still unset here) rather than the
        # administrative_process_started_at this call just set, and Başkan
        # approval is still missing too, so the record is not finalized.
        assert result_2.is_finalized_for_publish is False


# ---------------------------------------------------------------------------
# calculate_sequence_no: schema-not-ready fallback, exercised directly (the
# existing test suite only exercises this indirectly through
# ensure_low_score_processes_for_period's schema_missing branch).
# ---------------------------------------------------------------------------


def test_calculate_sequence_no_falls_back_to_one_when_low_score_tables_missing(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    app_obj = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app_obj))
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess, PerformanceLowScoreProcessEvent

    with app_obj.app_context():
        PerformanceLowScoreProcessEvent.__table__.drop(db.engine)
        PerformanceLowScoreProcess.__table__.drop(db.engine)

        # A transient (never added/committed) evaluation is enough here --
        # calculate_sequence_no's schema-missing guard
        # (_low_score_tables_ready()) short-circuits before any real query
        # against this evaluation's own attributes ever runs. A persisted,
        # freshly-fetched evaluation would instead trip over an unrelated
        # fact: PerformanceEvaluation.low_score_process (the backref at
        # app/models/performance_low_score_models.py:78) is lazy="joined",
        # so any real SELECT of a PerformanceEvaluation row unconditionally
        # LEFT OUTER JOINs performance_low_score_processes regardless of
        # this function's own guard -- not what this test is about.
        evaluation = PerformanceEvaluation(employee_id=999999, final_total_100=50.0)
        # _low_score_tables_ready() is False -> calculate_sequence_no takes
        # its documented early-return fallback of 1, regardless of history.
        assert svc.calculate_sequence_no(evaluation) == 1
        # ensure_low_score_process_for_evaluation's own schema guard means it
        # also safely no-ops (returns None) rather than raising against the
        # now-missing tables, for a genuinely low-scoring evaluation.
        assert svc.ensure_low_score_process_for_evaluation(evaluation) is None


def test_ensure_low_score_process_for_evaluation_returns_none_for_none_evaluation(ls_app) -> None:
    with ls_app.app_context():
        assert svc.ensure_low_score_process_for_evaluation(None) is None


# ---------------------------------------------------------------------------
# get_low_score_employee_publish_lock_reason / is_low_score_employee_publish_released:
# the live aliases actually imported by app/services/performance/visibility_guard.py
# (is_employee_visible, get_evaluation_visibility_state) and
# app/services/performance/personnel_support_publish_approval_service.py.
# ---------------------------------------------------------------------------


def test_publish_lock_reason_with_ensure_true_releases_only_after_full_approval_chain(ls_app) -> None:
    from app.extensions import db

    employee_id = _create_user(ls_app)
    president_id = _create_user(ls_app, role="baskan")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=57.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)

        # Before any process exists yet: ensure=True creates it and reports
        # the real "Başkan onayı bekliyor" pending reason.
        reason = svc.get_low_score_employee_publish_lock_reason(evaluation, ensure=True)
        db.session.commit()
        assert reason is not None
        assert "Başkan" in reason
        assert svc.is_low_score_employee_publish_released(evaluation) is False

        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        assert process is not None
        svc.president_approve_process(process, actor=president_id)
        db.session.commit()
        assert process.is_finalized_for_publish is True

        # With the process argument passed directly (the shape
        # get_low_score_publish_block_reason's real DB-lookup path supports),
        # the lock is genuinely released once Başkan approval + the
        # auto-recorded warning are both in place.
        assert svc.get_low_score_publish_block_reason(process=process, ensure=False) is None


def test_publish_lock_reason_for_non_low_score_evaluation_is_always_released(ls_app) -> None:
    from app.extensions import db

    employee_id = _create_user(ls_app)
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=88.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert svc.get_low_score_employee_publish_lock_reason(evaluation, ensure=True) is None
        assert svc.is_low_score_employee_publish_released(evaluation) is True

def test_publish_lock_reason_with_ensure_false_finds_already_finalized_process(ls_app) -> None:
    """BYS360 DEFECT AR: `get_low_score_publish_block_reason(evaluation=...,
    ensure=False)` previously never looked up an already-persisted
    PerformanceLowScoreProcess row -- it would report a genuinely finalized
    (Başkan-approved + warning-recorded) low-score evaluation as permanently
    publish-locked, forever, because `ensure=False` skipped both creation
    AND lookup. Fixed to do a read-only lookup before falling through to the
    "blocked" default. This is the corrected counterpart to
    test_publish_lock_reason_with_ensure_true_releases_only_after_full_approval_chain
    above, using the `evaluation=` + `ensure=False` call shape instead of
    passing `process` directly -- exactly the shape
    visibility_guard.py/personnel_support_publish_approval_service.py's live
    callers use."""
    from app.extensions import db

    employee_id = _create_user(ls_app)
    president_id = _create_user(ls_app, role="baskan")
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=57.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        process = svc.ensure_low_score_process_for_evaluation(evaluation)
        db.session.commit()
        svc.president_approve_process(process, actor=president_id)
        db.session.commit()
        assert process.is_finalized_for_publish is True

        # Before the fix: this returned the "Başkan onayı bekliyor" blocked
        # message unconditionally, even though approval already happened.
        reason = svc.get_low_score_publish_block_reason(evaluation=evaluation, ensure=False)
        assert reason is None
        assert svc.is_low_score_employee_publish_released(evaluation) is True


def test_publish_lock_reason_with_ensure_false_still_blocks_when_no_process_exists(ls_app) -> None:
    """Negative counterpart: ensure=False must still report the safe
    "pending" default (not silently unblock) when no process has ever been
    created for a low-score evaluation."""
    from app.extensions import db

    employee_id = _create_user(ls_app)
    period_id = _create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=57.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        reason = svc.get_low_score_publish_block_reason(evaluation=evaluation, ensure=False)
        assert reason is not None
        assert "Başkan" in reason
        assert svc.is_low_score_employee_publish_released(evaluation) is False
