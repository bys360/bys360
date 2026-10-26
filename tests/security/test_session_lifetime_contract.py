"""Session lifetime contract: PERMANENT_SESSION_LIFETIME_MINUTES really bounds the session cookie.

Before: ``configure_application_defaults`` used ``setdefault("PERMANENT_SESSION_LIFETIME", ...)``,
but Flask already defines that key (31 days), so PERMANENT_SESSION_LIFETIME_MINUTES (config.py,
default 30) never applied. Flask checks the signature age of the session cookie against that
lifetime -- also for the non-permanent sessions web login creates -- so a copied or stale session
cookie stayed valid for 31 days.

Now (approved policy, 2026-10-26):
- the lifetime is PERMANENT_SESSION_LIFETIME_MINUTES (default 30); a config object that defines
  PERMANENT_SESSION_LIFETIME itself keeps it; 0 or a negative value stops the app at startup;
- 30 minutes of real user inactivity: the session records the time of the last real user
  activity (a user-activated page navigation or form submission -- not any GET and not any write)
  and is cleared
  30 minutes after it, even if its cookie was re-signed meanwhile; background requests (the 30 s
  notification poll, page-load data, CSRF refresh, dashboard panels, script reloads) never extend
  it; the activity stamp also re-signs the cookie (at most once a minute);
- pages worked without navigation report activity through ``POST /session/activity`` (login, CSRF,
  at most one write a minute), rate limited per verified user (the user id in the signed session)
  with a separate per-address abuse ceiling, so staff behind one NAT do not block each other;
  X-Forwarded-For is never a key;
- web login keeps ``session.permanent = False`` (no Expires on the cookie), remember-me stays off,
  mobile token lifetimes are unchanged.

Time is controlled through itsdangerous' signature timestamp and the refresh hook's clock; no test
waits. Expiry is checked on the session content itself, not only on a redirect.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from itsdangerous.timed import TimestampSigner

from app.bootstrap import factory_bootstrap
from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import (
    PASSWORD,
    SICIL,
    _make_app,
    _web,
)
from tests.sqlite_test_cleanup import release_sqlite_app

env = _r05.env  # real create_app() on a temporary SQLite file, seeded accounts

ROOT = Path(__file__).resolve().parents[2]
MINUTE = 60

# What a browser sends when the user clicks a link, types the URL or submits a form.
USER_NAVIGATION = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Sec-Fetch-User": "?1",
                   "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
# A fetch()/XHR started by page script (polling, page-load data).
SCRIPT_FETCH = {"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest"}
# A reload or form.submit() started by script (no user activation): a navigation without Sec-Fetch-User.
SCRIPT_RELOAD = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Accept": "text/html"}
# fetch() POST from page script; the same headers whether a click handler or a timer sent it.
SCRIPT_WRITE = {"Sec-Fetch-Mode": "same-origin", "Sec-Fetch-Dest": "empty", "Accept": "*/*"}


@pytest.fixture
def csrf_on(env):
    """Call after logging in (the test login posts without a CSRF token); reset at teardown."""
    def enable():
        env.app.config["WTF_CSRF_ENABLED"] = True

    yield enable
    env.app.config["WTF_CSRF_ENABLED"] = False


@pytest.fixture
def clock(monkeypatch):
    """Shift itsdangerous signing/validation time and the refresh hook's clock together."""
    offset = {"seconds": 0}
    real = time.time

    def now() -> int:
        return int(real()) + offset["seconds"]

    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: now())
    monkeypatch.setattr(factory_bootstrap, "_epoch_seconds", now)

    def advance(minutes: float) -> None:
        offset["seconds"] += int(minutes * MINUTE)

    return advance


def _session_user(client) -> object:
    """The user id the app sees in this client's session cookie (None if the cookie is refused)."""
    with client.session_transaction() as sess:
        return sess.get("_user_id")


def _session_cookie_headers(response) -> list[str]:
    return [h for h in response.headers.getlist("Set-Cookie") if h.startswith("session=")]


