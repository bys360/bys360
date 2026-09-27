"""BYS360 PERFORMANCE P6 (overnight): a partially completed card is not a completed 70 altı card.

low_score_process_service._is_completed decides whether a card is "completed" for
the 70 altı chain (is_low_score_evaluation -> ensure_low_score_process_for_evaluation
-> the Başkan/Üst Onay queue). It excluded draft / pending / returned states, but its
fallback accepted any value containing "tamam", and the partial status
"kismen_tamamlandi" (set by scoring.recalculate_evaluation_totals when only some
required levels are completed, and by the mobile partial save) contains "tamam".

Verified at 18a7f00014b9f4bf9f3f8c537533a7fa48266514: a card whose 2. amir had
submitted (workflow level_2_tamamlandi) while the 1. amir had not scored yet was
recalculated by the weight save to status kismen_tamamlandi with final 50 (0 x 50%
+ 100 x 50%); the next GET of the 70 altı page (and the publish pre-step) opened a
president_approval_pending process for it, so the Başkan/Üst Onay queue showed a
50 that no manager had completed.

Since P6 a value containing "kismen" is treated like the other not-final states, and
so is an explicit negative completion value ("tamamlanmadi", "tamamlanmamis",
"tamamlanmayan": the "tamamlanma" stem). No writer sets a negative value today, but
the same "tamam" fallback accepted it. The positive forms ("tamamlandi", "tamamlandı",
"tamamlanmis", "tamamlanmış") do not contain "tamamlanma" and stay completed.
Fully completed cards are unchanged; the process follows the real completion.

Real Flask app, real admin login, real weight save / 70 altı page / v2 publish
routes; file-backed SQLite test database only.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import event, text

_PASSWORD = "TestLowScorePartial1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_overnight_p6_partial")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_counter = 0


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-overnight-p6-partial",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p6_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
    return flask_app


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _user(flask_app, *, role: str, managers: tuple[str | None, str | None] | None = None) -> tuple[int, str]:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        n = _next()
        sicil_no = f"P6LS{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p6-partial-{n}@bys360.test",
            ad="P6Partial",
            soyad=f"Kisi{n}",
            role=role,
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
    from app.extensions import db
    from app.models import PerformanceCriteria, PerformancePeriod

    flask_app = _make_app(monkeypatch)
    admin_id, admin_sicil = _user(flask_app, role="admin")
    admin = flask_app.test_client()
    _login(admin, admin_sicil)
    criteria_ids = []
    with flask_app.app_context():
        for index in range(2):
            criteria = PerformanceCriteria(name=f"P6 Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P6 Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        period_id = int(period.id)
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, criteria_ids=criteria_ids, period_id=period_id)


def _card(env: SimpleNamespace, *, level_1_scores: tuple[int, int] | None, level_2_scores: tuple[int, int]) -> int:
    """A two-manager card; without level_1_scores it is what the v2 level-2 submit leaves
    (2. amir completed, 1. amir not scored yet)."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem

    l1_id, l1_sicil = _user(env.app, role="grup_baskani")
    l2_id, l2_sicil = _user(env.app, role="koordinator")
    employee_id, _sicil = _user(env.app, role="personel", managers=(l1_sicil, l2_sicil))
    partial = level_1_scores is None
    with env.app.app_context():
        evaluation = PerformanceEvaluation(
            period_id=env.period_id, employee_id=employee_id, level_1_evaluator_id=l1_id, level_2_evaluator_id=l2_id,
            level_1_completed=not partial, level_2_completed=True,
            status="devam_ediyor" if partial else "tamamlandi", workflow_status="level_2_tamamlandi" if partial else "tamamlandi",
            level_1_general_comment=None if partial else _COMMENT,
        )
        db.session.add(evaluation)
        db.session.flush()
        levels = ((2, level_2_scores),) if partial else ((1, level_1_scores), (2, level_2_scores))
        for level, scores in levels:
            for criteria_id, score in zip(env.criteria_ids, scores or (), strict=True):
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


def _cards(env: SimpleNamespace) -> list[tuple[int, str, float]]:
    from app.extensions import db

    with env.app.app_context():
        rows = [(int(r[0]), r[1], r[2]) for r in db.session.execute(text("SELECT id, status, final_total_100 FROM performance_evaluations ORDER BY id")).all()]
        db.session.remove()
    return rows


def _processes(env: SimpleNamespace) -> list[tuple[int, float, str]]:
    from app.extensions import db

    with env.app.app_context():
        rows = [(int(r[0]), r[1], r[2]) for r in db.session.execute(text("SELECT evaluation_id, final_total_100, status FROM performance_low_score_processes ORDER BY id")).all()]
        db.session.remove()
    return rows


def _event_evaluations(env: SimpleNamespace) -> set[int]:
    """The cards that have 70 altı chain events (evaluation_completed, president_approval, ...)."""
    from app.extensions import db

    sql = "SELECT DISTINCT p.evaluation_id FROM performance_low_score_process_events e JOIN performance_low_score_processes p ON p.id = e.process_id"
    with env.app.app_context():
        rows = {int(r[0]) for r in db.session.execute(text(sql)).all()}
        db.session.remove()
    return rows


