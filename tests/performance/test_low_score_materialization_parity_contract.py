"""BYS360 PERFORMANCE P0.2O: low-score process materialization parity.

Canonical channel (unchanged): the v2 web completion,
app/services/performance_v2/evaluation_workspace.py::submit_assignment. When the
evaluation reaches a final status ({"tamamlandi", "tamamlandı", "completed",
"published"}) it calls ensure_low_score_process_for_evaluation(evaluation,
actor_user_id=assignment.evaluator_id, flush=False) inside the request's
transaction; the route commits.

Verified at 721216fb2f8c31e2c4af624d5324b234fa474af8: the admin weight
recalculation (POST /performance/hierarchy-settings action=save_weights ->
scoring.recalculate_all_evaluations(), which commits itself) could move a
completed evaluation below 70 without that call, so it had no process.

Since P0.2O recalculate_all_evaluations() calls the same ensure with the same
final-status gate before its own commit, only for evaluations whose
(final_total_100, status) changed; actor = the admin (current_user, as the
other admin-triggered ensure callers: sync, publish, rule enforcement). Any
error propagates to the route's existing rollback + flash, so weights, totals
and process rows stay atomic. A process of an evaluation that rises back above
70 is left as it is (no policy exists for that; unchanged).

The mobile completion channel is NOT covered here: it leaves workflow_status at
the model default "taslak_1_amir", so the canonical low-score predicate does not
treat it as completed at all (reported separately; needs a workflow decision).

Real Flask app, real routes/services, file-backed SQLite test database only.
"""
from __future__ import annotations

