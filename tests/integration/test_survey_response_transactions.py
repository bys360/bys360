"""BYS360 Test Integration Expansion Wave 2 -- survey response transactions.

Real Flask ``test_client()`` against the real mobile survey-submit endpoint
(``POST /api/mobile/surveys/<id>/submit``), a real in-memory SQLite DB, and
real ``Survey``/``SurveyQuestion``/`SurveyQuestionOption``/``SurveyResponse``/
``SurveyAnswer`` ORM rows. Verifies the actual before/after DB state of the
write, validation-failure atomicity (no partial rows), duplicate-submission
handling, target-assignment authorization, and the endpoint's real
uncaught-exception rollback path (no explicit try/except around the commit
in ``app/api/mobile/domains/support_survey_write.py::mobile_survey_submit``;
the app's global error handler converts it to a safe 500).
"""
from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text


def _make_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-survey-response-flows")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    # Config froze its values when config.py was first imported, possibly by
    # another test pointing at its own SQLite file; pin them so every app here
    # gets its own empty in-memory database.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch):
    flask_app = _make_app(monkeypatch)
    yield flask_app
    from app.extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user_and_token(app, client, *, sicil_no, email, password="SurveyTestFlow1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave2",
            soyad="Survey",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    login = client.post("/api/mobile/auth/login", json={"username": sicil_no, "password": password})
    assert login.status_code == 200
    token = login.get_json()["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


def _create_survey(
    app,
    *,
    creator_id,
    status="published",
    is_anonymous=False,
    allow_multiple_submissions=False,
    start_at=None,
    end_at=None,
    title="Wave2 Anket",
):
    from app.extensions import db
    from app.models.communication_models import Survey

    with app.app_context():
        survey = Survey(
            title=title,
            description="Test integration expansion wave 2 survey",
            survey_type="kurum_ici",
            created_by_user_id=creator_id,
            is_anonymous=is_anonymous,
            allow_multiple_submissions=allow_multiple_submissions,
            start_at=start_at,
            end_at=end_at,
            status=status,
        )
        db.session.add(survey)
        db.session.commit()
        return survey.id


def _add_question(app, survey_id, *, question_type, is_required=True, sort_order=1, options=None):
    from app.extensions import db
    from app.models.communication_models import SurveyQuestion, SurveyQuestionOption

    with app.app_context():
        question = SurveyQuestion(
            survey_id=survey_id,
            question_text=f"Wave2 soru ({question_type})",
            question_type=question_type,
            is_required=is_required,
            sort_order=sort_order,
        )
        db.session.add(question)
        db.session.commit()
        question_id = question.id

        option_ids = []
        for idx, option_text in enumerate(options or [], start=1):
            option = SurveyQuestionOption(question_id=question_id, option_text=option_text, sort_order=idx)
            db.session.add(option)
            db.session.commit()
            option_ids.append(option.id)

        return question_id, option_ids


def _add_assignment(app, survey_id, *, target_type="all", target_value=None):
    from app.extensions import db
    from app.models.communication_models import SurveyAssignment

    with app.app_context():
        assignment = SurveyAssignment(survey_id=survey_id, target_type=target_type, target_value=target_value)
        db.session.add(assignment)
        db.session.commit()
        return assignment.id


def _response_count(app) -> int:
    from app.extensions import db
    from app.models.communication_models import SurveyResponse

    with app.app_context():
        return db.session.query(SurveyResponse).count()


def _answer_count(app) -> int:
    from app.extensions import db
    from app.models.communication_models import SurveyAnswer

    with app.app_context():
        return db.session.query(SurveyAnswer).count()


def _create_creator(app) -> int:
    from app.extensions import db
    from app.models import User

    with app.app_context():
        creator = User(
            sicil_no="90300",
            email="w2.survey.creator@bys360.test",
            ad="Wave2",
            soyad="Creator",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        creator.set_password("SurveyCreatorTest1!")
        db.session.add(creator)
        db.session.commit()
        return creator.id


# --- DB-INTEGRATION: successful submit persists real rows ---


def test_submit_survey_response_creates_response_and_completed_answers(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    text_qid, _ = _add_question(app, survey_id, question_type="text", sort_order=1)
    rating_qid, _ = _add_question(app, survey_id, question_type="rating_5", sort_order=2)

    user_id, headers = _create_user_and_token(app, client, sicil_no="90301", email="w2.survey.submit1@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(text_qid): "Genel olarak memnunum.", str(rating_qid): 4}},
        headers=headers,
    )

    assert response.status_code == 200
    assert _response_count(app) == 1
    assert _answer_count(app) == 2

    from app.extensions import db
    from app.models.communication_models import SurveyResponse

    with app.app_context():
        row = db.session.query(SurveyResponse).filter_by(survey_id=survey_id).first()
        assert row is not None
        assert row.user_id == user_id
        assert row.is_completed is True


def test_submit_survey_multiple_choice_creates_one_answer_row_per_selection(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    qid, option_ids = _add_question(
        app, survey_id, question_type="multiple_choice", options=["Kırmızı", "Mavi", "Yeşil"]
    )

    _, headers = _create_user_and_token(app, client, sicil_no="90302", email="w2.survey.multi@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): [option_ids[0], option_ids[1]]}},
        headers=headers,
    )

    assert response.status_code == 200
    assert _answer_count(app) == 2


# --- VALIDATION-NEGATIVE: atomic writes, no partial rows ---


def test_submit_survey_missing_required_answer_returns_400_and_writes_no_rows(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    _add_question(app, survey_id, question_type="text", is_required=True)

    _, headers = _create_user_and_token(app, client, sicil_no="90303", email="w2.survey.missing@bys360.test")

    response_before = _response_count(app)
    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == response_before
    assert _answer_count(app) == 0


def test_submit_survey_invalid_option_id_returns_400_and_writes_no_rows(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    qid, _option_ids = _add_question(app, survey_id, question_type="single_choice", options=["Evet", "Hayır"])

    _, headers = _create_user_and_token(app, client, sicil_no="90304", email="w2.survey.badoption@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): 999999}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


def test_submit_survey_rating_out_of_range_returns_400_and_writes_no_rows(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="rating_5")

    _, headers = _create_user_and_token(app, client, sicil_no="90305", email="w2.survey.badrating@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): 99}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


def test_submit_survey_answers_not_a_dict_returns_400(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90306", email="w2.survey.badshape@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": ["not", "a", "dict"]},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


def test_submit_survey_with_no_questions_returns_400(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")

    _, headers = _create_user_and_token(app, client, sicil_no="90307", email="w2.survey.noquestions@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


# --- STATE / WINDOW-NEGATIVE ---


def test_submit_closed_survey_returns_400_and_writes_no_rows(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id, status="closed")
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90308", email="w2.survey.closed@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "cevap"}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


def test_submit_survey_before_start_at_returns_400(app, client):
    import datetime as dt

    creator_id = _create_creator(app)
    future = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(days=7)
    survey_id = _create_survey(app, creator_id=creator_id, start_at=future)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90309", email="w2.survey.future@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "cevap"}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


def test_submit_survey_after_end_at_returns_400(app, client):
    import datetime as dt

    creator_id = _create_creator(app)
    past = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=7)
    survey_id = _create_survey(app, creator_id=creator_id, end_at=past)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90310", email="w2.survey.past@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "cevap"}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


def test_submit_survey_nonexistent_id_returns_404(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90311", email="w2.survey.missing404@bys360.test")

    response = client.post(
        "/api/mobile/surveys/999999/submit",
        json={"answers": {}},
        headers=headers,
    )

    assert response.status_code == 404


# --- AUTHZ-NEGATIVE: assignment / ownership ---


def test_submit_survey_without_matching_assignment_returns_403_and_writes_no_rows(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    # Assignment targets a specific, different user id -- current test user has no match.
    _add_assignment(app, survey_id, target_type="user", target_value="999999")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90312", email="w2.survey.noassign@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "cevap"}},
        headers=headers,
    )

    assert response.status_code == 403
    assert _response_count(app) == 0


def test_submit_survey_with_all_target_assignment_succeeds_for_any_authenticated_user(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90313", email="w2.survey.alltarget@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "cevap"}},
        headers=headers,
    )

    assert response.status_code == 200


def test_submit_survey_without_auth_returns_401_and_writes_no_rows(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "cevap"}},
    )

    assert response.status_code == 401
    assert _response_count(app) == 0


# --- ANONYMITY CONTRACT ---


def test_submit_anonymous_survey_stores_null_user_id_and_anonymous_token(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id, is_anonymous=True)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90314", email="w2.survey.anon@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "anonim cevap"}},
        headers=headers,
    )

    assert response.status_code == 200

    from app.extensions import db
    from app.models.communication_models import SurveyResponse

    with app.app_context():
        row = db.session.query(SurveyResponse).filter_by(survey_id=survey_id).first()
        assert row is not None
        assert row.user_id is None
        assert row.anonymous_token is not None
        assert row.anonymous_token != ""


