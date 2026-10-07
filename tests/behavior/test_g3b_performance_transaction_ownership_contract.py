"""G3-B (HD-10 Option A): opening an evaluation form is a read; writes own their transaction.

``performance_v2_phase3_assignment`` (also served at faz4 / faz8 and the ``/performans``
aliases) used to build the workspace with ``_ensure_evaluation()``, which INSERTed a
``performance_evaluations`` row and re-stamped ``level_N_evaluator_id``. The interim-notes
readiness helper then committed that pending work, so:

* a GET persisted an evaluation row and an evaluator re-stamp;
* a POST built the workspace (and committed the row) before its business action ran, so a
  failed action left a partial evaluation behind.

Contract pinned here:

* GET builds a read model only: 0 INSERT/UPDATE/DELETE, 0 commits, no evaluation row, no
  re-stamp, ``updated_at`` unchanged, one readiness check per request.
* save / submit / return / withdraw create a missing evaluation themselves, inside the
  route's single business transaction; any failure before that commit leaves nothing behind.
* creation is race-safe on ``uq_period_employee_evaluation``.
* refused requests (wrong owner, pasif, muaf, anonymous) do no work at all.
"""

from __future__ import annotations

import re
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import FrameType, SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text

PASSWORD = "TransactionOwnershipTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "g3b_transaction_ownership" / "dbs"
_APP_DIR = Path(__file__).resolve().parents[2] / "app"
DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.I)
HELPER_FILE = "interim_notes_runtime.py"
ROUTE_FILE = "performance/v2_routes.py"
ROUTE_VIEW = "performance_v2_phase3_assignment"
SNAPSHOT_TABLES = ("performance_evaluations", "performance_evaluation_items", "evaluation_assignments")
ASSIGNMENT_PATHS = (
    "/performance/v2/faz3/assignment/{id}",
    "/performans/v2/faz3/assignment/{id}",
    "/performance/v2/faz4/assignment/{id}",
    "/performans/v2/faz4/assignment/{id}",
    "/performance/v2/faz8/assignment/{id}",
    "/performans/v2/faz8/assignment/{id}",
)
LIVE_SCORE = re.compile(r'id="liveLevelScore">([^<]*)<')


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-g3b-transaction-ownership",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "g3b-transaction-ownership-first-login",
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
def env(monkeypatch, install_interim_notes_schema):
    from app.extensions import db
    from app.models import (
        EvaluationAssignment,
        PerformanceCriteria,
        PerformanceEvaluation,
        PerformancePeriod,
        User,
    )

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    ids: dict[str, int] = {}
    with app.app_context():
        db.create_all()
        sicils: dict[str, str] = {}

        def _user(key: str, role: str, managers: tuple[str, str, str] | None = None) -> None:
            sicil = f"G3BT{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Islem",
                soyad=key.title(),
                role=role,
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            if managers:
                user.yonetici_sicil, user.ikinci_yonetici_sicil, user.ucuncu_yonetici_sicil = managers
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[key] = int(user.id)
            sicils[key] = sicil

        for key, role in (
            ("admin", "admin"),
            ("l1", "grup_baskani"),
            ("l2", "koordinator"),
            ("l3", "birim_sorumlusu"),
            ("l3b", "birim_sorumlusu"),
            ("intruder", "personel"),
        ):
            _user(key, role)
        chain = (sicils["l1"], sicils["l2"], sicils["l3"])
        for key in ("emp_new", "emp_gen", "emp_pasif", "emp_muaf"):
            _user(key, "personel", chain)
        _user("emp_solo", "personel")

        period = PerformancePeriod(
            title="Islem Sahipligi Donemi",
            period_type="quarterly",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.flush()
        ids["period"] = int(period.id)
        for index in range(2):
            criterion = PerformanceCriteria(name=f"G3B Kriter {index}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criterion)
            db.session.flush()
            ids[f"criterion_{index}"] = int(criterion.id)

        def _assignment(key: str, employee: str, evaluator: str, level: int, status: str = "bekliyor") -> None:
            assignment = EvaluationAssignment(
                period_id=period.id,
                employee_id=ids[employee],
                evaluator_id=ids[evaluator],
                manager_level=level,
                status=status,
            )
            db.session.add(assignment)
            db.session.flush()
            ids[key] = int(assignment.id)

        for prefix, employee in (("new", "emp_new"), ("gen", "emp_gen")):
            _assignment(f"{prefix}_l3", employee, "l3", 3)
            _assignment(f"{prefix}_l2", employee, "l2", 2)
            _assignment(f"{prefix}_l1", employee, "l1", 1)
        _assignment("pasif", "emp_pasif", "l3", 3, "pasif")
        _assignment("muaf", "emp_muaf", "l3", 3, "muaf")
        _assignment("solo_l1", "emp_solo", "l1", 1)
        # The assignment/evaluation generator lifecycle created this row (canonical origin).
        generated = PerformanceEvaluation(
            period_id=period.id,
            employee_id=ids["emp_gen"],
            level_1_evaluator_id=ids["l1"],
            level_2_evaluator_id=ids["l2"],
            level_3_evaluator_id=ids["l3"],
        )
        db.session.add(generated)
        db.session.flush()
        ids["gen_evaluation"] = int(generated.id)
        db.session.commit()
        install_interim_notes_schema(db.engine)
        db.session.remove()
    yield SimpleNamespace(app=app, ids=ids)
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


def _client(env, who):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": f"G3BT{who.upper()}", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _url(template: str, assignment_id: int) -> str:
    return template.format(id=assignment_id)


def _dashboard(env) -> str:
    from flask import url_for

    with env.app.test_request_context():
        return url_for("main.performance_v2_phase3_dashboard")


def _snapshot(env) -> dict[str, list[tuple]]:
    from app.extensions import db

    with env.app.app_context():
        state = {
            table: [tuple(row) for row in db.session.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()]
            for table in SNAPSHOT_TABLES
        }
        db.session.remove()
    return state


def _evaluations(env, employee: str) -> list[dict[str, Any]]:
    from app.extensions import db

    with env.app.app_context():
        rows = [
            dict(row._mapping)
            for row in db.session.execute(
                text("SELECT * FROM performance_evaluations WHERE employee_id = :e ORDER BY id"),
                {"e": env.ids[employee]},
            ).all()
        ]
        db.session.remove()
    return rows


def _items(env, evaluation_id: int) -> int:
    from app.extensions import db

    with env.app.app_context():
        count = db.session.execute(
            text("SELECT COUNT(*) FROM performance_evaluation_items WHERE evaluation_id = :e"), {"e": evaluation_id}
        ).scalar()
        db.session.remove()
    return int(count or 0)


def _assignment_status(env, key: str) -> str:
    from app.extensions import db

    with env.app.app_context():
        status = db.session.execute(
            text("SELECT status FROM evaluation_assignments WHERE id = :i"), {"i": env.ids[key]}
        ).scalar()
        db.session.remove()
    return str(status)


def _origin() -> tuple[tuple[str, str] | None, bool]:
    """First app/ frame that called the session method, and whether the readiness helper is on the stack."""
    frame: FrameType | None = sys._getframe(2)
    first: tuple[str, str] | None = None
    helper = False
    while frame is not None:
        try:
            rel = Path(frame.f_code.co_filename).resolve().relative_to(_APP_DIR)
        except ValueError:
            rel = None
        if rel is not None:
            if first is None:
                first = (rel.as_posix(), frame.f_code.co_name)
            if rel.name == HELPER_FILE:
                helper = True
        frame = frame.f_back
    return first, helper


@dataclass
class Tx:
    dml: list[str] = field(default_factory=list)
    engine_commits: int = 0
    session: list[tuple[str, tuple[str, str] | None, bool]] = field(default_factory=list)
    readiness_calls: int = 0

    def calls(self, method: str) -> list[tuple[str, str] | None]:
        return [origin for name, origin, _helper in self.session if name == method]

    def helper_calls(self, method: str) -> int:
        return sum(1 for name, _origin, helper in self.session if name == method and helper)


def _record(env, monkeypatch, call):
    """Run ``call`` while recording DML, real commits, session commit/rollback/flush and readiness checks."""
    from app.extensions import db
    from app.services.performance import interim_notes_runtime

    tx = Tx()
    with env.app.app_context():
        engine = db.engine

    def _on_sql(conn, cursor, statement, parameters, context, executemany):
        if DML.match(statement or ""):
            tx.dml.append(" ".join(statement.split()[:3]))

    def _on_commit(conn):
        tx.engine_commits += 1

    real_ready = interim_notes_runtime.ensure_interim_notes_table

    def _counting_ready():
        tx.readiness_calls += 1
        return real_ready()

    with monkeypatch.context() as patch:
        for method in ("commit", "rollback", "flush"):
            original = getattr(db.session, method)

            def _wrapper(*args, _method=method, _original=original, **kwargs):
                origin, helper = _origin()
                tx.session.append((_method, origin, helper))
                return _original(*args, **kwargs)

            patch.setattr(db.session, method, _wrapper)
        patch.setattr(interim_notes_runtime, "ensure_interim_notes_table", _counting_ready)
        event.listen(engine, "before_cursor_execute", _on_sql)
        event.listen(engine, "commit", _on_commit)
        try:
            response = call()
        finally:
            event.remove(engine, "before_cursor_execute", _on_sql)
            event.remove(engine, "commit", _on_commit)
    return response, tx


def _assert_read_only(tx: Tx) -> None:
    assert tx.dml == []
    assert tx.engine_commits == 0
    assert tx.calls("commit") == []
    assert tx.calls("flush") == []


# ---------------------------------------------------------------------------
# GET is a read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", ASSIGNMENT_PATHS)
def test_first_visit_get_without_evaluation_persists_nothing(env, monkeypatch, template):
    client = _client(env, "l3")
    before = _snapshot(env)
    response, tx = _record(env, monkeypatch, lambda: client.get(_url(template, env.ids["new_l3"])))
    assert response.status_code == 200
    _assert_read_only(tx)
    assert tx.helper_calls("commit") == 0
    assert tx.readiness_calls == 1
    assert _evaluations(env, "emp_new") == []
    assert _snapshot(env) == before


def test_get_with_generator_created_evaluation_changes_nothing(env, monkeypatch):
    client = _client(env, "l3")
    before = _snapshot(env)
    stamp = _evaluations(env, "emp_gen")[0]
    response, tx = _record(env, monkeypatch, lambda: client.get(_url(ASSIGNMENT_PATHS[0], env.ids["gen_l3"])))
    assert response.status_code == 200
    _assert_read_only(tx)
    after = _evaluations(env, "emp_gen")[0]
    assert after["updated_at"] == stamp["updated_at"]
    assert (after["level_1_evaluator_id"], after["level_2_evaluator_id"], after["level_3_evaluator_id"]) == (
        env.ids["l1"],
        env.ids["l2"],
        env.ids["l3"],
    )
    assert _snapshot(env) == before


def test_repeated_get_keeps_the_database_field_equivalent(env, monkeypatch):
    client = _client(env, "l3")
    before = _snapshot(env)
    for assignment in ("new_l3", "gen_l3", "new_l3"):
        response, tx = _record(env, monkeypatch, lambda a=assignment: client.get(_url(ASSIGNMENT_PATHS[0], env.ids[a])))
        assert response.status_code == 200
        _assert_read_only(tx)
        assert tx.readiness_calls == 1
        assert _snapshot(env) == before


def test_get_after_reassignment_does_not_persist_an_evaluator_restamp(env, monkeypatch):
    from app.extensions import db

    with env.app.app_context():
        db.session.execute(
            text("UPDATE evaluation_assignments SET evaluator_id = :new WHERE id = :a"),
            {"new": env.ids["l3b"], "a": env.ids["gen_l3"]},
        )
        db.session.commit()
        db.session.remove()
    stamp = _evaluations(env, "emp_gen")[0]
    client = _client(env, "l3b")
    response, tx = _record(env, monkeypatch, lambda: client.get(_url(ASSIGNMENT_PATHS[0], env.ids["gen_l3"])))
    assert response.status_code == 200
    _assert_read_only(tx)
    viewed = _evaluations(env, "emp_gen")[0]
    assert viewed["level_3_evaluator_id"] == env.ids["l3"]
    assert viewed["updated_at"] == stamp["updated_at"]

    # The business write that owns the alignment persists it.
    response = client.post(
        _url(ASSIGNMENT_PATHS[0], env.ids["gen_l3"]), data={"action": "save", "general_comment": "devralan amir"}
    )
    assert response.status_code == 302
    saved = _evaluations(env, "emp_gen")[0]
    assert saved["level_3_evaluator_id"] == env.ids["l3b"]
    assert saved["level_3_general_comment"] == "devralan amir"


def test_admin_view_does_not_create_an_evaluation(env, monkeypatch):
    client = _client(env, "admin")
    before = _snapshot(env)
    response, tx = _record(env, monkeypatch, lambda: client.get(_url(ASSIGNMENT_PATHS[0], env.ids["new_l3"])))
    assert response.status_code == 200
    _assert_read_only(tx)
    assert _evaluations(env, "emp_new") == []
    assert _snapshot(env) == before


def test_first_visit_read_model_renders_like_a_fresh_persisted_evaluation(env):
    client = _client(env, "l3")
    first_visit = client.get(_url(ASSIGNMENT_PATHS[0], env.ids["new_l3"])).get_data(as_text=True)
    generated = client.get(_url(ASSIGNMENT_PATHS[0], env.ids["gen_l3"])).get_data(as_text=True)
    assert LIVE_SCORE.findall(first_visit) == LIVE_SCORE.findall(generated) != []


def test_concurrent_first_visit_gets_both_succeed_without_creating_rows(env):
    clients = [_client(env, "l3"), _client(env, "l3")]
    barrier = threading.Barrier(len(clients))
    statuses: list[int] = []
    errors: list[BaseException] = []

    def _visit(client):
        try:
            barrier.wait(timeout=10)
            statuses.append(client.get(_url(ASSIGNMENT_PATHS[0], env.ids["new_l3"])).status_code)
        except BaseException as exc:  # pragma: no cover - surfaced through the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_visit, args=(client,)) for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    assert statuses == [200, 200]
    assert _evaluations(env, "emp_new") == []


# ---------------------------------------------------------------------------
# Refused requests do no work
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "assignment", "method"),
    [
        ("intruder", "new_l3", "get"),
        ("intruder", "new_l3", "post"),
        ("l3", "pasif", "get"),
        ("l3", "pasif", "post"),
        ("l3", "muaf", "get"),
        ("l3", "muaf", "post"),
    ],
)
def test_refused_requests_do_no_work(env, monkeypatch, who, assignment, method):
    client = _client(env, who)
    before = _snapshot(env)
    url = _url(ASSIGNMENT_PATHS[0], env.ids[assignment])

    def _call():
        if method == "get":
            return client.get(url)
        return client.post(url, data={"action": "save", "general_comment": "reddedilen taslak"})

    response, tx = _record(env, monkeypatch, _call)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(_dashboard(env))
    _assert_read_only(tx)
    assert tx.readiness_calls == 0
    assert _snapshot(env) == before


