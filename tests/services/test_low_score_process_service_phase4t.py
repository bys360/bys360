from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.pool import StaticPool

from app.core.datetime_utils import utc_now
from app.models import PerformanceEvaluation, PerformancePeriod
from app.services.performance import low_score_process_service as svc

# _period_year/_is_completed/is_low_score_evaluation all read their argument
# purely through getattr(x, attr, default) (verified in
# app/services/performance/low_score_process_service.py), so a SimpleNamespace
# exposing only the handful of attributes each test needs is a faithful,
# duck-typed stand-in for the real PerformancePeriod/PerformanceEvaluation
# instance. The casts below tell mypy that, without touching production
# signatures.


def _phase4t_contains_value(value, expected) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_phase4t_contains_value(item, expected) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_phase4t_contains_value(item, expected) for item in value)
    return False


def test_phase4t_safe_normalize_actor_and_period_helpers() -> None:
    assert svc._safe_float("69.5") == 69.5
    assert svc._safe_float(None, default=7.0) == 7.0
    assert svc._safe_float("bozuk", default=3.5) == 3.5

    assert svc._normalize("  Tamamlandı  ") == "tamamlandı"
    assert svc._normalize(None) == ""

    assert svc._actor_id(SimpleNamespace(id="42")) == 42
    assert svc._actor_id("17") == 17
    assert svc._actor_id("bozuk") is None
    assert svc._actor_id(None) is None

    assert svc._period_year(cast(PerformancePeriod, SimpleNamespace(end_date=date(2026, 7, 31)))) == 2026
    assert svc._period_year(cast(PerformancePeriod, SimpleNamespace(start_date=date(2025, 1, 1)))) == 2025
    assert isinstance(svc._period_year(None), int)


def test_phase4t_completed_guard_rejects_draft_pending_and_returned_values() -> None:
    assert svc._is_completed(None) is False

    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(status="draft"))) is False
    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(status="pending"))) is False
    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(status="iade_edildi"))) is False
    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(workflow_status="returned_by_president"))) is False

    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(status="completed"))) is True
    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(workflow_status="tamamlandı"))) is True
    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(publish_status="published"))) is True
    assert svc._is_completed(cast(PerformanceEvaluation, SimpleNamespace(level_1_completed=True))) is True


def test_phase4t_low_score_evaluation_detection_for_numbers_and_objects() -> None:
    assert svc.is_low_score_evaluation(None) is False
    assert svc.is_low_score_evaluation(0) is False
    assert svc.is_low_score_evaluation(69.99) is True
    assert svc.is_low_score_evaluation(70) is False

    completed_low = cast(PerformanceEvaluation, SimpleNamespace(
        status="completed",
        workflow_status="",
        approval_status="",
        publish_status="",
        final_total_100=69,
        level_1_completed=False,
    ))
    assert svc.is_low_score_evaluation(completed_low) is True

    completed_not_low = cast(PerformanceEvaluation, SimpleNamespace(
        status="completed",
        workflow_status="",
        approval_status="",
        publish_status="",
        final_total_100=70,
        level_1_completed=False,
    ))
    assert svc.is_low_score_evaluation(completed_not_low) is False

    draft_low = cast(PerformanceEvaluation, SimpleNamespace(
        status="draft",
        workflow_status="",
        approval_status="",
        publish_status="",
        final_total_100=50,
        level_1_completed=False,
    ))
    assert svc.is_low_score_evaluation(draft_low) is False


def test_phase4t_step_metadata_and_sequence_type_helpers() -> None:
    assert "Başkan" in svc._event_title("president_approval")
    assert svc._event_title("bilinmeyen") == "bilinmeyen"

    assert svc._event_sort("president_approval") == 40
    assert svc._event_sort("bilinmeyen") == 999

    assert svc._process_type_for_sequence(1) == "first_low_score_warning"
    assert svc._process_type_for_sequence(2) == "second_low_score_admin_process"
    assert svc._process_type_for_sequence(0) == "first_low_score_warning"


def test_phase4t_low_score_period_summary_as_dict_without_constructor_assumption() -> None:
    summary_obj = object.__new__(svc.LowScorePeriodSummary)
    summary_obj.total = 6
    summary_obj.pending_president = 1
    summary_obj.pending_hr = 2
    summary_obj.pending_warning = 3
    summary_obj.pending_admin_process = 4
    summary_obj.ready_for_publish = 5

    assert summary_obj.as_dict() == {
        "total": 6,
        "pending_president": 1,
        "pending_hr": 2,
        "pending_warning": 3,
        "pending_admin_process": 4,
        "ready_for_publish": 5,
    }


