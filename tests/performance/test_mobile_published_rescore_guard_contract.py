"""BYS360 PERFORMANCE P0.2S: a published evaluation cannot be rescored from mobile.

Endpoint: POST /api/mobile/performance/tasks/<id>/score-form
(require_mobile_user -> performance_routes.mobile_performance_task_score_submit ->
phase3c_mobile_performance_task_score_submit_service): assignment resolve ->
_v2822_can_view_assignment (evaluator or global mobile role, else 403) -> body
validation -> save_evaluation_level (items, level flags, totals, status via
recalculate_evaluation_totals) -> assignment status -> commit.

Verified at 9d71d282108804c1168b1b5addc7bd025ecabe41: nothing on that path
looks at the publish state, so a card published to the employee could be
rescored (90 -> 80, 90 -> 50, an approved and published low score 50 -> 30),
also by a global role that is not the evaluator, or pulled back to a draft
(status "bekliyor", assignment "kismen_tamamlandi") while it stayed published.

Canonical publish state: PerformanceEvaluation.is_published_to_employee, written
together with published_to_employee_at by every publish/unpublish writer. The
mobile withdraw/return actions of the same API already refuse a published card
with ``is_published_to_employee or published_to_employee_at`` -> ValueError ->
400 {"message": "Personele yayınlanmış değerlendirme mobil ekrandan ... ."}.
Since P0.2S the score submit uses the same check and contract before any write;
authorization (403) and authentication (401) still come first. The mobile
workflow state machine is NOT changed (P0.2Q CASE C stays open).

Real Flask app, real v2 assignment sync, real mobile Bearer auth, real v2 web
route, real publish / president-approve / personnel-support routes (no
can_access_menu bypass); file-backed SQLite test database only. The Alembic-owned
personnel-support approval table is created with the DDL used by
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

_ROUTES_MODULE = "app.api.mobile.performance_routes"
_PASSWORD = "TestMobilePublishedRescore1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02s_mobile_published")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_PUBLISHED_ERROR = {"message": "Personele yayınlanmış değerlendirme mobil ekrandan değiştirilemez."}
_ACCESS_ERROR = {"message": "Bu değerlendirme görevine erişim yetkiniz bulunmamaktadır."}
_SESSION_ERROR = {"message": "Mobil oturum bulunamadı veya süresi doldu."}
_SAVE_ERROR = {"message": "Puanlama kaydedilemedi. Lütfen bilgileri kontrol edip tekrar deneyin."}

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
        "SECRET_KEY": "test-secret-key-for-p02s-mobile-published-rescore",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02s_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P2S{n:06d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02s-mobile-{n}@bys360.test",
            ad="P02S",
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
    """Admin (publish screens, also a global mobile role) and the Personel ve
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
            criteria = PerformanceCriteria(name=f"P0.2S Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        db.session.commit()
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids)


