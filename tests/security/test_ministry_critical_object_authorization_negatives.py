"""Negative authorization contracts for critical objects (G5/G6-A).

Each case pins the refusal the route already returns (derived from its guard
chain and the existing contracts, then confirmed on the unmodified code) and
proves the refused request changed nothing:

* horizontal IDOR -- another personnel's scorecard / evaluation assignment,
  another user's File Center chunk-upload session;
* vertical escalation -- a ``personel`` user calling admin/manager-only
  mutations (personnel deactivation, period/criteria/org-unit deletion,
  survey lifecycle, development notes);
* unauthenticated access and ID tampering (non-existent ids).

Guard chains: ``login_required`` redirects anonymous users to ``/login``; the
``/admin/*`` path guard (app/bootstrap/operational_guards.py) answers anonymous
and non-admin requests with 403 before the view; ``admin_required`` /
``manager_required`` / ``menu_key_required`` and the phase-3 evaluation
visibility guard answer with the corporate 403 page; ``get_or_404`` runs
before object guards, so a non-existent id is 404.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "MinistryAuthzNegativeTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "ministry_authz_negatives" / "dbs"
MISSING_ID = 987654


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-ministry-authz-negatives",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "ministry-authz-first-login",
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
        # File Center is off by default; enable it so the ownership gate (not the feature gate) is tested.
        "FILE_CENTER_ENABLED": "true",
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
def env(monkeypatch):
    from app.extensions import db
    from app.models import (
        EvaluationAssignment,
        OrganizationUnit,
        PerformanceCriteria,
        PerformanceEvaluation,
        PerformancePeriod,
        Survey,
        User,
    )
    from app.models.file_center_models import FileUploadSession

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    ids: dict[str, int] = {}
    with app.app_context():
        db.create_all()
        for key, role in (
            ("admin", "admin"),
            ("owner", "personel"),
            ("evaluator", "personel"),
            ("intruder", "personel"),
            ("target", "personel"),
        ):
            sicil = f"MAZN{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Yetki",
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
            title="Yetki Sözleşmesi Dönemi",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.flush()
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=ids["owner"])
        assignment = EvaluationAssignment(
            period_id=period.id,
            employee_id=ids["target"],
            evaluator_id=ids["evaluator"],
            manager_level=1,
            status="bekliyor",
        )
        criteria = PerformanceCriteria(name="Yetki Sözleşmesi Kriteri")
        unit = OrganizationUnit(name="Yetki Sözleşmesi Birimi")
        draft_survey = Survey(title="Taslak Anket", created_by_user_id=ids["admin"], status="draft")
        live_survey = Survey(
            title="Yayındaki Anket", created_by_user_id=ids["admin"], status="published"
        )
        upload = FileUploadSession(
            owner_user_id=ids["owner"],
            session_token=uuid.uuid4().hex,
            original_filename="sahip-dosyasi.pdf",
        )
        db.session.add_all(
            [evaluation, assignment, criteria, unit, draft_survey, live_survey, upload]
        )
        db.session.commit()
        ids.update(
            period=int(period.id),
            evaluation=int(evaluation.id),
            assignment=int(assignment.id),
            criteria=int(criteria.id),
            unit=int(unit.id),
            draft_survey=int(draft_survey.id),
            live_survey=int(live_survey.id),
            upload=int(upload.id),
        )
    yield SimpleNamespace(app=app, ids=ids)
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


def _url(env, endpoint: str, **values) -> str:
    from flask import url_for

    with env.app.test_request_context():
        return url_for(endpoint, **values)


def _client(env, who=None):
    client = env.app.test_client()
    if who is not None:
        response = client.post(
            "/login", data={"sicil_or_email": f"MAZN{who.upper()}", "password": PASSWORD}
        )
        assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _state(env) -> dict:
    """Every column a refused request could have mutated."""
    from app.extensions import db
    from app.models import (
        EvaluationAssignment,
        OrganizationUnit,
        PerformanceCriteria,
        PerformanceEvaluation,
        PerformanceEvaluationItem,
        PerformancePeriod,
        Survey,
        User,
    )
    from app.models.file_center_models import FileUploadSession

    ids = env.ids
    with env.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, ids["evaluation"])
        assignment = db.session.get(EvaluationAssignment, ids["assignment"])
        target = db.session.get(User, ids["target"])
        period = db.session.get(PerformancePeriod, ids["period"])
        upload = db.session.get(FileUploadSession, ids["upload"])
        assert evaluation is not None and assignment is not None and target is not None
        state = {
            "target_active": target.is_active,
            "period": None if period is None else bool(period.is_active),
            "criteria": db.session.get(PerformanceCriteria, ids["criteria"]) is not None,
            "unit": db.session.get(OrganizationUnit, ids["unit"]) is not None,
            "surveys": {s.id: s.status for s in Survey.query.order_by(Survey.id).all()},
            "evaluation_ack": (
                evaluation.employee_score_viewed_at,
                evaluation.employee_score_acknowledged_at,
                evaluation.employee_score_acknowledged_note,
            ),
            "assignment": (assignment.status, assignment.completed_at),
            "evaluation_items": PerformanceEvaluationItem.query.count(),
            "upload": None if upload is None else upload.status,
        }
        db.session.remove()
        return state


# --- performance scorecard: horizontal IDOR, unauthenticated, ID tampering --------------------


@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_scorecard_of_another_personnel_is_refused_403(env, suffix):
    before = _state(env)
    response = _client(env, "intruder").get(
        f"/performance/scorecard/{env.ids['evaluation']}{suffix}"
    )
    assert response.status_code == 403
    assert _state(env) == before


@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_scorecard_guard_is_object_specific_owner_is_not_refused(env, suffix):
    response = _client(env, "owner").get(f"/performance/scorecard/{env.ids['evaluation']}{suffix}")
    assert response.status_code != 403


def test_scorecard_acknowledge_by_another_personnel_redirects_without_writing(env):
    before = _state(env)
    evaluation_id = env.ids["evaluation"]
    response = _client(env, "intruder").post(
        f"/performance/scorecard/{evaluation_id}/acknowledge",
        data={"ack_note": "başkasının karnesi"},
    )
    assert response.status_code == 302
    assert f"/performance/scorecard/{evaluation_id}" in response.headers["Location"]
    assert _state(env) == before


def test_scorecard_development_note_is_refused_for_personnel_role(env):
    before = _state(env)
    response = _client(env, "intruder").post(
        f"/performance/scorecard/{env.ids['evaluation']}/development-note",
        data={"recommendation_text": "yetkisiz gelişim notu"},
    )
    assert response.status_code == 403
    assert _state(env) == before


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("get", ""), ("get", "/pdf"), ("post", "/acknowledge"), ("post", "/development-note")],
)
def test_scorecard_routes_redirect_anonymous_users_to_login(env, method, suffix):
    before = _state(env)
    response = getattr(_client(env), method)(
        f"/performance/scorecard/{env.ids['evaluation']}{suffix}"
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert _state(env) == before


@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_scorecard_with_tampered_missing_id_is_404(env, suffix):
    response = _client(env, "intruder").get(f"/performance/scorecard/{MISSING_ID}{suffix}")
    assert response.status_code == 404


# --- performance v2 evaluation assignment: horizontal IDOR -----------------------------------

ASSIGNMENT_PATHS = (
    "/performance/v2/faz3/assignment/{id}",
    "/performans/v2/faz3/assignment/{id}",
    "/performance/v2/faz4/assignment/{id}",
    "/performance/v2/faz8/assignment/{id}",
)


@pytest.mark.parametrize("template", ASSIGNMENT_PATHS)
def test_assignment_of_another_evaluator_is_refused_with_redirect(env, template):
    response = _client(env, "intruder").get(template.format(id=env.ids["assignment"]))
    assert response.status_code == 302
    assert response.headers["Location"].endswith(_url(env, "main.performance_v2_phase3_dashboard"))


def test_assignment_post_by_another_evaluator_writes_no_scores_or_status(env):
    before = _state(env)
    response = _client(env, "intruder").post(
        f"/performance/v2/faz3/assignment/{env.ids['assignment']}",
        data={
            "action": "submit",
            f"score_{env.ids['criteria']}": "5",
            "general_comment": "yetkisiz",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(_url(env, "main.performance_v2_phase3_dashboard"))
    after = _state(env)
    assert after["assignment"] == before["assignment"]
    assert after["evaluation_items"] == before["evaluation_items"] == 0


def test_assignment_owner_is_not_refused(env):
    response = _client(env, "evaluator").get(
        f"/performance/v2/faz3/assignment/{env.ids['assignment']}"
    )
    assert response.status_code == 200


def test_assignment_redirects_anonymous_users_to_login(env):
    response = _client(env).get(f"/performance/v2/faz3/assignment/{env.ids['assignment']}")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_assignment_with_tampered_missing_id_is_404(env):
    response = _client(env, "intruder").get(f"/performance/v2/faz3/assignment/{MISSING_ID}")
    assert response.status_code == 404


# --- vertical escalation: personel -> admin-only mutations -----------------------------------

ADMIN_MUTATIONS = (
    ("/personnel/{target}/toggle-active", "target_active"),
    ("/performance/periods/{period}/toggle-active", "period"),
    ("/performance/periods/{period}/delete", "period"),
    ("/performance/criteria/{criteria}/delete", "criteria"),
    ("/admin/org-units/{unit}/delete", "unit"),
)


@pytest.mark.parametrize(
    ("template", "field"), ADMIN_MUTATIONS, ids=[t for t, _ in ADMIN_MUTATIONS]
)
def test_admin_mutation_is_refused_403_for_personnel_with_zero_mutation(env, template, field):
    before = _state(env)
    response = _client(env, "intruder").post(template.format(**env.ids))
    assert response.status_code == 403
    assert _state(env) == before


@pytest.mark.parametrize(
    ("template", "field"), ADMIN_MUTATIONS, ids=[t for t, _ in ADMIN_MUTATIONS]
)
def test_admin_mutation_rejects_anonymous_with_zero_mutation(env, template, field):
    before = _state(env)
    response = _client(env).post(template.format(**env.ids))
    if template.startswith("/admin/"):
        # /admin/* path guard answers before login_required (existing admin-ops contract).
        assert response.status_code == 403
    else:
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]
    assert _state(env) == before


# --- vertical escalation: survey lifecycle ----------------------------------------------------

SURVEY_ACTIONS = (
    ("publish", "draft_survey"),
    ("close", "live_survey"),
    ("archive", "live_survey"),
    ("reopen", "live_survey"),
)


@pytest.mark.parametrize(("action", "survey"), SURVEY_ACTIONS, ids=[a for a, _ in SURVEY_ACTIONS])
def test_survey_lifecycle_is_refused_for_personnel_with_zero_mutation(env, action, survey):
    # personel passes menu_key_required("surveys"); the in-view is_manager() gate refuses
    # with a flash + redirect to the survey list (communication/phase2_routes.py).
    before = _state(env)
    response = _client(env, "intruder").post(
        f"/communication/faz2/surveys/{env.ids[survey]}/{action}"
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(_url(env, "main.communication_phase2_surveys"))
    assert _state(env) == before


@pytest.mark.parametrize(("action", "survey"), SURVEY_ACTIONS, ids=[a for a, _ in SURVEY_ACTIONS])
def test_survey_lifecycle_redirects_anonymous_users_to_login(env, action, survey):
    before = _state(env)
    response = _client(env).post(f"/communication/faz2/surveys/{env.ids[survey]}/{action}")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert _state(env) == before


# --- File Center: another user's chunk-upload session -----------------------------------------


def test_chunk_upload_session_status_of_another_user_is_refused_403(env):
    response = _client(env, "intruder").get(
        f"/file-center/chunk-upload/session/{env.ids['upload']}/status"
    )
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["ok"] is False
    assert "sahip-dosyasi.pdf" not in response.get_data(as_text=True)


def test_chunk_upload_session_cancel_of_another_user_is_refused_without_mutation(env):
    before = _state(env)
    response = _client(env, "intruder").post(
        f"/file-center/chunk-upload/session/{env.ids['upload']}/cancel"
    )
    assert response.status_code == 403
    assert _state(env) == before


def test_chunk_upload_session_owner_status_is_not_refused(env):
    response = _client(env, "owner").get(
        f"/file-center/chunk-upload/session/{env.ids['upload']}/status"
    )
    assert response.status_code == 200


def test_chunk_upload_session_with_tampered_missing_id_is_404(env):
    response = _client(env, "intruder").get(
        f"/file-center/chunk-upload/session/{MISSING_ID}/status"
    )
    assert response.status_code == 404
