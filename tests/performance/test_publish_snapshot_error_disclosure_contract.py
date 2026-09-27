"""BYS360 PERFORMANCE P1 (overnight): a snapshot failure after publication never shows technical details.

Routes (app/performance/engagement_publish_routes.py; login + admin + menu
"performance_publish"):

- POST /performance/publish/period/<id> (main.performance_publish_period):
  publish_period_results -> bulk_publish logs -> commit -> create_snapshots_for_period
  (inner try/except) -> notifications -> commit; outer try/except.
- POST /performance/publish/evaluation/<id> (main.performance_publish_evaluation):
  publish_evaluation -> publish log -> commit -> create_snapshot_for_evaluation
  (inner try/except) -> notifications -> commit; outer try/except.

Verified at 18a7f00014b9f4bf9f3f8c537533a7fa48266514: both inner handlers flashed
"Yayın tamamlandı ancak snapshot oluşturulurken hata oluştu: {exc}", so the admin saw
the raw exception text: a driver error carried the full INSERT statement, the bind
parameters with the employee's name and sicil number, and SQLAlchemy internals.
This is the H1F defect shape (tests/behavior/test_h1f_route_exception_leak_contract.py)
left in a route file of the H1F scope.

Since P1 the inner handlers show the same sentence without the exception text; the
exception is still logged server-side with its traceback. Publication itself is
unchanged (it was committed before the snapshot step).

Real Flask app, real admin login, real personnel-support approval and publish
routes; file-backed SQLite test database only. The Alembic-owned personnel-support
approval table is created with the DDL used by
tests/behavior/test_personnel_support_publish_approval_workflow_contract.py.
"""
from __future__ import annotations

import importlib
import logging
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

_ROUTES_MODULE = "app.performance.engagement_publish_routes"
_SERVICE_MODULE = "app.services.performance_snapshot_service"
_SENTINEL = "TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A"
_SAFE_SNAPSHOT_WARNING = ("warning", "Yayın tamamlandı ancak snapshot oluşturulurken hata oluştu.")
_PASSWORD = "SnapshotErrorDisclosure1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_overnight_p1_snapshot_error")
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
        "SECRET_KEY": "test-secret-key-for-overnight-p1-snapshot-error",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p1_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P1SE{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p1-snapshot-error-{n}@bys360.test",
            ad="P1Snapshot",
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
            criteria = PerformanceCriteria(name=f"P1 Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P1 Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        period_id = int(period.id)
    env = SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids, period_id=period_id)
    env.cards = [_card(env, level_1, level_2) for level_1, level_2 in (((4, 4), (5, 5)), ((3, 3), (4, 4)), ((5, 5), (5, 5)))]
    _calculate(env)
    for evaluation_id in env.cards:
        _personnel_support_approve(env, evaluation_id)
    env.people = _people(env)
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


def _people(env: SimpleNamespace) -> dict[int, tuple[str, str]]:
    """Card id -> (employee full name, sicil) as the snapshot INSERT parameters carry them."""
    from app.extensions import db

    with env.app.app_context():
        rows = db.session.execute(
            text("SELECT e.id, u.ad || ' ' || u.soyad, u.sicil_no FROM performance_evaluations e JOIN users u ON u.id = e.employee_id")
        ).all()
        db.session.remove()
    return {int(row[0]): (row[1], row[2]) for row in rows}


def _published_ids(env: SimpleNamespace) -> list[int]:
    from app.extensions import db

    with env.app.app_context():
        ids = [int(row[0]) for row in db.session.execute(text("SELECT id FROM performance_evaluations WHERE is_published_to_employee = 1 ORDER BY id")).all()]
        db.session.remove()
    return ids


def _fail_snapshot_insert(env: SimpleNamespace, error_class):
    """A real driver error on the snapshot INSERT (its message carries the SQL and the bind parameters)."""
    from app.extensions import db

    def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().upper().startswith("INSERT INTO PERFORMANCE_RESULT_SNAPSHOTS"):
            raise error_class(statement, parameters, Exception(f"simulated {_SENTINEL}"))

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _fail)
    return lambda: event.remove(engine, "before_cursor_execute", _fail)


def _assert_nothing_technical_is_shown(env: SimpleNamespace, flashes: list[tuple[str, str]]) -> None:
    shown = " ".join(message for _category, message in flashes)
    for fragment in (_SENTINEL, "INSERT INTO", "[SQL:", "parameters:", "sqlalche.me", "Traceback", "Error", "autoflush"):
        assert fragment not in shown
    for name, sicil in env.people.values():
        assert name not in shown and sicil not in shown


def _assert_logged(caplog: pytest.LogCaptureFixture, marker: str) -> None:
    assert any(record.exc_info and marker in record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR)


# ---------------------------------------------------------------------------
# Period publish
# ---------------------------------------------------------------------------


def _raise_with(message_for):
    def _install(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):
        service = importlib.import_module(_SERVICE_MODULE)

        def _fails(evaluation_id, actor_user_id=None):  # noqa: ARG001
            raise RuntimeError(message_for(env, evaluation_id))

        monkeypatch.setattr(service, "create_snapshot_for_evaluation", _fails)
        return None

    return _install


