"""Contract: mobile v1 create-thread ignores recipient ids that are not users.

POST /api/mobile/communication/messages/create-thread
(_bys360_legacy_mobile_b46_communication_create_thread) accepted every int-parsable id and
inserted a MessageThreadParticipant for it. message_thread_participants.user_id is a foreign
key to users.id, so on a database that enforces foreign keys (PostgreSQL in production) an
unknown id made the request fail with IntegrityError (HTTP 500). Without enforcement it
created a thread with a participant row pointing at no user.

Rule reused: the v2 twin (communication_v2_write.py, _bys360_legacy_mobile_b48_..._create_thread)
keeps only ids for which db.session.get(User, id) exists; with no valid recipient left it answers
400 "Konuşma başlatmak için en az bir alıcı seçilmelidir." without writing anything.

Real Flask app, real test client and mobile bearer token, file-backed SQLite only.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event

PASSWORD = "MobileV1ThreadRecipientTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "mobile_v1_thread_unknown_recipient" / "dbs"
_CREATE_THREAD = "/api/mobile/communication/messages/create-thread"
_NO_RECIPIENT_MESSAGE = "Konuşma başlatmak için en az bir alıcı seçilmelidir."
_UNKNOWN_USER_ID = 99999


def _build_app(monkeypatch, *, enforce_foreign_keys):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-mobile-v1-thread-recipient", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "mobile-v1-thread-recipient-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    # Report errors the way a real client sees them (status code), not as raised exceptions.
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri, PROPAGATE_EXCEPTIONS=False)
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        if enforce_foreign_keys:
            # Enforce foreign keys like PostgreSQL does; drop pooled connections opened without it.
            event.listen(db.engine, "connect", lambda dbapi_conn, _record: dbapi_conn.execute("PRAGMA foreign_keys=ON"))
            db.engine.dispose()
        db.create_all()
        ids = {}
        for sicil in ("MVT01", "MVT02"):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Mobil", soyad=sicil, role="personel",
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = user.id
        db.session.commit()
        flask_app.config["_IDS"] = ids
    return flask_app


@pytest.fixture
def app(monkeypatch):
    return _build_app(monkeypatch, enforce_foreign_keys=False)


@pytest.fixture
def fk_app(monkeypatch):
    return _build_app(monkeypatch, enforce_foreign_keys=True)


def _create_thread(app, participant_ids):
    client = app.test_client()
    login = client.post("/api/mobile/auth/login", json={"username": "MVT01", "password": PASSWORD})
    assert login.status_code == 200
    token = login.get_json()["access_token"]
    return client.post(
        _CREATE_THREAD,
        json={"participant_user_ids": participant_ids, "body": "Merhaba"},
        headers={"Authorization": f"Bearer {token}"},
    )


def _thread_state(app):
    from app.models import MessageThread, MessageThreadParticipant

    with app.app_context():
        threads = MessageThread.query.count()
        participants = sorted(row.user_id for row in MessageThreadParticipant.query.all())
    return threads, participants


def test_unknown_recipient_is_400_not_500_when_foreign_keys_are_enforced(fk_app):
    response = _create_thread(fk_app, [_UNKNOWN_USER_ID])

    assert response.status_code == 400
    assert response.get_json() == {"message": _NO_RECIPIENT_MESSAGE}
    assert _thread_state(fk_app) == (0, [])


def test_unknown_recipient_creates_no_thread_or_dangling_participant(app):
    response = _create_thread(app, [_UNKNOWN_USER_ID])

    assert response.status_code == 400
    assert response.get_json() == {"message": _NO_RECIPIENT_MESSAGE}
    assert _thread_state(app) == (0, [])


def test_unknown_id_is_dropped_and_known_recipient_kept(fk_app):
    ids = fk_app.config["_IDS"]
    response = _create_thread(fk_app, [_UNKNOWN_USER_ID, ids["MVT02"]])

    assert response.status_code == 200
    assert response.get_json()["message"] == "Konuşma başlatıldı."
    assert _thread_state(fk_app) == (1, sorted([ids["MVT01"], ids["MVT02"]]))


def test_known_recipient_thread_is_unchanged(fk_app):
    ids = fk_app.config["_IDS"]
    response = _create_thread(fk_app, [ids["MVT02"]])

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Konuşma başlatıldı."
    assert isinstance(payload["thread_id"], int)
    assert _thread_state(fk_app) == (1, sorted([ids["MVT01"], ids["MVT02"]]))
