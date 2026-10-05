"""BYS360 Test Integration Expansion Wave 2 -- mobile notification bulk dispatch.

Real Flask ``test_client()`` against
``POST /api/mobile/notifications/read-all``
(``app/api/mobile/domains/notifications.py::mobile_notifications_mark_all_read_v2864``),
a real in-memory SQLite DB, and real ``Notification`` ORM rows. This
endpoint's sibling single-notification mark-read route already has real-HTTP
coverage from Wave 1 (``tests/integration/test_mobile_notification_state_transitions.py``);
this file closes the gap on the bulk read-all path -- ownership isolation,
idempotency, mixed read/unread state, and its own rollback path.
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
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-notification-dispatch")
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


def _create_user_and_token(app, client, *, sicil_no, email, password="NotifDispatchTest1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave2",
            soyad="Dispatch",
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


def _create_notification(app, user_id: int, *, is_read=False):
    from app.extensions import db
    from app.models.communication_models import Notification

    with app.app_context():
        notification = Notification(
            user_id=user_id,
            title="Wave2 toplu bildirim",
            body="Bulk read-all entegrasyon testi.",
            notification_type="test",
            is_read=is_read,
        )
        db.session.add(notification)
        db.session.commit()
        return notification.id


def _notification_state(app, notification_id: int):
    from app.extensions import db
    from app.models.communication_models import Notification

    with app.app_context():
        row = db.session.get(Notification, notification_id)
        assert row is not None
        return bool(row.is_read), row.read_at


def _unread_count(app, user_id: int) -> int:
    from app.extensions import db
    from app.models.communication_models import Notification

    with app.app_context():
        return db.session.query(Notification).filter_by(user_id=user_id, is_read=False).count()


# --- DB-INTEGRATION: bulk state transition ---


def test_mark_all_read_flips_all_unread_notifications_for_user(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90500", email="w2.dispatch.all@bys360.test")
    ids = [_create_notification(app, user_id) for _ in range(3)]

    response = client.post("/api/mobile/notifications/read-all", headers=headers)

    assert response.status_code == 200
    for notification_id in ids:
        is_read, _ = _notification_state(app, notification_id)
        assert is_read is True
    assert _unread_count(app, user_id) == 0


def test_mark_all_read_returns_correct_updated_count(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90501", email="w2.dispatch.count@bys360.test")
    for _ in range(4):
        _create_notification(app, user_id)

    response = client.post("/api/mobile/notifications/read-all", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["updated"] == 4


def test_mark_all_read_sets_read_at_timestamp_for_each_updated_row(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90502", email="w2.dispatch.readat@bys360.test")
    notification_id = _create_notification(app, user_id)

    client.post("/api/mobile/notifications/read-all", headers=headers)

    _, read_at = _notification_state(app, notification_id)
    assert read_at is not None


def test_mark_all_read_leaves_already_read_notifications_untouched(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90503", email="w2.dispatch.mixed@bys360.test")
    already_read_id = _create_notification(app, user_id, is_read=True)
    unread_id = _create_notification(app, user_id, is_read=False)

    response = client.post("/api/mobile/notifications/read-all", headers=headers)

    assert response.status_code == 200
    # Route filters WHERE is_read=False, so the already-read row is not part
    # of the updated set (real contract: updated count reflects only the
    # rows that were actually unread before the call).
    assert response.get_json()["updated"] == 1
    is_read_after, _ = _notification_state(app, unread_id)
    assert is_read_after is True
    is_read_already, _ = _notification_state(app, already_read_id)
    assert is_read_already is True


def test_mark_all_read_with_no_unread_notifications_returns_zero_updated(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90504", email="w2.dispatch.zero@bys360.test")

    response = client.post("/api/mobile/notifications/read-all", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["updated"] == 0


# --- IDEMPOTENCY ---


def test_mark_all_read_second_call_is_idempotent_and_updates_zero(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90505", email="w2.dispatch.idempotent@bys360.test")
    _create_notification(app, user_id)
    _create_notification(app, user_id)

    first = client.post("/api/mobile/notifications/read-all", headers=headers)
    second = client.post("/api/mobile/notifications/read-all", headers=headers)

    assert first.status_code == 200
    assert first.get_json()["updated"] == 2
    # IDEMPOTENT: repeat call is safe and reports zero further changes.
    assert second.status_code == 200
    assert second.get_json()["updated"] == 0
    assert _unread_count(app, user_id) == 0


# --- AUTHZ-NEGATIVE: ownership isolation ---


def test_mark_all_read_does_not_affect_other_users_notifications(app, client):
    owner_id, _owner_headers = _create_user_and_token(app, client, sicil_no="90506", email="w2.dispatch.owner@bys360.test")
    _, intruder_headers = _create_user_and_token(app, client, sicil_no="90507", email="w2.dispatch.intruder@bys360.test")
    owner_notification_id = _create_notification(app, owner_id)

    response = client.post("/api/mobile/notifications/read-all", headers=intruder_headers)

    assert response.status_code == 200
    assert response.get_json()["updated"] == 0
    is_read, _ = _notification_state(app, owner_notification_id)
    assert is_read is False


def test_mark_all_read_without_auth_returns_401(app, client):
    response = client.post("/api/mobile/notifications/read-all")

    assert response.status_code == 401


# --- SERVICE-INTEGRATION: real rollback path ---


def test_mark_all_read_commit_failure_rolls_back_all_remain_unread(app, client, monkeypatch):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90508", email="w2.dispatch.rollback@bys360.test")
    ids = [_create_notification(app, user_id) for _ in range(2)]

    import app.api.mobile.domains.notifications as notifications_module

    def _raise_on_commit():
        raise RuntimeError("simulated commit failure for read-all rollback test")

    monkeypatch.setattr(notifications_module.db.session, "commit", _raise_on_commit)

    response = client.post("/api/mobile/notifications/read-all", headers=headers)

    assert response.status_code == 500

    monkeypatch.undo()
    for notification_id in ids:
        is_read, _ = _notification_state(app, notification_id)
        assert is_read is False


# --- isolation from a stale process-global Config database URI ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported. If an earlier test imported it while DATABASE_URL pointed at
# its own SQLite file, setting DATABASE_URL here came too late: this module's
# apps silently used that file and collided on users.email when run again in
# the same process.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "notification_dispatch_stale_config"


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
