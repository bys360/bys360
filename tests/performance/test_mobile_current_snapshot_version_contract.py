"""BYS360 PERFORMANCE P0.2W: mobile performance results read the current snapshot version only.

Shared query: app/api/mobile/services/performance_query_helpers.py::_snapshot_query_for
(global mobile roles: every employee, others: their own rows) and
_period_snapshot_query (+ period). Consumers (all current result / metric):
GET /api/mobile/performance/scorecards, /summary, /reports, /risk-analysis,
/development-suggestions, /periods/<id>, the full-feature summary and the
publish pre-approval fallback. None of them shows version_no or a version
history; "Karne ve Arşiv" lists results per period.

Snapshot versioning (app/services/performance_snapshot_service.py and the
historical Excel import): a new version sets the previous current row of the
same (period, employee) to is_current=False, so each (period, employee) has at
most one current row; older versions stay in the table as history. The web
snapshot views (comparison_service / my-comparison) read is_current=True.

Verified at d236c258d5118ae70a1bceadb4ad894f18054626: the mobile query had no
is_current filter, so an old version was listed next to the current one and
counted in the average, the "70 altı" count, the risk list and the development
suggestions (v1=40 old + v2=80 current -> average 60, one false low score).

Since P0.2W the shared query keeps only is_current=True. Publication visibility
(period / card publish flags) is deliberately NOT changed (P0.2V CASE C).

Real Flask app, real publish / unpublish routes, real mobile Bearer auth;
file-backed SQLite test database only. Rows that the real writers would create
through an Excel upload (historical import) are inserted with the same shape.
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text

_PASSWORD = "MobileCurrentSnapshot1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02w_current_snapshot")
_COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılanamadı; gelişim planı gereklidir."
_HISTORY_IMPORT = "historical_excel_import"

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
        "SECRET_KEY": "test-secret-key-for-p02w-current-snapshot",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02w_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        sicil_no = f"P2W{n:06d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02w-snapshot-{n}@bys360.test",
            ad="P02W",
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
            criteria = PerformanceCriteria(name=f"P0.2W Kriter {_next()}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        db.session.commit()
    return SimpleNamespace(app=flask_app, admin=admin, admin_id=admin_id, chair=chair, criteria_ids=criteria_ids)


def _period(env: SimpleNamespace) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod

    with env.app.app_context():
        period = PerformancePeriod(title=f"P0.2W Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        return int(period.id)


def _snapshot(env: SimpleNamespace, *, period_id: int, employee_id: int, final: float, version: int, current: bool, source: str = "system_published") -> int:
    """A snapshot row with the shape the publish / historical import writers produce."""
    from app.extensions import db
    from app.models import PerformanceResultSnapshot

    with env.app.app_context():
        row = PerformanceResultSnapshot(
            period_id=period_id,
            evaluation_id=None,
            employee_id=employee_id,
            employee_name_snapshot="Snapshot Personel",
            sicil_no_snapshot="SNAP",
            final_total_100=final,
            published_at=datetime(2026, 4, 1),
            source_type=source,
            version_no=version,
            is_current=current,
        )
        db.session.add(row)
        db.session.commit()
        return int(row.id)


def _get(env: SimpleNamespace, user_id: int | None, path: str) -> dict[str, Any]:
    """Real mobile GET; metrics by title, item ids, and every DML statement issued."""
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    headers = {}
    if user_id is not None:
        with env.app.app_context():
            user = db.session.get(User, user_id)
            assert user is not None
            headers["Authorization"] = f"Bearer {_issue_token(user)}"
    dml: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            dml.append(statement)

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = env.app.test_client().get(path, headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    body = response.get_json() or {}
    return {
        "status": response.status_code,
        "metrics": {metric.get("title"): metric.get("value") for metric in body.get("metrics", [])},
        "items": [str(item.get("id")) for item in body.get("items", [])],
        "body": body,
        "dml": dml,
    }


def _rows(env: SimpleNamespace, employee_id: int) -> list[tuple[int, int, bool]]:
    from app.extensions import db

    with env.app.app_context():
        rows = db.session.execute(
            text("SELECT id, version_no, is_current FROM performance_result_snapshots WHERE employee_id = :e ORDER BY id"), {"e": employee_id}
        ).all()
        db.session.remove()
    return [(int(r[0]), int(r[1]), bool(r[2])) for r in rows]


# ---------------------------------------------------------------------------
# Real publish -> unpublish -> republish: one current version, listed once
# ---------------------------------------------------------------------------


def test_republished_result_is_listed_once_with_its_current_version(env) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem
    from app.services.performance.personnel_support_publish_approval_service import (
        ensure_personnel_support_publish_approval_for_evaluation,
    )

    period_id = _period(env)
    l1_id, l1_sicil = _user(env.app, role="grup_baskani")
    l2_id, l2_sicil = _user(env.app, role="koordinator")
    employee_id, _sicil = _user(env.app, role="personel", managers=(l1_sicil, l2_sicil, None))
    with env.app.app_context():
        evaluation = PerformanceEvaluation(
            period_id=period_id, employee_id=employee_id, level_1_evaluator_id=l1_id, level_2_evaluator_id=l2_id,
            level_1_completed=True, level_2_completed=True, status="tamamlandi", workflow_status="tamamlandi",
            level_1_general_comment=_COMMENT, final_total_100=90.0, level_1_total_100=80.0, level_2_total_100=100.0,
        )
        db.session.add(evaluation)
        db.session.flush()
        for level, scores in ((1, (4, 4)), (2, (5, 5))):
            for criteria_id, score in zip(env.criteria_ids, scores, strict=True):
                db.session.add(PerformanceEvaluationItem(evaluation_id=evaluation.id, criteria_id=criteria_id, manager_level=level, score=float(score), score_100=float(score) * 20, justification="Gerekçe"))
        db.session.commit()
        evaluation_id = int(evaluation.id)
        row = ensure_personnel_support_publish_approval_for_evaluation(evaluation)
        assert row is not None
        approval_id = int(row["id"])
        db.session.commit()
    assert env.chair.post(f"/performance/personnel-support-publish-approvals/{approval_id}/approve", data={"note": "Uygundur."}).status_code == 302
    for path, flash in (
        (f"/performance/publish/evaluation/{evaluation_id}", ("success", "Sonuç personele yayımlandı.")),
        (f"/performance/unpublish/evaluation/{evaluation_id}", ("success", "Sonuç yayından kaldırıldı.")),
        (f"/performance/publish/evaluation/{evaluation_id}", ("success", "Sonuç personele yayımlandı.")),
    ):
        assert env.admin.post(path, data={}, follow_redirects=False).status_code == 302
        assert flash in _flashes(env.admin)

    rows = _rows(env, employee_id)
    assert [(version, current) for _id, version, current in rows] == [(1, False), (2, True)]  # history kept, one current
    result = _get(env, employee_id, "/api/mobile/performance/scorecards")
    assert result["status"] == 200 and result["dml"] == []
    assert result["items"] == [str(rows[1][0])]
    assert (result["metrics"]["Karne"], result["metrics"]["Ortalama"]) == ("1", "90/100")


# ---------------------------------------------------------------------------
# Old versions are not current results and do not feed the metrics
# ---------------------------------------------------------------------------


def test_old_version_is_not_listed_or_counted_anywhere(env) -> None:
    employee_id, _sicil = _user(env.app, role="personel")
    p1, p2 = _period(env), _period(env)
    current_p1 = _snapshot(env, period_id=p1, employee_id=employee_id, final=90.0, version=1, current=True)
    _snapshot(env, period_id=p2, employee_id=employee_id, final=40.0, version=1, current=False)
    current_p2 = _snapshot(env, period_id=p2, employee_id=employee_id, final=80.0, version=2, current=True)

    scorecards = _get(env, employee_id, "/api/mobile/performance/scorecards")
    assert sorted(scorecards["items"]) == sorted([str(current_p1), str(current_p2)])
    assert (scorecards["metrics"]["Karne"], scorecards["metrics"]["Ortalama"]) == ("2", "85/100")

    summary = _get(env, employee_id, "/api/mobile/performance/summary")
    assert (summary["metrics"]["Ortalama Puan"], summary["metrics"]["70 Altı Takip"]) == ("85/100", "0")

    reports = _get(env, employee_id, "/api/mobile/performance/reports")
    assert (reports["metrics"]["Karne"], reports["metrics"]["Ortalama"], reports["metrics"]["70 Altı"]) == ("2", "85/100", "0")

    risk = _get(env, employee_id, "/api/mobile/performance/risk-analysis")
    assert (risk["metrics"]["70 Altı"], risk["metrics"]["90 Üstü"], risk["items"]) == ("0", "1", ["risk-empty"])

    development = _get(env, employee_id, "/api/mobile/performance/development-suggestions")
    assert development["items"] == ["development-empty"]

    period_detail = _get(env, employee_id, f"/api/mobile/performance/periods/{p2}")
    assert period_detail["items"][1:] == [str(current_p2)]
    assert (period_detail["metrics"]["Ortalama"], period_detail["metrics"]["70 Altı"]) == ("80/100", "0")

    for result in (scorecards, summary, reports, risk, development, period_detail):
        assert result["status"] == 200 and result["dml"] == []


def test_a_period_with_only_an_old_version_has_no_current_result(env) -> None:
    employee_id, _sicil = _user(env.app, role="personel")
    period_id = _period(env)
    old_id = _snapshot(env, period_id=period_id, employee_id=employee_id, final=55.0, version=1, current=False)

    scorecards = _get(env, employee_id, "/api/mobile/performance/scorecards")
    assert (scorecards["items"], scorecards["metrics"]["Karne"]) == ([], "0")
    period_detail = _get(env, employee_id, f"/api/mobile/performance/periods/{period_id}")
    assert period_detail["items"][1:] == []
    assert (period_detail["metrics"]["Ortalama"], period_detail["metrics"]["70 Altı"]) == ("-", "0")
    assert _rows(env, employee_id) == [(old_id, 1, False)]  # the row itself is kept as history


def test_history_across_periods_stays_visible_one_current_row_per_period(env) -> None:
    """Imported past results and live results: each period keeps its current version."""
    employee_id, _sicil = _user(env.app, role="personel")
    p2024, p2025, p2026 = _period(env), _period(env), _period(env)
    current_2024 = _snapshot(env, period_id=p2024, employee_id=employee_id, final=71.0, version=1, current=True, source=_HISTORY_IMPORT)
    _snapshot(env, period_id=p2025, employee_id=employee_id, final=66.0, version=1, current=False, source=_HISTORY_IMPORT)
    current_2025 = _snapshot(env, period_id=p2025, employee_id=employee_id, final=74.0, version=2, current=True, source=_HISTORY_IMPORT)
    current_2026 = _snapshot(env, period_id=p2026, employee_id=employee_id, final=88.0, version=1, current=True)

    scorecards = _get(env, employee_id, "/api/mobile/performance/scorecards")
    assert sorted(scorecards["items"]) == sorted([str(current_2024), str(current_2025), str(current_2026)])
    assert (scorecards["metrics"]["Karne"], scorecards["metrics"]["Ortalama"]) == ("3", "77/100")  # int(mean(71, 74, 88))
    summary = _get(env, employee_id, "/api/mobile/performance/summary")
    assert (summary["metrics"]["Ortalama Puan"], summary["metrics"]["70 Altı Takip"]) == ("77/100", "0")


# ---------------------------------------------------------------------------
# Scope and authentication are unchanged
# ---------------------------------------------------------------------------


def test_employee_isolation_and_global_scope_are_unchanged(env) -> None:
    employee_id, _s1 = _user(env.app, role="personel")
    other_id, _s2 = _user(env.app, role="personel")
    period_id = _period(env)
    own_old = _snapshot(env, period_id=period_id, employee_id=employee_id, final=40.0, version=1, current=False)
    own_current = _snapshot(env, period_id=period_id, employee_id=employee_id, final=80.0, version=2, current=True)
    other_current = _snapshot(env, period_id=period_id, employee_id=other_id, final=65.0, version=1, current=True)

    assert _get(env, employee_id, "/api/mobile/performance/scorecards")["items"] == [str(own_current)]
    assert _get(env, other_id, "/api/mobile/performance/scorecards")["items"] == [str(other_current)]
    admin_items = _get(env, env.admin_id, "/api/mobile/performance/scorecards")["items"]
    assert sorted(admin_items) == sorted([str(own_current), str(other_current)])  # every employee, current versions
    assert str(own_old) not in admin_items


def test_missing_token_keeps_the_existing_session_error(env) -> None:
    result = _get(env, None, "/api/mobile/performance/scorecards")
    assert (result["status"], result["body"]) == (401, {"message": "Mobil oturum bulunamadı veya süresi doldu."})
    assert result["dml"] == []
