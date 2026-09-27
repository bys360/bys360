"""BYS360 PERFORMANCE P4 (overnight): a card published to the employee cannot be withdrawn or returned on the v2 web screen.

Route: POST /performance/v2/faz3/assignment/<id> (main.performance_v2_phase3_assignment,
app/performance/v2_routes.py; login + "admin or the assignment's evaluator")
action=withdraw -> evaluation_workspace.withdraw_assignment_submission,
action=return -> evaluation_workspace.return_assignment_to_previous_level;
ValueError -> rollback + danger flash (the route's existing validation contract).

Verified at 18a7f00014b9f4bf9f3f8c537533a7fa48266514: neither action looked at the
publication. On a card published to the employee (90, and an approved 70 altı 60)
the evaluator or an admin rolled the workflow back (level_1_completed=0,
workflow_status taslak_1_amir / level_2_iade, assignment taslak / iade) while the
card stayed published and visible (mobile 90/100).

The mobile task actions already refuse this with the card-level publication
evidence (is_published_to_employee or published_to_employee_at):
"Personele yayınlanmış değerlendirme mobil ekrandan geri çekilemez / iade edilemez."
(app/api/mobile/performance_routes.py), as the mobile rescore does (P0.2S). Since P4
the web actions apply the same rule before any change; the correction path is an
explicit unpublish first. Authorization is checked first and unchanged.

Real Flask app, real logins, real personnel-support / Başkan/Üst Onay / v2 period
publish routes; file-backed SQLite test database only. The Alembic-owned
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

_PASSWORD = "PublishedReturnWithdraw1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_overnight_p4_return_withdraw")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_BLOCKED = {
    "withdraw": ("danger", "Personele yayınlanmış değerlendirme geri çekilemez."),
    "return": ("danger", "Personele yayınlanmış değerlendirme iade edilemez."),
}
_DONE = {"withdraw": ("info", "Gönderim taslağa alındı."), "return": ("warning", "Kayıt 2. amire iade edildi.")}

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
        "SECRET_KEY": "test-secret-key-for-overnight-p4-return-withdraw",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p4_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P4RW{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p4-return-withdraw-{n}@bys360.test",
            ad="P4Workflow",
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
    one criteria set; one open, ended quarter."""
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
            criteria = PerformanceCriteria(name=f"P4 Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P4 Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        period_id = int(period.id)
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids, period_id=period_id)


def _card(env: SimpleNamespace, level_1_scores: tuple[int, int], level_2_scores: tuple[int, int]) -> SimpleNamespace:
    """A completed two-manager card with its level 1 / level 2 tasks; totals come from _calculate."""
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformanceEvaluationItem

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
        tasks = []
        for level, evaluator_id in ((1, l1_id), (2, l2_id)):
            task = EvaluationAssignment(period_id=env.period_id, employee_id=employee_id, evaluator_id=evaluator_id, manager_level=level, status="tamamlandi")
            db.session.add(task)
            db.session.flush()
            tasks.append(int(task.id))
        db.session.commit()
        return SimpleNamespace(id=int(evaluation.id), employee_id=employee_id, level_1_task=tasks[0], level_1_sicil=l1_sicil)


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


def _president_approve(env: SimpleNamespace, evaluation_id: int) -> None:
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


def _v2_publish(env: SimpleNamespace) -> None:
    response = env.admin.post("/performance/v2/faz5/publish", data={"period_id": str(env.period_id), "publish_action": "publish", "force_publish": "1"}, follow_redirects=False)
    assert response.status_code == 302
    _flashes(env.admin)


def _published_card(env: SimpleNamespace, *, low_score: bool = False) -> SimpleNamespace:
    card = _card(env, (2, 2), (4, 4)) if low_score else _card(env, (4, 4), (5, 5))  # 60 / 90
    _calculate(env)
    if low_score:
        _president_approve(env, card.id)
    _personnel_support_approve(env, card.id)
    _v2_publish(env)
    return card


def _client_for(env: SimpleNamespace, card: SimpleNamespace, who: str):
    if who == "admin":
        return env.admin
    client = env.app.test_client()
    if who == "evaluator":
        _login(client, card.level_1_sicil)
    elif who == "other_manager":
        _uid, sicil = _user(env.app, role="grup_baskani")
        _login(client, sicil)
    return client


