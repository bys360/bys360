"""BYS360 Test Integration Expansion Wave 2 -- mobile push token registration.

Real Flask ``test_client()`` against the real
``app/api/mobile/domains/push_notifications.py`` routes, backed by the real
(raw-SQL, no ORM model) ``mobile_push_tokens`` table in an in-memory SQLite
DB. Verifies real row creation/upsert behaviour, ownership-scoped
unregistration, truncation/validation edges, and the legacy alias route.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


def _make_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-push-token-flows")
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

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has

    return app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user_and_token(app, client, *, sicil_no, email, password="PushTokenTestSecret1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave2",
            soyad="Push",
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


def _token_row(app, token: str):
    from app.extensions import db

    with app.app_context():
        return db.session.execute(
            text("SELECT * FROM mobile_push_tokens WHERE token = :token"), {"token": token}
        ).mappings().first()


def _token_row_count(app) -> int:
    from app.extensions import db

    with app.app_context():
        try:
            return int(db.session.execute(text("SELECT COUNT(*) FROM mobile_push_tokens")).scalar() or 0)
        except Exception:
            # Table not yet created (no push route hit) -- treat as zero rows.
            return 0


# --- DB-INTEGRATION: real row creation and upsert ---


def test_register_push_token_creates_new_row_with_action_created(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90400", email="w2.push.create@bys360.test")

    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-aaa", "platform": "android"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["action"] == "created"

    row = _token_row(app, "wave2-push-test-token-aaa")
    assert row is not None
    assert bool(row["is_active"]) is True
    assert row["platform"] == "android"


def test_register_same_token_again_updates_existing_row_action_updated(app, client):
    user_id, headers = _create_user_and_token(app, client, sicil_no="90401", email="w2.push.reupdate@bys360.test")

    client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-bbb", "platform": "android", "device_label": "eski cihaz"},
        headers=headers,
    )
    second = client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-bbb", "platform": "ios", "device_label": "yeni cihaz"},
        headers=headers,
    )

    assert second.status_code == 200
    assert second.get_json()["action"] == "updated"
    assert _token_row_count(app) == 1

    row = _token_row(app, "wave2-push-test-token-bbb")
    assert row["platform"] == "ios"
    assert row["device_label"] == "yeni cihaz"
    assert row["user_id"] == user_id


def test_register_token_for_different_user_reassigns_ownership(app, client):
    """Documents actual observed behaviour: the upsert matches by token only
    (not token+user_id), so a token re-registered by a different user is
    reassigned rather than rejected. This is a real device-reinstall
    scenario, not a cross-tenant data read -- no notification content is
    exposed to the new owner, only future delivery targeting changes."""
    owner_id, owner_headers = _create_user_and_token(app, client, sicil_no="90402", email="w2.push.owner@bys360.test")
    _, other_headers = _create_user_and_token(app, client, sicil_no="90403", email="w2.push.other@bys360.test")

    client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-shared"},
        headers=owner_headers,
    )
    client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-shared"},
        headers=other_headers,
    )

    row = _token_row(app, "wave2-push-test-token-shared")
    assert row is not None
    assert row["user_id"] != owner_id
    assert _token_row_count(app) == 1


def test_register_token_without_platform_defaults_to_android(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90404", email="w2.push.noplatform@bys360.test")

    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-noplatform"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["platform"] == "android"


def test_register_token_over_length_limit_is_truncated_and_stored(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90405", email="w2.push.long@bys360.test")

    long_token = "a" * 600
    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": long_token},
        headers=headers,
    )

    assert response.status_code == 200
    row = _token_row(app, long_token[:512])
    assert row is not None
    assert len(row["token"]) == 512


# --- VALIDATION-NEGATIVE ---


def test_register_token_missing_field_returns_400_and_writes_no_row(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90406", email="w2.push.missing@bys360.test")

    response = client.post("/api/mobile/push/register-token", json={}, headers=headers)

    assert response.status_code == 400
    assert response.get_json()["error"] == "token_required"
    assert _token_row_count(app) == 0


def test_register_token_empty_string_returns_400(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90407", email="w2.push.empty@bys360.test")

    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": "   "},
        headers=headers,
    )

    assert response.status_code == 400
    assert _token_row_count(app) == 0


# --- AUTHZ-NEGATIVE ---


def test_register_token_without_auth_returns_401_and_writes_no_row(app, client):
    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-noauth"},
    )

    assert response.status_code == 401
    assert _token_row_count(app) == 0


# --- OWNERSHIP-ISOLATION: unregister is scoped to token AND user_id ---


def test_unregister_token_deactivates_own_token(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90408", email="w2.push.unreg@bys360.test")

    client.post("/api/mobile/push/register-token", json={"token": "wave2-push-test-token-unreg"}, headers=headers)
    response = client.post(
        "/api/mobile/push/unregister-token",
        json={"token": "wave2-push-test-token-unreg"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["push_enabled"] is False

    row = _token_row(app, "wave2-push-test-token-unreg")
    assert bool(row["is_active"]) is False


def test_unregister_token_owned_by_another_user_does_not_deactivate_it(app, client):
    _, owner_headers = _create_user_and_token(app, client, sicil_no="90409", email="w2.push.realowner@bys360.test")
    _, intruder_headers = _create_user_and_token(app, client, sicil_no="90410", email="w2.push.intruder@bys360.test")

    client.post("/api/mobile/push/register-token", json={"token": "wave2-push-test-token-guarded"}, headers=owner_headers)
    response = client.post(
        "/api/mobile/push/unregister-token",
        json={"token": "wave2-push-test-token-guarded"},
        headers=intruder_headers,
    )

    # Route responds 200 unconditionally (UPDATE with no matching row is a no-op),
    # but the real DB state proves ownership isolation held.
    assert response.status_code == 200
    row = _token_row(app, "wave2-push-test-token-guarded")
    assert bool(row["is_active"]) is True


def test_unregister_token_missing_field_returns_400(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90411", email="w2.push.unregmissing@bys360.test")

    response = client.post("/api/mobile/push/unregister-token", json={}, headers=headers)

    assert response.status_code == 400


# --- STATUS / READ-ONLY CONTRACT ---


def test_push_status_reports_zero_active_tokens_before_registration(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90412", email="w2.push.statuszero@bys360.test")

    response = client.get("/api/mobile/push/status", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["active_tokens"] == 0
    assert payload["push_ready"] is False


def test_push_status_reflects_active_token_after_registration_and_excludes_after_unregister(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90413", email="w2.push.statusflow@bys360.test")

    client.post("/api/mobile/push/register-token", json={"token": "wave2-push-test-token-status"}, headers=headers)
    after_register = client.get("/api/mobile/push/status", headers=headers).get_json()
    assert after_register["active_tokens"] == 1
    assert after_register["push_ready"] is True

    client.post("/api/mobile/push/unregister-token", json={"token": "wave2-push-test-token-status"}, headers=headers)
    after_unregister = client.get("/api/mobile/push/status", headers=headers).get_json()
    assert after_unregister["active_tokens"] == 0
    assert after_unregister["push_ready"] is False


# --- LEGACY ALIAS EQUIVALENCE ---


def test_legacy_fcm_token_alias_registers_token_same_as_canonical_route(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90414", email="w2.push.legacy@bys360.test")

    response = client.post(
        "/api/mobile/notifications/fcm-token",
        json={"token": "wave2-push-test-token-legacy-alias"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["action"] == "created"
    row = _token_row(app, "wave2-push-test-token-legacy-alias")
    assert row is not None


# --- BYS360 DEFECT AR: db.session.bind dialect-detection defect ---
#
# _is_sqlite() used to read db.session.bind, which this Flask-SQLAlchemy
# runtime always returns as None -- the AttributeError was swallowed and
# _is_sqlite() always returned False, so SQLite always took the PostgreSQL
# "id SERIAL PRIMARY KEY" branch. SQLite accepts SERIAL as an arbitrary
# (non-INTEGER) type-affinity token and does not apply rowid-alias /
# autoincrement behaviour to it, so every inserted row's id came back
# permanently NULL. The fix switches to db.session.get_bind() (the same
# established pattern already used by interim_notes_runtime.py::_id_sql()).


def test_register_push_token_assigns_nonnull_integer_id_on_sqlite(app, client):
    _, headers = _create_user_and_token(app, client, sicil_no="90415", email="w2.push.idnotnull@bys360.test")

    response = client.post(
        "/api/mobile/push/register-token",
        json={"token": "wave2-push-test-token-id-not-null", "platform": "android"},
        headers=headers,
    )

    assert response.status_code == 200
    row = _token_row(app, "wave2-push-test-token-id-not-null")
    assert row is not None
    # Before the fix this was always NULL on SQLite.
    assert row["id"] is not None
    assert isinstance(row["id"], int)


def test_mobile_push_tokens_table_id_column_is_sqlite_integer_autoincrement_not_serial(app):
    from app.api.mobile.domains.push_notifications import _ensure_mobile_push_token_table
    from app.extensions import db

    with app.app_context():
        _ensure_mobile_push_token_table()
        columns = db.session.execute(text("PRAGMA table_info(mobile_push_tokens)")).fetchall()

    id_column = next(col for col in columns if col[1] == "id")
    # column tuple: (cid, name, type, notnull, dflt_value, pk)
    assert id_column[2].upper() == "INTEGER", (
        f"id column type is {id_column[2]!r}, expected INTEGER (the SQLite "
        "rowid-alias/autoincrement type) -- SERIAL would mean the bug regressed"
    )
    assert id_column[5] == 1, "id column must be the PRIMARY KEY for autoincrement behaviour to apply"


def test_is_sqlite_returns_true_on_real_sqlite_app_context(app):
    from app.api.mobile.domains.push_notifications import _is_sqlite

    with app.app_context():
        # Before the fix this always returned False, even on SQLite.
        assert _is_sqlite() is True


def test_is_sqlite_returns_false_when_bind_dialect_is_postgresql(app, monkeypatch):
    from app.api.mobile.domains.push_notifications import _is_sqlite
    from app.extensions import db

    class _FakeDialect:
        name = "postgresql"

    class _FakeBind:
        dialect = _FakeDialect()

    with app.app_context():
        monkeypatch.setattr(db.session, "get_bind", lambda: _FakeBind())
        # The PostgreSQL (SERIAL) branch selection must remain unchanged: a
        # real postgresql dialect must still make _is_sqlite() return False.
        assert _is_sqlite() is False
