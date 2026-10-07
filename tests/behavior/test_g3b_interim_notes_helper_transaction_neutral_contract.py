"""G3-B: the interim-notes readiness helper and notes reader are transaction-neutral.

``app.services.performance.interim_notes_runtime.ensure_interim_notes_table()`` only inspects
the Alembic-owned schema (revision x1f3a9c5e7b2). It must never commit, roll back or flush the
caller's session: callers own their transactions. The notes reader used by the evaluation
workspace and the scorecard must not roll back the caller's transaction as error recovery and
must not turn an unexpected database error into an empty result.

Callers covered: mobile in-period notes (read / create), mobile note-scorecard, scorecard detail
and PDF. The web interim-note create route never uses the helper and keeps its own commit.
"""

from __future__ import annotations

import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import FrameType, SimpleNamespace

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

PASSWORD = "InterimNotesNeutralTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "g3b_interim_notes_neutral" / "dbs"
_APP_DIR = Path(__file__).resolve().parents[2] / "app"
DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.I)
DDL = re.compile(r"^\s*(CREATE|ALTER|DROP)\b", re.I)
HELPER_FILE = "interim_notes_runtime.py"
NOT_READY = "Dönem içi not tablosu hazır değil; veritabanı migration'ı (flask db upgrade) çalıştırılmalıdır."
GUIDANCE_MARKER = "G3B-KANONIK-GELISIM"
NOTE_MARKER = "G3B-KARNE-NOTU"


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-g3b-interim-notes-neutral",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "g3b-interim-notes-neutral-first-login",
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


def _new_app(monkeypatch):
    from app.extensions import db

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    with app.app_context():
        db.create_all()
    return app, db_file


def _dispose(app, db_file) -> None:
    from app.extensions import db

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


@pytest.fixture
def bare_app(monkeypatch):
    app, db_file = _new_app(monkeypatch)
    yield app
    _dispose(app, db_file)


@pytest.fixture
def ready_app(monkeypatch, install_interim_notes_schema):
    app, db_file = _new_app(monkeypatch)
    from app.extensions import db

    with app.app_context():
        install_interim_notes_schema(db.engine)
    yield app
    _dispose(app, db_file)


@pytest.fixture
def env(monkeypatch, install_interim_notes_schema, install_development_recommendations_schema):
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod, User

    app, db_file = _new_app(monkeypatch)
    ids: dict[str, int] = {}
    with app.app_context():
        install_interim_notes_schema(db.engine)
        install_development_recommendations_schema(db.engine)
        for key, role in (("baskan", "baskan"), ("admin", "admin"), ("owner", "personel"), ("evaluator", "personel"), ("other", "personel")):
            sicil = f"G3BN{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Not",
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
            title="Not Donemi",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
            results_published=True,
        )
        db.session.add(period)
        db.session.flush()
        ids["period"] = int(period.id)
        evaluation = PerformanceEvaluation(
            period_id=period.id,
            employee_id=ids["owner"],
            level_1_evaluator_id=ids["evaluator"],
            status="tamamlandi",
            workflow_status="tamamlandi",
            is_published_to_employee=True,
            level_1_completed=True,
            final_total_100=80,
        )
        db.session.add(evaluation)
        db.session.add(
            EvaluationAssignment(
                period_id=period.id, employee_id=ids["owner"], evaluator_id=ids["evaluator"], manager_level=1, status="tamamlandi"
            )
        )
        db.session.flush()
        ids["evaluation"] = int(evaluation.id)
        db.session.execute(
            text(
                "INSERT INTO performance_development_recommendations (employee_id, employee_name, period_id, period_name, "
                "recommendation_type, development_area, priority, recommendation_text, visibility_scope, publication_status, "
                "show_on_scorecard, is_published, supervisor_approval_required, supervisor_approved, hr_publish_required, "
                "hr_publish_approved, publish_lock, scorecard_visibility_mode, scorecard_detail_level, updated_at) VALUES "
                "(:e, 'Not Owner', :p, 'Not Donemi', 'improvement_plan', 'communication', 'high', :t, 'scorecard', "
                "'published', :y, :y, :y, :y, :y, :y, :n, 'after_publish', 'summary', :u)"
            ),
            {"e": ids["owner"], "p": ids["period"], "t": f"{GUIDANCE_MARKER}: iletisim plani", "y": True, "n": False, "u": datetime(2026, 4, 1, 9, 0, 0)},
        )
        db.session.execute(
            text(
                "INSERT INTO performance_interim_notes (period_id, employee_id, employee_user_id, manager_id, created_by, "
                "created_by_id, note_type, title, note, note_body, visibility_level, visibility_scope, remind_during_scoring, "
                "remind_in_evaluation, include_in_scorecard, visible_on_scorecard, is_active, active, occurred_at, created_at, "
                "updated_at) VALUES (:p, :e, :e, :m, :m, :m, 'basari', :t, :t, :t, 'manager_scope', 'manager_scope', :y, :y, "
                ":y, :y, :y, :y, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"p": ids["period"], "e": ids["owner"], "m": ids["evaluator"], "t": NOTE_MARKER, "y": True},
        )
        db.session.commit()
        db.session.remove()
    yield SimpleNamespace(app=app, ids=ids)
    _dispose(app, db_file)


def _client(env, who):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": f"G3BN{who.upper()}", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _mobile_headers(env, who) -> dict[str, str]:
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[who])
        assert user is not None
        token = _issue_token(user)
        db.session.remove()
    return {"Authorization": f"Bearer {token}"}


