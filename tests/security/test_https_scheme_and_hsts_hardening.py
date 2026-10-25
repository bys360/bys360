"""BYS360 HTTPS scheme + HSTS trust-boundary hardening regression tests.

Covers three related fixes:

1. config._resolve_preferred_url_scheme() / Config.PREFERRED_URL_SCHEME --
   previously undefined anywhere in the repo, so Flask silently defaulted to
   'http' for any URL built outside an active request (background mail
   jobs, CLI). Resolution order: explicit PREFERRED_URL_SCHEME env value >
   APP_BASE_URL scheme > safe 'http' default.

2. app/bootstrap/response_hardening.py's is_secure computation -- previously
   trusted a raw, client-suppliable X-Forwarded-Proto header directly, with
   no dependency on ProxyFix's trusted-hop validation. A client could send
   that header on any request (even with ProxyFix disabled, e.g. in
   development) and force is_secure=True. The fix relies only on
   request.is_secure (which ProxyFix already corrects for trusted hops when
   enabled) and PREFERRED_URL_SCHEME (a non-spoofable, server-side signal
   derived from APP_BASE_URL).

3. config._resolve_secure_cookie() / _default_secure_cookie() (drives
   SESSION_COOKIE_SECURE and REMEMBER_COOKIE_SECURE) -- previously derived
   its https/local-host determination directly from raw APP_BASE_URL and
   never consulted the *resolved* PREFERRED_URL_SCHEME. An operator could
   set PREFERRED_URL_SCHEME=https explicitly (turning HSTS on) while
   APP_BASE_URL still pointed at a stale http URL, and the cookies would
   silently stay non-Secure. The fix makes both cookies follow the single,
   resolved PREFERRED_URL_SCHEME value when no explicit cookie env override
   is given, and adds a fail-fast RuntimeError (same style as the SECRET_KEY
   guard below) when APP_BASE_URL's own scheme and an explicit
   PREFERRED_URL_SCHEME override disagree on a production/staging,
   non-local/private host -- see
   config._preferred_url_scheme_conflicts_with_app_base_url() and the
   Config class body in config.py.

4. BYS360_SEC3B_A1_COOKIE_FAIL_FAST_V1: closes a residual gap left by fix
   #3 above -- production/staging + effective HTTPS + an EXPLICIT
   SESSION_COOKIE_SECURE=false (or REMEMBER_COOKIE_SECURE=false) was still
   being accepted as the operator's "conscious choice", only logged as a
   warning. config._resolve_secure_cookie() now raises a RuntimeError for
   exactly this combination (production/staging, effective external scheme
   HTTPS, explicit false), so config.py itself refuses to import. This is
   independent of, and does not replace,
   app.security.startup_audit.validate_live_security_defaults (which
   already hard-blocks SESSION_COOKIE_SECURE/REMEMBER_COOKIE_SECURE=False in
   production/staging regardless of scheme, but only once a real Flask app
   is created via create_app()) -- the two are defense-in-depth layers at
   different points in the boot sequence.

5. BYS360_SEC3C_A1_PRODUCTION_HTTPS_FAIL_FAST_V1: closes the residual gap
   left by fix #3/#4 -- production/staging + APP_BASE_URL=http://... (NO
   explicit PREFERRED_URL_SCHEME override, public/non-local host) previously
   resolved PREFERRED_URL_SCHEME to 'http' completely silently: neither the
   SECRET_KEY guard, nor the PREFERRED_URL_SCHEME/APP_BASE_URL conflict guard
   (fix #3, which only fires when an *explicit* override disagrees with
   APP_BASE_URL's own scheme), nor the cookie fail-fast (fix #4, which only
   fires on an *explicit* false) caught this shape, so `import config`
   succeeded with exit=0 for a plain-HTTP production deployment. A third,
   narrower guard now closes this: production/staging + resolved
   PREFERRED_URL_SCHEME != 'https' + non-local/private host always raises
   RuntimeError, regardless of whether an explicit override is present. See
   the Config class body comment tagged BYS360_SEC3C_A1_PRODUCTION_HTTPS_
   FAIL_FAST_V1 for the full relationship to the fix-#3 conflict guard (they
   intentionally overlap on some inputs -- e.g. APP_BASE_URL=https +
   PREFERRED_URL_SCHEME=http -- and the earlier, fix-#3 guard always wins in
   that case; this is harmless, both reach the same RuntimeError outcome).

6. BYS360_SEC3C_A1_TRUSTED_HOSTS_V1: config.Config.TRUSTED_HOSTS wires
   Flask 3.1's built-in app.config['TRUSTED_HOSTS'] Host-header validation
   (werkzeug.sansio.utils.get_host/host_is_trusted, applied automatically by
   Flask.create_url_adapter() on every request -- no extra route_support.py
   hook needed). config._resolve_trusted_hosts() always includes
   APP_BASE_URL's own host (the single canonical trust root, consistent with
   app/security/redirect_guard.py's design) plus any explicit, comma
   separated TRUSTED_HOSTS env entries; '*' is rejected with RuntimeError in
   production/staging; development/testing additionally get localhost/
   127.0.0.1/::1 auto-added. Enforcement (assigning a concrete, non-None list
   to Config.TRUSTED_HOSTS) is *always* on for production/staging, but only
   opt-in (requires an explicit TRUSTED_HOSTS env value) for development/
   testing -- see the Config class body comment for why: unconditionally
   restricting Host headers in APP_ENV=testing was verified to break the
   pre-existing, out-of-scope
   tests/security/test_account_change_photo_redirect_guard.py, which
   deliberately forges a Host header via test_request_context() to prove
   application logic never trusts request.host.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from config import (
    _default_secure_cookie,
    _preferred_url_scheme_conflicts_with_app_base_url,
    _resolve_preferred_url_scheme,
    _resolve_secure_cookie,
    _resolve_trusted_hosts,
)
from tests.sqlite_test_cleanup import release_sqlite_app

_HARDENING_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "https_hsts_hardening" / "test_dbs"
_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# PREFERRED_URL_SCHEME resolution -- pure unit tests, no Flask app needed
# ---------------------------------------------------------------------------

def test_explicit_https_wins_over_http_app_base_url():
    assert _resolve_preferred_url_scheme("https", "http://127.0.0.1:8000") == "https"


def test_explicit_scheme_is_normalized_case_and_whitespace():
    assert _resolve_preferred_url_scheme(" HTTPS ", "http://example.com") == "https"


def test_production_https_app_base_url_without_explicit_override():
    assert (
        _resolve_preferred_url_scheme(None, "https://bys360.canakkaletarihialan.gov.tr")
        == "https"
    )


def test_development_http_app_base_url_is_unaffected():
    assert _resolve_preferred_url_scheme(None, "http://127.0.0.1:8000") == "http"


def test_empty_explicit_env_value_falls_back_to_app_base_url_scheme():
    assert (
        _resolve_preferred_url_scheme("", "https://bys360.canakkaletarihialan.gov.tr")
        == "https"
    )


def test_invalid_explicit_scheme_is_ignored_not_passed_through():
    assert (
        _resolve_preferred_url_scheme("ftp", "https://bys360.canakkaletarihialan.gov.tr")
        == "https"
    )


def test_both_signals_missing_or_invalid_uses_safe_http_default():
    assert _resolve_preferred_url_scheme(None, "") == "http"
    assert _resolve_preferred_url_scheme("", "not-a-url-with-no-scheme") == "http"


def test_config_class_exposes_resolved_preferred_url_scheme():
    from config import Config

    assert Config.PREFERRED_URL_SCHEME in {"http", "https"}


# ---------------------------------------------------------------------------
# External URL generation actually honours PREFERRED_URL_SCHEME.
#
# Flask only consults PREFERRED_URL_SCHEME when building a URL adapter with
# no bound request (background jobs / CLI -- exactly where password-reset
# and notification mail links get generated). Inside an active request,
# Werkzeug binds the adapter to the request's own (ProxyFix-corrected)
# scheme instead, so this is exercised the same way Flask itself does it
# internally for SERVER_NAME-based, request-independent URL building.
# ---------------------------------------------------------------------------

def test_external_login_url_uses_https_when_preferred_scheme_is_https(app, monkeypatch):
    monkeypatch.setitem(app.config, "PREFERRED_URL_SCHEME", "https")
    with app.app_context():
        adapter = app.url_map.bind(
            "bys360.canakkaletarihialan.gov.tr",
            url_scheme=app.config["PREFERRED_URL_SCHEME"],
        )
        url = adapter.build("main.login", {}, force_external=True)
    assert url.startswith("https://")


def test_external_login_url_uses_http_when_preferred_scheme_is_http(app, monkeypatch):
    monkeypatch.setitem(app.config, "PREFERRED_URL_SCHEME", "http")
    with app.app_context():
        adapter = app.url_map.bind(
            "127.0.0.1:8000",
            url_scheme=app.config["PREFERRED_URL_SCHEME"],
        )
        url = adapter.build("main.login", {}, force_external=True)
    assert url.startswith("http://")
    assert not url.startswith("https://")


# ---------------------------------------------------------------------------
# HSTS / is_secure -- using the shared session app+client (PROXY_FIX_ENABLED
# is False here, since APP_ENV=testing; this is the "no trusted proxy
# configured" scenario, e.g. local/dev).
# ---------------------------------------------------------------------------

def test_shared_test_app_has_proxyfix_disabled_precondition(app):
    assert app.config.get("PROXY_FIX_ENABLED") is False


def test_hsts_absent_over_plain_http_with_no_signal(client):
    response = client.get("/login")
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_when_request_is_directly_secure(client):
    response = client.get("/login", base_url="https://testserver")
    assert "Strict-Transport-Security" in response.headers


def test_spoofed_x_forwarded_proto_without_proxyfix_is_not_treated_as_secure(client):
    """Regression: a raw X-Forwarded-Proto header must never flip is_secure
    on its own when no trusted proxy (ProxyFix) is configured to vet it."""
    response = client.get("/login", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_when_preferred_url_scheme_is_https(app, client, monkeypatch):
    """APP_BASE_URL-derived PREFERRED_URL_SCHEME is a non-spoofable,
    server-side third signal (defense-in-depth) independent of the
    connection's actual transport."""
    monkeypatch.setitem(app.config, "PREFERRED_URL_SCHEME", "https")
    response = client.get("/login")
    assert "Strict-Transport-Security" in response.headers


