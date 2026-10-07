"""Scorecard development guidance reads the one canonical Phase-10 recommendation contract.

``performance_development_recommendations`` has a single schema: the 47 columns adopted by
Alembic revision 29fee38a97e1. The scorecard detail page and the scorecard PDF must show the
same "safe to show on the scorecard" set (``app/performance/phase10_development_guidance_ui.py``):
shown on the scorecard, published, not locked, approvals complete, visibility mode
after_publish/after_ack, same employee, same period (or period-agnostic).

The former P4 reader selected and filtered columns that do not exist in that schema
(source, title, is_required, status, approved_by, approved_at, evaluation_id,
employee_user_id); PostgreSQL rejected it (42703) and left the transaction aborted (25P02).
"""

from __future__ import annotations

import re
import tempfile
import traceback
import uuid
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

PASSWORD = "ScorecardGuidanceContractTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "scorecard_guidance_contract" / "dbs"

SAFE_NEW = "KANONIK-GORUNUR-YENI"
SAFE_OLD = "KANONIK-GORUNUR-ESKI"
HIDDEN_MARKERS = {
    "draft": "TASLAK-IC-KAYIT",
    "locked": "YAYIN-KILITLI-KAYIT",
    "pending_hr": "IK-ONAYI-BEKLEYEN-KAYIT",
    "internal_mode": "IC-GORUNURLUK-KAYIT",
    "other_employee": "BASKA-PERSONEL-KAYIT",
    "other_period": "BASKA-DONEM-KAYIT",
}
EMPLOYEE_EMPTY_STATE = "Bu karne için yayınlanmış gelişim önerisi bulunmuyor."
MANAGER_EMPTY_STATE = "Henüz bu karneye bağlanmış gelişim önerisi"
VIEWERS = ["baskan", "admin", "owner"]
DDL_ON_TABLE = re.compile(r"^\s*(CREATE|ALTER|DROP)\b.*performance_development_recommendations", re.I | re.S)


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-scorecard-guidance-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "scorecard-guidance-first-login",
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


def _insert_recommendation(db, **values):
    row = {
        "employee_name": "Sözleşme Personeli",
        "period_name": "Sözleşme Dönemi",
        "recommendation_type": "improvement_plan",
        "development_area": "communication",
        "priority": "high",
        "visibility_scope": "scorecard",
        "publication_status": "published",
        "show_on_scorecard": True,
        "is_published": True,
        "supervisor_approval_required": True,
        "supervisor_approved": True,
        "hr_publish_required": True,
        "hr_publish_approved": True,
        "publish_lock": False,
        "scorecard_visibility_mode": "after_publish",
        "scorecard_detail_level": "summary",
        "employee_message": None,
        "created_by": None,
        "updated_at": datetime(2026, 4, 1, 9, 0, 0),
    }
    row.update(values)
    columns = ", ".join(row)
    placeholders = ", ".join(f":{name}" for name in row)
    db.session.execute(
        text(f"INSERT INTO performance_development_recommendations ({columns}) VALUES ({placeholders})"),
        row,
    )


@pytest.fixture
def env(monkeypatch, install_interim_notes_schema, install_development_recommendations_schema):
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod, User

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    ids: dict[str, int] = {}
    with app.app_context():
        db.create_all()
        install_interim_notes_schema(db.engine)
        install_development_recommendations_schema(db.engine)
        for key, role in (
            ("baskan", "baskan"),
            ("admin", "admin"),
            ("owner", "personel"),
            ("other", "personel"),
            ("evaluator", "personel"),
        ):
            sicil = f"SCGC{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Karne",
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
            title="Sözleşme Dönemi",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
            results_published=True,
        )
        other_period = PerformancePeriod(
            title="Önceki Dönem",
            period_type="quarterly",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 12, 31),
            is_active=False,
        )
        db.session.add_all([period, other_period])
        db.session.flush()
        ids["period"], ids["other_period"] = int(period.id), int(other_period.id)
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
                period_id=period.id,
                employee_id=ids["owner"],
                evaluator_id=ids["evaluator"],
                manager_level=1,
                status="tamamlandi",
            )
        )
        db.session.flush()
        ids["evaluation"] = int(evaluation.id)
        owner, pid = ids["owner"], ids["period"]
        _insert_recommendation(
            db,
            employee_id=owner,
            period_id=pid,
            recommendation_text=f"{SAFE_NEW}: İletişim planı\nikinci satır — çğıöşü",
            updated_at=datetime(2026, 4, 2, 9, 0, 0),
        )
        _insert_recommendation(
            db,
            employee_id=owner,
            period_id=pid,
            recommendation_text=f"{SAFE_OLD}: Zaman yönetimi",
            updated_at=datetime(2026, 4, 1, 9, 0, 0),
        )
        _insert_recommendation(
            db,
            employee_id=owner,
            period_id=pid,
            recommendation_text=HIDDEN_MARKERS["draft"],
            publication_status="draft",
            show_on_scorecard=False,
            is_published=False,
        )
        _insert_recommendation(db, employee_id=owner, period_id=pid, recommendation_text=HIDDEN_MARKERS["locked"], publish_lock=True)
        _insert_recommendation(db, employee_id=owner, period_id=pid, recommendation_text=HIDDEN_MARKERS["pending_hr"], hr_publish_approved=False)
        _insert_recommendation(
            db, employee_id=owner, period_id=pid, recommendation_text=HIDDEN_MARKERS["internal_mode"], scorecard_visibility_mode="internal_only"
        )
        _insert_recommendation(db, employee_id=ids["other"], period_id=pid, recommendation_text=HIDDEN_MARKERS["other_employee"])
        _insert_recommendation(db, employee_id=owner, period_id=ids["other_period"], recommendation_text=HIDDEN_MARKERS["other_period"])
        db.session.commit()
        db.session.remove()
    return SimpleNamespace(app=app, ids=ids)