import importlib
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_EVENTS_PER_FIRST_LOW_SCORE = 5
_WEIGHTS_ERROR = "Ağırlık ayarları kaydedilirken hata oluştu."
_LOW_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_PASSWORD = "TestMaterializationContract1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02o_materialization")
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
        "SECRET_KEY": "test-secret-key-for-p02o-materialization-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "test-password",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02o_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

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


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _user(flask_app, *, role: str, managers: tuple[str | None, str | None, str | None] | None = None) -> tuple[int, str]:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        n = _next()
        sicil_no = f"P2O{n:06d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02o-materialization-{n}@bys360.test",
            ad="P02O",
            soyad=f"Kullanici{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        if managers:
            user.yonetici_sicil, user.ikinci_yonetici_sicil, user.ucuncu_yonetici_sicil = managers
        user.set_password(_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return int(user.id), sicil_no


def _login(client, sicil_no: str) -> None:
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": _PASSWORD}, follow_redirects=False)
    assert response.status_code == 302
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """App + logged-in admin web client. Only the live menu matrix is bypassed
    (same as tests/behavior/test_h1f_route_exception_leak_contract.py)."""
    flask_app = _make_app(monkeypatch)
    monkeypatch.setattr(importlib.import_module("app.route_support"), "can_access_menu", lambda user, key: True)
    admin_id, admin_sicil = _user(flask_app, role="admin")
    client = flask_app.test_client()
    _login(client, admin_sicil)
    return SimpleNamespace(app=flask_app, client=client, admin_id=admin_id)


def _period(flask_app, *, start: date = date(2026, 1, 1), end: date = date(2026, 3, 31)) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod

    with flask_app.app_context():
        period = PerformancePeriod(title=f"P0.2O Dönem {_next()}", period_type="quarterly", start_date=start, end_date=end, is_active=True)
        db.session.add(period)
        db.session.commit()
        return int(period.id)


def _criteria(flask_app, count: int = 2) -> list[int]:
    from app.extensions import db
    from app.models import PerformanceCriteria

    ids = []
    with flask_app.app_context():
        for index in range(count):
            criteria = PerformanceCriteria(name=f"P0.2O Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            ids.append(int(criteria.id))
        db.session.commit()
    return ids


def _assignment(flask_app, *, period_id: int, employee_id: int, evaluator_id: int, level: int) -> int:
    from app.extensions import db
    from app.models import EvaluationAssignment

    with flask_app.app_context():
        assignment = EvaluationAssignment(period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id, manager_level=level, status="bekliyor")
        db.session.add(assignment)
        db.session.commit()
        return int(assignment.id)


def _state(flask_app, period_id: int) -> dict[str, Any]:
    """Committed state as a fresh transaction sees it."""
    from app.extensions import db

    with flask_app.app_context():
        db.session.remove()
        evaluations = [
            (row[0], row[1], row[2])
            for row in db.session.execute(
                text("SELECT id, status, final_total_100 FROM performance_evaluations WHERE period_id = :p ORDER BY id"), {"p": period_id}
            ).all()
        ]
        processes = [
            {"evaluation_id": row[0], "final": row[1], "created_by": row[2], "updated_by": row[3], "updated_at": row[4]}
            for row in db.session.execute(
                text(
                    "SELECT evaluation_id, final_total_100, created_by_user_id, updated_by_user_id, updated_at "
                    "FROM performance_low_score_processes WHERE period_id = :p ORDER BY id"
                ),
                {"p": period_id},
            ).all()
        ]
        events = db.session.execute(
            text(
                "SELECT COUNT(*) FROM performance_low_score_process_events e "
                "JOIN performance_low_score_processes p ON p.id = e.process_id WHERE p.period_id = :p"
            ),
            {"p": period_id},
        ).scalar()
        db.session.remove()
    return {"evaluations": evaluations, "processes": processes, "events": events}


def _add_duplicate_process_then_real_ensure(real_ensure):
    """A real DB error inside the materialization: a second process row for the
    same evaluation is autoflushed by ensure's own query (UNIQUE evaluation_id)."""

    def _fail(evaluation, *args, **kwargs):
        from app.extensions import db
        from app.models import PerformanceLowScoreProcess

        db.session.flush()  # the evaluation row must exist to reference it
        db.session.add(PerformanceLowScoreProcess(period_id=evaluation.period_id, evaluation_id=evaluation.id, employee_id=evaluation.employee_id, calendar_year=2026))
        db.session.flush()
        db.session.add(PerformanceLowScoreProcess(period_id=evaluation.period_id, evaluation_id=evaluation.id, employee_id=evaluation.employee_id, calendar_year=2026))
        return real_ensure(evaluation, *args, **kwargs)

    return _fail


def _raise_runtime(evaluation, *args, **kwargs):
    raise RuntimeError("simulated policy runtime failure")


# ---------------------------------------------------------------------------
# V2 canonical baseline (unchanged channel, real ensure)
# ---------------------------------------------------------------------------


def _v2_chain(flask_app) -> dict[str, Any]:
    l1_id, l1_sicil = _user(flask_app, role="grup_baskani")
    l2_id, l2_sicil = _user(flask_app, role="koordinator")
    l3_id, l3_sicil = _user(flask_app, role="birim_sorumlusu")
    employee_id, _s = _user(flask_app, role="personel", managers=(l1_sicil, l2_sicil, l3_sicil))
    period_id = _period(flask_app, start=date(2020, 1, 1), end=date(2020, 3, 31))
    criteria_ids = _criteria(flask_app)
    return {
        "period_id": period_id,
        "criteria_ids": criteria_ids,
        "l1_id": l1_id,
        "a3": _assignment(flask_app, period_id=period_id, employee_id=employee_id, evaluator_id=l3_id, level=3),
        "a2": _assignment(flask_app, period_id=period_id, employee_id=employee_id, evaluator_id=l2_id, level=2),
        "a1": _assignment(flask_app, period_id=period_id, employee_id=employee_id, evaluator_id=l1_id, level=1),
    }


def _v2_form(criteria_ids: list[int], scores: tuple[int, int] | None, comment: str) -> dict[str, str]:
    data = {"general_comment": comment}
    for criteria_id, score in zip(criteria_ids, scores or (), strict=False):
        data[f"score_{criteria_id}"] = str(score)
        data[f"comment_{criteria_id}"] = "Kriter yorumu ve gerekçesi"
    return data


def _v2_complete(flask_app, chain: dict[str, Any], scores: tuple[int, int]) -> None:
    from app.extensions import db
    from app.services.performance_v2 import evaluation_workspace

    for key, level_scores in (("a3", None), ("a2", scores), ("a1", scores)):
        with flask_app.app_context():
            evaluation_workspace.submit_assignment(chain[key], _v2_form(chain["criteria_ids"], level_scores, _LOW_COMMENT))
            db.session.commit()


def test_v2_baseline_high_score_creates_no_process(env) -> None:
    chain = _v2_chain(env.app)
    _v2_complete(env.app, chain, (5, 4))
    state = _state(env.app, chain["period_id"])
    assert [status for _id, status, _final in state["evaluations"]] == ["tamamlandi"]
    assert state["evaluations"][0][2] >= 70
    assert (state["processes"], state["events"]) == ([], 0)


def test_v2_baseline_low_score_creates_one_chain_with_the_final_evaluator_as_actor(env) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance_v2 import evaluation_workspace

    chain = _v2_chain(env.app)
    _v2_complete(env.app, chain, (2, 2))
    state = _state(env.app, chain["period_id"])
    ((evaluation_id, status, final),) = state["evaluations"]
    assert status == "tamamlandi" and final < 70
    assert len(state["processes"]) == 1 and state["events"] == _EVENTS_PER_FIRST_LOW_SCORE
    assert (state["processes"][0]["created_by"], state["processes"][0]["updated_by"]) == (chain["l1_id"], chain["l1_id"])

    # Re-submitting the final level (retry) does not duplicate anything.
    with env.app.app_context():
        evaluation_workspace.submit_assignment(chain["a1"], _v2_form(chain["criteria_ids"], (2, 2), _LOW_COMMENT))
        db.session.commit()
        assert db.session.get(PerformanceEvaluation, evaluation_id) is not None
    again = _state(env.app, chain["period_id"])
    assert (len(again["processes"]), again["events"]) == (1, _EVENTS_PER_FIRST_LOW_SCORE)


# ---------------------------------------------------------------------------
# Admin weight recalculation
# ---------------------------------------------------------------------------


def _two_manager_evaluation(flask_app, level_1_scores: tuple[int, int], level_2_scores: tuple[int, int]) -> int:
    """A completed evaluation whose final total depends on the period weights."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem

    l1_id, l1_sicil = _user(flask_app, role="grup_baskani")
    l2_id, l2_sicil = _user(flask_app, role="koordinator")
    employee_id, _s = _user(flask_app, role="personel", managers=(l1_sicil, l2_sicil, None))
    period_id = _period(flask_app)
    criteria_ids = _criteria(flask_app)
    with flask_app.app_context():
        evaluation = PerformanceEvaluation(
            period_id=period_id,
            employee_id=employee_id,
            level_1_evaluator_id=l1_id,
            level_2_evaluator_id=l2_id,
            level_1_completed=True,
            level_2_completed=True,
            status="tamamlandi",
            workflow_status="tamamlandi",
            level_1_general_comment=_LOW_COMMENT,
        )
        db.session.add(evaluation)
        db.session.flush()
        for level, scores in ((1, level_1_scores), (2, level_2_scores)):
            for criteria_id, score in zip(criteria_ids, scores, strict=True):
                db.session.add(
                    PerformanceEvaluationItem(
                        evaluation_id=evaluation.id, criteria_id=criteria_id, manager_level=level, score=float(score), score_100=float(score) * 20, justification="Gerekçe"
                    )
                )
        db.session.commit()
    return period_id


def _save_weights(env: SimpleNamespace, period_id: int, w1: int, w2: int, client=None):
    return (client or env.client).post(
        "/performance/hierarchy-settings",
        data={"action": "save_weights", "period_id": str(period_id), "evaluator_1_weight": str(w1), "evaluator_2_weight": str(w2), "evaluator_3_weight": "0"},
        follow_redirects=False,
    )


def test_weight_recalc_that_drops_a_score_below_70_creates_one_chain(env) -> None:
    """W1 80 -> 68. Before P0.2O: no process. Repeating the same weights is a no-op."""
    period_id = _two_manager_evaluation(env.app, (3, 3), (5, 5))  # level 1 = 60, level 2 = 100
    assert _save_weights(env, period_id, 50, 50).status_code == 302
    assert _state(env.app, period_id)["evaluations"][0][2] == 80.0
    assert _state(env.app, period_id)["processes"] == []

    assert _save_weights(env, period_id, 80, 20).status_code == 302
    state = _state(env.app, period_id)
    assert state["evaluations"][0][2] == 68.0
    assert len(state["processes"]) == 1 and state["events"] == _EVENTS_PER_FIRST_LOW_SCORE
    process = state["processes"][0]
    assert (process["final"], process["created_by"], process["updated_by"]) == (68.0, env.admin_id, env.admin_id)

    assert _save_weights(env, period_id, 80, 20).status_code == 302
    assert _state(env.app, period_id) == state  # unchanged score: no audit mutation, no duplicate


def test_weight_recalc_back_above_70_leaves_the_existing_process_untouched(env) -> None:
    """W2 68 -> 80: no low->high policy exists; the process stays exactly as it was."""
    period_id = _two_manager_evaluation(env.app, (3, 3), (5, 5))
    _save_weights(env, period_id, 80, 20)
    low = _state(env.app, period_id)
    assert len(low["processes"]) == 1

    assert _save_weights(env, period_id, 50, 50).status_code == 302
    high = _state(env.app, period_id)
    assert high["evaluations"][0][2] == 80.0
    assert (high["processes"], high["events"]) == (low["processes"], low["events"])


def test_weight_recalc_within_low_range_updates_the_same_chain_without_duplicates(env) -> None:
    """W3 64 -> 58: same process, score synced, no new events."""
    period_id = _two_manager_evaluation(env.app, (2, 2), (5, 5))  # level 1 = 40, level 2 = 100
    _save_weights(env, period_id, 60, 40)
    first = _state(env.app, period_id)
    assert first["evaluations"][0][2] == 64.0 and len(first["processes"]) == 1

    assert _save_weights(env, period_id, 70, 30).status_code == 302
    second = _state(env.app, period_id)
    assert second["evaluations"][0][2] == 58.0
    assert len(second["processes"]) == 1 and second["events"] == first["events"] == _EVENTS_PER_FIRST_LOW_SCORE
    assert second["processes"][0]["final"] == 58.0


@pytest.mark.parametrize("failure", ["runtime", "integrity"])
def test_weight_recalc_materialization_failure_rolls_everything_back(env, monkeypatch, failure) -> None:
    from app.extensions import db
    from app.models import PerformanceWeightConfig

    period_id = _two_manager_evaluation(env.app, (3, 3), (5, 5))
    assert _save_weights(env, period_id, 50, 50).status_code == 302
    before = _state(env.app, period_id)
    svc = importlib.import_module(_SERVICE_MODULE)
    fake = _raise_runtime if failure == "runtime" else _add_duplicate_process_then_real_ensure(svc.ensure_low_score_process_for_evaluation)
    monkeypatch.setattr(svc, "ensure_low_score_process_for_evaluation", fake)

    response = _save_weights(env, period_id, 80, 20)
    assert response.status_code == 200  # the route re-renders the settings page after its rollback
    assert _WEIGHTS_ERROR in response.get_data(as_text=True)
    assert _state(env.app, period_id) == before  # scores and processes unchanged
    with env.app.app_context():
        config = PerformanceWeightConfig.query.filter_by(period_id=period_id).first()
        assert config is not None
        assert (config.evaluator_1_weight, config.evaluator_2_weight) == (50, 50)
        db.session.remove()


def test_weight_recalc_access_contract_is_unchanged(env) -> None:
    period_id = _two_manager_evaluation(env.app, (3, 3), (5, 5))
    before = _state(env.app, period_id)
    _uid, sicil = _user(env.app, role="personel")
    personel = env.app.test_client()
    _login(personel, sicil)
    assert _save_weights(env, period_id, 80, 20, client=personel).status_code == 403
    anonymous = _save_weights(env, period_id, 80, 20, client=env.app.test_client())
    assert anonymous.status_code == 302 and anonymous.headers["Location"].startswith("/login")
    assert _state(env.app, period_id) == before  # nothing recalculated, nothing materialized