def _origin() -> tuple[tuple[str, str] | None, bool]:
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
    ddl: list[str] = field(default_factory=list)
    engine_commits: int = 0
    session: list[tuple[str, tuple[str, str] | None, bool]] = field(default_factory=list)

    def calls(self, method: str) -> list[tuple[str, str] | None]:
        return [origin for name, origin, _helper in self.session if name == method]

    def helper_calls(self, method: str) -> int:
        return sum(1 for name, _origin, helper in self.session if name == method and helper)


def _record(app, monkeypatch, call):
    from app.extensions import db

    tx = Tx()
    with app.app_context():
        engine = db.engine

    def _on_sql(conn, cursor, statement, parameters, context, executemany):
        if DML.match(statement or ""):
            tx.dml.append(" ".join(statement.split()[:3]))
        if DDL.match(statement or ""):
            tx.ddl.append(" ".join(statement.split()[:4]))

    def _on_commit(conn):
        tx.engine_commits += 1

    with monkeypatch.context() as patch:
        for method in ("commit", "rollback", "flush"):
            original = getattr(db.session, method)

            def _wrapper(*args, _method=method, _original=original, **kwargs):
                origin, helper = _origin()
                tx.session.append((_method, origin, helper))
                return _original(*args, **kwargs)

            patch.setattr(db.session, method, _wrapper)
        event.listen(engine, "before_cursor_execute", _on_sql)
        event.listen(engine, "commit", _on_commit)
        try:
            result = call()
        finally:
            event.remove(engine, "before_cursor_execute", _on_sql)
            event.remove(engine, "commit", _on_commit)
    return result, tx


def _forbid_session_transaction_control(monkeypatch) -> None:
    from app.extensions import db

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("readiness must not control the caller's transaction")

    for method in ("commit", "rollback", "flush"):
        monkeypatch.setattr(db.session, method, _forbidden)


def _pending_user(db, suffix: str):
    from app.models import User

    user = User(
        sicil_no=f"G3BPENDING{suffix}",
        email=f"g3b-pending-{suffix}@example.gov.tr",
        ad="Bekleyen",
        soyad="Kayit",
        role="personel",
        is_active=True,
        must_change_password=False,
        must_set_security_question=False,
    )
    user.set_password(PASSWORD)
    db.session.add(user)
    return user


