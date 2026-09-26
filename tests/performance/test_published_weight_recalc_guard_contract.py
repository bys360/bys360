"""BYS360 PERFORMANCE P0.2T: no weight recalculation in a published or locked period.

Route: POST /performance/hierarchy-settings action=save_weights
(main.performance_hierarchy_settings, app/performance/routes.py; login + admin +
menu "performance_hierarchy_assignments") -> PerformanceWeightConfig and
period level-3 flags -> scoring.recalculate_all_evaluations(period) rewrites
every evaluation total of the period (+ low-score materialization, P0.2O-W) ->
commit.

Verified at 55c014d44b09bf609e7068dd0bbf8b8c039c688e: the route never looked at
the period state. A published card changed (90 -> 84) while its publish
snapshot kept 90; a published 80 dropped to 68 and got an unapproved low-score
process while staying published; an approved, published low score was re-scored
(64 -> 58 -> 88); a period with results_published=True and is_locked=True was
recalculated as well.

Canonical period rule (app/services/performance/period_state_guard.py, used by
the v2 web scoring window): "Bu dönem sonuçları yayınlandığı için puanlama
değişikliği yapılamaz." / "Bu dönem kilitli olduğu için puanlama değişikliği
yapılamaz."; published periods are expected to be locked
(performance_v2.validators.validate_publish_guard) and a republication goes
through unpublish first (validate_publish_window). Since P0.2T the weight save
applies the same period rule (validate_period_scores_mutable, extracted from
validate_scoring_window without changing it) before any write. The correction
path stays: unpublish, then change the weights.

Real Flask app, real admin login and permissions (no can_access_menu bypass),
real publish / unpublish / president-approve / personnel-support / period toggle
routes; file-backed SQLite test database only. The Alembic-owned
personnel-support approval table is created with the DDL used by
tests/behavior/test_personnel_support_publish_approval_workflow_contract.py.
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text

_PASSWORD = "PublishedWeightRecalc1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02t_published_weights")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_PUBLISHED_MESSAGE = "Bu dönem sonuçları yayınlandığı için puanlama değişikliği yapılamaz."
_LOCKED_MESSAGE = "Bu dönem kilitli olduğu için puanlama değişikliği yapılamaz."
_SAVED_FLASH = ("success", "Dönem ağırlıkları güncellendi.")

_APPROVAL_TABLE_DDL = (
    """CREATE TABLE performance_personnel_support_publish_approvals (
        id INTEGER PRIMARY KEY, evaluation_id INTEGER NOT NULL, period_id INTEGER, employee_id INTEGER,
        final_score NUMERIC(6, 2), status VARCHAR(50) NOT NULL DEFAULT 'pending',
        requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, requested_by_user_id INTEGER,
        decided_at DATETIME, decided_by_user_id INTEGER, decision_note TEXT, return_note TEXT,
        rule_version VARCHAR(120) NOT NULL DEFAULT 'phase1.4b-personnel-support-publish-approval-v1',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX ix_phase14b_publish_approval_status ON performance_personnel_support_publish_approvals(status)",
    "CREATE INDEX ix_phase14b_publish_approval_period_status ON performance_personnel_support_publish_approvals(period_id, status)",
    "CREATE INDEX ix_phase14b_publish_approval_employee ON performance_personnel_support_publish_approvals(employee_id)",
)
_counter = 0


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p02t-published-weights",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02t_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

    from app.extensions import db

    with flask_app.app_context():

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
        for statement in _APPROVAL_TABLE_DDL:
            db.session.execute(text(statement))
        db.session.commit()
    return flask_app


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _user(flask_app, *, role: str, managers: tuple[str | None, str | None, str | None] | None = None, unvan: str | None = None) -> tuple[int, str]:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        n = _next()
        sicil_no = f"P2T{n:06d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02t-weights-{n}@bys360.test",
            ad="P02T",
            soyad=f"Kullanici{n}",
            role=role,
            unvan=unvan,
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
    assert "/login" not in response.headers.get("Location", "")
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)  # the login's own "Giriş başarılı." flash


