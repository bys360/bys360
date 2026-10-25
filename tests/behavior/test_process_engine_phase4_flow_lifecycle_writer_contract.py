"""Behavioral contract tests for
app/services/performance/process_engine_phase4_flow.py's
``ensure_process_flow_for_evaluation`` -- the production-reachable writer
introduced to close the gap AN/AO's investigations confirmed: nothing in
production ever created a ``performance_process_flows`` row, so the
already-correct Phase8 Süreç Takibi read path had no real data to show.

This function is called from the same, already-live trigger point
``app/services/performance_v2/evaluation_workspace.py::submit_assignment()``
already uses for ``low_score_process_service.ensure_low_score_process_for_
evaluation`` -- the moment an evaluation's own ``status`` reaches a terminal
value (level 1's submission). It deliberately does not read or reproduce
that sibling function's business decision (whether the evaluation is a
low-score case requiring president approval): the general flow tracks the
evaluation's own process state only, and ``PerformanceLowScoreProcess``
stays the sole source of truth for the low-score/president-approval
workflow.

Fixture setup mirrors the proven pattern from
tests/behavior/test_evaluation_workspace_submission_workflow_contract.py
(``_setup_full_chain``/``_make_app``) -- an independent tmp-db directory
keeps this file's DB state isolated from that one.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

# Deliberately not imported at module level -- importing app.models/
# app.services here at collection time would transitively import config.py
# before this file's own _make_app() can patch Config.SQLALCHEMY_DATABASE_URI,
# silently freezing every test onto a stale in-memory engine (the same
# forensic root-cause documented in the sibling submission-workflow test file).
User: Any = None
PerformancePeriod: Any = None
PerformanceCriteria: Any = None
PerformanceEvaluation: Any = None
EvaluationAssignment: Any = None
PerformanceProcessFlow: Any = None
PerformanceLowScoreProcess: Any = None
evaluation_workspace: Any = None
process_engine_phase4_flow: Any = None


def _import_symbols() -> None:
    global User, PerformancePeriod, PerformanceCriteria, PerformanceEvaluation
    global EvaluationAssignment, PerformanceProcessFlow, PerformanceLowScoreProcess
    global evaluation_workspace, process_engine_phase4_flow

    if evaluation_workspace is not None:
        return

    from app.models import (
        EvaluationAssignment as _EvaluationAssignment,
        PerformanceCriteria as _PerformanceCriteria,
        PerformanceEvaluation as _PerformanceEvaluation,
        PerformancePeriod as _PerformancePeriod,
        User as _User,
    )
    from app.models.performance_low_score_models import (
        PerformanceLowScoreProcess as _PerformanceLowScoreProcess,
    )
    from app.models.performance_process_engine_models import (
        PerformanceProcessFlow as _PerformanceProcessFlow,
    )
    from app.services.performance import process_engine_phase4_flow as _process_engine_phase4_flow
    from app.services.performance_v2 import evaluation_workspace as _evaluation_workspace

    User = _User
    PerformancePeriod = _PerformancePeriod
    PerformanceCriteria = _PerformanceCriteria
    PerformanceEvaluation = _PerformanceEvaluation
    EvaluationAssignment = _EvaluationAssignment
    PerformanceProcessFlow = _PerformanceProcessFlow
    PerformanceLowScoreProcess = _PerformanceLowScoreProcess
    evaluation_workspace = _evaluation_workspace
    process_engine_phase4_flow = _process_engine_phase4_flow


_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ap")
_user_counter = 0


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ap-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_ap_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    _import_symbols()

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
def ap_app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role: str = "personel", manager_sicils: tuple[str | None, str | None, str | None] | None = None) -> tuple[int, str]:
    from app.extensions import db

    suffix = _next_suffix()
    with app.app_context():
        sicil = f"AP{suffix:06d}"
        user = User(
            sicil_no=sicil,
            email=f"defect-ap-{suffix}@bys360.test",
            ad="Contract",
            soyad=f"User{suffix}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        if manager_sicils:
            user.yonetici_sicil, user.ikinci_yonetici_sicil, user.ucuncu_yonetici_sicil = manager_sicils
        user.set_password("DefectApContractTest1!")
        db.session.add(user)
        db.session.commit()
        return user.id, sicil


def _create_period(app, *, start: date, end: date) -> int:
    from app.extensions import db

    suffix = _next_suffix()
    with app.app_context():
        period = PerformancePeriod(
            title=f"Defect AP Dönem {suffix}",
            period_type="quarterly",
            start_date=start,
            end_date=end,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _create_criteria(app, *, count: int = 2) -> list[int]:
    from app.extensions import db

    ids: list[int] = []
    with app.app_context():
        for i in range(count):
            criterion = PerformanceCriteria(
                name=f"Kriter DefectAP {_next_suffix()}",
                weight=50.0,
                sort_order=i,
                is_active=True,
            )
            db.session.add(criterion)
            db.session.flush()
            ids.append(criterion.id)
        db.session.commit()
    return ids


def _create_assignment(app, *, period_id: int, employee_id: int, evaluator_id: int, manager_level: int, status: str = "bekliyor") -> int:
    from app.extensions import db

    with app.app_context():
        assignment = EvaluationAssignment(
            period_id=period_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            manager_level=manager_level,
            status=status,
        )
        db.session.add(assignment)
        db.session.commit()
        return assignment.id


def _setup_full_chain(app, *, criteria_ids: list[int] | None = None) -> dict[str, Any]:
    """Employee + 3 real managers (linked via explicit sicil fields) + period
    (scoring window open, in the past) + 2 active criteria + one
    EvaluationAssignment per level (3, 2, 1). Identical shape to the proven
    pattern in test_evaluation_workspace_submission_workflow_contract.py.

    PerformanceCriteria rows are global (not period-scoped) and every
    active one is required to have a score before a submission validates,
    so a second chain built in the same test MUST reuse the first chain's
    own criteria_ids (pass it in) rather than create a second active set --
    otherwise the first chain's own submissions start failing validation
    for criteria that belong to the unrelated second chain."""
    l1_id, l1_sicil = _create_user(app, role="grup_baskani")
    l2_id, l2_sicil = _create_user(app, role="koordinator")
    l3_id, l3_sicil = _create_user(app, role="birim_sorumlusu")
    employee_id, _employee_sicil = _create_user(
        app,
        role="personel",
        manager_sicils=(l1_sicil, l2_sicil, l3_sicil),
    )
    period_id = _create_period(app, start=date(2020, 1, 1), end=date(2020, 3, 31))
    if criteria_ids is None:
        criteria_ids = _create_criteria(app, count=2)

    a3 = _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=l3_id, manager_level=3)
    a2 = _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=l2_id, manager_level=2)
    a1 = _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=l1_id, manager_level=1)

    return {
        "employee_id": employee_id,
        "period_id": period_id,
        "criteria_ids": criteria_ids,
        "l1_id": l1_id,
        "l2_id": l2_id,
        "l3_id": l3_id,
        "a3": a3,
        "a2": a2,
        "a1": a1,
    }


def _build_form_data(
    criteria_ids: list[int],
    *,
    scores: tuple[Any, ...] | None,
    general_comment: str | None = "Genel değerlendirme metni",
) -> dict[str, str]:
    data: dict[str, str] = {}
    if general_comment is not None:
        data["general_comment"] = general_comment
    if scores is not None:
        for criteria_id, score in zip(criteria_ids, scores, strict=True):
            data[f"score_{criteria_id}"] = str(score)
            data[f"comment_{criteria_id}"] = "Kriter yorumu"
    return data


def _submit_full_chain(app, scn: dict[str, Any], *, scores: tuple[Any, ...]):
    """Drives level 3 -> level 2 -> level 1 to completion with the given
    per-criterion scores at every scoring level, exactly matching the real
    submission sequence a live scoring workspace request performs -- no
    performance_process_flows row is ever seeded manually anywhere in this
    helper."""
    from app.extensions import db

    criteria_ids = scn["criteria_ids"]
    with app.app_context():
        evaluation_workspace.submit_assignment(scn["a3"], _build_form_data(criteria_ids, scores=None, general_comment="Üst görüş"))
        db.session.commit()
    with app.app_context():
        evaluation_workspace.submit_assignment(scn["a2"], _build_form_data(criteria_ids, scores=scores))
        db.session.commit()
    with app.app_context():
        assignment1, evaluation = evaluation_workspace.submit_assignment(scn["a1"], _build_form_data(criteria_ids, scores=scores))
        db.session.commit()
        return evaluation.id


# ---------------------------------------------------------------------------
# Direct unit tests of ensure_process_flow_for_evaluation.
# ---------------------------------------------------------------------------


def test_ensure_process_flow_returns_none_for_missing_evaluation(ap_app) -> None:
    with ap_app.app_context():
        assert process_engine_phase4_flow.ensure_process_flow_for_evaluation(None) is None


def test_ensure_process_flow_direct_call_twice_reuses_same_row(ap_app) -> None:
    """Section 7's own required proof, at the function level: first call
    creates one flow, second identical call returns the same row -- no
    duplicate. PerformanceEvaluation is created directly here (not via the
    real submission chain) to isolate ensure_process_flow_for_evaluation's
    own idempotency from the lazy-evaluation-creation mechanism, which is
    a different, already-proven concern."""
    scn = _setup_full_chain(ap_app)
    with ap_app.app_context():
        from app.extensions import db

        evaluation = PerformanceEvaluation(
            period_id=scn["period_id"],
            employee_id=scn["employee_id"],
            status="tamamlandi",
            workflow_status="tamamlandi",
            final_total_100=82.5,
        )
        db.session.add(evaluation)
        db.session.commit()

        first = process_engine_phase4_flow.ensure_process_flow_for_evaluation(evaluation)
        db.session.commit()
        second = process_engine_phase4_flow.ensure_process_flow_for_evaluation(evaluation)
        db.session.commit()

        assert first.id == second.id
        assert PerformanceProcessFlow.query.filter_by(evaluation_id=evaluation.id).count() == 1


# ---------------------------------------------------------------------------
# Real end-to-end proof (section 13): trigger the real upstream lifecycle
# event through submit_assignment(), never seed performance_process_flows
# manually, then read it back through the real Phase8 path.
# ---------------------------------------------------------------------------


def test_normal_evaluation_creates_exactly_one_general_flow_no_manual_seed(ap_app) -> None:
    """User proof #1: a normal (non-low-score) evaluation creates exactly
    one general process flow via the real submission chain."""
    scn = _setup_full_chain(ap_app)
    evaluation_id = _submit_full_chain(ap_app, scn, scores=(5, 5))

    with ap_app.app_context():
        evaluation = db_get(PerformanceEvaluation, evaluation_id)
        assert evaluation.final_total_100 >= 70.0, "test setup expected a non-low-score final result"

        flows = PerformanceProcessFlow.query.filter_by(evaluation_id=evaluation_id).all()
        assert len(flows) == 1
        flow = flows[0]
        assert flow.period_id == scn["period_id"]
        assert flow.employee_id == scn["employee_id"]
        assert flow.current_status == "tamamlandi"
        assert flow.is_finalized is True
        assert float(flow.final_score) == pytest.approx(float(evaluation.final_total_100))

        # No PerformanceLowScoreProcess should exist for a non-low-score result.
        assert PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation_id).count() == 0


def test_low_score_evaluation_creates_general_flow_and_low_score_process_distinctly(ap_app) -> None:
    """User proofs #2 and #3: a low-score evaluation creates exactly one
    general flow AND its existing low-score process, and the two records
    have distinct responsibilities -- the general flow does not duplicate
    the low-score workflow's own business state."""
    scn = _setup_full_chain(ap_app)
    evaluation_id = _submit_full_chain(ap_app, scn, scores=(1, 1))

    with ap_app.app_context():
        evaluation = db_get(PerformanceEvaluation, evaluation_id)
        assert evaluation.final_total_100 < 70.0, "test setup expected a low-score final result"

        flows = PerformanceProcessFlow.query.filter_by(evaluation_id=evaluation_id).all()
        assert len(flows) == 1
        flow = flows[0]
        assert flow.current_status == "tamamlandi"
        assert flow.is_finalized is True

        # Distinct responsibility: the general flow does not decide or mirror
        # the low-score/president-approval business state. Those fields stay
        # at their real model defaults -- PerformanceLowScoreProcess is the
        # sole authority on that workflow, not this record.
        assert flow.president_approval_required is False
        assert flow.president_approval_status == "not_required"
        assert flow.is_low_score is False

        low_score_processes = PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation_id).all()
        assert len(low_score_processes) == 1
        process = low_score_processes[0]
        assert process.status == "president_approval_pending"
        assert type(process) is not type(flow)  # distinct records, distinct tables