def _chain(env: SimpleNamespace, levels: int = 1) -> dict[str, Any]:
    """Chain produced by the real v2 assignment sync (1 or 2 managers)."""
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod, User
    from app.services.performance_v2.sync_service import sync_employee_assignments_v2

    l1_id, l1_sicil = _user(env.app, role="grup_baskani")
    l2_id, l2_sicil = _user(env.app, role="koordinator")
    managers = (l1_sicil, l2_sicil if levels == 2 else None, None)
    employee_id, _sicil = _user(env.app, role="personel", managers=managers)
    with env.app.app_context():
        period = PerformancePeriod(title=f"P0.2S Dönem {_next()}", period_type="quarterly", start_date=date(2020, 1, 1), end_date=date(2020, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        sync_employee_assignments_v2(period, employee=db.session.get(User, employee_id))
        db.session.commit()
        assignments = {row.manager_level: row.id for row in EvaluationAssignment.query.filter_by(period_id=period.id).all()}
        evaluation = PerformanceEvaluation.query.filter_by(period_id=period.id).one()
        return {
            "period_id": period.id,
            "evaluation_id": evaluation.id,
            "assignment_id": assignments[1],
            "assignments": assignments,
            "manager_id": l1_id,
            "manager_sicil": l1_sicil,
            "managers": {1: l1_id, 2: l2_id},
        }


def _token(env: SimpleNamespace, user_id: int) -> str:
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, user_id)
        assert user is not None
        return _issue_token(user)


def _submit(env: SimpleNamespace, assignment_id: int, scores: tuple[int, int], *, user_id: int | None, completed: bool = True) -> tuple[int, Any, list[str]]:
    """Real mobile submit; returns HTTP status, JSON body and every DML statement issued."""
    from app.extensions import db

    headers = {"Authorization": f"Bearer {_token(env, user_id)}"} if user_id is not None else {}
    body = {
        "completed": completed,
        "general_comment": _COMMENT,
        "items": [{"criteria_id": c, "score": s, "comment": "Kriter notu"} for c, s in zip(env.criteria_ids, scores, strict=True)],
    }
    dml: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            dml.append(statement)

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = env.app.test_client().post(f"/api/mobile/performance/tasks/{assignment_id}/score-form", json=body, headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return response.status_code, response.get_json(), dml


def _v2_complete(env: SimpleNamespace, chain: dict[str, Any], scores: tuple[int, int]) -> None:
    client = env.app.test_client()
    _login(client, chain["manager_sicil"])
    data = {"action": "submit", "general_comment": _COMMENT}
    for criteria_id, score in zip(env.criteria_ids, scores, strict=True):
        data[f"score_{criteria_id}"] = str(score)
        data[f"comment_{criteria_id}"] = "Kriter yorumu ve gerekçesi"
    response = client.post(f"/performance/v2/faz3/assignment/{chain['assignment_id']}", data=data, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Değerlendirme tamamlandı.") in _flashes(client)


def _president_approve(env: SimpleNamespace, evaluation_id: int) -> None:
    from app.extensions import db

    with env.app.app_context():
        process_id = db.session.execute(text("SELECT id FROM performance_low_score_processes WHERE evaluation_id = :e"), {"e": evaluation_id}).scalar()
        db.session.remove()
    assert process_id is not None
    response = env.admin.post(f"/performance/low-score-process/{process_id}/president-approve", data={"note": "Onaylandı"}, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Başkan onayı kaydedildi.") in _flashes(env.admin)


def _personnel_support_approve(env: SimpleNamespace, evaluation_id: int) -> None:
    """Pending row via the preflight's own service call, decision on the real chair route."""
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
    response = env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Sonuç personele yayımlandı.") in _flashes(env.admin)


def _published_card(env: SimpleNamespace, *, channel: str = "mobile", scores: tuple[int, int] = (5, 4), president_approved: bool = False) -> dict[str, Any]:
    chain = _chain(env)
    if channel == "v2":
        _v2_complete(env, chain, scores)
    else:
        status, _body, _dml = _submit(env, chain["assignment_id"], scores, user_id=chain["manager_id"])
        assert status == 200
    if president_approved:
        _president_approve(env, chain["evaluation_id"])
    _personnel_support_approve(env, chain["evaluation_id"])
    _publish(env, chain["evaluation_id"])
    assert _snapshot(env, chain)["evaluation"]["is_published_to_employee"] in (1, True)
    return chain


def _snapshot(env: SimpleNamespace, chain: dict[str, Any]) -> dict[str, Any]:
    """Every row the submit could touch, as a fresh transaction sees it."""
    from app.extensions import db

    params = {"e": chain["evaluation_id"], "p": chain["period_id"]}

    def _rows(sql: str) -> list[dict[str, Any]]:
        return [dict(row) for row in db.session.execute(text(sql), params).mappings().all()]

    with env.app.app_context():
        db.session.remove()
        state = {
            "evaluation": _rows("SELECT * FROM performance_evaluations WHERE id = :e")[0],
            "assignments": _rows("SELECT * FROM evaluation_assignments WHERE period_id = :p ORDER BY id"),
            "items": _rows("SELECT * FROM performance_evaluation_items WHERE evaluation_id = :e ORDER BY id"),
            "processes": _rows("SELECT * FROM performance_low_score_processes WHERE evaluation_id = :e ORDER BY id"),
            "events": _rows(
                "SELECT ev.* FROM performance_low_score_process_events ev "
                "JOIN performance_low_score_processes p ON p.id = ev.process_id WHERE p.evaluation_id = :e ORDER BY ev.id"
            ),
            "publish_logs": _rows("SELECT * FROM performance_publish_logs WHERE evaluation_id = :e ORDER BY id"),
        }
        db.session.remove()
    return state


def _forbid_scoring_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard runs before the first write: save_evaluation_level (items,
    flags, totals, status) and the assignment update must not be reached."""
    routes = importlib.import_module(_ROUTES_MODULE)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("published card reached the scoring write path")

    monkeypatch.setattr(routes, "save_evaluation_level", _must_not_be_called)


def _assert_rejected_without_writes(env, chain, *, scores, user_id, completed=True, expected=(400, _PUBLISHED_ERROR)) -> None:
    before = _snapshot(env, chain)
    status, body, dml = _submit(env, chain["assignment_id"], scores, user_id=user_id, completed=completed)
    assert (status, body) == expected
    assert dml == []
    assert _snapshot(env, chain) == before


# ---------------------------------------------------------------------------
# Unpublished cards: unchanged behavior
# ---------------------------------------------------------------------------


def test_unpublished_owner_submit_succeeds(env) -> None:
    chain = _chain(env)
    status, body, dml = _submit(env, chain["assignment_id"], (4, 4), user_id=chain["manager_id"])
    assert status == 200 and body["message"] == "Değerlendirme başarıyla tamamlandı."
    assert body["final_score_100"] == 80.0 and dml
    evaluation = _snapshot(env, chain)["evaluation"]
    # P0.2Q (unchanged): completed for the status, draft for the workflow.
    assert (evaluation["status"], evaluation["workflow_status"], bool(evaluation["level_1_completed"])) == ("tamamlandi", "taslak_1_amir", True)

    # Retry of the same submission keeps the same result.
    first = _snapshot(env, chain)
    status, _body, _dml = _submit(env, chain["assignment_id"], (4, 4), user_id=chain["manager_id"])
    assert status == 200
    again = _snapshot(env, chain)
    assert (again["evaluation"]["final_total_100"], again["evaluation"]["status"]) == (first["evaluation"]["final_total_100"], "tamamlandi")
    assert [(item["criteria_id"], item["score"]) for item in again["items"]] == [(item["criteria_id"], item["score"]) for item in first["items"]]


def test_unpublished_low_score_and_partial_level_submits_are_unchanged(env) -> None:
    low = _chain(env)
    status, body, _dml = _submit(env, low["assignment_id"], (2, 3), user_id=low["manager_id"])
    assert status == 200 and body["final_score_100"] == 50.0
    low_state = _snapshot(env, low)
    assert (low_state["evaluation"]["workflow_status"], low_state["processes"]) == ("taslak_1_amir", [])  # P0.2Q, unchanged

    two = _chain(env, levels=2)
    status, _body, _dml = _submit(env, two["assignments"][2], (4, 4), user_id=two["managers"][2])
    assert status == 200
    assert _snapshot(env, two)["evaluation"]["status"] == "kismen_tamamlandi"


# ---------------------------------------------------------------------------
# Published cards: rejected before any write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("scores", "completed"), [((4, 4), True), ((2, 3), True), ((2, 3), False)], ids=["high_to_high", "high_to_low", "draft_save"])
def test_owner_cannot_change_a_published_card(env, monkeypatch, scores, completed) -> None:
    chain = _published_card(env)
    _forbid_scoring_writes(monkeypatch)
    _assert_rejected_without_writes(env, chain, scores=scores, user_id=chain["manager_id"], completed=completed)


def test_owner_cannot_change_a_published_approved_low_score_card(env, monkeypatch) -> None:
    chain = _published_card(env, channel="v2", scores=(2, 3), president_approved=True)
    state = _snapshot(env, chain)
    assert (len(state["processes"]), len(state["events"]), state["evaluation"]["final_total_100"]) == (1, 5, 50.0)
    _forbid_scoring_writes(monkeypatch)
    _assert_rejected_without_writes(env, chain, scores=(1, 2), user_id=chain["manager_id"])


def test_global_mobile_role_cannot_change_a_published_card(env, monkeypatch) -> None:
    """Admin is a global mobile role: it passes the task authorization, not the publish guard."""
    chain = _published_card(env)
    _forbid_scoring_writes(monkeypatch)
    _assert_rejected_without_writes(env, chain, scores=(2, 3), user_id=env.admin_id)


def test_repeated_submits_on_a_published_card_are_all_rejected(env, monkeypatch) -> None:
    chain = _published_card(env)
    _forbid_scoring_writes(monkeypatch)
    for _ in range(3):
        _assert_rejected_without_writes(env, chain, scores=(2, 3), user_id=chain["manager_id"])


# ---------------------------------------------------------------------------
# Authentication / authorization keep their order and contract
# ---------------------------------------------------------------------------


def test_unrelated_user_gets_the_existing_access_error_first(env) -> None:
    published = _published_card(env)
    unpublished = _chain(env)
    other_id, _sicil = _user(env.app, role="grup_baskani")
    for chain in (published, unpublished):  # same answer: the publish state is not disclosed
        _assert_rejected_without_writes(env, chain, scores=(2, 3), user_id=other_id, expected=(403, _ACCESS_ERROR))


def test_missing_token_gets_the_existing_session_error(env) -> None:
    chain = _published_card(env)
    _assert_rejected_without_writes(env, chain, scores=(2, 3), user_id=None, expected=(401, _SESSION_ERROR))


# ---------------------------------------------------------------------------
# Lookup failure is fail-closed; read and action endpoints are unchanged
# ---------------------------------------------------------------------------


def test_publish_state_lookup_error_uses_the_existing_save_error_without_writes(env, monkeypatch, caplog) -> None:
    """A real driver error in the publish-state lookup: the service's existing
    except -> rollback -> 500 JSON; nothing of the evaluation is written. The
    only statement is the app-wide 5xx security event
    (app/bootstrap/operational_guards.py::operational_access_log -> audit_logs)."""
    import logging

    from app.extensions import db

    chain = _published_card(env)
    routes = importlib.import_module(_ROUTES_MODULE)

    def _broken_first():
        db.session.execute(text("SELECT no_such_column FROM performance_evaluations"))

    monkeypatch.setattr(routes, "PerformanceEvaluation", SimpleNamespace(query=SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=_broken_first))))
    _forbid_scoring_writes(monkeypatch)
    before = _snapshot(env, chain)
    with caplog.at_level(logging.ERROR):
        status, body, dml = _submit(env, chain["assignment_id"], (2, 3), user_id=chain["manager_id"])
    assert (status, body) == (500, _SAVE_ERROR)
    assert [" ".join(statement.split()[:3]) for statement in dml] == ["INSERT INTO audit_logs"]
    assert _snapshot(env, chain) == before
    logged = [record.exc_info[0].__name__ for record in caplog.records if record.name == _ROUTES_MODULE and record.exc_info and record.exc_info[0]]
    assert logged == ["OperationalError"]


def test_published_card_stays_readable_and_withdraw_guard_is_unchanged(env) -> None:
    chain = _published_card(env)
    headers = {"Authorization": f"Bearer {_token(env, chain['manager_id'])}"}
    client = env.app.test_client()

    form = client.get(f"/api/mobile/performance/tasks/{chain['assignment_id']}/score-form", headers=headers)
    assert form.status_code == 200
    assert form.get_json()["form"]["is_completed"] is True
    assert client.get(f"/api/mobile/performance/tasks/{chain['assignment_id']}", headers=headers).status_code == 200

    before = _snapshot(env, chain)
    withdraw = client.post(f"/api/mobile/performance/tasks/{chain['assignment_id']}/score-action", json={"action": "withdraw"}, headers=headers)
    assert (withdraw.status_code, withdraw.get_json()["message"]) == (400, "Personele yayınlanmış değerlendirme mobil ekrandan geri çekilemez.")
    assert _snapshot(env, chain) == before
