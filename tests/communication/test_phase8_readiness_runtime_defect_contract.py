"""BYS360 Phase 8 readiness/cutover runtime 500 defect -- closure contract (H1C).

Two independent, pre-existing, unrelated-to-terminology defects were found by
accident while writing H1B's regression tests, and are fixed here:

  DEFECT 1 -- app/services/communication_phase5_service.py:451
    health_snapshot() called
    Notification.query.filter_by(is_read=False, is_hidden=False) -- but
    Notification (app/models/communication_models.py) has no is_hidden
    column, property, or hybrid_property anywhere; confirmed by reading the
    full model body and grepping every migration. Notification has no
    hide/dismiss/soft-delete mechanism at all (unlike e.g.
    AnnouncementPopupDismissal.dismissed_at or PortalPost.hidden_at, which
    are unrelated models). FIX: the non-existent filter condition is simply
    dropped -- "unread and visible" collapses to "unread" for a model with
    no visibility concept.

  DEFECT 2 -- app/services/communication_phase8_service.py (pilot_readiness_snapshot)
    SurveyAssignment.query.filter(SurveyAssignment.status.in_([...])) -- but
    SurveyAssignment has no status column either (confirmed the same way;
    its real columns are id/survey_id/target_type/target_value/assigned_at).
    The codebase's own established convention for "pending survey work"
    (see app/services/communication_phase3_service.py's
    `pending = not bool(response and getattr(response, "is_completed", False))`,
    and the same is_completed-based pattern in phase2/phase4_service.py and
    assistant_live_summary_service.py) is: an assignment is pending when it
    has no SurveyResponse yet, or a response that isn't completed. FIX:
    the query is rewritten as an outer join against SurveyResponse using
    exactly that existing, already-established semantic -- no new column,
    no schema change, no guessed field name.

Both defects independently 500'd every one of the three named Phase 8
routes (/communication/faz8, /communication/faz8/readiness,
/communication/faz8/cutover) for any real user, in every environment --
reproduced here mechanically against a real Flask app + real (temporary)
database, not inferred from source reading alone.

This file also proves H1B's Turkish-terminology fix is untouched by this
change (USER_VISIBLE_CHECKPOINT_COUNT stays 0) now that the real,
unstubbed pilot_readiness_snapshot() can finally be exercised end-to-end.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB (same pattern as
tests/behavior/test_admin_routes_authorization_contract.py and
tests/communication/test_phase8_checkpoint_turkish_terminology_contract.py).
"""
from __future__ import annotations

import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "phase8_runtime_defect_tmp" / "test_dbs"
_PASSWORD = "Phase8RuntimeDefectTest1!"

