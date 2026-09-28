"""BYS360 Test Integration Expansion Wave 2 -- communication/survey/push
security negatives.

Real Flask ``test_client()`` against the real mobile survey-submit,
push-token, and announcement-acknowledge routes. Focused on adversarial /
malformed input handling: bad auth headers, malformed JSON, oversized or
SQL-special-character payloads, and negative numeric ids -- proving the real
route + real parameterized-SQL / ORM layer degrades safely (4xx, no crash,
no injected row) rather than 500ing or writing bad state.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


def _make_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-communication-security-negatives")
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
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has

    return app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user_and_token(app, client, *, sicil_no, email, password="CommSecurityTestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave2",
            soyad="Security",
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


def _create_survey_with_text_question(app, *, creator_id):
    from app.extensions import db
    from app.models.communication_models import Survey, SurveyAssignment, SurveyQuestion

    with app.app_context():
        survey = Survey(
            title="Security negative anket",
            survey_type="kurum_ici",
            created_by_user_id=creator_id,
            status="published",
        )
        db.session.add(survey)
        db.session.commit()
        db.session.add(SurveyAssignment(survey_id=survey.id, target_type="all"))
        question = SurveyQuestion(
            survey_id=survey.id,
            question_text="Yorumunuz?",
            question_type="text",
            is_required=False,
            sort_order=1,
        )
        db.session.add(question)
        db.session.commit()
        return survey.id, question.id


def _create_survey_with_single_choice(app, *, creator_id):
    from app.extensions import db
    from app.models.communication_models import Survey, SurveyAssignment, SurveyQuestion

    with app.app_context():
        survey = Survey(
            title="Security negative option anket",
            survey_type="kurum_ici",
            created_by_user_id=creator_id,
            status="published",
        )
        db.session.add(survey)
        db.session.commit()
        db.session.add(SurveyAssignment(survey_id=survey.id, target_type="all"))
        question = SurveyQuestion(
            survey_id=survey.id,
            question_text="Seçiminiz?",
            question_type="single_choice",
            is_required=True,
            sort_order=1,
        )
        db.session.add(question)
        db.session.commit()
        return survey.id, question.id


def _create_creator(app) -> int:
    from app.extensions import db
    from app.models import User

    with app.app_context():
        creator = User(
            sicil_no="90700",
            email="w2.security.creator@bys360.test",
            ad="Wave2",
            soyad="Creator",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        creator.set_password("SecurityCreatorTest1!")
        db.session.add(creator)
        db.session.commit()
        return creator.id


def _response_count(app) -> int:
    from app.extensions import db
    from app.models.communication_models import SurveyResponse

    with app.app_context():
        return db.session.query(SurveyResponse).count()


# --- MALFORMED-AUTH NEGATIVE ---


def test_survey_submit_with_malformed_authorization_header_returns_401(app, client):
    creator_id = _create_creator(app)
    survey_id, _qid = _create_survey_with_text_question(app, creator_id=creator_id)
    _create_user_and_token(app, client, sicil_no="90701", email="w2.security.malformedauth@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {}},
        headers={"Authorization": "NotBearer garbage-token-value"},
    )

    assert response.status_code == 401
    assert _response_count(app) == 0


def test_survey_submit_with_tampered_bearer_token_returns_401(app, client):
    creator_id = _create_creator(app)
    survey_id, _qid = _create_survey_with_text_question(app, creator_id=creator_id)
    _, headers = _create_user_and_token(app, client, sicil_no="90702", email="w2.security.tampered@bys360.test")
    tampered = {"Authorization": headers["Authorization"] + "tampered-suffix"}

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {}},
        headers=tampered,
    )

    assert response.status_code == 401


def test_push_status_without_bearer_prefix_returns_401(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90703", email="w2.security.noprefix@bys360.test")
    raw_token = headers["Authorization"].split(" ", 1)[1]

    response = client.get("/api/mobile/push/status", headers={"Authorization": raw_token})

    assert response.status_code == 401


# --- MALFORMED-PAYLOAD NEGATIVE ---


def test_survey_submit_with_non_json_body_does_not_crash(app, client):
    creator_id = _create_creator(app)
    # Required question: get_json(silent=True) on unparsable body yields {},
    # so answers resolve to {} -- the required-field validation path (not a
    # 500 crash) is what should reject this, proving the malformed body is
    # absorbed safely rather than propagating a parse exception.
    survey_id, _qid = _create_survey_with_single_choice(app, creator_id=creator_id)
    _, headers = _create_user_and_token(app, client, sicil_no="90704", email="w2.security.nonjson@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        data="this is not json",
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


def test_push_register_token_with_non_string_token_value_does_not_crash(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90705", email="w2.security.nonstring@bys360.test")

    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": 123456789},
        headers=headers,
    )

    assert response.status_code < 500


def test_survey_submit_with_unexpected_extra_field_is_ignored_not_500(app, client):
    creator_id = _create_creator(app)
    survey_id, qid = _create_survey_with_text_question(app, creator_id=creator_id)
    _, headers = _create_user_and_token(app, client, sicil_no="90706", email="w2.security.extrafield@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): "gecerli cevap"}, "unexpected_admin_flag": True, "survey_id": 999999},
        headers=headers,
    )

    assert response.status_code == 200
    assert _response_count(app) == 1


# --- ADVERSARIAL-STRING NEGATIVE: stored safely, no injection/crash ---


def test_push_token_with_sql_special_characters_is_stored_as_literal_text(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90707", email="w2.security.sqlchars@bys360.test")
    adversarial_token = "abc'); DROP TABLE mobile_push_tokens; --"

    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": adversarial_token},
        headers=headers,
    )

    assert response.status_code == 200

    from app.extensions import db

    with app.app_context():
        # Table must still exist and the value must be stored verbatim --
        # proves the parameterized `text()` query treats it as inert data.
        count = db.session.execute(text("SELECT COUNT(*) FROM mobile_push_tokens")).scalar()
        assert count == 1
        row = db.session.execute(
            text("SELECT token FROM mobile_push_tokens WHERE token = :t"), {"t": adversarial_token}
        ).mappings().first()
        assert row is not None
        assert row["token"] == adversarial_token


def test_survey_text_answer_with_script_payload_is_stored_verbatim_not_executed(app, client):
    creator_id = _create_creator(app)
    survey_id, qid = _create_survey_with_text_question(app, creator_id=creator_id)
    _, headers = _create_user_and_token(app, client, sicil_no="90708", email="w2.security.xsspayload@bys360.test")
    payload_text = "<script>alert('xss')</script>"

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): payload_text}},
        headers=headers,
    )

    assert response.status_code == 200

    from app.extensions import db
    from app.models.communication_models import SurveyAnswer

    with app.app_context():
        answer = db.session.query(SurveyAnswer).first()
        assert answer is not None
        # Stored as plain data, not stripped/escaped at the persistence layer
        # (escaping is a rendering-layer concern) -- proves no crash and no
        # silent corruption of the stored value.
        assert answer.answer_text == payload_text


def test_survey_submit_with_negative_option_id_returns_400_and_writes_no_rows(app, client):
    creator_id = _create_creator(app)
    survey_id, qid = _create_survey_with_single_choice(app, creator_id=creator_id)
    _, headers = _create_user_and_token(app, client, sicil_no="90709", email="w2.security.negativeoption@bys360.test")

    response = client.post(
        f"/api/mobile/surveys/{survey_id}/submit",
        json={"answers": {str(qid): -1}},
        headers=headers,
    )

    assert response.status_code == 400
    assert _response_count(app) == 0


# --- ANNOUNCEMENT RUNTIME TOKEN ADVERSARIAL NEGATIVE ---


def test_announcement_acknowledge_with_oversized_runtime_token_returns_400(app, client):
    from app.extensions import db
    from app.models import User
    from app.models.announcement_popup_models import Announcement, AnnouncementRead

    with app.app_context():
        user = User(
            sicil_no="90710",
            email="w2.security.oversizedtoken@bys360.test",
            ad="Wave2",
            soyad="Security",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("CommSecurityTestKey1!")
        db.session.add(user)
        announcement = Announcement(
            title="Adversarial duyuru",
            body="Oversized token negative test",
            is_active=True,
            target_scope="all",
        )
        db.session.add(announcement)
        db.session.commit()
        announcement_id = announcement.id
        user_id = user.id

    login = client.post(
        "/login",
        data={"sicil_or_email": "90710", "password": "CommSecurityTestKey1!"},
        follow_redirects=False,
    )
    assert login.status_code == 302

    response = client.post(
        f"/announcements/popup/{announcement_id}/acknowledge",
        data={"runtime_token": "x" * 5000},
    )

    assert response.status_code == 400

    with app.app_context():
        count = (
            db.session.query(AnnouncementRead)
            .filter_by(announcement_id=announcement_id, user_id=user_id)
            .count()
        )
        assert count == 0
