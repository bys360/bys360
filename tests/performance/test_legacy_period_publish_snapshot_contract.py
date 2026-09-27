"""BYS360 PERFORMANCE P0.2AB: the legacy period publish snapshots only the cards it published.

Route: POST /performance/publish/period/<id> (main.performance_publish_period,
app/performance/engagement_publish_routes.py; login + admin + menu
"performance_publish") -> publish_service.publish_period_results (the publish
decision: sets is_published_to_employee / published_to_employee_at on every
publishable card, skips the rest, returns published_evaluation_ids) ->
bulk_publish logs -> commit -> performance_snapshot_service.create_snapshots_for_period
-> notifications -> commit.

Verified at beed223733019bb9b3614651c30733e73f09564d: the snapshot step took every
completed card of the period, so a card the publish had skipped (a 70 altı card
waiting for or returned by Başkan/Üst Onay, a card without the Personel ve
Destek Hizmetleri Grup Başkanı approval, the Başkan's own exempt card) stayed
unpublished yet got a current system_published snapshot, and the mobile
scorecards showed its score to the employee (50/100).

Since P0.2AB the route hands the publish decision's published_evaluation_ids to
the snapshot step, which snapshots only those cards: NOT PUBLISHED => NO NEW
SYSTEM_PUBLISHED SNAPSHOT. The publish decision, the period flag, the publish
logs, the retry refusal and the existing version rule are unchanged. Snapshots
created earlier are neither deleted nor rewritten (cleanup is a separate
decision). Publication visibility of existing snapshots is not changed (P0.2V
CASE C).

Real Flask app, real admin login, real personnel-support / Başkan/Üst Onay /
single and period publish routes; file-backed SQLite test database only. The
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

_ROUTES_MODULE = "app.performance.engagement_publish_routes"
_SERVICE_MODULE = "app.services.performance_snapshot_service"
_PASSWORD = "TestLegacyPublishSnapshot1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02ab_legacy_publish")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_NOTHING_PUBLISHED = ("warning", "Yayınlanabilecek tamamlanmış kayıt bulunamadı.")
_PRESIDENT_PENDING = "Başkan onayı bekliyor. Başkan/Üst Onay şartı tamamlanmadan yayın yapılamaz. Başkan/Üst Onay Yayın Kilidi"

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
        "SECRET_KEY": "test-secret-key-for-p02ab-legacy-publish",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02ab_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P2AB{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02ab-legacy-{n}@bys360.test",
            ad="P02AB",
            soyad=f"Kullanici{n}",
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
    """Admin (publish screens, Başkan/Üst Onay) and the Personel ve Destek
    Hizmetleri Grup Başkanı, logged in for real; one criteria set; one open,
    ended quarter."""
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
            criteria = PerformanceCriteria(name=f"P0.2AB Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P0.2AB Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        period_id = int(period.id)
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids, period_id=period_id)


# ---------------------------------------------------------------------------
# Cards through the real routes
# ---------------------------------------------------------------------------


def _card(env: SimpleNamespace, level_1_scores: tuple[int, int], level_2_scores: tuple[int, int]) -> int:
    """A completed two-manager card of the period; totals come from _calculate."""
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
    """Totals through the real weight save (50/50) of the open period."""
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


def _low_score_process(env: SimpleNamespace, evaluation_id: int) -> int:
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
    return process_id


def _president(env: SimpleNamespace, evaluation_id: int, decision: str) -> None:
    process_id = _low_score_process(env, evaluation_id)
    response = env.admin.post(f"/performance/low-score-process/{process_id}/president-{decision}", data={"note": "Başkan kararı"}, follow_redirects=False)
    assert response.status_code == 302
    expected = ("success", "Başkan onayı kaydedildi.") if decision == "approve" else ("warning", "Başkan/Üst Onay iadesi kaydedildi. Yayın kilidi devam ediyor.")
    assert expected in _flashes(env.admin)


def _set(env: SimpleNamespace, model_name: str, row_id: int, **columns: Any) -> None:
    from app import models
    from app.extensions import db

    with env.app.app_context():
        row = db.session.get(getattr(models, model_name), row_id)
        for key, value in columns.items():
            setattr(row, key, value)
        db.session.commit()


def _employee(env: SimpleNamespace, evaluation_id: int) -> int:
    from app.extensions import db

    with env.app.app_context():
        employee_id = db.session.execute(text("SELECT employee_id FROM performance_evaluations WHERE id = :e"), {"e": evaluation_id}).scalar_one()
        db.session.remove()
    return int(employee_id)


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


def _publish_period(env: SimpleNamespace, client=None) -> tuple[Any, list[tuple[str, str]], list[str]]:
    """Real legacy period publish; returns the response, its flashes and every DML statement issued."""
    from app.extensions import db

    client = client or env.admin
    dml: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        words = statement.split()
        if words and words[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            dml.append(" ".join(words[:3]) if words[0].upper() != "UPDATE" else " ".join(words[:2]))

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = client.post(f"/performance/publish/period/{env.period_id}", data={}, follow_redirects=False)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return response, _flashes(client), dml


def _state(env: SimpleNamespace) -> dict[str, list[dict[str, Any]]]:
    """Every row the publish could touch, as a fresh session sees it."""
    from app.extensions import db

    def _rows(table: str) -> list[dict[str, Any]]:
        return [dict(row) for row in db.session.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings().all()]  # noqa: S608

    tables = ("performance_result_snapshots", "performance_periods", "performance_evaluations", "performance_publish_logs", "mail_logs")
    with env.app.app_context():
        db.session.remove()
        state = {table: _rows(table) for table in tables}
        db.session.remove()
    return state


def _published_ids(state: dict[str, list[dict[str, Any]]]) -> set[int]:
    return {row["id"] for row in state["performance_evaluations"] if row["is_published_to_employee"] or row["published_to_employee_at"]}


def _current_snapshot_ids(state: dict[str, list[dict[str, Any]]]) -> set[int]:
    return {row["evaluation_id"] for row in state["performance_result_snapshots"] if row["is_current"]}


def _mobile_cards(env: SimpleNamespace, evaluation_id: int) -> tuple[str, str]:
    """(Karne, Ortalama) of the card owner's mobile scorecards, real Bearer token."""
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        employee = db.session.get(User, _employee(env, evaluation_id))
        assert employee is not None
        token = _issue_token(employee)
    body = env.app.test_client().get("/api/mobile/performance/scorecards", headers={"Authorization": f"Bearer {token}"}).get_json()
    metrics = {metric["title"]: metric["value"] for metric in body["metrics"]}
    return metrics["Karne"], metrics["Ortalama"]