def _fresh_app(monkeypatch, request):
    db_file = Path(tempfile.gettempdir()) / "bys360" / "session_lifetime" / f"s_{uuid.uuid4().hex}.sqlite3"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    request.addfinalizer(lambda: release_sqlite_app(app))
    return app


# --------------------------------------------------------------------------- configured lifetime


def test_default_lifetime_is_30_minutes(env):
    assert env.app.permanent_session_lifetime == timedelta(minutes=30)
    assert env.app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(minutes=30)


def test_configured_minutes_are_applied(monkeypatch, request):
    from config import Config

    monkeypatch.setattr(Config, "PERMANENT_SESSION_LIFETIME_MINUTES", 45)
    assert _fresh_app(monkeypatch, request).permanent_session_lifetime == timedelta(minutes=45)


def test_environment_variable_reaches_the_config_class():
    """Config reads the variable when config.py is imported; check it in a separate interpreter."""
    code = "import config; print(config.Config.PERMANENT_SESSION_LIFETIME_MINUTES)"
    child_env = {**os.environ, "PERMANENT_SESSION_LIFETIME_MINUTES": "45"}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=child_env, capture_output=True, text=True,
                            timeout=120, check=True)
    assert result.stdout.strip().splitlines()[-1] == "45"


def test_explicit_lifetime_in_the_config_object_is_kept(monkeypatch, request):
    from config import Config

    monkeypatch.setattr(Config, "PERMANENT_SESSION_LIFETIME", timedelta(hours=2), raising=False)
    assert _fresh_app(monkeypatch, request).permanent_session_lifetime == timedelta(hours=2)


@pytest.mark.parametrize("minutes", [0, -5, True, "30"])
def test_invalid_minutes_stop_the_app_at_startup(monkeypatch, request, minutes):
    from config import Config

    monkeypatch.setattr(Config, "PERMANENT_SESSION_LIFETIME_MINUTES", minutes)
    with pytest.raises(ValueError, match="PERMANENT_SESSION_LIFETIME_MINUTES"):
        _fresh_app(monkeypatch, request)


# --------------------------------------------------------------------------- signed cookie age


def test_an_unexpired_session_cookie_is_accepted(env, clock):
    client = _web(env, "plain")
    user_id = _session_user(client)
    assert user_id is not None
    clock(29)
    assert _session_user(client) == user_id
    assert client.get("/account", headers=USER_NAVIGATION).status_code == 200


def test_an_expired_session_cookie_is_refused(env, clock):
    client = _web(env, "plain")
    assert _session_user(client) is not None
    clock(31)
    assert _session_user(client) is None  # the app cannot read the cookie any more
    response = client.get("/account")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_real_user_activity_keeps_the_session_alive_and_inactivity_ends_it(env, clock):
    client = _web(env, "plain")
    user_id = _session_user(client)
    clock(20)
    first = client.get("/account", headers=USER_NAVIGATION)
    assert first.status_code == 200 and _session_cookie_headers(first)  # activity recorded, re-signed
    again = client.get("/account", headers=USER_NAVIGATION)
    assert not _session_cookie_headers(again)  # at most once a minute
    clock(25)  # 45 minutes after login, 25 after the last activity
    assert _session_user(client) == user_id
    assert client.get("/account", headers=USER_NAVIGATION).status_code == 200
    clock(31)  # 31 minutes without activity
    assert _session_user(client) is None