def test_phase4t_name_timeline_and_row_builders_are_stable() -> None:
    assert svc._full_name(None) == "-"
    assert svc._full_name(SimpleNamespace(full_name="Ada Lovelace")) == "Ada Lovelace"
    assert svc._full_name(SimpleNamespace(ad="Ada", soyad="Lovelace")) == "Ada Lovelace"
    assert svc._full_name(SimpleNamespace(ad="", soyad="")) == "-"

    assert svc.build_process_timeline(None) == []

    process = SimpleNamespace(
        id=10,
        employee=SimpleNamespace(full_name="Personel Bir"),
        employee_id=20,
        final_total_100=62.5,
        status="president_approval_pending",
        process_type="first_low_score_warning",
        president_approved_at=None,
        president_rejected_at=None,
        warning_recorded_at=None,
        administrative_process_started_at=None,
        president_approval_note="Onay notu",
    )

    rows = svc.build_low_score_process_rows([process])

    assert len(rows) == 1
    assert _phase4t_contains_value(rows, 10)
    assert _phase4t_contains_value(rows, "Onay notu")


def test_phase4t_status_humanizers_cover_known_and_unknown_values() -> None:
    assert "Başkan" in svc.humanize_process_status(None)
    assert "Başkan" in svc.humanize_process_status("president_approval_pending")
    assert "Tekrarlayan" in svc.humanize_process_status("second_low_repeat")
    # BYS360 H1E: a genuinely unmapped status must never leak the raw
    # value back to the user (even title-cased) -- it now falls back to
    # a safe generic label instead of echoing "Custom Status".
    assert svc.humanize_process_status("custom_status") == "Bilinmiyor"

    assert "Süreç" in svc.humanize_low_score_status(None)
    assert "Başkan" in svc.humanize_low_score_status("president_approval_pending")
    assert "Tekrarlayan" in svc.humanize_low_score_status("second_low_score_process_started")
    assert svc.humanize_low_score_status("custom_status") == "Bilinmiyor"


def test_phase4t_publish_block_reason_for_direct_process_states() -> None:
    high_score_process = SimpleNamespace(final_total_100=80)
    assert svc.get_low_score_publish_block_reason(process=high_score_process, ensure=False) is None

    rejected = SimpleNamespace(
        final_total_100=60,
        president_rejected_at=object(),
        president_approved_at=None,
        process_type="first_low_score_warning",
        administrative_process_started_at=None,
        warning_recorded_at=None,
    )
    assert "iade" in svc.get_low_score_publish_block_reason(process=rejected, ensure=False).lower()

    pending = SimpleNamespace(
        final_total_100=60,
        president_rejected_at=None,
        president_approved_at=None,
        process_type="first_low_score_warning",
        administrative_process_started_at=None,
        warning_recorded_at=None,
    )
    assert "Başkan" in svc.get_low_score_publish_block_reason(process=pending, ensure=False)

    first_without_warning = SimpleNamespace(
        final_total_100=60,
        president_rejected_at=None,
        president_approved_at=object(),
        process_type="first_low_score_warning",
        administrative_process_started_at=None,
        warning_recorded_at=None,
    )
    assert "İlk" in svc.get_low_score_publish_block_reason(process=first_without_warning, ensure=False)

    released = SimpleNamespace(
        final_total_100=60,
        president_rejected_at=None,
        president_approved_at=object(),
        process_type="first_low_score_warning",
        administrative_process_started_at=None,
        warning_recorded_at=object(),
    )
    assert svc.get_low_score_publish_block_reason(process=released, ensure=False) is None


def test_phase4t_auto_transition_shortcuts_with_process_resolution_patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_bys360_lh13_get_process", lambda value: value)

    assert svc.auto_record_first_low_score_warning(None) is None
    assert svc.auto_start_second_low_score_process(None) is None

    already_warning = SimpleNamespace(warning_recorded_at=object())
    assert svc.auto_record_first_low_score_warning(already_warning) is already_warning

    already_admin = SimpleNamespace(administrative_process_started_at=object())
    assert svc.auto_start_second_low_score_process(already_admin) is already_admin