def _client(env, who=None):
    client = env.app.test_client()
    if who is not None:
        response = client.post("/login", data={"sicil_or_email": f"SCGC{who.upper()}", "password": PASSWORD})
        assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _get(env, who, suffix=""):
    return _client(env, who).get(f"/performance/scorecard/{env.ids['evaluation']}{suffix}")


def _visible_markers(body: str) -> set[str]:
    return {marker for marker in (SAFE_NEW, SAFE_OLD, *HIDDEN_MARKERS.values()) if marker in body}


@pytest.mark.parametrize("who", VIEWERS)
@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_published_scorecard_renders_for_every_authorized_viewer(env, who, suffix):
    response = _get(env, who, suffix)
    assert response.status_code == 200


@pytest.mark.parametrize("who", VIEWERS)
@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_canonical_scorecard_safe_recommendations_appear_exactly_once(env, who, suffix):
    body = _get(env, who, suffix).get_data(as_text=True)
    assert body.count(SAFE_NEW) == 1
    assert body.count(SAFE_OLD) == 1
    assert "çğıöşü" in body  # Unicode/multiline content survives


@pytest.mark.parametrize("who", VIEWERS)
def test_detail_and_pdf_show_the_same_recommendation_set(env, who):
    detail = _get(env, who).get_data(as_text=True)
    pdf = _get(env, who, "/pdf").get_data(as_text=True)
    assert _visible_markers(detail) == _visible_markers(pdf) == {SAFE_NEW, SAFE_OLD}


@pytest.mark.parametrize("who", VIEWERS)
@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_recommendations_keep_the_canonical_newest_first_order(env, who, suffix):
    body = _get(env, who, suffix).get_data(as_text=True)
    assert body.index(SAFE_NEW) < body.index(SAFE_OLD)


@pytest.mark.parametrize("who", VIEWERS)
@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_internal_unpublished_and_foreign_recommendations_never_reach_the_scorecard(env, who, suffix):
    body = _get(env, who, suffix).get_data(as_text=True)
    assert not (_visible_markers(body) & set(HIDDEN_MARKERS.values()))


@pytest.mark.parametrize("who", VIEWERS)
def test_no_false_empty_state_when_a_canonical_recommendation_exists(env, who):
    body = _get(env, who).get_data(as_text=True)
    assert EMPLOYEE_EMPTY_STATE not in body
    assert MANAGER_EMPTY_STATE not in body


def test_empty_state_is_rendered_when_no_scorecard_safe_recommendation_exists(env):
    from app.extensions import db

    with env.app.app_context():
        db.session.execute(
            text("DELETE FROM performance_development_recommendations WHERE recommendation_text LIKE 'KANONIK-%'")
        )
        db.session.commit()
        db.session.remove()
    owner_detail = _get(env, "owner")
    assert owner_detail.status_code == 200
    assert EMPLOYEE_EMPTY_STATE in owner_detail.get_data(as_text=True)
    manager_detail = _get(env, "baskan")
    assert manager_detail.status_code == 200
    assert MANAGER_EMPTY_STATE in manager_detail.get_data(as_text=True)
    for who in VIEWERS:
        pdf = _get(env, who, "/pdf")
        assert pdf.status_code == 200
        assert not _visible_markers(pdf.get_data(as_text=True))


