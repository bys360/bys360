"""BYS360 PERFORMANCE P0.2M: 70-altı process page view-model contract.

Page: GET /performance/low-score-processes (main.performance_low_score_processes,
app/performance/low_score_process_routes.py), template
performance_low_score_processes.html.

Verified at a35ce5abb2607f040d23666b682a382c76f552e5 (P0.2L): the route passed
the PerformancePeriod itself to build_low_score_process_rows(), which iterates
a process collection -> TypeError -> 500 whenever a period existed; and the
helper's rows lacked most fields the template reads, so even a corrected route
failed (jinja2 UndefinedError on row.process).

Since P0.2M one row contract serves route, builder and template:

- the route passes the period's processes (ordered by id) to
  build_low_score_process_rows();
- each row carries the ORM process/evaluation (needed for the action forms and
  the scorecard link) plus presentation fields;
- row.timeline is the CURRENT workflow checklist (not an audit trail): the same
  steps and done-conditions as the step events created by
  ensure_low_score_process_for_evaluation(), is_current = first step not done;
- row.events_history ("Süreç Geçmişi") is built from process fields only;
  actor_name comes solely from that step's own *_by relation, otherwise None.

No new dependency on performance_low_score_process_events (schema parity is an
open question, P0.2I/P0.2J). Actor/event semantics (P0.2H) are unchanged.

Real Flask app, real test client and login, file-backed SQLite test database only.
"""
from __future__ import annotations

import importlib
import re
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "app" / "templates" / "performance_low_score_processes.html"
_PAGE_URL = "/performance/low-score-processes"
_EMPTY_MESSAGE = "Bu dönem için 70 altı süreç kaydı görünmüyor."
# The row badge (the summary card also contains the words "Yayına hazır").
_READY_BADGE = '<span class="low-status ready"><i class="fa-solid fa-check"></i> Yayına hazır</span>'
_PASSWORD = "TestProcessPageContract1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02m_page")
_ROW_KEYS = {
    "id", "process", "evaluation", "employee_name", "sicil_no", "birim", "period_title", "sequence_label", "score",
    "status_label", "ready_for_publish", "owner_label", "timeline", "events_history",
    "approval_note", "rejection_note", "process_note",
}
_TIMELINE_KEYS = {"key", "title", "is_done", "is_current", "note"}
_HISTORY_KEYS = {"key", "title", "status", "actor_name", "note"}
# _sync_current_stage() stage -> the checklist step that is still open (None = all done).
_STAGE_TO_CURRENT_STEP = {
    "president_approval_pending": "president_approval",
    "president_returned": "president_approval",
    "president_approved_pending_warning": "first_warning_record",
    "president_approved_pending_admin_process": "second_repeat_admin_process",
    "first_low_warning": None,
    "second_low_repeat": None,
}
_counter = 0


# ---------------------------------------------------------------------------
# Real Flask app + file-backed SQLite (same pattern as
# tests/behavior/test_low_score_process_service_workflow_contract.py::_make_app).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p02m-page-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "test-password",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02m_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

    from sqlalchemy import event

    from app.extensions import db

    with flask_app.app_context():

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
    return flask_app


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _user(flask_app, *, role: str, birim: str | None = None) -> tuple[int, str]:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        n = _next()
        sicil_no = f"P2M{n:06d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02m-page-{n}@bys360.test",
            ad="P02M",
            soyad=f"Kullanici{n}",
            role=role,
            birim=birim,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return int(user.id), sicil_no


def _login(client, sicil_no: str):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": _PASSWORD}, follow_redirects=False)
    assert response.status_code == 302
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)  # the login's own "Giriş başarılı." flash
    return response