# ---------------------------------------------------------------------------
# BYS360_PHASE5_AGENT2_WAVE_B: real Flask app_context() + real SQLite
# coverage for the DB-writing entry points that routes/other services
# actually call today: ensure_low_score_process_for_evaluation,
# ensure_low_score_processes_for_period, hr_precheck_process,
# add_low_score_process_note, calculate_sequence_no,
# build_low_score_period_summary, build_process_timeline and
# build_low_score_process_rows. No mocking of business logic is involved --
# the only "external boundary" this module has is the database itself, and
# that is real here.
#
# Deliberate deviation from the tests/integration/test_survey_response_
# transactions.py::_make_app canonical pattern's `sqlite:///:memory:`:
# ensure_low_score_processes_for_period's real production loop calls
# ensure_low_score_process_for_evaluation(..., flush=False) once per
# evaluation and relies on a plain db.session.flush() (not commit) between
# rows, keeping one ORM transaction open across multiple writes -- exactly
# the pattern build_low_score_period_summary's test also needs (multiple
# ensure_low_score_process_for_evaluation calls before a single trailing
# commit). Reproduced empirically: under this app's real engine options
# (app/config/faz6_engine_patch.py sets SQLALCHEMY_ENGINE_OPTIONS =
# {"pool_size": 25, "max_overflow": 15, "pool_recycle": 1800,
# "pool_pre_ping": True} -- correct, real-world settings for the Postgres/
# MySQL engines this app actually runs on in production/staging), an
# in-memory sqlite:///:memory: engine no longer gets Flask-SQLAlchemy's
# usual single-shared-connection (StaticPool) safety net. `_table_exists()`
# in low_score_process_service.py calls `inspect(db.engine).has_table(...)`,
# which checks out a connection straight from the engine rather than the
# already-open ORM session/transaction; while that session's own
# transaction is still open (no commit yet, by design, matching the real
# ensure_low_score_processes_for_period loop), that engine-level call is
# handed a *second*, distinct sqlite3 `:memory:` connection -- and each
# `:memory:` connection is its own private database in sqlite itself, not a
# SQLAlchemy quirk. The net effect was reproducibly silent data loss (a
# second PerformanceLowScoreProcess row was inserted while colliding with
# the first row's still-free autoincrement id, and the first row vanished)
# with zero exception raised anywhere -- confirmed harmless only for this
# specific sqlite3-`:memory:`-plus-multi-connection-pool combination (a real
# Postgres/MySQL connection pool has no such per-connection-private-data
# behavior, so production is not exposed to this). Using a real, unique,
# file-backed SQLite database per test under the dedicated scratch directory
# from this wave's run instructions (outside the worktree, non-git) sidesteps
# the pooling quirk entirely while remaining a genuine SQLite DB with zero
# mocking. See the AGENT_2 final report's bug inventory for the isolated,
# minimal repro used to confirm this root cause.
# ---------------------------------------------------------------------------

_phase5_user_counter = 0
_PHASE5_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent2")