# ---------------------------------------------------------------------------
# A skipped card never gets a system_published snapshot
# ---------------------------------------------------------------------------


def _pending_low_score(env: SimpleNamespace) -> int:
    evaluation_id = _card(env, (2, 2), (3, 3))  # 50
    _calculate(env)
    return evaluation_id


def _returned_low_score(env: SimpleNamespace) -> int:
    evaluation_id = _card(env, (2, 2), (3, 3))  # 50
    _calculate(env)
    _president(env, evaluation_id, "reject")
    return evaluation_id


def _without_personnel_support_approval(env: SimpleNamespace) -> int:
    evaluation_id = _card(env, (4, 4), (4, 4))  # 80
    _calculate(env)
    return evaluation_id


def _not_completed(env: SimpleNamespace) -> int:
    evaluation_id = _card(env, (4, 4), (5, 5))
    _calculate(env)
    _personnel_support_approve(env, evaluation_id)
    _set(env, "PerformanceEvaluation", evaluation_id, status="kismen_tamamlandi")
    return evaluation_id


def _president_exempt(env: SimpleNamespace) -> int:
    """The Başkan's own card: publish_period_results skips it without a reason."""
    evaluation_id = _card(env, (4, 4), (5, 5))
    _calculate(env)
    _set(env, "User", _employee(env, evaluation_id), role="baskan")
    return evaluation_id


