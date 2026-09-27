"""BYS360 PERFORMANCE P0.2AA: the snapshot backfill only repairs missing publication snapshots.

Route: POST /performance/snapshots/backfill (main.performance_snapshot_backfill,
app/performance/engagement_publish_routes.py; login + admin + menu
"performance_publish") -> performance_snapshot_service.backfill_snapshots_for_published_periods
-> create_snapshot_for_evaluation (the existing versioning helper) -> route commit.

Verified at 326f7e0ab7283455e7d41e0dc885cbca29c9c1fe (P0.2Z): the route never
committed (every snapshot was rolled back at request end) while flashing
"Dönem: 0, Yeni: N, Güncellenen: 0, Atlanan: 0" from keys the service did not
return; the service re-versioned every completed card of every published OR
active period, including unpublished cards and a low score still waiting for
Başkan/Üst Onay, on every call.

Since P0.2AA a card is repaired only when all of these hold: its period has
results_published, the card is completed ("tamamlandi"), the card carries the
publication evidence (is_published_to_employee or published_to_employee_at),
and it has no current system_published snapshot (evaluation_id link). The
backfill never publishes anything; the route owns the transaction (commit on
success, rollback + error flash on any failure). The v2 period publish (the
publish screen) writes no snapshot, which is the gap this repair closes.
Publication visibility of existing snapshots is not changed (P0.2V CASE C).

Real Flask app, real admin login, real personnel-support / Başkan/Üst Onay /
v2 period publish routes; file-backed SQLite test database only. The
Alembic-owned personnel-support approval table is created with the DDL used by
tests/behavior/test_personnel_support_publish_approval_workflow_contract.py.
"""
from __future__ import annotations

import importlib
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

