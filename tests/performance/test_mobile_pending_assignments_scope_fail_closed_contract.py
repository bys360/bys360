"""BYS360 PERFORMANCE POST-OVERNIGHT P2: a failing scope helper never widens the mobile pending tasks.

Helper: app/api/mobile/performance_routes._v2852_pending_assignments(user), scoped by
_v2822_assignment_query(user) (own evaluator tasks unless a global mobile role).
Consumers:

- GET /api/mobile/performance/reminders (task items: employee name, period, due label)
- GET /api/mobile/performance/full-feature-summary ("Bekleyen Görev" count)

Verified at 2c7a46a7665e3ff343c5f08db33a4ae188a051fc: the helper wrapped the scope
call in ``except Exception`` and fell back to the unscoped EvaluationAssignment.query.
A failing scope helper (RuntimeError / ValueError / AttributeError) showed person A
the 3 institution-wide tasks (person B's two included) in the reminders and
"Bekleyen Görev: 3" in the summary. It was also reached without any code fault:
a single failed refresh of the user row (the summary's earlier safe reads roll back
and expire the user; a dropped connection on the refresh SELECT) returned the
institution-wide count.

Since this change the fallback is gone (the P0.2Y precedent,
tests/performance/test_mobile_snapshot_scope_fail_closed_contract.py): the helper is
the only scope source, and a helper error reaches the app's existing handler
(rollback, HTTP 500 "Sistem Hatası" page; the app-wide 5xx security event is written
to audit_logs) instead of returning somebody else's tasks. Execution-time database
errors keep the existing safe read helper's behavior (no rows).

Real Flask app, real mobile Bearer auth; file-backed SQLite test database only.
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
from sqlalchemy.exc import OperationalError

_ROUTES_MODULE = "app.api.mobile.performance_routes"
_PASSWORD = "TestPendingScope1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_post_overnight_p2_pending_scope")
_REMINDERS = "/api/mobile/performance/reminders"
_SUMMARY = "/api/mobile/performance/full-feature-summary"
_counter = 0


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-post-overnight-p2-pending-scope",
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
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p2p_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
            sicil_no=f"P2P{n:06d}",
            email=f"p2-pending-scope-{n}@bys360.test",
            ad="P2Pending",
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
    """Person A (one own open task), person B (two open tasks) and an admin (global mobile role)."""
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformancePeriod

    flask_app = _make_app(monkeypatch)
    person_a = _user(flask_app, role="personel")
    person_b = _user(flask_app, role="personel")
    employee = _user(flask_app, role="personel")
    admin_id = _user(flask_app, role="admin")
    with flask_app.app_context():
        period = PerformancePeriod(title=f"P2 Bekleyen Dönem {_next()}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.flush()
        for evaluator, level in ((person_a, 1), (person_b, 1), (person_b, 2)):
            db.session.add(EvaluationAssignment(period_id=period.id, employee_id=employee, evaluator_id=evaluator, manager_level=level, status="bekliyor"))
        db.session.commit()
        task_ids = {
            owner: sorted(int(row.id) for row in EvaluationAssignment.query.filter_by(evaluator_id=owner).all())
            for owner in (person_a, person_b)
        }
    return SimpleNamespace(app=flask_app, person_a=person_a, person_b=person_b, admin_id=admin_id, task_ids=task_ids)


def _get(env: SimpleNamespace, user_id: int | None, path: str) -> dict[str, Any]:
    """Real mobile GET: status, content type, metrics by title, item ids, every DML statement."""
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
        "item_ids": sorted(int(item.get("id")) for item in body.get("items", []) if str(item.get("id", "")).isdigit()),
        "body": body,
        "dml": dml,
    }


def _assignments(env: SimpleNamespace) -> list[tuple[Any, ...]]:
    from app.extensions import db

    with env.app.app_context():
        rows = [tuple(r) for r in db.session.execute(text("SELECT * FROM evaluation_assignments ORDER BY id")).all()]
        db.session.remove()
    return rows


def _raise(error: Exception):
    def _helper(user):  # noqa: ARG001
        raise error

    return _helper


# ---------------------------------------------------------------------------
# Normal path: unchanged
# ---------------------------------------------------------------------------


def test_each_user_sees_only_own_pending_tasks(env) -> None:
    for user_id, own in ((env.person_a, env.task_ids[env.person_a]), (env.person_b, env.task_ids[env.person_b])):
        reminders = _get(env, user_id, _REMINDERS)
        assert (reminders["status"], reminders["item_ids"], reminders["metrics"]["Bekleyen"]) == (200, own, str(len(own)))
        summary = _get(env, user_id, _SUMMARY)
        assert (summary["status"], summary["metrics"]["Bekleyen Görev"]) == (200, str(len(own)))
        assert reminders["dml"] == [] and summary["dml"] == []


def test_global_role_keeps_its_institution_scope(env) -> None:
    every_task = sorted(env.task_ids[env.person_a] + env.task_ids[env.person_b])
    reminders = _get(env, env.admin_id, _REMINDERS)
    assert (reminders["status"], reminders["item_ids"], reminders["metrics"]["Bekleyen"]) == (200, every_task, "3")
    assert _get(env, env.admin_id, _SUMMARY)["metrics"]["Bekleyen Görev"] == "3"


def test_missing_token_keeps_the_existing_session_error(env) -> None:
    for path in (_REMINDERS, _SUMMARY):
        result = _get(env, None, path)
        assert (result["status"], result["body"]) == (401, {"message": "Mobil oturum bulunamadı veya süresi doldu."})
        assert result["dml"] == []


# ---------------------------------------------------------------------------
# Scope helper failure: the existing error contract, never wider data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [_REMINDERS, _SUMMARY], ids=["reminders", "full_feature_summary"])
@pytest.mark.parametrize(
    "error",
    [RuntimeError("simulated scope helper failure"), ValueError("simulated scope helper failure"), AttributeError("'NoneType' object has no attribute 'id'")],
    ids=["runtime_error", "value_error", "attribute_error"],
)
def test_scope_helper_failure_uses_the_existing_error_page_without_data(env, monkeypatch, path, error) -> None:
    monkeypatch.setattr(importlib.import_module(_ROUTES_MODULE), "_v2822_assignment_query", _raise(error))
    before = _assignments(env)
    for _attempt in range(2):  # deterministic on repeat
        result = _get(env, env.person_a, path)
        assert result["status"] == 500
        assert result["content_type"].startswith("text/html")
        assert "Sistem Hatası" in result["text"]
        assert result["body"] == {} and result["metrics"] == {} and result["item_ids"] == []
        assert result["dml"] == ["INSERT INTO audit_logs"]  # the app-wide 5xx security event only
    assert _assignments(env) == before


@pytest.mark.parametrize("path", [_REMINDERS, _SUMMARY], ids=["reminders", "full_feature_summary"])
def test_transient_error_refreshing_the_user_never_widens_the_scope(env, monkeypatch, path) -> None:
    """The fault-free path: the endpoints' safe read helpers roll back and so expire the
    user, and the scope helper's refresh SELECT hits a dropped connection once. The real
    helper runs; the wrapper only sets up those two preconditions deterministically.
    Before this change the error fell back to every task ("Bekleyen Görev: 3" for A)."""
    from app.extensions import db

    routes = importlib.import_module(_ROUTES_MODULE)
    real_helper = routes._v2822_assignment_query
    with env.app.app_context():
        engine = db.engine
    armed: list[bool] = []

    def _fail_once(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if armed and "from users" in statement.lower():
            armed.clear()
            raise OperationalError(statement, parameters, Exception("simulated dropped connection"))

    def _helper(user):
        db.session.expire(user)
        armed.append(True)
        return real_helper(user)

    monkeypatch.setattr(routes, "_v2822_assignment_query", _helper)
    before = _assignments(env)
    event.listen(engine, "before_cursor_execute", _fail_once)
    try:
        result = _get(env, env.person_a, path)
    finally:
        event.remove(engine, "before_cursor_execute", _fail_once)
    assert armed == []  # the refresh SELECT ran inside the real helper and failed once
    assert result["status"] == 500
    assert "Veritabanı Hatası" in result["text"]  # the app's existing database-error page
    assert result["body"] == {} and result["metrics"] == {} and result["item_ids"] == []
    assert result["dml"] == ["INSERT INTO audit_logs"]
    assert _assignments(env) == before


def test_database_error_at_execution_keeps_the_existing_safe_empty_result(env) -> None:
    """A real driver error on the task SELECT: the scoped query is still used (nothing
    widens) and the existing safe read helper reports no rows."""
    from app.extensions import db

    with env.app.app_context():
        engine = db.engine

    def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if "from evaluation_assignments" in statement.lower():
            raise OperationalError(statement, parameters, Exception("simulated database outage"))

    event.listen(engine, "before_cursor_execute", _fail)
    try:
        reminders = _get(env, env.person_a, _REMINDERS)
        summary = _get(env, env.person_a, _SUMMARY)
    finally:
        event.remove(engine, "before_cursor_execute", _fail)
    assert (reminders["status"], reminders["item_ids"], reminders["metrics"]["Bekleyen"]) == (200, [], "0")
    assert (summary["status"], summary["metrics"]["Bekleyen Görev"]) == (200, "0")
    assert reminders["dml"] == [] and summary["dml"] == []
