"""BYS360_COVERAGE_WAVE6_AGENT2_SURVEY_PUBLICATION_RESPONSE_ELIGIBILITY_CONTRACT

Behavioral, route-boundary contract for the desktop survey publication +
response-eligibility lifecycle (app/communication/surveys_routes.py):

    survey_publish    POST /survey-publish/<id>
    survey_unpublish  POST /survey-unpublish/<id>
    survey_close      POST /survey-close/<id>
    survey_take       GET  /surveys/<id>/take
    survey_submit     POST /surveys/<id>/submit

Why this domain and not mobile performance authorization: the immediately
preceding Mobile Security Checkpoint already exhaustively read and reasoned
about authorization for essentially the entire mobile performance/KPI route
surface (summary, periods, approvals, scorecards, tasks, score-form,
score-action, full-feature-summary, risk-analysis, etc. -- ~25 routes), and
Defect N/O/P's 16 regression tests already lock in the mobile object-level
authorization contract for the routes that were actually vulnerable. A new
mobile authorization test here would conceptually re-tread ground just
covered, not add independent assurance. This desktop survey lifecycle, by
contrast, was mechanically confirmed to have ZERO real behavioral test
coverage before this file: every existing survey-related test under
tests/architecture/test_survey_faz*_*.py is a pure static-text assertion on
route/service source (e.g. `"submit_survey_response as _service_submit_..."
in ROUTES.read_text()`), never a real HTTP request; the one real end-to-end
survey behavioral suite that exists, tests/integration/test_survey_response_
transactions.py, targets the separate MOBILE API survey-submit endpoint
(/api/mobile/...), not this desktop main_bp route family at all. Confirmed
via `grep -n "client\\.\\|test_client" tests/architecture/test_survey_faz*.py`
(zero matches) and reading that integration file's own login helper
(POST /api/mobile/auth/login) before selecting this scope.

Eligibility contract under test (read directly from app/communication/
surveys_routes.py and app/services/surveys/{time_utils,targets,state}.py):

    survey_access_state(survey):
        status must be "published"
        now must be within [start_at, end_at] when those are set
    matching_assignment_for_user(survey_id, user):
        target_type == "all" -> always matches
        target_type == "user" -> str(user.id) == target_value
    survey_take / survey_submit both require access_state AND a matching
    assignment; submit additionally rejects a second COMPLETED response
    when not survey.allow_multiple_submissions and not survey.is_anonymous.
    survey_publish requires >=1 question AND >=1 assignment before it will
    call the state-transition service at all (checked BEFORE any mutation).

Menu-gate note (menu_key_required("surveys" / "survey_manage")): read
directly from app/menu_registry.py's ROLE_MENU_DEFAULTS -- role "personel"
carries "surveys" but NOT "survey_manage" by default; role "admin" carries
both. Fixtures use role="personel" for ordinary take/submit actors and
role="admin" for the manager actor, matching this real, live default
policy (not invented for the test).

Form-token note: `_render_survey_take`/`survey_submit` use a real per-
(user, survey) one-time token stored in the Flask session
(`form_token:survey_submit:{user_id}:{survey_id}`, app/route_support.py's
issue_form_token/consume_form_token). This file injects that exact session
key via `client.session_transaction()` rather than scraping the rendered
HTML for a hidden input, since the token mechanism itself is already
exercised for real by the route/service pair being tested and the goal
here is the eligibility/lifecycle contract, not the token template markup.

Fixture pattern: this wave's mandatory proven shape (Config class-attribute
patch BEFORE create_app(), StaticPool + pysqlite isolation_level=None +
explicit BEGIN event listener, real `/login` POST), copied from
tests/behavior/test_file_center_quota_and_role_matrix_admin_contract.py.
Uses its own dedicated tmp DB directory (C:\\bys360_pytest_tmp_wave6_agent2)
so it shares no state with any other wave/agent running concurrently.
"""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave6_agent2")

DEFAULT_PASSWORD = "Wave6Agent2SurveyTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "wave6-agent2-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-wave6-agent2-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"wave6_agent2_{uuid.uuid4().hex}.sqlite3")
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


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# User / login helpers
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"W6A2{n:06d}",
            email=f"wave6-agent2-{n}@bys360.test",
            ad="Wave6",
            soyad=f"Survey{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id, user.sicil_no


def _create_manager(app):
    return _create_user(app, role="admin")


def _create_personnel(app):
    return _create_user(app, role="personel")


def _login(client, sicil_no, password=DEFAULT_PASSWORD):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _flashes(client):
    with client.session_transaction() as sess:
        return [msg for _cat, msg in sess.get("_flashes", [])]


def _inject_form_token(client, *, user_id, survey_id, token="wave6-agent2-test-form-token"):
    with client.session_transaction() as sess:
        sess[f"form_token:survey_submit:{user_id}:{survey_id}"] = token
    return token


# ---------------------------------------------------------------------------
# Fixture builders (real DB rows)
# ---------------------------------------------------------------------------