_SERVICE_MODULE = "app.services.performance_snapshot_service"
_URL = "/performance/snapshots/backfill"
_PASSWORD = "TestSnapshotBackfillRepair1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02aa_snapshot_backfill")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_ERROR_FLASH = [("danger", "Snapshot backfill sırasında hata oluştu.")]

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
        "SECRET_KEY": "test-secret-key-for-p02aa-snapshot-backfill",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02aa_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P2AA{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02aa-backfill-{n}@bys360.test",
            ad="P02AA",
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
    """Admin (publish screens, Başkan/Üst Onay, backfill) and the Personel ve Destek
    Hizmetleri Grup Başkanı, logged in for real; one criteria set."""
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
            criteria = PerformanceCriteria(name=f"P0.2AA Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        db.session.commit()
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids)


# ---------------------------------------------------------------------------
# Data through the real routes
# ---------------------------------------------------------------------------


def _period(env: SimpleNamespace, **columns: Any) -> int:
    """An ended quarter (the v2 publish window is open), active unless told otherwise."""
    from app.extensions import db
    from app.models import PerformancePeriod

    with env.app.app_context():
        values = {"is_active": True, **columns}
        period = PerformancePeriod(title=f"P0.2AA Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), **values)
        db.session.add(period)
        db.session.commit()
        return int(period.id)


def _completed_evaluation(env: SimpleNamespace, period_id: int, level_1_scores: tuple[int, int], level_2_scores: tuple[int, int]) -> int:
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem

    l1_id, l1_sicil = _user(env.app, role="grup_baskani")
    l2_id, l2_sicil = _user(env.app, role="koordinator")
    employee_id, _sicil = _user(env.app, role="personel", managers=(l1_sicil, l2_sicil))
    with env.app.app_context():
        evaluation = PerformanceEvaluation(
            period_id=period_id, employee_id=employee_id, level_1_evaluator_id=l1_id, level_2_evaluator_id=l2_id,
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


def _calculate(env: SimpleNamespace, period_id: int) -> None:
    """Totals through the real weight save (50/50) of the open period."""
    response = env.admin.post(
        "/performance/hierarchy-settings",
        data={"action": "save_weights", "period_id": str(period_id), "evaluator_1_weight": "50", "evaluator_2_weight": "50", "evaluator_3_weight": "0"},
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


def _v2_publish(env: SimpleNamespace, period_id: int) -> list[tuple[str, str]]:
    """The publish screen's period publish: opens the eligible cards, writes no snapshot."""
    response = env.admin.post("/performance/v2/faz5/publish", data={"period_id": str(period_id), "publish_action": "publish", "force_publish": "1"}, follow_redirects=False)
    assert response.status_code == 302
    return _flashes(env.admin)


def _published_period(env: SimpleNamespace, *cards: tuple[tuple[int, int], tuple[int, int], str]) -> tuple[int, list[int]]:
    """Cards are (level 1 scores, level 2 scores, "approve" | "president" | "none")."""
    period_id = _period(env)
    evaluation_ids = [_completed_evaluation(env, period_id, level_1, level_2) for level_1, level_2, _mode in cards]
    _calculate(env, period_id)
    for evaluation_id, (_level_1, _level_2, mode) in zip(evaluation_ids, cards, strict=True):
        if mode == "president":
            _president_approve(env, evaluation_id)
        if mode in {"approve", "president"}:
            _personnel_support_approve(env, evaluation_id)
    _v2_publish(env, period_id)
    return period_id, evaluation_ids


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


def _backfill(env: SimpleNamespace, client=None) -> tuple[Any, list[tuple[str, str]], list[str]]:
    """Real backfill POST; returns the response, its flashes and every DML statement issued."""
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
        response = client.post(_URL, data={}, follow_redirects=False)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return response, _flashes(client), dml


def _state(env: SimpleNamespace) -> dict[str, list[dict[str, Any]]]:
    """Every row the backfill could touch, as a fresh session sees it."""
    from app.extensions import db

    def _rows(table: str) -> list[dict[str, Any]]:
        return [dict(row) for row in db.session.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings().all()]  # noqa: S608

    with env.app.app_context():
        db.session.remove()
        state = {table: _rows(table) for table in ("performance_result_snapshots", "performance_periods", "performance_evaluations")}
        db.session.remove()
    return state


def _snapshots(state: dict[str, list[dict[str, Any]]]) -> list[tuple[Any, ...]]:
    return [
        (row["evaluation_id"], row["source_type"], row["version_no"], bool(row["is_current"]), row["final_total_100"])
        for row in state["performance_result_snapshots"]
    ]


def _assert_one_current_per_person(state: dict[str, list[dict[str, Any]]]) -> None:
    current = Counter((row["period_id"], row["employee_id"]) for row in state["performance_result_snapshots"] if row["is_current"])
    assert all(count == 1 for count in current.values())


def _success(period_count: int, created: int, skipped: int) -> list[tuple[str, str]]:
    return [("success", f"Snapshot backfill tamamlandı. Dönem: {period_count}, Yeni: {created}, Atlanan: {skipped}")]


# ---------------------------------------------------------------------------
# Repair of a published card
# ---------------------------------------------------------------------------


def test_published_card_without_snapshot_is_repaired_and_persisted(env) -> None:
    period_id, (evaluation_id,) = _published_period(env, ((4, 4), (5, 5), "approve"))
    before = _state(env)
    assert before["performance_result_snapshots"] == []  # the v2 period publish writes no snapshot
    assert [(row["is_published_to_employee"], row["final_total_100"]) for row in before["performance_evaluations"]] == [(1, 90.0)]

    response, flashes, dml = _backfill(env)
    assert response.status_code == 302 and response.headers["Location"] == "/performance/publish"
    assert flashes == _success(1, 1, 0)
    assert Counter(dml) == Counter(
        {"UPDATE performance_result_snapshots": 2, "INSERT INTO performance_result_snapshots": 1, "UPDATE performance_periods": 1}
    )  # deactivate-current, insert, ranking; period snapshot stamp

    after = _state(env)  # a fresh session: the repair is committed
    (snapshot,) = after["performance_result_snapshots"]
    assert (snapshot["period_id"], snapshot["employee_id"], snapshot["evaluation_id"]) == (period_id, _employee(env, evaluation_id), evaluation_id)
    assert (snapshot["source_type"], snapshot["version_no"], bool(snapshot["is_current"]), snapshot["final_total_100"]) == ("system_published", 1, True, 90.0)
    assert (snapshot["published_by_user_id"], snapshot["ranking_in_scope"], snapshot["source_reference"]) == (env.admin_id, 1, f"evaluation:{evaluation_id}")
    (period,) = after["performance_periods"]
    assert (period["snapshot_status"], period["snapshot_generated_by_id"]) == ("completed", env.admin_id)
    assert after["performance_evaluations"] == before["performance_evaluations"]  # nothing is (re)published


def test_repeated_backfill_is_idempotent(env) -> None:
    _published_period(env, ((4, 4), (5, 5), "approve"))
    assert _backfill(env)[1] == _success(1, 1, 0)
    first = _state(env)
    for _attempt in range(2):
        response, flashes, dml = _backfill(env)
        assert response.status_code == 302
        assert flashes == _success(1, 0, 1)
        assert dml == []
        assert _state(env) == first  # same version_no, published_at and current row


def test_published_low_score_card_is_repaired_like_any_published_card(env) -> None:
    """70 altı: the publication itself is the evidence (Başkan/Üst Onay was required
    to publish it); the backfill does not re-decide the approval."""
    _period_id, (evaluation_id,) = _published_period(env, ((2, 2), (4, 4), "president"))
    before = _state(env)
    assert [(row["is_published_to_employee"], row["final_total_100"]) for row in before["performance_evaluations"]] == [(1, 60.0)]
    assert _backfill(env)[1] == _success(1, 1, 0)
    assert _snapshots(_state(env)) == [(evaluation_id, "system_published", 1, True, 60.0)]


def test_counts_cover_created_and_already_current_cards(env) -> None:
    from app.extensions import db

    _period_id, (existing_id, first_id, second_id) = _published_period(
        env, ((5, 5), (5, 5), "approve"), ((3, 3), (4, 4), "approve"), ((4, 4), (5, 5), "approve")
    )
    service = importlib.import_module(_SERVICE_MODULE)
    with env.app.app_context():
        service.create_snapshot_for_evaluation(existing_id, actor_user_id=env.admin_id)
        db.session.commit()
    existing_row = _state(env)["performance_result_snapshots"][0]

    assert _backfill(env)[1] == _success(1, 2, 1)
    after = _state(env)
    assert after["performance_result_snapshots"][0] | {"ranking_in_scope": None, "ranking_in_unit": None, "updated_at": None} == existing_row | {
        "ranking_in_scope": None, "ranking_in_unit": None, "updated_at": None,
    }  # the existing current row is kept; only its ranking is refreshed
    assert _snapshots(after) == [
        (existing_id, "system_published", 1, True, 100.0),
        (first_id, "system_published", 1, True, 70.0),
        (second_id, "system_published", 1, True, 90.0),
    ]
    assert [row["ranking_in_scope"] for row in after["performance_result_snapshots"]] == [1, 3, 2]
    _assert_one_current_per_person(after)


# ---------------------------------------------------------------------------
# Never a publication mechanism
# ---------------------------------------------------------------------------


def test_unpublished_results_are_never_backfilled(env) -> None:
    """Active but unpublished period; published period with a card the publish
    skipped (no personnel-support approval) and a 70 altı card waiting for
    Başkan/Üst Onay: only the published card is repaired."""
    open_period = _period(env)
    _completed_evaluation(env, open_period, (4, 4), (5, 5))
    _calculate(env, open_period)
    _published_id, (published, skipped, waiting_low) = _published_period(
        env, ((4, 4), (5, 5), "approve"), ((4, 4), (4, 4), "none"), ((2, 2), (3, 3), "none")
    )
    before = _state(env)
    assert [(row["id"], row["is_published_to_employee"], row["final_total_100"]) for row in before["performance_evaluations"]][1:] == [
        (published, 1, 90.0), (skipped, 0, 80.0), (waiting_low, 0, 50.0),
    ]

    assert _backfill(env)[1] == _success(1, 1, 0)
    after = _state(env)
    assert _snapshots(after) == [(published, "system_published", 1, True, 90.0)]
    assert after["performance_evaluations"] == before["performance_evaluations"]
    assert [row for row in after["performance_periods"] if row["id"] == open_period] == [row for row in before["performance_periods"] if row["id"] == open_period]


@pytest.mark.parametrize(
    ("period_published", "status", "flag", "published_at", "created"),
    [
        (True, "tamamlandi", True, None, 1),
        (True, "tamamlandi", False, datetime(2026, 4, 2), 1),
        (True, "tamamlandi", False, None, 0),
        (False, "tamamlandi", True, datetime(2026, 4, 2), 0),  # period flag switched off (W8 drift)
        (True, "bekliyor", True, datetime(2026, 4, 2), 0),
    ],
    ids=["card_flag", "card_timestamp", "card_not_published", "period_not_published", "card_not_completed"],
)
def test_period_flag_completion_and_card_publication_are_all_required(env, period_published, status, flag, published_at, created) -> None:
    period_id = _period(env, is_active=False, results_published=period_published)
    evaluation_id = _completed_evaluation(env, period_id, (4, 4), (5, 5))
    _set(env, "PerformanceEvaluation", evaluation_id, status=status, is_published_to_employee=flag, published_to_employee_at=published_at, final_total_100=90.0)
    before = _state(env)

    response, flashes, dml = _backfill(env)
    assert response.status_code == 302
    assert flashes == _success(1 if period_published else 0, created, 0)
    if created:
        assert _snapshots(_state(env)) == [(evaluation_id, "system_published", 1, True, 90.0)]
    else:
        assert dml == []
        assert _state(env) == before


# ---------------------------------------------------------------------------
# Historical import collision
# ---------------------------------------------------------------------------


def test_historical_import_row_is_kept_and_the_published_result_becomes_current(env) -> None:
    """Same model rule as the history import (a live published result wins over
    imported history): the imported row stays in the table, not current."""
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import PerformanceResultSnapshot, User

    period_id = _period(env)
    evaluation_id = _completed_evaluation(env, period_id, (4, 4), (5, 5))
    employee_id = _employee(env, evaluation_id)
    with env.app.app_context():
        db.session.add(
            PerformanceResultSnapshot(
                period_id=period_id, employee_id=employee_id, evaluation_id=None, employee_name_snapshot="Geçmiş Kayıt", sicil_no_snapshot="HIST",
                final_total_100=77.0, published_at=datetime(2025, 1, 1), source_type="historical_excel_import", source_reference="gecmis.xlsx#batch:1",
                version_no=1, is_current=True,
            )
        )
        db.session.commit()
    _calculate(env, period_id)
    _personnel_support_approve(env, evaluation_id)
    _v2_publish(env, period_id)
    historical = _state(env)["performance_result_snapshots"][0]

    assert _backfill(env)[1] == _success(1, 1, 0)
    after = _state(env)
    kept, repaired = after["performance_result_snapshots"]
    assert kept | {"is_current": None, "updated_at": None, "ranking_in_scope": None, "ranking_in_unit": None} == historical | {
        "is_current": None, "updated_at": None, "ranking_in_scope": None, "ranking_in_unit": None,
    }
    assert not kept["is_current"]
    assert (repaired["evaluation_id"], repaired["source_type"], repaired["version_no"], bool(repaired["is_current"]), repaired["final_total_100"]) == (
        evaluation_id, "system_published", 2, True, 90.0,
    )
    _assert_one_current_per_person(after)

    with env.app.app_context():
        employee = db.session.get(User, employee_id)
        assert employee is not None
        token = _issue_token(employee)
    body = env.app.test_client().get("/api/mobile/performance/scorecards", headers={"Authorization": f"Bearer {token}"}).get_json()
    assert {metric["title"]: metric["value"] for metric in body["metrics"]}["Karne"] == "1"  # current only (P0.2W)
    assert _backfill(env)[1] == _success(1, 0, 1)
    assert _state(env) == after


# ---------------------------------------------------------------------------
# One transaction, owned by the route
# ---------------------------------------------------------------------------


def test_failure_in_the_middle_of_a_batch_persists_nothing(env, monkeypatch) -> None:
    _published_period(env, ((4, 4), (5, 5), "approve"), ((3, 3), (4, 4), "approve"), ((5, 5), (5, 5), "approve"))
    service = importlib.import_module(_SERVICE_MODULE)
    real = service.create_snapshot_for_evaluation
    calls: list[int] = []

    def _third_fails(evaluation_id, actor_user_id=None):
        calls.append(evaluation_id)
        if len(calls) == 3:
            raise RuntimeError("simulated failure on the third card")
        return real(evaluation_id, actor_user_id=actor_user_id)

    monkeypatch.setattr(service, "create_snapshot_for_evaluation", _third_fails)
    before = _state(env)
    response, flashes, dml = _backfill(env)
    assert response.status_code == 302 and flashes == _ERROR_FLASH
    assert len(calls) == 3 and "INSERT INTO performance_result_snapshots" in dml  # two snapshots were written, then rolled back
    assert _state(env) == before  # snapshots, rankings and the period stamp


def _fail_snapshot_insert(error_class):
    def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().upper().startswith("INSERT INTO PERFORMANCE_RESULT_SNAPSHOTS"):
            raise error_class(statement, parameters, Exception("simulated database error"))

    return _fail


@pytest.mark.parametrize("failure", ["integrity_error", "operational_error", "sqlalchemy_error"])
def test_database_errors_roll_back_without_a_success_message(env, monkeypatch, failure) -> None:
    from app.extensions import db

    _published_period(env, ((4, 4), (5, 5), "approve"), ((3, 3), (4, 4), "approve"))
    before = _state(env)
    with env.app.app_context():
        engine = db.engine
    hook = None
    if failure == "sqlalchemy_error":
        service = importlib.import_module(_SERVICE_MODULE)

        def _ranking_fails(period_id):
            raise SQLAlchemyError("simulated error after the inserts")

        monkeypatch.setattr(service, "_recalculate_period_rankings", _ranking_fails)
    else:
        hook = _fail_snapshot_insert(IntegrityError if failure == "integrity_error" else OperationalError)
        event.listen(engine, "before_cursor_execute", hook)
    try:
        response, flashes, _dml = _backfill(env)
    finally:
        if hook is not None:
            event.remove(engine, "before_cursor_execute", hook)
    assert response.status_code == 302 and flashes == _ERROR_FLASH
    assert _state(env) == before


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


def test_access_contract_is_unchanged(env) -> None:
    _published_period(env, ((4, 4), (5, 5), "approve"))
    before = _state(env)
    anonymous, _flashes_anonymous, anonymous_dml = _backfill(env, client=env.app.test_client())
    assert anonymous.status_code == 302 and anonymous.headers["Location"].startswith("/login")
    _uid, sicil = _user(env.app, role="personel")
    personel = env.app.test_client()
    _login(personel, sicil)
    denied, _flashes_denied, _denied_dml = _backfill(env, client=personel)
    assert denied.status_code == 403
    assert anonymous_dml == []
    assert _state(env)["performance_result_snapshots"] == before["performance_result_snapshots"] == []
