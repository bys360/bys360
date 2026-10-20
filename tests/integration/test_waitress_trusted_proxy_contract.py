"""Waitress proxy trust over a real Waitress server and real HTTP connections.

Before this change run_server.py called ``serve(app, host, port, threads)``: Waitress trusted no
peer, removed X-Forwarded-For/-Proto/-Host/-Port from every request, and behind a reverse proxy
the application saw the proxy's address, ``http`` (so no HSTS) and the internal host. The Flask
test client never passes through Waitress, so only a real server shows this.

The trusted peer is 127.0.0.2 (the client binds that source address); 127.0.0.1 plays a direct,
untrusted client sending the same headers. Fake data only.
"""
from __future__ import annotations

import http.client
import json
import logging
import tempfile
import threading
import uuid
from pathlib import Path

import pytest

from app.core.waitress_proxy import WaitressProxyConfigError, waitress_proxy_settings

TRUSTED_PEER = "127.0.0.2"
UNTRUSTED_PEER = "127.0.0.1"
PUBLIC_HOST = "bys.example.test"
CLIENT_IP = "198.51.100.9"
FOUR_HEADERS = "x-forwarded-for x-forwarded-proto x-forwarded-host x-forwarded-port"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "waitress_trusted_proxy" / "dbs"


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
def test_no_setting_trusts_no_proxy() -> None:
    assert waitress_proxy_settings({}) == {"clear_untrusted_proxy_headers": True}
    assert waitress_proxy_settings({"WAITRESS_TRUSTED_PROXY": "  "}) == {"clear_untrusted_proxy_headers": True}


def test_a_valid_setting_names_one_proxy_and_only_the_listed_headers() -> None:
    settings = waitress_proxy_settings({
        "WAITRESS_TRUSTED_PROXY": " 10.0.0.5 ",
        "WAITRESS_TRUSTED_PROXY_COUNT": "2",
        "WAITRESS_TRUSTED_PROXY_HEADERS": "X-Forwarded-For, x-forwarded-proto",
    })
    assert settings == {
        "clear_untrusted_proxy_headers": True,
        "trusted_proxy": "10.0.0.5",
        "trusted_proxy_count": 2,
        "trusted_proxy_headers": "x-forwarded-for x-forwarded-proto",
    }


