"""BYS360_SECURITY_REMEDIATION_DEFECT_N_MOBILE_PERFORMANCE_NOTE_CREATE

Regression contract for the authorization bypass in
app/api/mobile/services/performance_note_route_services.py::
phase3c_mobile_performance_create_in_period_note_v2853_service, mounted at
POST /api/mobile/performance/in-period-notes/v2.

DEFECT N (fixed): the CREATE service extracted `employee_id` straight from
the client-supplied JSON body and inserted a `performance_interim_notes` row
for that employee_id with zero ownership/relationship check -- any
authenticated "personel" caller could forge a note (including one flagged
`include_in_scorecard=True`) attributed to an arbitrary, unrelated employee.
The sibling READ service in the same file (
phase3c_mobile_performance_in_period_notes_v2853_service) already correctly
scoped its SELECT via `_has_global_scope`, but the CREATE path never
extracted that dependency at all.

Fix (reviewed contract, reused verbatim from the existing canonical mobile
performance authorization checks -- not invented):
  1. self-note (`employee_id == user.id`, including the pre-existing default
     of omitting employee_id entirely) is always allowed.
  2. `_has_global_scope(user)` (from app/api/mobile/shared.py, exactly the
     check reused everywhere else in this file) allows targeting any
     employee.
  3. Otherwise a real `EvaluationAssignment` row with
     `evaluator_id == caller.id AND employee_id == target` is required
     (no `status` filter -- matching the existing canonical
     `_v2822_can_view_assignment` / `_assignment_query_for` policy
     elsewhere in the mobile performance domain, which also never filters
     by status). Any other case is denied with HTTP 403 and zero DB
     mutation.

Fixture pattern: proven per this remediation wave's mandatory rule -- copied
from tests/behavior/test_admin_ops_user_actions_destructive_operations_
contract.py's `_make_app` (Config class attributes monkeypatched BEFORE
create_app(), StaticPool + pysqlite isolation_level=None + explicit BEGIN
event listener). Drives requests through the real Flask test client, real
ORM-seeded User rows, and the real mobile bearer-token issuance function
(app.api.mobile.shared._issue_token) -- no hand-rolled tokens, no mocking of
the authorization check itself. Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_secfix_n) so it shares no state with any other
wave/agent running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_secfix_n")

DEFAULT_PASSWORD = "SecFixNContractTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "secfix-n-first-login-test-pw"

_user_counter = 0

_ENDPOINT = "/api/mobile/performance/in-period-notes/v2"


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-secfix-n-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"secfix_n_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # BYS360_SECFIX_N: Config.SQLALCHEMY_DATABASE_URI is a class attribute
    # frozen the first time config.py is imported anywhere in this pytest
    # process. Flask-SQLAlchemy 3.x lazily binds AND CACHES the per-app
    # Engine on first access, read from app.config at that exact moment.
    # Patching Config's class attributes BEFORE create_app() (not updating
    # flask_app.config afterward) is required for this test's own unique
    # file-backed SQLite DB to actually take effect.
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
def app(monkeypatch, install_interim_notes_schema):
    flask_app = _make_app(monkeypatch)
    from app.extensions import db

    with flask_app.app_context():
        # The table is Alembic-owned (revision x1f3a9c5e7b2); requests no longer create it.
        install_interim_notes_schema(db.engine)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role="personel", is_active=True, password=DEFAULT_PASSWORD):
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"SECN{suffix:06d}",
            email=f"secfix-n-{suffix}@bys360.test",
            ad="SecFixN",
            soyad=f"User{suffix}",
            role=role,
            is_active=is_active,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _bearer_token(app, user_id):
    from app.api.mobile.shared import _issue_token
    from app.models import User

    with app.app_context():
        user = User.query.get(user_id)
        return _issue_token(user)


def _auth_headers(app, user_id):
    return {"Authorization": f"Bearer {_bearer_token(app, user_id)}"}


def _create_assignment(app, *, evaluator_id, employee_id, status="bekliyor", period_id=None, manager_level=1):
    import datetime as _dt

    from app.extensions import db
    from app.models import EvaluationAssignment, PerformancePeriod

    with app.app_context():
        if period_id is None:
            today = _dt.date.today()
            period = PerformancePeriod(
                title=f"SecFixN Period {uuid.uuid4().hex[:8]}",
                name=f"SecFixN Period {uuid.uuid4().hex[:8]}",
                period_type="yillik",
                start_date=today,
                end_date=today + _dt.timedelta(days=90),
                is_active=True,
            )
            db.session.add(period)
            db.session.commit()
            period_id = period.id
        assignment = EvaluationAssignment(
            period_id=period_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            manager_level=manager_level,
            status=status,
        )
        db.session.add(assignment)
        db.session.commit()
        return assignment.id, period_id


def _note_count(app):
    from sqlalchemy import text as _sql_text

    from app.extensions import db

    with app.app_context():
        try:
            row = db.session.execute(_sql_text("SELECT COUNT(*) FROM performance_interim_notes")).first()
            return int(row[0]) if row else 0
        except Exception:
            # Table may not exist yet if it was never lazily created.
            return 0


def _note_rows_for_employee(app, employee_id, note_text):
    from sqlalchemy import text as _sql_text

    from app.extensions import db

    with app.app_context():
        try:
            rows = db.session.execute(
                _sql_text(
                    "SELECT id, employee_id, manager_id, created_by, note, include_in_scorecard "
                    "FROM performance_interim_notes WHERE employee_id = :employee_id AND note = :note"
                ),
                {"employee_id": employee_id, "note": note_text},
            ).mappings().all()
            return list(rows)
        except Exception:
            return []


def _post_note(client, headers, *, employee_id=None, note="SecFixN synthetic note", include_in_scorecard=False, period_id=None):
    payload = {"note": note, "include_in_scorecard": include_in_scorecard}
    if employee_id is not None:
        payload["employee_id"] = employee_id
    if period_id is not None:
        payload["period_id"] = period_id
    return client.post(_ENDPOINT, json=payload, headers=headers)


# ---------------------------------------------------------------------------
# N1: unauthenticated / invalid token -> 401, pre-existing require_mobile_user
# behavior stays intact.
# ---------------------------------------------------------------------------


def test_n1_unauthenticated_request_is_rejected_with_401(app, client):
    user_a_id = _create_user(app, role="personel")
    user_b_id = _create_user(app, role="personel")
    before = _note_count(app)

    resp_no_header = client.post(_ENDPOINT, json={"note": "no auth", "employee_id": user_b_id})
    assert resp_no_header.status_code == 401

    resp_garbage_token = client.post(
        _ENDPOINT,
        json={"note": "garbage auth", "employee_id": user_b_id},
        headers={"Authorization": "Bearer this-is-not-a-real-token"},
    )
    assert resp_garbage_token.status_code == 401

    assert _note_count(app) == before
    _ = user_a_id


# ---------------------------------------------------------------------------
# N2/N3: the core regression -- unrelated personel A targeting unrelated
# personel B with no EvaluationAssignment relationship at all must be
# denied, not silently accepted.
# ---------------------------------------------------------------------------


def test_n2_n3_unrelated_personnel_cannot_forge_note_for_unrelated_employee(app, client):
    user_a_id = _create_user(app, role="personel")
    user_b_id = _create_user(app, role="personel")
    headers_a = _auth_headers(app, user_a_id)
    note_text = f"FORGED-NOTE-{uuid.uuid4().hex}"

    before = _note_count(app)
    resp = _post_note(client, headers_a, employee_id=user_b_id, note=note_text, include_in_scorecard=True)
    after = _note_count(app)

    assert resp.status_code == 403
    body = resp.get_json()
    assert body is not None
    assert body.get("ok") is not True
    assert "kaydedildi" not in str(body.get("message", "")).lower()

    assert after == before, "denied create request must not mutate performance_interim_notes"
    assert _note_rows_for_employee(app, user_b_id, note_text) == []


# ---------------------------------------------------------------------------
# N4: positive case -- a real EvaluationAssignment(evaluator=A, employee=B)
# must allow A to create a note for B, including a scorecard-visible one.
# ---------------------------------------------------------------------------


def test_n4_evaluator_with_real_assignment_can_create_note_for_employee(app, client):
    user_a_id = _create_user(app, role="personel")
    user_b_id = _create_user(app, role="personel")
    # Deliberately use a non-"active"/non-terminal status to prove the fix's
    # contract matches the canonical no-status-filter policy used elsewhere
    # in the mobile performance domain (_v2822_can_view_assignment,
    # _assignment_query_for).
    _create_assignment(app, evaluator_id=user_a_id, employee_id=user_b_id, status="bekliyor")
    headers_a = _auth_headers(app, user_a_id)
    note_text = f"LEGIT-NOTE-{uuid.uuid4().hex}"

    before = _note_count(app)
    resp = _post_note(client, headers_a, employee_id=user_b_id, note=note_text, include_in_scorecard=True)
    after = _note_count(app)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None
    assert body.get("ok") is True

    assert after == before + 1

    rows = _note_rows_for_employee(app, user_b_id, note_text)
    assert len(rows) == 1
    row = rows[0]
    assert int(row["employee_id"]) == user_b_id
    assert int(row["manager_id"]) == user_a_id
    assert int(row["created_by"]) == user_a_id
    assert bool(row["include_in_scorecard"]) is True


# ---------------------------------------------------------------------------
# N5: positive case -- global-scope role (e.g. admin) may target an employee
# with zero EvaluationAssignment relationship at all.
# ---------------------------------------------------------------------------


def test_n5_global_scope_role_can_create_note_without_any_assignment(app, client):
    user_c_id = _create_user(app, role="admin")
    user_b_id = _create_user(app, role="personel")
    headers_c = _auth_headers(app, user_c_id)
    note_text = f"GLOBAL-SCOPE-NOTE-{uuid.uuid4().hex}"

    before = _note_count(app)
    resp = _post_note(client, headers_c, employee_id=user_b_id, note=note_text)
    after = _note_count(app)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None
    assert body.get("ok") is True

    assert after == before + 1
    rows = _note_rows_for_employee(app, user_b_id, note_text)
    assert len(rows) == 1
    assert int(rows[0]["employee_id"]) == user_b_id
    assert int(rows[0]["manager_id"]) == user_c_id


# ---------------------------------------------------------------------------
# N6: self-note default behavior (employee_id omitted, or explicitly equal
# to caller's own id) must remain untouched by the fix.
# ---------------------------------------------------------------------------


def test_n6_self_note_with_employee_id_omitted_is_allowed(app, client):
    user_a_id = _create_user(app, role="personel")
    headers_a = _auth_headers(app, user_a_id)
    note_text = f"SELF-NOTE-OMITTED-{uuid.uuid4().hex}"

    before = _note_count(app)
    resp = _post_note(client, headers_a, employee_id=None, note=note_text)
    after = _note_count(app)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None
    assert body.get("ok") is True

    assert after == before + 1
    rows = _note_rows_for_employee(app, user_a_id, note_text)
    assert len(rows) == 1
    assert int(rows[0]["employee_id"]) == user_a_id
    assert int(rows[0]["manager_id"]) == user_a_id
    assert int(rows[0]["created_by"]) == user_a_id


def test_n6_self_note_with_employee_id_explicitly_own_id_is_allowed(app, client):
    user_a_id = _create_user(app, role="personel")
    headers_a = _auth_headers(app, user_a_id)
    note_text = f"SELF-NOTE-EXPLICIT-{uuid.uuid4().hex}"

    before = _note_count(app)
    resp = _post_note(client, headers_a, employee_id=user_a_id, note=note_text)
    after = _note_count(app)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None
    assert body.get("ok") is True

    assert after == before + 1
    rows = _note_rows_for_employee(app, user_a_id, note_text)
    assert len(rows) == 1
    assert int(rows[0]["employee_id"]) == user_a_id


# ---------------------------------------------------------------------------
# Boundary: an EvaluationAssignment DOES exist between A and B, but with the
# evaluator/employee roles reversed (B is the evaluator of A). The fix must
# still deny A creating a note for B -- proving it checks the correct
# direction of the relationship, not just "any row mentioning both users".
# ---------------------------------------------------------------------------


def test_boundary_reversed_assignment_direction_is_still_denied(app, client):
    user_a_id = _create_user(app, role="personel")
    user_b_id = _create_user(app, role="personel")
    # B is the evaluator OF A -- the reverse of what A is attempting.
    _create_assignment(app, evaluator_id=user_b_id, employee_id=user_a_id, status="bekliyor")
    headers_a = _auth_headers(app, user_a_id)
    note_text = f"REVERSED-DIRECTION-NOTE-{uuid.uuid4().hex}"

    before = _note_count(app)
    resp = _post_note(client, headers_a, employee_id=user_b_id, note=note_text)
    after = _note_count(app)

    assert resp.status_code == 403
    body = resp.get_json()
    assert body is not None
    assert body.get("ok") is not True

    assert after == before
    assert _note_rows_for_employee(app, user_b_id, note_text) == []