def _driver(error_class):
    def _install(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
        return _fail_snapshot_insert(env, error_class)

    return _install


def _ranking_error(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    service = importlib.import_module(_SERVICE_MODULE)

    def _fails(period_id):  # noqa: ARG001
        raise SQLAlchemyError(f"ranking failed {_SENTINEL}")

    monkeypatch.setattr(service, "_recalculate_period_rankings", _fails)
    return None


_PERIOD_FAILURES = {
    "runtime_error": _raise_with(lambda env, evaluation_id: f"snapshot failed {_SENTINEL}"),
    "employee_name_in_exception": _raise_with(lambda env, evaluation_id: f"cannot snapshot {env.people[evaluation_id][0]}"),
    "employee_sicil_in_exception": _raise_with(lambda env, evaluation_id: f"duplicate sicil {env.people[evaluation_id][1]}"),
    "integrity_error_with_sql": _driver(IntegrityError),
    "operational_error_with_sql": _driver(OperationalError),
    "sqlalchemy_error": _ranking_error,
}


@pytest.mark.parametrize("failure", list(_PERIOD_FAILURES))
def test_period_publish_snapshot_failure_shows_a_fixed_message(env, monkeypatch, caplog, failure) -> None:
    caplog.set_level(logging.ERROR)
    undo = _PERIOD_FAILURES[failure](env, monkeypatch)
    try:
        response = env.admin.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    finally:
        if undo:
            undo()
    flashes = _flashes(env.admin)
    assert response.status_code == 302
    assert flashes[0] == _SAFE_SNAPSHOT_WARNING
    _assert_nothing_technical_is_shown(env, flashes)
    _assert_logged(caplog, "Snapshot create failed for period publish")
    assert _published_ids(env) == env.cards  # the publication was committed before the snapshot step


def test_period_publish_without_failure_is_unchanged(env, caplog) -> None:
    caplog.set_level(logging.ERROR)
    response = env.admin.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    flashes = _flashes(env.admin)
    assert response.status_code == 302
    assert flashes == [("success", "3 sonuç yayımlandı."), ("info", "Bilgilendirme e-postası sonucu: başarılı 0, hatalı 9.")]
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR and record.exc_info]


def test_period_publish_step_failure_keeps_its_fixed_message(env, monkeypatch, caplog) -> None:
    caplog.set_level(logging.ERROR)
    routes = importlib.import_module(_ROUTES_MODULE)

    def _fails(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError(f"publish log failed {_SENTINEL}")

    monkeypatch.setattr(routes, "create_publish_log", _fails)
    env.admin.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    flashes = _flashes(env.admin)
    assert flashes == [("danger", "Toplu yayın sırasında hata oluştu.")]
    _assert_nothing_technical_is_shown(env, flashes)
    _assert_logged(caplog, "beklenmeyen hata")
    assert _published_ids(env) == []


# ---------------------------------------------------------------------------
# Single publish
# ---------------------------------------------------------------------------


def test_single_publish_snapshot_failure_shows_a_fixed_message(env, monkeypatch, caplog) -> None:
    caplog.set_level(logging.ERROR)
    evaluation_id = env.cards[0]
    routes = importlib.import_module(_ROUTES_MODULE)

    def _fails(evaluation_id, actor_user_id=None):  # noqa: ARG001
        raise RuntimeError(f"snapshot failed {_SENTINEL} {env.people[evaluation_id][0]} {env.people[evaluation_id][1]}")

    monkeypatch.setattr(routes, "create_snapshot_for_evaluation", _fails)
    response = env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    flashes = _flashes(env.admin)
    assert response.status_code == 302
    assert flashes[0] == _SAFE_SNAPSHOT_WARNING
    assert ("success", "Sonuç personele yayımlandı.") in flashes
    _assert_nothing_technical_is_shown(env, flashes)
    _assert_logged(caplog, "Snapshot create failed for single publish")
    assert _published_ids(env) == [evaluation_id]


def test_single_publish_snapshot_driver_error_shows_nothing_technical(env, caplog) -> None:
    """The driver error surfaces in the snapshot step (deactivating the current version)."""
    from app.extensions import db

    caplog.set_level(logging.ERROR)
    evaluation_id = env.cards[0]

    def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if " ".join(statement.split()).upper().startswith("UPDATE PERFORMANCE_RESULT_SNAPSHOTS SET IS_CURRENT"):
            raise OperationalError(statement, parameters, Exception(f"simulated {_SENTINEL}"))

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _fail)
    try:
        env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    finally:
        event.remove(engine, "before_cursor_execute", _fail)
    flashes = _flashes(env.admin)
    assert flashes[0] == _SAFE_SNAPSHOT_WARNING
    _assert_nothing_technical_is_shown(env, flashes)
    _assert_logged(caplog, "Snapshot create failed for single publish")
    assert _published_ids(env) == [evaluation_id]