def _users_with_sicil(app, sicil: str) -> int:
    from app.extensions import db

    with db.engine.connect() as other:
        return int(other.execute(text("SELECT COUNT(*) FROM users WHERE sicil_no = :s"), {"s": sicil}).scalar() or 0)


def _note_rows(app) -> int:
    from app.extensions import db

    with app.app_context(), db.engine.connect() as other:
        return int(other.execute(text("SELECT COUNT(*) FROM performance_interim_notes")).scalar() or 0)


# ---------------------------------------------------------------------------
# The readiness helper only inspects
# ---------------------------------------------------------------------------


def test_canonical_schema_readiness_does_not_touch_the_session(ready_app, monkeypatch):
    from app.extensions import db
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    with ready_app.app_context():
        pending = _pending_user(db, "CANON")
        new_before, dirty_before, identity_before = set(db.session.new), set(db.session.dirty), set(db.session.identity_map.keys())
        with monkeypatch.context() as patch:
            _forbid_session_transaction_control(patch)
            assert ensure_interim_notes_table() == (True, [])
        assert set(db.session.new) == new_before == {pending}
        assert set(db.session.dirty) == dirty_before
        assert set(db.session.identity_map.keys()) == identity_before
        db.session.rollback()


@pytest.mark.parametrize("shape", ["absent", "missing_index"])
def test_not_ready_schema_keeps_the_readiness_contract_without_repair(bare_app, monkeypatch, install_interim_notes_schema, shape):
    from app.extensions import db
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    with bare_app.app_context():
        if shape == "missing_index":
            install_interim_notes_schema(db.engine)
            with db.engine.begin() as connection:
                connection.execute(text("DROP INDEX ix_perf_interim_notes_employee_period"))
        catalog_before = sorted(inspect(db.engine).get_table_names())
        with monkeypatch.context() as patch:
            _forbid_session_transaction_control(patch)
            result, tx = _record(bare_app, patch, ensure_interim_notes_table)
        assert result == (False, [NOT_READY])
        assert tx.ddl == [] and tx.dml == [] and tx.engine_commits == 0
        assert sorted(inspect(db.engine).get_table_names()) == catalog_before


def test_readiness_never_commits_unrelated_pending_work(ready_app):
    from app.extensions import db
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    with ready_app.app_context():
        pending = _pending_user(db, "UNRELATED")
        assert ensure_interim_notes_table() == (True, [])
        assert pending in db.session.new
        assert _users_with_sicil(ready_app, "G3BPENDINGUNRELATED") == 0
        db.session.rollback()
        assert _users_with_sicil(ready_app, "G3BPENDINGUNRELATED") == 0


# ---------------------------------------------------------------------------
# The notes reader preserves the caller's transaction
# ---------------------------------------------------------------------------


def _insert_note(db, *, employee_id: int, title: str, created_at: str | None) -> None:
    db.session.execute(
        text(
            "INSERT INTO performance_interim_notes (period_id, employee_id, employee_user_id, note_type, title, note, note_body, "
            "include_in_scorecard, visible_on_scorecard, is_active, active, created_at) VALUES "
            "(NULL, :e, :e, 'genel_gozlem', :t, :t, :t, :y, :y, :y, :y, :c)"
        ),
        {"e": employee_id, "t": title, "y": True, "c": created_at},
    )


def test_notes_reader_keeps_caller_pending_work_and_orders_nulls_last(env):
    from app.extensions import db
    from app.models import EvaluationAssignment
    from app.services.performance.interim_notes_runtime import build_interim_notes_context

    with env.app.app_context():
        _insert_note(db, employee_id=env.ids["other"], title="NULL-TARIH", created_at=None)
        _insert_note(db, employee_id=env.ids["other"], title="ESKI", created_at="2026-01-05 10:00:00")
        _insert_note(db, employee_id=env.ids["other"], title="YENI", created_at="2026-02-05 10:00:00")
        db.session.commit()
        pending = _pending_user(db, "READER")
        assignment = EvaluationAssignment(period_id=env.ids["period"], employee_id=env.ids["other"], evaluator_id=env.ids["evaluator"], manager_level=1)
        context = build_interim_notes_context(assignment=assignment)
        assert [note["title"] for note in context["notes"]] == ["YENI", "ESKI", "NULL-TARIH"]
        assert pending in db.session.new
        assert _users_with_sicil(env.app, "G3BPENDINGREADER") == 0
        db.session.rollback()


