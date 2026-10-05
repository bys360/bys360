"""BYS360 Test Integration Expansion Wave 1 — mobile notification state transitions.

Real Flask ``test_client()`` + real in-memory SQLite DB. Verifies the
before/after DB state of a write endpoint (is_read flip), ownership
isolation between users, and a real commit-failure rollback path.
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
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-notification-flows")
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


def _create_user_and_token(app, client, *, sicil_no, email, password="NotifTestFlow1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave1",
            soyad="Notif",
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


def _create_notification(app, user_id: int) -> int:
    from app.extensions import db
    from app.models.communication_models import Notification

    with app.app_context():
        notification = Notification(
            user_id=user_id,
            title="Wave1 test bildirimi",
            body="Bu bildirim entegrasyon testi için oluşturuldu.",
            notification_type="test",
            is_read=False,
        )
        db.session.add(notification)
        db.session.commit()
        return notification.id


def _is_read(app, notification_id: int) -> bool:
    from app.extensions import db
    from app.models.communication_models import Notification

    with app.app_context():
        row = db.session.get(Notification, notification_id)
        assert row is not None
        return bool(row.is_read)


# --- DB-INTEGRATION: real before/after state transition ---


def test_mark_notification_read_flips_is_read_from_false_to_true(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90200", email="w1.notif.owner@bys360.test")
    notification_id = _create_notification(app, user_id)

    assert _is_read(app, notification_id) is False

    response = client.post(f"/api/mobile/notifications/{notification_id}/read", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert _is_read(app, notification_id) is True


def test_mark_notification_read_sets_read_at_timestamp(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90201", email="w1.notif.readat@bys360.test")
    notification_id = _create_notification(app, user_id)

    client.post(f"/api/mobile/notifications/{notification_id}/read", headers=headers)

    from app.extensions import db
    from app.models.communication_models import Notification

    with app.app_context():
        row = db.session.get(Notification, notification_id)
        assert row is not None
        assert row.read_at is not None


def test_mark_notification_read_is_idempotent_on_repeat_call(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90202", email="w1.notif.repeat@bys360.test")
    notification_id = _create_notification(app, user_id)

    first = client.post(f"/api/mobile/notifications/{notification_id}/read", headers=headers)
    second = client.post(f"/api/mobile/notifications/{notification_id}/read", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _is_read(app, notification_id) is True


# --- AUTHZ-NEGATIVE: ownership isolation ---


def test_user_cannot_mark_another_users_notification_as_read(app, client):
    owner_id, _owner_headers = _create_user_and_token(app, client, sicil_no="90203", email="w1.notif.real_owner@bys360.test")
    _, intruder_headers = _create_user_and_token(app, client, sicil_no="90204", email="w1.notif.intruder@bys360.test")
    notification_id = _create_notification(app, owner_id)

    response = client.post(f"/api/mobile/notifications/{notification_id}/read", headers=intruder_headers)

    assert response.status_code == 404
    assert _is_read(app, notification_id) is False


def test_mark_nonexistent_notification_read_returns_404(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90205", email="w1.notif.missing@bys360.test")

    response = client.post("/api/mobile/notifications/999999/read", headers=headers)

    assert response.status_code == 404


def test_mark_notification_read_without_auth_returns_401(app, client):
    user_id, _headers = _create_user_and_token(app, client, sicil_no="90206", email="w1.notif.noauth@bys360.test")
    notification_id = _create_notification(app, user_id)

    response = client.post(f"/api/mobile/notifications/{notification_id}/read")

    assert response.status_code == 401
    assert _is_read(app, notification_id) is False


# --- SERVICE-INTEGRATION: the endpoint's own try/except/rollback path ---


def test_mark_notification_read_commit_failure_rolls_back_and_stays_unread(app, client, monkeypatch):
    """This endpoint already wraps its commit in try/except + rollback
    (app/api/mobile/domains/notifications.py). This test proves that
    existing safety net actually leaves is_read=False when commit fails,
    rather than merely asserting the code shape."""
    user_id, headers = _create_user_and_token(app, client, sicil_no="90207", email="w1.notif.rollback@bys360.test")
    notification_id = _create_notification(app, user_id)

    import app.api.mobile.domains.notifications as notifications_module

    def _raise_on_commit():
        raise RuntimeError("simulated commit failure for notification rollback test")

    monkeypatch.setattr(notifications_module.db.session, "commit", _raise_on_commit)

    response = client.post(f"/api/mobile/notifications/{notification_id}/read", headers=headers)

    assert response.status_code == 500

    monkeypatch.undo()
    assert _is_read(app, notification_id) is False


# --- isolation from a stale process-global Config database URI ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported. If an earlier test imported it while DATABASE_URL pointed at
# its own SQLite file, setting DATABASE_URL here came too late: this module's
# apps silently used that file and collided on users.email when run again in
# the same process.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_notification_state_stale_config"


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
    counts = {}
    try:
        with app.app_context():
            engine_url = str(db.engine.url)
            on_stale_db = inspect(db.engine).has_table("stale_config_marker")
            counts["users"] = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            counts["notifications"] = db.session.execute(
                text("SELECT COUNT(*) FROM notifications")
            ).scalar()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        stale_path.unlink(missing_ok=True)

    assert engine_url == "sqlite:///:memory:"
    assert not on_stale_db
    assert counts == {"users": 0, "notifications": 0}
