"""BYS360 PERFORMANCE P5 (overnight): the personnel-support approval is required for every publication.

Publication preflight (app/services/performance/publish_preflight_rules.validate_evaluation_for_publish):
after the Başkan/Üst Onay step and every earlier blocker, the Personel ve Destek
Hizmetleri Grup Başkanı approval is mandatory before the Admin/İK publication
(personnel_support_publish_approval_service.get_personnel_support_publish_block_reason;
only an explicit "approved" row releases it). While an earlier step still blocks
the card, the approval request is not created yet (predecessor_blocked); for a
70 altı card the service also waits for its low-score predecessor
(_low_score_predecessor_is_ready).

Verified at 18a7f00014b9f4bf9f3f8c537533a7fa48266514: with the admin rule setting
"70 altı Başkan onayı zorunlu" switched off (performance.low_score_requires_president_approval,
the preflight then applies no Başkan/Üst Onay step), the predecessor check still
waited for a Başkan approval that would never come, so it answered "not ready",
the service treated that as "no approval required", and a 60 card was published
with no approval at all -- while a 90 card in the same setup still waited for the
personnel-support approval.

Since P5 the predecessor check uses the same rule-engine decision as the preflight
(requires_president_approval): without a Başkan/Üst Onay step there is nothing to
wait for and the personnel-support approval is required like for any other card.
With the default setting nothing changes.

Real Flask app, real logins, real Başkan/Üst Onay / personnel-support / single and
v2 period publish routes; file-backed SQLite test database only. The
Alembic-owned personnel-support approval table is created with the DDL used by
tests/behavior/test_personnel_support_publish_approval_workflow_contract.py.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

_PASSWORD = "PersonnelSupportPredecessor1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_overnight_p5_personnel_support")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_PERSONNEL_SUPPORT_PENDING = "Personel ve Destek Hizmetleri Grup Başkanı ön onayı tamamlanmadan karne personele açılamaz."
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
        "SECRET_KEY": "test-secret-key-for-overnight-p5-personnel-support",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p5_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P5PS{n:05d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p5-personnel-support-{n}@bys360.test",
            ad="P5Approval",
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
            criteria = PerformanceCriteria(name=f"P5 Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title=f"P5 Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
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


def _calculate(env: SimpleNamespace) -> None:
    response = env.admin.post(
        "/performance/hierarchy-settings",
        data={"action": "save_weights", "period_id": str(env.period_id), "evaluator_1_weight": "50", "evaluator_2_weight": "50", "evaluator_3_weight": "0"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert ("success", "Dönem ağırlıkları güncellendi.") in _flashes(env.admin)


def _president_approval_setting(env: SimpleNamespace, enabled: bool) -> None:
    """The admin rule setting "70 altı Başkan onayı zorunlu" as the settings center stores it."""
    from app.extensions import db
    from app.models import ModuleSetting

    with env.app.app_context():
        db.session.add(
            ModuleSetting(
                module_key="performance_flow", setting_key="low_score_requires_president_approval", label="70 altı Başkan onayı zorunlu",
                value_text="true" if enabled else "false", value_type="bool",
            )
        )
        db.session.commit()


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


def _chair(env: SimpleNamespace, evaluation_id: int, decision: str) -> None:
    """The personnel-support request as the preflight creates it, then the chair's real decision."""
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
    response = env.chair.post(f"/performance/personnel-support-publish-approvals/{approval_id}/{decision}", data={"note": "Karar notu"}, follow_redirects=False)
    assert response.status_code == 302


def _publish(env: SimpleNamespace, evaluation_id: int) -> list[tuple[str, str]]:
    response = env.admin.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    assert response.status_code == 302
    return [flash for flash in _flashes(env.admin) if "e-posta" not in flash[1]]


def _published(env: SimpleNamespace) -> list[int]:
    from app.extensions import db

    with env.app.app_context():
        ids = [int(row[0]) for row in db.session.execute(text("SELECT id FROM performance_evaluations WHERE is_published_to_employee = 1 ORDER BY id")).all()]
        db.session.remove()
    return ids