def test_a_user_submitted_form_counts_as_activity(env, clock):
    client = _web(env, "plain")
    user_id = _session_user(client)
    clock(20)
    assert client.post("/notifications/mark-all-read", headers=USER_NAVIGATION).status_code in {200, 302}
    clock(25)  # 45 minutes after login, 25 after the action
    assert client.get("/account", headers=USER_NAVIGATION).status_code == 200
    assert _session_user(client) == user_id


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/notifications/unread-count", SCRIPT_FETCH),  # the 30-second poll in base.html
        ("/pwa/csrf-refresh", SCRIPT_FETCH),
        ("/ai-agent/api/assistant-widget-summary", SCRIPT_FETCH),
        ("/dashboard/heavy-panels", SCRIPT_FETCH),
        ("/account", SCRIPT_FETCH),  # any page fetched by script
        ("/dashboard", SCRIPT_RELOAD),  # an automatic dashboard reload (no user activation)
        ("/notifications/unread-count", USER_NAVIGATION),  # a background endpoint never counts
        ("/account", {"X-Requested-With": "XMLHttpRequest", "Accept": "text/html"}),  # old browser XHR
        ("/account", {"Accept": "application/json"}),  # old browser, not a page request
        ("/account", {"Accept": "text/html"}),  # old browser page load: a script reload looks the same
    ],
    ids=["unread-count-poll", "csrf-refresh", "widget-summary", "dashboard-heavy-panels", "page-by-fetch",
         "dashboard-auto-reload", "background-endpoint-navigated", "old-browser-xhr", "old-browser-json",
         "old-browser-page-load"],
)
def test_background_requests_do_not_extend_the_session(env, clock, path, headers):
    client = _web(env, "plain")
    assert _session_user(client) is not None
    for _ in range(6):  # a background request every 5 minutes for 30 minutes
        clock(5)
        client.get(path, headers=headers)
    clock(1)  # 31 minutes after the last real activity (the login)
    assert _session_user(client) is None
    response = client.get("/account", headers=USER_NAVIGATION)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize(
    ("method", "path", "headers"),
    [
        ("POST", "/notifications/mark-all-read", SCRIPT_WRITE),  # fetch() write (auto-save / handler alike)
        ("POST", "/messages/thread/1/typing", SCRIPT_WRITE),  # typing indicator
        ("POST", "/notifications/mark-all-read", {**SCRIPT_WRITE, "X-Requested-With": "XMLHttpRequest"}),
        ("POST", "/notifications/mark-all-read", SCRIPT_RELOAD),  # form.submit() from a timer, no activation
        ("POST", "/notifications/mark-all-read", {"X-Requested-With": "XMLHttpRequest", "Accept": "text/html"}),
        ("POST", "/notifications/mark-all-read", {"Accept": "application/json"}),  # old browser script write
        ("POST", "/file-center/chunk-upload/session/1/chunk/0", SCRIPT_WRITE),  # chunk loop after the user's start
        ("PUT", "/notifications/mark-all-read", SCRIPT_WRITE),
        ("DELETE", "/notifications/mark-all-read", SCRIPT_WRITE),
        ("POST", "/notifications/mark-all-read", {"Accept": "text/html,*/*;q=0.8"}),  # old-browser form.submit()
    ],
    ids=["fetch-post", "typing-indicator", "xhr-post", "timer-form-submit", "old-browser-xhr-post",
         "old-browser-json-post", "chunk-upload-loop", "fetch-put", "fetch-delete", "old-browser-form-post"],
)
def test_automatic_writes_do_not_extend_the_session(env, clock, method, path, headers):
    client = _web(env, "plain")
    assert _session_user(client) is not None
    for _ in range(6):  # an automatic write every 5 minutes for 30 minutes
        clock(5)
        client.open(path, method=method, headers=headers)
    clock(1)  # 31 minutes after the last real activity (the login)
    response = client.get("/account", headers=USER_NAVIGATION)
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert _session_user(client) is None


def test_a_freshly_signed_cookie_does_not_outlive_the_last_real_activity(env, clock):
    """Something writing to the session re-signs the cookie; the recorded activity still decides."""
    client = _web(env, "plain")
    clock(29)
    with client.session_transaction() as sess:
        sess["unrelated"] = "x"  # re-signs the cookie now, the activity stamp stays at login
    clock(2)  # cookie signed 2 minutes ago, last real activity 31 minutes ago
    response = client.get("/account", headers=USER_NAVIGATION)
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert _session_user(client) is None


