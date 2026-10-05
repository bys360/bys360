"""Contract: support / feedback requests never create or alter the schema (G2).

The seven support tables are owned by Alembic revision ``a3d8f1c9b6e2``. Before
G2, ``GET /feedback/gonder`` (any logged-in user), the help-admin pages and
``POST /support/setup`` ran ``__table__.create`` (CREATE TABLE / CREATE INDEX)
from inside the request when the tables were missing. Request code now only
detects readiness; a missing schema yields a controlled Turkish notice and
writes nothing.
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
PASSWORD = "SupportFeedbackSchemaG2Test!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "support_feedback_schema_g2" / "dbs"

ADMIN_SICIL = "G2SUPADMIN"
PERSONEL_SICIL = "G2SUPPERS"
# Dependency order (children first) so SQLite foreign keys never block the drop.
SUPPORT_TABLES = (
    "support_ticket_status_history",
    "support_feedback_ratings",
    "support_ticket_attachments",
    "support_ticket_messages",
    "support_tickets",
    "support_categories",
)
HELP_TABLE = "support_help_articles"
AFFECTED_FILES = (
    REPO / "app" / "support" / "routes.py",
    REPO / "app" / "communication" / "user_feedback_routes.py",
)
MIGRATION_HINT = "migration"


def _reset_ready_cache():
    from app.support import routes as support_routes

    support_routes._SUPPORT_READY_CACHE.update(
        {"tables_checked_at": 0.0, "tables_ready": None, "help_checked_at": 0.0, "help_ready": None}
    )


def _make_app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-support-feedback-g2",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "support-feedback-g2-first-login",
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
    from app.extensions import db
    from app.models import User

    with app.app_context():
        db.create_all()
        for sicil, role in ((ADMIN_SICIL, "admin"), (PERSONEL_SICIL, "personel")):
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Destek",
                soyad="Sema",
                role=role,
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()
    _reset_ready_cache()
    return app, db_file


def _drop(app, tables):
    from app.extensions import db

    with app.app_context():
        for table in tables:
            db.session.execute(db.text(f"DROP TABLE IF EXISTS {table}"))
        db.session.commit()
    _reset_ready_cache()


def _tables(app) -> set[str]:
    from app.extensions import db

    with app.app_context():
        return set(inspect(db.engine).get_table_names())


def _login(client, sicil):
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")


def _capture(app, call):
    from app.extensions import db

    statements: list[str] = []
    commits = [0]
    with app.app_context():
        engine = db.engine

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        if DDL.match(statement or ""):
            statements.append(" ".join(statement.split())[:160])

    def _on_commit(conn):
        commits[0] += 1

    event.listen(engine, "before_cursor_execute", _on_execute)
    event.listen(engine, "commit", _on_commit)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)
        event.remove(engine, "commit", _on_commit)
    return response, statements, commits[0]


def _flashes(client) -> list[tuple[str, str]]:
    with client.session_transaction() as session:
        return list(session.get("_flashes", []))


def _feedback_form():
    return {
        "feedback_kind": "idea",
        "module_name": "Genel",
        "title": "G2 sözleşme denemesi",
        "description": "Şema eksikken kayıt oluşturulmamalıdır.",
        "priority": "normal",
    }


@pytest.fixture
def app_and_file(monkeypatch):
    app, db_file = _make_app(monkeypatch)
    yield app, db_file
    from app.extensions import db

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    _reset_ready_cache()
    db_file.unlink(missing_ok=True)


@pytest.fixture
def app(app_and_file):
    return app_and_file[0]


@pytest.fixture
def missing_schema_app(app):
    _drop(app, (*SUPPORT_TABLES, HELP_TABLE))
    assert not (_tables(app) & {*SUPPORT_TABLES, HELP_TABLE})
    return app


# --- 1. GET /feedback/gonder ----------------------------------------------------------------


def test_feedback_get_with_missing_schema_runs_no_ddl_and_shows_notice(missing_schema_app):
    client = missing_schema_app.test_client()
    _login(client, PERSONEL_SICIL)
    response, ddl, commits = _capture(missing_schema_app, lambda: client.get("/feedback/gonder"))
    assert ddl == [], f"GET /feedback/gonder altered the schema: {ddl}"
    assert commits == 0
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Geri bildirim altyapısı hazırlanıyor" in body
    assert not (_tables(missing_schema_app) & {*SUPPORT_TABLES, HELP_TABLE})


# --- 2. POST /feedback/gonder ---------------------------------------------------------------


def test_feedback_post_with_missing_schema_fails_closed_without_writes(missing_schema_app):
    client = missing_schema_app.test_client()
    _login(client, PERSONEL_SICIL)
    response, ddl, commits = _capture(
        missing_schema_app, lambda: client.post("/feedback/gonder", data=_feedback_form())
    )
    assert ddl == [], f"POST /feedback/gonder altered the schema: {ddl}"
    assert commits == 0
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/feedback/gonder")
    messages = " ".join(message for _, message in _flashes(client))
    assert MIGRATION_HINT in messages.lower()
    assert not (_tables(missing_schema_app) & {*SUPPORT_TABLES, HELP_TABLE})


# --- 3. support help-admin with the help table missing --------------------------------------


@pytest.fixture
def missing_help_app(app):
    _drop(app, (HELP_TABLE,))
    assert HELP_TABLE not in _tables(app)
    assert set(SUPPORT_TABLES) <= _tables(app)
    return app


def test_help_admin_list_with_missing_help_table_runs_no_ddl(missing_help_app):
    client = missing_help_app.test_client()
    _login(client, ADMIN_SICIL)
    response, ddl, commits = _capture(missing_help_app, lambda: client.get("/support/help-admin"))
    assert ddl == [], f"GET /support/help-admin altered the schema: {ddl}"
    assert commits == 0
    assert response.status_code == 200
    assert MIGRATION_HINT in response.get_data(as_text=True).lower()
    assert HELP_TABLE not in _tables(missing_help_app)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/support/help-admin/new"),
        ("get", "/support/help-admin/1/edit"),
        ("post", "/support/help-admin/seed"),
        ("post", "/support/help-admin/sync"),
    ],
)
def test_help_admin_actions_with_missing_help_table_redirect_without_ddl(
    missing_help_app, method, path
):
    client = missing_help_app.test_client()
    _login(client, ADMIN_SICIL)
    response, ddl, commits = _capture(missing_help_app, lambda: getattr(client, method)(path))
    assert ddl == [], f"{method.upper()} {path} altered the schema: {ddl}"
    assert commits == 0
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/support/help-admin")
    messages = " ".join(message for _, message in _flashes(client))
    assert MIGRATION_HINT in messages.lower()
    assert HELP_TABLE not in _tables(missing_help_app)


def test_help_admin_authorization_is_unchanged_for_non_admin(missing_help_app):
    client = missing_help_app.test_client()
    _login(client, PERSONEL_SICIL)
    response, ddl, _ = _capture(missing_help_app, lambda: client.get("/support/help-admin"))
    assert ddl == []
    assert response.status_code == 403
    assert HELP_TABLE not in _tables(missing_help_app)


def test_help_admin_requires_login(missing_help_app):
    client = missing_help_app.test_client()
    response, ddl, _ = _capture(missing_help_app, lambda: client.get("/support/help-admin"))
    assert ddl == []
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- 4. POST /support/setup -----------------------------------------------------------------


def test_support_setup_post_with_missing_schema_requires_migration(missing_schema_app):
    client = missing_schema_app.test_client()
    _login(client, ADMIN_SICIL)
    response, ddl, commits = _capture(missing_schema_app, lambda: client.post("/support/setup"))
    assert ddl == [], f"POST /support/setup altered the schema: {ddl}"
    assert commits == 0
    assert response.status_code == 200
    assert MIGRATION_HINT in response.get_data(as_text=True).lower()
    assert not (_tables(missing_schema_app) & {*SUPPORT_TABLES, HELP_TABLE})


def test_support_setup_authorization_is_unchanged_for_non_admin(missing_schema_app):
    client = missing_schema_app.test_client()
    _login(client, PERSONEL_SICIL)
    response, ddl, _ = _capture(missing_schema_app, lambda: client.post("/support/setup"))
    assert ddl == []
    assert response.status_code == 403
    assert not (_tables(missing_schema_app) & {*SUPPORT_TABLES, HELP_TABLE})


# --- 5. migrated schema: normal behaviour is preserved --------------------------------------


def test_feedback_happy_path_on_migrated_schema(app):
    from app.extensions import db
    from app.models import SupportTicket

    client = app.test_client()
    _login(client, PERSONEL_SICIL)
    response, ddl, _ = _capture(app, lambda: client.get("/feedback/gonder"))
    assert ddl == []
    assert response.status_code == 200
    assert "Geri bildirim altyapısı hazırlanıyor" not in response.get_data(as_text=True)

    response, ddl, _ = _capture(app, lambda: client.post("/feedback/gonder", data=_feedback_form()))
    assert ddl == []
    assert response.status_code == 302
    assert "/feedback/gonderildi/" in response.headers["Location"]
    with app.app_context():
        tickets = SupportTicket.query.all()
        assert len(tickets) == 1
        assert tickets[0].ticket_no.startswith("GBD-")
        assert tickets[0].title == "[Fikir / Öneri] G2 sözleşme denemesi"
        db.session.remove()
    success = client.get(response.headers["Location"])
    assert success.status_code == 200


def test_help_admin_happy_path_on_migrated_schema(app):
    from app.models import SupportHelpArticle

    client = app.test_client()
    _login(client, ADMIN_SICIL)
    response, ddl, _ = _capture(app, lambda: client.get("/support/help-admin"))
    assert ddl == []
    assert response.status_code == 200
    assert MIGRATION_HINT not in response.get_data(as_text=True).lower()

    response, ddl, _ = _capture(app, lambda: client.get("/support/help-admin/new"))
    assert ddl == []
    assert response.status_code == 200

    response, ddl, _ = _capture(app, lambda: client.post("/support/help-admin/seed"))
    assert ddl == []
    assert response.status_code == 302
    with app.app_context():
        assert SupportHelpArticle.query.count() > 0


def test_support_setup_on_migrated_schema_seeds_categories_with_dml_only(app):
    from app.models import SupportCategory
    from app.support.routes import DEFAULT_CATEGORY_ROWS

    client = app.test_client()
    _login(client, ADMIN_SICIL)
    get_response, ddl, _ = _capture(app, lambda: client.get("/support/setup"))
    assert ddl == []
    assert get_response.status_code == 200

    for _ in range(2):
        response, ddl, _ = _capture(app, lambda: client.post("/support/setup"))
        assert ddl == []
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/support")
    with app.app_context():
        names = sorted(row.name for row in SupportCategory.query.all())
    assert names == sorted(name for name, _, _ in DEFAULT_CATEGORY_ROWS)


# --- 6. static contract ---------------------------------------------------------------------

_STATIC_DDL = re.compile(r"\b(CREATE\s+(UNIQUE\s+)?INDEX|CREATE\s+TABLE|ALTER\s+TABLE)\b", re.I)
# Former request-time table creators; neither may come back under these names.
_FORMER_CREATORS = {
    "_ensure_support_tables_for_current_db",
    "_ensure_support_help_tables_for_current_db",
}


@pytest.mark.parametrize("path", AFFECTED_FILES, ids=lambda p: p.name)
def test_affected_request_modules_contain_no_ddl(path):
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"create", "create_all"}:
            target = node.value
            if node.attr == "create_all" or (
                isinstance(target, ast.Attribute) and target.attr == "__table__"
            ):
                offenders.append(f"line {node.lineno}: .{node.attr}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _STATIC_DDL.search(node.value)
        ):
            offenders.append(f"line {node.lineno}: {node.value[:60]!r}")
        if isinstance(node, ast.Name) and node.id in _FORMER_CREATORS:
            offenders.append(f"line {node.lineno}: {node.id}")
        if isinstance(node, ast.FunctionDef) and node.name in _FORMER_CREATORS:
            offenders.append(f"line {node.lineno}: def {node.name}")
        if isinstance(node, ast.ImportFrom):
            offenders.extend(
                f"line {node.lineno}: import {a.name}"
                for a in node.names
                if a.name in _FORMER_CREATORS
            )
    assert offenders == [], f"{path.relative_to(REPO)} still contains request-time DDL: {offenders}"
