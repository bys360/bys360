"""BYS360 PERFORMANCE POST-OVERNIGHT P1: a failing mail stage never rolls back or denies a committed publication.

Routes (app/performance/engagement_publish_routes.py; login + admin + menu
"performance_publish"): the period publish and the single publish commit the
publication (flags, publish logs), run the snapshot step in a SAVEPOINT (P2), send
the notifications and commit again. The mail stage is best-effort by its own
contract: mail_core.send_email never raises (a delivery failure is a MailLog row with
is_success=False and is counted in the "Bilgilendirme e-postası sonucu" message).

Verified at 2c7a46a7665e3ff343c5f08db33a4ae188a051fc: an exception in the mail stage
(the mail builder / sender raising, or a database error on the mail_logs INSERT at
the final commit) reached the outer handler, which rolled back and flashed "Toplu
yayın sırasında hata oluştu." / "Tekil yayın sırasında hata oluştu." although the
publication was already committed; the rollback also discarded the successful
snapshot step (no snapshot, no ranking, period stamp back to "not_started"). The
retry was refused ("zaten yayımlanmış") and only the P0.2AA backfill restored the
snapshots.

Since this change the snapshot step's result is committed right after the step
(before the mail stage), and a failure after the publication commit is reported as
"Yayın tamamlandı ancak bilgilendirme e-postaları gönderilirken hata oluştu." The
publication and the snapshots stay; only the mail stage's own rows are rolled back.
A failure before the publication commit keeps the existing error message.

Real Flask app, real admin login, real personnel-support approval and publish routes;
file-backed SQLite test database only. The Alembic-owned personnel-support approval
table is created with the DDL used by
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

_SENDER_MODULE = "app.services.mail_performance_sender"
_ROUTES_MODULE = "app.performance.engagement_publish_routes"
_MAIL_STAGE_WARNING = ("warning", "Yayın tamamlandı ancak bilgilendirme e-postaları gönderilirken hata oluştu.")
_SNAPSHOT_WARNING = ("warning", "Yayın tamamlandı ancak snapshot oluşturulurken hata oluştu.")
_PASSWORD = "TestMailStageConsistency1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_post_overnight_p1_mail_stage")
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
        "SECRET_KEY": "test-secret-key-for-post-overnight-p1-mail-stage",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p1m_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P1MS{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p1-mail-stage-{n}@bys360.test",
            ad="P1Mail",
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
            criteria = PerformanceCriteria(name=f"P1M Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P1M Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
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
    """What a fresh session sees: publication, publish logs, snapshots, the period stamp, mail logs."""
    from app.extensions import db

    with env.app.app_context():
        db.session.remove()
        state = {
            "published": [
                (int(row[0]), bool(row[1]), row[2] is not None)
                for row in db.session.execute(text("SELECT id, is_published_to_employee, published_to_employee_at FROM performance_evaluations ORDER BY id")).all()
            ],
            "period": tuple(db.session.execute(text("SELECT results_published, published_at IS NOT NULL, snapshot_status FROM performance_periods")).one()),
            "publish_logs": [tuple(row) for row in db.session.execute(text("SELECT action_type, evaluation_id FROM performance_publish_logs ORDER BY id")).all()],
            "snapshots": [
                (row[0], row[1], bool(row[2]), row[3])
                for row in db.session.execute(text("SELECT evaluation_id, version_no, is_current, ranking_in_scope FROM performance_result_snapshots ORDER BY id")).all()
            ],
            "mail_logs": int(db.session.execute(text("SELECT COUNT(*) FROM mail_logs")).scalar_one()),
        }
        db.session.remove()
    return state


def _mail_call_fails(name: str, position: int, error: Exception):
    def _install(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
        sender = importlib.import_module(_SENDER_MODULE)
        real = getattr(sender, name)
        calls: list[int] = []

        def _flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) == position:
                raise error
            return real(*args, **kwargs)

        monkeypatch.setattr(sender, name, _flaky)
        return None

    return _install


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


_MAIL_STAGE_FAILURES = {
    "first_mail_raises": _mail_call_fails("send_email", 1, RuntimeError("simulated mail failure")),
    "second_mail_raises": _mail_call_fails("send_email", 2, RuntimeError("simulated mail failure")),
    "mail_log_builder_raises": _mail_call_fails("create_mail_log", 1, SQLAlchemyError("simulated mail log failure")),
    "mail_log_insert_integrity_error": _statement_fails(("INSERT INTO MAIL_LOGS",), IntegrityError),
    "mail_log_insert_operational_error": _statement_fails(("INSERT INTO MAIL_LOGS",), OperationalError),
}


def _post(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, url: str, failure: str | None = None):
    undo = _MAIL_STAGE_FAILURES[failure](env, monkeypatch) if failure else None
    try:
        response = env.admin.post(url, data={}, follow_redirects=False)
    finally:
        if undo:
            undo()
    return response, _flashes(env.admin)


# ---------------------------------------------------------------------------
# Successful mail stage: unchanged
# ---------------------------------------------------------------------------


def test_successful_period_publish_is_unchanged(env, monkeypatch) -> None:
    response, flashes = _post(env, monkeypatch, f"/performance/publish/period/{env.period_id}")
    assert response.status_code == 302
    assert flashes == [("success", "3 sonuç yayımlandı."), ("info", "Bilgilendirme e-postası sonucu: başarılı 0, hatalı 9.")]
    after = _state(env)
    assert after["snapshots"] == [(env.cards[0], 1, True, 2), (env.cards[1], 1, True, 3), (env.cards[2], 1, True, 1)]
    assert (after["period"], after["mail_logs"]) == ((1, 1, "completed"), 9)


# ---------------------------------------------------------------------------
# Mail stage failure after the publication commit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("failure", list(_MAIL_STAGE_FAILURES))
def test_period_publish_mail_stage_failure_keeps_publication_and_snapshots(env, monkeypatch, failure) -> None:
    response, flashes = _post(env, monkeypatch, f"/performance/publish/period/{env.period_id}", failure)
    assert response.status_code == 302
    assert flashes == [_MAIL_STAGE_WARNING]  # never "Toplu yayın sırasında hata oluştu."
    after = _state(env)
    assert after["published"] == [(card, True, True) for card in env.cards]
    assert after["publish_logs"] == [("bulk_publish", card) for card in env.cards]
    assert after["snapshots"] == [(env.cards[0], 1, True, 2), (env.cards[1], 1, True, 3), (env.cards[2], 1, True, 1)]
    assert after["period"] == (1, 1, "completed")
    assert after["mail_logs"] == 0  # only the mail stage's own rows are rolled back


@pytest.mark.parametrize("failure", list(_MAIL_STAGE_FAILURES))
def test_single_publish_mail_stage_failure_keeps_publication_and_snapshot(env, monkeypatch, failure) -> None:
    evaluation_id = env.cards[0]
    response, flashes = _post(env, monkeypatch, f"/performance/publish/evaluation/{evaluation_id}", failure)
    assert response.status_code == 302
    assert flashes == [_MAIL_STAGE_WARNING]  # never "Tekil yayın sırasında hata oluştu."
    after = _state(env)
    assert after["published"] == [(env.cards[0], True, True), (env.cards[1], False, False), (env.cards[2], False, False)]
    assert after["publish_logs"] == [("publish", evaluation_id)]
    assert after["snapshots"] == [(evaluation_id, 1, True, None)]
    assert after["mail_logs"] == 0


def test_snapshot_warning_and_mail_stage_warning_are_both_reported(env, monkeypatch) -> None:
    service = importlib.import_module("app.services.performance_snapshot_service")

    def _snapshot_fails(evaluation_id, actor_user_id=None):  # noqa: ARG001
        raise RuntimeError("simulated snapshot failure")

    monkeypatch.setattr(service, "create_snapshot_for_evaluation", _snapshot_fails)
    response, flashes = _post(env, monkeypatch, f"/performance/publish/period/{env.period_id}", "first_mail_raises")
    assert response.status_code == 302
    assert flashes == [_SNAPSHOT_WARNING, _MAIL_STAGE_WARNING]
    after = _state(env)
    assert after["published"] == [(card, True, True) for card in env.cards]
    assert (after["snapshots"], after["period"], after["mail_logs"]) == ([], (1, 1, "not_started"), 0)


def test_retry_after_a_mail_stage_failure_needs_no_repair(env, monkeypatch) -> None:
    _post(env, monkeypatch, f"/performance/publish/period/{env.period_id}", "mail_log_insert_operational_error")
    snapshots = _state(env)["snapshots"]
    assert len(snapshots) == 3
    _response, flashes = _post(env, monkeypatch, f"/performance/publish/period/{env.period_id}")
    assert flashes == [("warning", "Bu dönem sonuçları zaten yayımlanmış görünüyor.")]
    env.admin.post("/performance/snapshots/backfill", data={}, follow_redirects=False)
    assert _flashes(env.admin) == [("success", "Snapshot backfill tamamlandı. Dönem: 1, Yeni: 0, Atlanan: 3")]
    assert _state(env)["snapshots"] == snapshots


# ---------------------------------------------------------------------------
# Failure before the publication commit: the existing error contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["period", "single"])
def test_failure_before_the_publication_commit_keeps_the_existing_error(env, monkeypatch, route) -> None:
    routes = importlib.import_module(_ROUTES_MODULE)

    def _log_fails(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("simulated publish log failure")

    monkeypatch.setattr(routes, "create_publish_log", _log_fails)
    before = _state(env)
    url = f"/performance/publish/period/{env.period_id}" if route == "period" else f"/performance/publish/evaluation/{env.cards[0]}"
    response, flashes = _post(env, monkeypatch, url)
    assert response.status_code == 302
    assert flashes == [("danger", "Toplu yayın sırasında hata oluştu." if route == "period" else "Tekil yayın sırasında hata oluştu.")]
    assert _state(env) == before


# ---------------------------------------------------------------------------
# Live v2 period publish / unpublish: the handler rolls back like the other publish routes
# ---------------------------------------------------------------------------


def _v2(env: SimpleNamespace, action: str):
    data = {"period_id": str(env.period_id), "publish_action": action}
    if action == "publish":
        data["force_publish"] = "1"
    return env.admin.post("/performance/v2/faz5/publish", data=data, follow_redirects=False)


@pytest.mark.parametrize("failure", ["mail_log_insert_integrity_error", "mail_log_insert_operational_error"])
def test_v2_publish_database_error_after_the_publication_commit_redirects(env, monkeypatch, failure) -> None:
    """performance_v2.publish_workspace commits the publication, then sends the notifications
    and commits again. Verified at 2c7a46a7665e3ff343c5f08db33a4ae188a051fc: a database error
    on the mail_logs INSERT left the session unusable because the route's handler did not
    roll back, so building the redirect failed with HTTP 500 although the publication was
    committed. Since this change the handler rolls back like the module's other publish
    routes. Its existing message is kept (that it does not say the publication was committed
    is an open review item: the notification stage runs inside the service)."""
    undo = _MAIL_STAGE_FAILURES[failure](env, monkeypatch)
    try:
        response = _v2(env, "publish")
    finally:
        if undo:
            undo()
    assert response.status_code == 302
    assert _flashes(env.admin) == [("danger", "Yayın işlemi sırasında beklenmeyen bir hata oluştu.")]
    after = _state(env)
    assert after["published"] == [(card, True, True) for card in env.cards]
    assert (after["publish_logs"], after["snapshots"], after["mail_logs"]) == ([], [], 0)


def test_v2_unpublish_database_error_redirects_and_changes_nothing(env, monkeypatch) -> None:
    assert _v2(env, "publish").status_code == 302
    _flashes(env.admin)
    before = _state(env)
    undo = _statement_fails(("UPDATE PERFORMANCE_EVALUATIONS SET",), OperationalError)(env, monkeypatch)
    try:
        response = _v2(env, "unpublish")
    finally:
        undo()
    assert response.status_code == 302
    assert _flashes(env.admin) == [("danger", "Yayın işlemi sırasında beklenmeyen bir hata oluştu.")]
    assert _state(env) == before
