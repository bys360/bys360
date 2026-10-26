"""BYS360_DEFECT_T_REMEDIATION_ORCHESTRATION_EMPTY_SCOPE_FAIL_CLOSED_CONTRACT

Permanent regression contract for DEFECT T
(app/services/performance/orchestration.py::_scope_rows and its caller
build_chain_health_snapshot). Asserts the FIXED behavior only -- it does
not characterize, freeze, or otherwise exercise the prior buggy shape.

Prior defect (fixed by this same change): `_scope_rows` computed
`allowed = {int(v) for v in (employee_ids or []) if str(v).isdigit()}`
then `if not allowed: return list(rows or [])` -- collapsing `None` and
an explicit empty `employee_ids` into the identical "return every row
unfiltered" behavior. This fed `build_chain_health_snapshot`'s hierarchy
issue rows and assignment rows (each carrying `user`/`birim`/`ust_birim`
identity), reached from `build_performance_service_snapshot`, reached
from `app/services/performance/ops_center.py`.

The fix distinguishes `employee_ids is None` (unrestricted, return every
row) from "provided" (filter to the resolved `allowed` set, which
naturally yields zero rows via the existing per-row `in` check when
`allowed` is empty -- no query-level `employee_id == -1` sentinel is
needed here since `_scope_rows` filters an in-memory list of dicts, not a
SQL query).

`_scope_rows` is exercised directly (it is the exact, isolated fix
location, and calling it with real dict rows is not a mock of the
function under test) and once more end-to-end through
`build_chain_health_snapshot` with real seeded ORM users, to prove the
public entry point's wiring holds and no unrelated employee identity
leaks through it.

`build_assignment_generation_snapshot` (same file) was independently
re-confirmed during triage to already use the correct `is not None`
semantics and is NOT touched by this change; it has no regression test
here since no behavior changed.

Fixture pattern: service-boundary style for the end-to-end case, matching
the established Wave 6/7 precedent and this file's sibling Defect T
contracts. Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_defect_t_orchestration) so it shares no state with
any other wave/agent/test file running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_t_orchestration")

DEFAULT_PASSWORD = "DefectTOrchestrationTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "defect-t-orchestration-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# 1-4. _scope_rows -- pure function, direct proof (no DB needed)
# ---------------------------------------------------------------------------


def test_scope_rows_none_returns_all_legitimate_rows():
    from app.services.performance.orchestration import _scope_rows

    rows = [{"employee_id": 1, "user": "a"}, {"employee_id": 2, "user": "b"}]

    result = _scope_rows(rows, None)

    assert result == rows


def test_scope_rows_matching_returns_only_matching_rows():
    from app.services.performance.orchestration import _scope_rows

    rows = [{"employee_id": 1, "user": "a"}, {"employee_id": 2, "user": "b"}]

    result = _scope_rows(rows, {1})

    assert result == [{"employee_id": 1, "user": "a"}]


def test_scope_rows_nonmatching_returns_zero_rows():
    from app.services.performance.orchestration import _scope_rows

    rows = [{"employee_id": 1, "user": "a"}, {"employee_id": 2, "user": "b"}]

    result = _scope_rows(rows, {999999})

    assert result == []


def test_scope_rows_empty_returns_zero_rows():
    from app.services.performance.orchestration import _scope_rows

    rows = [{"employee_id": 1, "user": "a"}, {"employee_id": 2, "user": "b"}]

    result = _scope_rows(rows, set())

    assert result == [], "an explicitly empty authorization scope must never fall back to the unfiltered row list"


# ---------------------------------------------------------------------------
# App / DB fixture (end-to-end proof)
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-t-orchestration-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", DEFAULT_FIRST_LOGIN_PASSWORD)
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_t_orchestration_{uuid.uuid4().hex}.sqlite3")
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

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, ad="Kerem", soyad=None, birim="BT"):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"DTOR{n:06d}",
            email=f"defect-t-orchestration-{n}@bys360.test",
            ad=ad,
            soyad=soyad or f"Orchestration{n}",
            role="personel",
            is_active=True,
            birim=birim,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


# ---------------------------------------------------------------------------
# 5. end-to-end: build_chain_health_snapshot leaks no unrelated identity
# ---------------------------------------------------------------------------


def test_chain_health_snapshot_empty_scope_leaks_no_unrelated_identity(app):
    from app.services.performance.orchestration import build_chain_health_snapshot

    with app.app_context():
        _create_user(app, ad="Nazli", soyad="Aydin", birim="Muhasebe")

        snapshot_none = build_chain_health_snapshot(employee_ids=None)
        snapshot_empty = build_chain_health_snapshot(employee_ids=set())

    assert snapshot_none["user_count"] >= 1, "sanity check: the real seeded user is visible under the unrestricted (None) scope"
    assert snapshot_empty["user_count"] == 0, "an explicitly empty authorization scope must never fall back to the unfiltered user roster"
    assert snapshot_empty["issue_count"] == 0
    assert snapshot_empty["top_issue_units"] == []
    assert snapshot_empty["sample_issue_rows"] == []
    serialized_empty = repr(snapshot_empty)
    assert "Nazli" not in serialized_empty
    assert "Aydin" not in serialized_empty
    assert "Muhasebe" not in serialized_empty