@pytest.fixture
def page_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """App + logged-in admin client. Only the live menu matrix is bypassed (same
    as tests/behavior/test_h1f_route_exception_leak_contract.py); login_required
    and admin_required run for real."""
    flask_app = _make_app(monkeypatch)
    monkeypatch.setattr(importlib.import_module("app.route_support"), "can_access_menu", lambda user, key: True)
    admin_id, admin_sicil = _user(flask_app, role="admin")
    client = flask_app.test_client()
    _login(client, admin_sicil)
    return SimpleNamespace(app=flask_app, client=client, admin_id=admin_id)


def _seed_period(flask_app, scores: list[float], *, birim: str | None = "Test Birimi") -> tuple[int, list[int]]:
    """One period, one completed evaluation per score (one employee each)."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    employee_ids = [_user(flask_app, role="personel", birim=birim)[0] for _score in scores]
    with flask_app.app_context():
        period = PerformancePeriod(
            title=f"P0.2M Dönem {_next()}",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        )
        db.session.add(period)
        db.session.flush()
        evaluation_ids = []
        for score, employee_id in zip(scores, employee_ids, strict=True):
            evaluation = PerformanceEvaluation(
                period_id=period.id,
                employee_id=employee_id,
                final_total_100=score,
                status="completed",
                workflow_status="tamamlandi",
                level_1_completed=True,
            )
            db.session.add(evaluation)
            db.session.flush()
            evaluation_ids.append(evaluation.id)
        db.session.commit()
        return period.id, evaluation_ids


def _process_ids(flask_app, period_id: int) -> list[int]:
    from app.extensions import db

    with flask_app.app_context():
        return [row[0] for row in db.session.execute(text("SELECT id FROM performance_low_score_processes WHERE period_id = :p ORDER BY id"), {"p": period_id}).all()]


def _display_name(flask_app, user_id: int) -> str:
    from app.extensions import db
    from app.models import User

    svc = importlib.import_module(_SERVICE_MODULE)
    with flask_app.app_context():
        return svc._full_name(db.session.get(User, user_id))


def _get_page(env: SimpleNamespace, period_id: int | None) -> tuple[int, str]:
    url = _PAGE_URL + (f"?period_id={period_id}" if period_id else "")
    response = env.client.get(url)
    return response.status_code, response.get_data(as_text=True)


def _rows(flask_app, period_id: int) -> list[dict[str, Any]]:
    from app.models import PerformanceLowScoreProcess

    svc = importlib.import_module(_SERVICE_MODULE)
    with flask_app.app_context():
        processes = PerformanceLowScoreProcess.query.filter_by(period_id=period_id).order_by(PerformanceLowScoreProcess.id.asc()).all()
        rows = svc.build_low_score_process_rows(processes)
        # Detach-safe copies of what the assertions need.
        return [{**row, "process": row["process"].id, "evaluation": getattr(row["evaluation"], "id", None)} for row in rows]


# ---------------------------------------------------------------------------
# Route matrix (A-J)
# ---------------------------------------------------------------------------


def test_page_without_any_period_renders_empty_state(page_env) -> None:
    status, body = _get_page(page_env, None)
    assert status == 200
    assert _EMPTY_MESSAGE in body


def test_page_with_period_but_no_low_score_process_renders_empty_state(page_env) -> None:
    """Before P0.2M: 500 (TypeError, the period was passed to the row builder)."""
    period_id, _ids = _seed_period(page_env.app, [88.0])
    status, body = _get_page(page_env, period_id)
    assert status == 200
    assert _EMPTY_MESSAGE in body
    assert _process_ids(page_env.app, period_id) == []


def test_page_with_one_pending_process_renders_row_checklist_and_no_actor(page_env) -> None:
    """Before P0.2M: 500. Pending workflow, no actor anywhere: no invented actor."""
    period_id, _ids = _seed_period(page_env.app, [57.0])
    status, body = _get_page(page_env, period_id)
    assert status == 200
    assert _EMPTY_MESSAGE not in body
    (row,) = _rows(page_env.app, period_id)
    assert row["employee_name"] in body
    assert row["sicil_no"] in body
    assert "Test Birimi" in body
    assert "1. 70 altı sonuç" in body
    for step in row["timeline"]:
        assert step["title"] in body
    assert [step["key"] for step in row["timeline"] if step["is_current"]] == ["president_approval"]
    assert row["events_history"] == []
    assert "İşlem yapan" not in body
    assert "None" not in body


def test_page_with_multiple_processes_renders_every_row_in_id_order(page_env) -> None:
    period_id, _ids = _seed_period(page_env.app, [57.0, 44.0, 61.0])
    status, body = _get_page(page_env, period_id)
    assert status == 200
    rows = _rows(page_env.app, period_id)
    assert [row["process"] for row in rows] == _process_ids(page_env.app, period_id)
    positions = [body.index(f'<div class="low-person">{row["employee_name"]}</div>') for row in rows]
    assert positions == sorted(positions)


def test_page_shows_approving_actor_and_publish_ready_state(page_env) -> None:
    """Approved first low score (the approval auto-records the warning): every
    checklist step done, publish-ready badge, the approver's name from
    president_approved_by."""
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    svc = importlib.import_module(_SERVICE_MODULE)
    period_id, _ids = _seed_period(page_env.app, [57.0])
    _get_page(page_env, period_id)  # the page itself creates the process (existing GET contract)
    president_id, _s = _user(page_env.app, role="baskan")
    (process_id,) = _process_ids(page_env.app, period_id)
    with page_env.app.app_context():
        svc.president_approve_process(db.session.get(PerformanceLowScoreProcess, process_id), actor=president_id, note="Onay notu P0.2M")
        db.session.commit()

    status, body = _get_page(page_env, period_id)
    assert status == 200
    (row,) = _rows(page_env.app, period_id)
    assert row["ready_for_publish"] is True
    assert all(step["is_done"] for step in row["timeline"])
    assert not any(step["is_current"] for step in row["timeline"])
    (approval,) = [item for item in row["events_history"] if item["key"] == "president_approval"]
    assert approval["actor_name"] == _display_name(page_env.app, president_id)
    assert f"İşlem yapan: {approval['actor_name']}" in body
    assert "Başkan/Üst Onay tamamlandı" in body
    assert "Onay notu P0.2M" in body
    assert _READY_BADGE in body


def test_page_shows_rejected_state_with_the_rejecting_actor(page_env) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    svc = importlib.import_module(_SERVICE_MODULE)
    period_id, _ids = _seed_period(page_env.app, [57.0])
    _get_page(page_env, period_id)
    president_id, _s = _user(page_env.app, role="baskan")
    (process_id,) = _process_ids(page_env.app, period_id)
    with page_env.app.app_context():
        svc.president_reject_process(db.session.get(PerformanceLowScoreProcess, process_id), actor=president_id, note="İade notu P0.2M")
        db.session.commit()

    status, body = _get_page(page_env, period_id)
    assert status == 200
    (row,) = _rows(page_env.app, period_id)
    assert row["ready_for_publish"] is False
    assert [step["key"] for step in row["timeline"] if step["is_current"]] == ["president_approval"]
    (rejection,) = row["events_history"]
    assert (rejection["key"], rejection["status"], rejection["note"]) == ("president_rejected", "Başkan/Üst Onay tarafından iade edildi", "İade notu P0.2M")
    assert rejection["actor_name"] == _display_name(page_env.app, president_id)
    assert "Başkan/Üst Onay tarafından iade edildi" in body
    assert "İade notu P0.2M" in body
    assert _READY_BADGE not in body


def test_page_row_without_birim_renders_no_placeholder(page_env) -> None:
    period_id, _ids = _seed_period(page_env.app, [57.0], birim=None)
    status, body = _get_page(page_env, period_id)
    assert status == 200
    (row,) = _rows(page_env.app, period_id)
    assert row["birim"] is None
    assert "None" not in body


# ---------------------------------------------------------------------------
# Row / checklist / history contract (real ORM processes)
# ---------------------------------------------------------------------------


def _set_state(process, **fields: Any) -> None:
    for name, value in fields.items():
        setattr(process, name, value)


@pytest.mark.parametrize(
    ("state", "sequence_no"),
    [
        ({}, 1),
        ({"president_rejected_at": "now"}, 1),
        ({"president_approved_at": "now"}, 1),
        ({"president_approved_at": "now"}, 2),
        ({"president_approved_at": "now", "warning_recorded_at": "now"}, 1),
        ({"president_approved_at": "now", "administrative_process_started_at": "now"}, 2),
        ({"warning_recorded_at": "now"}, 1),
    ],
    ids=["pending", "rejected", "approved_pending_warning", "approved_pending_admin", "first_finalized", "second_finalized", "warning_before_approval"],
)
def test_checklist_current_step_matches_the_existing_stage_machine(page_env, state, sequence_no) -> None:
    """is_current (first step not done) must agree with _sync_current_stage()
    in every reachable state; done-conditions are ensure()'s event statuses."""
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    svc = importlib.import_module(_SERVICE_MODULE)
    period_id, _ids = _seed_period(page_env.app, [57.0])
    _get_page(page_env, period_id)
    (process_id,) = _process_ids(page_env.app, period_id)
    with page_env.app.app_context():
        process = db.session.get(PerformanceLowScoreProcess, process_id)
        assert process is not None
        process.sequence_no = sequence_no
        _set_state(process, **{name: utc_now() for name in state})
        svc._sync_current_stage(process)
        (row,) = svc.build_low_score_process_rows([process])
        timeline = row["timeline"]
        assert [set(step) for step in timeline] == [_TIMELINE_KEYS] * 5
        expected_branch = "second_repeat_admin_process" if sequence_no >= 2 else "first_warning_record"
        assert [step["key"] for step in timeline] == ["evaluation_completed", "low_score_detected", "president_approval", expected_branch, "publish_release"]
        assert [step["title"] for step in timeline] == [svc._event_title(step["key"]) for step in timeline]
        current = [step["key"] for step in timeline if step["is_current"]]
        assert current == ([_STAGE_TO_CURRENT_STEP[process.current_stage_key]] if _STAGE_TO_CURRENT_STEP[process.current_stage_key] else [])
        assert timeline[-1]["is_done"] is process.is_finalized_for_publish
        db.session.rollback()


