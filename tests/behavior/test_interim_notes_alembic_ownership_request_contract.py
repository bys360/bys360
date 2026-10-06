"""performance_interim_notes is Alembic-owned: request paths never create, alter or index it.

* With the migrated (canonical) schema, every request path that reads or writes
  interim notes executes zero DDL -- on the first, second and tenth request.
* With the table missing or an unmigrated legacy shape, the same requests do not
  repair it; they keep their existing read-only error contract.
* The former creators (runtime readiness helper, mobile fallback, mobile
  note-scorecard column retrofit, P2 apply helper) can no longer create anything.
* The readiness helper's existing commit boundary is unchanged: pending session
  work is still committed (G3-B owns that boundary; this slice does not move it).
"""

from __future__ import annotations

import re
import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, inspect, text

PASSWORD = "InterimNotesOwnershipTest1!"
TABLE = "performance_interim_notes"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "interim_notes_alembic_ownership" / "dbs"
DDL = re.compile(r"^\s*(CREATE|ALTER|DROP)\b", re.I)


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-interim-notes-alembic-ownership",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "interim-notes-first-login",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "DATABASE_URL": uri,
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    return app


def _build(monkeypatch, schema: str, install_interim_notes_schema):
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod, User

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    ids: dict[str, int] = {}
    with app.app_context():
        db.create_all()
        if schema == "canonical":
            install_interim_notes_schema(db.engine)
        elif schema == "legacy_mobile_shape":
            db.session.execute(
                text(
                    f"CREATE TABLE {TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, period_id INTEGER NULL, "
                    "employee_id INTEGER NULL, employee_user_id INTEGER NULL, manager_id INTEGER NULL, created_by INTEGER NULL, "
                    "created_by_id INTEGER NULL, note_type VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem', title VARCHAR(255) NULL, "
                    "note TEXT NULL, note_body TEXT NULL, visibility_level VARCHAR(80) NULL DEFAULT 'manager_scope', "
                    "remind_during_scoring BOOLEAN DEFAULT TRUE, include_in_scorecard BOOLEAN DEFAULT FALSE, "
                    "is_active BOOLEAN DEFAULT TRUE, occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP, "
                    "created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            db.session.commit()
        for key, role in (("admin", "admin"), ("evaluator", "personel"), ("employee", "personel")):
            sicil = f"IANO{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Not",
                soyad=key.title(),
                role=role,
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[key] = int(user.id)
        period = PerformancePeriod(
            title="Not Sahipliği Dönemi",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.flush()
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=ids["employee"])
        assignment = EvaluationAssignment(
            period_id=period.id,
            employee_id=ids["employee"],
            evaluator_id=ids["evaluator"],
            manager_level=1,
            status="bekliyor",
        )
        db.session.add_all([evaluation, assignment])
        db.session.commit()
        ids.update(
            period=int(period.id), evaluation=int(evaluation.id), assignment=int(assignment.id)
        )
    return SimpleNamespace(app=app, ids=ids, db_file=db_file)


@pytest.fixture
def make_env(monkeypatch, install_interim_notes_schema):
    from app.extensions import db

    built = []

    def _make(schema: str):
        env = _build(monkeypatch, schema, install_interim_notes_schema)
        built.append(env)
        return env

    yield _make
    for env in built:
        with env.app.app_context():
            db.session.remove()
            db.engine.dispose()
        env.db_file.unlink(missing_ok=True)


def _web(env, who):
    client = env.app.test_client()
    response = client.post(
        "/login", data={"sicil_or_email": f"IANO{who.upper()}", "password": PASSWORD}
    )
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _mobile(env, who):
    client = env.app.test_client()
    response = client.post(
        "/api/mobile/auth/login", json={"username": f"IANO{who.upper()}", "password": PASSWORD}
    )
    token = (response.get_json(silent=True) or {}).get("access_token")
    assert response.status_code == 200 and token
    return client, {"Authorization": f"Bearer {token}"}


class _Capture:
    """Counts DDL statements and DDL-carrying commits on the app engine."""

    def __init__(self, env):
        from app.extensions import db

        with env.app.app_context():
            self.engine = db.engine
        self.ddl: list[str] = []
        self.schema_commits = 0

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on_exec)
        event.listen(self.engine, "commit", self._on_commit)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on_exec)
        event.remove(self.engine, "commit", self._on_commit)

    def _on_exec(self, conn, cursor, statement, parameters, context, executemany):
        if DDL.match(statement or ""):
            self.ddl.append(" ".join(statement.split())[:120])
            conn.info["g3a_ddl_txn"] = True

    def _on_commit(self, conn):
        if conn.info.pop("g3a_ddl_txn", False):
            self.schema_commits += 1


