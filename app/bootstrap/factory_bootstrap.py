
"""Application factory kurulum yardimcilari.

Core Refactor Faz 4 kapsami:
- app/__init__.py yalnizca orchestration katmani olarak kalir.
- Flask nesnesi, temel config, reverse proxy/preflight ve extension init adimlari
  burada test edilebilir kucuk fonksiyonlara ayrilir.
- Davranis degismez; DB, route, schema, guvenlik ve template akislari ayni sira ile calisir.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Flask

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
    return app


def configure_application_defaults(app: Flask, config_object: type[Any] = Config) -> None:
    """Uygulama acilisinda beklenen config varsayilanlarini tek yerde tutar."""
    app.config.setdefault("STRICT_SCHEMA_CHECK", getattr(config_object, "STRICT_SCHEMA_CHECK", False))
    app.config.setdefault("AUTO_REPAIR_SCHEMA", getattr(config_object, "AUTO_REPAIR_SCHEMA", False))
    app.config.setdefault(
        "PERMANENT_SESSION_LIFETIME",
        timedelta(minutes=app.config.get("PERMANENT_SESSION_LIFETIME_MINUTES", 480)),
    )


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
    "run_preflight_checks",
]