# ---------------------------------------------------------------------------
# "70 altı Başkan onayı zorunlu" switched off
# ---------------------------------------------------------------------------


def test_without_the_president_step_a_low_score_still_needs_the_personnel_support_approval(env) -> None:
    _president_approval_setting(env, enabled=False)
    low = _card(env, (2, 2), (4, 4))  # 60
    _calculate(env)
    assert _publish(env, low) == [("warning", _PERSONNEL_SUPPORT_PENDING)]
    assert _published(env) == []
    _chair(env, low, "approve")
    assert _publish(env, low) == [("success", "Sonuç personele yayımlandı.")]
    assert _published(env) == [low]


def test_without_the_president_step_the_live_period_publish_also_waits(env) -> None:
    _president_approval_setting(env, enabled=False)
    low = _card(env, (2, 2), (4, 4))  # 60
    high = _card(env, (4, 4), (5, 5))  # 90
    _calculate(env)
    _chair(env, high, "approve")
    response = env.admin.post("/performance/v2/faz5/publish", data={"period_id": str(env.period_id), "publish_action": "publish", "force_publish": "1"}, follow_redirects=False)
    assert response.status_code == 302
    flashes = _flashes(env.admin)
    assert ("warning", f"1 kayıt atlandı: {_PERSONNEL_SUPPORT_PENDING}") in flashes
    assert _published(env) == [high]
    assert low not in _published(env)


def test_low_and_high_scores_need_the_same_approval(env) -> None:
    _president_approval_setting(env, enabled=False)
    low = _card(env, (2, 2), (4, 4))  # 60
    high = _card(env, (4, 4), (5, 5))  # 90
    _calculate(env)
    assert _publish(env, low) == _publish(env, high) == [("warning", _PERSONNEL_SUPPORT_PENDING)]


# ---------------------------------------------------------------------------
# Default setting: unchanged order Başkan/Üst Onay -> personnel support -> publication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("explicit_setting", [False, True], ids=["default", "explicitly_on"])
def test_default_order_is_unchanged(env, explicit_setting) -> None:
    if explicit_setting:
        _president_approval_setting(env, enabled=True)
    low = _card(env, (2, 2), (4, 4))  # 60
    _calculate(env)
    assert _publish(env, low) == [("warning", _PRESIDENT_PENDING)]
    _president_approve(env, low)
    assert _publish(env, low) == [("warning", _PERSONNEL_SUPPORT_PENDING)]
    _chair(env, low, "approve")
    assert _publish(env, low) == [("success", "Sonuç personele yayımlandı.")]


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ("approve", [("success", "Sonuç personele yayımlandı.")]),
        (None, [("warning", _PERSONNEL_SUPPORT_PENDING)]),
        ("return", [("warning", "Personel ve Destek Hizmetleri Grup Başkanı karneyi iade ettiği için Admin/İK yayını yapılamaz. İade notu: Karar notu")]),
    ],
    ids=["approved", "missing_request", "returned"],
)
def test_only_an_explicit_approval_releases_the_publication(env, decision, expected) -> None:
    high = _card(env, (4, 4), (5, 5))
    _calculate(env)
    if decision:
        _chair(env, high, decision)
    assert _publish(env, high) == expected
    assert _published(env) == ([high] if decision == "approve" else [])


def test_approval_read_failure_is_not_an_approval(env) -> None:
    from app.extensions import db

    high = _card(env, (4, 4), (5, 5))
    _calculate(env)
    _chair(env, high, "approve")

    def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if "FROM performance_personnel_support_publish_approvals" in statement:
            raise OperationalError(statement, parameters, Exception("simulated database outage"))

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _fail)
    try:
        flashes = _publish(env, high)
    finally:
        event.remove(engine, "before_cursor_execute", _fail)
    assert flashes == [("danger", "Tekil yayın sırasında hata oluştu.")]
    assert _published(env) == []
