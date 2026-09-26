"""BYS360 PERFORMANCE P0.2R: fail-closed low-score publish gate.

Publish chain: POST /performance/publish/evaluation/<id>
(main.performance_publish_evaluation) -> publish_service.publish_evaluation ->
visibility_guard.is_evaluation_publishable ->
publish_preflight_rules.validate_evaluation_for_publish.

Verified at 5c8b365070bab07fffdf4830da80d98b3ffbac90: for a completed card
(publish contract: status in FINAL_STATUSES) with 0 < final < 70 the preflight
asked get_low_score_publish_block_reason(ensure=True) and derived
``president_approved = not low_score_block_reason``. That service returns None
when its own completion predicate does not count the evaluation as completed
(a mobile completion keeps workflow_status "taslak_1_amir"), so no process
existed, nothing was approved, and the card was still published once the
personnel-support pre-approval was given.

Since P0.2R the lock opens only on explicit evidence: an existing process that
the canonical model policy finalizes for publish
(PerformanceLowScoreProcess.is_finalized_for_publish: Başkan/Üst Onay, no
return, warning / administrative process recorded). A missing process is not an
approval. Database errors reach the route's rollback. A 0/None score and 70+
cards keep their previous contract. The mobile workflow state machine is NOT
changed (P0.2Q CASE C stays open).

Real Flask app, real login and permissions (no can_access_menu bypass), real v2
assignment sync, real mobile Bearer route, real v2 web route, real
president-approve route, real personnel-support approve route, real publish
route; file-backed SQLite test database only. The personnel-support approval
table is Alembic-owned (db.create_all() does not create it); the fixture creates
it with the DDL used by
tests/behavior/test_personnel_support_publish_approval_workflow_contract.py, and
the pending row is created by the same service call the preflight makes.
"""
from __future__ import annotations

import importlib
import logging
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

_PREFLIGHT_MODULE = "app.services.performance.publish_preflight_rules"
_ROUTE_MODULE = "app.performance.engagement_publish_routes"
_PASSWORD = "PublishFailClosedContract1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02r_publish_fail_closed")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_LOW = (2, 3)  # level total 50
_HIGH = (4, 4)  # level total 80