def test_web_login_stays_a_browser_session_and_sets_no_remember_cookie(env, clock):
    client = env.app.test_client()
    login = client.post("/login", data={"sicil_or_email": SICIL["plain"], "password": PASSWORD})
    assert login.status_code == 302 and "/login" not in login.headers["Location"]
    cookies = login.headers.getlist("Set-Cookie")
    session_cookie = [c for c in cookies if c.startswith("session=")]
    assert session_cookie and "expires" not in session_cookie[0].lower() and "max-age" not in session_cookie[0].lower()
    assert not [c for c in cookies if c.startswith((env.app.config.get("REMEMBER_COOKIE_NAME") or "remember_token") + "=")]
    clock(2)
    refreshed = _session_cookie_headers(client.get("/account", headers=USER_NAVIGATION))
    assert refreshed and "expires" not in refreshed[0].lower()  # the refresh keeps it non-permanent
    with client.session_transaction() as sess:
        assert not sess.permanent


def test_remember_me_settings_are_untouched(env):
    from config import Config

    for key in ("REMEMBER_COOKIE_DURATION", "REMEMBER_COOKIE_SECURE", "REMEMBER_COOKIE_HTTPONLY"):
        assert env.app.config.get(key) == getattr(Config, key, None), key


def test_logout_still_ends_the_session(env):
    client = _web(env, "plain")
    assert _session_user(client) is not None
    response = client.get("/logout")
    assert response.status_code == 302
    assert _session_user(client) is None
    protected = client.get("/account")
    assert protected.status_code == 302 and "/login" in protected.headers["Location"]


def test_anonymous_requests_get_no_activity_stamp(env):
    client = env.app.test_client()
    response = client.get("/login")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert factory_bootstrap.SESSION_ACTIVITY_KEY not in sess