# ---------------------------------------------------------------------------
# The helper's status table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "workflow", "level_1_completed", "expected"),
    [
        ("tamamlandi", "tamamlandi", True, True),
        ("TAMAMLANDI", "Tamamlandi", True, True),
        ("kismen_tamamlandi", "level_2_tamamlandi", False, False),
        ("kismen_tamamlandi", "level_3_tamamlandi", False, False),
        ("kismen_tamamlandi", "", True, False),
        ("kismen_tamamlandi", "", False, False),
        ("kismen_tamamlandi", "taslak_1_amir", False, False),
        ("devam_ediyor", "level_2_tamamlandi", False, False),
        ("taslak", "taslak_1_amir", False, False),
        ("kismen_tamamlandi", "level_2_iade", False, False),
        ("kismen_tamamlandi", "tamamlandi", True, False),
        # olumlu biçimler: tamamlanma durumdan gelir (1. amir bayrağı kapalı)
        ("tamamlandı", "", False, True),
        ("tamamlanmis", "", False, True),
        ("tamamlanmış", "", False, True),
        ("completed", "", False, True),
        # açık olumsuz biçimler: 1. amir bayrağı açık olsa da tamamlanmış sayılmaz
        ("tamamlanmadi", "", False, False),
        ("tamamlanmadi", "", True, False),
        ("tamamlanmadı", "", True, False),
        ("tamamlanmamis", "level_2_tamamlandi", True, False),
        ("tamamlanmamış", "", True, False),
        ("tamamlanmayan", "", True, False),
        ("", "", False, False),
        (None, None, False, False),
        # tanınmayan değer: mevcut sözleşme (1. amir tamamlanmadıysa tamamlanmış sayılmaz)
        ("bilinmeyen_durum", "", False, False),
    ],
)
def test_only_final_cards_count_as_completed_low_scores(status, workflow, level_1_completed, expected) -> None:
    from app.services.performance.low_score_process_service import (
        _is_completed,
        is_low_score_evaluation,
    )

    card = SimpleNamespace(status=status, workflow_status=workflow, level_1_completed=level_1_completed, final_total_100=50.0)
    assert _is_completed(cast(Any, card)) is expected  # the helpers read attributes only
    assert is_low_score_evaluation(cast(Any, card)) is expected


# ---------------------------------------------------------------------------
# The real flow
# ---------------------------------------------------------------------------


def test_partially_completed_low_total_opens_no_process(env) -> None:
    partial = _card(env, level_1_scores=None, level_2_scores=(5, 5))  # 2. amir 100, 1. amir not yet
    completed_low = _card(env, level_1_scores=(2, 2), level_2_scores=(3, 3))  # 40 / 60 -> 50
    _calculate(env)
    assert _cards(env) == [(partial, "kismen_tamamlandi", 50.0), (completed_low, "tamamlandi", 50.0)]

    assert env.admin.get(f"/performance/low-score-processes?period_id={env.period_id}").status_code == 200
    assert _processes(env) == [(completed_low, 50.0, "president_approval_pending")]
    response = env.admin.post("/performance/v2/faz5/publish", data={"period_id": str(env.period_id), "publish_action": "publish", "force_publish": "1"}, follow_redirects=False)
    assert response.status_code == 302
    _flashes(env.admin)
    assert _processes(env) == [(completed_low, 50.0, "president_approval_pending")]
    assert _event_evaluations(env) == {completed_low}  # no Başkan/Üst Onay step for the partial card


@pytest.mark.parametrize("negative_status", ["tamamlanmadi", "tamamlanmamis", "tamamlanmayan"])
def test_an_explicitly_incomplete_low_total_opens_no_process(env, negative_status) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation

    incomplete = _card(env, level_1_scores=(2, 2), level_2_scores=(3, 3))  # 40 / 60 -> 50
    completed_low = _card(env, level_1_scores=(2, 2), level_2_scores=(3, 3))
    # No writer sets a negative value today (the weight recalculation would rewrite the
    # status and already materialize), so the card is stored as it would be read; the
    # 70 altı page and the sync below are then the only materialization.
    with env.app.app_context():
        for evaluation_id in (incomplete, completed_low):
            evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
            assert evaluation is not None
            evaluation.final_total_100 = 50.0
            if evaluation_id == incomplete:
                evaluation.status = negative_status
                evaluation.workflow_status = negative_status
        db.session.commit()
    assert _cards(env) == [(incomplete, negative_status, 50.0), (completed_low, "tamamlandi", 50.0)]
    assert _processes(env) == []

    assert env.admin.get(f"/performance/low-score-processes?period_id={env.period_id}").status_code == 200
    response = env.admin.post(f"/performance/low-score-processes/sync/{env.period_id}", follow_redirects=False)
    assert response.status_code == 302
    _flashes(env.admin)
    assert _processes(env) == [(completed_low, 50.0, "president_approval_pending")]
    assert _event_evaluations(env) == {completed_low}


def test_the_process_follows_the_real_completion(env) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem

    partial = _card(env, level_1_scores=None, level_2_scores=(3, 3))  # 2. amir 60
    _calculate(env)
    env.admin.get(f"/performance/low-score-processes?period_id={env.period_id}")
    assert _processes(env) == []
    assert _event_evaluations(env) == set()
    with env.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, partial)
        assert evaluation is not None
        for criteria_id in env.criteria_ids:
            db.session.add(PerformanceEvaluationItem(evaluation_id=partial, criteria_id=criteria_id, manager_level=1, score=3.0, score_100=60.0, justification="Gerekçe"))
        evaluation.level_1_completed = True
        evaluation.level_1_general_comment = _COMMENT
        evaluation.workflow_status = "tamamlandi"
        db.session.commit()
    _calculate(env)  # completed now: 60 / 60 -> 60, materialized by the recalculation (P0.2O-W)
    assert _cards(env) == [(partial, "tamamlandi", 60.0)]
    assert _processes(env) == [(partial, 60.0, "president_approval_pending")]
    assert _event_evaluations(env) == {partial}