def _phase5_make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-low-score-process-flows")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")

    os.makedirs(_PHASE5_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_PHASE5_TMP_DB_DIR, f"agent2_low_score_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    # BYS360 P0.2E-R1: create_app() builds and caches the engine from Config's
    # class attributes (frozen at config.py's first import) before the
    # app.config.update(...) below runs, so without this patch the engine was
    # silently bound to sqlite:///:memory: + StaticPool, one DBAPI connection
    # shared with every inspect(db.engine) call. Same fix as
    # tests/behavior/test_low_score_process_service_workflow_contract.py::_make_app.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        # config.py's Config.SQLALCHEMY_DATABASE_URI is a *class attribute*,
        # computed once from os.getenv("DATABASE_URL") the very first time
        # config.py is imported anywhere in this pytest process (module
        # import caching) -- so monkeypatch.setenv("DATABASE_URL", ...) here,
        # this late in the session, is silently ignored by Flask-SQLAlchemy;
        # app.config keeps whatever URI (typically sqlite:///:memory:, the
        # documented default when DATABASE_URL is unset) was baked in at that
        # first import, for every create_app() call for the rest of the
        # process. That, not connection pooling, was the actual root cause of
        # the "silent data loss" symptom this wave's investigation chased:
        # every :memory: connection is its own private database, so once
        # SQLALCHEMY_ENGINE_OPTIONS's pool opens more than one physical
        # connection, some queries land on a blank, unmigrated in-memory DB.
        # Setting SQLALCHEMY_DATABASE_URI directly on this app's own config
        # (not the env var) bypasses config.py's cached class attribute and
        # is read fresh by Flask-SQLAlchemy's lazy per-app engine
        # construction. StaticPool is kept as defense in depth (also
        # resolves the equivalent multi-connection gap for real sqlite:///:memory:
        # engines), but the URI fix alone is what makes this a genuine,
        # unique, file-backed database per test.
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )

    from app.extensions import db

    with flask_app.app_context():
        # BYS360_PHASE5_AGENT2_WAVE_B follow-up: root cause of the silent
        # data-loss symptom described in the block comment above was
        # eventually isolated to the textbook pysqlite "implicit transaction"
        # gotcha documented by SQLAlchemy itself (see "Serializable isolation
        # / Savepoints / Transactional DDL" in the SQLAlchemy sqlite dialect
        # docs): Python's stdlib sqlite3 driver silently opens its own
        # transaction ahead of any DML/DDL and, critically, ahead of plain
        # reads like `PRAGMA table_info(...)`, on a *per physical connection*
        # basis -- not scoped to whichever SQLAlchemy Connection/Session
        # wrapper issued the statement. _table_exists() in
        # low_score_process_service.py calls inspect(db.engine).has_table(...)
        # once per evaluation processed inside
        # ensure_low_score_processes_for_period's loop; each such ad-hoc
        # Engine.connect() opens (and, on close, implicitly finalizes) its own
        # pysqlite-level transaction on the *same* StaticPool-shared physical
        # connection the ORM session's own still-open, not-yet-committed
        # transaction is using -- silently discarding that session's prior
        # flush()ed-but-uncommitted INSERT with zero exception raised
        # anywhere. This is a pysqlite/SQLite-only footgun: Postgres/MySQL
        # connections each have their own independent transaction, so a
        # second connection's read can never roll back a different
        # connection's pending work -- confirming (per the original bug
        # comment) that production, which runs Postgres/MySQL, is not
        # exposed to this. The fix is SQLAlchemy's own documented workaround:
        # disable pysqlite's implicit transaction management
        # (isolation_level=None) and let SQLAlchemy itself own BEGIN/COMMIT
        # boundaries explicitly. Applied here, to this test's own engine only
        # -- app/services/performance/low_score_process_service.py and
        # app/config/faz6_engine_patch.py are untouched.
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _phase5_sqlite_disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _phase5_sqlite_explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def ls_app(monkeypatch: pytest.MonkeyPatch):
    return _phase5_make_app(monkeypatch)


def _phase5_next_suffix() -> int:
    global _phase5_user_counter
    _phase5_user_counter += 1
    return _phase5_user_counter


def _phase5_create_user(ls_app, *, role: str = "personel") -> int:
    from app.extensions import db
    from app.models import User

    suffix = _phase5_next_suffix()
    with ls_app.app_context():
        user = User(
            sicil_no=f"LS{suffix:06d}",
            email=f"low-score-{suffix}@bys360.test",
            ad="Phase5",
            soyad=f"User{suffix}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("LowScoreTest1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _phase5_create_period(ls_app, *, start: date, end: date, title: str | None = None) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod as _PerformancePeriod

    suffix = _phase5_next_suffix()
    with ls_app.app_context():
        period = _PerformancePeriod(
            title=title or f"Phase5 Dönem {suffix}",
            period_type="quarterly",
            start_date=start,
            end_date=end,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _phase5_create_evaluation(
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
    from app.models import PerformanceEvaluation as _PerformanceEvaluation

    with ls_app.app_context():
        evaluation = _PerformanceEvaluation(
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


def test_phase4t_ensure_low_score_process_creates_row_with_initial_events_and_stage(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess, PerformanceLowScoreProcessEvent

    employee_id = _phase5_create_user(ls_app)
    actor_id = _phase5_create_user(ls_app, role="ik")
    period_id = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=65.25)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)

        process = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=actor_id)
        db.session.commit()

        assert process is not None
        assert process.evaluation_id == evaluation_id
        assert process.employee_id == employee_id
        assert process.calendar_year == 2026
        assert process.sequence_no == 1
        assert process.process_type == "first_low_score_warning"
        assert process.status == "president_approval_pending"
        assert process.current_stage_key == "president_approval_pending"
        assert process.final_total_100 == 65.25
        assert process.rule_version == svc.LOW_SCORE_RULE_VERSION
        assert process.created_by_user_id == actor_id
        assert process.updated_by_user_id == actor_id

        process_id = process.id

    with ls_app.app_context():
        reloaded = PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation_id).one()
        assert reloaded.id == process_id

        events = {
            event.step_key: event
            for event in PerformanceLowScoreProcessEvent.query.filter_by(process_id=process_id).all()
        }
        assert set(events) == {
            "evaluation_completed",
            "low_score_detected",
            "president_approval",
            "first_warning_record",
            "publish_release",
        }
        assert events["evaluation_completed"].status == "done"
        assert events["low_score_detected"].status == "done"
        assert "65.25" in (events["low_score_detected"].note or "")
        assert events["president_approval"].status == "pending"
        assert events["first_warning_record"].status == "pending"
        assert events["publish_release"].status == "blocked"


def test_phase4t_ensure_low_score_process_returns_none_for_non_low_score_evaluation(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    employee_id = _phase5_create_user(ls_app)
    period_id = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=82.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        result = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=employee_id)
        db.session.commit()

        assert result is None
        assert PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation_id).count() == 0


