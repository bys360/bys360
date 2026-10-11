"""BYS360 performance: failed saves must not be reported as successful.

Two POST routes told the user a save had succeeded even when it had failed:

  1. POST /performance/feedback-followup/actions/<id>/quick-update
     (main.performance_feedback_followup_quick_update,
     app/performance/feedback_followup_phase4_routes.py)
     update_followup_action() rolls back and returns None when the UPDATE
     fails, but the route ignored the return value and always flashed
     "Eylem planı takip bilgisi güncellendi." ("success").
     feedback_meeting_action_plans.meeting_id is NOT NULL, so a successful
     update always returns the meeting id and None only means failure.

  2. POST /performance/meeting-development/faz10
     (main.performance_meeting_p4_development_guidance,
     app/performance/meeting_p4_development_guidance_routes.py)
     save_phase10_recommendation_from_request() flashes its own warning or
     error and returns False on validation or database failure, but the route
     then always added "Gelişim rehberi kaydı alındı." ("success").

The database failures below are real: a SQLite trigger aborts the statement,
so the production code path runs unchanged (no monkeypatching of app code).

Real Flask app, real test client and login, file-backed SQLite only.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

_PASSWORD = "SaveFailureFeedbackTest1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_save_failure_feedback")
_QUICK_UPDATE_SUCCESS = ("success", "Eylem planı takip bilgisi güncellendi.")
_GUIDANCE_SUCCESS = ("success", "Gelişim rehberi kaydı alındı.")
_FAZ10_PATH = "/performance/meeting-development/faz10"


def _make_app(monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-save-failure-feedback-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "test-password",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"save_failure_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

    from app.extensions import db
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
    return flask_app


@pytest.fixture
def perf_app(monkeypatch: pytest.MonkeyPatch):
    return _make_app(monkeypatch)


def _admin(flask_app) -> int:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        user = User(
            sicil_no="SFF000001",
            email="save-failure-feedback-admin@bys360.test",
            ad="SaveFailure",
            soyad="Admin",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return int(user.id)


def _login(client) -> None:
    response = client.post("/login", data={"sicil_or_email": "SFF000001", "password": _PASSWORD}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    with client.session_transaction() as session:
        session.pop("_flashes", None)  # drop the login flash; only the route under test counts


def _flashes(client) -> list[tuple[str, str]]:
    with client.session_transaction() as session:
        return [tuple(item) for item in session.get("_flashes", [])]


def _abort_trigger(flask_app, *, table: str, event: str) -> None:
    from app.extensions import db

    with flask_app.app_context():
        db.session.execute(text(
            f"CREATE TRIGGER save_failure_{event.lower()}_{table} BEFORE {event} ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'forced database failure'); END"
        ))
        db.session.commit()


# ---------------------------------------------------------------------------
# 1. Feedback follow-up quick update
# ---------------------------------------------------------------------------


def _seed_action(flask_app, admin_id: int) -> int:
    from app.extensions import db

    with flask_app.app_context():
        # The follow-up routes never read the feedback request; this test DB does
        # not enforce foreign keys, so a placeholder request id is enough.
        meeting_id = db.session.execute(text(
            "INSERT INTO feedback_meetings (feedback_request_id, employee_id, manager_id, meeting_date, meeting_start, "
            "meeting_end, meeting_type, status, created_at) "
            "VALUES (1, :uid, :uid, '2026-10-01', '10:00:00', '10:30:00', 'yuz_yuze', 'tamamlandi', "
            "CURRENT_TIMESTAMP) RETURNING id"
        ), {"uid": admin_id}).scalar_one()
        action_id = db.session.execute(text(
            "INSERT INTO feedback_meeting_action_plans (meeting_id, employee_id, manager_id, title, status) "
            "VALUES (:mid, :uid, :uid, 'Takip edilecek eylem', 'acik') RETURNING id"
        ), {"mid": meeting_id, "uid": admin_id}).scalar_one()
        db.session.commit()
        return int(action_id)


def _action_row(flask_app, action_id: int) -> tuple[str, str | None]:
    from app.extensions import db

    with flask_app.app_context():
        row = db.session.execute(
            text("SELECT status, follow_up_note FROM feedback_meeting_action_plans WHERE id=:id"), {"id": action_id}
        ).one()
        return row[0], row[1]


def _quick_update(client, action_id: int):
    return client.post(
        f"/performance/feedback-followup/actions/{action_id}/quick-update",
        data={"status": "tamamlandi", "follow_up_note": "Takip notu", "result_summary": "Sonuç"},
        follow_redirects=False,
    )


def test_quick_update_success_still_reports_success(perf_app) -> None:
    admin_id = _admin(perf_app)
    action_id = _seed_action(perf_app, admin_id)
    client = perf_app.test_client()
    _login(client)

    response = _quick_update(client, action_id)

    assert response.status_code == 302
    assert _flashes(client) == [_QUICK_UPDATE_SUCCESS]
    assert _action_row(perf_app, action_id) == ("tamamlandi", "Takip notu")


def test_quick_update_database_failure_is_not_reported_as_success(perf_app) -> None:
    admin_id = _admin(perf_app)
    action_id = _seed_action(perf_app, admin_id)
    _abort_trigger(perf_app, table="feedback_meeting_action_plans", event="UPDATE")
    client = perf_app.test_client()
    _login(client)

    response = _quick_update(client, action_id)

    assert response.status_code == 302
    flashes = _flashes(client)
    assert _QUICK_UPDATE_SUCCESS not in flashes
    assert [category for category, _ in flashes] == ["danger"]
    assert _action_row(perf_app, action_id) == ("acik", None)


# ---------------------------------------------------------------------------
# 2. Faz 10 development guidance save
# ---------------------------------------------------------------------------


def _install_guidance_table(flask_app, install_schema) -> None:
    from app.extensions import db

    with flask_app.app_context():
        install_schema(db.engine)


def _guidance_count(flask_app) -> int:
    from app.extensions import db

    with flask_app.app_context():
        return int(db.session.execute(text("SELECT COUNT(*) FROM performance_development_recommendations")).scalar_one())


def _post_guidance(client, recommendation_text: str):
    return client.post(
        _FAZ10_PATH,
        data={"recommendation_text": recommendation_text, "employee_name": "Test Personel"},
        follow_redirects=False,
    )


def test_guidance_save_success_still_reports_success(perf_app, install_development_recommendations_schema) -> None:
    _admin(perf_app)
    _install_guidance_table(perf_app, install_development_recommendations_schema)
    client = perf_app.test_client()
    _login(client)

    response = _post_guidance(client, "Somut gelişim önerisi")

    assert response.status_code == 302
    flashes = _flashes(client)
    assert ("success", "Gelişim planı iç değerlendirme kaydı olarak kaydedildi.") in flashes
    assert _GUIDANCE_SUCCESS in flashes
    assert _guidance_count(perf_app) == 1


def test_guidance_validation_failure_is_not_reported_as_success(perf_app, install_development_recommendations_schema) -> None:
    _admin(perf_app)
    _install_guidance_table(perf_app, install_development_recommendations_schema)
    client = perf_app.test_client()
    _login(client)

    response = _post_guidance(client, "")

    assert response.status_code == 302
    assert _flashes(client) == [("warning", "Gelişim önerisi metni boş bırakılamaz.")]
    assert _guidance_count(perf_app) == 0


def test_guidance_database_failure_is_not_reported_as_success(perf_app, install_development_recommendations_schema) -> None:
    _admin(perf_app)
    _install_guidance_table(perf_app, install_development_recommendations_schema)
    _abort_trigger(perf_app, table="performance_development_recommendations", event="INSERT")
    client = perf_app.test_client()
    _login(client)

    response = _post_guidance(client, "Somut gelişim önerisi")

    assert response.status_code == 302
    assert _flashes(client) == [
        ("danger", "Gelişim planı kaydedilemedi. Veritabanı şeması veya yetki kontrolü incelenmelidir."),
    ]
    assert _guidance_count(perf_app) == 0