def _create_survey(app, *, status="draft", is_anonymous=False, allow_multiple_submissions=False, start_at=None, end_at=None, created_by_id):
    from app.extensions import db
    from app.models import Survey

    with app.app_context():
        survey = Survey(
            title=f"Wave6 Agent2 Anket {uuid.uuid4().hex[:8]}",
            description="test anketi",
            survey_type="kurum_ici",
            created_by_user_id=created_by_id,
            is_anonymous=is_anonymous,
            allow_multiple_submissions=allow_multiple_submissions,
            start_at=start_at,
            end_at=end_at,
            status=status,
        )
        db.session.add(survey)
        db.session.commit()
        return survey.id


def _add_question(app, *, survey_id, question_type="text", is_required=True, sort_order=1):
    from app.extensions import db
    from app.models import SurveyQuestion

    with app.app_context():
        question = SurveyQuestion(
            survey_id=survey_id,
            question_text="Test sorusu?",
            question_type=question_type,
            is_required=is_required,
            sort_order=sort_order,
        )
        db.session.add(question)
        db.session.commit()
        return question.id


def _add_assignment(app, *, survey_id, target_type, target_value=None):
    from app.extensions import db
    from app.models import SurveyAssignment

    with app.app_context():
        assignment = SurveyAssignment(
            survey_id=survey_id,
            target_type=target_type,
            target_value=target_value,
        )
        db.session.add(assignment)
        db.session.commit()
        return assignment.id


def _create_completed_response(app, *, survey_id, user_id, assignment_id):
    from app.extensions import db
    from app.models import SurveyResponse

    with app.app_context():
        response = SurveyResponse(
            survey_id=survey_id,
            user_id=user_id,
            assignment_id=assignment_id,
            submitted_at=_dt.datetime.utcnow(),
            is_completed=True,
        )
        db.session.add(response)
        db.session.commit()
        return response.id


# ---------------------------------------------------------------------------
# DB read helpers
# ---------------------------------------------------------------------------


def _survey_snapshot(app, survey_id):
    from app.models import Survey

    with app.app_context():
        survey = Survey.query.get(survey_id)
        if survey is None:
            return None
        return {"status": survey.status, "start_at": survey.start_at, "end_at": survey.end_at}


def _response_count(app, survey_id=None):
    from app.models import SurveyResponse

    with app.app_context():
        q = SurveyResponse.query
        if survey_id is not None:
            q = q.filter_by(survey_id=survey_id)
        return q.count()


def _answer_count(app):
    from app.models import SurveyAnswer

    with app.app_context():
        return SurveyAnswer.query.count()


# ---------------------------------------------------------------------------
# 1. survey_publish -- pre-mutation validation boundaries
# ---------------------------------------------------------------------------


