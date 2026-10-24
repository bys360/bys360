"""BYS360 DEFECT AR: build_sp3a_kpi_dashboard_context(current_user) accepted
a `current_user` parameter but never referenced it in the query body --
every viewer who passed the screen's own is_top_or_manager gate (which
includes mid-level roles like koordinator, grup_baskani, birim_sorumlusu,
not just Başkan/Admin/İK) saw the exact same unrestricted, organization-wide
KPI/target feed. The fix scopes non-"global" viewers (per the app's already
audited role_group_for classification from ai_decision.visibility_scope) to
rows they own, when the underlying table carries an owner-id column.

None of the real TARGET_TABLE_CANDIDATES tables exist in this codebase yet
(no migration defines strategic_targets/kpi_targets/etc.) -- this is
scaffolding for a not-yet-built SP-1 module. This contract creates a
synthetic table matching the service's own dynamic column-detection
convention to prove the scoping logic itself, independent of which real
table eventually gets built.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ar-sp3a-contract")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    tmp_dir = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ar_sp3a")
    os.makedirs(tmp_dir, exist_ok=True)
    db_path = os.path.join(tmp_dir, f"defect_ar_sp3a_{uuid.uuid4().hex}.sqlite3")
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
        db.session.execute(db.text("""
            CREATE TABLE strategic_targets (
                id INTEGER PRIMARY KEY,
                target_name TEXT NOT NULL,
                owner_user_id INTEGER,
                is_active INTEGER DEFAULT 1
            )
        """))
        db.session.execute(
            db.text("INSERT INTO strategic_targets (id, target_name, owner_user_id) VALUES (1, 'Koordinator Hedefi', 101)"),
        )
        db.session.execute(
            db.text("INSERT INTO strategic_targets (id, target_name, owner_user_id) VALUES (2, 'Baska Biriminin Hedefi', 202)"),
        )
        db.session.commit()
    return flask_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def test_manager_scope_role_sees_only_own_targets(app):
    from app.services.sp3a_kpi_dashboard_live_service import build_sp3a_kpi_dashboard_context

    koordinator = SimpleNamespace(id=101, role="koordinator")
    with app.app_context():
        context = build_sp3a_kpi_dashboard_context(koordinator)

    names = [row["name"] for row in context["targets"]]
    assert "Koordinator Hedefi" in names
    assert "Baska Biriminin Hedefi" not in names


def test_global_scope_role_sees_all_targets(app):
    from app.services.sp3a_kpi_dashboard_live_service import build_sp3a_kpi_dashboard_context

    admin = SimpleNamespace(id=999, role="admin")
    with app.app_context():
        context = build_sp3a_kpi_dashboard_context(admin)

    names = [row["name"] for row in context["targets"]]
    assert "Koordinator Hedefi" in names
    assert "Baska Biriminin Hedefi" in names


def test_manager_scope_role_with_no_current_user_id_sees_no_targets_not_everything(app):
    from app.services.sp3a_kpi_dashboard_live_service import build_sp3a_kpi_dashboard_context

    anonymous_like = SimpleNamespace(id=None, role="koordinator")
    with app.app_context():
        context = build_sp3a_kpi_dashboard_context(anonymous_like)

    # Fail-closed: no identifiable owner -> no rows, never the unscoped set.
    assert context["targets"] == []