def _request_paths(env):
    ids = env.ids
    return {
        "web v2 faz3 assignment": lambda: _web(env, "evaluator").get(
            f"/performance/v2/faz3/assignment/{ids['assignment']}"
        ),
        "web /performans alias assignment": lambda: _web(env, "evaluator").get(
            f"/performans/v2/faz3/assignment/{ids['assignment']}"
        ),
        "web faz4 assignment": lambda: _web(env, "evaluator").get(
            f"/performance/v2/faz4/assignment/{ids['assignment']}"
        ),
        "web faz8 assignment": lambda: _web(env, "evaluator").get(
            f"/performance/v2/faz8/assignment/{ids['assignment']}"
        ),
        "web scorecard": lambda: _web(env, "admin").get(
            f"/performance/scorecard/{ids['evaluation']}"
        ),
        "web scorecard pdf": lambda: _web(env, "admin").get(
            f"/performance/scorecard/{ids['evaluation']}/pdf"
        ),
        "web interim-notes create": lambda: _web(env, "admin").post(
            "/performance/interim-notes/create",
            data={
                "employee_id": ids["employee"],
                "period_id": ids["period"],
                "note_type": "basari",
                "note": "web notu",
            },
        ),
        "mobile in-period-notes read": lambda: (
            lambda c, h: c.get("/api/mobile/performance/in-period-notes/v2", headers=h)
        )(*_mobile(env, "employee")),
        "mobile in-period-notes write": lambda: (
            lambda c, h: c.post(
                "/api/mobile/performance/in-period-notes/v2", headers=h, json={"note": "mobil not"}
            )
        )(*_mobile(env, "employee")),
        "mobile note-scorecard read": lambda: (
            lambda c, h: c.get("/api/mobile/performance/note-scorecard", headers=h)
        )(*_mobile(env, "employee")),
    }


PATHS = sorted(_request_paths(SimpleNamespace(ids={})).keys())


def _columns(env) -> dict[str, Any]:
    from app.extensions import db

    with env.app.app_context():
        insp = inspect(db.engine)
        return {c["name"]: c for c in insp.get_columns(TABLE)} if insp.has_table(TABLE) else {}


def _indexes(env) -> set[str]:
    from app.extensions import db

    with env.app.app_context():
        insp = inspect(db.engine)
        return {str(ix["name"]) for ix in insp.get_indexes(TABLE)} if insp.has_table(TABLE) else set()


def _note_bodies(env) -> list[str]:
    from app.extensions import db

    with env.app.app_context():
        rows = (
            db.session.execute(text(f"SELECT note_body FROM {TABLE} ORDER BY id")).scalars().all()
        )
        db.session.remove()
        return list(rows)


@pytest.mark.parametrize("path", PATHS)
def test_canonical_schema_request_executes_no_ddl(make_env, path):
    env = make_env("canonical")
    with _Capture(env) as capture:
        response = _request_paths(env)[path]()
    assert response.status_code < 500
    assert capture.ddl == []
    assert capture.schema_commits == 0


@pytest.mark.parametrize(
    "path",
    [
        "web v2 faz3 assignment",
        "mobile in-period-notes read",
        "mobile note-scorecard read",
        "web scorecard",
    ],
)
def test_repeated_requests_never_execute_ddl(make_env, path):
    env = make_env("canonical")
    paths = _request_paths(env)
    with _Capture(env) as capture:
        statuses = [paths[path]().status_code for _ in range(10)]
    assert all(status < 500 for status in statuses)
    assert capture.ddl == []