def test_mobile_token_lifetimes_are_unaffected(env, clock):
    from app.api.mobile import shared

    assert shared._MOBILE_ACCESS_MAX_AGE_SECONDS == 24 * 60 * 60
    assert shared._MOBILE_REFRESH_MAX_AGE_SECONDS == 30 * 24 * 60 * 60
    client = env.app.test_client()
    login = client.post("/api/mobile/auth/login", json={"username": SICIL["plain"], "password": PASSWORD})
    assert login.status_code == 200, login.get_data(as_text=True)[:200]
    token = login.get_json()["access_token"]
    clock(120)  # two hours: far past the web session lifetime, inside the 24 h access token
    assert client.get("/api/mobile/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


# --------------------------------------------------------------------------- activity endpoint (AJAX work)

ACTIVITY_URL = "/session/activity"


def _csrf_token(client) -> str:
    page = client.get("/account", headers=USER_NAVIGATION).get_data(as_text=True)
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    assert match, "csrf meta tag missing"
    return match.group(1)


def _notify(client, token: str | None, **headers):
    sent = {**SCRIPT_WRITE, **headers}
    if token is not None:
        sent["X-CSRFToken"] = token
    return client.post(ACTIVITY_URL, headers=sent)


def test_activity_endpoint_keeps_ajax_work_alive(env, clock, csrf_on):
    """Typing in the assistant or messages sends no navigation; the page's activity notice does."""
    client = _web(env, "plain")
    user_id = _session_user(client)
    csrf_on()
    token = _csrf_token(client)
    for _ in range(4):  # 40 minutes of AJAX work, one notice every 10 minutes
        clock(10)
        assert _notify(client, token).status_code == 204
    clock(25)  # 25 minutes after the last notice
    assert client.get("/account", headers=USER_NAVIGATION).status_code == 200
    assert _session_user(client) == user_id
    clock(31)
    assert _session_user(client) is None or client.get("/account").status_code == 302


def test_activity_endpoint_without_csrf_token_does_not_extend(env, clock, csrf_on):
    client = _web(env, "plain")
    csrf_on()
    for _ in range(6):
        clock(5)
        assert _notify(client, None).status_code in {302, 400}  # CSRF refusal (the app redirects or 400s)
        assert _notify(client, "forged-token").status_code in {302, 400}
    clock(1)
    response = client.get("/account", headers=USER_NAVIGATION)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_activity_endpoint_needs_a_login_and_a_post(env):
    client = env.app.test_client()
    anonymous = _notify(client, None)
    assert anonymous.status_code in {302, 401} and anonymous.status_code != 204
    assert client.get(ACTIVITY_URL).status_code == 405
    with client.session_transaction() as sess:
        assert factory_bootstrap.SESSION_ACTIVITY_KEY not in sess


def _seen(client) -> object:
    with client.session_transaction() as sess:
        return sess.get(factory_bootstrap.SESSION_ACTIVITY_KEY)


def test_activity_route_accepts_only_post(env, clock):
    rules = [rule for rule in env.app.url_map.iter_rules() if rule.rule == ACTIVITY_URL]
    assert [(rule.endpoint, sorted(set(rule.methods or ()) - {"OPTIONS"})) for rule in rules] == [
        ("session_activity", ["POST"])]
    client = _web(env, "plain")
    seen = _seen(client)
    clock(5)
    for method in ("GET", "HEAD", "PUT", "PATCH", "DELETE"):
        assert client.open(ACTIVITY_URL, method=method, headers=SCRIPT_WRITE).status_code == 405, method
    options = client.open(ACTIVITY_URL, method="OPTIONS", headers=SCRIPT_WRITE)
    assert set(options.headers["Allow"].split(", ")) == {"POST", "OPTIONS"}
    assert _seen(client) == seen  # none of them recorded activity
    assert _notify(client, None).status_code == 204 and _seen(client) != seen


def test_activity_endpoint_cannot_revive_an_expired_session(env, clock):
    client = _web(env, "plain")
    clock(31)  # the signed cookie is too old
    response = _notify(client, None)
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert _session_user(client) is None


def test_activity_endpoint_cannot_revive_an_idle_session_with_a_fresh_cookie(env, clock):
    client = _web(env, "plain")
    clock(20)
    with client.session_transaction() as sess:
        sess["_bys360_unrelated"] = 1  # re-signs the cookie; the last activity stays 20 minutes old
    clock(11)
    response = _notify(client, None)
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert _session_user(client) is None


@pytest.mark.parametrize("rotate_stamp", [True, False], ids=["admin-deactivation", "inactive-flag-only"])
def test_activity_endpoint_refuses_a_deactivated_account(env, rotate_stamp):
    """Admin deactivation and password resets rotate the security stamp (account_change_guard); an
    inactive account is refused even when only the flag changed."""
    from app.extensions import db
    from app.models import User

    client = _web(env, "plain")
    with env.app.app_context():
        user = db.session.get(User, env.ids["plain"])
        assert user is not None
        user.is_active = False
        if rotate_stamp:
            user.rotate_security_stamp()
        db.session.commit()
    response = _notify(client, None)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_activity_endpoint_refuses_another_sessions_csrf_token(env, csrf_on):
    alice, bob = _web(env, "plain"), _web(env, "plain2")
    csrf_on()
    bob_token = _csrf_token(bob)
    assert _notify(alice, bob_token).status_code in {302, 400}
    assert _notify(alice, _csrf_token(alice)).status_code == 204


def test_activity_endpoint_grants_nothing_beyond_the_callers_own_session(env, clock):
    """Any logged-in role may call it; it only refreshes the caller's own session."""
    alice, bob = _web(env, "plain"), _web(env, "plain2")
    bob_seen = _seen(bob)
    clock(5)
    for who in ("plain", "admin", "sysadm", "koordinator"):
        assert _notify(_web(env, who), None).status_code == 204, who
    assert _notify(alice, None).status_code == 204
    assert _seen(bob) == bob_seen
    assert alice.get("/admin/users", headers=USER_NAVIGATION).status_code != 200  # still no admin access


def test_activity_endpoint_does_not_accept_a_mobile_bearer_token(env):
    client = env.app.test_client()
    login = client.post("/api/mobile/auth/login", json={"username": SICIL["plain"], "password": PASSWORD})
    token = login.get_json()["access_token"]
    response = client.post(ACTIVITY_URL, headers={**SCRIPT_WRITE, "Authorization": f"Bearer {token}"})
    assert response.status_code in {302, 401}


def test_activity_endpoint_keeps_the_request_body_limits(env, clock, csrf_on):
    """PR #110: the activity endpoint is an ordinary non-upload endpoint. With CSRF on (as in
    production) an oversized body is refused with 413 before it is read and records nothing."""
    from app.core.form_body_limit import body_limit_for, configured_limit

    config = env.app.config
    assert body_limit_for("session_activity", authenticated=True, is_json=False, config=config) == \
        configured_limit(config, "MAX_CONTENT_LENGTH")
    assert body_limit_for("session_activity", authenticated=False, is_json=False, config=config) == \
        configured_limit(config, "ANONYMOUS_MAX_CONTENT_LENGTH")
    assert body_limit_for("session_activity", authenticated=True, is_json=True, config=config) == \
        configured_limit(config, "JSON_MAX_CONTENT_LENGTH")
    client = _web(env, "plain")
    csrf_on()
    token = _csrf_token(client)
    seen = _seen(client)
    clock(5)
    over_form = configured_limit(config, "MAX_CONTENT_LENGTH") + 1
    over_json = configured_limit(config, "JSON_MAX_CONTENT_LENGTH") + 1
    for body, content_type in ((b"a=" + b"x" * over_form, "application/x-www-form-urlencoded"),
                               (b"x" * over_json, "application/json")):
        response = client.post(ACTIVITY_URL, data=body, content_type=content_type,
                               headers={**SCRIPT_WRITE, "X-CSRFToken": token})
        assert response.status_code == 413, content_type
        assert _seen(client) == seen
    anonymous = env.app.test_client()
    too_big = anonymous.post(ACTIVITY_URL, data=b"a=" + b"x" * (configured_limit(config, "ANONYMOUS_MAX_CONTENT_LENGTH") + 1),
                             content_type="application/x-www-form-urlencoded", headers=SCRIPT_WRITE)
    assert too_big.status_code == 413
    assert _notify(client, token).status_code == 204 and _seen(client) != seen


def test_activity_endpoint_writes_at_most_once_a_minute(env, clock):
    client = _web(env, "plain")
    clock(5)
    first = _notify(client, None)
    assert first.status_code == 204 and _session_cookie_headers(first)
    clock(0.5)
    again = _notify(client, None)
    assert again.status_code == 204 and not _session_cookie_headers(again)


# --------------------------------------------------------------------------- activity endpoint rate limits

# Staff behind one NAT or corporate proxy reach the app from one address.
OFFICE_ADDRESS = {"REMOTE_ADDR": "203.0.113.7"}


def _office_users(env, count: int) -> list[str]:
    """Create ``count`` extra active users and return their sicil numbers."""
    from app.extensions import db
    from app.models import User

    sicils = [f"NAT{index:03d}X" for index in range(1, count + 1)]
    with env.app.app_context():
        for sicil in sicils:
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Kisi", soyad=sicil,
                        unvan="Uzman", role="personel", birim="R05 Birim", ust_birim="R05 Ust Birim",
                        is_active=True, must_change_password=False, must_set_security_question=False,
                        is_first_login=False)
            user.password_hash = _r05._password_hash()
            db.session.add(user)
        db.session.commit()
    return sicils