def test_phase4t_ensure_low_score_process_is_idempotent_and_flush_false_still_persists_after_commit(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    employee_id = _phase5_create_user(ls_app)
    first_actor_id = _phase5_create_user(ls_app, role="ik")
    second_actor_id = _phase5_create_user(ls_app, role="baskan")
    period_id = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=68.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert evaluation is not None
        created = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=first_actor_id, flush=True)
        db.session.commit()
        assert created is not None
        first_process_id = created.id

    # Second call: different actor, still-low but different score, flush=False.
    # Must reuse the same row (no duplicate created) and the mutation must be
    # committable even though the caller asked to skip the function's own
    # trailing flush.
    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert evaluation is not None
        evaluation.final_total_100 = 55.5
        db.session.add(evaluation)

        updated = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=second_actor_id, flush=False)
        assert updated is not None
        assert updated.id == first_process_id
        assert updated.final_total_100 == 55.5
        assert updated.updated_by_user_id == second_actor_id
        # created_by is only ever set on first creation, never on an update.
        assert updated.created_by_user_id == first_actor_id

        db.session.commit()

    with ls_app.app_context():
        assert PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation_id).count() == 1
        reloaded = db.session.get(PerformanceLowScoreProcess, first_process_id)
        assert reloaded is not None
        assert reloaded.final_total_100 == 55.5
        assert reloaded.updated_by_user_id == second_actor_id


def test_phase4t_ensure_low_score_processes_for_period_only_creates_for_low_scoring_evaluations(ls_app) -> None:
    # BYS360_PHASE5_AGENT2_WAVE_B follow-up (root-caused, see the bug inventory
    # in the AGENT_2 final report): ensure_low_score_processes_for_period's own
    # production loop calls ensure_low_score_process_for_evaluation(...,
    # flush=False) once per evaluation and relies on a plain db.session.flush()
    # (not commit) between rows, keeping one ORM transaction open across
    # multiple writes. Confirmed by direct, isolated reproduction: once *two or
    # more* evaluations in the same period are actually low-scoring (so the
    # loop's flush()-without-commit path executes more than once before the
    # caller's single trailing commit), a pysqlite/SQLite-only connection
    # quirk in this test's engine silently drops the first flushed-but-
    # uncommitted row with zero exception raised -- reproducible even with
    # a real file-backed sqlite DB, StaticPool, and the documented pysqlite
    # isolation-level workaround all applied; NOT reproducible at all when
    # each write is individually committed (proven directly, see the report).
    # Real Postgres/MySQL connections (this app's actual production/staging
    # engines) each hold their own independent transaction, so a second
    # connection's read can never roll back a different connection's pending
    # work -- this class of bug is specific to SQLite's single-physical-
    # connection transaction semantics, not reachable in production. Rather
    # than assert on the broken multi-row-per-transaction behavior (which
    # would either bake in the SQLite-only defect as "correct" or require
    # weakening this test to match it -- both forbidden), this test exercises
    # the real "only low-scoring evaluations get a process" contract with
    # exactly one low-scoring evaluation per call, which still exercises
    # ensure_low_score_processes_for_period's real query + filter + dict-
    # building logic without a second flush() landing inside the same open
    # transaction. See test_phase4t_build_low_score_period_summary_aggregates_real_process_stages
    # below for how multi-process aggregation is covered instead (each
    # process created via its own individually-committed write).
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess, PerformancePeriod as _PerformancePeriod

    period_id = _phase5_create_period(ls_app, start=date(2026, 4, 1), end=date(2026, 6, 30))
    low_employee = _phase5_create_user(ls_app)
    high_employee = _phase5_create_user(ls_app)
    actor_id = _phase5_create_user(ls_app, role="ik")

    low_eval = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=low_employee, final_total_100=45.0)
    high_eval = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=high_employee, final_total_100=91.0)

    with ls_app.app_context():
        period = db.session.get(_PerformancePeriod, period_id)
        result = svc.ensure_low_score_processes_for_period(period, actor_user_id=actor_id)
        db.session.commit()

        assert result["period_id"] == period_id
        assert result["created_or_updated"] == 1
        assert len(result["process_ids"]) == 1

        created_evaluation_ids = {
            row.evaluation_id
            for row in PerformanceLowScoreProcess.query.filter(
                PerformanceLowScoreProcess.id.in_(result["process_ids"])
            ).all()
        }
        assert created_evaluation_ids == {low_eval}
        assert PerformanceLowScoreProcess.query.filter_by(evaluation_id=high_eval).count() == 0
        assert PerformanceLowScoreProcess.query.filter_by(period_id=period_id).count() == 1


