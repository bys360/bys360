"""BYS360_COVERAGE_WAVE7_AGENT1_SURVEY_ADMIN_LIFECYCLE_CONTRACT

Behavioral, route-boundary contract for the approved Wave 7 survey
administration scope (app/communication/surveys_routes.py +
app/services/surveys/state.py, authoring.py, normalizers.py, targets.py):

    survey_create       POST /survey-create
    survey_delete       POST /survey-delete/<id>
    survey_archive      POST /survey-archive/<id>
    survey_restore      POST /survey-restore/<id>
    survey_bulk_action   POST /survey-bulk-action

Explicitly excluded (Wave 6-covered or reserved for a later scope):
survey-edit, survey-results, survey-results/export-csv, publish/unpublish/
close, take/submit.

DEFECT Q (discovered during this wave, NOT fixed, NOT characterized as
correct -- reported separately): app/services/surveys/state.py::
restore_survey has NO `_ensure_state_change(...)` guard, unlike every one
of its siblings in the same file (publish_survey, unpublish_survey,
close_survey, archive_survey -- all four call it). restore_survey
unconditionally sets `survey.status = "draft"` regardless of the survey's
current status. Consequence: an already-authorized survey manager can
POST /survey-restore/<id> on a PUBLISHED (or closed) survey and silently
force it back to draft with a success flash and no warning -- an
unintended "unpublish" via the wrong endpoint. This file therefore:
  - DOES test restore's one confirmed-correct positive path (archived ->
    draft), which is unaffected by the missing guard.
  - Does NOT test any "invalid restore transition rejected" case, because
    no such rejection exists in current production code -- inventing one
    would fabricate a passing test for behavior that isn't real, and
    asserting the unguarded accept-anything behavior as correct would
    freeze a genuine defect as intended design. Neither is acceptable.
archive_survey, by contrast, DOES call `_ensure_state_change` (no
`allow_same=True`), so "already-archived survey cannot be re-archived" is
a real, current production rule and IS tested below as the archive
cluster's negative/boundary case.

Deletion contract asymmetry (observed, not a defect -- both paths are
already individually correct on their own terms, just differently scoped):
  - `survey_delete` (single) blocks via `safe_any_response_count` -- ANY
    response (including an incomplete one) blocks deletion.
  - `bulk_survey_action`'s delete branch blocks via
    `safe_completed_response_count` -- only a COMPLETED response blocks
    deletion.
  No live code path in this codebase creates a SurveyResponse with
  `is_completed=False` (confirmed via `grep -rn "SurveyResponse(" app/`:
  every real construction site hardcodes `is_completed=True`), so this
  asymmetry has no observable behavioral difference under any data this
  test file -- or any real caller -- can currently produce. Each path is
  tested against its own actual rule; this file does not assert the two
  rules are identical, because they are not, and does not test the
  currently-unreachable incomplete-response case either, because it is
  currently unreachable.

Fixture pattern: this wave's mandatory proven shape (Config class-attribute
patch BEFORE create_app(), StaticPool + pysqlite isolation_level=None +
explicit BEGIN event listener, real `/login` POST), copied from Wave 6's
own tests/behavior/test_survey_publication_response_eligibility_contract.py.
Uses its own dedicated tmp DB directory (C:\\bys360_pytest_tmp_wave7_agent1)
so it shares no state with any other wave/agent running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave7_agent1")

DEFAULT_PASSWORD = "Wave7Agent1SurveyAdminTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "wave7-agent1-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-wave7-agent1-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"wave7_agent1_{uuid.uuid4().hex}.sqlite3")
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
            sicil_no=f"W7A1{n:06d}",
            email=f"wave7-agent1-{n}@bys360.test",
            ad="Wave7",
            soyad=f"SurveyAdmin{n}",
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


# ---------------------------------------------------------------------------
# Fixture builders (real DB rows)
# ---------------------------------------------------------------------------


def _create_survey(app, *, status="draft", created_by_id):
    from app.extensions import db
    from app.models import Survey

    with app.app_context():
        survey = Survey(
            title=f"Wave7 Agent1 Anket {uuid.uuid4().hex[:8]}",
            description="test anketi",
            survey_type="kurum_ici",
            created_by_user_id=created_by_id,
            is_anonymous=False,
            allow_multiple_submissions=False,
            status=status,
        )
        db.session.add(survey)
        db.session.commit()
        return survey.id


def _add_completed_response(app, *, survey_id, user_id=None):
    import datetime as _dt

    from app.extensions import db
    from app.models import SurveyResponse

    with app.app_context():
        response = SurveyResponse(
            survey_id=survey_id,
            user_id=user_id,
            submitted_at=_dt.datetime.utcnow(),
            is_completed=True,
        )
        db.session.add(response)
        db.session.commit()
        return response.id


def _survey_row_count(app):
    from app.models import Survey

    with app.app_context():
        return Survey.query.count()


def _survey_snapshot(app, survey_id):
    from app.models import Survey

    with app.app_context():
        survey = Survey.query.get(survey_id)
        if survey is None:
            return None
        return {"status": survey.status, "title": survey.title}


def _survey_exists(app, survey_id) -> bool:
    from app.models import Survey

    with app.app_context():
        return Survey.query.get(survey_id) is not None


def _valid_create_form(**overrides):
    data = {
        "title": f"Wave7 Yeni Anket {uuid.uuid4().hex[:8]}",
        "description": "Oluşturma testi",
        "survey_type": "kurum_ici",
        "status": "draft",
        "target_type": "all",
        "question_text[]": ["İlk soru?"],
        "question_type[]": ["text"],
        "question_required[]": ["1"],
        "question_options[]": [""],
        "question_helper_text[]": [""],
        "question_logic_mode[]": ["always"],
        "question_logic_source[]": [""],
        "question_logic_operator[]": [""],
        "question_logic_value[]": [""],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# 1. survey_create -- positive + validation boundaries
# ---------------------------------------------------------------------------


def test_create_valid_survey_by_manager_creates_real_rows(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    before = _survey_row_count(app)
    resp = client.post("/survey-create", data=_valid_create_form(), follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_row_count(app) == before + 1


def test_create_denied_for_non_manager_zero_mutation(app, client):
    _personnel_id, personnel_sicil = _create_personnel(app)
    _login(client, personnel_sicil)

    before = _survey_row_count(app)
    resp = client.post("/survey-create", data=_valid_create_form(), follow_redirects=False)

    assert resp.status_code in (302, 403)
    assert _survey_row_count(app) == before, "a non-manager must never be able to create a survey"


def test_create_rejects_empty_title_zero_mutation(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    before = _survey_row_count(app)
    resp = client.post("/survey-create", data=_valid_create_form(title=""), follow_redirects=False)

    assert resp.status_code == 200
    assert _survey_row_count(app) == before
    assert "başlığı zorunludur" in resp.get_data(as_text=True), (
        "the validation-failure path re-renders the create form in the same request, "
        "consuming the flash via the template -- so this asserts against the response "
        "body, not a post-redirect session flash"
    )


def test_create_rejects_end_before_start_zero_mutation(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    before = _survey_row_count(app)
    resp = client.post(
        "/survey-create",
        data=_valid_create_form(start_at="2026-06-10T10:00", end_at="2026-06-01T10:00"),
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert _survey_row_count(app) == before
    assert "Bitiş tarihi" in resp.get_data(as_text=True)


def test_create_rejects_non_all_target_without_values_zero_mutation(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    before = _survey_row_count(app)
    resp = client.post(
        "/survey-create",
        data=_valid_create_form(target_type="user", target_values=[]),
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert _survey_row_count(app) == before
    assert "Hedef kitle" in resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 2. survey_archive -- positive + real "already archived" rejection
# ---------------------------------------------------------------------------


def test_archive_manager_success_sets_archived(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-archive/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "archived"


def test_archive_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _login(client, personnel_sicil)

    resp = client.post(f"/survey-archive/{survey_id}", follow_redirects=False)

    assert resp.status_code in (302, 403)
    assert _survey_snapshot(app, survey_id)["status"] == "draft"


def test_archive_already_archived_survey_rejected_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="archived", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-archive/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "archived"
    assert any("zaten" in msg for msg in _flashes(client)), "re-archiving an already-archived survey must be rejected, not silently re-applied"


def test_archive_unknown_survey_id_handled_safely(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    resp = client.post("/survey-archive/999999", follow_redirects=False)

    assert resp.status_code == 302
    assert any("bulunamadı" in msg for msg in _flashes(client))


# ---------------------------------------------------------------------------
# 3. survey_restore -- confirmed-correct positive path only (see Defect Q)
# ---------------------------------------------------------------------------


def test_restore_manager_success_from_archived_sets_draft(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="archived", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-restore/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "draft"


def test_restore_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="archived", created_by_id=manager_id)
    _login(client, personnel_sicil)

    resp = client.post(f"/survey-restore/{survey_id}", follow_redirects=False)

    assert resp.status_code in (302, 403)
    assert _survey_snapshot(app, survey_id)["status"] == "archived"


# ---------------------------------------------------------------------------
# 4. survey_delete -- positive + real response-protection boundary
# ---------------------------------------------------------------------------


def test_delete_manager_success_when_no_responses(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-delete/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_exists(app, survey_id) is False


def test_delete_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _login(client, personnel_sicil)

    resp = client.post(f"/survey-delete/{survey_id}", follow_redirects=False)

    assert resp.status_code in (302, 403)
    assert _survey_exists(app, survey_id) is True


def test_delete_rejected_when_survey_has_responses_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    _add_completed_response(app, survey_id=survey_id, user_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-delete/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_exists(app, survey_id) is True, "a survey with any response must never be hard-deleted"
    assert any("silinemez" in msg for msg in _flashes(client))


def test_delete_unknown_survey_id_handled_safely(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    resp = client.post("/survey-delete/999999", follow_redirects=False)

    assert resp.status_code == 302
    assert any("bulunamadı" in msg for msg in _flashes(client))


# ---------------------------------------------------------------------------
# 5. survey_bulk_action -- positive + selective skip boundary
# ---------------------------------------------------------------------------


def test_bulk_action_archive_success_multiple_surveys(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_a = _create_survey(app, status="draft", created_by_id=manager_id)
    survey_b = _create_survey(app, status="draft", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(
        "/survey-bulk-action",
        data={"survey_ids": [str(survey_a), str(survey_b)], "bulk_action": "archive", "current_status": "all"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_a)["status"] == "archived"
    assert _survey_snapshot(app, survey_b)["status"] == "archived"


def test_bulk_action_delete_skips_surveys_with_completed_responses(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_clean = _create_survey(app, status="draft", created_by_id=manager_id)
    survey_with_response = _create_survey(app, status="published", created_by_id=manager_id)
    _add_completed_response(app, survey_id=survey_with_response, user_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(
        "/survey-bulk-action",
        data={"survey_ids": [str(survey_clean), str(survey_with_response)], "bulk_action": "delete", "current_status": "all"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _survey_exists(app, survey_clean) is False, "the response-free survey must be deleted"
    assert _survey_exists(app, survey_with_response) is True, "the response-bearing survey must be preserved, not deleted alongside the batch"
    assert any("yanıt içerdiği için silinmedi" in msg for msg in _flashes(client))


def test_bulk_action_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _login(client, personnel_sicil)

    resp = client.post(
        "/survey-bulk-action",
        data={"survey_ids": [str(survey_id)], "bulk_action": "archive", "current_status": "all"},
        follow_redirects=False,
    )

    assert resp.status_code in (302, 403)
    assert _survey_snapshot(app, survey_id)["status"] == "draft"


def test_bulk_action_unknown_ids_handled_safely_zero_mutation(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    before = _survey_row_count(app)
    resp = client.post(
        "/survey-bulk-action",
        data={"survey_ids": ["999999", "888888"], "bulk_action": "archive", "current_status": "all"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _survey_row_count(app) == before
    assert any("bulunamadı" in msg for msg in _flashes(client))
