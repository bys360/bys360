"""The legacy P4 recommendation writers are retired; the canonical Phase-10 writer is the only one.

* POST /performance/scorecard/<id>/development-note no longer inserts the conflicting P4 row shape:
  it keeps its guards (login, manager role, object lookup, guidance permission) and answers with an
  explicit "not saved" message that points to the canonical development-guidance workflow.
* POST /performance/meeting-development/faz10/apply only seeds its module settings: it no longer
  creates or alters performance_development_recommendations and no longer inserts a demo row.
* The canonical writer keeps working after the retired actions ran.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, inspect, text

PASSWORD = "LegacyP4WritersRetiredTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "legacy_p4_writers_retired" / "dbs"
TABLE = "performance_development_recommendations"
CANONICAL_WORKFLOW = "/performance/meeting-development/faz10"
DDL_ON_TABLE = re.compile(r"^\s*(CREATE|ALTER|DROP)\b.*performance_development_recommendations", re.I | re.S)


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-legacy-p4-writers-retired",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "legacy-p4-writers-first-login",
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
def env(monkeypatch, install_development_recommendations_schema):
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod, User

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    ids: dict[str, int] = {}
    with app.app_context():
        db.create_all()
        install_development_recommendations_schema(db.engine)
        for key, role in (("baskan", "baskan"), ("owner", "personel"), ("intruder", "personel")):
            sicil = f"LP4W{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Eski",
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
            title="Eski Yazıcı Dönemi", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True
        )
        db.session.add(period)
        db.session.flush()
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=ids["owner"], final_total_100=60)
        db.session.add(evaluation)
        db.session.commit()
        ids["period"], ids["evaluation"] = int(period.id), int(evaluation.id)
        db.session.remove()
    return SimpleNamespace(app=app, ids=ids)


def _client(env, who):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": f"LP4W{who.upper()}", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _table_state(env):
    from app.extensions import db

    with env.app.app_context():
        columns = sorted(col["name"] for col in inspect(db.engine).get_columns(TABLE))
        rows = db.session.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar()
        db.session.remove()
    return columns, rows


def _watch_ddl(env, call):
    from app.extensions import db

    statements: list[str] = []
    with env.app.app_context():
        engine = db.engine

    def _on_sql(conn, cursor, statement, parameters, context, executemany):
        if DDL_ON_TABLE.match(statement or ""):
            statements.append(" ".join(statement.split())[:80])

    event.listen(engine, "before_cursor_execute", _on_sql)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", _on_sql)
    return response, statements


def _flashes(client) -> list[str]:
    with client.session_transaction() as session:
        return [message for _category, message in session.get("_flashes", [])]


def test_scorecard_development_note_is_not_persisted_and_points_to_the_canonical_workflow(env):
    before = _table_state(env)
    client = _client(env, "baskan")
    response, ddl = _watch_ddl(
        env,
        lambda: client.post(
            f"/performance/scorecard/{env.ids['evaluation']}/development-note",
            data={"recommendation_type": "below_70_development", "title": "Eski not", "recommendation_text": "Eski karne notu metni", "is_required": "on"},
        ),
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(CANONICAL_WORKFLOW)
    assert ddl == []
    assert _table_state(env) == before
    messages = _flashes(client)
    assert any("kaydedilmedi" in message for message in messages), messages


def test_scorecard_development_note_keeps_its_guards(env):
    before = _table_state(env)
    assert _client(env, "intruder").post(
        f"/performance/scorecard/{env.ids['evaluation']}/development-note", data={"recommendation_text": "x"}
    ).status_code == 403
    assert _client(env, "baskan").post("/performance/scorecard/987654/development-note", data={"recommendation_text": "x"}).status_code == 404
    assert _table_state(env) == before


def test_faz10_apply_seeds_settings_without_touching_the_recommendation_table(env):
    from app.extensions import db
    from app.models import ModuleSetting

    before = _table_state(env)
    client = _client(env, "baskan")
    response, ddl = _watch_ddl(env, lambda: client.post("/performance/meeting-development/faz10/apply"))
    assert response.status_code == 302
    assert ddl == []
    assert _table_state(env) == before
    with env.app.app_context():
        keys = {row.setting_key for row in ModuleSetting.query.filter_by(module_key="performance").all()}
        db.session.remove()
    assert "performance_development_recommendation_required_below_70" in keys


def test_canonical_writer_still_works_after_the_retired_actions_ran(env):
    client = _client(env, "baskan")
    client.post(f"/performance/scorecard/{env.ids['evaluation']}/development-note", data={"recommendation_text": "eski"})
    client.post("/performance/meeting-development/faz10/apply")
    columns, rows = _table_state(env)
    response = client.post(
        CANONICAL_WORKFLOW,
        data={
            "employee_id": env.ids["owner"],
            "period_id": env.ids["period"],
            "recommendation_type": "improvement_plan",
            "recommendation_text": "Kanonik yazıcı ile kaydedilen gelişim planı",
        },
    )
    assert response.status_code == 302
    assert _table_state(env) == (columns, rows + 1)
    assert len(columns) == 47
