"""Contract: mobile score writes follow the web scoring rule (admin or the assignment's evaluator).

The web scoring workspace (``performance_v2_phase3_assignment``, also behind the Faz 4 /
Faz 8 aliases) refuses every save/submit/return/withdraw unless
``current_user.role == 'admin'`` or ``assignment.evaluator_id == current_user.id``.

POST /api/mobile/performance/tasks/<id>/score-form and /score-action only checked the
mobile read helper ``_v2822_can_view_assignment`` (evaluator or any mobile global role).
A ``baskan`` or ``baskan_yardimcisi`` who is not the evaluator could therefore write
level scores that are saved under the real evaluator's id, or withdraw/return a
completed evaluation, which the web refuses to the same user.

Rule reused: the web scoring rule above. Mobile read access (score-form GET, task
detail) is unchanged.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest

PASSWORD = "MobileScoreWriteScopeTest1!"
COMMENT = "Dönem boyunca hedeflerin önemli bir kısmı karşılandı; gelişim alanları not edildi."
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_score_write_scope" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-mobile-score-write", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "mobile-score-write-first-login",
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
    from app.models import EvaluationAssignment, PerformanceCriteria, PerformancePeriod, User
    from app.services.performance_v2.sync_service import sync_employee_assignments_v2

    with flask_app.app_context():
        db.create_all()
        users = {}
        for sicil, role in (("MSW01", "grup_baskani"), ("MSW02", "baskan"), ("MSW03", "admin"), ("MSW04", "personel")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Score", soyad=sicil, role=role,
                        birim="Birim-A", is_active=True, must_change_password=False, must_set_security_question=False)
            if sicil == "MSW04":
                user.yonetici_sicil = "MSW01"
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        criteria_ids = []
        for index in range(2):
            criteria = PerformanceCriteria(name=f"MSW Kriter {index}", weight=50.0, sort_order=index, is_active=True)
            db.session.add(criteria)
            db.session.flush()
            criteria_ids.append(int(criteria.id))
        period = PerformancePeriod(title="MSW Dönem", period_type="quarterly", start_date=date(2020, 1, 1),
                                   end_date=date(2020, 3, 31), is_active=True)
        db.session.add(period)
        db.session.commit()
        sync_employee_assignments_v2(period, employee=users["MSW04"])
        db.session.commit()
        assignment = EvaluationAssignment.query.filter_by(period_id=period.id, manager_level=1).one()
        assert assignment.evaluator_id == users["MSW01"].id
        flask_app.config["_ASSIGNMENT_ID"] = assignment.id
        flask_app.config["_CRITERIA_IDS"] = criteria_ids
        flask_app.config["_USER_IDS"] = {sicil: user.id for sicil, user in users.items()}
    return flask_app


def _headers(app, sicil):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, app.config["_USER_IDS"][sicil])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _submit(app, sicil, score=4):
    body = {
        "completed": True,
        "general_comment": COMMENT,
        "items": [{"criteria_id": cid, "score": score, "comment": "Kriter notu"} for cid in app.config["_CRITERIA_IDS"]],
    }
    return app.test_client().post(
        f"/api/mobile/performance/tasks/{app.config['_ASSIGNMENT_ID']}/score-form", json=body, headers=_headers(app, sicil)
    )


def _action(app, sicil, action):
    return app.test_client().post(
        f"/api/mobile/performance/tasks/{app.config['_ASSIGNMENT_ID']}/score-action",
        json={"action": action, "note": "Düzeltme gerekli."}, headers=_headers(app, sicil),
    )


def _state(app):
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation

    with app.app_context():
        assignment = db.session.get(EvaluationAssignment, app.config["_ASSIGNMENT_ID"])
        assert assignment is not None
        evaluation = PerformanceEvaluation.query.filter_by(period_id=assignment.period_id, employee_id=assignment.employee_id).first()
        level_1 = [float(item.score or 0) for item in evaluation.items] if evaluation is not None else []
        return assignment.status, bool(getattr(evaluation, "level_1_completed", False)), level_1


def test_web_scoring_rule_refuses_a_non_evaluator_president(app):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": "MSW02", "password": PASSWORD})
    assert response.status_code == 302
    before = _state(app)
    client.post(f"/performance/v2/faz3/assignment/{app.config['_ASSIGNMENT_ID']}", data={"action": "save"})
    assert _state(app) == before


def test_non_evaluator_global_role_cannot_submit_scores_from_mobile(app):
    before = _state(app)
    response = _submit(app, "MSW02", score=1)
    assert response.status_code == 403
    assert _state(app) == before


def test_non_evaluator_global_role_cannot_withdraw_a_completed_evaluation_from_mobile(app):
    assert _submit(app, "MSW01").status_code == 200
    completed = _state(app)
    assert completed[1] is True
    response = _action(app, "MSW02", "withdraw")
    assert response.status_code == 403
    assert _state(app) == completed


def test_non_evaluator_global_role_can_still_open_the_mobile_score_form(app):
    response = app.test_client().get(
        f"/api/mobile/performance/tasks/{app.config['_ASSIGNMENT_ID']}/score-form", headers=_headers(app, "MSW02")
    )
    assert response.status_code == 200


def test_evaluator_can_still_submit_and_withdraw_from_mobile(app):
    assert _submit(app, "MSW01").status_code == 200
    assert _state(app)[1] is True
    assert _action(app, "MSW01", "withdraw").status_code == 200
    assert _state(app)[1] is False


def test_admin_can_still_submit_from_mobile(app):
    assert _submit(app, "MSW03").status_code == 200
    assert _state(app)[1] is True


def test_unrelated_personnel_is_still_refused(app):
    assert _submit(app, "MSW04").status_code == 403