def test_hsts_policy_value_matches_config(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "PREFERRED_URL_SCHEME", "https")
    response = client.get("/login")
    assert response.headers.get("Strict-Transport-Security") == app.config.get(
        "HSTS_POLICY", "max-age=31536000; includeSubDomains"
    )


# ---------------------------------------------------------------------------
# HSTS via a real, trusted ProxyFix hop -- proves the legitimate proxied-
# HTTPS path still works after removing the raw-header shortcut.
# ---------------------------------------------------------------------------

def _make_proxyfix_test_app(monkeypatch):
    _HARDENING_TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _HARDENING_TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-https-hsts-hardening")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "PROXY_FIX_ENABLED", True)
    monkeypatch.setattr(Config, "PROXY_FIX_X_PROTO", 1)
    monkeypatch.setattr(
        Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix()
    )
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    proxied_app = create_app()
    proxied_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with proxied_app.app_context():
        db.create_all()

    return proxied_app


def test_hsts_present_via_trusted_proxyfix_hop(monkeypatch, request):
    proxied_app = _make_proxyfix_test_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(proxied_app))
    assert proxied_app.config.get("PROXY_FIX_ENABLED") is True
    proxied_client = proxied_app.test_client()

    response = proxied_client.get("/login", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" in response.headers


# ---------------------------------------------------------------------------
# Fixed: cookie Secure resolution now follows the *resolved* PREFERRED_URL_
# SCHEME (explicit env override > APP_BASE_URL scheme), not raw APP_BASE_URL
# alone. Contract (see config._resolve_secure_cookie / _default_secure_cookie
# docstrings for the authoritative version):
#
#   1. Explicit SESSION_COOKIE_SECURE / REMEMBER_COOKIE_SECURE env value ->
#      respected as the operator's conscious choice, EXCEPT:
#        a) an explicit 'true' is downgraded to False (with a
#           logger.warning) when the effective external scheme is not https
#           or the host is local/private, since a Secure cookie there would
#           never actually be sent back by the browser and would silently
#           break sessions.
#        b) BYS360_SEC3B_A1_COOKIE_FAIL_FAST_V1: an explicit 'false' that
#           contradicts an effective-https/public-host signal in production
#           or staging is NO LONGER honoured -- it raises RuntimeError (after
#           a logger.warning) so config.py itself refuses to import. This is
#           independent of, and does not replace,
#           app.security.startup_audit.validate_live_security_defaults, which
#           separately hard-blocks SESSION_COOKIE_SECURE/REMEMBER_COOKIE_
#           SECURE=False in production/staging regardless of scheme, but only
#           once a real Flask app is created via create_app() (factory_
#           bootstrap.run_preflight_checks). The two checks are
#           defense-in-depth at different points in the boot sequence: this
#           one catches the narrower "explicit false + effective https" case
#           at bare `import config` time (before any app object exists); the
#           other one is the broader, scheme-independent final gate at app
#           creation time. Neither one is redundant with, or disables, the
#           other.
#   2. No explicit value -> Secure is True iff the resolved PREFERRED_URL_
#      SCHEME is 'https' AND the APP_BASE_URL host is not local/private.
#   3. If APP_BASE_URL's own scheme and an explicit PREFERRED_URL_SCHEME
#      override disagree on a production/staging, non-local/private host,
#      config.py refuses to import (RuntimeError, same style as the
#      SECRET_KEY guard) instead of silently picking one of the two
#      contradictory signals. This never fires for local/private hosts or
#      outside production/staging (see the subprocess-based tests below),
#      so it cannot affect development/testing.
#   4. REMEMBER_COOKIE_SECURE follows the exact same contract via the same
#      _resolve_secure_cookie() helper.
# ---------------------------------------------------------------------------


def test_default_secure_cookie_true_when_effective_scheme_https_and_host_public():
    assert _default_secure_cookie("http://bys360.canakkaletarihialan.gov.tr", "https") is True


def test_default_secure_cookie_false_when_effective_scheme_is_http():
    assert _default_secure_cookie("http://bys360.canakkaletarihialan.gov.tr", "http") is False


def test_default_secure_cookie_false_when_host_local_even_if_effective_scheme_https():
    assert _default_secure_cookie("http://127.0.0.1:8000", "https") is False


def test_no_explicit_env_cookie_secure_now_follows_resolved_preferred_scheme_on_public_host():
    """Locks the fix for the previously-documented gap: an explicit
    PREFERRED_URL_SCHEME=https override on a *public, non-local* APP_BASE_URL
    now produces SESSION_COOKIE_SECURE=True even though APP_BASE_URL's own
    scheme is still http (e.g. an operator enabled a TLS-terminating proxy
    and set PREFERRED_URL_SCHEME=https but forgot to update APP_BASE_URL).
    Negative-test requirement: production + effective HTTPS + non-local host
    can no longer produce an insecure cookie."""
    app_base_url = "http://bys360.canakkaletarihialan.gov.tr"

    resolved_scheme = _resolve_preferred_url_scheme("https", app_base_url)
    resolved_cookie_secure = _resolve_secure_cookie("", "production", app_base_url, resolved_scheme)

    assert resolved_scheme == "https"
    assert resolved_cookie_secure is True


def test_local_host_cookie_secure_still_false_with_https_preferred_scheme_override():
    """The narrow, still-safe case: PREFERRED_URL_SCHEME=https override on a
    *local* APP_BASE_URL (e.g. local HSTS testing, matches this file's own
    test_hsts_present_when_preferred_url_scheme_is_https) must not flip the
    cookie Secure flag, since a local plain-HTTP connection would never
    actually deliver a Secure cookie back to the server."""
    local_http_base_url = "http://127.0.0.1:8000"

    resolved_scheme = _resolve_preferred_url_scheme("https", local_http_base_url)
    resolved_cookie_secure = _resolve_secure_cookie("", "production", local_http_base_url, resolved_scheme)

    assert resolved_scheme == "https"
    assert resolved_cookie_secure is False


def test_remember_cookie_secure_follows_same_contract_as_session_cookie_secure():
    app_base_url = "http://bys360.canakkaletarihialan.gov.tr"
    resolved_scheme = _resolve_preferred_url_scheme("https", app_base_url)

    assert (
        _resolve_secure_cookie(
            "", "production", app_base_url, resolved_scheme, cookie_name="REMEMBER_COOKIE_SECURE"
        )
        is True
    )


def test_explicit_true_is_downgraded_to_false_when_effective_scheme_is_http():
    resolved = _resolve_secure_cookie(
        "true", "production", "http://bys360.canakkaletarihialan.gov.tr", "http"
    )
    assert resolved is False


def test_explicit_true_is_downgraded_to_false_on_local_host_even_with_https_scheme():
    resolved = _resolve_secure_cookie("true", "production", "http://127.0.0.1:8000", "https")
    assert resolved is False


def test_explicit_true_is_respected_when_consistent_with_effective_https():
    """Explicit config priority (rule 1): a non-risky explicit value passes
    through unchanged."""
    resolved = _resolve_secure_cookie(
        "true", "production", "https://bys360.canakkaletarihialan.gov.tr", "https"
    )
    assert resolved is True


def test_explicit_false_now_fails_fast_in_production_when_effective_scheme_is_https(caplog):
    """BYS360_SEC3B_A1_COOKIE_FAIL_FAST_V1: closes the previously-open gap --
    production + effective HTTPS + explicit SESSION_COOKIE_SECURE=false is no
    longer silently honoured as the operator's "conscious choice" (that
    behaviour was rejected: it only produced a logger.warning, never blocked
    boot). _resolve_secure_cookie() now raises RuntimeError for exactly this
    combination, after first logging a warning for observability -- same
    fail-fast style as the SECRET_KEY guard and the PREFERRED_URL_SCHEME/
    APP_BASE_URL scheme-conflict guard in config.py's Config class body.
    """
    with caplog.at_level(logging.WARNING, logger="config"), pytest.raises(RuntimeError) as exc_info:
        _resolve_secure_cookie(
            "false", "production", "https://bys360.canakkaletarihialan.gov.tr", "https"
        )
    assert "SESSION_COOKIE_SECURE" in str(exc_info.value)
    assert "false" in str(exc_info.value).lower()
    assert any(
        "SESSION_COOKIE_SECURE=false" in record.message and "HTTPS" in record.message
        for record in caplog.records
    )


def test_explicit_false_fails_fast_for_remember_cookie_too():
    """Rule 4 (same contract for both cookies): the fail-fast is not special-
    cased to SESSION_COOKIE_SECURE -- REMEMBER_COOKIE_SECURE=false under the
    same production + effective-HTTPS conditions must also refuse silently
    passing through."""
    with pytest.raises(RuntimeError) as exc_info:
        _resolve_secure_cookie(
            "false", "production", "https://bys360.canakkaletarihialan.gov.tr", "https",
            cookie_name="REMEMBER_COOKIE_SECURE",
        )
    assert "REMEMBER_COOKIE_SECURE" in str(exc_info.value)


def test_explicit_false_fails_fast_in_staging_too():
    """Staging must carry the exact same contract as production -- this is
    not a production-only guard."""
    with pytest.raises(RuntimeError):
        _resolve_secure_cookie(
            "false", "staging", "https://bys360.canakkaletarihialan.gov.tr", "https"
        )


def test_explicit_false_still_accepted_outside_production_staging():
    """Regression guard (requirement #4): the fail-fast must be scoped to
    APP_ENV in {production, staging} only -- development/testing with an
    explicit false must keep working exactly as before, even on a public,
    effective-https host (an unusual but legal dev/test shape)."""
    resolved = _resolve_secure_cookie(
        "false", "testing", "https://bys360.canakkaletarihialan.gov.tr", "https"
    )
    assert resolved is False


def test_explicit_false_still_accepted_when_effective_scheme_is_http_in_production():
    """Regression guard: the fail-fast is scoped to *effective HTTPS* only --
    an explicit false in production while the effective external scheme is
    still http (no TLS-terminating proxy signal at all) is a different,
    lower-risk shape and must not be swept into this new fail-fast."""
    resolved = _resolve_secure_cookie(
        "false", "production", "http://bys360.canakkaletarihialan.gov.tr", "http"
    )
    assert resolved is False


def test_malformed_boolean_value_does_not_silently_produce_insecure_cookie_in_production_https():
    """Requirement #3: a garbled SESSION_COOKIE_SECURE value (not a
    recognised boolean token) must not slip through str_to_bool() into a
    silently-accepted insecure cookie in production + effective HTTPS --
    str_to_bool() treats it as False (same as an explicit 'false'), so it
    must hit the exact same fail-fast, not a silent False return."""
    with pytest.raises(RuntimeError):
        _resolve_secure_cookie(
            "not-a-bool", "production", "https://bys360.canakkaletarihialan.gov.tr", "https"
        )


def test_empty_string_value_is_treated_as_no_override_not_as_explicit_false():
    """Requirement #3 (other half): an empty-string env value (e.g.
    SESSION_COOKIE_SECURE="") must not be treated as an explicit choice at
    all -- it falls through to _default_secure_cookie(), which in
    production + effective HTTPS on a public host safely resolves to True
    (not to a silently-accepted insecure False)."""
    resolved = _resolve_secure_cookie(
        "", "production", "https://bys360.canakkaletarihialan.gov.tr", "https"
    )
    assert resolved is True


def test_explicit_true_downgrade_is_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="config"):
        _resolve_secure_cookie("true", "production", "http://127.0.0.1:8000", "https")
    assert any("SESSION_COOKIE_SECURE=true" in record.message for record in caplog.records)


