"""BYS360 PERFORMANCE P0.2Y: a failing scope helper never widens mobile performance data.

Endpoints and their scope helpers (app/api/mobile/services/performance_query_helpers.py,
resolved from app/api/mobile/performance_routes.py at request time):

- GET /api/mobile/performance/full-feature-summary
  (performance_summary_risk_route_services.phase3c_mobile_performance_full_feature_summary_service)
- GET /api/mobile/performance/reports
  (performance_routes._bys360_legacy_mobile_performance_reports)

_snapshot_query_for(user): current snapshots (P0.2W), own rows unless a global
mobile role. _assignment_query_for(user): own evaluator tasks unless global.

Verified at 036214250d583c8d7092c27b7600a104a7d0bd65: both endpoints wrapped the
helper calls in ``except Exception`` and fell back to the unscoped
PerformanceResultSnapshot.query (and EvaluationAssignment.query in the reports).
The branch is not reached by a real database outage (the helpers only build
queries; P0.2X), but any error there turned an employee's result into
institution-wide numbers without the current-version filter.

Since P0.2Y the fallbacks are gone: the helpers are the only scope source, and a
helper error reaches the app's existing handler (rollback, HTTP 500 "Sistem
Hatası" page; the app-wide 5xx security event is written to audit_logs) instead
of returning somebody else's data. Execution-time database errors keep the
existing safe read helpers' behavior (0 / "-"). Publication visibility is not
changed (P0.2V CASE C).

Real Flask app, real mobile Bearer auth; file-backed SQLite test database only.
"""
from __future__ import annotations

import importlib
import tempfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

_ROUTES_MODULE = "app.api.mobile.performance_routes"
_PASSWORD = "MobileSnapshotScope1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02y_snapshot_scope")
_SUMMARY = "/api/mobile/performance/full-feature-summary"
_REPORTS = "/api/mobile/performance/reports"
_counter = 0


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p02y-snapshot-scope",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02y_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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