def _flashes(client) -> list[tuple[str, str]]:
    with client.session_transaction() as sess:
        return [tuple(item) for item in sess.pop("_flashes", [])]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Admin (settings, publish and Başkan/Üst Onay screens) and the Personel ve
    Destek Hizmetleri Grup Başkanı, logged in for real; one criteria set."""
    from app.extensions import db
    from app.models import PerformanceCriteria

    flask_app = _make_app(monkeypatch)
    admin_id, admin_sicil = _user(flask_app, role="admin")
    admin = flask_app.test_client()
    _login(admin, admin_sicil)
    _chair_id, chair_sicil = _user(flask_app, role="personel", unvan="Personel ve Destek Hizmetleri Grup Başkanı")
    chair = flask_app.test_client()
    _login(chair, chair_sicil)
    criteria_ids = []
    with flask_app.app_context():
        for index in range(2):
            criteria = PerformanceCriteria(name=f"P0.2T Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        db.session.commit()
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids)


def _period(env: SimpleNamespace) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod

    with env.app.app_context():
        period = PerformancePeriod(title=f"P0.2T Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        return int(period.id)


def _completed_evaluation(env: SimpleNamespace, period_id: int, level_1_scores: tuple[int, int], level_2_scores: tuple[int, int]) -> int:
    """A completed two-manager evaluation whose final total depends on the period weights."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem

    l1_id, l1_sicil = _user(env.app, role="grup_baskani")
    l2_id, l2_sicil = _user(env.app, role="koordinator")
    employee_id, _sicil = _user(env.app, role="personel", managers=(l1_sicil, l2_sicil, None))
    with env.app.app_context():
        evaluation = PerformanceEvaluation(
            period_id=period_id,
            employee_id=employee_id,
            level_1_evaluator_id=l1_id,
            level_2_evaluator_id=l2_id,
            level_1_completed=True,
            level_2_completed=True,
            status="tamamlandi",
            workflow_status="tamamlandi",
            level_1_general_comment=_COMMENT,
        )
        db.session.add(evaluation)
        db.session.flush()
        for level, scores in ((1, level_1_scores), (2, level_2_scores)):
            for criteria_id, score in zip(env.criteria_ids, scores, strict=True):
                db.session.add(
                    PerformanceEvaluationItem(evaluation_id=evaluation.id, criteria_id=criteria_id, manager_level=level, score=float(score), score_100=float(score) * 20, justification="Gerekçe")
                )
        db.session.commit()
        return int(evaluation.id)


def _save_weights(env: SimpleNamespace, period_id: int, w1: int, w2: int, client=None) -> tuple[Any, list[tuple[str, str]], list[str]]:
    """Real settings POST; returns the response, its flashes and every DML statement issued."""
    from app.extensions import db

    client = client or env.admin
    dml: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            dml.append(statement)

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = client.post(
            "/performance/hierarchy-settings",
            data={"action": "save_weights", "period_id": str(period_id), "evaluator_1_weight": str(w1), "evaluator_2_weight": str(w2), "evaluator_3_weight": "0"},
            follow_redirects=False,
        )
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return response, _flashes(client), dml


def _state(env: SimpleNamespace, period_id: int) -> dict[str, Any]:
    """Every row the weight save could touch, as a fresh transaction sees it."""
    from app.extensions import db

    params = {"p": period_id}

    def _rows(sql: str) -> list[dict[str, Any]]:
        return [dict(row) for row in db.session.execute(text(sql), params).mappings().all()]

    with env.app.app_context():
        db.session.remove()
        state = {
            "period": _rows("SELECT * FROM performance_periods WHERE id = :p"),
            "weights": _rows("SELECT * FROM performance_weight_configs WHERE period_id = :p ORDER BY id"),
            "evaluations": _rows("SELECT * FROM performance_evaluations WHERE period_id = :p ORDER BY id"),
            "items": _rows("SELECT i.* FROM performance_evaluation_items i JOIN performance_evaluations e ON e.id = i.evaluation_id WHERE e.period_id = :p ORDER BY i.id"),
            "processes": _rows("SELECT * FROM performance_low_score_processes WHERE period_id = :p ORDER BY id"),
            "events": _rows(
                "SELECT ev.* FROM performance_low_score_process_events ev "
                "JOIN performance_low_score_processes p ON p.id = ev.process_id WHERE p.period_id = :p ORDER BY ev.id"
            ),
            "snapshots": _rows("SELECT * FROM performance_result_snapshots WHERE period_id = :p ORDER BY id"),
        }
        db.session.remove()
    return state


def _finals(state: dict[str, Any]) -> list[float]:
    return [row["final_total_100"] for row in state["evaluations"]]


def _personnel_support_approve(env: SimpleNamespace, evaluation_id: int) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance.personnel_support_publish_approval_service import (
        ensure_personnel_support_publish_approval_for_evaluation,
    )

    with env.app.app_context():
        row = ensure_personnel_support_publish_approval_for_evaluation(db.session.get(PerformanceEvaluation, evaluation_id))
        assert row is not None
        approval_id = int(row["id"])
        db.session.commit()
    response = env.chair.post(f"/performance/personnel-support-publish-approvals/{approval_id}/approve", data={"note": "Uygundur."}, follow_redirects=False)
    assert response.status_code == 302


