"""BYS360 DEFECT AR: found during the Section 22 final repository-wide
residual sweep (beyond the wave's originally-named A1/A2 candidates) --
app.services.performance.meeting_development.ensure_meeting_foundation_schema
(5 tables) and app.services.ai_agent.knowledge.init_knowledge_table (1
table) both created tables with a hardcoded ``id SERIAL PRIMARY KEY`` and no
dialect branch at all, the exact same class of defect already fixed
elsewhere in this wave (interim_notes_manager_routes.py,
mobile/performance_routes.py). Both functions are heavily live: the meeting
one has 8+ call sites across the meeting/development-guidance subsystem
(meeting_development.py, meeting_development_final_gate.py,
meeting_development_gate.py, meeting_p0_completion.py,
meeting_rule_enforcement.py); the knowledge one is called from
app/ai_agent/routes.py and every read path in its own module.

Fixed by adding a local dialect check (mirroring
interim_notes_runtime.py::_id_sql(), using db.session.get_bind() not the
always-None db.session.bind) in each file.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ar-residual-sweep-contract")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    tmp_dir = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ar_residual")
    os.makedirs(tmp_dir, exist_ok=True)
    db_path = os.path.join(tmp_dir, f"defect_ar_residual_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
    return flask_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    return _make_app(monkeypatch)


def test_meeting_foundation_schema_ids_are_not_null_on_sqlite(app):
    from app.extensions import db
    from app.services.performance.meeting_development import provision_meeting_foundation_schema

    with app.app_context():
        provision_meeting_foundation_schema()
        db.session.execute(
            db.text("INSERT INTO performance_employee_categories (category_name) VALUES ('BYS360-AR-CATEGORY')"),
        )
        db.session.commit()
        row = db.session.execute(
            db.text("SELECT id FROM performance_employee_categories WHERE category_name = 'BYS360-AR-CATEGORY'"),
        ).fetchone()

    assert row is not None
    assert row[0] is not None


def test_ai_agent_knowledge_table_ids_are_not_null_on_sqlite(app):
    from app.extensions import db
    from app.services.ai_agent.knowledge import provision_knowledge_table

    with app.app_context():
        provision_knowledge_table()
        db.session.execute(
            db.text(
                "INSERT INTO ai_agent_knowledge_entries (title, question_patterns, answer) "
                "VALUES ('BYS360-AR-KNOWLEDGE', 'test pattern', 'test answer')"
            ),
        )
        db.session.commit()
        row = db.session.execute(
            db.text("SELECT id FROM ai_agent_knowledge_entries WHERE title = 'BYS360-AR-KNOWLEDGE'"),
        ).fetchone()

    assert row is not None
    assert row[0] is not None