def test_config_class_testing_env_local_host_cookie_secure_false_and_no_fail():
    """Development/test behaviour must be unaffected (requirement #4):
    the real, session-wide Config (APP_ENV=testing, default local
    APP_BASE_URL, per tests/conftest.py) resolves both cookies to False and
    -- since this module already imported successfully -- never fails."""
    from config import Config

    assert Config.APP_ENV == "testing"
    assert Config.SESSION_COOKIE_SECURE is False
    assert Config.REMEMBER_COOKIE_SECURE is False


# ---------------------------------------------------------------------------
# Scheme-conflict fail-fast (contract rule #3) -- exercised via a fresh
# subprocess `import config`, because Config's class-body attributes are
# computed exactly once per process from os.environ (see the BYS360_P13B_
# TEST_APP_ENV note in tests/security/test_phase13b_setup_admin.py); a
# subprocess is the only reliable way to re-trigger that class-body
# evaluation under different env vars without corrupting the already-cached
# `config` module for the rest of this pytest session.
# ---------------------------------------------------------------------------

_CONFLICT_SENSITIVE_ENV_KEYS = (
    "APP_ENV",
    "APP_BASE_URL",
    "PREFERRED_URL_SCHEME",
    "SECRET_KEY",
    "SESSION_COOKIE_SECURE",
    "REMEMBER_COOKIE_SECURE",
)
_STRONG_TEST_SECRET_KEY = "bys360-subprocess-config-conflict-test-secret-key-2026"