@pytest.mark.parametrize(
    "env",
    [
        {"WAITRESS_TRUSTED_PROXY": "*", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5,10.0.0.6", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.0/24", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for"},
        {"WAITRESS_TRUSTED_PROXY": "proxy.internal", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for"},
        {"WAITRESS_TRUSTED_PROXY": "0.0.0.0", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5", "WAITRESS_TRUSTED_PROXY_HEADERS": "forwarded"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for x-forwarded-by"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for", "WAITRESS_TRUSTED_PROXY_COUNT": "0"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for", "WAITRESS_TRUSTED_PROXY_COUNT": "-1"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for", "WAITRESS_TRUSTED_PROXY_COUNT": "11"},
        {"WAITRESS_TRUSTED_PROXY": "10.0.0.5", "WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for", "WAITRESS_TRUSTED_PROXY_COUNT": "two"},
        {"WAITRESS_TRUSTED_PROXY_COUNT": "1"},
        {"WAITRESS_TRUSTED_PROXY_HEADERS": "x-forwarded-for"},
    ],
)
def test_an_invalid_or_incomplete_setting_is_refused_not_widened(env) -> None:
    with pytest.raises(WaitressProxyConfigError):
        waitress_proxy_settings(env)


def test_run_server_passes_the_settings_to_waitress_and_stops_on_an_invalid_value() -> None:
    source = (Path(__file__).resolve().parents[2] / "run_server.py").read_text(encoding="utf-8")
    assert "**_waitress_proxy_settings()" in source
    assert "except WaitressProxyConfigError" in source and "raise SystemExit" in source


# ---------------------------------------------------------------------------
# real Waitress
# ---------------------------------------------------------------------------
@pytest.fixture
def make_app(monkeypatch):
    created = []

    def factory(trusted_proxy: str = ""):
        _DB_ROOT.mkdir(parents=True, exist_ok=True)
        db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
        uri = "sqlite:///" + db_file.as_posix()
        for key, value in {
            "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-waitress-proxy", "DATABASE_URL": uri,
            "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
            "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
            "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
            "DEFAULT_FIRST_LOGIN_PASSWORD": "waitress-proxy-test",
        }.items():
            monkeypatch.setenv(key, value)
        from app import create_app
        from config import Config

        monkeypatch.setattr(Config, "APP_ENV", "testing")
        monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
        monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
        monkeypatch.setattr(Config, "PROXY_FIX_ENABLED", True)  # the production default
        monkeypatch.setattr(Config, "WAITRESS_TRUSTED_PROXY", trusted_proxy)
        app = create_app()
        app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=uri)
        from app.extensions import db
        from app.services import runtime_schema

        with app.app_context():
            db.create_all()
            runtime_schema.provision_all()

        def seen():
            from flask import request, url_for

            return json.dumps({
                "remote_addr": request.remote_addr, "scheme": request.scheme, "host": request.host,
                "external": url_for("main.index", _external=True),
            })

        app.add_url_rule("/__proxy_probe", "proxy_probe", seen)
        created.append((app, db_file))
        return app

    yield factory
    from app.extensions import db

    for app, db_file in created:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        db_file.unlink(missing_ok=True)


@pytest.fixture
def serve():
    from waitress import create_server

    running = []

    def start(app, env: dict[str, str] | None = None) -> int:
        server = create_server(app, host="127.0.0.1", port=0, threads=2, **waitress_proxy_settings(env or {}))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        running.append((server, thread))
        return int(server.effective_port)

    yield start
    for server, thread in running:
        server.close()
        server.task_dispatcher.shutdown()
        thread.join(10)
        assert not thread.is_alive(), "the Waitress test server did not stop"


def _get(port: int, path: str, *, source: str, headers: dict[str, str] | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30, source_address=(source, 0))
    try:
        connection.request("GET", path, headers={"Connection": "close", **(headers or {})})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _probe(port: int, *, source: str, headers: dict[str, str] | None = None) -> dict:
    status, _headers, body = _get(port, "/__proxy_probe", source=source, headers=headers)
    assert status == 200, body[:300]
    return json.loads(body)


def _hsts(port: int, *, source: str, headers: dict[str, str] | None = None) -> str | None:
    return _get(port, "/login", source=source, headers=headers)[1].get("Strict-Transport-Security")


def _proxy_headers(forwarded_for: str = CLIENT_IP) -> dict[str, str]:
    return {"X-Forwarded-For": forwarded_for, "X-Forwarded-Proto": "https", "X-Forwarded-Host": PUBLIC_HOST, "X-Forwarded-Port": "443"}


def _trust(count: int = 1) -> dict[str, str]:
    return {"WAITRESS_TRUSTED_PROXY": TRUSTED_PEER, "WAITRESS_TRUSTED_PROXY_COUNT": str(count), "WAITRESS_TRUSTED_PROXY_HEADERS": FOUR_HEADERS}


def _untouched(seen: dict, port: int, peer: str) -> None:
    assert seen == {
        "remote_addr": peer, "scheme": "http", "host": f"127.0.0.1:{port}", "external": f"http://127.0.0.1:{port}/",
    }


def test_with_no_trust_forged_proxy_headers_change_nothing(make_app, serve) -> None:
    port = serve(make_app())
    for peer in (UNTRUSTED_PEER, TRUSTED_PEER):
        _untouched(_probe(port, source=peer, headers=_proxy_headers()), port, peer)
        assert _hsts(port, source=peer, headers=_proxy_headers()) is None


def test_the_trusted_proxy_sets_client_address_https_and_public_url(make_app, serve) -> None:
    port = serve(make_app(TRUSTED_PEER), _trust())
    seen = _probe(port, source=TRUSTED_PEER, headers=_proxy_headers())
    assert seen == {"remote_addr": CLIENT_IP, "scheme": "https", "host": PUBLIC_HOST, "external": f"https://{PUBLIC_HOST}/"}
    assert _hsts(port, source=TRUSTED_PEER, headers=_proxy_headers())


def test_a_direct_untrusted_connection_with_the_same_headers_is_not_believed(make_app, serve) -> None:
    port = serve(make_app(TRUSTED_PEER), _trust())
    _untouched(_probe(port, source=UNTRUSTED_PEER, headers=_proxy_headers()), port, UNTRUSTED_PEER)
    assert _hsts(port, source=UNTRUSTED_PEER, headers=_proxy_headers()) is None


def test_a_client_supplied_forwarded_for_value_cannot_replace_the_client_address(make_app, serve) -> None:
    """The proxy appends the address it saw; whatever the client put in front stays ignored."""
    port = serve(make_app(TRUSTED_PEER), _trust())
    seen = _probe(port, source=TRUSTED_PEER, headers=_proxy_headers(f"10.6.6.6, 127.0.0.1, {CLIENT_IP}"))
    assert seen["remote_addr"] == CLIENT_IP


def test_two_proxy_layers_take_the_address_the_outer_proxy_saw(make_app, serve) -> None:
    """outer proxy (sees the client) -> inner proxy 192.0.2.10 -> Waitress. ProxyFix must not read
    X-Forwarded-For again: with PROXY_FIX_X_FOR=1 it would replace the client with 192.0.2.10."""
    port = serve(make_app(TRUSTED_PEER), _trust(count=2))
    seen = _probe(port, source=TRUSTED_PEER, headers=_proxy_headers(f"10.6.6.6, {CLIENT_IP}, 192.0.2.10"))
    assert seen["remote_addr"] == CLIENT_IP
    assert seen["scheme"] == "https" and seen["host"] == PUBLIC_HOST


def test_the_guest_token_reaches_neither_application_nor_waitress_logs(make_app, serve, caplog, capfd) -> None:
    token = "SAHTEbelirtec" + uuid.uuid4().hex
    port = serve(make_app(TRUSTED_PEER), _trust())
    caplog.set_level(logging.DEBUG)
    referer = {"Referer": f"https://{PUBLIC_HOST}/guest/files/{token}?x=1"}
    for path in (f"/guest/files/{token}", f"/guest/upload/{token}"):
        status, _headers, body = _get(port, path, source=TRUSTED_PEER, headers={**_proxy_headers(), **referer})
        assert status < 500 and token.encode() not in body
    _get(port, "/login", source=UNTRUSTED_PEER, headers=referer)
    logged = "\n".join(f"{r.name} {r.getMessage()} {r.__dict__}" for r in caplog.records)
    captured = capfd.readouterr()
    assert token not in logged
    assert token not in captured.out + captured.err
