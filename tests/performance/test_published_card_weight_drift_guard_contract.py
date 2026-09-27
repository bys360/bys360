"""BYS360 PERFORMANCE P8 (overnight): a weight save never recalculates a card that is published to the employee.

Route: POST /performance/hierarchy-settings action=save_weights
(main.performance_hierarchy_settings, app/performance/routes.py; login + admin +
menu "performance_hierarchy_assignments") -> scoring.recalculate_all_evaluations
rewrites every total of the period -> commit.

P0.2T (d236c258) blocks the save when the period is published or locked
(period_state_guard.validate_period_scores_mutable). Verified at
18a7f00014b9f4bf9f3f8c537533a7fa48266514 (P0.2U W8): when the period flag is off
but a card still carries the publication evidence (the period list toggle
"Yayından Kaldır" flips only period.results_published), the save recalculated
the published card (90 -> 84) while its publication snapshot kept 90.

Since P8 the save also refuses while any card of the period carries the
publication evidence used everywhere else (is_published_to_employee or
published_to_employee_at; P0.2S, the mobile task actions, P0.2AA/AB):
"Bu dönemde personele yayınlanmış değerlendirme bulunduğu için puanlama
değişikliği yapılamaz." No write happens. The period-level messages keep their
precedence; the correction path stays an explicit unpublish first. The toggle
itself is not changed.

Real Flask app, real admin login and permissions, real personnel-support /
single publish / unpublish / period toggle routes; file-backed SQLite test
database only. The Alembic-owned personnel-support approval table is created
with the DDL used by tests/behavior/test_personnel_support_publish_approval_workflow_contract.py.
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

_PASSWORD = "PublishedCardWeightDrift1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_overnight_p8_weight_drift")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_CARD_MESSAGE = "Bu dönemde personele yayınlanmış değerlendirme bulunduğu için puanlama değişikliği yapılamaz."
_PUBLISHED_MESSAGE = "Bu dönem sonuçları yayınlandığı için puanlama değişikliği yapılamaz."
_LOCKED_MESSAGE = "Bu dönem kilitli olduğu için puanlama değişikliği yapılamaz."

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
        "SECRET_KEY": "test-secret-key-for-overnight-p8-weight-drift",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p8_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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


def _user(flask_app, *, role: str, managers: tuple[str | None, str | None] | None = None, unvan: str | None = None) -> tuple[int, str]:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        n = _next()
        sicil_no = f"P8WD{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p8-weight-drift-{n}@bys360.test",
            ad="P8Weight",
            soyad=f"Kisi{n}",
            role=role,
            unvan=unvan,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        if managers:
            user.yonetici_sicil, user.ikinci_yonetici_sicil = managers
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
    """Admin and the Personel ve Destek Hizmetleri Grup Başkanı, logged in for real;
    one criteria set; one open quarter."""
    from app.extensions import db
    from app.models import PerformanceCriteria, PerformancePeriod

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
            criteria = PerformanceCriteria(name=f"P8 Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P8 Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        period_id = int(period.id)
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids, period_id=period_id)


def _card(env: SimpleNamespace, level_1_scores: tuple[int, int], level_2_scores: tuple[int, int]) -> int:
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem

    l1_id, l1_sicil = _user(env.app, role="grup_baskani")
    l2_id, l2_sicil = _user(env.app, role="koordinator")
    employee_id, _sicil = _user(env.app, role="personel", managers=(l1_sicil, l2_sicil))
    with env.app.app_context():
        evaluation = PerformanceEvaluation(
            period_id=env.period_id, employee_id=employee_id, level_1_evaluator_id=l1_id, level_2_evaluator_id=l2_id,
            level_1_completed=True, level_2_completed=True, status="tamamlandi", workflow_status="tamamlandi", level_1_general_comment=_COMMENT,
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


def _save_weights(env: SimpleNamespace, w1: int, w2: int) -> tuple[Any, list[tuple[str, str]], list[str]]:
    """Real settings POST; returns the response, its flashes and every DML statement issued."""
    from app.extensions import db

    dml: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            dml.append(statement)

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = env.admin.post(
            "/performance/hierarchy-settings",
            data={"action": "save_weights", "period_id": str(env.period_id), "evaluator_1_weight": str(w1), "evaluator_2_weight": str(w2), "evaluator_3_weight": "0"},
            follow_redirects=False,
        )
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return response, _flashes(env.admin), dml


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


def _publish(env: SimpleNamespace, evaluation_id: int) -> None:
    _personnel_support_approve(env, evaluation_id)
    response = env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Sonuç personele yayımlandı.") in _flashes(env.admin)


def _toggle_period_publish(env: SimpleNamespace, target: bool) -> None:
    """The real period list toggle ("Yayınla" / "Yayından Kaldır")."""
    response = env.admin.post(f"/performance/periods/{env.period_id}/toggle-publish", data={"target_state": "true" if target else "false"}, follow_redirects=False)
    assert response.status_code == 302
    assert _flashes(env.admin) == [("success", "Dönem yayın durumu güncellendi.")]


def _set_card(env: SimpleNamespace, evaluation_id: int, **columns: Any) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with env.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        for key, value in columns.items():
            setattr(evaluation, key, value)
        db.session.commit()


def _state(env: SimpleNamespace) -> dict[str, list[dict[str, Any]]]:
    from app.extensions import db

    params = {"p": env.period_id}
    with env.app.app_context():
        db.session.remove()
        state = {
            name: [dict(row) for row in db.session.execute(text(sql), params).mappings().all()]
            for name, sql in {
                "period": "SELECT * FROM performance_periods WHERE id = :p",
                "weights": "SELECT * FROM performance_weight_configs WHERE period_id = :p ORDER BY id",
                "evaluations": "SELECT * FROM performance_evaluations WHERE period_id = :p ORDER BY id",
                "processes": "SELECT * FROM performance_low_score_processes WHERE period_id = :p ORDER BY id",
                "snapshots": "SELECT * FROM performance_result_snapshots WHERE period_id = :p ORDER BY id",
            }.items()
        }
        db.session.remove()
    return state


def _finals(state: dict[str, list[dict[str, Any]]]) -> list[float]:
    return [row["final_total_100"] for row in state["evaluations"]]


def _assert_blocked(env: SimpleNamespace, message: str) -> dict[str, list[dict[str, Any]]]:
    from flask import url_for

    before = _state(env)
    response, flashes, dml = _save_weights(env, 80, 20)
    assert response.status_code == 302
    with env.app.test_request_context():
        assert response.headers["Location"] == url_for("main.performance_hierarchy_settings", period_id=env.period_id, scope="all")
    assert flashes == [("warning", message)]
    assert dml == []
    after = _state(env)
    assert after == before
    return after


# ---------------------------------------------------------------------------
# Card-level publication evidence blocks the recalculation
# ---------------------------------------------------------------------------


def test_period_flag_switched_off_while_the_card_stays_published(env) -> None:
    """P0.2U W8: publish, then the period list "Yayından Kaldır" toggle."""
    evaluation_id = _card(env, (4, 4), (5, 5))  # 80 / 100
    _save_weights(env, 50, 50)
    _publish(env, evaluation_id)
    _toggle_period_publish(env, False)
    state = _assert_blocked(env, _CARD_MESSAGE)
    assert _finals(state) == [90.0]
    assert [(row["final_total_100"], bool(row["is_current"])) for row in state["snapshots"]] == [(90.0, True)]


@pytest.mark.parametrize(
    ("flag", "published_at"),
    [(True, None), (False, datetime(2026, 4, 2)), (True, datetime(2026, 4, 2))],
    ids=["flag_only", "timestamp_only", "flag_and_timestamp"],
)
def test_any_card_publication_evidence_blocks(env, flag, published_at) -> None:
    evaluation_id = _card(env, (4, 4), (5, 5))
    _save_weights(env, 50, 50)
    _set_card(env, evaluation_id, is_published_to_employee=flag, published_to_employee_at=published_at)
    assert _finals(_assert_blocked(env, _CARD_MESSAGE)) == [90.0]


def test_one_published_card_blocks_the_whole_period(env) -> None:
    published = _card(env, (4, 4), (5, 5))
    _card(env, (3, 3), (5, 5))
    _save_weights(env, 50, 50)
    _set_card(env, published, is_published_to_employee=True, published_to_employee_at=datetime(2026, 4, 2))
    assert _finals(_assert_blocked(env, _CARD_MESSAGE)) == [90.0, 80.0]


def test_several_published_cards_block(env) -> None:
    flag_only = _card(env, (4, 4), (5, 5))
    timestamp_only = _card(env, (3, 3), (5, 5))
    _save_weights(env, 50, 50)
    _set_card(env, flag_only, is_published_to_employee=True, published_to_employee_at=None)
    _set_card(env, timestamp_only, is_published_to_employee=False, published_to_employee_at=datetime(2026, 4, 2))
    assert _finals(_assert_blocked(env, _CARD_MESSAGE)) == [90.0, 80.0]


def test_period_level_messages_keep_their_precedence(env) -> None:
    evaluation_id = _card(env, (4, 4), (5, 5))
    _save_weights(env, 50, 50)
    _publish(env, evaluation_id)  # the single publish also marks the period published
    _assert_blocked(env, _PUBLISHED_MESSAGE)


def test_locked_period_keeps_its_message_over_the_card_check(env) -> None:
    evaluation_id = _card(env, (4, 4), (5, 5))
    _save_weights(env, 50, 50)
    _set_card(env, evaluation_id, is_published_to_employee=True, published_to_employee_at=datetime(2026, 4, 2))  # period flag off
    response = env.admin.post(f"/performance/periods/{env.period_id}/toggle-lock", data={"target_state": "true"}, follow_redirects=False)
    assert response.status_code == 302
    assert _flashes(env.admin) == [("success", "Dönem kilitlendi.")]
    assert _finals(_assert_blocked(env, _LOCKED_MESSAGE)) == [90.0]


# ---------------------------------------------------------------------------
# Unchanged paths
# ---------------------------------------------------------------------------


def test_open_period_without_published_cards_still_recalculates(env) -> None:
    _card(env, (3, 3), (5, 5))  # 60 / 100
    response, flashes, _dml = _save_weights(env, 50, 50)
    assert response.status_code == 302 and flashes[0] == ("success", "Dönem ağırlıkları güncellendi.")
    assert _finals(_state(env)) == [80.0]
    _save_weights(env, 80, 20)
    assert _finals(_state(env)) == [68.0]


def test_unpublish_then_save_is_the_correction_path(env) -> None:
    evaluation_id = _card(env, (4, 4), (5, 5))
    _save_weights(env, 50, 50)
    _publish(env, evaluation_id)
    _toggle_period_publish(env, False)
    response = env.admin.post(f"/performance/unpublish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Sonuç yayından kaldırıldı.") in _flashes(env.admin)
    _response, flashes, _dml = _save_weights(env, 80, 20)
    assert flashes[0] == ("success", "Dönem ağırlıkları güncellendi.")
    assert _finals(_state(env)) == [84.0]


def test_database_error_in_the_card_check_changes_nothing(env) -> None:
    from app.extensions import db

    evaluation_id = _card(env, (4, 4), (5, 5))
    _save_weights(env, 50, 50)
    _set_card(env, evaluation_id, is_published_to_employee=True, published_to_employee_at=datetime(2026, 4, 2))  # period flag stays off
    before = _state(env)
    failed: list[str] = []

    def _fail_once(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        normalized = " ".join(statement.split()).lower()
        if not failed and "from performance_evaluations" in normalized and "published_to_employee_at is not null" in normalized:
            failed.append(statement)
            raise OperationalError(statement, parameters, Exception("simulated database outage"))

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _fail_once)
    try:
        response, _flashes_after_render, _dml = _save_weights(env, 80, 20)
    finally:
        event.remove(engine, "before_cursor_execute", _fail_once)
    assert failed  # the card check ran and failed
    assert response.status_code == 200  # the existing error path: rollback, danger message, settings page
    assert "Ağırlık ayarları kaydedilirken hata oluştu." in response.get_data(as_text=True)
    assert _state(env) == before
