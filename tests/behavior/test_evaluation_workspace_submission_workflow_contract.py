"""BYS360_PHASE5_AGENT1_EVALUATION_WORKSPACE_WORKFLOW_CONTRACT

Behavioral contract tests for app/services/performance_v2/evaluation_workspace.py,
focused on the real, currently-live submission workflow entry points:
`save_assignment_draft`, `submit_assignment`, `return_assignment_to_previous_level`
and `withdraw_assignment_submission`.

These are confirmed (via `grep -rn "submit_assignment\\|return_assignment_to_previous_level\\|
withdraw_assignment_submission\\|save_assignment_draft" app/ --include=*.py`) to be the
functions imported and called directly by app/performance/evaluation_workspace_routes.py
-- the live scoring workspace routes. The older app/performance/evaluation_core_routes.py
`main.performance_evaluate` route now redirects into this workspace flow rather than
implementing its own submission logic, so this module is the real, reachable engine.

Test data uses a plain "personel" employee with all three manager sicil fields
(yonetici_sicil / ikinci_yonetici_sicil / ucuncu_yonetici_sicil) explicitly set.
`app/services/performance_v2/chain.py::build_resolved_chain` resolves the manager
chain either from an authoritative rule engine or, when the employee carries any
explicit manager-sicil field, directly from those fields via
`app/services/performance/chain_rule_engine.py::_explicit_authoritative_chain`
(confirmed by reading `has_explicit_manager_fields` / `resolve_authoritative_chain`).
That lets these tests build a real, fully-resolved 3-level chain without needing to
also stand up the separate organizational-hierarchy/authority engine -- the manager
users' own `role` field is irrelevant to chain resolution once explicit sicil fields
are present, only their sicil_no linkage matters.

The workflow order for a plain personel (GROUP_STAFF policy) is level 3 -> level 2 ->
level 1 (level 1 is the *final* approval level, level 3 is the first-line manager).
Level 3 defaults to comment-only mode (score_enabled=False) because
`app/services/performance/third_supervisor_policy.py`'s own DEFAULTS have
`third_supervisor_weight_enabled=False`, which is read directly (no per-test
ModuleSetting row needed) -- this is exercised deliberately as the real
score_enabled=False contract for `save_assignment_draft` / `submit_assignment`.

`ensure_low_score_process_for_evaluation` (imported into this module's own
namespace from app/services/performance/low_score_process_service.py) is stubbed
at that exact call boundary per the wave's scope split -- low_score_process_service's
own internals (including a separate, already-tracked production defect in its
`ensure=False` publish-lock path) are Wave 1's territory and are not touched here.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

# Deliberately NOT imported at module level -- see the block comment in
# tests/behavior/test_low_score_process_service_workflow_contract.py's own
# `PerformanceEvaluation: Any = None` placeholder for the full forensic
# root-cause. In short: importing app.models / app.services... here would
# transitively import config.py at pytest COLLECTION time, before this file's
# own _make_app() ever gets a chance to set DATABASE_URL / patch
# Config.SQLALCHEMY_DATABASE_URI -- silently freezing every test in this file
# onto a stale sqlite:///:memory: engine for the whole pytest process.
User: Any = None
PerformancePeriod: Any = None
PerformanceCriteria: Any = None
PerformanceEvaluation: Any = None
PerformanceEvaluationItem: Any = None
EvaluationAssignment: Any = None
evaluation_workspace: Any = None


def _import_symbols() -> None:
    global User, PerformancePeriod, PerformanceCriteria, PerformanceEvaluation
    global PerformanceEvaluationItem, EvaluationAssignment, evaluation_workspace

    if evaluation_workspace is not None:
        return

    from app.models import (
        EvaluationAssignment as _EvaluationAssignment,
        PerformanceCriteria as _PerformanceCriteria,
        PerformanceEvaluation as _PerformanceEvaluation,
        PerformanceEvaluationItem as _PerformanceEvaluationItem,
        PerformancePeriod as _PerformancePeriod,
        User as _User,
    )
    from app.services.performance_v2 import evaluation_workspace as _evaluation_workspace

    User = _User
    PerformancePeriod = _PerformancePeriod
    PerformanceCriteria = _PerformanceCriteria
    PerformanceEvaluation = _PerformanceEvaluation
    PerformanceEvaluationItem = _PerformanceEvaluationItem
    EvaluationAssignment = _EvaluationAssignment
    evaluation_workspace = _evaluation_workspace


# ---------------------------------------------------------------------------
# DB fixture: the exact proven pattern from Wave 1's
# test_low_score_process_service_workflow_contract.py::_make_app, reproduced
# here with an independent tmp-db directory so this file shares zero DB state
# with any other wave/agent running concurrently against this worktree.
# ---------------------------------------------------------------------------

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent_evalworkspace")
_user_counter = 0


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-evaluation-workspace-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"evalworkspace_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    _import_symbols()

    # MANDATORY (see Wave 1's forensic closure, reproduced in this file's own
    # module docstring-adjacent comment above): Config.SQLALCHEMY_DATABASE_URI
    # is a class attribute frozen at config.py's first import in this pytest
    # process. create_app() itself touches db.engine during its own bootstrap
    # and Flask-SQLAlchemy 3.x caches that Engine per-app on first access, so
    # patching app.config *after* create_app() is too late -- the class
    # attributes must be patched first.
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
def eval_app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _create_user(app, *, role: str = "personel", manager_sicils: tuple[str | None, str | None, str | None] | None = None) -> tuple[int, str]:
    from app.extensions import db

    suffix = _next_suffix()
    with app.app_context():
        sicil = f"EW{suffix:06d}"
        user = User(
            sicil_no=sicil,
            email=f"evalworkspace-{suffix}@bys360.test",
            ad="Contract",
            soyad=f"User{suffix}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        if manager_sicils:
            user.yonetici_sicil, user.ikinci_yonetici_sicil, user.ucuncu_yonetici_sicil = manager_sicils
        user.set_password("EvalWorkspaceContractTest1!")
        db.session.add(user)
        db.session.commit()
        return user.id, sicil


def _create_period(app, *, start: date, end: date) -> int:
    from app.extensions import db

    suffix = _next_suffix()
    with app.app_context():
        period = PerformancePeriod(
            title=f"Eval Workspace Contract Dönem {suffix}",
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
                name=f"Kriter EvalWorkspace {_next_suffix()}",
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


def _setup_full_chain(app):
    """Employee + 3 real managers (linked via explicit sicil fields) + period
    (scoring window open, in the past) + 2 active criteria + one
    EvaluationAssignment per level (3, 2, 1)."""
    l1_id, l1_sicil = _create_user(app, role="grup_baskani")
    l2_id, l2_sicil = _create_user(app, role="koordinator")
    l3_id, l3_sicil = _create_user(app, role="birim_sorumlusu")
    employee_id, _employee_sicil = _create_user(
        app,
        role="personel",
        manager_sicils=(l1_sicil, l2_sicil, l3_sicil),
    )
    period_id = _create_period(app, start=date(2020, 1, 1), end=date(2020, 3, 31))
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
    scores: tuple[Any, ...] | None = None,
    general_comment: str | None = "Genel değerlendirme metni",
    skip_criteria_id: int | None = None,
) -> dict[str, str]:
    data: dict[str, str] = {}
    if general_comment is not None:
        data["general_comment"] = general_comment
    if scores is not None:
        for criteria_id, score in zip(criteria_ids, scores, strict=True):
            if criteria_id == skip_criteria_id:
                continue
            data[f"score_{criteria_id}"] = str(score)
            data[f"comment_{criteria_id}"] = "Kriter yorumu"
    return data


def _install_low_score_stub(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake_ensure(evaluation, actor_user_id=None, flush=False):  # noqa: ARG001
        calls.append(
            {
                "evaluation_id": getattr(evaluation, "id", None),
                "actor_user_id": actor_user_id,
                "flush": flush,
            }
        )
        return None

    monkeypatch.setattr(
        "app.services.performance_v2.evaluation_workspace.ensure_low_score_process_for_evaluation",
        _fake_ensure,
    )
    return calls


# ---------------------------------------------------------------------------
# save_assignment_draft
# ---------------------------------------------------------------------------


def test_save_assignment_draft_persists_weighted_score_and_taslak_status_for_scoring_level(eval_app) -> None:
    from app.extensions import db

    scn = _setup_full_chain(eval_app)
    criteria_ids = scn["criteria_ids"]
    form_data = _build_form_data(criteria_ids, scores=(4, 5), general_comment="2. amir taslak notu")

    with eval_app.app_context():
        assignment, evaluation = evaluation_workspace.save_assignment_draft(scn["a2"], form_data)
        db.session.commit()

        assert assignment.status == "taslak"
        assert evaluation.workflow_status == "taslak_2_amir"
        assert evaluation.level_2_general_comment == "2. amir taslak notu"
        # raw_score_to_100(4) == 80.0, raw_score_to_100(5) == 100.0, equal
        # criteria weights -> weighted average is a plain 90.0.
        assert evaluation.level_2_total_100 == pytest.approx(90.0)
        # A draft save must not mark the level complete.
        assert evaluation.level_2_completed is False
        assert assignment.completed_at is None

    with eval_app.app_context():
        items = (
            PerformanceEvaluationItem.query
            .filter_by(evaluation_id=evaluation.id, manager_level=2)
            .order_by(PerformanceEvaluationItem.criteria_id.asc())
            .all()
        )
        assert len(items) == 2
        scores_by_criteria = {item.criteria_id: item.score for item in items}
        assert scores_by_criteria[criteria_ids[0]] == 4.0
        assert scores_by_criteria[criteria_ids[1]] == 5.0


def test_save_assignment_draft_score_enabled_false_ignores_scores_and_zeroes_total(eval_app) -> None:
    """Level 3 defaults to comment-only mode (score_enabled=False). Even when
    the submitted form_data carries score_<id> fields, _upsert_items's
    score_enabled=False branch discards them entirely -- only the general
    comment is persisted, and the level total is forced to 0.0 rather than
    computed from (ignored) item scores."""
    from app.extensions import db

    scn = _setup_full_chain(eval_app)
    criteria_ids = scn["criteria_ids"]
    # Scores are supplied here on purpose -- the real contract is that they
    # get silently dropped for a comment-only level, not that omitting them
    # is required.
    form_data = _build_form_data(criteria_ids, scores=(5, 5), general_comment="3. amir üst görüşü")

    with eval_app.app_context():
        assignment, evaluation = evaluation_workspace.save_assignment_draft(scn["a3"], form_data)
        db.session.commit()

        assert assignment.status == "taslak"
        assert evaluation.workflow_status == "taslak_3_amir"
        assert evaluation.level_3_general_comment == "3. amir üst görüşü"
        assert evaluation.level_3_total_100 == 0.0

    with eval_app.app_context():
        items = PerformanceEvaluationItem.query.filter_by(evaluation_id=evaluation.id, manager_level=3).all()
        assert len(items) == 2
        for item in items:
            assert item.score is None
            assert item.score_100 == 0.0
            assert item.comment is None


# ---------------------------------------------------------------------------
# submit_assignment: per-level terminal states, validation fail-closed cases,
# and the low-score hook boundary.
# ---------------------------------------------------------------------------


def test_submit_assignment_level_3_comment_only_transitions_and_skips_low_score_hook(eval_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.extensions import db

    calls = _install_low_score_stub(monkeypatch)
    scn = _setup_full_chain(eval_app)
    form_data = _build_form_data(scn["criteria_ids"], scores=None, general_comment="Üst görüş tamam")

    with eval_app.app_context():
        assignment, evaluation = evaluation_workspace.submit_assignment(scn["a3"], form_data)
        db.session.commit()

        assert assignment.status == "tamamlandi"
        assert assignment.completed_at is not None
        assert evaluation.workflow_status == "level_3_tamamlandi"
        assert evaluation.status == "devam_ediyor"
        assert evaluation.level_3_completed is True

    # Evaluation is not yet in a terminal "tamamlandi" status, so the
    # low-score hook must not have fired at all for a level-3-only submit.
    assert calls == []


def test_submit_assignment_level_3_requires_general_comment_and_still_persists_draft(eval_app, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real, documented behavior: submit_assignment() calls
    save_assignment_draft() UNCONDITIONALLY before running
    _validate_submission(). So a submit that fails validation still leaves
    the draft-stage mutations (status='taslak', workflow_status, computed
    totals/comment) applied -- only the completion flags/timestamps that
    _validate_submission gates are skipped. This is asserted as the real
    contract, not worked around."""
    from app.extensions import db

    calls = _install_low_score_stub(monkeypatch)
    scn = _setup_full_chain(eval_app)
    # No general_comment at all for a comment-only level -> _validate_submission
    # must reject this.
    form_data = _build_form_data(scn["criteria_ids"], scores=None, general_comment=None)

    with eval_app.app_context():
        with pytest.raises(ValueError, match="Genel Görüş alanı zorunludur"):
            evaluation_workspace.submit_assignment(scn["a3"], form_data)
        db.session.commit()

    with eval_app.app_context():
        assignment = EvaluationAssignment.query.get(scn["a3"])
        evaluation = PerformanceEvaluation.query.filter_by(period_id=scn["period_id"], employee_id=scn["employee_id"]).first()
        # Draft-stage mutation from the unconditional save_assignment_draft
        # call did happen...
        assert assignment.status == "taslak"
        assert evaluation.workflow_status == "taslak_3_amir"
        # ...but completion never occurred.
        assert assignment.completed_at is None
        assert evaluation.level_3_completed is False
        assert evaluation.status != "tamamlandi"

    assert calls == []


