"""BYS360 Assistant V2 -- web CSRF contract (mandate Phase D).

Prior wave finding: the assistant chat widget's POST to `/ai-agent/api/ask`
sent no CSRF token, while the companion `/ai-agent/panel` page's own caller
to the SAME endpoint always did (reading the site-wide
`<meta name="csrf-token">` base.html already renders for every authenticated
page). Since `app/extensions.py`'s `CSRFProtect()` is registered globally
with no exemption for this blueprint/route (grep-confirmed), and this is
the established authenticated-JSON-API pattern already used elsewhere in
this app (see tests/security/test_phase13b_csrf_and_scope.py's own
`/pwa/csrf-refresh`-harvested-token pattern, reused here), this was
case B (missing, not an established exemption) -- fixed by adding the same
token-header sending to both `bys360_assistant_module.js` and
`bys360_assistant_module_memory_v30.js`.

This file proves the SERVER side of that fix with CSRF genuinely enabled
(the shared `app`/`client` fixtures run with WTF_CSRF_ENABLED=false, so a
separate, dedicated app instance is built here, matching the same pattern
already used for Phase 13B's own CSRF negative tests).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

pytestmark = pytest.mark.ci_safe

_CSRF_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "assistant_v2_csrf" / "test_dbs"
_PASSWORD = "Assist_v2_Csrf_Test_Pw_1!"


def _make_app(monkeypatch, **config_overrides):
    _CSRF_TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _CSRF_TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-assistant-v2-csrf-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "true")
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
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    app.config.update(config_overrides)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no, email=f"{sicil_no}@ktb.gov.tr", ad="Csrf", soyad="Test",
            role=role, is_active=True, must_change_password=False, must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _harvest_csrf_token(client) -> str:
    response = client.get("/pwa/csrf-refresh")
    assert response.status_code == 200
    token = response.get_json().get("csrf_token")
    assert token
    return token


def _login(client, sicil_no, password=_PASSWORD):
    token = _harvest_csrf_token(client)
    response = client.post(
        "/login", data={"sicil_or_email": sicil_no, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def test_ask_endpoint_is_csrf_protected_by_the_global_middleware(monkeypatch, request):
    """Confirms this is genuinely case B (missing, not an established
    exemption): with CSRF enabled and no token sent at all, the endpoint
    must reject the request, exactly like every other state-changing POST
    in this app."""
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="av2_csrf_missing_admin")
    client = app.test_client()
    _login(client, "av2_csrf_missing_admin")

    response = client.post(
        "/ai-agent/api/ask", json={"question": "merhaba"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body is not None
    assert body.get("code") == "csrf_refresh_required"


def test_ask_endpoint_rejects_invalid_csrf_token(monkeypatch, request):
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="av2_csrf_invalid_admin")
    client = app.test_client()
    _login(client, "av2_csrf_invalid_admin")

    response = client.post(
        "/ai-agent/api/ask", json={"question": "merhaba"},
        headers={"Accept": "application/json", "X-CSRFToken": "garbage-token-not-a-real-csrf-value"},
    )
    assert response.status_code == 400


def test_ask_endpoint_succeeds_with_valid_csrf_token(monkeypatch, request):
    """Positive control -- proves the fix (widget now sends this exact
    header, matching panel.html's own established pattern) does not
    collateral-damage a legitimate authorized request."""
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="av2_csrf_valid_admin")
    client = app.test_client()
    _login(client, "av2_csrf_valid_admin")
    token = _harvest_csrf_token(client)

    response = client.post(
        "/ai-agent/api/ask", json={"question": "merhaba"},
        headers={"Accept": "application/json", "X-CSRFToken": token},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["answer"]


def test_ask_endpoint_still_enforces_authorization_with_valid_csrf(monkeypatch, request):
    """A valid CSRF token must never substitute for real authorization --
    a denied capability must still be denied even with a technically valid
    token attached."""
    from app.route_support import can_access_menu
    from app.services.assistant_v2.capability_registry import ASSISTANT_CAPABILITY_REGISTRY

    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="av2_csrf_authz_personel", role="personel")
    client = app.test_client()
    _login(client, "av2_csrf_authz_personel")
    token = _harvest_csrf_token(client)

    with app.test_request_context():
        from app.models import User

        personel = User.query.filter_by(sicil_no="av2_csrf_authz_personel").first()
        denied_entry = next(
            (
                e for e in ASSISTANT_CAPABILITY_REGISTRY
                if e.permission_key and not e.is_self_describing and not can_access_menu(personel, e.permission_key)
            ),
            None,
        )
    assert denied_entry is not None

    response = client.post(
        "/ai-agent/api/ask", json={"question": denied_entry.intent_tags[0]},
        headers={"Accept": "application/json", "X-CSRFToken": token},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "erişim yetkisi" in body["answer"].lower() or "tam olarak anlayamadım" in body["answer"].lower()
