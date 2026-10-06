"""Contract: a refused evaluation-assignment request writes nothing (D-1).

``performance_v2_phase3_assignment`` (also served at faz4 / faz8 and the
``/performans`` aliases) used to build the full workspace context -- including
``_ensure_evaluation()``, which INSERTs a ``performance_evaluations`` row and
sets ``level_N_evaluator_id`` -- before checking that the caller is the
assignment's evaluator. The pending rows were then committed by the
interim-notes readiness check, so a refused request (302 back to the
dashboard) still persisted data. The ownership / status checks now run first;
the refusal response itself is unchanged.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event

PASSWORD = "AssignmentRefusalNoWriteTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "assignment_refusal_side_effect" / "dbs"
DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.I)
ASSIGNMENT_PATHS = (
    "/performance/v2/faz3/assignment/{id}",
    "/performans/v2/faz3/assignment/{id}",
    "/performance/v2/faz4/assignment/{id}",
    "/performans/v2/faz4/assignment/{id}",
    "/performance/v2/faz8/assignment/{id}",
    "/performans/v2/faz8/assignment/{id}",
)


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-assignment-refusal",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "assignment-refusal-first-login",
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


@pytest.fixture
def env(monkeypatch):
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformancePeriod, User
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    ids: dict[str, int] = {}
    with app.app_context():
        db.create_all()
        for key, role in (
            ("admin", "admin"),
            ("evaluator", "personel"),
            ("employee", "personel"),
            ("passive_employee", "personel"),
            ("intruder", "personel"),
        ):
            sicil = f"ARSE{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Gorev",
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
            title="Görev Reddi Dönemi",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.flush()
        for key, employee, status in (
            ("assignment", "employee", "bekliyor"),
            ("passive_assignment", "passive_employee", "pasif"),
        ):
            assignment = EvaluationAssignment(
                period_id=period.id,
                employee_id=ids[employee],
                evaluator_id=ids["evaluator"],
                manager_level=1,
                status=status,
            )
            db.session.add(assignment)
            db.session.flush()
            ids[key] = int(assignment.id)
        db.session.commit()
        # Complete interim-notes schema: the readiness check takes its no-DDL path.
        assert ensure_interim_notes_table()[0] is True
        ids["period"] = int(period.id)
    yield SimpleNamespace(app=app, ids=ids)
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


def _client(env, who):
    client = env.app.test_client()
    response = client.post(
        "/login", data={"sicil_or_email": f"ARSE{who.upper()}", "password": PASSWORD}
    )
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _dashboard(env) -> str:
    from flask import url_for

    with env.app.test_request_context():
        return url_for("main.performance_v2_phase3_dashboard")


def _capture_dml(env, call):
    from app.extensions import db

    statements: list[str] = []
    with env.app.app_context():
        engine = db.engine

    def _record(conn, cursor, statement, parameters, context, executemany):
        if DML.match(statement or ""):
            statements.append(" ".join(statement.split()[:3]))

    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return response, statements


def _evaluation_rows(env) -> list[tuple]:
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformanceEvaluationItem

    with env.app.app_context():
        rows: list[tuple] = [
            (e.employee_id, e.level_1_evaluator_id, e.level_1_general_comment)
            for e in PerformanceEvaluation.query.order_by(PerformanceEvaluation.id).all()
        ]
        rows.append(("items", PerformanceEvaluationItem.query.count()))
        db.session.remove()
        return rows


@pytest.mark.parametrize("template", ASSIGNMENT_PATHS)
def test_refused_get_by_non_evaluator_writes_nothing(env, template):
    client = _client(env, "intruder")
    response, dml = _capture_dml(env, lambda: client.get(template.format(id=env.ids["assignment"])))
    assert response.status_code == 302
    assert response.headers["Location"].endswith(_dashboard(env))
    assert dml == []
    assert _evaluation_rows(env) == [("items", 0)]


def test_refused_post_by_non_evaluator_writes_nothing(env):
    client = _client(env, "intruder")
    response, dml = _capture_dml(
        env,
        lambda: client.post(
            f"/performance/v2/faz3/assignment/{env.ids['assignment']}",
            data={"action": "save", "general_comment": "yetkisiz taslak"},
        ),
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(_dashboard(env))
    assert dml == []
    assert _evaluation_rows(env) == [("items", 0)]


@pytest.mark.parametrize("who", ["evaluator", "intruder"])
def test_passive_assignment_is_refused_for_everyone_without_writes(env, who):
    client = _client(env, who)
    response, dml = _capture_dml(
        env, lambda: client.get(f"/performance/v2/faz3/assignment/{env.ids['passive_assignment']}")
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(_dashboard(env))
    assert dml == []
    assert _evaluation_rows(env) == [("items", 0)]


@pytest.mark.parametrize("who", ["evaluator", "admin"])
def test_authorized_users_still_open_the_workspace(env, who):
    response = _client(env, who).get(f"/performance/v2/faz3/assignment/{env.ids['assignment']}")
    assert response.status_code == 200


def test_evaluator_save_still_persists_the_draft(env):
    client = _client(env, "evaluator")
    response = client.post(
        f"/performance/v2/faz3/assignment/{env.ids['assignment']}",
        data={"action": "save", "general_comment": "yetkili taslak"},
    )
    assert response.status_code == 302
    rows = _evaluation_rows(env)
    assert rows[0][:2] == (env.ids["employee"], env.ids["evaluator"])
    assert rows[0][2] == "yetkili taslak"


def test_missing_assignment_is_still_404(env):
    response = _client(env, "intruder").get("/performance/v2/faz3/assignment/987654")
    assert response.status_code == 404
