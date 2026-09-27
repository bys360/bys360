"""BYS360 PERFORMANCE P2 (overnight): the snapshot step after a publication is all-or-nothing.

Routes (app/performance/engagement_publish_routes.py; login + admin + menu
"performance_publish"): the period publish and the single publish commit the
publication first (flags, publish logs), then run the snapshot step in an inner
try/except, then send the notifications and commit again. A snapshot failure is
reported as a warning and the publication stays committed (existing design).

Verified at 18a7f00014b9f4bf9f3f8c537533a7fa48266514:

- an error on the 2nd / 3rd card left 1 / 2 of the 3 snapshots committed, without
  rankings and without the period snapshot stamp; an error while ranking left all
  3 snapshots unranked;
- a database error inside the step (snapshot INSERT, the period stamp UPDATE)
  broke the session, so the notification step failed as well: the outer handler
  rolled back, flashed "Toplu yayın sırasında hata oluştu." although the
  publication was already committed, and no notification was sent;
- the single publish flushed its snapshot INSERT only after the inner handler, so
  an INSERT error became "Tekil yayın sırasında hata oluştu." for a committed
  publication, again without notifications.

Since P2 the snapshot step runs in a SAVEPOINT (the precedent of
low_score_process_service.ensure_low_score_processes_for_period and
meeting_rule_enforcement): on any failure every snapshot-step change (snapshots,
the deactivated previous version, rankings, the period stamp) is rolled back, the
session stays usable, the warning is shown and the notifications and the success
message follow as for any committed publication. The committed publication is
never rolled back. The missing snapshots are repaired by the P0.2AA backfill.

Real Flask app, real admin login, real personnel-support approval and publish /
unpublish / backfill routes; file-backed SQLite test database only. The
Alembic-owned personnel-support approval table is created with the DDL used by
tests/behavior/test_personnel_support_publish_approval_workflow_contract.py.
"""
from __future__ import annotations

import importlib
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