def _president_approve(env: SimpleNamespace, evaluation_id: int) -> None:
    """The process as the v2 completion creates it, then Başkan/Üst Onay on the real route."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance.low_score_process_service import (
        ensure_low_score_process_for_evaluation,
    )

    with env.app.app_context():
        process = ensure_low_score_process_for_evaluation(db.session.get(PerformanceEvaluation, evaluation_id), actor_user_id=env.admin_id)
        assert process is not None
        process_id = int(process.id)
        db.session.commit()
    response = env.admin.post(f"/performance/low-score-process/{process_id}/president-approve", data={"note": "Onaylandı"}, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Başkan onayı kaydedildi.") in _flashes(env.admin)


def _publish(env: SimpleNamespace, evaluation_id: int, *, low_score: bool = False) -> None:
    if low_score:
        _president_approve(env, evaluation_id)
    _personnel_support_approve(env, evaluation_id)
    response = env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Sonuç personele yayımlandı.") in _flashes(env.admin)


def _toggle(env: SimpleNamespace, period_id: int, what: str) -> None:
    """The real period toggle route (admin), as the period list uses it."""
    expected = {"publish": ("success", "Dönem yayın durumu güncellendi."), "lock": ("success", "Dönem kilitlendi.")}[what]
    response = env.admin.post(f"/performance/periods/{period_id}/toggle-{what}", data={"target_state": "true"}, follow_redirects=False)
    assert response.status_code == 302
    assert _flashes(env.admin) == [expected]


def _assert_blocked(env: SimpleNamespace, period_id: int, message: str, w1: int = 80, w2: int = 20) -> dict[str, Any]:
    from flask import url_for

    before = _state(env, period_id)
    response, flashes, dml = _save_weights(env, period_id, w1, w2)
    assert response.status_code == 302
    with env.app.test_request_context():
        settings_url = url_for("main.performance_hierarchy_settings", period_id=period_id, scope="all")  # same target as the save success
    assert response.headers["Location"] == settings_url
    assert flashes == [("warning", message)]
    assert dml == []
    after = _state(env, period_id)
    assert after == before
    return after


# ---------------------------------------------------------------------------
# Unpublished, unlocked period: unchanged behavior
# ---------------------------------------------------------------------------


def test_weight_save_in_an_open_period_still_recalculates(env) -> None:
    period_id = _period(env)
    _completed_evaluation(env, period_id, (3, 3), (5, 5))  # level 1 = 60, level 2 = 100
    response, flashes, _dml = _save_weights(env, period_id, 50, 50)
    assert response.status_code == 302 and _SAVED_FLASH in flashes
    assert _finals(_state(env, period_id)) == [80.0]
    response, flashes, _dml = _save_weights(env, period_id, 80, 20)
    assert response.status_code == 302 and _SAVED_FLASH in flashes
    state = _state(env, period_id)
    assert _finals(state) == [68.0] and len(state["processes"]) == 1 and len(state["events"]) == 5  # P0.2O-W


def test_unpublish_then_weight_save_is_the_correction_path(env) -> None:
    period_id = _period(env)
    evaluation_id = _completed_evaluation(env, period_id, (4, 4), (5, 5))
    _save_weights(env, period_id, 50, 50)
    _publish(env, evaluation_id)
    _assert_blocked(env, period_id, _PUBLISHED_MESSAGE)

    response = env.admin.post(f"/performance/unpublish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    assert response.status_code == 302 and ("success", "Sonuç yayından kaldırıldı.") in _flashes(env.admin)
    response, flashes, _dml = _save_weights(env, period_id, 80, 20)
    assert response.status_code == 302 and _SAVED_FLASH in flashes
    assert _finals(_state(env, period_id)) == [84.0]


# ---------------------------------------------------------------------------
# Published or locked period: blocked before any write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("level_1_scores", "published_final"), [((4, 4), 90.0), ((3, 3), 80.0)], ids=["stays_high", "would_drop_below_70"])
def test_published_card_blocks_the_weight_save(env, level_1_scores, published_final) -> None:
    period_id = _period(env)
    evaluation_id = _completed_evaluation(env, period_id, level_1_scores, (5, 5))
    _save_weights(env, period_id, 50, 50)
    _publish(env, evaluation_id)
    state = _assert_blocked(env, period_id, _PUBLISHED_MESSAGE)
    assert _finals(state) == [published_final]
    assert [row["final_total_100"] for row in state["snapshots"]] == [published_final]  # live score == published snapshot
    assert state["processes"] == []


def test_published_approved_low_score_card_blocks_the_weight_save(env) -> None:
    period_id = _period(env)
    evaluation_id = _completed_evaluation(env, period_id, (2, 2), (5, 5))  # level 1 = 40, level 2 = 100
    _save_weights(env, period_id, 60, 40)  # 64
    _publish(env, evaluation_id, low_score=True)
    state = _assert_blocked(env, period_id, _PUBLISHED_MESSAGE, 70, 30)
    assert _finals(state) == [64.0]
    assert [(row["final_total_100"], row["president_approved_at"] is not None) for row in state["processes"]] == [(64.0, True)]


def test_mixed_period_is_blocked_as_a_whole(env) -> None:
    """One published and one unpublished card: no card is recalculated, so the
    period never holds two weight versions."""
    period_id = _period(env)
    published_id = _completed_evaluation(env, period_id, (4, 4), (5, 5))
    _completed_evaluation(env, period_id, (3, 3), (5, 5))
    _save_weights(env, period_id, 50, 50)
    _publish(env, published_id)
    state = _assert_blocked(env, period_id, _PUBLISHED_MESSAGE)
    assert _finals(state) == [90.0, 80.0]


def test_period_marked_published_blocks_even_without_a_published_card(env) -> None:
    period_id = _period(env)
    _completed_evaluation(env, period_id, (3, 3), (5, 5))
    _save_weights(env, period_id, 50, 50)
    _toggle(env, period_id, "publish")
    _assert_blocked(env, period_id, _PUBLISHED_MESSAGE)


def test_locked_period_blocks_with_the_lock_message(env) -> None:
    period_id = _period(env)
    _completed_evaluation(env, period_id, (3, 3), (5, 5))
    _save_weights(env, period_id, 50, 50)
    _toggle(env, period_id, "lock")
    _assert_blocked(env, period_id, _LOCKED_MESSAGE)


def test_repeated_blocked_requests_never_mutate(env) -> None:
    period_id = _period(env)
    evaluation_id = _completed_evaluation(env, period_id, (4, 4), (5, 5))
    _save_weights(env, period_id, 50, 50)
    _publish(env, evaluation_id)
    first = _assert_blocked(env, period_id, _PUBLISHED_MESSAGE)
    for w1, w2 in ((80, 20), (20, 80), (50, 50)):
        assert _assert_blocked(env, period_id, _PUBLISHED_MESSAGE, w1, w2) == first


def test_weight_save_access_contract_is_unchanged(env) -> None:
    period_id = _period(env)
    evaluation_id = _completed_evaluation(env, period_id, (4, 4), (5, 5))
    _save_weights(env, period_id, 50, 50)
    _publish(env, evaluation_id)
    before = _state(env, period_id)
    _uid, sicil = _user(env.app, role="personel")
    personel = env.app.test_client()
    _login(personel, sicil)
    assert _save_weights(env, period_id, 80, 20, client=personel)[0].status_code == 403
    anonymous = _save_weights(env, period_id, 80, 20, client=env.app.test_client())[0]
    assert anonymous.status_code == 302 and anonymous.headers["Location"].startswith("/login")
    assert _state(env, period_id) == before


# ---------------------------------------------------------------------------
# The extracted period rule leaves the v2 scoring window unchanged
# ---------------------------------------------------------------------------


def test_scoring_window_contract_is_unchanged() -> None:
    from app.services.performance.period_state_guard import (
        validate_period_scores_mutable,
        validate_scoring_window,
    )

    def _period_ns(**overrides: Any) -> SimpleNamespace:
        base: dict[str, Any] = {"results_published": False, "is_locked": False, "end_date": date(2026, 3, 31), "scoring_start_date": None, "scoring_end_date": None}
        base.update(overrides)
        return SimpleNamespace(**base)

    now = datetime(2026, 5, 1, 12, 0)
    assert validate_scoring_window(None, now=now) == (False, "Performans dönemi bulunamadı.")
    assert validate_scoring_window(_period_ns(results_published=True, is_locked=True), now=now) == (False, _PUBLISHED_MESSAGE)
    assert validate_scoring_window(_period_ns(is_locked=True), now=now) == (False, _LOCKED_MESSAGE)
    assert validate_scoring_window(_period_ns(), now=now) == (True, "Puanlama dönemi açık.")
    assert validate_scoring_window(_period_ns(), now=datetime(2026, 3, 15)) == (False, "Puanlama dönemi henüz başlamadı. Puanlama başlangıcı: 01.04.2026 00:00")
    assert validate_scoring_window(_period_ns(scoring_end_date=datetime(2026, 4, 30)), now=now) == (False, "Puanlama süresi sona erdi. Bitiş: 30.04.2026 00:00")

    # Timing does not matter for the extracted rule: weights are set before scoring starts.
    assert validate_period_scores_mutable(_period_ns()) == (True, "")
    assert validate_period_scores_mutable(_period_ns(results_published=True, is_locked=True)) == (False, _PUBLISHED_MESSAGE)
    assert validate_period_scores_mutable(_period_ns(is_locked=True)) == (False, _LOCKED_MESSAGE)