def test_writes_persist_on_the_migrated_table(make_env):
    env = make_env("canonical")
    paths = _request_paths(env)
    assert paths["web interim-notes create"]().status_code == 302
    response = paths["mobile in-period-notes write"]()
    assert response.status_code == 200 and response.get_json()["ok"] is True
    assert _note_bodies(env) == ["web notu", "mobil not"]


@pytest.mark.parametrize("path", PATHS)
def test_missing_table_is_not_created_by_any_request(make_env, path):
    env = make_env("absent")
    with _Capture(env) as capture:
        response = _request_paths(env)[path]()
    assert capture.ddl == []
    assert _columns(env) == {}
    if path == "mobile in-period-notes write":
        # Existing error contract of the mobile writer when the INSERT cannot run.
        assert response.status_code == 500
        assert (
            response.get_json()["message"] == "Dönem içi not kaydedilemedi. Lütfen tekrar deneyin."
        )
    elif path == "web interim-notes create":
        assert response.status_code == 302
    else:
        assert response.status_code < 500


@pytest.mark.parametrize("path", PATHS)
def test_unmigrated_legacy_shape_is_not_retrofitted_by_any_request(make_env, path):
    env = make_env("legacy_mobile_shape")
    before_columns, before_indexes = list(_columns(env)), _indexes(env)
    with _Capture(env) as capture:
        _request_paths(env)[path]()
    assert capture.ddl == []
    assert list(_columns(env)) == before_columns
    assert _indexes(env) == before_indexes


def test_runtime_readiness_helper_reports_missing_table_without_creating_it(make_env):
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    env = make_env("absent")
    with env.app.app_context(), _Capture(env) as capture:
        ready, warnings = ensure_interim_notes_table()
    assert ready is False and warnings
    assert capture.ddl == []
    assert _columns(env) == {}


def test_runtime_readiness_helper_reports_ready_for_migrated_table(make_env):
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    env = make_env("canonical")
    with env.app.app_context(), _Capture(env) as capture:
        assert ensure_interim_notes_table() == (True, [])
    assert capture.ddl == []


def test_mobile_helper_cannot_create_the_table_even_when_the_readiness_check_raises(
    make_env, monkeypatch
):
    import app.services.performance.interim_notes_runtime as runtime
    from app.api.mobile.performance_routes import _v2853_ensure_interim_notes_table

    env = make_env("absent")

    def _raise():
        raise RuntimeError("readiness check failed")

    monkeypatch.setattr(runtime, "ensure_interim_notes_table", _raise)
    with env.app.app_context(), _Capture(env) as capture:
        assert _v2853_ensure_interim_notes_table() is False
    assert capture.ddl == []
    assert _columns(env) == {}


def test_p2_apply_helper_cannot_create_the_table(make_env):
    from app.services.performance.meeting_p2_archive_notes import ensure_interim_notes_table

    env = make_env("absent")
    with env.app.app_context(), _Capture(env) as capture:
        ready, warnings = ensure_interim_notes_table()
    assert ready is False and warnings
    assert [s for s in capture.ddl if TABLE in s] == []
    assert _columns(env) == {}


@pytest.mark.parametrize("schema", ["canonical", "absent"])
def test_readiness_helper_still_commits_pending_session_work(make_env, schema):
    """Unchanged G3-B boundary: callers' pending work is committed by the helper, as before."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    env = make_env(schema)
    with env.app.app_context():
        db.session.add(
            PerformanceEvaluation(period_id=env.ids["period"], employee_id=env.ids["admin"])
        )
        ensure_interim_notes_table()
        db.session.rollback()  # nothing left to roll back if the helper committed
        persisted = PerformanceEvaluation.query.filter_by(employee_id=env.ids["admin"]).count()
        db.session.remove()
    assert persisted == 1
