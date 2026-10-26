
"""Application factory kurulum yardimcilari.

Core Refactor Faz 4 kapsami:
- app/__init__.py yalnizca orchestration katmani olarak kalir.
- Flask nesnesi, temel config, reverse proxy/preflight ve extension init adimlari
  burada test edilebilir kucuk fonksiyonlara ayrilir.
- Davranis degismez; DB, route, schema, guvenlik ve template akislari ayni sira ile calisir.
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from flask import Flask, Request, Response, request, session
from flask_login import login_required

from app.core.form_body_limit import BYS360Request
from app.core.reverse_proxy import apply_reverse_proxy_fix
from app.extensions import csrf, db, login_manager, migrate
from app.security.startup_audit import validate_live_security_defaults
from app.startup_checks import validate_runtime_prerequisites
from config import Config


def create_configured_flask_app(import_name: str, config_object: type[Any] = Config) -> Flask:
    """Flask uygulamasini olusturur ve temel config varsayilanlarini yukler."""
    app = Flask(import_name)
    app.request_class = BYS360Request
    app.config.from_object(config_object)
    configure_application_defaults(app, config_object)
    register_session_activity_refresh(app)
    return app


def configure_application_defaults(app: Flask, config_object: type[Any] = Config) -> None:
    """Uygulama acilisinda beklenen config varsayilanlarini tek yerde tutar."""
    app.config.setdefault("STRICT_SCHEMA_CHECK", getattr(config_object, "STRICT_SCHEMA_CHECK", False))
    app.config.setdefault("AUTO_REPAIR_SCHEMA", getattr(config_object, "AUTO_REPAIR_SCHEMA", False))
    app.config["PERMANENT_SESSION_LIFETIME"] = resolve_session_lifetime(app, config_object)


def resolve_session_lifetime(app: Flask, config_object: type[Any] = Config) -> timedelta:
    """Oturum cerezi imzasinin en fazla gecerli kalacagi sure.

    Flask PERMANENT_SESSION_LIFETIME icin kendi varsayilanini (31 gun) tanimladigi icin eski
    ``setdefault`` hic calismiyordu; PERMANENT_SESSION_LIFETIME_MINUTES (config.py, varsayilan 30)
    uygulanmiyordu. Flask bu sureyi kalici olmayan oturumlarda da imza yasi siniri olarak kullanir.
    Config nesnesi PERMANENT_SESSION_LIFETIME'i acikca tanimliyorsa o deger korunur.
    """
    if "PERMANENT_SESSION_LIFETIME" in _defined_settings(config_object):
        return app.permanent_session_lifetime
    minutes = app.config.get("PERMANENT_SESSION_LIFETIME_MINUTES", 30)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("PERMANENT_SESSION_LIFETIME_MINUTES pozitif bir tam sayi olmali (dakika).")
    return timedelta(minutes=minutes)


def _defined_settings(config_object: type[Any]) -> dict[str, Any]:
    """Config sinifinda (ve ust siniflarinda) tanimli ayarlar; Flask varsayilanlari dahil degil."""
    names: dict[str, Any] = {}
    for klass in reversed(getattr(config_object, "__mro__", (config_object,))):
        names.update(vars(klass))
    return names


SESSION_ACTIVITY_KEY = "_bys360_seen"
SESSION_ACTIVITY_REFRESH_SECONDS = 60

# Requests a page makes on its own (polling, page-load data, PWA, health checks); they never count
# as user activity, whatever headers they carry.
BACKGROUND_ENDPOINTS: frozenset[str] = frozenset({
    "static",
    "main.notifications_unread_count",  # base.html polls every 30 s
    "pwa.pwa_csrf_refresh",  # CSRF token refresh on every page load
    "ai_agent.ai_agent_assistant_widget_summary",  # assistant widget summary on page load
    "main.dashboard_heavy_panels",  # dashboard panels loaded after the page
    "main.messages_thread_live",
    "main.messages_thread_typing",
    "main.bys360_pwa_service_worker",
    "main.bys360_pwa_manifest",
    "pwa.manifest_webmanifest",
    "main.healthz",
    "ai_agent.ai_agent_health",
    "ai_agent.ai_agent_public_healthz",
})
BACKGROUND_BLUEPRINTS: frozenset[str] = frozenset({"health", "mobile_api"})


def _epoch_seconds() -> int:
    return int(time.time())


def is_user_activity(req: Request) -> bool:
    """True only when the request provably comes from a person: a page navigation or form submission
    the user activated. Anything else -- including writes -- is not activity.

    - background endpoints (above) never count;
    - browsers send ``Sec-Fetch-Mode``, ``Sec-Fetch-Dest`` and ``Sec-Fetch-User`` and scripts cannot
      set them. A link click, typed URL or submitted form is ``navigate`` + ``document`` + ``?1``,
      whatever the method. fetch()/XHR requests -- GET or POST, polling, auto-save or a button
      handler -- are never ``navigate``, and a reload or ``form.submit()`` started by a timer has no
      ``Sec-Fetch-User``; the server cannot tell a clicked fetch from an automatic one, so none
      counts;
    - without these headers (old browsers) nothing counts here: a script reload or ``form.submit()``
      looks like a user navigation there. Those browsers keep the session through the activity
      endpoint below, like AJAX work in any browser.
    """
    endpoint = req.endpoint
    if not endpoint or endpoint in BACKGROUND_ENDPOINTS or req.blueprint in BACKGROUND_BLUEPRINTS:
        return False
    if req.method in {"HEAD", "OPTIONS"}:
        return False
    return (req.headers.get("Sec-Fetch-Mode") == "navigate" and req.headers.get("Sec-Fetch-Dest") == "document"
            and req.headers.get("Sec-Fetch-User") == "?1")


def register_session_activity_refresh(app: Flask) -> None:
    """30 dakika gercek kullanici hareketsizliginde oturumu bitirir (onayli politika, 2026-10-26).

    Oturumda son gercek etkinligin zamani tutulur (SESSION_ACTIVITY_KEY). Her istekte bu zamandan
    bu yana PERMANENT_SESSION_LIFETIME gectiyse oturum temizlenir; cerez imzasi baska bir sebeple
    (ornegin arka planda oturuma yazan bir istek) yenilenmis olsa bile. Zaman yalniz gercek
    kullanici etkinliginde (is_user_activity) ve en fazla dakikada bir guncellenir; bu yazma cerezin
    yeniden imzalanmasini da saglar (web girisi session.permanent=False kullanir; Flask bu
    oturumlari yalniz degistiklerinde yeniden imzalar). Oturumda kullanici yoksa (anonim, mobil
    token) hicbir sey yazilmaz.

    Sayfa gecisi olmadan calisilan ekranlar (asistan, mesajlar, AJAX formlar) icin
    ``POST /session/activity`` (endpoint ``session_activity``) etkinligi kaydeder: oturum acik
    kullaniciya acik, genel CSRF korumasi altinda, imzali oturumdaki kullanici basina hiz sinirli,
    ayrica istemci adresi basina genis bir kotuye kullanim tavani var (api_rate_limit; ayni NAT
    arkasindaki personel birbirini engellemez) ve en fazla dakikada bir zaman yazar. static/js/bys360_session_activity.js onu yalniz klavye, isaretci,
    dokunma, tekerlek ve metin girisi olaylarinda cagirir; zamanlayici yoktur. Istemci sinyalleri
    (event.isTrusted dahil) insan kaniti degildir: bu uc, oturum cerezi ve CSRF belirteci olan
    sayfa kodunun cagirabilecegi bir etkinlik bildirimidir.
    """

    @app.before_request
    def end_idle_session() -> None:
        if not session.get("_user_id"):
            return
        seen = session.get(SESSION_ACTIVITY_KEY)
        if isinstance(seen, int) and _epoch_seconds() - seen >= app.permanent_session_lifetime.total_seconds():
            session.clear()

    @app.after_request
    def record_session_activity(response: Response) -> Response:
        if not session.get("_user_id"):
            return response
        now = _epoch_seconds()
        seen = session.get(SESSION_ACTIVITY_KEY)
        if not isinstance(seen, int):
            session[SESSION_ACTIVITY_KEY] = now  # the login response, or a session from before this rule
        elif now - seen >= SESSION_ACTIVITY_REFRESH_SECONDS and is_user_activity(request):
            session[SESSION_ACTIVITY_KEY] = now
        return response

    @login_required
    def session_activity() -> tuple[str, int]:
        now = _epoch_seconds()
        seen = session.get(SESSION_ACTIVITY_KEY)
        if not isinstance(seen, int) or now - seen >= SESSION_ACTIVITY_REFRESH_SECONDS:
            session[SESSION_ACTIVITY_KEY] = now
        return "", 204

    app.add_url_rule("/session/activity", "session_activity", session_activity, methods=["POST"])


def run_preflight_checks(app: Flask) -> None:
    """Extension init oncesi reverse proxy ve canli guvenlik on kontrollerini calistirir."""
    apply_reverse_proxy_fix(app)
    validate_runtime_prerequisites(app)
    validate_live_security_defaults(app)


def initialize_core_extensions(app: Flask) -> None:
    """BYS360 cekirdek Flask extension init sirasini korur."""
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)


def configure_login_manager_defaults() -> None:
    """Login manager varsayilan mesaj ve yonlendirme ayarlarini uygular."""
    login_manager.login_view = "main.login"
    login_manager.login_message = "Lütfen giriş yapın."
    login_manager.login_message_category = "warning"


__all__ = [
    "configure_application_defaults",
    "configure_login_manager_defaults",
    "create_configured_flask_app",
    "initialize_core_extensions",
    "is_user_activity",
    "register_session_activity_refresh",
    "resolve_session_lifetime",
    "run_preflight_checks",
]
