"""Runtime contract: an anonymous request is refused by every route that is not explicitly public.

tests/security/test_authorization_matrix_contract.py decides "authenticated" statically,
from decorators, known blueprint guards and the view body. That misses a guard that only
looks like one: the ai_agent blueprint's before_request lets anonymous requests through, so
a new ai_agent route without @login_required would pass the static check. This test sends
one anonymous request to every registered rule instead and compares the answers with an
explicit allowlist, so a new public route has to be listed here on purpose.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "anonymous_route_runtime" / "dbs"

# Endpoints that answer an anonymous request by design (reviewed 2026-09-28/29).
PUBLIC_ENDPOINTS = {
    "ai_agent.ai_agent_public_healthz",  # smoke check: status, service, version, mode, bridge flags only
    "health.health",
    "health.health_deep",
    "main.healthz",
    "main.readyz",
    "main.versionz",
    "mobile_api.mobile_health",
    "mobile_api.mobile_login",
    "main.login",
    "main.forgot_password",
    "main.setup_admin",  # 404 unless explicitly permitted; redirects once any user exists
    "main.kunye",
    "main.file_center_guest_download",  # token-gated guest link
    "main.file_center_guest_upload",  # token-gated guest link
    "main.bys360_pwa_manifest",
    "main.bys360_pwa_service_worker",
    "pwa.manifest_webmanifest",
    "pwa.service_worker_js",
    "pwa.pwa_offline",
    "pwa.pwa_csrf_refresh",
}
_REDIRECTS = {301, 302, 303, 307, 308}


@pytest.fixture(scope="module")
def app():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    with pytest.MonkeyPatch.context() as monkeypatch:
        for key, value in {
            "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-anonymous-route-runtime", "DATABASE_URL": uri,
            "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
            "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
            "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
            "DEFAULT_FIRST_LOGIN_PASSWORD": "anonymous-route-runtime-first-login",
        }.items():
            monkeypatch.setenv(key, value)
        from app import create_app
        from config import Config

        monkeypatch.setattr(Config, "APP_ENV", "testing")
        monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
        monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
        flask_app = create_app()
        flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
        from app.extensions import db
        from app.services import runtime_schema

        with flask_app.app_context():
            db.create_all()
            runtime_schema.provision_all()
        yield flask_app


def _url(app, rule):
    from flask import url_for

    for value in (1, "probe"):
        values: dict[str, Any] = {name: value for name in rule.arguments}
        try:
            with app.test_request_context():
                return url_for(rule.endpoint, **values)
        except Exception:  # noqa: BLE001 - try the next placeholder type
            continue
    raise AssertionError(f"cannot build a URL for {rule.endpoint} ({rule.rule})")


@pytest.fixture(scope="module")
def answers(app):
    result = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        if rule.endpoint == "static":
            continue
        methods = set(rule.methods or ()) - {"HEAD", "OPTIONS"}
        method = "GET" if "GET" in methods else sorted(methods)[0]
        response = app.test_client().open(_url(app, rule), method=method)
        result[(rule.endpoint, rule.rule, method)] = (response.status_code, response.headers.get("Location", ""))
    return result


def _refused(status, location):
    if status in (401, 403):
        return True
    return status in _REDIRECTS and location.split("?", 1)[0].rstrip("/").endswith("/login")


def test_every_non_public_route_refuses_an_anonymous_request(answers):
    open_routes = sorted(
        f"{method} {path} ({endpoint}) -> {status} {location}".strip()
        for (endpoint, path, method), (status, location) in answers.items()
        if endpoint not in PUBLIC_ENDPOINTS and not _refused(status, location)
    )
    assert open_routes == []


def test_no_route_fails_with_a_server_error_for_an_anonymous_request(answers):
    errors = sorted(f"{method} {path} ({endpoint}) -> {status}"
                    for (endpoint, path, method), (status, _) in answers.items() if status >= 500)
    assert errors == []


def test_public_allowlist_names_registered_endpoints(app):
    registered = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert sorted(PUBLIC_ENDPOINTS - registered) == []