def _run_python_in_subprocess(code: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for key in _CONFLICT_SENSITIVE_ENV_KEYS:
        env.pop(key, None)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_config_boot_fails_when_preferred_url_scheme_conflicts_with_app_base_url_in_production():
    """APP_BASE_URL=http + explicit PREFERRED_URL_SCHEME=https (production,
    non-local host) must not pass silently: at minimum a warning, and here a
    hard fail-fast RuntimeError (same style as the SECRET_KEY guard)."""
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "http://bys360.canakkaletarihialan.gov.tr",
            "PREFERRED_URL_SCHEME": "https",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr
    assert "PREFERRED_URL_SCHEME" in result.stderr
    assert "APP_BASE_URL" in result.stderr


def test_config_boot_fails_for_reverse_scheme_conflict_in_staging():
    """The reverse direction also counts as a conflict: APP_BASE_URL=https
    with an explicit PREFERRED_URL_SCHEME=http downgrade."""
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "staging",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "PREFERRED_URL_SCHEME": "http",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr


def test_config_boot_conflict_never_fires_on_local_host_even_in_production():
    """The fail-fast must stay inert for local/private hosts -- this is
    exactly the dev/local-HSTS-testing shape used elsewhere in this file
    (monkeypatch.setitem(app.config, "PREFERRED_URL_SCHEME", "https") on the
    default local APP_BASE_URL) and must never be turned into a boot
    failure."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.SESSION_COOKIE_SECURE is False\n"
        "print('OK')\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "http://127.0.0.1:8000",
            "PREFERRED_URL_SCHEME": "https",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_boot_conflict_never_fires_outside_production_staging():
    """Requirement #4: development/testing must be completely unaffected by
    the new fail-fast, even when the conflict is present on a public host."""
    result = _run_python_in_subprocess(
        "import config\nprint('OK')\n",
        {
            "APP_ENV": "testing",
            "APP_BASE_URL": "http://bys360.canakkaletarihialan.gov.tr",
            "PREFERRED_URL_SCHEME": "https",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_boot_conflict_never_fires_when_preferred_url_scheme_not_overridden():
    """The common/expected production shape (APP_BASE_URL itself is https,
    no explicit PREFERRED_URL_SCHEME override) must never trip the
    conflict check -- PREFERRED_URL_SCHEME simply falls back to
    APP_BASE_URL's own scheme, so there is nothing to disagree with."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.PREFERRED_URL_SCHEME == 'https'\n"
        "assert Config.SESSION_COOKIE_SECURE is True\n"
        "assert Config.REMEMBER_COOKIE_SECURE is True\n"
        "print('OK')\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_preferred_url_scheme_conflicts_with_app_base_url_helper_both_directions():
    assert _preferred_url_scheme_conflicts_with_app_base_url("https", "http://example.com") is True
    assert _preferred_url_scheme_conflicts_with_app_base_url("http", "https://example.com") is True
    assert _preferred_url_scheme_conflicts_with_app_base_url("https", "https://example.com") is False
    assert _preferred_url_scheme_conflicts_with_app_base_url(None, "http://example.com") is False
    assert _preferred_url_scheme_conflicts_with_app_base_url("", "http://example.com") is False


# ---------------------------------------------------------------------------
# BYS360_SEC3B_A1_COOKIE_FAIL_FAST_V1 -- exercised via a fresh subprocess
# `import config`, same rationale as the scheme-conflict subprocess tests
# above: _resolve_secure_cookie() is called directly from the Config class
# body (SESSION_COOKIE_SECURE = _resolve_secure_cookie(...) /
# REMEMBER_COOKIE_SECURE = _resolve_secure_cookie(...)), so a bare
# `import config` in production/staging with an explicit *_COOKIE_SECURE=false
# and an effective HTTPS scheme must itself raise RuntimeError and abort the
# import -- this is what actually happens at process boot, not just what the
# pure _resolve_secure_cookie() unit tests above exercise directly.
# ---------------------------------------------------------------------------

def test_config_boot_fails_when_session_cookie_secure_explicit_false_in_production_effective_https():
    """Bare `import config` (no app factory involved) must itself refuse to
    boot when APP_ENV=production, APP_BASE_URL is a public https host (so
    PREFERRED_URL_SCHEME resolves to https with no local/private host
    exemption), and SESSION_COOKIE_SECURE is explicitly set to false --
    exactly the combination BYS360_SEC3B_A1_COOKIE_FAIL_FAST_V1 closes."""
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
            "SESSION_COOKIE_SECURE": "false",
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr
    assert "SESSION_COOKIE_SECURE" in result.stderr


def test_config_boot_fails_when_remember_cookie_secure_explicit_false_in_staging_effective_https():
    """Same contract as above, but for REMEMBER_COOKIE_SECURE and staging --
    the fail-fast is not special-cased to one cookie or to production only."""
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "staging",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
            "REMEMBER_COOKIE_SECURE": "false",
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr
    assert "REMEMBER_COOKIE_SECURE" in result.stderr


def test_config_boot_succeeds_with_explicit_cookie_secure_false_in_development_effective_https():
    """Regression guard (requirement #4): the exact same explicit-false +
    effective-https shape must keep booting successfully -- with both
    cookies actually resolving to False, not silently upgraded -- outside
    production/staging (here: development), even on a public https host."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.SESSION_COOKIE_SECURE is False\n"
        "print('OK')\n",
        {
            "APP_ENV": "development",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SESSION_COOKIE_SECURE": "false",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# BYS360_SEC3C_A1_PRODUCTION_HTTPS_FAIL_FAST_V1 -- closes the residual gap:
# production/staging + APP_BASE_URL=http://... with NO explicit
# PREFERRED_URL_SCHEME override on a public/non-local host previously
# resolved PREFERRED_URL_SCHEME to 'http' and let `import config` succeed
# with exit=0. Exercised via subprocess `import config`, same rationale as
# the scheme-conflict/cookie fail-fast subprocess tests above.
# ---------------------------------------------------------------------------


def test_config_boot_fails_when_production_app_base_url_is_plain_http_with_no_override():
    """The actual open gap this fix closes: production + APP_BASE_URL=http://...
    (public host, no explicit PREFERRED_URL_SCHEME override at all) must no
    longer boot successfully."""
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "http://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr
    assert "PREFERRED_URL_SCHEME" in result.stderr
    assert "https" in result.stderr.lower()


def test_config_boot_fails_when_staging_app_base_url_is_plain_http_with_no_override():
    """Staging must carry the exact same contract as production."""
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "staging",
            "APP_BASE_URL": "http://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr


def test_config_boot_succeeds_production_https_app_base_url_no_override():
    """The common/expected production shape (APP_BASE_URL already https, no
    override needed) must keep booting, with both cookies True."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.PREFERRED_URL_SCHEME == 'https'\n"
        "assert Config.SESSION_COOKIE_SECURE is True\n"
        "assert Config.REMEMBER_COOKIE_SECURE is True\n"
        "print('OK')\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_boot_production_https_guard_never_fires_on_local_host():
    """The new guard must stay inert for local/private hosts, exactly like
    the existing scheme-conflict guard -- this is the dev/local-testing
    shape and must never become a boot failure."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.PREFERRED_URL_SCHEME == 'http'\n"
        "print('OK')\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "http://127.0.0.1:8000",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_boot_production_https_guard_never_fires_outside_production_staging_development():
    """Requirement #4-style regression guard: development must be completely
    unaffected, even on a public http host."""
    result = _run_python_in_subprocess(
        "import config\nprint('OK')\n",
        {
            "APP_ENV": "development",
            "APP_BASE_URL": "http://bys360.canakkaletarihialan.gov.tr",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_boot_production_https_guard_never_fires_in_testing():
    """Same regression guard for APP_ENV=testing (the environment
    tests/conftest.py actually runs the rest of this suite under)."""
    result = _run_python_in_subprocess(
        "import config\nprint('OK')\n",
        {
            "APP_ENV": "testing",
            "APP_BASE_URL": "http://bys360.canakkaletarihialan.gov.tr",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_boot_scheme_conflict_guard_still_wins_when_both_guards_would_apply():
    """When an explicit PREFERRED_URL_SCHEME override disagrees with
    APP_BASE_URL's own scheme AND the resolved scheme ends up non-https
    (APP_BASE_URL=https + override=http), the earlier scheme-conflict guard
    (fix #3) fires first in the Config class body -- this is expected, not a
    bug: both guards would reach the same RuntimeError outcome for this
    input, and their relative order is not part of the observable contract."""
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "PREFERRED_URL_SCHEME": "http",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr
    assert "celisemez" in result.stderr


def test_config_boot_production_https_guard_negative_control_temporarily_disabled():
    """Controlled negative verification (required by the task): with the new
    guard's condition short-circuited to False, the exact input from
    test_config_boot_fails_when_production_app_base_url_is_plain_http_with_no_override
    must NO LONGER raise -- proving the guard (and not some other, unrelated
    mechanism) is what makes that test fail today.

    Implementation note: the patched copy of config.py is written to a
    throwaway ``tempfile.TemporaryDirectory()`` (never inside the repo tree,
    and never under the allowed-files boundary for this task) and imported
    from there via PYTHONPATH, with ``cwd`` still pointed at the repo root so
    the module's own ``from app...`` sub-imports keep resolving normally.
    The real config.py on disk is never modified.
    """
    import config as config_module

    source_path = Path(config_module.__file__)
    original_source = source_path.read_text(encoding="utf-8")
    marker = "APP_ENV in {'production', 'staging'}\n        and PREFERRED_URL_SCHEME != 'https'\n        and not _host_is_local_or_private(_preferred_scheme_conflict_host)"
    assert marker in original_source, "guard condition text moved; update this test's marker"
    disabled_source = original_source.replace(marker, "False  # BYS360_TEST_TEMP_DISABLED")
    assert disabled_source != original_source

    with tempfile.TemporaryDirectory(prefix="bys360_guard3_negctrl_") as tmp_dir:
        tmp_module_name = "_bys360_tmp_disabled_guard3_config"
        (Path(tmp_dir) / f"{tmp_module_name}.py").write_text(disabled_source, encoding="utf-8")

        env = dict(os.environ)
        for key in _CONFLICT_SENSITIVE_ENV_KEYS:
            env.pop(key, None)
        env.update(
            {
                "APP_ENV": "production",
                "APP_BASE_URL": "http://bys360.canakkaletarihialan.gov.tr",
                "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
                "PYTHONPATH": tmp_dir,
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", f"import {tmp_module_name}\nprint('OK')\n"],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            "Negative control failed: disabling the guard's condition should make "
            "the production+http+no-override shape boot successfully again. "
            f"stdout={result.stdout} stderr={result.stderr}"
        )
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# BYS360_SEC3C_A1_TRUSTED_HOSTS_V1 -- pure _resolve_trusted_hosts() unit
# tests (no Flask app needed).
# ---------------------------------------------------------------------------


def test_resolve_trusted_hosts_always_includes_canonical_app_base_url_host():
    resolved = _resolve_trusted_hosts(None, "https://bys360.canakkaletarihialan.gov.tr", "production")
    assert resolved == ["bys360.canakkaletarihialan.gov.tr"]


def test_resolve_trusted_hosts_empty_production_allowlist_defaults_to_app_base_url_host():
    """Requirement: an empty/unset production TRUSTED_HOSTS env must resolve
    to a safe default (APP_BASE_URL's own host), never to an empty list --
    Werkzeug treats an empty/None trusted list as "trust every Host header",
    which is the functional equivalent of a wildcard and unacceptable in
    production."""
    resolved = _resolve_trusted_hosts("", "https://bys360.canakkaletarihialan.gov.tr", "production")
    assert resolved == ["bys360.canakkaletarihialan.gov.tr"]
    assert resolved


def test_resolve_trusted_hosts_wildcard_raises_in_production():
    with pytest.raises(RuntimeError) as exc_info:
        _resolve_trusted_hosts("*", "https://bys360.canakkaletarihialan.gov.tr", "production")
    assert "TRUSTED_HOSTS" in str(exc_info.value)
    assert "*" in str(exc_info.value)


def test_resolve_trusted_hosts_wildcard_raises_in_staging_too():
    with pytest.raises(RuntimeError):
        _resolve_trusted_hosts("*", "https://bys360.canakkaletarihialan.gov.tr", "staging")


def test_resolve_trusted_hosts_wildcard_among_other_entries_still_raises():
    with pytest.raises(RuntimeError):
        _resolve_trusted_hosts(
            "bys360.canakkaletarihialan.gov.tr,*", "https://bys360.canakkaletarihialan.gov.tr", "production"
        )


def test_resolve_trusted_hosts_wildcard_is_accepted_outside_production_staging():
    """Regression guard (requirement #4 style): the wildcard rejection is
    scoped to production/staging only -- development/testing must not be
    swept into this fail-fast (an operator explicitly disabling Host
    validation locally is a legal, lower-risk shape)."""
    resolved = _resolve_trusted_hosts("*", "http://127.0.0.1:8000", "development")
    assert "*" in resolved


def test_resolve_trusted_hosts_dev_test_auto_adds_local_hosts():
    for env in ("development", "test", "testing"):
        resolved = _resolve_trusted_hosts(None, "http://127.0.0.1:8000", env)
        assert "localhost" in resolved, env
        assert "127.0.0.1" in resolved, env
        assert "::1" in resolved, env


def test_resolve_trusted_hosts_production_does_not_auto_add_local_hosts():
    """Requirement: production'da localhost KABUL EDILMEZ -- the dev/test
    local-host convenience must never leak into production/staging."""
    resolved = _resolve_trusted_hosts(None, "https://bys360.canakkaletarihialan.gov.tr", "production")
    assert "localhost" not in resolved
    assert "127.0.0.1" not in resolved
    assert "::1" not in resolved


def test_resolve_trusted_hosts_conflict_with_app_base_url_logs_warning_and_autoincludes_canonical(caplog):
    """Requirement: APP_BASE_URL/TRUSTED_HOSTS celiskisi ele alinir -- an
    explicit TRUSTED_HOSTS env that omits APP_BASE_URL's own host is not
    silently passed through: a warning is logged AND the canonical host is
    still auto-added so enforcement never accidentally locks out the
    application's own advertised base URL."""
    with caplog.at_level(logging.WARNING, logger="config"):
        resolved = _resolve_trusted_hosts(
            "other.example.gov.tr", "https://bys360.canakkaletarihialan.gov.tr", "production"
        )
    assert "bys360.canakkaletarihialan.gov.tr" in resolved
    assert "other.example.gov.tr" in resolved
    assert any(
        "TRUSTED_HOSTS" in record.message and "bys360.canakkaletarihialan.gov.tr" in record.message
        for record in caplog.records
    )


def test_resolve_trusted_hosts_no_warning_when_explicit_entries_already_cover_canonical(caplog):
    with caplog.at_level(logging.WARNING, logger="config"):
        resolved = _resolve_trusted_hosts(
            "bys360.canakkaletarihialan.gov.tr,extra.example.gov.tr",
            "https://bys360.canakkaletarihialan.gov.tr",
            "production",
        )
    assert resolved == ["bys360.canakkaletarihialan.gov.tr", "extra.example.gov.tr"]
    assert not any("TRUSTED_HOSTS" in record.message for record in caplog.records)


def test_resolve_trusted_hosts_port_in_app_base_url_is_stripped_from_canonical_entry():
    """Requirement: portlu kanonik host dogru islenir -- urlparse(...).hostname
    already strips the port, so the resolved TRUSTED_HOSTS entry is always
    host-only, matching what Werkzeug's host_is_trusted() expects (it also
    strips any port from both the incoming Host header and each trusted-list
    entry before comparing)."""
    resolved = _resolve_trusted_hosts(None, "https://bys360.canakkaletarihialan.gov.tr:8443", "production")
    assert resolved == ["bys360.canakkaletarihialan.gov.tr"]


def test_resolve_trusted_hosts_never_returns_empty_list_in_production():
    resolved = _resolve_trusted_hosts(None, "https://bys360.canakkaletarihialan.gov.tr", "production")
    assert resolved
    resolved_empty_env = _resolve_trusted_hosts("   ", "https://bys360.canakkaletarihialan.gov.tr", "production")
    assert resolved_empty_env


# ---------------------------------------------------------------------------
# BYS360_SEC3C_A1_TRUSTED_HOSTS_V1 -- real Flask app + test client, forged
# Host header. Isolated, single-test Flask app pattern (same rationale as
# _make_proxyfix_test_app above): Config.TRUSTED_HOSTS is computed once per
# process from os.environ, so a fresh in-process app with Config attributes
# monkeypatched directly is the only way to exercise different TRUSTED_HOSTS
# shapes without a subprocess per HTTP assertion.
# ---------------------------------------------------------------------------


def _make_trusted_hosts_test_app(
    monkeypatch,
    *,
    app_env: str,
    app_base_url: str,
    trusted_hosts_env: str | None = None,
):
    """Gercek bir Flask app + test client uzerinden app.config['TRUSTED_HOSTS']
    Host-header dogrulamasini uctan uca kanitlamak icin izole bir app kurar.

    Config.TRUSTED_HOSTS'u, config.py'deki Config class body'sinin GERCEKTEN
    kullandigi ayni iki adimli mantikla hesaplar: once _resolve_trusted_hosts()
    (test edilen GERCEK fonksiyon) ile coz, sonra config.py'deki AYNI
    enforcement kapisini uygular (production/staging HER ZAMAN zorlanir;
    development/testing SADECE acik bir TRUSTED_HOSTS env degeri verilmisse
    zorlanir -- bkz. bu dosyanin basindaki modul docstring'i, madde 6, ve
    config.py'deki BYS360_SEC3C_A1_TRUSTED_HOSTS_V1 yorumu).
    """
    _HARDENING_TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _HARDENING_TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("FLASK_ENV", app_env)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-trusted-hosts-hardening-2026")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    resolved = _resolve_trusted_hosts(trusted_hosts_env, app_base_url, app_env)
    is_prod_like = app_env in {"production", "staging"}
    explicit_opt_in = bool((trusted_hosts_env or "").strip())
    enforced = resolved if (is_prod_like or explicit_opt_in) else None

    monkeypatch.setattr(Config, "APP_ENV", app_env)
    monkeypatch.setattr(Config, "APP_BASE_URL", app_base_url)
    monkeypatch.setattr(Config, "TRUSTED_HOSTS", enforced)
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    if is_prod_like:
        # Bu yardimci yalnizca TRUSTED_HOSTS'u kanitlamak icindir; production/
        # staging PREFERRED_URL_SCHEME ve cookie Secure fail-fast'lerinin
        # (bu dosyanin geri kalaninda zaten ayrica kilitli) burada devreye
        # girip app kurulumunu engellemesini onlemek icin ilgili alanlari
        # tutarli/gecerli tutuyoruz.
        monkeypatch.setattr(Config, "PREFERRED_URL_SCHEME", "https")
        monkeypatch.setattr(Config, "SESSION_COOKIE_SECURE", True)
        monkeypatch.setattr(Config, "REMEMBER_COOKIE_SECURE", True)

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def test_trusted_hosts_production_canonical_host_is_accepted(monkeypatch, request):
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="production", app_base_url="https://bys360.canakkaletarihialan.gov.tr",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get("/login", headers={"Host": "bys360.canakkaletarihialan.gov.tr"})
    assert response.status_code != 400


def test_trusted_hosts_forged_host_header_is_rejected_with_400(monkeypatch, request):
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="production", app_base_url="https://bys360.canakkaletarihialan.gov.tr",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get("/login", headers={"Host": "evil.attacker.example"})
    assert response.status_code == 400


def test_trusted_hosts_rejects_subdomain_suffix_trick_host(monkeypatch, request):
    """`trusted.example.evil.example` (kanonik host'u SONEK olarak tasiyan
    ama aslinda tamamen farkli bir domain olan sahte host) reddedilmelidir --
    Werkzeug'un host_is_trusted() kurali, girdi '.' ile BASLAMADIKCA
    (bkz. _resolve_trusted_hosts docstring'i) yalnizca TAM eslesme kabul
    eder, naif bir str.endswith() DEGIL."""
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="production", app_base_url="https://trusted.example",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get("/login", headers={"Host": "trusted.example.evil.example"})
    assert response.status_code == 400


def test_trusted_hosts_rejects_prefix_trick_host(monkeypatch, request):
    """`eviltrusted.example` (kanonik host'u SONUNDA tasiyan ama farkli bir
    domain olan sahte host) reddedilmelidir."""
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="production", app_base_url="https://trusted.example",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get("/login", headers={"Host": "eviltrusted.example"})
    assert response.status_code == 400


def test_trusted_hosts_development_localhost_is_accepted_when_explicitly_enforced(monkeypatch, request):
    """Requirement: development'ta localhost kabul edilir. Development'ta
    varsayilan (acik TRUSTED_HOSTS env yokken) enforcement KAPALIDIR (bkz.
    modul docstring'i madde 6) -- bu yuzden ozelligi gercekten Flask
    seviyesinde kanitlamak icin operatorun acik bir TRUSTED_HOSTS verdigi
    (opt-in) senaryoyu kullaniyoruz; localhost/127.0.0.1/::1 otomatik
    eklendigi icin operatorun kendi listesinde olmasa bile erisilebilir
    kalmalidir."""
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="development", app_base_url="http://127.0.0.1:8000",
        trusted_hosts_env="mydevhost.local",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get("/login", headers={"Host": "localhost"})
    assert response.status_code != 400


def test_trusted_hosts_testing_localhost_is_accepted_when_explicitly_enforced(monkeypatch, request):
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="testing", app_base_url="http://127.0.0.1:8000",
        trusted_hosts_env="mytesthost.local",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get("/login", headers={"Host": "localhost"})
    assert response.status_code != 400


def test_trusted_hosts_127_0_0_1_is_accepted_in_test_and_dev(monkeypatch, request):
    for env in ("development", "testing"):
        app = _make_trusted_hosts_test_app(
            monkeypatch, app_env=env, app_base_url="http://127.0.0.1:8000",
            trusted_hosts_env="mydevhost.local",
        )
        request.addfinalizer(lambda app=app: release_sqlite_app(app))  # one finalizer per loop app
        client = app.test_client()
        response = client.get("/login", headers={"Host": "127.0.0.1"})
        assert response.status_code != 400, f"127.0.0.1 rejected in {env}"


def test_trusted_hosts_production_does_not_accept_localhost(monkeypatch, request):
    """Requirement: production'da localhost KABUL EDILMEZ -- dev/test'e ozel
    otomatik yerel host ekleme production/staging'de ASLA yapilmaz."""
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="production", app_base_url="https://bys360.canakkaletarihialan.gov.tr",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get("/login", headers={"Host": "localhost"})
    assert response.status_code == 400


def test_trusted_hosts_port_in_canonical_host_is_stripped_and_still_matches(monkeypatch, request):
    """Requirement: portlu kanonik host dogru islenir -- APP_BASE_URL'in
    kendi portu TRUSTED_HOSTS girdisine dahil edilmez ve Werkzeug'un kendi
    host_is_trusted()'i de hem gelen Host basligindaki hem trusted-list
    girdisindeki portu karsilastirmadan once atar -- bu yuzden APP_BASE_URL'in
    kendi portundan FARKLI bir portla gelen (ama host adi ayni olan) bir
    istek yine de kabul edilir."""
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="production",
        app_base_url="https://bys360.canakkaletarihialan.gov.tr:8443",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get(
        "/login", headers={"Host": "bys360.canakkaletarihialan.gov.tr:9999"}
    )
    assert response.status_code != 400


def test_trusted_hosts_wrong_host_with_matching_port_is_still_rejected(monkeypatch, request):
    """Negative control for the port test above: matching the port but not
    the hostname must still be rejected -- proves acceptance above is driven
    by hostname matching (with port correctly ignored), not by accident."""
    app = _make_trusted_hosts_test_app(
        monkeypatch, app_env="production",
        app_base_url="https://bys360.canakkaletarihialan.gov.tr:8443",
    )
    request.addfinalizer(lambda: release_sqlite_app(app))
    client = app.test_client()
    response = client.get(
        "/login", headers={"Host": "evil.attacker.example:8443"}
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# BYS360_SEC3C_A1_TRUSTED_HOSTS_V1 -- class-body wiring / boot-time
# behaviour via subprocess `import config` (same rationale as the
# scheme-conflict/cookie fail-fast subprocess tests above).
# ---------------------------------------------------------------------------


def test_config_boot_fails_when_trusted_hosts_env_contains_wildcard_in_production():
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
            "TRUSTED_HOSTS": "*",
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr
    assert "TRUSTED_HOSTS" in result.stderr


def test_config_boot_fails_when_trusted_hosts_env_contains_wildcard_in_staging():
    result = _run_python_in_subprocess(
        "import config\n",
        {
            "APP_ENV": "staging",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
            "TRUSTED_HOSTS": "*",
        },
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "RuntimeError" in result.stderr


def test_config_class_trusted_hosts_always_a_nonempty_list_in_production():
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.TRUSTED_HOSTS == ['bys360.canakkaletarihialan.gov.tr']\n"
        "print('OK')\n",
        {
            "APP_ENV": "production",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_class_trusted_hosts_is_none_in_development_without_explicit_env():
    """Enforcement gate: development/testing'de acik bir TRUSTED_HOSTS env
    degeri verilmedikce Config.TRUSTED_HOSTS None kalir (Flask'in varsayilan/
    eski davranisi -- tum Host basliklarina guven -- korunur). Bu, mevcut/
    ilgisiz Host-header-sahteciligi testlerini (bkz. modul docstring'i madde
    6 ve tests/security/test_account_change_photo_redirect_guard.py) kirmamak
    icin bilincli bir tasarim karari."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.TRUSTED_HOSTS is None\n"
        "print('OK')\n",
        {
            "APP_ENV": "development",
            "APP_BASE_URL": "http://127.0.0.1:8000",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_class_trusted_hosts_is_none_in_testing_without_explicit_env():
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.TRUSTED_HOSTS is None\n"
        "print('OK')\n",
        {
            "APP_ENV": "testing",
            "APP_BASE_URL": "http://127.0.0.1:8000",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_class_trusted_hosts_enforced_in_development_when_explicit_env_given():
    """Opt-in: operator development'ta acikca TRUSTED_HOSTS verirse (ornegin
    bir LAN/ngrok host kisitlamasini yerel test etmek icin), enforcement
    gercekten devreye girer ve kanonik host + local host'lar otomatik dahil
    edilir."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.TRUSTED_HOSTS is not None\n"
        "assert 'mydevhost.local' in Config.TRUSTED_HOSTS\n"
        "assert 'localhost' in Config.TRUSTED_HOSTS\n"
        "assert '127.0.0.1' in Config.TRUSTED_HOSTS\n"
        "print('OK')\n",
        {
            "APP_ENV": "development",
            "APP_BASE_URL": "http://127.0.0.1:8000",
            "TRUSTED_HOSTS": "mydevhost.local",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_config_class_trusted_hosts_negative_control_temporarily_disabled():
    """Controlled negative verification (required by the task): with the
    wildcard-rejection branch short-circuited to a no-op, the exact input
    from test_config_boot_fails_when_trusted_hosts_env_contains_wildcard_in_production
    must NO LONGER raise -- proving that specific branch (and not some other
    mechanism) is what makes that test fail today.

    Same throwaway-``tempfile.TemporaryDirectory()`` technique as
    test_config_boot_production_https_guard_negative_control_temporarily_disabled
    above -- the real config.py on disk is never modified.
    """
    import config as config_module

    source_path = Path(config_module.__file__)
    original_source = source_path.read_text(encoding="utf-8")
    marker = (
        "    if app_env in {'production', 'staging'}:\n"
        "        for entry in explicit_entries:\n"
        "            if entry == '*':\n"
    )
    assert marker in original_source, "guard condition text moved; update this test's marker"
    disabled_source = original_source.replace(
        marker,
        "    if False:  # BYS360_TEST_TEMP_DISABLED\n"
        "        for entry in explicit_entries:\n"
        "            if entry == '*':\n",
    )
    assert disabled_source != original_source

    with tempfile.TemporaryDirectory(prefix="bys360_trustedhosts_negctrl_") as tmp_dir:
        tmp_module_name = "_bys360_tmp_disabled_wildcard_config"
        (Path(tmp_dir) / f"{tmp_module_name}.py").write_text(disabled_source, encoding="utf-8")

        env = dict(os.environ)
        for key in _CONFLICT_SENSITIVE_ENV_KEYS:
            env.pop(key, None)
        env.update(
            {
                "APP_ENV": "production",
                "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
                "SECRET_KEY": _STRONG_TEST_SECRET_KEY,
                "TRUSTED_HOSTS": "*",
                "PYTHONPATH": tmp_dir,
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", f"import {tmp_module_name}\nprint('OK')\n"],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            "Negative control failed: disabling the wildcard-rejection branch "
            "should make TRUSTED_HOSTS='*' boot successfully again. "
            f"stdout={result.stdout} stderr={result.stderr}"
        )
        assert "OK" in result.stdout


def test_config_boot_succeeds_with_explicit_cookie_secure_false_in_testing_effective_https():
    """Same regression guard as above for APP_ENV=testing (the environment
    tests/conftest.py actually runs the rest of this suite under)."""
    result = _run_python_in_subprocess(
        "from config import Config\n"
        "assert Config.SESSION_COOKIE_SECURE is False\n"
        "assert Config.REMEMBER_COOKIE_SECURE is False\n"
        "print('OK')\n",
        {
            "APP_ENV": "testing",
            "APP_BASE_URL": "https://bys360.canakkaletarihialan.gov.tr",
            "SESSION_COOKIE_SECURE": "false",
            "REMEMBER_COOKIE_SECURE": "false",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