_SUCCESS_FLASH = ("success", "Sonuç personele yayımlandı.")
_ERROR_FLASH = ("danger", "Tekil yayın sırasında hata oluştu.")
# Existing low-score reasons (low_score_process_service.get_low_score_publish_block_reason).
_NO_PROCESS_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay tamamlanmadan 70 altı karne yayınlanamaz. Başkan/Üst Onay Yayın Kilidi"
_PENDING_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay şartı tamamlanmadan yayın yapılamaz. Başkan/Üst Onay Yayın Kilidi"
_REJECTED_REASON = "Başkan/Üst Onay tarafından iade edildi. Yayın kilidi devam ediyor."
_WARNING_MISSING_REASON = "İlk düşük performans uyarısı oluşmadan yayın yapılamaz."
_PERSONNEL_PENDING_REASON = "Personel ve Destek Hizmetleri Grup Başkanı ön onayı tamamlanmadan karne personele açılamaz."

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
        "SECRET_KEY": "test-secret-key-for-p02r-publish-fail-closed",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02r_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P2R{n:06d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02r-publish-{n}@bys360.test",
            ad="P02R",
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
    """Admin (publish + Başkan/Üst Onay screen) and the Personel ve Destek
    Hizmetleri Grup Başkanı, both logged in for real; one criteria set."""
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
            criteria = PerformanceCriteria(name=f"P0.2R Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        db.session.commit()
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids)


def _chain(env: SimpleNamespace) -> dict[str, Any]:
    """One-manager chain produced by the real v2 assignment sync."""
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod, User
    from app.services.performance_v2.sync_service import sync_employee_assignments_v2

    manager_id, manager_sicil = _user(env.app, role="grup_baskani")
    employee_id, _sicil = _user(env.app, role="personel", managers=(manager_sicil, None, None))
    with env.app.app_context():
        period = PerformancePeriod(title=f"P0.2R Dönem {_next()}", period_type="quarterly", start_date=date(2020, 1, 1), end_date=date(2020, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        sync_employee_assignments_v2(period, employee=db.session.get(User, employee_id))
        db.session.commit()
        assignment = EvaluationAssignment.query.filter_by(period_id=period.id, manager_level=1).one()
        evaluation = PerformanceEvaluation.query.filter_by(period_id=period.id).one()
        return {"period_id": period.id, "evaluation_id": evaluation.id, "assignment_id": assignment.id, "manager_id": manager_id, "manager_sicil": manager_sicil}


def _v2_complete(env: SimpleNamespace, chain: dict[str, Any], scores: tuple[int, int]) -> None:
    """The manager submits on the real v2 web route."""
    client = env.app.test_client()
    _login(client, chain["manager_sicil"])
    data = {"action": "submit", "general_comment": _COMMENT}
    for criteria_id, score in zip(env.criteria_ids, scores, strict=True):
        data[f"score_{criteria_id}"] = str(score)
        data[f"comment_{criteria_id}"] = "Kriter yorumu ve gerekçesi"
    response = client.post(f"/performance/v2/faz3/assignment/{chain['assignment_id']}", data=data, follow_redirects=False)
    assert response.status_code == 302
    assert ("success", "Değerlendirme tamamlandı.") in _flashes(client)


def _mobile_complete(env: SimpleNamespace, chain: dict[str, Any], scores: tuple[int, int]) -> None:
    """The manager completes on the real mobile route (Bearer token)."""
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        manager = db.session.get(User, chain["manager_id"])
        assert manager is not None
        token = _issue_token(manager)
    body = {
        "completed": True,
        "general_comment": _COMMENT,
        "items": [{"criteria_id": c, "score": s, "comment": "Kriter notu"} for c, s in zip(env.criteria_ids, scores, strict=True)],
    }
    response = env.app.test_client().post(f"/api/mobile/performance/tasks/{chain['assignment_id']}/score-form", json=body, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def _process_id(env: SimpleNamespace, evaluation_id: int) -> int | None:
    from app.extensions import db

    with env.app.app_context():
        value = db.session.execute(text("SELECT id FROM performance_low_score_processes WHERE evaluation_id = :e"), {"e": evaluation_id}).scalar()
        db.session.remove()
    return value


def _president_approve(env: SimpleNamespace, evaluation_id: int) -> None:
    """Admin records Başkan/Üst Onay on the real low-score screen route."""
    process_id = _process_id(env, evaluation_id)
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
    assert ("success", "Personel ve Destek Hizmetleri Grup Başkanı ön onayı verildi. Karne nihai yayına hazır.") in _flashes(env.chair)


def _seed_process(env: SimpleNamespace, evaluation_id: int, **fields: Any) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceLowScoreProcess

    with env.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert evaluation is not None
        db.session.add(
            PerformanceLowScoreProcess(
                period_id=evaluation.period_id,
                evaluation_id=evaluation.id,
                employee_id=evaluation.employee_id,
                calendar_year=2020,
                sequence_no=1,
                final_total_100=evaluation.final_total_100,
                **fields,
            )
        )
        db.session.commit()


def _publish(env: SimpleNamespace, evaluation_id: int, client=None):
    client = client or env.admin
    response = client.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    return response, _flashes(client)


def _state(env: SimpleNamespace, evaluation_id: int) -> dict[str, Any]:
    """Committed state as a fresh transaction sees it."""
    from app.extensions import db

    params = {"e": evaluation_id}
    with env.app.app_context():
        db.session.remove()
        status, workflow, final, published = db.session.execute(
            text("SELECT status, workflow_status, final_total_100, is_published_to_employee FROM performance_evaluations WHERE id = :e"), params
        ).one()
        state = {
            "status": status,
            "workflow_status": workflow,
            "final": final,
            "published": bool(published),
            "processes": db.session.execute(text("SELECT COUNT(*) FROM performance_low_score_processes WHERE evaluation_id = :e"), params).scalar(),
            "president_approved": bool(
                db.session.execute(
                    text("SELECT COUNT(*) FROM performance_low_score_processes WHERE evaluation_id = :e AND (president_approved_at IS NOT NULL OR president_approved_by_id IS NOT NULL)"),
                    params,
                ).scalar()
            ),
            "personnel_support": [row[0] for row in db.session.execute(text("SELECT status FROM performance_personnel_support_publish_approvals WHERE evaluation_id = :e"), params).all()],
            "publish_logs": db.session.execute(text("SELECT COUNT(*) FROM performance_publish_logs WHERE evaluation_id = :e"), params).scalar(),
        }
        db.session.remove()
    return state


def _assert_blocked(env: SimpleNamespace, evaluation_id: int, reason: str) -> dict[str, Any]:
    before = _state(env, evaluation_id)
    response, flashes = _publish(env, evaluation_id)
    assert response.status_code == 302
    assert flashes == [("warning", reason)]
    after = _state(env, evaluation_id)
    assert after == before and after["published"] is False and after["publish_logs"] == 0
    return after


def _assert_published(env: SimpleNamespace, evaluation_id: int) -> dict[str, Any]:
    response, flashes = _publish(env, evaluation_id)
    assert response.status_code == 302
    assert _SUCCESS_FLASH in flashes
    assert not [flash for flash in flashes if flash[0] == "danger"]
    after = _state(env, evaluation_id)
    assert after["published"] is True and after["publish_logs"] == 1
    return after


def _mobile_low_card_with_personnel_support_approval(env: SimpleNamespace) -> dict[str, Any]:
    chain = _chain(env)
    _mobile_complete(env, chain, _LOW)
    _personnel_support_approve(env, chain["evaluation_id"])
    state = _state(env, chain["evaluation_id"])
    # The P0.2Q state (unchanged): completed for the publish layer, draft for the
    # low-score service, no process, pre-approval given.
    assert (state["status"], state["workflow_status"], state["final"]) == ("tamamlandi", "taslak_1_amir", 50.0)
    assert (state["processes"], state["personnel_support"]) == (0, ["approved"])
    return chain


# ---------------------------------------------------------------------------
# P1-P4: v2 web channel (canonical, unchanged)
# ---------------------------------------------------------------------------


def test_p1_v2_high_score_publishes_without_a_low_score_process(env) -> None:
    chain = _chain(env)
    _v2_complete(env, chain, _HIGH)
    _personnel_support_approve(env, chain["evaluation_id"])
    after = _assert_published(env, chain["evaluation_id"])
    assert (after["final"], after["processes"]) == (80.0, 0)


def test_p2_v2_low_score_without_president_approval_is_blocked(env) -> None:
    chain = _chain(env)
    _v2_complete(env, chain, _LOW)
    after = _assert_blocked(env, chain["evaluation_id"], _PENDING_REASON)
    assert (after["processes"], after["president_approved"]) == (1, False)


def test_p3_v2_low_score_with_president_approval_but_no_personnel_support_approval_is_blocked(env) -> None:
    chain = _chain(env)
    _v2_complete(env, chain, _LOW)
    _president_approve(env, chain["evaluation_id"])
    after = _assert_blocked(env, chain["evaluation_id"], _PERSONNEL_PENDING_REASON)
    assert after["president_approved"] is True


def test_p4_v2_low_score_with_both_approvals_publishes(env) -> None:
    chain = _chain(env)
    _v2_complete(env, chain, _LOW)
    _president_approve(env, chain["evaluation_id"])
    _personnel_support_approve(env, chain["evaluation_id"])
    after = _assert_published(env, chain["evaluation_id"])
    assert (after["processes"], after["president_approved"], after["personnel_support"]) == (1, True, ["approved"])


# ---------------------------------------------------------------------------
# P5-P7: mobile channel / no process
# ---------------------------------------------------------------------------


def test_p5_mobile_low_score_without_president_approval_is_blocked_after_personnel_support_approval(env) -> None:
    """The P0.2Q defect: published at 5c8b3650. Blocked now; no process is materialized by publish."""
    chain = _mobile_low_card_with_personnel_support_approval(env)
    after = _assert_blocked(env, chain["evaluation_id"], _NO_PROCESS_REASON)
    assert (after["processes"], after["workflow_status"]) == (0, "taslak_1_amir")


def test_p5_other_publish_callers_see_the_same_lock(env) -> None:
    """visibility_guard.is_evaluation_publishable (publish dashboard, bulk publish,
    scorecard visibility) delegates to the same preflight."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import visibility_guard

    chain = _mobile_low_card_with_personnel_support_approval(env)
    with env.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, chain["evaluation_id"])
        assert evaluation is not None
        assert visibility_guard.is_evaluation_publishable(evaluation.period, evaluation) == (False, _NO_PROCESS_REASON)
        db.session.rollback()


def test_p6_mobile_high_score_publishes(env) -> None:
    chain = _chain(env)
    _mobile_complete(env, chain, _HIGH)
    _personnel_support_approve(env, chain["evaluation_id"])
    after = _assert_published(env, chain["evaluation_id"])
    assert (after["final"], after["workflow_status"], after["processes"]) == (80.0, "taslak_1_amir", 0)


def test_p7_completed_low_score_whose_process_lookup_finds_nothing_is_blocked(env) -> None:
    """Publish contract says completed, score < 70, the process query returns None."""
    chain = _mobile_low_card_with_personnel_support_approval(env)
    assert _process_id(env, chain["evaluation_id"]) is None
    _assert_blocked(env, chain["evaluation_id"], _NO_PROCESS_REASON)


# ---------------------------------------------------------------------------
# P8/P9 + fail-closed negatives: explicit evidence from an existing process
# ---------------------------------------------------------------------------


def _dt():
    from app.core.datetime_utils import utc_now

    return utc_now()


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({}, _PENDING_REASON),
        ({"status": "president_approved"}, _PENDING_REASON),  # a status label is not evidence
        ({"president_approved_at": "now", "president_rejected_at": "now", "president_rejection_note": "Eksik"}, _REJECTED_REASON),
        ({"president_approved_at": "now"}, _WARNING_MISSING_REASON),
    ],
    ids=["p8_pending_timestamp_none", "status_label_only", "rejected", "approved_without_warning_record"],
)
def test_p8_existing_process_without_publish_release_blocks(env, fields, reason) -> None:
    chain = _mobile_low_card_with_personnel_support_approval(env)
    _seed_process(env, chain["evaluation_id"], **{key: (_dt() if value == "now" else value) for key, value in fields.items()})
    after = _assert_blocked(env, chain["evaluation_id"], reason)
    assert after["processes"] == 1


def test_p9_existing_process_explicitly_released_publishes(env) -> None:
    chain = _mobile_low_card_with_personnel_support_approval(env)
    _seed_process(env, chain["evaluation_id"], status="first_low_warning", president_approved_at=_dt(), president_approved_by_id=env.admin_id, warning_recorded_at=_dt())
    after = _assert_published(env, chain["evaluation_id"])
    assert (after["processes"], after["president_approved"]) == (1, True)


# ---------------------------------------------------------------------------
# Errors in the evidence lookup never become an approval
# ---------------------------------------------------------------------------


def _logged_errors(caplog: pytest.LogCaptureFixture, module: str) -> list[str]:
    return [record.exc_info[0].__name__ for record in caplog.records if record.name == module and record.exc_info and record.exc_info[0]]


def _lookup_raising(fail):
    return SimpleNamespace(query=SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=fail)))


def _operational_error() -> None:
    from app.extensions import db

    db.session.execute(text("SELECT no_such_column FROM performance_low_score_processes"))


def _runtime_error() -> None:
    raise RuntimeError("simulated lookup failure")


@pytest.mark.parametrize(("fail", "expected"), [(_operational_error, "OperationalError"), (_runtime_error, "RuntimeError")], ids=["operational_error", "runtime_error"])
def test_evidence_lookup_error_is_rolled_back_by_the_route(env, monkeypatch, caplog, fail, expected) -> None:
    chain = _mobile_low_card_with_personnel_support_approval(env)
    before = _state(env, chain["evaluation_id"])
    monkeypatch.setattr(importlib.import_module(_PREFLIGHT_MODULE), "PerformanceLowScoreProcess", _lookup_raising(fail))
    with caplog.at_level(logging.ERROR):
        response, flashes = _publish(env, chain["evaluation_id"])
    assert response.status_code == 302
    assert flashes == [_ERROR_FLASH]
    assert _logged_errors(caplog, _ROUTE_MODULE) == [expected]
    assert _logged_errors(caplog, _PREFLIGHT_MODULE) == []  # not swallowed
    assert _state(env, chain["evaluation_id"]) == before


def test_evidence_lookup_integrity_error_is_rolled_back_by_the_route(env, monkeypatch, caplog) -> None:
    """A real IntegrityError from the real lookup query's autoflush (two process
    rows for one evaluation, UNIQUE evaluation_id)."""
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    preflight = importlib.import_module(_PREFLIGHT_MODULE)
    real_predicate = preflight.is_low_score_evaluation
    chain = _mobile_low_card_with_personnel_support_approval(env)
    before = _state(env, chain["evaluation_id"])

    def _predicate_then_pending_duplicates(value):
        for _ in range(2):
            db.session.add(PerformanceLowScoreProcess(period_id=chain["period_id"], evaluation_id=chain["evaluation_id"], employee_id=1, calendar_year=2020))
        return real_predicate(value)

    monkeypatch.setattr(preflight, "is_low_score_evaluation", _predicate_then_pending_duplicates)
    with caplog.at_level(logging.ERROR):
        response, flashes = _publish(env, chain["evaluation_id"])
    assert response.status_code == 302
    assert flashes == [_ERROR_FLASH]
    assert _logged_errors(caplog, _ROUTE_MODULE) == ["IntegrityError"]
    assert _state(env, chain["evaluation_id"]) == before


# ---------------------------------------------------------------------------
# Scope: 70+ and 0/None scores keep their contract; access unchanged
# ---------------------------------------------------------------------------


def test_high_score_publish_never_touches_the_evidence_lookup(env, monkeypatch) -> None:
    def _must_not_be_called():
        raise AssertionError("70+ card must not query low-score evidence")

    monkeypatch.setattr(importlib.import_module(_PREFLIGHT_MODULE), "PerformanceLowScoreProcess", _lookup_raising(_must_not_be_called))
    chain = _chain(env)
    _mobile_complete(env, chain, _HIGH)
    _personnel_support_approve(env, chain["evaluation_id"])
    _assert_published(env, chain["evaluation_id"])


@pytest.mark.parametrize("final_total_100", [None, 0.0])
def test_zero_or_missing_score_keeps_the_previous_preflight_result(final_total_100) -> None:
    """No app context: any evidence query would raise. The result is the same as
    at 5c8b3650 (the low-score service does not count 0/None as a low score)."""
    preflight = importlib.import_module(_PREFLIGHT_MODULE)
    evaluation = SimpleNamespace(
        id=9191,
        period_id=1,
        employee_id=1,
        status="tamamlandi",
        workflow_status="taslak_1_amir",
        employee=SimpleNamespace(role="personel"),
        final_total_100=final_total_100,
        level_1_evaluator_id=501,
        level_2_evaluator_id=None,
        level_3_evaluator_id=None,
        level_1_completed=True,
        level_2_completed=False,
        level_3_completed=False,
        level_1_general_comment=_COMMENT,
        level_2_general_comment="",
        level_3_general_comment="",
        items=[SimpleNamespace(manager_level=1, criteria_id=1, score=3, justification="Yeterli açıklama metni", comment="", strength_note="")],
    )
    period = SimpleNamespace(enable_level_3=False, enable_level_3_scoring=False, level_3_mode="", require_level_3_completion_for_final=False)
    result = preflight.validate_evaluation_for_publish(period, evaluation)
    assert [finding.code for finding in result.blockers] == ["personnel_support_publish_approval_required"]


def test_publish_access_contract_is_unchanged(env) -> None:
    chain = _mobile_low_card_with_personnel_support_approval(env)
    before = _state(env, chain["evaluation_id"])
    for role in ("personel", "grup_baskani"):
        _uid, sicil = _user(env.app, role=role)
        client = env.app.test_client()
        _login(client, sicil)
        assert _publish(env, chain["evaluation_id"], client=client)[0].status_code == 403
    anonymous = env.app.test_client().post(f"/performance/publish/evaluation/{chain['evaluation_id']}", data={}, follow_redirects=False)
    assert anonymous.status_code == 302 and anonymous.headers["Location"].startswith("/login")
    assert _state(env, chain["evaluation_id"]) == before
