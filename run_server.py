
import contextlib
import os
import sys


def _ensure_utf8_stdio() -> None:
    """Reconfigures stdout/stderr to UTF-8 before any startup output.

    Windows Scheduled Task / redirected-console stdout defaults to the
    system ANSI codepage (commonly cp1252), which cannot encode Turkish
    characters such as the "s,"/"i" combinations in this module's own
    startup message. An otherwise-successful startup print then raises
    UnicodeEncodeError and kills the process before Waitress ever binds
    the port -- proven directly on the live Windows Server 2019 Scheduled
    Task "BYS360 Live Waitress 80": the task showed as Running, the
    process died on this exact print, port 80 never opened, and health
    checks failed. Reconfiguring stdout/stderr here (rather than just
    ASCII-sanitizing this one print) removes the locale dependency for
    every subsequent print/log call made through this process, not only
    this module's own message.

    Fails safe: if reconfigure isn't available or fails for any reason on
    a given stream, startup must still proceed unchanged -- an operator
    message must never be able to crash the app by itself.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(AttributeError, ValueError, OSError):
                reconfigure(encoding="utf-8")


_ensure_utf8_stdio()

from app import create_app  # noqa: E402 -- must run after _ensure_utf8_stdio()

app = create_app()


def _host() -> str:
    default_host = "127.0.0.1" if app.config.get("APP_ENV") == "development" else "0.0.0.0"
    return os.getenv("APP_HOST", default_host)


def _port() -> int:
    return int(os.getenv("APP_PORT", "8000"))


def _waitress_threads() -> int:
    return int(os.getenv("WAITRESS_THREADS", str(app.config.get("WAITRESS_THREADS", 8))))


def _waitress_proxy_settings() -> dict:
    """WAITRESS_TRUSTED_PROXY* (app/core/waitress_proxy.py); an invalid value stops startup."""
    from app.core.waitress_proxy import WaitressProxyConfigError, waitress_proxy_settings

    try:
        return waitress_proxy_settings(os.environ)
    except WaitressProxyConfigError as exc:
        raise SystemExit(f"BYS360 Waitress proxy yapilandirmasi gecersiz: {exc}") from exc


if __name__ == "__main__":
    host = _host()
    port = _port()
    app_env = (app.config.get("APP_ENV") or "development").strip().lower()
    print(f"BYS360 başlatılıyor ({app_env}): http://{host}:{port}")

    if app_env in {"production", "staging"}:
        from waitress import serve

        serve(app, host=host, port=port, threads=_waitress_threads(), **_waitress_proxy_settings())
    else:
        app.run(host=host, port=port, debug=False)
