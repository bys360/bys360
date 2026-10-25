"""BYS360 DEFECT AR: four live ``table_exists``/``_table_exists`` helpers
raised straight through on any ``inspect()`` failure (e.g. a dropped
connection), unlike ~20 other implementations doing the identical
conceptual check elsewhere in this codebase (including, ironically, two of
these same modules' own docstrings, which claimed kinship with the
safe-swallow family without actually matching its exception behavior). All
four are aligned here to the dominant convention: log and return False
instead of raising.

Covers:
- app.services.performance.process_engine_phase4_flow.table_exists
- app.services.performance.process_engine_phase6_president_approvals.table_exists
- app.services.performance.president_card_review_service.table_exists
- app.performance.president_low_score_card_routes._table_exists

Each is proven for both the normal-operation cases (existing/missing table)
and the regression case that previously raised (inspect() failure -> must
now return False, not propagate the exception).
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_ar_table_exists")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ar-table-exists-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ar-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_ar_te_{uuid.uuid4().hex}.sqlite3")
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
        WTF_CSRF_ENABLED=False,
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
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


_MODULES = [
    ("app.services.performance.process_engine_phase4_flow", "table_exists"),
    ("app.services.performance.process_engine_phase6_president_approvals", "table_exists"),
    ("app.services.performance.president_card_review_service", "table_exists"),
    ("app.performance.president_low_score_card_routes", "_table_exists"),
]


@pytest.mark.parametrize("module_path, func_name", _MODULES)
def test_table_exists_true_for_real_table(app, module_path, func_name):
    import importlib

    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    with app.app_context():
        assert func("users") is True


@pytest.mark.parametrize("module_path, func_name", _MODULES)
def test_table_exists_false_for_missing_table(app, module_path, func_name):
    import importlib

    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    with app.app_context():
        assert func("bys360_ar_this_table_does_not_exist") is False


@pytest.mark.parametrize("module_path, func_name", _MODULES)
def test_table_exists_returns_false_not_raise_on_inspect_failure(app, module_path, func_name, monkeypatch):
    import importlib

    module = importlib.import_module(module_path)
    func = getattr(module, func_name)

    def _raising_inspect(*args, **kwargs):
        raise RuntimeError("BYS360-AR-SIMULATED-INSPECT-FAILURE")

    monkeypatch.setattr(module, "inspect", _raising_inspect)
    with app.app_context():
        # Before the fix, this would propagate RuntimeError instead of
        # returning False like every other table-existence helper.
        assert func("users") is False


def test_portal_experience_v2_table_exists_false_on_inspect_failure(app, monkeypatch):
    from app.services import portal_experience_v2_service as module

    with app.app_context():
        from app.extensions import db

        def _raising_inspect(*args, **kwargs):
            raise RuntimeError("BYS360-AR-SIMULATED-INSPECT-FAILURE")

        monkeypatch.setattr(db, "inspect", _raising_inspect)
        assert module._table_exists("users") is False