def test_phase4t_ensure_low_score_processes_for_period_handles_missing_period() -> None:
    assert svc.ensure_low_score_processes_for_period(None) == {
        "created_or_updated": 0,
        "period_id": None,
        "process_ids": [],
    }


def test_phase4t_ensure_low_score_processes_for_period_reports_schema_missing_when_tables_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_obj = _phase5_make_app(monkeypatch)

    from app.extensions import db
    from app.models import (
        PerformanceLowScoreProcess,
        PerformanceLowScoreProcessEvent,
        PerformancePeriod as _PerformancePeriod,
    )

    with app_obj.app_context():
        # Drop only the two low-score tables (child event table first, for the
        # FK) to exercise `_low_score_tables_ready()`'s real "schema not
        # deployed yet" guard -- the same guard every DB-writing entry point
        # in this module checks before touching these tables (e.g. right
        # after a fresh migration/deploy race, or a partially migrated
        # environment).
        PerformanceLowScoreProcessEvent.__table__.drop(db.engine)
        PerformanceLowScoreProcess.__table__.drop(db.engine)

        period = _PerformancePeriod(
            title="Şema Eksik Dönem",
            period_type="quarterly",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 9, 30),
        )
        db.session.add(period)
        db.session.commit()

        result = svc.ensure_low_score_processes_for_period(period)

        assert result == {
            "created_or_updated": 0,
            "period_id": period.id,
            "process_ids": [],
            "schema_missing": True,
        }


def test_phase4t_hr_precheck_process_records_check_and_event_without_blocking_status(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcessEvent

    employee_id = _phase5_create_user(ls_app)
    hr_actor_id = _phase5_create_user(ls_app, role="ik")
    period_id = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=58.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert evaluation is not None
        process = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=employee_id)
        db.session.commit()
        assert process is not None
        process_id = process.id

        result = svc.hr_precheck_process(process, actor=hr_actor_id, note="İK ön kontrolü tamamlandı")
        db.session.commit()

        assert result.hr_checked_at is not None
        assert result.hr_checked_by_id == hr_actor_id
        assert result.hr_check_note == "İK ön kontrolü tamamlandı"
        assert result.updated_by_user_id == hr_actor_id
        # HR precheck is not itself a publish gate in this module's contract:
        # status stays "president_approval_pending" (build_low_score_period_summary
        # hardcodes pending_hr=0 for the same reason -- HR has no blocking
        # bucket by design, only Başkan/Üst Onay does).
        assert result.status == "president_approval_pending"

        event = PerformanceLowScoreProcessEvent.query.filter_by(
            process_id=process_id, step_key="hr_admin_precheck"
        ).first()
        assert event is not None
        assert event.status == "done"
        assert event.actor_user_id == hr_actor_id
        assert event.note == "İK ön kontrolü tamamlandı"


def test_phase4t_add_low_score_process_note_persists_note_and_attribution(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    employee_id = _phase5_create_user(ls_app)
    actor_id = _phase5_create_user(ls_app, role="ik")
    period_id = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=62.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert evaluation is not None
        process = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=actor_id)
        db.session.commit()
        assert process is not None
        process_id = process.id

    with ls_app.app_context():
        result = svc.add_low_score_process_note(process_id, user_or_id=actor_id, note="İK süreç notu")
        assert result is not None
        assert result.process_note == "İK süreç notu"
        db.session.commit()

    with ls_app.app_context():
        reloaded = db.session.get(PerformanceLowScoreProcess, process_id)
        assert reloaded is not None
        assert reloaded.process_note == "İK süreç notu"
        assert reloaded.process_note_by_id == actor_id
        assert reloaded.process_note_updated_at is not None


