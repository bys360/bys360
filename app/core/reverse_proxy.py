from __future__ import annotations

from typing import Any

ProxyFix: type[Any] | None
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
except Exception:  # pragma: no cover - ortamda middleware olmayabilir
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/core/reverse_proxy.py:4")
    ProxyFix = None


def apply_reverse_proxy_fix(app):
    if ProxyFix is None:
        return app

    if not bool(app.config.get("PROXY_FIX_ENABLED", False)):
        return app

    hops = {
        "x_for": int(app.config.get("PROXY_FIX_X_FOR", 1) or 1),
        "x_proto": int(app.config.get("PROXY_FIX_X_PROTO", 1) or 1),
        "x_host": int(app.config.get("PROXY_FIX_X_HOST", 1) or 1),
        "x_port": int(app.config.get("PROXY_FIX_X_PORT", 1) or 1),
        "x_prefix": int(app.config.get("PROXY_FIX_X_PREFIX", 1) or 1),
    }
    if str(app.config.get("WAITRESS_TRUSTED_PROXY") or "").strip():
        # Waitress already applied the trusted proxy's X-Forwarded-For/-Proto/-Host/-Port
        # (app/core/waitress_proxy.py) and leaves those headers in place; reading them again here
        # would pick the wrong hop behind more than one proxy.
        hops.update(x_for=0, x_proto=0, x_host=0, x_port=0)
    app.wsgi_app = ProxyFix(app.wsgi_app, **hops)
    return app