def test_submit_assignment_rejects_out_of_order_level_2_before_level_3_submitted(eval_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.extensions import db

    calls = _install_low_score_stub(monkeypatch)
    scn = _setup_full_chain(eval_app)
    # Level 3 (the first actionable level for this chain) was never
    # submitted -- level 2 is not yet actionable.
    form_data = _build_form_data(scn["criteria_ids"], scores=(4, 4))

    with eval_app.app_context():
        with pytest.raises(ValueError, match="işlem sırası henüz gelmedi"):
            evaluation_workspace.submit_assignment(scn["a2"], form_data)
        db.session.commit()

    with eval_app.app_context():
        assignment = EvaluationAssignment.query.get(scn["a2"])
        evaluation = PerformanceEvaluation.query.filter_by(period_id=scn["period_id"], employee_id=scn["employee_id"]).first()
        assert assignment.completed_at is None
        assert evaluation.level_2_completed is False
        assert evaluation.status != "tamamlandi"

    assert calls == []


def test_submit_assignment_level_2_requires_all_criteria_scored(eval_app, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_low_score_stub(monkeypatch)
    scn = _setup_full_chain(eval_app)
    criteria_ids = scn["criteria_ids"]

    # Make level 2 actionable first (real ordering precondition).
    with eval_app.app_context():
        evaluation_workspace.submit_assignment(scn["a3"], _build_form_data(criteria_ids, scores=None, general_comment="Üst görüş"))
        from app.extensions import db

        db.session.commit()

    # One of the two criteria is left unscored.
    form_data = _build_form_data(criteria_ids, scores=(4, 4), skip_criteria_id=criteria_ids[1])

    with eval_app.app_context():
        with pytest.raises(ValueError, match="tüm kriterlere puan verilmelidir"):
            evaluation_workspace.submit_assignment(scn["a2"], form_data)
        from app.extensions import db

        db.session.commit()

    with eval_app.app_context():
        assignment = EvaluationAssignment.query.get(scn["a2"])
        evaluation = PerformanceEvaluation.query.filter_by(period_id=scn["period_id"], employee_id=scn["employee_id"]).first()
        assert assignment.status == "taslak"
        assert assignment.completed_at is None
        assert evaluation.level_2_completed is False

    # Level 3's earlier, valid submit is a different level's evaluation
    # status ("devam_ediyor"), so this failed level-2 attempt must not have
    # triggered the low-score hook either way.
    assert calls == []


def test_submit_assignment_full_chain_reaches_final_status_and_fires_low_score_hook_once(eval_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.extensions import db

    calls = _install_low_score_stub(monkeypatch)
    scn = _setup_full_chain(eval_app)
    criteria_ids = scn["criteria_ids"]

    with eval_app.app_context():
        evaluation_workspace.submit_assignment(scn["a3"], _build_form_data(criteria_ids, scores=None, general_comment="Üst görüş"))
        db.session.commit()
    assert calls == []

    with eval_app.app_context():
        assignment2, evaluation = evaluation_workspace.submit_assignment(scn["a2"], _build_form_data(criteria_ids, scores=(4, 5)))
        db.session.commit()
        assert assignment2.status == "tamamlandi"
        assert evaluation.workflow_status == "level_2_tamamlandi"
        assert evaluation.status == "devam_ediyor"
        assert evaluation.level_2_completed is True
    assert calls == []

    with eval_app.app_context():
        assignment1, evaluation = evaluation_workspace.submit_assignment(scn["a1"], _build_form_data(criteria_ids, scores=(3, 4)))
        db.session.commit()

        assert assignment1.status == "tamamlandi"
        assert assignment1.completed_at is not None
        assert evaluation.workflow_status == "tamamlandi"
        assert evaluation.status == "tamamlandi"
        assert evaluation.level_1_completed is True
        # _update_level_totals ran across the whole (now-complete) chain.
        assert evaluation.final_total_100 is not None
        assert evaluation.final_total_100 > 0.0
        evaluation_id = evaluation.id
        level1_evaluator_id = scn["l1_id"]

    # The low-score hook is only wired to fire once the evaluation itself
    # reaches a terminal "tamamlandi" status -- exactly once, at the final
    # (level 1) submit, called with this evaluation and the level-1 actor.
    assert len(calls) == 1
    assert calls[0]["evaluation_id"] == evaluation_id
    assert calls[0]["actor_user_id"] == level1_evaluator_id
    assert calls[0]["flush"] is False


# ---------------------------------------------------------------------------
# return_assignment_to_previous_level: fail-closed guards + real success path.
# ---------------------------------------------------------------------------


def test_return_assignment_to_previous_level_rejects_non_level_1_actor_without_mutation(eval_app) -> None:
    from app.extensions import db

    l2_id, _ = _create_user(eval_app, role="koordinator")
    employee_id, _ = _create_user(eval_app, role="personel")
    period_id = _create_period(eval_app, start=date(2020, 1, 1), end=date(2020, 3, 31))
    a2 = _create_assignment(eval_app, period_id=period_id, employee_id=employee_id, evaluator_id=l2_id, manager_level=2, status="tamamlandi")

    with eval_app.app_context():
        with pytest.raises(ValueError, match="yalnızca 1. amir ekranından yapılır"):
            evaluation_workspace.return_assignment_to_previous_level(a2, note="Gerekçe var")
        db.session.commit()

    with eval_app.app_context():
        assignment = EvaluationAssignment.query.get(a2)
        assert assignment.status == "tamamlandi"
        # The raise happens before _ensure_evaluation is ever called for a
        # non-level-1 actor, so no evaluation row should exist at all.
        evaluation = PerformanceEvaluation.query.filter_by(period_id=period_id, employee_id=employee_id).first()
        assert evaluation is None


def test_return_assignment_to_previous_level_rejects_blank_note_without_mutation(eval_app) -> None:
    from app.extensions import db

    l1_id, _ = _create_user(eval_app, role="grup_baskani")
    employee_id, _ = _create_user(eval_app, role="personel")
    period_id = _create_period(eval_app, start=date(2020, 1, 1), end=date(2020, 3, 31))
    a1 = _create_assignment(eval_app, period_id=period_id, employee_id=employee_id, evaluator_id=l1_id, manager_level=1, status="tamamlandi")

    with eval_app.app_context():
        with pytest.raises(ValueError, match="İade notu zorunludur"):
            evaluation_workspace.return_assignment_to_previous_level(a1, note="   ")
        db.session.commit()

    with eval_app.app_context():
        assignment = EvaluationAssignment.query.get(a1)
        assert assignment.status == "tamamlandi"
        # The note check also happens before _ensure_evaluation.
        evaluation = PerformanceEvaluation.query.filter_by(period_id=period_id, employee_id=employee_id).first()
        assert evaluation is None


def test_return_assignment_to_previous_level_rejects_missing_level_2_target(eval_app) -> None:
    from app.extensions import db

    l1_id, _ = _create_user(eval_app, role="grup_baskani")
    employee_id, _ = _create_user(eval_app, role="personel")
    period_id = _create_period(eval_app, start=date(2020, 1, 1), end=date(2020, 3, 31))
    # Only a level-1 assignment exists for this period/employee -- no level-2
    # row to return to.
    a1 = _create_assignment(eval_app, period_id=period_id, employee_id=employee_id, evaluator_id=l1_id, manager_level=1, status="tamamlandi")

    with eval_app.app_context():
        with pytest.raises(ValueError, match="2. amir görevi bulunamadı"):
            evaluation_workspace.return_assignment_to_previous_level(a1, note="Eksik bilgi")
        db.session.commit()

    with eval_app.app_context():
        assignment = EvaluationAssignment.query.get(a1)
        assert assignment.status == "tamamlandi"
        # _ensure_evaluation *does* run before the target lookup (real
        # ordering in the source), so an evaluation row now exists, but none
        # of return_assignment_to_previous_level's own state changes (which
        # all come after the raised target lookup) were applied.
        evaluation = PerformanceEvaluation.query.filter_by(period_id=period_id, employee_id=employee_id).first()
        assert evaluation is not None
        assert evaluation.level_1_completed is False
        assert evaluation.workflow_status == "taslak_1_amir"
        assert evaluation.level_2_return_note is None


def test_return_assignment_to_previous_level_success_resets_target_and_evaluation(eval_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.extensions import db

    calls = _install_low_score_stub(monkeypatch)
    scn = _setup_full_chain(eval_app)
    criteria_ids = scn["criteria_ids"]

    with eval_app.app_context():
        evaluation_workspace.submit_assignment(scn["a3"], _build_form_data(criteria_ids, scores=None, general_comment="Üst görüş"))
        evaluation_workspace.submit_assignment(scn["a2"], _build_form_data(criteria_ids, scores=(4, 5)))
        evaluation_workspace.submit_assignment(scn["a1"], _build_form_data(criteria_ids, scores=(3, 4)))
        db.session.commit()
    assert len(calls) == 1

    with eval_app.app_context():
        target, evaluation = evaluation_workspace.return_assignment_to_previous_level(scn["a1"], note="Eksik gerekçe var")
        db.session.commit()

        assert target.id == scn["a2"]
        assert target.status == "iade"
        assert target.completed_at is None
        assert evaluation.level_1_completed is False
        assert evaluation.workflow_status == "level_2_iade"
        assert evaluation.level_2_return_note == "Eksik gerekçe var"
        # Real (documented, not asserted as either correct or a bug) behavior:
        # return_assignment_to_previous_level only clears level_1_completed --
        # it does NOT reset evaluation.level_2_completed even though the
        # level-2 assignment's own status is reset to "iade".
        assert evaluation.level_2_completed is True

    with eval_app.app_context():
        assignment1 = EvaluationAssignment.query.get(scn["a1"])
        assert assignment1.status == "taslak"
        assert assignment1.completed_at is None


# ---------------------------------------------------------------------------
# withdraw_assignment_submission
# ---------------------------------------------------------------------------


def test_withdraw_assignment_submission_clears_only_its_own_level_flag(eval_app) -> None:
    from app.extensions import db

    scn = _setup_full_chain(eval_app)
    criteria_ids = scn["criteria_ids"]

    with eval_app.app_context():
        evaluation_workspace.submit_assignment(scn["a3"], _build_form_data(criteria_ids, scores=None, general_comment="Üst görüş"))
        evaluation_workspace.submit_assignment(scn["a2"], _build_form_data(criteria_ids, scores=(4, 5)))
        db.session.commit()

    with eval_app.app_context():
        evaluation = PerformanceEvaluation.query.filter_by(period_id=scn["period_id"], employee_id=scn["employee_id"]).first()
        assert evaluation.level_3_completed is True
        assert evaluation.level_2_completed is True

    with eval_app.app_context():
        assignment, evaluation = evaluation_workspace.withdraw_assignment_submission(scn["a3"])
        db.session.commit()

        assert assignment.status == "taslak"
        assert assignment.completed_at is None
        assert evaluation.workflow_status == "taslak_3_amir"
        assert evaluation.level_3_completed is False
        # The already-completed level 2 flag must survive a level-3 withdraw
        # untouched.
        assert evaluation.level_2_completed is True

    with eval_app.app_context():
        evaluation = PerformanceEvaluation.query.filter_by(period_id=scn["period_id"], employee_id=scn["employee_id"]).first()
        assert evaluation.level_3_completed is False
        assert evaluation.level_2_completed is True


def test_withdraw_assignment_submission_on_never_submitted_assignment_is_a_clean_reset(eval_app) -> None:
    from app.extensions import db

    scn = _setup_full_chain(eval_app)

    with eval_app.app_context():
        assignment, evaluation = evaluation_workspace.withdraw_assignment_submission(scn["a3"])
        db.session.commit()

        assert assignment.status == "taslak"
        assert assignment.completed_at is None
        assert evaluation.level_3_completed is False
        assert evaluation.workflow_status == "taslak_3_amir"


# ---------------------------------------------------------------------------
# Return -> resubmit end-to-end coherence.
# ---------------------------------------------------------------------------


def test_return_then_resubmit_cycle_leaves_coherent_final_state(eval_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.extensions import db

    calls = _install_low_score_stub(monkeypatch)
    scn = _setup_full_chain(eval_app)
    criteria_ids = scn["criteria_ids"]

    with eval_app.app_context():
        evaluation_workspace.submit_assignment(scn["a3"], _build_form_data(criteria_ids, scores=None, general_comment="Üst görüş"))
        evaluation_workspace.submit_assignment(scn["a2"], _build_form_data(criteria_ids, scores=(4, 5)))
        evaluation_workspace.submit_assignment(scn["a1"], _build_form_data(criteria_ids, scores=(3, 4)))
        db.session.commit()
    assert len(calls) == 1

    with eval_app.app_context():
        evaluation_workspace.return_assignment_to_previous_level(scn["a1"], note="Tekrar incele")
        db.session.commit()

    # Level 3's own status ("tamamlandi") was never touched by the return, so
    # level 2 is actionable again immediately (current_actionable_levels only
    # looks at the *other* levels' assignment status, not the level being
    # resubmitted).
    with eval_app.app_context():
        assignment2, evaluation = evaluation_workspace.submit_assignment(scn["a2"], _build_form_data(criteria_ids, scores=(5, 5)))
        db.session.commit()
        assert assignment2.status == "tamamlandi"
        assert evaluation.workflow_status == "level_2_tamamlandi"

    with eval_app.app_context():
        assignment1, evaluation = evaluation_workspace.submit_assignment(scn["a1"], _build_form_data(criteria_ids, scores=(4, 4)))
        db.session.commit()

        assert assignment1.status == "tamamlandi"
        assert assignment1.completed_at is not None
        assert evaluation.workflow_status == "tamamlandi"
        assert evaluation.status == "tamamlandi"
        assert evaluation.level_1_completed is True
        assert evaluation.level_2_completed is True
        assert evaluation.level_3_completed is True

    with eval_app.app_context():
        assignment3 = EvaluationAssignment.query.get(scn["a3"])
        assignment2 = EvaluationAssignment.query.get(scn["a2"])
        assignment1 = EvaluationAssignment.query.get(scn["a1"])
        assert assignment3.status == "tamamlandi"
        assert assignment2.status == "tamamlandi"
        assert assignment1.status == "tamamlandi"
        # The record reached "tamamlandi" twice across this cycle (once
        # before the return, once after the resubmit) -- the hook fires each
        # time the evaluation status lands on "tamamlandi", not just once
        # ever.
        assert len(calls) == 2