def test_notes_reader_does_not_hide_database_errors_or_roll_back_the_caller(env, monkeypatch):
    from app.extensions import db
    from app.models import EvaluationAssignment
    from app.services.performance.interim_notes_runtime import build_interim_notes_context

    with env.app.app_context():
        rollbacks: list[str] = []
        real_execute = db.session.execute

        def _failing_notes_select(statement, *args, **kwargs):
            if "FROM performance_interim_notes" in str(statement):
                raise OperationalError(str(statement), {}, Exception("G3B injected read failure"))
            return real_execute(statement, *args, **kwargs)

        pending = _pending_user(db, "FAILURE")
        assignment = EvaluationAssignment(period_id=env.ids["period"], employee_id=env.ids["owner"], evaluator_id=env.ids["evaluator"], manager_level=1)
        with monkeypatch.context() as patch:
            patch.setattr(db.session, "execute", _failing_notes_select)
            patch.setattr(db.session, "rollback", lambda: rollbacks.append("rollback"))
            with pytest.raises(OperationalError):
                build_interim_notes_context(assignment=assignment)
        assert rollbacks == []
        assert pending in db.session.new
        db.session.rollback()


# ---------------------------------------------------------------------------
# Mobile notes and note-scorecard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/mobile/performance/in-period-notes/v2", "/api/mobile/performance/note-scorecard"])
def test_mobile_note_reads_do_not_commit(env, monkeypatch, path):
    client = env.app.test_client()
    headers = _mobile_headers(env, "evaluator")
    response, tx = _record(env.app, monkeypatch, lambda: client.get(path, headers=headers))
    assert response.status_code == 200
    assert NOTE_MARKER in response.get_data(as_text=True)
    assert tx.helper_calls("commit") == 0
    assert tx.calls("commit") == []
    assert tx.dml == [] and tx.engine_commits == 0