def _office_login(env, sicil: str):
    client = env.app.test_client()
    client.environ_base.update(OFFICE_ADDRESS)
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers["Location"], sicil
    return client


def _assert_rate_limited(response) -> None:
    assert response.status_code == 429
    assert response.get_json()["ok"] is False
    assert response.headers.get("Retry-After")


def test_activity_endpoint_limits_each_user_not_the_shared_office_address(env):
    """25 staff behind one address each use their full per-user allowance; none is refused."""
    clients = [_office_login(env, sicil) for sicil in _office_users(env, 25)]
    for _ in range(6):  # six calls a minute per user (the per-user limit), 150 from one address
        assert [_notify(client, None).status_code for client in clients] == [204] * len(clients)


def test_one_user_over_the_limit_is_refused_without_blocking_colleagues(env, clock):
    sicils = _office_users(env, 21)
    noisy, colleagues = _office_login(env, sicils[0]), [_office_login(env, sicil) for sicil in sicils[1:]]
    assert [_notify(noisy, None).status_code for _ in range(6)] == [204] * 6
    for _ in range(3):
        _assert_rate_limited(_notify(noisy, None))
    assert [_notify(client, None).status_code for client in colleagues] == [204] * len(colleagues)
    # A forged X-Forwarded-For does not move the user into a fresh bucket.
    _assert_rate_limited(_notify(noisy, None, **{"X-Forwarded-For": "198.51.100.23"}))
    # The refused calls did not refresh the session: 31 minutes after the last accepted call it ends.
    with noisy.session_transaction() as sess:
        seen = sess[factory_bootstrap.SESSION_ACTIVITY_KEY]
    clock(31)
    with noisy.session_transaction() as sess:
        assert sess.get(factory_bootstrap.SESSION_ACTIVITY_KEY) in {None, seen}
    response = noisy.get("/account", headers=USER_NAVIGATION)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_anonymous_calls_are_limited_per_address_and_ignore_x_forwarded_for(env):
    client = env.app.test_client()
    client.environ_base.update(OFFICE_ADDRESS)
    codes = [_notify(client, None, **{"X-Forwarded-For": f"198.51.100.{index}"}).status_code for index in range(9)]
    assert all(code in {302, 401} for code in codes[:6]), codes  # login required, never 204
    for code in codes[6:]:
        assert code == 429, codes