def test_repeated_completion_trigger_remains_idempotent(ap_app) -> None:
    """User proof #4: calling the general-flow ensure a second time for the
    same, already-completed evaluation does not create a duplicate."""
    scn = _setup_full_chain(ap_app)
    evaluation_id = _submit_full_chain(ap_app, scn, scores=(5, 5))

    with ap_app.app_context():
        evaluation = db_get(PerformanceEvaluation, evaluation_id)
        process_engine_phase4_flow.ensure_process_flow_for_evaluation(evaluation)
        from app.extensions import db

        db.session.commit()

        assert PerformanceProcessFlow.query.filter_by(evaluation_id=evaluation_id).count() == 1


def test_phase8_tracking_shows_the_flow_created_by_real_submission(ap_app) -> None:
    """User proof #5: Phase8's real read path shows the flow the submission
    chain created -- performance_process_flows is never seeded manually
    anywhere in this test."""
    from app.services.performance.process_engine_phase8_tracking import (
        build_process_tracking_workspace,
    )

    scn = _setup_full_chain(ap_app)
    evaluation_id = _submit_full_chain(ap_app, scn, scores=(5, 5))

    class _Admin:
        id = 1
        is_admin = True
        is_superuser = False
        role = "admin"
        unvan = None

    with ap_app.app_context():
        workspace = build_process_tracking_workspace(_Admin(), status_filter="all", search="", limit=300)

    items_by_evaluation = {item["evaluation_id"]: item for item in workspace["items"]}
    assert evaluation_id in items_by_evaluation
    item = items_by_evaluation[evaluation_id]
    assert item["employee_id"] == scn["employee_id"]
    assert item["bucket"] == "completed"
    assert item["waiting_days"] == 0
    assert item["is_overdue"] is False