@pytest.mark.parametrize("method", ["get", "post"])
def test_anonymous_requests_do_no_work(env, monkeypatch, method):
    client = env.app.test_client()
    before = _snapshot(env)
    url = _url(ASSIGNMENT_PATHS[0], env.ids["new_l3"])
    response, tx = _record(
        env,
        monkeypatch,
        lambda: client.get(url) if method == "get" else client.post(url, data={"action": "save"}),
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    _assert_read_only(tx)
    assert tx.readiness_calls == 0
    assert _snapshot(env) == before


# ---------------------------------------------------------------------------
# Explicit writes own creation, alignment and the commit
# ---------------------------------------------------------------------------


def _assert_single_route_commit(tx: Tx) -> None:
    assert tx.calls("commit") == [(ROUTE_FILE, ROUTE_VIEW)]
    assert tx.helper_calls("commit") == 0
    assert tx.helper_calls("rollback") == 0
    assert tx.engine_commits == 1
    assert tx.readiness_calls == 0


def test_first_save_creates_the_evaluation_inside_the_business_transaction(env, monkeypatch):
    client = _client(env, "l3")
    response, tx = _record(
        env,
        monkeypatch,
        lambda: client.post(
            _url(ASSIGNMENT_PATHS[0], env.ids["new_l3"]), data={"action": "save", "general_comment": "ilk taslak"}
        ),
    )
    assert response.status_code == 302
    _assert_single_route_commit(tx)
    rows = _evaluations(env, "emp_new")
    assert len(rows) == 1
    assert rows[0]["level_3_evaluator_id"] == env.ids["l3"]
    assert rows[0]["level_3_general_comment"] == "ilk taslak"
    assert rows[0]["workflow_status"] == "taslak_3_amir"
    assert _items(env, rows[0]["id"]) == 2
    assert _assignment_status(env, "new_l3") == "taslak"


def test_first_submit_creates_and_completes_in_one_transaction(env, monkeypatch):
    client = _client(env, "l3")
    response, tx = _record(
        env,
        monkeypatch,
        lambda: client.post(
            _url(ASSIGNMENT_PATHS[0], env.ids["new_l3"]), data={"action": "submit", "general_comment": "ust gorus"}
        ),
    )
    assert response.status_code == 302
    _assert_single_route_commit(tx)
    rows = _evaluations(env, "emp_new")
    assert len(rows) == 1
    assert rows[0]["level_3_completed"] in (1, True)
    assert rows[0]["level_3_general_comment"] == "ust gorus"
    assert _assignment_status(env, "new_l3") == "tamamlandi"


def test_submit_validation_failure_keeps_the_existing_draft_semantics(env, monkeypatch):
    """Level 2 is not actionable before level 3; the route keeps the inputs as a draft (existing contract)."""
    client = _client(env, "l2")
    data = {
        "action": "submit",
        "general_comment": "sirasi gelmeyen",
        f"score_{env.ids['criterion_0']}": "4",
        f"score_{env.ids['criterion_1']}": "5",
    }
    response, tx = _record(env, monkeypatch, lambda: client.post(_url(ASSIGNMENT_PATHS[0], env.ids["new_l2"]), data=data))
    assert response.status_code == 302
    _assert_single_route_commit(tx)
    rows = _evaluations(env, "emp_new")
    assert len(rows) == 1
    assert rows[0]["level_2_general_comment"] == "sirasi gelmeyen"
    assert rows[0]["level_2_completed"] in (0, False)
    assert _assignment_status(env, "new_l2") == "taslak"


def _raise_after(original, exc_type=RuntimeError):
    def _wrapped(*args, **kwargs):
        original(*args, **kwargs)
        raise exc_type("G3B injected failure")

    return _wrapped


@pytest.mark.parametrize(
    "boundary",
    ["after_evaluation_insert", "after_evaluator_alignment", "after_draft_items", "before_commit", "commit_failure"],
)
@pytest.mark.parametrize("action", ["save", "submit"])
def test_failure_before_the_business_commit_leaves_nothing_behind(env, monkeypatch, boundary, action):
    from app.extensions import db
    from app.performance import v2_routes
    from app.services.performance_v2 import evaluation_workspace

    client = _client(env, "l3")
    before = _snapshot(env)
    if boundary == "after_evaluation_insert":
        monkeypatch.setattr(
            evaluation_workspace,
            "_create_evaluation_for_write",
            _raise_after(evaluation_workspace._create_evaluation_for_write),
        )
    elif boundary == "after_evaluator_alignment":
        monkeypatch.setattr(
            evaluation_workspace,
            "_align_evaluator_for_write",
            _raise_after(evaluation_workspace._align_evaluator_for_write),
        )
    elif boundary == "after_draft_items":
        monkeypatch.setattr(evaluation_workspace, "_upsert_items", _raise_after(evaluation_workspace._upsert_items))
    elif boundary == "before_commit":
        target = "save_assignment_draft" if action == "save" else "submit_assignment"
        monkeypatch.setattr(v2_routes, target, _raise_after(getattr(v2_routes, target)))
    else:
        def _failing_commit():
            raise RuntimeError("G3B injected commit failure")

        monkeypatch.setattr(db.session, "commit", _failing_commit)

    response = client.post(
        _url(ASSIGNMENT_PATHS[0], env.ids["new_l3"]), data={"action": action, "general_comment": "yarim kalan"}
    )
    monkeypatch.undo()
    assert response.status_code == 500
    assert _snapshot(env) == before
    assert _evaluations(env, "emp_new") == []


def test_return_without_level_2_target_leaves_no_phantom_evaluation(env, monkeypatch):
    client = _client(env, "l1")
    before = _snapshot(env)
    response, tx = _record(
        env,
        monkeypatch,
        lambda: client.post(
            _url(ASSIGNMENT_PATHS[0], env.ids["solo_l1"]), data={"action": "return", "return_note": "eksik"}
        ),
    )
    assert response.status_code == 302
    assert tx.calls("commit") == []
    assert tx.helper_calls("commit") == 0
    assert tx.engine_commits == 0
    assert _evaluations(env, "emp_solo") == []
    assert _snapshot(env) == before


def test_withdraw_on_missing_evaluation_keeps_its_clean_reset_semantics(env, monkeypatch):
    client = _client(env, "l3")
    response, tx = _record(
        env, monkeypatch, lambda: client.post(_url(ASSIGNMENT_PATHS[0], env.ids["new_l3"]), data={"action": "withdraw"})
    )
    assert response.status_code == 302
    _assert_single_route_commit(tx)
    rows = _evaluations(env, "emp_new")
    assert len(rows) == 1
    assert rows[0]["workflow_status"] == "taslak_3_amir"
    assert rows[0]["level_3_completed"] in (0, False)
    assert _assignment_status(env, "new_l3") == "taslak"


def test_first_write_race_reuses_the_winning_evaluation(env, monkeypatch):
    """A competing request commits the evaluation between our lookup and our insert."""
    from app.extensions import db
    from app.services.performance_v2 import evaluation_workspace

    real_find = evaluation_workspace._find_evaluation
    competitor: dict[str, int] = {}

    def _find_then_lose_the_race(assignment):
        found = real_find(assignment)
        if found is None and not competitor:
            with db.engine.begin() as other:
                other.execute(
                    text(
                        "INSERT INTO performance_evaluations (period_id, employee_id, level_3_evaluator_id, "
                        "level_1_total_100, level_2_total_100, level_3_total_100, final_total_100, "
                        "level_1_completed, level_2_completed, level_3_completed, status, workflow_status, "
                        "is_published_to_employee, feedback_request_allowed, evaluation_exempted, "
                        "employee_leave_days_in_period, employee_absence_days_in_period, "
                        "employee_available_days_in_period, created_at, updated_at) VALUES "
                        "(:p, :e, :l3, 0, 0, 0, 0, :f, :f, :f, 'bekliyor', 'taslak_1_amir', :f, :t, :f, 0, 0, 0, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"p": assignment.period_id, "e": assignment.employee_id, "l3": assignment.evaluator_id, "f": False, "t": True},
                )
                competitor["id"] = int(
                    other.execute(
                        text("SELECT id FROM performance_evaluations WHERE period_id = :p AND employee_id = :e"),
                        {"p": assignment.period_id, "e": assignment.employee_id},
                    ).scalar_one()
                )
        return found

    monkeypatch.setattr(evaluation_workspace, "_find_evaluation", _find_then_lose_the_race)
    client = _client(env, "l3")
    response = client.post(
        _url(ASSIGNMENT_PATHS[0], env.ids["new_l3"]), data={"action": "save", "general_comment": "yarisi kaybeden"}
    )
    monkeypatch.undo()
    assert response.status_code == 302
    rows = _evaluations(env, "emp_new")
    assert [row["id"] for row in rows] == [competitor["id"]]
    assert rows[0]["level_3_general_comment"] == "yarisi kaybeden"
    assert _items(env, competitor["id"]) == 2