def _user(flask_app, *, role: str) -> int:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        n = _next()
        user = User(
            sicil_no=f"P2Y{n:06d}",
            email=f"p02y-scope-{n}@bys360.test",
            ad="P02Y",
            soyad=f"Kullanici{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return int(user.id)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Person A (own result 20, one task), person B (current 100, old version 10,
    two tasks) and an admin (global mobile role)."""
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformancePeriod, PerformanceResultSnapshot

    flask_app = _make_app(monkeypatch)
    person_a = _user(flask_app, role="personel")
    person_b = _user(flask_app, role="personel")
    employee = _user(flask_app, role="personel")
    admin_id = _user(flask_app, role="admin")
    with flask_app.app_context():
        period = PerformancePeriod(title=f"P0.2Y Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.flush()
        for owner, final, version, current in ((person_a, 20.0, 1, True), (person_b, 10.0, 1, False), (person_b, 100.0, 2, True)):
            db.session.add(
                PerformanceResultSnapshot(
                    period_id=period.id, employee_id=owner, employee_name_snapshot="Snapshot Personel", sicil_no_snapshot="SNAP",
                    final_total_100=final, published_at=datetime(2026, 4, 1), source_type="system_published", version_no=version, is_current=current,
                )
            )
        for evaluator, level in ((person_a, 1), (person_b, 1), (person_b, 2)):
            db.session.add(EvaluationAssignment(period_id=period.id, employee_id=employee, evaluator_id=evaluator, manager_level=level, status="bekliyor"))
        db.session.commit()
    return SimpleNamespace(app=flask_app, person_a=person_a, person_b=person_b, admin_id=admin_id)


def _get(env: SimpleNamespace, user_id: int | None, path: str) -> dict[str, Any]:
    """Real mobile GET: status, content type, metrics by title, every DML statement."""
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
            dml.append(" ".join(statement.split()[:3]))

    with env.app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = env.app.test_client().get(path, headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    body = response.get_json(silent=True) or {}
    return {
        "status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "text": response.get_data(as_text=True),
        "metrics": {metric.get("title"): metric.get("value") for metric in body.get("metrics", [])},
        "body": body,
        "dml": dml,
    }


def _metrics(result: dict[str, Any], *titles: str) -> tuple[Any, ...]:
    return tuple(result["metrics"].get(title) for title in titles)


def _rows(env: SimpleNamespace) -> dict[str, list[tuple[Any, ...]]]:
    from app.extensions import db

    with env.app.app_context():
        state = {
            "snapshots": [tuple(r) for r in db.session.execute(text("SELECT * FROM performance_result_snapshots ORDER BY id")).all()],
            "assignments": [tuple(r) for r in db.session.execute(text("SELECT * FROM evaluation_assignments ORDER BY id")).all()],
        }
        db.session.remove()
    return state


def _raise_scope_error(user):
    raise RuntimeError("simulated scope helper failure")


# ---------------------------------------------------------------------------
# Normal path: unchanged
# ---------------------------------------------------------------------------


def test_employee_sees_only_own_current_data(env) -> None:
    summary = _get(env, env.person_a, _SUMMARY)
    assert _metrics(summary, "Karne", "Ortalama", "70 Altı") == ("1", "20/100", "1")
    reports = _get(env, env.person_a, _REPORTS)
    assert _metrics(reports, "Görev", "Karne", "Ortalama", "70 Altı") == ("1", "1", "20/100", "1")
    for result in (summary, reports):
        assert result["status"] == 200 and result["dml"] == []


def test_global_role_keeps_its_current_institution_scope(env) -> None:
    summary = _get(env, env.admin_id, _SUMMARY)
    assert _metrics(summary, "Karne", "Ortalama", "70 Altı") == ("2", "60/100", "1")  # B's old version 10 is not counted
    reports = _get(env, env.admin_id, _REPORTS)
    assert _metrics(reports, "Görev", "Karne", "Ortalama", "70 Altı") == ("3", "2", "60/100", "1")
    for result in (summary, reports):
        assert result["status"] == 200 and result["dml"] == []


def test_missing_token_keeps_the_existing_session_error(env) -> None:
    for path in (_SUMMARY, _REPORTS):
        result = _get(env, None, path)
        assert (result["status"], result["body"]) == (401, {"message": "Mobil oturum bulunamadı veya süresi doldu."})
        assert result["dml"] == []


# ---------------------------------------------------------------------------
# Scope helper failure: the existing error contract, never wider data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [_SUMMARY, _REPORTS], ids=["full_feature_summary", "reports"])
@pytest.mark.parametrize("helper", ["_snapshot_query_for", "_assignment_query_for"])
def test_scope_helper_failure_uses_the_existing_error_page_without_data(env, monkeypatch, path, helper) -> None:
    monkeypatch.setattr(importlib.import_module(_ROUTES_MODULE), helper, _raise_scope_error)
    before = _rows(env)
    for _attempt in range(2):  # deterministic on repeat
        result = _get(env, env.person_a, path)
        assert result["status"] == 500
        assert result["content_type"].startswith("text/html")
        assert "Sistem Hatası" in result["text"]
        assert result["body"] == {} and result["metrics"] == {}
        assert result["dml"] == ["INSERT INTO audit_logs"]  # the app-wide 5xx security event only
    assert _rows(env) == before


def test_database_error_at_execution_keeps_the_existing_safe_empty_result(env) -> None:
    """A real driver error on the snapshot and task SELECTs: the scoped queries are
    still used (nothing widens) and the existing safe read helpers report 0 / "-"."""
    from app.extensions import db

    with env.app.app_context():
        engine = db.engine

    def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        lowered = statement.lower()
        if "from performance_result_snapshots" in lowered or "from evaluation_assignments" in lowered:
            raise OperationalError(statement, parameters, Exception("simulated database outage"))

    event.listen(engine, "before_cursor_execute", _fail)
    try:
        summary = _get(env, env.person_a, _SUMMARY)
        reports = _get(env, env.person_a, _REPORTS)
    finally:
        event.remove(engine, "before_cursor_execute", _fail)
    assert (summary["status"], _metrics(summary, "Karne", "Ortalama", "70 Altı")) == (200, ("0", "-", "0"))
    assert (reports["status"], _metrics(reports, "Görev", "Karne", "Ortalama", "70 Altı")) == (200, ("0", "0", "-", "0"))
    assert summary["dml"] == [] and reports["dml"] == []