def test_row_and_history_item_keys_are_the_canonical_contract(page_env) -> None:
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    svc = importlib.import_module(_SERVICE_MODULE)
    period_id, _ids = _seed_period(page_env.app, [57.0])
    _get_page(page_env, period_id)
    president_id, _s = _user(page_env.app, role="baskan")
    (process_id,) = _process_ids(page_env.app, period_id)
    with page_env.app.app_context():
        process = db.session.get(PerformanceLowScoreProcess, process_id)
        assert process is not None
        svc.president_reject_process(process, actor=president_id, note="iade")
        svc.add_low_score_process_note(process, user_or_id=None, note="not, kaydedeni bilinmiyor")
        db.session.commit()
        (row,) = svc.build_low_score_process_rows([process])
        assert set(row) == _ROW_KEYS
        assert row["process"] is process
        assert row["evaluation"] is process.evaluation
        assert [set(item) for item in row["events_history"]] == [_HISTORY_KEYS, _HISTORY_KEYS]
        assert [item["key"] for item in row["events_history"]] == ["president_rejected", "process_note"]
        note_item = row["events_history"][1]
        assert (note_item["status"], note_item["actor_name"]) == (None, None)  # no *_by recorded -> no actor invented
        assert row["events_history"] == svc.build_process_timeline(process)