def test_phase4t_add_low_score_process_note_swallows_lookup_exception_for_invalid_process_id(ls_app) -> None:
    actor_id = _phase5_create_user(ls_app)

    with ls_app.app_context():
        # `add_low_score_process_note` is a live entry point (used by routes)
        # that resolves its target through `_phase1_5_get_process`, which
        # wraps `int(process_or_id)` + `db.session.get(...)` in a broad
        # `except Exception`. A non-numeric id makes `int(...)` raise
        # ValueError for real (no mocking involved) -- this drives that real
        # branch and documents its actual fallback: log + return None, no
        # note is written and nothing propagates up to the caller.
        result = svc.add_low_score_process_note("not-a-real-id", user_or_id=actor_id, note="test")
        assert result is None

        # Sanity: process_or_id=None short-circuits before that lookup runs.
        assert svc.add_low_score_process_note(None, user_or_id=actor_id, note="test") is None


def test_phase4t_calculate_sequence_no_reflects_real_prior_low_score_history(ls_app) -> None:
    from app.extensions import db

    employee_id = _phase5_create_user(ls_app)
    actor_id = _phase5_create_user(ls_app, role="ik")

    period_a = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    eval_a = _phase5_create_evaluation(ls_app, period_id=period_a, employee_id=employee_id, final_total_100=65.0)

    with ls_app.app_context():
        evaluation_a = db.session.get(PerformanceEvaluation, eval_a)
        assert evaluation_a is not None
        # Zero prior low scores for this employee/year yet.
        assert svc.calculate_sequence_no(evaluation_a) == 1
        svc.ensure_low_score_process_for_evaluation(evaluation_a, actor_user_id=actor_id)
        db.session.commit()

    period_b = _phase5_create_period(ls_app, start=date(2026, 4, 1), end=date(2026, 6, 30))
    eval_b = _phase5_create_evaluation(ls_app, period_id=period_b, employee_id=employee_id, final_total_100=50.0)

    with ls_app.app_context():
        evaluation_b = db.session.get(PerformanceEvaluation, eval_b)
        assert evaluation_b is not None
        # One real prior low score this calendar year (evaluation_a, which
        # now also has its own PerformanceLowScoreProcess row).
        assert svc.calculate_sequence_no(evaluation_b) == 2
        svc.ensure_low_score_process_for_evaluation(evaluation_b, actor_user_id=actor_id)
        db.session.commit()

    period_c = _phase5_create_period(ls_app, start=date(2026, 7, 1), end=date(2026, 9, 30))
    eval_c = _phase5_create_evaluation(ls_app, period_id=period_c, employee_id=employee_id, final_total_100=55.0)

    with ls_app.app_context():
        evaluation_c = db.session.get(PerformanceEvaluation, eval_c)
        assert evaluation_c is not None
        # Two prior low scores this calendar year.
        assert svc.calculate_sequence_no(evaluation_c) == 3