@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_other_personnel_and_wrong_evaluator_are_still_refused(env, suffix):
    for who in ("other", "evaluator"):
        response = _get(env, who, suffix)
        assert response.status_code == 403
        assert not _visible_markers(response.get_data(as_text=True))


@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_anonymous_and_missing_ids_stay_refused(env, suffix):
    anonymous = _client(env).get(f"/performance/scorecard/{env.ids['evaluation']}{suffix}")
    assert anonymous.status_code == 302 and "/login" in anonymous.headers["Location"]
    missing = _client(env, "baskan").get(f"/performance/scorecard/987654{suffix}")
    assert missing.status_code == 404


GUIDANCE_CODE = ("phase10_development_guidance_ui.py", "meeting_p4_development_guidance.py")


def _from_guidance_code() -> bool:
    # The SQLite test database has no runtime-schema menu tables, so unrelated menu helpers log
    # (and roll back) their own failures on every page; only the guidance path is under test here.
    return any(frame.filename.endswith(GUIDANCE_CODE) for frame in traceback.extract_stack())


def _instrumented(env, call):
    from app.extensions import db

    observed: dict[str, Any] = {"db_errors": [], "rollbacks": 0, "ddl": []}
    with env.app.app_context():
        engine = db.engine

    def _on_error(context):
        if _from_guidance_code() or "performance_development_recommendations" in (context.statement or ""):
            observed["db_errors"].append(str(context.original_exception).splitlines()[0])

    def _on_sql(conn, cursor, statement, parameters, context, executemany):
        if DDL_ON_TABLE.match(statement or ""):
            observed["ddl"].append(" ".join(statement.split())[:80])

    def _on_rollback(session):
        if _from_guidance_code():
            observed["rollbacks"] += 1

    event.listen(engine, "handle_error", _on_error)
    event.listen(engine, "before_cursor_execute", _on_sql)
    event.listen(Session, "after_rollback", _on_rollback)
    try:
        response = call()
    finally:
        event.remove(engine, "handle_error", _on_error)
        event.remove(engine, "before_cursor_execute", _on_sql)
        event.remove(Session, "after_rollback", _on_rollback)
    return response, observed


@pytest.mark.parametrize("who", VIEWERS)
@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_scorecard_guidance_runs_without_db_errors_rollbacks_or_ddl(env, who, suffix):
    client = _client(env, who)
    response, observed = _instrumented(
        env, lambda: client.get(f"/performance/scorecard/{env.ids['evaluation']}{suffix}")
    )
    assert response.status_code == 200
    assert observed["db_errors"] == []
    assert observed["rollbacks"] == 0
    assert observed["ddl"] == []


def _guidance_snapshot(env):
    snapshot = {}
    for who in VIEWERS:
        for suffix in ("", "/pdf"):
            response = _get(env, who, suffix)
            body = response.get_data(as_text=True)
            snapshot[(who, suffix)] = (
                response.status_code,
                sorted(_visible_markers(body)),
                body.count("dev-guide-scorecard-item\""),
            )
    return snapshot


def test_scorecard_guidance_is_independent_of_the_interim_notes_hidden_commit(env, monkeypatch):
    """G3-B will remove the readiness helper's commit; scorecard guidance must not change."""
    with_commit = _guidance_snapshot(env)

    import app.services.performance.interim_notes_runtime as runtime

    def _readiness_without_commit():
        return runtime._schema_ready(), []

    monkeypatch.setattr(runtime, "ensure_interim_notes_table", _readiness_without_commit)
    without_commit = _guidance_snapshot(env)

    assert with_commit == without_commit
    assert all(status == 200 for status, _, _ in with_commit.values())
    assert all(markers == sorted([SAFE_NEW, SAFE_OLD]) for _, markers, _ in with_commit.values())
    assert all(items == 2 for _, _, items in with_commit.values())


def test_pdf_is_one_html_document_with_nothing_after_the_closing_tag(env):
    body = _get(env, "baskan", "/pdf").get_data(as_text=True)
    assert body.count("</html>") == 1
    assert body.split("</html>", 1)[1].strip() == ""
    assert body.count("Gelişim Önerisi ve Rehberlik") == 1


def test_template_global_uses_the_canonical_reader_and_fails_closed_without_an_employee(env):
    from flask import render_template_string

    with env.app.test_request_context("/"):
        rendered = render_template_string(
            "{{ get_scorecard_development_guidance(e, p)|length }}|{{ get_scorecard_development_guidance(None, p)|length }}",
            e=env.ids["owner"],
            p=env.ids["period"],
        )
    assert rendered == "2|0"