# ---------------------------------------------------------------------------
# Negative tests (section 14).
# ---------------------------------------------------------------------------


def test_unrelated_evaluation_does_not_receive_a_flow(ap_app) -> None:
    scn_a = _setup_full_chain(ap_app)
    # scn_b reuses scn_a's own criteria (see _setup_full_chain's own note --
    # PerformanceCriteria is global, not period-scoped) and is deliberately
    # never submitted, so no PerformanceEvaluation row exists for it either
    # (evaluations are themselves lazily created on first submission).
    scn_b = _setup_full_chain(ap_app, criteria_ids=scn_a["criteria_ids"])
    evaluation_id_a = _submit_full_chain(ap_app, scn_a, scores=(5, 5))

    with ap_app.app_context():
        assert PerformanceEvaluation.query.filter_by(
            period_id=scn_b["period_id"], employee_id=scn_b["employee_id"]
        ).first() is None

        assert PerformanceProcessFlow.query.filter_by(evaluation_id=evaluation_id_a).count() == 1
        assert PerformanceProcessFlow.query.filter_by(employee_id=scn_b["employee_id"]).count() == 0


def test_intermediate_level_submission_does_not_yet_create_a_flow(ap_app) -> None:
    """A general flow reflects the evaluation's own canonical lifecycle
    (real completion), not every intermediate manager-level submission --
    matching the exact same gating condition the sibling low-score hook
    already uses at this call site."""
    from app.extensions import db

    scn = _setup_full_chain(ap_app)
    criteria_ids = scn["criteria_ids"]
    with ap_app.app_context():
        evaluation_workspace.submit_assignment(scn["a3"], _build_form_data(criteria_ids, scores=None, general_comment="Üst görüş"))
        db.session.commit()
    with ap_app.app_context():
        _, evaluation = evaluation_workspace.submit_assignment(scn["a2"], _build_form_data(criteria_ids, scores=(3, 3)))
        db.session.commit()
        assert evaluation.status == "devam_ediyor"
        assert PerformanceProcessFlow.query.filter_by(evaluation_id=evaluation.id).count() == 0


def db_get(model: Any, object_id: int) -> Any:
    from app.extensions import db

    return db.session.get(model, object_id)