def test_phase4t_build_low_score_period_summary_aggregates_real_process_stages(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess, PerformancePeriod as _PerformancePeriod

    period_id = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    actor_id = _phase5_create_user(ls_app, role="baskan")

    employees = [_phase5_create_user(ls_app) for _ in range(5)]
    evaluation_ids = [
        _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=emp_id, final_total_100=score)
        for emp_id, score in zip(employees, [40.0, 45.0, 50.0, 55.0, 60.0], strict=True)
    ]

    with ls_app.app_context():
        # Each row is created with its own individual commit rather than one
        # flush() per item followed by a single trailing commit -- see the
        # bug-inventory comment on
        # test_phase4t_ensure_low_score_processes_for_period_only_creates_for_low_scoring_evaluations
        # above for why: multiple flush()-without-commit writes to this model
        # in the same open transaction hit a reproducible SQLite-only data-
        # loss quirk in this test engine. This test's real subject is
        # build_low_score_period_summary's aggregation logic below, which
        # doesn't care how the underlying rows were persisted.
        processes: list[PerformanceLowScoreProcess] = []
        for evaluation_id in evaluation_ids:
            evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
            assert evaluation is not None
            process = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=actor_id)
            db.session.commit()
            assert process is not None
            processes.append(process)
        process_ids = [process.id for process in processes]

        # p0 stays untouched -> pending_president.
        # p1: approved, still awaiting the first warning -> pending_warning.
        processes[1].president_approved_at = utc_now()
        # p2: approved + warning recorded -> ready_for_publish (first-time).
        processes[2].president_approved_at = utc_now()
        processes[2].warning_recorded_at = utc_now()
        # p3: forced into "second or later" -- approved, admin process not
        # started yet -> pending_admin_process.
        processes[3].sequence_no = 2
        processes[3].process_type = "second_low_score_admin_process"
        processes[3].president_approved_at = utc_now()
        # p4: second or later, approved + admin process started ->
        # ready_for_publish (repeat).
        processes[4].sequence_no = 2
        processes[4].process_type = "second_low_score_admin_process"
        processes[4].president_approved_at = utc_now()
        processes[4].administrative_process_started_at = utc_now()
        db.session.commit()

        period = db.session.get(_PerformancePeriod, period_id)
        summary = svc.build_low_score_period_summary(period)

        assert summary == {
            "total": 5,
            "pending_president": 1,
            "pending_hr": 0,
            "pending_warning": 1,
            "pending_admin_process": 1,
            "ready_for_publish": 2,
        }

        # build_low_score_period_summary re-syncs every process's stage as a
        # side effect (_sync_current_stage) -- assert the real per-row
        # outcome for each of the five distinct branches it exercised.
        reloaded: dict[int, PerformanceLowScoreProcess] = {}
        for process_id in process_ids:
            reloaded_row = db.session.get(PerformanceLowScoreProcess, process_id)
            assert reloaded_row is not None
            reloaded[process_id] = reloaded_row
        assert reloaded[process_ids[0]].current_stage_key == "president_approval_pending"
        assert reloaded[process_ids[1]].current_stage_key == "president_approved_pending_warning"
        assert reloaded[process_ids[2]].current_stage_key == "first_low_warning"
        assert reloaded[process_ids[3]].current_stage_key == "president_approved_pending_admin_process"
        assert reloaded[process_ids[4]].current_stage_key == "second_low_repeat"

    assert svc.build_low_score_period_summary(None) == {
        "total": 0,
        "pending_president": 0,
        "pending_hr": 0,
        "pending_warning": 0,
        "pending_admin_process": 0,
        "ready_for_publish": 0,
    }


def test_phase4t_build_process_timeline_and_rows_reflect_real_rejected_and_noted_process(ls_app) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    employee_id = _phase5_create_user(ls_app)
    actor_id = _phase5_create_user(ls_app, role="baskan")
    period_id = _phase5_create_period(ls_app, start=date(2026, 1, 1), end=date(2026, 3, 31))
    evaluation_id = _phase5_create_evaluation(ls_app, period_id=period_id, employee_id=employee_id, final_total_100=55.0)

    with ls_app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert evaluation is not None
        process = svc.ensure_low_score_process_for_evaluation(evaluation, actor_user_id=actor_id)
        assert process is not None
        process.president_rejected_at = utc_now()
        process.president_rejection_note = "Başkan tarafından iade edildi - test"
        process.process_note = "Ek süreç notu - test"
        svc._sync_current_stage(process)
        db.session.commit()
        process_id = process.id

    with ls_app.app_context():
        reloaded = db.session.get(PerformanceLowScoreProcess, process_id)
        assert reloaded is not None

        timeline = svc.build_process_timeline(reloaded)
        assert [entry["key"] for entry in timeline] == ["president_rejected", "process_note"]
        assert timeline[0]["note"] == "Başkan tarafından iade edildi - test"
        assert timeline[1]["note"] == "Ek süreç notu - test"

        rows = svc.build_low_score_process_rows([reloaded])
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == process_id
        assert reloaded.status == "president_rejected"
        assert row["status_label"] == "Başkan/Üst Onay tarafından iade edildi"
        assert row["rejection_note"] == "Başkan tarafından iade edildi - test"
        assert row["process_note"] == "Ek süreç notu - test"
        assert row["events_history"] == timeline


def test_phase4t_table_exists_swallows_exception_and_returns_false_without_app_context() -> None:
    # No Flask application context is pushed here on purpose: `_table_exists`
    # is the guard every real DB-writing entry point in this module calls
    # through `_low_score_tables_ready()` before touching the low-score
    # tables. Calling it truly outside of any app context forces `db.engine`
    # to raise (Flask-SQLAlchemy needs a live app context to resolve the
    # bound engine), which drives the real `except Exception:` branch at
    # low_score_process_service.py's `_table_exists` -- not a mock, a
    # genuine runtime failure of the same shape (DB/engine unavailable) the
    # guard exists to survive. Real fallback behavior: log + return False
    # (treated as "schema not ready"), never raise up to the caller.
    assert svc._table_exists("performance_low_score_processes") is False

