"""Contract: ordinary requests never alter the schema (schema / runtime DDL waves 1-2).

Raw-SQL tables that are not owned by Alembic are verified by request code
(app.services.runtime_schema.require, read-only) and created only by the
explicit ``flask runtime-schema provision`` maintenance command. Before wave 1
these GET pages ran CREATE TABLE / CREATE INDEX on every request.
"""
from __future__ import annotations

import ast
import re
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event, inspect

REPO = Path(__file__).resolve().parents[2]
DDL = re.compile(r"^\s*(CREATE\s+(UNIQUE\s+)?INDEX|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+)", re.I)
PASSWORD = "RuntimeSchemaWave1Test!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "runtime_schema_wave1" / "dbs"

# GET pages that executed DDL on every request before wave 1 (dynamic probe, 2026-09-28).
FORMER_DDL_GET_PAGES = (
    "/performance/v2-1-2-categories",
    "/performance/v2-1-3-personnel-category-card",
    "/performance/v2-1-6-category-period-integration",
    "/performans/donem-yonetim-merkezi",
    "/performance/meeting-development",
    "/performance/feedback-aftercare",
    "/performance/feedback-followup",
    "/performance/interim-notes",
    "/ai-agent/knowledge",
    # development-guidance pages (overnight wave 2)
    "/performance/meeting-development/faz10",
    "/performans/toplanti-gelistirme/faz10-gelisim-rehberi",
)
RECOMMENDATIONS_MIGRATION = REPO / "migrations" / "versions" / "29fee38a97e1_adopt_performance_development_.py"


def _make_app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "FLASK_ENV": "testing", "SECRET_KEY": "test-secret-key-runtime-schema-wave1",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "runtime-schema-wave1-first-login", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false", "DATABASE_URL": uri,
        "MAIL_SUPPRESS_SEND": "true", "SCHEDULER_ENABLED": "false", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import User
    from app.services import runtime_schema

    runtime_schema.forget_verified()
    with app.app_context():
        db.create_all()
        admin = User(sicil_no="RSW1ADMIN", email="rsw1-admin@example.gov.tr", ad="Runtime", soyad="Schema",
                     role="admin", is_active=True, must_change_password=False, must_set_security_question=False)
        admin.set_password(PASSWORD)
        db.session.add(admin)
        db.session.commit()
    return app


def _login(client):
    response = client.post("/login", data={"sicil_or_email": "RSW1ADMIN", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")


def _get_capturing_ddl(app, client, path):
    from app.extensions import db

    statements: list[str] = []
    with app.app_context():
        engine = db.engine

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if DDL.match(statement or ""):
            statements.append(" ".join(statement.split())[:160])

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        response = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    return response, statements


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def provisioned_app(app):
    from app.services import runtime_schema

    with app.app_context():
        results = runtime_schema.provision_all()
    assert {name: after for name, (_, after) in results.items() if after} == {}
    return app


@pytest.mark.parametrize("path", FORMER_DDL_GET_PAGES)
def test_get_page_executes_no_ddl_when_schema_is_provisioned(provisioned_app, path):
    client = provisioned_app.test_client()
    _login(client)
    response, ddl = _get_capturing_ddl(provisioned_app, client, path)
    assert ddl == [], f"{path} altered the schema: {ddl}"
    assert response.status_code != 503


def test_missing_runtime_schema_fails_closed_without_creating_it(app):
    from app.extensions import db

    client = app.test_client()
    _login(client)
    response, ddl = _get_capturing_ddl(app, client, "/performance/v2-1-2-categories")
    assert response.status_code == 503
    assert ddl == []
    with app.app_context():
        assert not inspect(db.engine).has_table("performance_personnel_categories")



def test_missing_recommendation_table_is_reported_without_creating_it(provisioned_app):
    from app.extensions import db
    from app.services import runtime_schema

    with provisioned_app.app_context():
        db.session.execute(db.text("DROP TABLE performance_development_recommendations"))
        db.session.commit()
        runtime_schema.forget_verified()
    client = provisioned_app.test_client()
    _login(client)
    response, ddl = _get_capturing_ddl(provisioned_app, client, "/performance/meeting-development/faz10")
    assert ddl == []
    assert response.status_code == 200
    with provisioned_app.app_context():
        assert not inspect(db.engine).has_table("performance_development_recommendations")


def test_recommendation_check_matches_the_alembic_migration():
    import importlib.util

    from app.performance.phase10_development_guidance_ui import DEVELOPMENT_RECOMMENDATIONS_SCHEMA

    spec = importlib.util.spec_from_file_location("migration_29fee38a97e1", RECOMMENDATIONS_MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    checked = {column for _, column in DEVELOPMENT_RECOMMENDATIONS_SCHEMA.columns}
    assert checked | {"id"} == set(migration._EXPECTED_COLUMNS)

def test_require_is_read_only_and_caches_a_positive_check(provisioned_app):
    from app.extensions import db
    from app.services import runtime_schema
    from app.services.performance.meeting_development import MEETING_FOUNDATION_SCHEMA

    with provisioned_app.app_context():
        runtime_schema.forget_verified()
        executed: list[str] = []

        def _count(conn, cursor, statement, parameters, context, executemany):
            executed.append(statement)

        event.listen(db.engine, "before_cursor_execute", _count)
        try:
            runtime_schema.require(MEETING_FOUNDATION_SCHEMA)
            first = list(executed)
            executed.clear()
            runtime_schema.require(MEETING_FOUNDATION_SCHEMA)
        finally:
            event.remove(db.engine, "before_cursor_execute", _count)
    assert not any(DDL.match(s) for s in first)
    assert executed == []


def test_provisioning_is_explicit_and_idempotent(provisioned_app):
    from app.services import runtime_schema

    with provisioned_app.app_context():
        again = runtime_schema.provision_all()
    assert all(before == [] and after == [] for before, after in again.values())


def test_cli_check_and_provision(app):
    runner = app.test_cli_runner()
    before = runner.invoke(args=["runtime-schema", "check"])
    assert before.exit_code == 1 and "performance.personnel_categories: MISSING" in before.output, before.output
    provision = runner.invoke(args=["runtime-schema", "provision"])
    assert provision.exit_code == 0, provision.output
    after = runner.invoke(args=["runtime-schema", "check"])
    assert after.exit_code == 0 and "MISSING" not in after.output, after.output


def test_every_registering_module_is_listed_for_the_cli():
    from app.services.runtime_schema import GROUP_MODULES

    registering = set()
    for path in (REPO / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8-sig", errors="ignore")
        if "runtime_schema.register(" not in source:
            continue
        tree = ast.parse(source)
        if any(isinstance(n, ast.Call) and ast.unparse(n.func) == "runtime_schema.register" for n in ast.walk(tree)):
            registering.add(".".join(path.relative_to(REPO).with_suffix("").parts))
    assert registering == set(GROUP_MODULES)