@pytest.mark.parametrize(
    "build",
    [_pending_low_score, _returned_low_score, _without_personnel_support_approval, _not_completed, _president_exempt],
    ids=["low_score_president_pending", "low_score_president_returned", "no_personnel_support_approval", "not_completed", "president_exempt"],
)
def test_a_card_the_publish_skipped_gets_no_snapshot(env, build) -> None:
    evaluation_id = build(env)
    before = _state(env)

    response, flashes, dml = _publish_period(env)
    assert response.status_code == 302
    assert flashes[0] == _NOTHING_PUBLISHED
    after = _state(env)
    assert _published_ids(after) == set()
    assert after["performance_result_snapshots"] == []
    assert not any(statement.endswith("performance_result_snapshots") for statement in dml)
    assert after["performance_evaluations"] == before["performance_evaluations"]
    assert [row["results_published"] for row in after["performance_periods"]] == [0]
    assert after["performance_publish_logs"] == before["performance_publish_logs"] == []
    if build is not _president_exempt:  # the Başkan reads the institution-wide scope on mobile
        assert _mobile_cards(env, evaluation_id) == ("0", "-")


def test_leak_case_president_pending_50_stays_hidden_from_the_employee(env) -> None:
    """The P0.2Z/P0.2AA finding: unpublished 50 with Başkan/Üst Onay pending."""
    evaluation_id = _pending_low_score(env)
    _response, flashes, _dml = _publish_period(env)
    assert flashes == [_NOTHING_PUBLISHED, ("info", f"Blok nedenleri: {_PRESIDENT_PENDING}: 1")]
    after = _state(env)
    (card,) = after["performance_evaluations"]
    assert (card["final_total_100"], card["is_published_to_employee"], card["published_to_employee_at"]) == (50.0, 0, None)
    assert after["performance_result_snapshots"] == []
    assert _mobile_cards(env, evaluation_id) == ("0", "-")


# ---------------------------------------------------------------------------
# Published cards keep their snapshot
# ---------------------------------------------------------------------------


def test_mixed_period_snapshots_exactly_the_published_cards(env) -> None:
    high = _card(env, (4, 4), (5, 5))  # 90
    approved_low = _card(env, (2, 2), (4, 4))  # 60
    pending_low = _card(env, (2, 2), (3, 3))  # 50
    _calculate(env)
    _personnel_support_approve(env, high)
    _president(env, approved_low, "approve")
    _personnel_support_approve(env, approved_low)

    response, flashes, _dml = _publish_period(env)
    assert response.status_code == 302
    assert flashes[:2] == [("success", "2 sonuç yayımlandı. 1 bloklu kayıt atlandı."), ("warning", f"Atlama nedenleri: {_PRESIDENT_PENDING}: 1")]
    after = _state(env)
    assert _published_ids(after) == {high, approved_low}
    assert _current_snapshot_ids(after) == _published_ids(after)
    assert [
        (row["evaluation_id"], row["source_type"], row["version_no"], bool(row["is_current"]), row["final_total_100"], row["ranking_in_scope"])
        for row in after["performance_result_snapshots"]
    ] == [(high, "system_published", 1, True, 90.0, 1), (approved_low, "system_published", 1, True, 60.0, 2)]
    assert [row["results_published"] for row in after["performance_periods"]] == [1]
    assert [row["snapshot_status"] for row in after["performance_periods"]] == ["completed"]
    assert [(row["action_type"], row["evaluation_id"]) for row in after["performance_publish_logs"]] == [("bulk_publish", high), ("bulk_publish", approved_low)]
    assert _mobile_cards(env, high) == ("1", "90/100")
    assert _mobile_cards(env, approved_low) == ("1", "60/100")
    assert _mobile_cards(env, pending_low) == ("0", "-")


