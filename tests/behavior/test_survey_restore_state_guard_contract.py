"""BYS360_DEFECT_Q_REMEDIATION_SURVEY_RESTORE_STATE_GUARD_CONTRACT

Permanent regression contract for DEFECT Q (app/services/surveys/
state.py::restore_survey). Asserts the FIXED behavior only -- it does not
characterize, freeze, or otherwise exercise the prior buggy shape.

Prior defect (fixed by this same change): `restore_survey` unconditionally
set `survey.status = "draft"` regardless of the survey's current status,
unlike every sibling transition in the same file (publish_survey,
unpublish_survey, close_survey, archive_survey), and unlike this file's own
`bulk_survey_action`'s "restore" branch, which already correctly restricts
the source state to `archived` before writing `draft`
(`if (getattr(survey, "status", None) or "") == "archived": ...`). An
already-authorized survey manager could therefore POST
/survey-restore/<id> on a PUBLISHED or CLOSED survey and silently force it
back to draft -- an unintended "unpublish"/"reopen-to-draft" via the wrong
endpoint, with a success flash and no warning.

Canonical contract proven from production code before implementing (see
`bulk_survey_action`'s restore branch in app/services/surveys/state.py):
restore is valid ONLY from `archived`. The fix makes the singular
`restore_survey` reuse this exact same condition -- not a new state
machine -- and raise `ValueError` (the same exception contract every
sibling transition already uses via `_ensure_state_change`, and that
`app/communication/surveys_routes.py::survey_restore` already catches and
flashes as a warning) before any mutation occurs when the survey is not
currently archived.

Fixture pattern: this file's mandatory proven shape, copied from
tests/behavior/test_survey_admin_lifecycle_contract.py (Config
class-attribute patch BEFORE create_app(), StaticPool + pysqlite
isolation_level=None + explicit BEGIN event listener, real `/login` POST).
Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_qr_final_q) so it shares no state with any other
wave/agent/test file running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_qr_final_q")

DEFAULT_PASSWORD = "QrFinalQRestoreGuardTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "qr-final-q-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-qr-final-q-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"qr_final_q_{uuid.uuid4().hex}.sqlite3")
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
            sicil_no=f"QRFQ{n:06d}",
            email=f"qr-final-q-{n}@bys360.test",
            ad="QrFinalQ",
            soyad=f"RestoreGuard{n}",
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
            title=f"QrFinalQ Anket {uuid.uuid4().hex[:8]}",
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


def _survey_snapshot(app, survey_id):
    from app.models import Survey

    with app.app_context():
        survey = Survey.query.get(survey_id)
        if survey is None:
            return None
        return {"status": survey.status, "title": survey.title}


# ---------------------------------------------------------------------------
# 1. Route-boundary contract -- restore_survey via /survey-restore/<id>
# ---------------------------------------------------------------------------


def test_restore_from_archived_succeeds_and_sets_draft(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="archived", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-restore/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "draft"
    assert any("geri alındı" in msg for msg in _flashes(client))


def test_restore_published_survey_rejected_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="published", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-restore/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "published", "restoring a published survey must be rejected, not silently downgrade it to draft"
    assert any("yalnızca arşivden" in msg for msg in _flashes(client))


def test_restore_closed_survey_rejected_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="closed", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-restore/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "closed", "restoring a closed survey must be rejected, not silently downgrade it to draft"
    assert any("yalnızca arşivden" in msg for msg in _flashes(client))


def test_restore_draft_survey_noop_rejected_zero_mutation(app, client):
    manager_id, manager_sicil = _create_manager(app)
    survey_id = _create_survey(app, status="draft", created_by_id=manager_id)
    _login(client, manager_sicil)

    resp = client.post(f"/survey-restore/{survey_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert _survey_snapshot(app, survey_id)["status"] == "draft"
    assert any("yalnızca arşivden" in msg for msg in _flashes(client))


def test_restore_unknown_survey_id_handled_safely(app, client):
    _manager_id, manager_sicil = _create_manager(app)
    _login(client, manager_sicil)

    resp = client.post("/survey-restore/999999", follow_redirects=False)

    assert resp.status_code == 302
    assert any("bulunamadı" in msg for msg in _flashes(client))


def test_restore_denied_for_non_manager_zero_mutation(app, client):
    manager_id, _ = _create_manager(app)
    _personnel_id, personnel_sicil = _create_personnel(app)
    survey_id = _create_survey(app, status="archived", created_by_id=manager_id)
    _login(client, personnel_sicil)

    resp = client.post(f"/survey-restore/{survey_id}", follow_redirects=False)

    assert resp.status_code in (302, 403)
    assert _survey_snapshot(app, survey_id)["status"] == "archived"


# ---------------------------------------------------------------------------
# 2. Service-boundary contract -- restore_survey direct call, zero mutation
# ---------------------------------------------------------------------------


def test_service_restore_survey_from_archived_succeeds(app):
    from app.extensions import db
    from app.models import Survey
    from app.services.surveys.state import restore_survey

    manager_id, _ = _create_manager(app)
    survey_id = _create_survey(app, status="archived", created_by_id=manager_id)

    with app.app_context():
        survey = Survey.query.get(survey_id)
        result = restore_survey(survey, db_session=db.session)
        assert result.affected == 1
        assert survey.status == "draft"


@pytest.mark.parametrize("blocked_status", ["published", "closed", "draft"])
def test_service_restore_survey_rejects_non_archived_source_zero_mutation(app, blocked_status):
    from app.extensions import db
    from app.models import Survey
    from app.services.surveys.state import restore_survey

    manager_id, _ = _create_manager(app)
    survey_id = _create_survey(app, status=blocked_status, created_by_id=manager_id)

    with app.app_context():
        survey = Survey.query.get(survey_id)
        with pytest.raises(ValueError):
            restore_survey(survey, db_session=db.session)
        db.session.rollback()
        refreshed = Survey.query.get(survey_id)
        assert refreshed.status == blocked_status, "a rejected restore transition must leave the survey's status completely unchanged"