_SERVICE_MODULE = "app.services.performance_snapshot_service"
_SNAPSHOT_WARNING_PREFIX = "Yayın tamamlandı ancak snapshot oluşturulurken hata oluştu"
_PASSWORD = "TestSnapshotStageAtomicity1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_overnight_p2_snapshot_stage")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."

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
        "SECRET_KEY": "test-secret-key-for-overnight-p2-snapshot-stage",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p2_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P2SS{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p2-snapshot-stage-{n}@bys360.test",
            ad="P2Snapshot",
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
    one criteria set; one open, ended quarter; three approved 90/70/100 cards."""
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
            criteria = PerformanceCriteria(name=f"P2 Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P2 Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        period_id = int(period.id)
    env = SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids, period_id=period_id)
    env.cards = [_card(env, level_1, level_2) for level_1, level_2 in (((4, 4), (5, 5)), ((3, 3), (4, 4)), ((5, 5), (5, 5)))]
    _calculate(env)
    for evaluation_id in env.cards:
        _personnel_support_approve(env, evaluation_id)
    return env


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


def _calculate(env: SimpleNamespace) -> None:
    response = env.admin.post(
        "/performance/hierarchy-settings",
        data={"action": "save_weights", "period_id": str(env.period_id), "evaluator_1_weight": "50", "evaluator_2_weight": "50", "evaluator_3_weight": "0"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert ("success", "Dönem ağırlıkları güncellendi.") in _flashes(env.admin)


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


def _state(env: SimpleNamespace) -> dict[str, Any]:
    """What a fresh session sees: snapshots, the period snapshot stamp, publication and notifications."""
    from app.extensions import db

    with env.app.app_context():
        db.session.remove()
        state = {
            "snapshots": [
                (row[0], row[1], bool(row[2]), row[3])
                for row in db.session.execute(text("SELECT evaluation_id, version_no, is_current, ranking_in_scope FROM performance_result_snapshots ORDER BY id")).all()
            ],
            "period_stamp": tuple(db.session.execute(text("SELECT snapshot_status, snapshot_generated_at, snapshot_generated_by_id FROM performance_periods")).one()),
            "published": [int(row[0]) for row in db.session.execute(text("SELECT id FROM performance_evaluations WHERE is_published_to_employee = 1 ORDER BY id")).all()],
            "publish_logs": int(db.session.execute(text("SELECT COUNT(*) FROM performance_publish_logs")).scalar_one()),
            "mail_logs": int(db.session.execute(text("SELECT COUNT(*) FROM mail_logs")).scalar_one()),
        }
        db.session.remove()
    return state


def _fail_on_card(position: int):
    def _install(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):
        service = importlib.import_module(_SERVICE_MODULE)
        real = service.create_snapshot_for_evaluation
        calls: list[int] = []

        def _flaky(evaluation_id, actor_user_id=None):
            calls.append(evaluation_id)
            if len(calls) == position:
                raise RuntimeError("simulated snapshot failure")
            return real(evaluation_id, actor_user_id=actor_user_id)

        monkeypatch.setattr(service, "create_snapshot_for_evaluation", _flaky)
        return None

    return _install


def _ranking_fails(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    service = importlib.import_module(_SERVICE_MODULE)

    def _fails(period_id):  # noqa: ARG001
        raise SQLAlchemyError("simulated ranking failure")

    monkeypatch.setattr(service, "_recalculate_period_rankings", _fails)
    return None


def _statement_fails(fragments: tuple[str, ...], error_class):
    def _install(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
        from app.extensions import db

        def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
            normalized = " ".join(statement.split()).upper()
            if all(fragment in normalized for fragment in fragments):
                raise error_class(statement, parameters, Exception("simulated database error"))

        with env.app.app_context():
            engine = db.engine
        event.listen(engine, "before_cursor_execute", _fail)
        return lambda: event.remove(engine, "before_cursor_execute", _fail)

    return _install


_FAILURES = {
    "first_card": _fail_on_card(1),
    "second_card": _fail_on_card(2),
    "third_card": _fail_on_card(3),
    "ranking": _ranking_fails,
    "period_stamp_update": _statement_fails(("UPDATE PERFORMANCE_PERIODS SET", "SNAPSHOT_STATUS"), OperationalError),
    "snapshot_insert_integrity_error": _statement_fails(("INSERT INTO PERFORMANCE_RESULT_SNAPSHOTS",), IntegrityError),
    "snapshot_insert_operational_error": _statement_fails(("INSERT INTO PERFORMANCE_RESULT_SNAPSHOTS",), OperationalError),
}


def test_successful_snapshot_step_is_unchanged(env) -> None:
    env.admin.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    assert _flashes(env.admin) == [("success", "3 sonuç yayımlandı."), ("info", "Bilgilendirme e-postası sonucu: başarılı 0, hatalı 9.")]
    after = _state(env)
    assert after["snapshots"] == [(env.cards[0], 1, True, 2), (env.cards[1], 1, True, 3), (env.cards[2], 1, True, 1)]
    assert (after["period_stamp"][0], after["period_stamp"][2]) == ("completed", env.admin_id)
    assert (after["published"], after["publish_logs"], after["mail_logs"]) == (env.cards, 3, 9)


@pytest.mark.parametrize("failure", list(_FAILURES))
def test_failed_snapshot_step_leaves_no_partial_snapshot_data(env, monkeypatch, failure) -> None:
    before = _state(env)
    undo = _FAILURES[failure](env, monkeypatch)
    try:
        response = env.admin.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    finally:
        if undo:
            undo()
    flashes = _flashes(env.admin)
    assert response.status_code == 302
    assert flashes[0][0] == "warning" and flashes[0][1].startswith(_SNAPSHOT_WARNING_PREFIX)
    assert flashes[1:] == [("success", "3 sonuç yayımlandı."), ("info", "Bilgilendirme e-postası sonucu: başarılı 0, hatalı 9.")]
    after = _state(env)
    assert after["snapshots"] == before["snapshots"] == []  # snapshots and rankings: all or nothing
    assert after["period_stamp"] == before["period_stamp"]
    assert (after["published"], after["publish_logs"], after["mail_logs"]) == (env.cards, 3, 9)  # the publication stays committed


def test_the_backfill_repairs_a_failed_snapshot_step(env) -> None:
    with pytest.MonkeyPatch.context() as patch:
        _FAILURES["third_card"](env, patch)
        env.admin.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    _flashes(env.admin)
    env.admin.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    assert _flashes(env.admin) == [("warning", "Bu dönem sonuçları zaten yayımlanmış görünüyor.")]
    env.admin.post("/performance/snapshots/backfill", data={}, follow_redirects=False)
    assert _flashes(env.admin) == [("success", "Snapshot backfill tamamlandı. Dönem: 1, Yeni: 3, Atlanan: 0")]
    assert _state(env)["snapshots"] == [(env.cards[0], 1, True, 2), (env.cards[1], 1, True, 3), (env.cards[2], 1, True, 1)]


def test_single_publish_snapshot_failure_keeps_the_previous_version_current(env, monkeypatch) -> None:
    """Published (v1), unpublished (v1 stays current, P0.2V), published again with a
    failing snapshot INSERT: the deactivation of v1 is rolled back with the step."""
    evaluation_id = env.cards[0]
    assert env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False).status_code == 302
    assert env.admin.post(f"/performance/unpublish/evaluation/{evaluation_id}", data={}, follow_redirects=False).status_code == 302
    _flashes(env.admin)
    before = _state(env)
    assert before["snapshots"] == [(evaluation_id, 1, True, None)]

    undo = _statement_fails(("INSERT INTO PERFORMANCE_RESULT_SNAPSHOTS",), IntegrityError)(env, monkeypatch)
    try:
        env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    finally:
        undo()
    flashes = _flashes(env.admin)
    assert flashes[0][0] == "warning" and flashes[0][1].startswith(_SNAPSHOT_WARNING_PREFIX)
    assert flashes[1:] == [("success", "Sonuç personele yayımlandı."), ("info", "Bilgilendirme e-postası sonucu: başarılı 0, hatalı 3.")]
    after = _state(env)
    assert after["snapshots"] == [(evaluation_id, 1, True, None)]
    assert (after["published"], after["mail_logs"]) == ([evaluation_id], before["mail_logs"] + 3)