def test_retry_is_refused_and_changes_nothing(env) -> None:
    high = _card(env, (4, 4), (5, 5))
    _pending_low_score(env)
    _personnel_support_approve(env, high)
    _publish_period(env)
    first = _state(env)

    response, flashes, dml = _publish_period(env)
    assert response.status_code == 302
    assert flashes == [("warning", "Bu dönem sonuçları zaten yayımlanmış görünüyor.")]
    assert dml == []
    assert _state(env) == first


def test_existing_snapshots_follow_the_version_rule_and_are_never_cleaned_up(env) -> None:
    """A: published, unpublished (its v1 stays current, P0.2V), then published
    again by the period publish -> v2 current, v1 kept. B: a skipped card with a
    current snapshot left by the old behavior -> no new version, not deleted,
    not rewritten (only the period-wide ranking is refreshed)."""
    from app.extensions import db

    republished = _card(env, (4, 4), (5, 5))
    skipped = _card(env, (2, 2), (3, 3))
    _calculate(env)
    _personnel_support_approve(env, republished)
    assert env.admin.post(f"/performance/publish/evaluation/{republished}", data={}, follow_redirects=False).status_code == 302
    assert env.admin.post(f"/performance/unpublish/evaluation/{republished}", data={}, follow_redirects=False).status_code == 302
    _flashes(env.admin)
    service = importlib.import_module(_SERVICE_MODULE)
    with env.app.app_context():
        service.create_snapshot_for_evaluation(skipped, actor_user_id=env.admin_id)
        db.session.commit()
    before_rows = {row["id"]: row for row in _state(env)["performance_result_snapshots"]}

    _publish_period(env)
    after = _state(env)
    assert _published_ids(after) == {republished}
    assert [
        (row["evaluation_id"], row["version_no"], bool(row["is_current"])) for row in after["performance_result_snapshots"]
    ] == [(republished, 1, False), (skipped, 1, True), (republished, 2, True)]
    skipped_row = next(row for row in after["performance_result_snapshots"] if row["evaluation_id"] == skipped)
    ignore = {"ranking_in_scope": None, "ranking_in_unit": None, "updated_at": None}
    assert skipped_row | ignore == before_rows[skipped_row["id"]] | ignore


# ---------------------------------------------------------------------------
# Failure and access contracts are unchanged
# ---------------------------------------------------------------------------


def test_failure_in_the_publish_step_rolls_everything_back(env, monkeypatch) -> None:
    first = _card(env, (4, 4), (5, 5))
    second = _card(env, (3, 3), (4, 4))
    _pending_low_score(env)
    for evaluation_id in (first, second):
        _personnel_support_approve(env, evaluation_id)
    routes = importlib.import_module(_ROUTES_MODULE)
    real = routes.create_publish_log
    calls: list[int] = []

    def _second_log_fails(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("simulated publish log failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(routes, "create_publish_log", _second_log_fails)
    before = _state(env)
    response, flashes, _dml = _publish_period(env)
    assert response.status_code == 302
    assert flashes == [("danger", "Toplu yayın sırasında hata oluştu.")]
    assert _state(env) == before


def test_access_contract_is_unchanged(env) -> None:
    high = _card(env, (4, 4), (5, 5))
    _calculate(env)
    _personnel_support_approve(env, high)
    before = _state(env)
    anonymous, _anonymous_flashes, anonymous_dml = _publish_period(env, client=env.app.test_client())
    assert anonymous.status_code == 302 and anonymous.headers["Location"].startswith("/login")
    assert anonymous_dml == []
    _uid, sicil = _user(env.app, role="personel")
    personel = env.app.test_client()
    _login(personel, sicil)
    assert _publish_period(env, client=personel)[0].status_code == 403
    assert _state(env)["performance_evaluations"] == before["performance_evaluations"]
    assert _state(env)["performance_result_snapshots"] == before["performance_result_snapshots"] == []