# --- IDEMPOTENCY / DUPLICATE-SUBMISSION CLASSIFICATION ---


def test_submit_survey_second_time_without_allow_multiple_is_duplicate_rejected(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id, allow_multiple_submissions=False)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90315", email="w2.survey.dup@bys360.test")

    first = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "ilk cevap"}},
        headers=headers,
    )
    second = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "ikinci cevap"}},
        headers=headers,
    )

    assert first.status_code == 200
    # DUPLICATE-REJECTED: the endpoint's own duplicate-submission contract (409).
    assert second.status_code == 409
    assert _response_count(app) == 1


def test_submit_survey_second_time_with_allow_multiple_is_duplicate_allowed(app, client):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id, allow_multiple_submissions=True)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90316", email="w2.survey.dupallowed@bys360.test")

    first = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "ilk cevap"}},
        headers=headers,
    )
    second = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "ikinci cevap"}},
        headers=headers,
    )

    assert first.status_code == 200
    # DUPLICATE-ALLOWED: allow_multiple_submissions=True is a real, intended contract.
    assert second.status_code == 200
    assert _response_count(app) == 2


# --- SERVICE-INTEGRATION: real uncaught-exception rollback (no partial rows) ---


def test_submit_survey_commit_failure_leaves_no_partial_response_or_answer_rows(app, client, monkeypatch):
    creator_id = _create_creator(app)
    survey_id = _create_survey(app, creator_id=creator_id)
    _add_assignment(app, survey_id, target_type="all")
    qid, _ = _add_question(app, survey_id, question_type="text", is_required=False)

    _, headers = _create_user_and_token(app, client, sicil_no="90317", email="w2.survey.rollback@bys360.test")

    import app.api.mobile.domains.support_survey_write as survey_write_module

    def _raise_on_commit():
        raise RuntimeError("simulated commit failure for survey submit rollback test")

    monkeypatch.setattr(survey_write_module.db.session, "commit", _raise_on_commit)

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "rollback cevabı"}},
        headers=headers,
    )

    assert response.status_code >= 500

    monkeypatch.undo()
    assert _response_count(app) == 0
    assert _answer_count(app) == 0


# --- isolation from a stale process-global Config database URI ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported. If an earlier test imported it while DATABASE_URL pointed at
# its own SQLite file, setting DATABASE_URL here came too late: this module's
# apps shared that file and the fixed creator collided on users.email.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "survey_response_stale_config"


def test_app_does_not_inherit_a_stale_frozen_config_database_uri(monkeypatch):
    from app.extensions import db
    from config import Config

    _STALE_DB_ROOT.mkdir(parents=True, exist_ok=True)
    stale_path = _STALE_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    conn = sqlite3.connect(stale_path)
    conn.execute("CREATE TABLE stale_config_marker (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + stale_path.as_posix())

    app = _make_app(monkeypatch)
    try:
        with app.app_context():
            engine_url = str(db.engine.url)
            on_stale_db = inspect(db.engine).has_table("stale_config_marker")
            users = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            responses = db.session.execute(text("SELECT COUNT(*) FROM survey_responses")).scalar()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        stale_path.unlink(missing_ok=True)

    assert engine_url == "sqlite:///:memory:"
    assert not on_stale_db
    assert users == 0
    assert responses == 0
