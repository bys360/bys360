"""Contract: mobile survey submit requires a matching assignment, as the web does.

The web submit (``survey_submit``, POST /surveys/<id>/submit) and take page refuse every
user, a president or admin included, who has no matching ``SurveyAssignment``
(``matching_assignment_for_user``): "Bu anketi cevaplama yetkiniz yok.".

POST /api/mobile/surveys/<id>/submit accepted ``_has_global_scope(user) or assignment``,
and the mobile detail advertised the same in ``can_submit``. A mobile global role
(``admin``, ``baskan``, ``ik``, ...) outside the target audience could add a response,
stored with ``assignment_id=NULL``, that the web refuses to the same user; this skews the
survey results.

Rule reused: the web assignment requirement, through the mobile assignment matcher that
non-global mobile users already pass. The submit and the ``can_submit`` flag change
together (the consistency test fails if only one does). Mobile read access (list and
detail visibility) is unchanged.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "MobileSurveySubmitScopeTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_survey_submit_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-mobile-survey-submit", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "mobile-survey-submit-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import User
    from app.models.communication_models import Survey, SurveyAssignment, SurveyQuestion
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        users = {}
        for sicil, role in (("MSS01", "personel"), ("MSS02", "baskan"), ("MSS03", "admin"), ("MSS04", "personel")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Survey", soyad=sicil, role=role,
                        birim="Birim-A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()

        def _survey(target_type, target_value):
            survey = Survey(title=f"MSS {target_type}", description="MSS", survey_type="kurum_ici",
                            created_by_user_id=users["MSS03"].id, is_anonymous=False,
                            allow_multiple_submissions=False, status="published")
            db.session.add(survey)
            db.session.flush()
            db.session.add(SurveyAssignment(survey_id=survey.id, target_type=target_type, target_value=target_value))
            question = SurveyQuestion(survey_id=survey.id, question_text="MSS soru", question_type="text",
                                      is_required=False, sort_order=1)
            db.session.add(question)
            db.session.flush()
            return survey.id, question.id

        flask_app.config["_SURVEYS"] = {
            "targeted": _survey("user", str(users["MSS01"].id)),
            "president_role": _survey("role", "baskan"),
        }
        flask_app.config["_USER_IDS"] = {sicil: user.id for sicil, user in users.items()}
        db.session.commit()
    return flask_app


def _headers(app, sicil):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, app.config["_USER_IDS"][sicil])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _submit(app, sicil, key):
    survey_id, question_id = app.config["_SURVEYS"][key]
    return app.test_client().post(
        f"/api/mobile/surveys/{survey_id}/submit", json={"answers": {str(question_id): "cevap"}}, headers=_headers(app, sicil)
    )


def _responses(app, key):
    from app.extensions import db
    from app.models.communication_models import SurveyResponse

    with app.app_context():
        return db.session.query(SurveyResponse).filter_by(survey_id=app.config["_SURVEYS"][key][0]).count()


def test_web_submit_refuses_an_unassigned_president(app):
    survey_id, question_id = app.config["_SURVEYS"]["targeted"]
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": "MSS02", "password": PASSWORD}).status_code == 302
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)
    client.post(f"/surveys/{survey_id}/submit", data={f"question_{question_id}": "cevap"})
    with client.session_transaction() as sess:
        messages = [message for _category, message in sess.get("_flashes", [])]
    assert "Bu anketi cevaplama yetkiniz yok." in messages
    assert _responses(app, "targeted") == 0


@pytest.mark.parametrize("sicil", ["MSS01", "MSS02", "MSS03", "MSS04"])
def test_mobile_can_submit_flag_matches_the_mobile_submit_outcome(app, sicil):
    survey_id, _question_id = app.config["_SURVEYS"]["targeted"]
    detail = app.test_client().get(f"/api/mobile/surveys/{survey_id}", headers=_headers(app, sicil))
    advertised = detail.status_code == 200 and bool((detail.get_json() or {}).get("can_submit"))
    response = _submit(app, sicil, "targeted")
    assert response.status_code in (200, 403)
    assert (response.status_code == 200) is advertised
    assert _responses(app, "targeted") == (1 if advertised else 0)


@pytest.mark.parametrize("sicil", ["MSS02", "MSS03"])
def test_unassigned_mobile_global_role_cannot_submit(app, sicil):
    assert _submit(app, sicil, "targeted").status_code == 403
    assert _responses(app, "targeted") == 0


@pytest.mark.parametrize("sicil", ["MSS02", "MSS03"])
def test_unassigned_mobile_global_role_is_not_offered_submit(app, sicil):
    survey_id, _question_id = app.config["_SURVEYS"]["targeted"]
    detail = app.test_client().get(f"/api/mobile/surveys/{survey_id}", headers=_headers(app, sicil))
    assert detail.status_code == 200
    assert (detail.get_json() or {}).get("can_submit") is False


def test_unassigned_mobile_global_role_can_read_the_survey(app):
    survey_id, _question_id = app.config["_SURVEYS"]["targeted"]
    response = app.test_client().get(f"/api/mobile/surveys/{survey_id}", headers=_headers(app, "MSS02"))
    assert response.status_code == 200


def test_unassigned_personnel_is_refused_on_mobile(app):
    assert _submit(app, "MSS04", "targeted").status_code == 403
    assert _responses(app, "targeted") == 0


def test_targeted_personnel_can_submit_on_mobile(app):
    assert _submit(app, "MSS01", "targeted").status_code == 200
    assert _responses(app, "targeted") == 1


def test_global_role_in_the_target_audience_can_submit_on_mobile(app):
    assert _submit(app, "MSS02", "president_role").status_code == 200
    assert _responses(app, "president_role") == 1