def test_template_reads_only_fields_the_builder_produces() -> None:
    """Static guard: every row.* / step.* the template reads exists in the contract."""
    source = _TEMPLATE_PATH.read_text(encoding="utf-8")
    row_fields = set(re.findall(r"\brow\.(\w+)", source))
    assert row_fields <= _ROW_KEYS, row_fields - _ROW_KEYS
    timeline_loop = re.search(r"{%\s*for step in row\.timeline\s*%}(.*?){%\s*endfor\s*%}", source, re.S)
    history_loop = re.search(r"{%\s*for step in row\.events_history\s*%}(.*?){%\s*endfor\s*%}", source, re.S)
    assert timeline_loop and history_loop
    assert set(re.findall(r"\bstep\.(\w+)", timeline_loop.group(1))) <= _TIMELINE_KEYS
    assert set(re.findall(r"\bstep\.(\w+)", history_loop.group(1))) <= _HISTORY_KEYS
    for block in ("title", "extra_head", "page_kicker", "page_title", "page_subtitle"):
        match = re.search(r"{%\s*block " + block + r"\s*%}(.*?){%\s*endblock\s*%}", source, re.S)
        assert match and "<section" not in match.group(1), block


# ---------------------------------------------------------------------------
# Action -> commit -> redirect -> page
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "data", "flash_text", "column"),
    [
        ("president-approve", {"note": "Onay"}, "Başkan onayı kaydedildi.", "president_approved_at"),
        ("president-reject", {"note": "İade"}, "Başkan/Üst Onay iadesi kaydedildi.", "president_rejected_at"),
        ("note", {"note": "Süreç notu"}, "Süreç notu kaydedildi.", "process_note"),
        ("record-warning", {}, "Personel uyarı/süreç kaydı oluşturuldu.", "warning_recorded_at"),
        ("start-admin-process", {}, "İkinci 70 altı sonucuna ilişkin idari süreç kaydı oluşturuldu.", "administrative_process_started_at"),
    ],
    ids=["approve", "reject", "note", "record_warning", "start_admin_process"],
)
def test_action_redirects_to_a_working_page(page_env, action, data, flash_text, column) -> None:
    """Before P0.2M every one of these committed and then redirected to a 500 page."""
    from app.extensions import db

    period_id, _ids = _seed_period(page_env.app, [57.0])
    _get_page(page_env, period_id)
    (process_id,) = _process_ids(page_env.app, period_id)
    response = page_env.client.post(f"/performance/low-score-process/{process_id}/{action}", data=data, follow_redirects=True)
    assert response.status_code == 200
    with page_env.app.test_request_context():
        from flask import url_for

        page_path = url_for("main.performance_low_score_processes")
    assert response.request.path == page_path  # the redirect target of every action route
    body = response.get_data(as_text=True)
    assert flash_text in body
    with page_env.app.app_context():
        value = db.session.execute(text(f"SELECT {column} FROM performance_low_score_processes WHERE id = :p"), {"p": process_id}).scalar()
    assert value  # the action itself was committed


# ---------------------------------------------------------------------------
# Access control and GET side effect (existing contracts, unchanged)
# ---------------------------------------------------------------------------


def test_access_control_is_unchanged(page_env) -> None:
    _uid, personel_sicil = _user(page_env.app, role="personel")
    personel = page_env.app.test_client()
    _login(personel, personel_sicil)
    assert personel.get(_PAGE_URL).status_code == 403
    anonymous = page_env.app.test_client().get(_PAGE_URL)
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].startswith("/login")


def test_get_page_still_creates_missing_processes(page_env) -> None:
    """Existing contract kept as-is: viewing the page runs the period sync and
    commits it (a GET that writes; reported, not changed in P0.2M)."""
    period_id, _ids = _seed_period(page_env.app, [57.0, 44.0])
    assert _process_ids(page_env.app, period_id) == []
    status, _body = _get_page(page_env, period_id)
    assert status == 200
    assert len(_process_ids(page_env.app, period_id)) == 2