def test_rate_limit_key_is_the_signed_session_user_never_x_forwarded_for(env):
    from app.security.api_rate_limit import _session_activity_user_key

    spoofed = {"X-Forwarded-For": "198.51.100.23", "X-Real-IP": "198.51.100.24"}
    with env.app.test_request_context(ACTIVITY_URL, method="POST", headers=spoofed, environ_base=OFFICE_ADDRESS):
        assert _session_activity_user_key() == "session-activity:anon:203.0.113.7"
    with env.app.test_request_context(ACTIVITY_URL, method="POST", headers=spoofed, environ_base=OFFICE_ADDRESS):
        from flask import session

        session["_user_id"] = "42"
        assert _session_activity_user_key() == "session-activity:user:42"


@pytest.fixture
def small_address_ceiling(monkeypatch, request):
    """The per-address abuse ceiling, lowered to 10 a minute before the app is created."""
    monkeypatch.setenv("SESSION_ACTIVITY_IP_RATE_LIMIT", "10 per minute")
    return request.getfixturevalue("env")


def test_address_ceiling_stops_a_flood_from_one_address(small_address_ceiling):
    env = small_address_ceiling
    clients = [_office_login(env, sicil) for sicil in _office_users(env, 4)]
    codes = [_notify(client, None).status_code for _ in range(3) for client in clients]
    assert codes[:10] == [204] * 10, codes
    for code in codes[10:]:
        assert code == 429, codes
    other_office = _web(env, "plain")  # another address is not affected
    assert _notify(other_office, None).status_code == 204


def test_activity_limits_are_configured_per_user_and_per_address(monkeypatch):
    from app.security import api_rate_limit

    monkeypatch.delenv("SESSION_ACTIVITY_RATE_LIMIT", raising=False)
    monkeypatch.delenv("SESSION_ACTIVITY_IP_RATE_LIMIT", raising=False)
    assert api_rate_limit._session_activity_limit() == "6 per minute"
    assert api_rate_limit._session_activity_ip_limit() == "1200 per minute"