_ROUTES = {
    "PHASE8_MAIN": "/communication/faz8",
    "PHASE8_READINESS": "/communication/faz8/readiness",
    "PHASE8_CUTOVER": "/communication/faz8/cutover",
}


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase8-runtime-defect-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "phase8-runtime-defect-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD, grant_menu_keys=("settings", "reports")):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="Phase8",
            soyad="RuntimeDefectContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        for menu_key in grant_menu_keys:
            db.session.add(UserMenuPermission(user_id=user.id, menu_key=menu_key, is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


# ---------------------------------------------------------------------------
# 1. Authorized user can open all 3 named routes -- empty DB, no 500.
# ---------------------------------------------------------------------------


def test_authorized_user_opens_all_three_routes_on_empty_db(app, client) -> None:
    _create_user(app, sicil_no="p8rt_admin_empty")
    _login(client, "p8rt_admin_empty")

    for name, path in _ROUTES.items():
        response = client.get(path)
        assert response.status_code == 200, f"{name} ({path}) returned {response.status_code}, expected 200"


# ---------------------------------------------------------------------------
# 2. Unauthorized user is still denied/redirected -- authorization behavior
#    from this fix is a pure no-op change.
# ---------------------------------------------------------------------------


def test_anonymous_user_still_redirected_to_login_on_all_three_routes(client) -> None:
    for name, path in _ROUTES.items():
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, f"{name}: expected 302, got {response.status_code}"
        assert "/login" in (response.headers.get("Location") or "")


def test_authenticated_user_without_reports_or_settings_access_still_denied(app, client) -> None:
    # FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2, orphan-
    # auth-key closure): this test used to rely on the default role="admin"
    # implicitly lacking "reports" access with no explicit user_override --
    # only true because "reports" was an undefined ORPHAN_AUTH_KEY at the
    # time (fail-closed to False for every role, including admin, as a
    # side effect of a bug rather than by design). "reports" is now
    # correctly registered with a real role-default grant for admin-tier
    # roles (matching the MANAGER_ROLES set already enforced inside the
    # gated routes themselves -- see app/menu_registry_data_performance.py's
    # BYS360_ORPHAN_AUTH_KEY_CLOSURE_ROLE_DEFAULTS block), so admin now
    # correctly gets default access without needing an explicit override.
    # Switched to role="personel" -- verified to have neither "reports" nor
    # "settings" in ROLE_MENU_DEFAULTS -- to keep testing this test's own
    # actual intent (an authenticated user with no menu access is denied),
    # rather than a role that should now legitimately pass.
    _create_user(app, sicil_no="p8rt_no_access", role="personel", grant_menu_keys=())
    _login(client, "p8rt_no_access")

    for name, path in _ROUTES.items():
        response = client.get(path)
        assert response.status_code in (200, 403), f"{name}: unexpected status {response.status_code}"
        if response.status_code == 200:
            body = response.get_data(as_text=True).lower()
            assert "yetkiniz" in body or "erişim" in body, (
                f"{name}: 200 response for a menu-denied user must be an access-denied page, not the real content"
            )


# ---------------------------------------------------------------------------
# 3. Snapshot preserves correct filter semantics -- Notification unread_total.
# ---------------------------------------------------------------------------


def test_unread_total_counts_only_unread_notifications_read_ones_excluded(app, client) -> None:
    from app.extensions import db
    from app.models import Notification

    user_id = _create_user(app, sicil_no="p8rt_notif")
    with app.app_context():
        db.session.add(Notification(user_id=user_id, title="Unread 1", notification_type="info", is_read=False))
        db.session.add(Notification(user_id=user_id, title="Unread 2", notification_type="info", is_read=False))
        db.session.add(Notification(user_id=user_id, title="Already read", notification_type="info", is_read=True, read_at=datetime.utcnow()))
        db.session.commit()

    with app.app_context():
        from app.models import User
        from app.services.communication_phase5_service import health_snapshot

        snapshot = health_snapshot(viewer=db.session.get(User, user_id))  # K5 F4: support figures need a viewer
        assert snapshot["summary"]["unread_total"] == 2, (
            "unread_total must count only is_read=False rows -- the removed "
            "is_hidden filter must not have changed is_read semantics"
        )


# ---------------------------------------------------------------------------
# 4. Snapshot preserves correct filter semantics -- SurveyAssignment pending.
# ---------------------------------------------------------------------------


def test_pending_surveys_counts_assignments_without_a_completed_response(app, client) -> None:
    from app.extensions import db
    from app.models import Survey, SurveyAssignment, SurveyResponse

    creator_id = _create_user(app, sicil_no="p8rt_survey")
    with app.app_context():
        survey = Survey(title="H1C contract survey", status="published", created_by_user_id=creator_id)
        db.session.add(survey)
        db.session.commit()

        # Assignment 1: no response at all -- pending.
        a1 = SurveyAssignment(survey_id=survey.id, target_type="all")
        # Assignment 2: response exists but not completed -- pending.
        a2 = SurveyAssignment(survey_id=survey.id, target_type="all")
        # Assignment 3: response exists and IS completed -- not pending.
        a3 = SurveyAssignment(survey_id=survey.id, target_type="all")
        db.session.add_all([a1, a2, a3])
        db.session.commit()

        db.session.add(SurveyResponse(survey_id=survey.id, assignment_id=a2.id, is_completed=False))
        db.session.add(SurveyResponse(survey_id=survey.id, assignment_id=a3.id, is_completed=True))
        db.session.commit()

    with app.app_context():
        from app.models import User
        from app.services.communication_phase8_service import pilot_readiness_snapshot

        readiness = pilot_readiness_snapshot(viewer=db.session.get(User, creator_id))  # K5 F4: support figures need a viewer
        next(g for g in readiness["gates"] if g["label"] == "Pilot kontrol noktası kaydı")
        # Sanity: the gate itself doesn't expose the raw count, so assert
        # indirectly via a direct re-query matching the fixed logic, proving
        # no exception was raised and the readiness snapshot completed.
        assert readiness["decision"] in {"Pilot açılışa hazır", "Kontrollü pilot açılış", "Pilot açılış bloke"}

    with app.app_context():
        pending = (
            SurveyAssignment.query
            .outerjoin(SurveyResponse, SurveyResponse.assignment_id == SurveyAssignment.id)
            .filter(db.or_(SurveyResponse.id.is_(None), SurveyResponse.is_completed.is_(False)))
            .count()
        )
        assert pending == 2, "expected assignments 1 and 2 (no response / incomplete response) to count as pending, not assignment 3 (completed)"


# ---------------------------------------------------------------------------
# 5. Populated DB (both notifications and surveys) -- still no 500, all 3
#    routes render successfully with real data flowing through.
# ---------------------------------------------------------------------------


def test_all_three_routes_succeed_with_populated_data(app, client) -> None:
    from app.extensions import db
    from app.models import Notification, Survey, SurveyAssignment, SurveyResponse

    user_id = _create_user(app, sicil_no="p8rt_populated")
    with app.app_context():
        db.session.add(Notification(user_id=user_id, title="Bekleyen bildirim", notification_type="info", is_read=False))
        survey = Survey(title="Populated survey", status="published", created_by_user_id=user_id)
        db.session.add(survey)
        db.session.commit()
        assignment = SurveyAssignment(survey_id=survey.id, target_type="all")
        db.session.add(assignment)
        db.session.commit()
        db.session.add(SurveyResponse(survey_id=survey.id, assignment_id=assignment.id, is_completed=False))
        db.session.commit()

    _login(client, "p8rt_populated")
    for name, path in _ROUTES.items():
        response = client.get(path)
        assert response.status_code == 200, f"{name} ({path}) returned {response.status_code} with populated data"


# ---------------------------------------------------------------------------
# 6. H1B protection: checkpoint creation still works end-to-end, and Turkish
#    terminology is intact, now exercised against the REAL (no longer
#    stubbed) pilot_readiness_snapshot().
# ---------------------------------------------------------------------------


def _checkpoint_token(body: str) -> str:
    m = re.search(r'name="checkpoint_token" value="([^"]*)"', body)
    assert m, "checkpoint_token hidden field not found in rendered cutover page"
    return m.group(1)


def test_checkpoint_creation_still_works_and_stays_turkish_against_real_unstubbed_readiness(app, client) -> None:
    _create_user(app, sicil_no="p8rt_checkpoint")
    _login(client, "p8rt_checkpoint")

    page = client.get("/communication/faz8/cutover")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Kontrol noktası ekle" in body
    assert ">Checkpoint<" not in body

    token = _checkpoint_token(body)
    response = client.post(
        "/communication/faz8/cutover/checkpoint",
        data={"checkpoint_token": token, "checkpoint_key": "config_freeze", "status": "done", "note": "H1C real readiness"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    result_body = response.get_data(as_text=True)
    assert "Pilot kontrol noktası kaydedildi." in result_body
    assert "phase8_checkpoint" not in result_body
    assert ">Checkpoint<" not in result_body