def test_mobile_note_create_commits_only_through_its_own_business_write(env, monkeypatch):
    client = env.app.test_client()
    headers = _mobile_headers(env, "evaluator")
    before = _note_rows(env.app)
    response, tx = _record(
        env.app,
        monkeypatch,
        lambda: client.post(
            "/api/mobile/performance/in-period-notes/v2",
            json={"note": "G3B mobil not", "employee_id": env.ids["owner"], "period_id": env.ids["period"]},
            headers=headers,
        ),
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert tx.helper_calls("commit") == 0
    assert tx.calls("commit") == [
        ("api/mobile/services/performance_note_route_services.py", "phase3c_mobile_performance_create_in_period_note_v2853_service")
    ]
    assert tx.engine_commits == 1
    assert _note_rows(env.app) == before + 1


@pytest.mark.parametrize(
    ("payload", "status"),
    [({"note": "   "}, 400), ({"note": "baskasina not", "employee_id": "OTHER"}, 403)],
)
def test_mobile_note_create_refusals_commit_nothing(env, monkeypatch, payload, status):
    client = env.app.test_client()
    headers = _mobile_headers(env, "evaluator")
    body = dict(payload)
    if body.get("employee_id") == "OTHER":
        body["employee_id"] = env.ids["other"]
    before = _note_rows(env.app)
    response, tx = _record(
        env.app, monkeypatch, lambda: client.post("/api/mobile/performance/in-period-notes/v2", json=body, headers=headers)
    )
    assert response.status_code == status
    assert tx.calls("commit") == []
    assert tx.engine_commits == 0 and tx.dml == []
    assert _note_rows(env.app) == before


def test_mobile_note_create_write_failure_rolls_back_the_note(env, monkeypatch):
    from app.extensions import db

    client = env.app.test_client()
    headers = _mobile_headers(env, "evaluator")
    before = _note_rows(env.app)

    def _failing_commit():
        raise RuntimeError("G3B injected mobile commit failure")

    monkeypatch.setattr(db.session, "commit", _failing_commit)
    response = client.post(
        "/api/mobile/performance/in-period-notes/v2",
        json={"note": "kaydedilmeyecek", "employee_id": env.ids["owner"]},
        headers=headers,
    )
    monkeypatch.undo()
    assert response.status_code == 500
    assert response.get_json()["message"] == "Dönem içi not kaydedilemedi. Lütfen tekrar deneyin."
    assert _note_rows(env.app) == before


# ---------------------------------------------------------------------------
# Web interim-note create keeps its own explicit commit and never uses the helper
# ---------------------------------------------------------------------------


def test_web_interim_note_create_success_and_failure_keep_their_owner(env, monkeypatch):
    from app.extensions import db
    from app.services.performance import interim_notes_runtime

    helper_calls: list[int] = []

    def _tracked_ready():
        helper_calls.append(1)
        return True, []

    monkeypatch.setattr(interim_notes_runtime, "ensure_interim_notes_table", _tracked_ready)
    client = _client(env, "admin")
    before = _note_rows(env.app)
    data = {"employee_id": env.ids["owner"], "period_id": env.ids["period"], "note_type": "basari", "note": "web notu"}
    response, tx = _record(env.app, monkeypatch, lambda: client.post("/performance/interim-notes/create", data=data))
    assert response.status_code == 302
    assert tx.calls("commit") == [("performance/interim_notes_manager_routes.py", "performance_interim_notes_create")]
    assert _note_rows(env.app) == before + 1

    real_execute = db.session.execute

    def _failing_insert(statement, *args, **kwargs):
        if "INSERT INTO performance_interim_notes" in str(statement):
            raise SQLAlchemyError("G3B injected web insert failure")
        return real_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db.session, "execute", _failing_insert)
    response = client.post("/performance/interim-notes/create", data=data)
    assert response.status_code == 302
    assert _note_rows(env.app) == before + 1
    assert helper_calls == []


# ---------------------------------------------------------------------------
# Scorecard detail / PDF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("viewer", ["baskan", "admin", "owner"])
@pytest.mark.parametrize("suffix", ["", "/pdf"])
def test_scorecard_detail_and_pdf_render_canonical_guidance_without_commits(env, monkeypatch, viewer, suffix):
    from app.services.performance import interim_notes_runtime

    client = _client(env, viewer)
    url = f"/performance/scorecard/{env.ids['evaluation']}{suffix}"
    response, tx = _record(env.app, monkeypatch, lambda: client.get(url))
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert body.count(GUIDANCE_MARKER) == 1
    assert tx.helper_calls("commit") == 0 and tx.helper_calls("rollback") == 0
    if viewer == "owner" and suffix == "":
        # Existing explicit business write owned by the detail route: the employee's first view
        # of the published scorecard records employee_score_viewed_at.
        assert tx.calls("commit") == [("performance/evaluation_core_routes.py", "performance_scorecard_detail")]
        assert tx.dml == ["UPDATE performance_evaluations SET"] and tx.engine_commits == 1
    else:
        assert tx.calls("commit") == []
        assert tx.dml == [] and tx.engine_commits == 0

    with monkeypatch.context() as patch:
        patch.setattr(interim_notes_runtime, "ensure_interim_notes_table", lambda: (True, []))
        stubbed = client.get(url)
    assert stubbed.status_code == response.status_code
    assert stubbed.get_data(as_text=True).count(GUIDANCE_MARKER) == body.count(GUIDANCE_MARKER)
    assert stubbed.get_data(as_text=True).count(NOTE_MARKER) == body.count(NOTE_MARKER)
