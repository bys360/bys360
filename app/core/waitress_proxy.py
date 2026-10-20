"""Waitress proxy trust from the environment (WAITRESS_TRUSTED_PROXY*).

Waitress removes X-Forwarded-For/-Host/-Proto/-Port from every connection whose peer address is
not its ``trusted_proxy``. With no trust configured (the default) a reverse proxy's client address,
HTTPS scheme and public host never reach the application. These variables let the operator name
the one proxy Waitress may believe:

- ``WAITRESS_TRUSTED_PROXY``: the single IP address the proxy connects from (no ``*``, no list,
  no host name, no network);
- ``WAITRESS_TRUSTED_PROXY_COUNT``: proxy layers in front of Waitress (default 1, at most 10);
- ``WAITRESS_TRUSTED_PROXY_HEADERS``: the headers that proxy sets, a subset of
  x-forwarded-for, x-forwarded-proto, x-forwarded-host, x-forwarded-port.

Unset means no trust. An invalid or incomplete setting raises ``WaitressProxyConfigError``; it is
never widened or ignored. When Waitress trusts a proxy it alone interprets these headers, so the
application's ProxyFix must not read them again (see ``app/core/reverse_proxy.py``).

X-Forwarded-Prefix is not among the headers Waitress removes, and the application only sees the
address Waitress rewrote. ``waitress_application`` therefore drops it in front of Waitress's own
proxy handling unless the peer is the trusted proxy and every value is a plain path
(``/segment[/segment...]``); ProxyFix reads it only when ``PROXY_FIX_X_PREFIX`` enables it.
"""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from typing import Any

PROXY_ENV = "WAITRESS_TRUSTED_PROXY"
COUNT_ENV = "WAITRESS_TRUSTED_PROXY_COUNT"
HEADERS_ENV = "WAITRESS_TRUSTED_PROXY_HEADERS"
ALLOWED_HEADERS = frozenset({"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-forwarded-port"})
MAX_PROXY_COUNT = 10
PREFIX_ENVIRON_KEY = "HTTP_X_FORWARDED_PREFIX"
_PLAIN_PATH_PREFIX = re.compile(r"(?:/(?!\.\.?(?:/|$))[A-Za-z0-9._~-]+)+")  # no "." or ".." segment


class WaitressProxyConfigError(ValueError):
    """Invalid WAITRESS_TRUSTED_PROXY* configuration; Waitress must not start with it."""


def _value(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def trusted_proxy_address(env: Mapping[str, str]) -> str:
    """The normalised trusted proxy address, or "" when no trust is configured."""
    raw = _value(env, PROXY_ENV)
    if not raw:
        return ""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise WaitressProxyConfigError(
            f"{PROXY_ENV} must be the single IP address the reverse proxy connects from; got {raw!r}"
            " (no '*', list, host name or network)."
        ) from exc
    if address.is_unspecified:
        raise WaitressProxyConfigError(f"{PROXY_ENV} cannot be an unspecified address ({raw!r}).")
    return str(address)


def waitress_proxy_settings(env: Mapping[str, str]) -> dict[str, Any]:
    """Keyword arguments for ``waitress.serve`` derived from the environment."""
    settings: dict[str, Any] = {"clear_untrusted_proxy_headers": True}
    proxy = trusted_proxy_address(env)
    count_raw = _value(env, COUNT_ENV)
    headers_raw = _value(env, HEADERS_ENV)
    if not proxy:
        if count_raw or headers_raw:
            raise WaitressProxyConfigError(f"{COUNT_ENV} and {HEADERS_ENV} have no meaning without {PROXY_ENV}.")
        return settings

    count = 1
    if count_raw:
        if not re.fullmatch(r"\d+", count_raw) or not 1 <= int(count_raw) <= MAX_PROXY_COUNT:
            raise WaitressProxyConfigError(f"{COUNT_ENV} must be an integer from 1 to {MAX_PROXY_COUNT}; got {count_raw!r}.")
        count = int(count_raw)

    headers = {item.lower() for item in re.split(r"[\s,]+", headers_raw) if item}
    if not headers:
        raise WaitressProxyConfigError(
            f"{HEADERS_ENV} must list the headers the proxy sets (from {', '.join(sorted(ALLOWED_HEADERS))})."
        )
    unknown = headers - ALLOWED_HEADERS
    if unknown:
        raise WaitressProxyConfigError(
            f"{HEADERS_ENV} has unsupported values {sorted(unknown)}; allowed: {', '.join(sorted(ALLOWED_HEADERS))}."
        )
    settings.update(trusted_proxy=proxy, trusted_proxy_count=count, trusted_proxy_headers=" ".join(sorted(headers)))
    return settings


def _drop_untrusted_forwarded_prefix(app: Any, trusted_proxy: str | None) -> Any:
    def guarded(environ: dict[str, Any], start_response: Any) -> Any:
        value = environ.get(PREFIX_ENVIRON_KEY)
        if value is not None:
            from_trusted_proxy = bool(trusted_proxy) and environ.get("REMOTE_ADDR") == trusted_proxy
            plain = all(_PLAIN_PATH_PREFIX.fullmatch(part.strip()) for part in str(value).split(","))
            if not (from_trusted_proxy and plain):
                del environ[PREFIX_ENVIRON_KEY]
        return app(environ, start_response)

    return guarded


def waitress_application(app: Any, env: Mapping[str, str]) -> tuple[Any, dict[str, Any]]:
    """The WSGI application and ``waitress.serve`` keyword arguments for run_server.py.

    Waitress's own proxy-header handling is applied here, inside the X-Forwarded-Prefix guard (the
    guard must see the real peer address), so ``serve`` is told not to wrap the application again.
    """
    from waitress.proxy_headers import proxy_headers_middleware

    settings = waitress_proxy_settings(env)
    proxy = settings.get("trusted_proxy")
    inner = proxy_headers_middleware(
        app,
        trusted_proxy=proxy,
        trusted_proxy_count=settings.get("trusted_proxy_count", 1),
        trusted_proxy_headers=set(str(settings.get("trusted_proxy_headers", "")).split()),
        clear_untrusted=True,
    )
    return _drop_untrusted_forwarded_prefix(inner, proxy), {"clear_untrusted_proxy_headers": False}