def _act(env: SimpleNamespace, client, card: SimpleNamespace, action: str) -> tuple[Any, list[tuple[str, str]], list[str]]:
    """Real v2 task POST; returns the response, its flashes and every DML statement issued."""
    from app.extensions import db

    dml: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        words = statement.split()
        if words and words[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            dml.append(" ".join(words[:3]) if words[0].upper() != "UPDATE" else " ".join(words[:2]))

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = client.post(f"/performance/v2/faz3/assignment/{card.level_1_task}", data={"action": action, "return_note": "Düzeltme gerekli"}, follow_redirects=False)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return response, _flashes(client), dml


def _state(env: SimpleNamespace) -> dict[str, list[dict[str, Any]]]:
    from app.extensions import db

    with env.app.app_context():
        db.session.remove()
        state = {
            table: [dict(row) for row in db.session.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings().all()]  # noqa: S608
            for table in ("performance_evaluations", "evaluation_assignments", "performance_result_snapshots")
        }
        db.session.remove()
    return state


# ---------------------------------------------------------------------------
# Unpublished cards: unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["withdraw", "return"])
def test_unpublished_card_withdraw_and_return_are_unchanged(env, action) -> None:
    card = _card(env, (4, 4), (5, 5))
    _calculate(env)
    response, flashes, _dml = _act(env, _client_for(env, card, "evaluator"), card, action)
    assert response.status_code == 302
    assert flashes == [_DONE[action]]
    evaluation = _state(env)["performance_evaluations"][0]
    assert (evaluation["level_1_completed"], evaluation["workflow_status"]) == (0, "taslak_1_amir" if action == "withdraw" else "level_2_iade")


# ---------------------------------------------------------------------------
# Published cards: refused before any change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["evaluator", "admin"])
@pytest.mark.parametrize("low_score", [False, True], ids=["published_90", "published_approved_low_60"])
@pytest.mark.parametrize("action", ["withdraw", "return"])
def test_published_card_cannot_be_withdrawn_or_returned(env, action, low_score, who) -> None:
    card = _published_card(env, low_score=low_score)
    before = _state(env)
    assert [row["is_published_to_employee"] for row in before["performance_evaluations"]] == [1]
    client = _client_for(env, card, who)
    for _attempt in range(2):  # the same answer on retry
        response, flashes, dml = _act(env, client, card, action)
        assert response.status_code == 302
        assert flashes == [_BLOCKED[action]]
        assert dml == []
        assert _state(env) == before


@pytest.mark.parametrize("action", ["withdraw", "return"])
def test_publication_timestamp_alone_is_publication_evidence(env, action) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation

    card = _card(env, (4, 4), (5, 5))
    _calculate(env)
    with env.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, card.id)
        assert evaluation is not None
        evaluation.is_published_to_employee = False
        evaluation.published_to_employee_at = datetime(2026, 4, 2)
        db.session.commit()
    before = _state(env)
    _response, flashes, dml = _act(env, _client_for(env, card, "evaluator"), card, action)
    assert flashes == [_BLOCKED[action]]
    assert dml == [] and _state(env) == before


def test_unpublish_first_is_the_correction_path(env) -> None:
    card = _published_card(env)
    response = env.admin.post("/performance/v2/faz5/publish", data={"period_id": str(env.period_id), "publish_action": "unpublish"}, follow_redirects=False)
    assert response.status_code == 302
    _flashes(env.admin)
    _response, flashes, _dml = _act(env, _client_for(env, card, "evaluator"), card, "withdraw")
    assert flashes == [_DONE["withdraw"]]


# ---------------------------------------------------------------------------
# Authorization comes first and is unchanged
# ---------------------------------------------------------------------------


def test_access_contract_is_unchanged(env) -> None:
    card = _published_card(env)
    before = _state(env)
    response, flashes, dml = _act(env, _client_for(env, card, "other_manager"), card, "withdraw")
    assert (response.status_code, flashes, dml) == (302, [("danger", "Bu değerlendirme görevi size ait değil.")], [])
    anonymous, _anonymous_flashes, anonymous_dml = _act(env, env.app.test_client(), card, "withdraw")
    assert anonymous.status_code == 302 and anonymous.headers["Location"].startswith("/login")
    assert anonymous_dml == []
    assert _state(env) == before
