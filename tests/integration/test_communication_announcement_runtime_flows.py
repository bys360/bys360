"""BYS360 Test Integration Expansion Wave 2 -- announcement popup runtime flows.

Real Flask ``test_client()`` with a real session-cookie login (``POST
/login``) against the real
``app/communication/announcement_popup_routes.py`` runtime endpoints
(``/announcements/popup/runtime/pending``, ``/<id>/acknowledge``,
``/<id>/dismiss``), a real in-memory SQLite DB, and real
``Announcement``/``AnnouncementRead`` ORM rows.

These three routes are ``@login_required`` only (no ``menu_key_required``
role/menu-matrix gate), which is what makes them reachable end-to-end from a
plain authenticated test user without seeding role/menu visibility data.
Acknowledge/dismiss are also ``@csrf.exempt`` and instead gated by a
session-bound HMAC "runtime token" minted by the pending-check GET -- these
tests exercise that real token contract rather than assuming it away.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text


def _make_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-announcement-runtime-flows")
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


def _create_user(app, *, sicil_no, email, password="CommunicationTestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave2",
            soyad="Communication",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, *, sicil_no, password="CommunicationTestKey1!"):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return response


def _create_announcement(app, *, is_required=False, is_active=True, target_scope="all", target_role=None):
    from app.extensions import db
    from app.models.announcement_popup_models import Announcement

    with app.app_context():
        announcement = Announcement(
            title="Wave2 duyuru",
            body="Test integration expansion wave 2 announcement",
            announcement_type="info",
            is_active=is_active,
            is_required=is_required,
            show_rule="once",
            target_scope=target_scope,
            target_role=target_role,
        )
        db.session.add(announcement)
        db.session.commit()
        return announcement.id


def _get_runtime_token(client) -> str:
    response = client.get("/announcements/popup/runtime/pending")
    assert response.status_code == 200
    return response.get_json()["runtime_token"]


def _read_record(app, announcement_id: int, user_id: int):
    from app.extensions import db
    from app.models.announcement_popup_models import AnnouncementRead

    with app.app_context():
        return (
            db.session.query(AnnouncementRead)
            .filter_by(announcement_id=announcement_id, user_id=user_id)
            .first()
        )


def _read_record_count(app) -> int:
    from app.extensions import db
    from app.models.announcement_popup_models import AnnouncementRead

    with app.app_context():
        return db.session.query(AnnouncementRead).count()


# --- DB-INTEGRATION: pending-check records a real "seen" row ---


def test_runtime_pending_returns_active_announcement_and_records_seen(app, client):
    user_id = _create_user(app, sicil_no="90600", email="w2.announce.pending@bys360.test")
    announcement_id = _create_announcement(app)
    _login(client, sicil_no="90600")

    response = client.get("/announcements/popup/runtime/pending")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["has_pending"] is True
    assert payload["announcement"]["id"] == announcement_id

    record = _read_record(app, announcement_id, user_id)
    assert record is not None
    assert record.seen_count == 1
    assert record.first_seen_at is not None


def test_runtime_pending_with_no_active_announcements_returns_has_pending_false(app, client):
    _create_user(app, sicil_no="90601", email="w2.announce.none@bys360.test")
    _login(client, sicil_no="90601")

    response = client.get("/announcements/popup/runtime/pending")

    assert response.status_code == 200
    assert response.get_json()["has_pending"] is False


def test_runtime_pending_excludes_inactive_announcement(app, client):
    _create_user(app, sicil_no="90602", email="w2.announce.inactive@bys360.test")
    _create_announcement(app, is_active=False)
    _login(client, sicil_no="90602")

    response = client.get("/announcements/popup/runtime/pending")

    assert response.get_json()["has_pending"] is False


def test_runtime_pending_excludes_announcement_outside_publish_window(app, client):
    from app.extensions import db
    from app.models.announcement_popup_models import Announcement

    _create_user(app, sicil_no="90603", email="w2.announce.window@bys360.test")
    with app.app_context():
        past_start = dt.datetime.now() - dt.timedelta(days=10)
        past_end = dt.datetime.now() - dt.timedelta(days=1)
        announcement = Announcement(
            title="Süresi geçmiş duyuru",
            body="Bu duyuru artık pasif zaman aralığında.",
            is_active=True,
            target_scope="all",
            publish_start_at=past_start,
            publish_end_at=past_end,
        )
        db.session.add(announcement)
        db.session.commit()

    _login(client, sicil_no="90603")
    response = client.get("/announcements/popup/runtime/pending")

    assert response.get_json()["has_pending"] is False


def test_runtime_pending_without_auth_redirects_to_login(app, client):
    _create_announcement(app)

    response = client.get("/announcements/popup/runtime/pending", follow_redirects=False)

    assert response.status_code in {302, 401}


# --- DB-INTEGRATION: acknowledge / dismiss upsert AnnouncementRead ---


def test_acknowledge_with_valid_runtime_token_marks_record_acknowledged(app, client):
    user_id = _create_user(app, sicil_no="90604", email="w2.announce.ack@bys360.test")
    announcement_id = _create_announcement(app)
    _login(client, sicil_no="90604")
    token = _get_runtime_token(client)

    response = client.post(
        f"/announcements/popup/{announcement_id}/acknowledge",
        data={"runtime_token": token},
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    record = _read_record(app, announcement_id, user_id)
    assert record is not None
    assert record.acknowledged_at is not None


def test_dismiss_non_required_announcement_with_valid_token_succeeds(app, client):
    user_id = _create_user(app, sicil_no="90605", email="w2.announce.dismiss@bys360.test")
    announcement_id = _create_announcement(app, is_required=False)
    _login(client, sicil_no="90605")
    token = _get_runtime_token(client)

    response = client.post(
        f"/announcements/popup/{announcement_id}/dismiss",
        data={"runtime_token": token},
    )

    assert response.status_code == 200
    record = _read_record(app, announcement_id, user_id)
    assert record is not None
    assert record.dismissed_at is not None


def test_dismiss_required_announcement_returns_400_and_does_not_dismiss(app, client):
    user_id = _create_user(app, sicil_no="90606", email="w2.announce.reqdismiss@bys360.test")
    announcement_id = _create_announcement(app, is_required=True)
    _login(client, sicil_no="90606")
    token = _get_runtime_token(client)

    response = client.post(
        f"/announcements/popup/{announcement_id}/dismiss",
        data={"runtime_token": token},
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    record = _read_record(app, announcement_id, user_id)
    assert record is None or record.dismissed_at is None


def test_acknowledge_and_dismiss_upsert_the_same_read_row_not_duplicates(app, client):
    user_id = _create_user(app, sicil_no="90607", email="w2.announce.upsert@bys360.test")
    announcement_id = _create_announcement(app, is_required=False)
    _login(client, sicil_no="90607")
    token = _get_runtime_token(client)

    client.get("/announcements/popup/runtime/pending")  # seeds first_seen via record_announcement_seen
    client.post(f"/announcements/popup/{announcement_id}/acknowledge", data={"runtime_token": token})
    client.post(f"/announcements/popup/{announcement_id}/dismiss", data={"runtime_token": token})

    from app.extensions import db
    from app.models.announcement_popup_models import AnnouncementRead

    with app.app_context():
        rows = (
            db.session.query(AnnouncementRead)
            .filter_by(announcement_id=announcement_id, user_id=user_id)
            .all()
        )
        # Unique constraint on (announcement_id, user_id) -- exactly one row,
        # updated in place across seen/acknowledge/dismiss calls.
        assert len(rows) == 1
        assert rows[0].acknowledged_at is not None
        assert rows[0].dismissed_at is not None


# --- SECURITY-NEGATIVE: runtime token contract ---


def test_acknowledge_without_runtime_token_returns_400_and_writes_no_row(app, client):
    _create_user(app, sicil_no="90608", email="w2.announce.notoken@bys360.test")
    announcement_id = _create_announcement(app)
    _login(client, sicil_no="90608")

    before = _read_record_count(app)
    response = client.post(f"/announcements/popup/{announcement_id}/acknowledge", data={})

    assert response.status_code == 400
    assert _read_record_count(app) == before


def test_acknowledge_with_wrong_runtime_token_returns_400(app, client):
    _create_user(app, sicil_no="90609", email="w2.announce.wrongtoken@bys360.test")
    announcement_id = _create_announcement(app)
    _login(client, sicil_no="90609")
    _get_runtime_token(client)

    response = client.post(
        f"/announcements/popup/{announcement_id}/acknowledge",
        data={"runtime_token": "not-the-real-session-token"},
    )

    assert response.status_code == 400


def test_acknowledge_runtime_token_is_not_reusable_across_sessions(app, client):
    """A token minted for one login session must not authorize the same
    action after that session's cookie is discarded and a fresh client
    session begins -- proves the token is genuinely session-bound, not a
    static per-announcement secret."""
    _create_user(app, sicil_no="90610", email="w2.announce.crosssession@bys360.test")
    announcement_id = _create_announcement(app)

    _login(client, sicil_no="90610")
    token = _get_runtime_token(client)
    client.get("/logout")

    _login(client, sicil_no="90610")
    response = client.post(
        f"/announcements/popup/{announcement_id}/acknowledge",
        data={"runtime_token": token},
    )

    assert response.status_code == 400


def test_acknowledge_nonexistent_announcement_returns_404(app, client):
    _create_user(app, sicil_no="90611", email="w2.announce.missing@bys360.test")
    _login(client, sicil_no="90611")
    token = _get_runtime_token(client)

    response = client.post(
        "/announcements/popup/999999/acknowledge",
        data={"runtime_token": token},
    )

    assert response.status_code == 404


def test_acknowledge_without_auth_redirects_to_login_and_writes_no_row(app, client):
    announcement_id = _create_announcement(app)

    before = _read_record_count(app)
    response = client.post(
        f"/announcements/popup/{announcement_id}/acknowledge",
        data={"runtime_token": "irrelevant"},
        follow_redirects=False,
    )

    assert response.status_code in {302, 401}
    assert _read_record_count(app) == before


# --- IDEMPOTENCY ---


def test_acknowledge_called_twice_is_idempotent_single_row(app, client):
    user_id = _create_user(app, sicil_no="90612", email="w2.announce.ackidempotent@bys360.test")
    announcement_id = _create_announcement(app)
    _login(client, sicil_no="90612")
    token = _get_runtime_token(client)

    first = client.post(f"/announcements/popup/{announcement_id}/acknowledge", data={"runtime_token": token})
    second = client.post(f"/announcements/popup/{announcement_id}/acknowledge", data={"runtime_token": token})

    assert first.status_code == 200
    # IDEMPOTENT: repeat acknowledge on an already-acknowledged record is
    # accepted and does not create a second AnnouncementRead row.
    assert second.status_code == 200

    from app.extensions import db
    from app.models.announcement_popup_models import AnnouncementRead

    with app.app_context():
        count = (
            db.session.query(AnnouncementRead)
            .filter_by(announcement_id=announcement_id, user_id=user_id)
            .count()
        )
        assert count == 1


# --- isolation from a stale process-global Config database URI ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported. If an earlier test imported it while DATABASE_URL pointed at
# its own SQLite file, setting DATABASE_URL here came too late: this module's
# apps silently used that file, saw announcements left by earlier apps and
# collided on users.email when run again.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "communication_announcement_stale_config"


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
            counts["announcements"] = db.session.execute(
                text("SELECT COUNT(*) FROM announcements")
            ).scalar()
            counts["announcement_reads"] = db.session.execute(
                text("SELECT COUNT(*) FROM announcement_reads")
            ).scalar()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        stale_path.unlink(missing_ok=True)

    assert engine_url == "sqlite:///:memory:"
    assert not on_stale_db
    assert counts == {"users": 0, "announcements": 0, "announcement_reads": 0}
