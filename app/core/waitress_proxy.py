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