def test_publish_denied_without_questions_stays_draft_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _add_assignment(app, survey_id=survey_id, target_type="all")
    _login(client, manager_sicil)

    resp = client.post(f"/survey-publish/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "draft"
    assert any("en az bir soru" in msg for msg in _flashes(client))


def test_publish_denied_without_assignments_stays_draft_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _add_question(app, survey_id=survey_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-publish/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "draft"
    assert any("hedef kitle" in msg for msg in _flashes(client))


def test_publish_success_with_questions_and_assignments_sets_published(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _add_question(app, survey_id=survey_id)
    _add_assignment(app, survey_id=survey_id, target_type="all")
    _login(client, manager_sicil)

    resp = client.post(f"/survey-publish/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    snap = _survey_snapshot(app, survey_id)
    assert snap["status"] == "published"
    assert snap["start_at"] is not None


def test_publish_denied_for_non_manager_zero_mutation(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="draft", created_by_id=personnel_id)
    _add_question(app, survey_id=survey_id)
    _add_assignment(app, survey_id=survey_id, target_type="all")
    _login(client, personnel_sicil)

    resp = client.post(f"/survey-publish/{survey_id}", follow_redirects=False)

    assert resp.status_code in (302, 403)
    assert _survey_snapshot(app, survey_id)["status"] == "draft", "a non-manager must never be able to publish"
    _ = manager_sicil


# ---------------------------------------------------------------------------
# 2. survey_take -- eligibility boundaries (state + assignment match)
# ---------------------------------------------------------------------------


def test_take_denied_for_draft_survey(app, client):
    manager_id, _ = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _add_assignment(app, survey_id=survey_id, target_type="user", target_value=str(personnel_id))
    _login(client, personnel_sicil)

    resp = client.get(f"/surveys/{survey_id}/take", follow_redirects=False)

    assert resp.status_code == 302
    assert any("yayımlanmamış" in msg for msg in _flashes(client))


def test_take_denied_for_closed_survey(app, client):
    manager_id, _ = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="closed", created_by_id=manager_id)
    _add_assignment(app, survey_id=survey_id, target_type="user", target_value=str(personnel_id))
    _login(client, personnel_sicil)

    resp = client.get(f"/surveys/{survey_id}/take", follow_redirects=False)
    assert resp.status_code == 302


def test_take_denied_for_unassigned_user(app, client):
    manager_id, _ = _create_manager(app)
    assigned_id, _assigned_sicil = _create_personnel(app)
    stranger_id, stranger_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    _add_assignment(app, survey_id=survey_id, target_type="user", target_value=str(assigned_id))
    _login(client, stranger_sicil)

    resp = client.get(f"/surveys/{survey_id}/take", follow_redirects=False)

    assert resp.status_code == 302
    assert any("erişim yetkiniz yok" in msg for msg in _flashes(client))
    _ = stranger_id


def test_take_success_for_assigned_user_on_published_survey(app, client):
    manager_id, _ = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    _add_question(app, survey_id=survey_id)
    _add_assignment(app, survey_id=survey_id, target_type="user", target_value=str(personnel_id))
    _login(client, personnel_sicil)

    resp = client.get(f"/surveys/{survey_id}/take", follow_redirects=False)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 3. survey_submit -- eligibility + zero-write-on-rejection + duplicate boundary
# ---------------------------------------------------------------------------


def test_submit_denied_for_draft_survey_zero_response_row(app, client):
    manager_id, _ = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _add_assignment(app, survey_id=survey_id, target_type="user", target_value=str(personnel_id))
    _login(client, personnel_sicil)

    before = _response_count(app, survey_id)
    token = _inject_form_token(client, user_id=personnel_id, survey_id=survey_id)
    resp = client.post(f"/surveys/{survey_id}/submit", data={"_form_token": token}, follow_redirects=False)

    assert resp.status_code == 302
    assert _response_count(app, survey_id) == before


def test_submit_denied_for_unassigned_user_zero_response_row(app, client):
    manager_id, _ = _create_manager(app)
    assigned_id, _assigned_sicil = _create_personnel(app)
    stranger_id, stranger_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    _add_question(app, survey_id=survey_id)
    _add_assignment(app, survey_id=survey_id, target_type="user", target_value=str(assigned_id))
    _login(client, stranger_sicil)

    before = _response_count(app, survey_id)
    token = _inject_form_token(client, user_id=stranger_id, survey_id=survey_id)
    resp = client.post(f"/surveys/{survey_id}/submit", data={"_form_token": token}, follow_redirects=False)

    assert resp.status_code == 302
    assert _response_count(app, survey_id) == before


def test_submit_success_creates_response_and_answer_row(app, client):
    manager_id, _ = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    question_id = _add_question(app, survey_id=survey_id, question_type="text")
    _add_assignment(app, survey_id=survey_id, target_type="all")
    _login(client, personnel_sicil)

    before_responses = _response_count(app, survey_id)
    before_answers = _answer_count(app)
    token = _inject_form_token(client, user_id=personnel_id, survey_id=survey_id)
    resp = client.post(
        f"/surveys/{survey_id}/submit",
        data={"_form_token": token, f"question_{question_id}": "gerçek bir yanıt"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _response_count(app, survey_id) == before_responses + 1
    assert _answer_count(app) == before_answers + 1


def test_submit_second_time_without_allow_multiple_is_duplicate_rejected(app, client):
    manager_id, _ = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="published", allow_multiple_submissions=False, created_by_id=manager_id)
    question_id = _add_question(app, survey_id=survey_id, question_type="text")
    assignment_id = _add_assignment(app, survey_id=survey_id, target_type="all")
    _create_completed_response(app, survey_id=survey_id, user_id=personnel_id, assignment_id=assignment_id)
    _login(client, personnel_sicil)

    before = _response_count(app, survey_id)
    token = _inject_form_token(client, user_id=personnel_id, survey_id=survey_id)
    resp = client.post(
        f"/surveys/{survey_id}/submit",
        data={"_form_token": token, f"question_{question_id}": "ikinci yanıt"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert any("daha önce tamamladınız" in msg for msg in _flashes(client))
    assert _response_count(app, survey_id) == before, "duplicate submission must write zero new response rows"


def test_submit_second_time_with_allow_multiple_is_duplicate_allowed(app, client):
    manager_id, _ = _create_manager(app)
    personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="published", allow_multiple_submissions=True, created_by_id=manager_id)
    question_id = _add_question(app, survey_id=survey_id, question_type="text")
    assignment_id = _add_assignment(app, survey_id=survey_id, target_type="all")
    _create_completed_response(app, survey_id=survey_id, user_id=personnel_id, assignment_id=assignment_id)
    _login(client, personnel_sicil)

    before = _response_count(app, survey_id)
    token = _inject_form_token(client, user_id=personnel_id, survey_id=survey_id)
    resp = client.post(
        f"/surveys/{survey_id}/submit",
        data={"_form_token": token, f"question_{question_id}": "ikinci yanıt"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _response_count(app, survey_id) == before + 1, "allow_multiple_submissions must permit a second response"


# ---------------------------------------------------------------------------
# 4. survey_unpublish / survey_close -- manager-driven state transitions
# ---------------------------------------------------------------------------


def test_unpublish_manager_success_returns_to_draft(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-unpublish/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "draft"


def test_close_manager_success_sets_closed_and_end_at(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-close/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    snap = _survey_snapshot(app, survey_id)
    assert snap["status"] == "closed"
    assert snap["end_at"] is not None