GUARD_SCRIPT = ROOT / "app" / "static" / "js" / "bys360_form_csrf_guard_v2_17_61.js"


def _activity_section() -> str:
    """The session-activity block of the global CSRF guard script (loaded by base.html on every page)."""
    script = GUARD_SCRIPT.read_text(encoding="utf-8")
    start = script.index("(function sessionActivity(){")
    return re.sub(r"/\*.*?\*/", "", script[start:], flags=re.S)


def test_page_script_reports_only_trusted_interaction_events():
    whole = re.sub(r"/\*.*?\*/", "", GUARD_SCRIPT.read_text(encoding="utf-8"), flags=re.S)
    assert "setInterval" not in whole and "setTimeout" not in whole and "requestAnimationFrame" not in whole
    code = _activity_section()
    assert "event.isTrusted" in code and "visibilityState" in code and "MIN_INTERVAL_MS = 60000" in code
    for event_type in ("'keydown'", "'pointerdown'", "'touchstart'", "'wheel'", "'input'"):
        assert event_type in code
    for passive_type in ("'scroll'", "'mousemove'", "'focus'", "'load'", "'visibilitychange'", "'pageshow'"):
        assert passive_type not in code
    assert "X-CSRFToken" in code and "data-session-activity-url" in code
    assert code.count("notify") == 2  # defined once, used only as the interaction listener


def test_logged_in_pages_carry_the_activity_url_and_load_the_script(env):
    client = _web(env, "plain")
    page = client.get("/account", headers=USER_NAVIGATION).get_data(as_text=True)
    assert 'data-session-activity-url="/session/activity"' in page
    assert "js/bys360_form_csrf_guard_v2_17_61.js" in page
    login_page = env.app.test_client().get("/login").get_data(as_text=True)
    assert "data-session-activity-url" not in login_page  # the script does nothing without it


# --------------------------------------------------------------------------- chunked upload after an idle timeout


def test_chunked_upload_resumes_after_an_idle_timeout(env, clock, tmp_path, monkeypatch):
    """Automatic chunk requests do not extend the session; after logging in again the upload resumes."""
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")
    monkeypatch.setitem(env.app.config, "FILE_CENTER_STORAGE_ROOT", str(tmp_path))
    client = _web(env, "admin")
    chunk = 1024 * 1024
    created = client.post("/file-center/chunk-upload/session-json", headers=SCRIPT_WRITE,
                          data={"original_filename": "buyuk.bin", "total_size_bytes": str(3 * chunk),
                                "chunk_size_bytes": str(chunk), "sha256_hash": ""})
    assert created.status_code == 200 and created.get_json()["ok"], created.get_data(as_text=True)[:300]
    upload_id = created.get_json()["session"]["id"]

    def send(index: int):
        return client.post(f"/file-center/chunk-upload/session/{upload_id}/chunk/{index}", headers=SCRIPT_WRITE,
                           data={"chunk": (io.BytesIO(bytes([index]) * chunk), f"buyuk.bin.part{index}")},
                           content_type="multipart/form-data")

    assert send(0).get_json()["ok"]
    clock(31)  # the upload ran on its own for 31 minutes; nobody touched the page
    refused = send(1)
    assert refused.status_code == 302 and "/login" in refused.headers["Location"]
    assert _session_user(client) is None

    client = _web(env, "admin")  # the user logs in again and resumes the same upload
    status = client.get(f"/file-center/chunk-upload/session/{upload_id}/status", headers=SCRIPT_FETCH).get_json()
    assert status["session"]["received_indexes"] == [0]
    assert send(1).get_json()["ok"] and send(2).get_json()["ok"]
    status = client.get(f"/file-center/chunk-upload/session/{upload_id}/status", headers=SCRIPT_FETCH).get_json()
    assert status["session"]["received_indexes"] == [0, 1, 2]
