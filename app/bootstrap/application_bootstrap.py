
"""BYS360 application bootstrap orchestration.

Core Refactor Faz 5 kapsami:
- app/__init__.py yalnizca public factory ve user_loader sozlesmesini tutar.
- Flask nesnesi, extension init, route bootstrap, runtime servisleri ve startup
  dogrulama akisi bu dosyada tek ve test edilebilir pipeline olarak toplanir.
- Davranis degismez; mevcut sira korunur, yeni modul veya DB degisikligi yoktur.
"""
from __future__ import annotations

from flask import Flask

from app.bootstrap.factory_bootstrap import (
    configure_login_manager_defaults,
    create_configured_flask_app,
    initialize_core_extensions,
    run_preflight_checks,
)
from app.bootstrap.operational_guards import register_operational_guards, register_teardown_guards
from app.bootstrap.operational_logging import configure_operational_logging
from app.bootstrap.registry import configure_route_bootstrap
from app.bootstrap.response_hardening import register_response_hardening
from app.bootstrap.schema_contract import get_expected_schema
from app.bootstrap.schema_validation import validate_required_schema
from app.bootstrap.startup import run_runtime_pipeline
from app.core.monitoring import configure_optional_sentry
from app.error_handlers import register_error_handlers, register_service_unavailable_handler
from app.security.private_uploads import install_private_static_guard
from app.security.startup_audit import run_startup_security_audit
from app.services.assistant_module_access import register_assistant_module_master_access
from app.services.assistant_shortcut_visibility import (
    register_assistant_shortcut_visibility_context,
)
from app.services.performance.feedback_followup_scheduler import init_feedback_followup_scheduler
from app.services.runtime_schema import register_runtime_schema_cli
from app.startup_checks import run_schema_guard_bootstrap
from app.template_helpers import register_template_helpers
from app.template_safety import register_template_safety


def create_bys360_application(import_name: str) -> Flask:
    """BYS360 uygulamasini Faz 5 pipeline sozlesmesine gore olusturur."""
    app = create_configured_flask_app(import_name)
    install_private_static_guard(app)  # B2-F06: /static/uploads/* -> 404
    run_preflight_checks(app)
    initialize_core_extensions(app)
    configure_login_manager_defaults()
    configure_route_bootstrap(app)
    configure_runtime_services(app)
    run_startup_validation_pipeline(app)
    return app


def configure_runtime_services(app: Flask) -> None:
    """Template safety, logging, error handlers ve request/response guard zinciri."""
    configure_optional_sentry(app)
    run_runtime_pipeline(
        app,
        register_template_safety=register_template_safety,
        configure_operational_logging=configure_operational_logging,
        register_error_handlers=register_error_handlers,
        register_service_unavailable_handler=register_service_unavailable_handler,
        register_teardown_guards=register_teardown_guards,
        register_operational_guards=register_operational_guards,
        register_response_hardening=register_response_hardening,
    )
    register_assistant_module_master_access(app)  # BYS360_V58_ASSISTANT_CONTEXT_PROCESSOR_BOOTSTRAP
    register_assistant_shortcut_visibility_context(app)  # BYS360_V58_ASSISTANT_SHORTCUT_VISIBILITY_BOOTSTRAP
    register_template_helpers(app)  # BYS360_MAINTENANCE_V13_P1_TEMPLATE_HELPERS_BOOTSTRAP
    init_feedback_followup_scheduler(app)  # BYS360_MAINTENANCE_MEDIUM_FEEDBACK_FOLLOWUP_SCHEDULER
    register_runtime_schema_cli(app)


def run_startup_validation_pipeline(app: Flask) -> None:
    """Security audit ve schema guard dogrulamasini tek yerde calistirir."""
    run_startup_security_audit(app)

    with app.app_context():
        run_schema_guard_bootstrap(app, lambda target_app: validate_required_schema(target_app, get_expected_schema()))


__all__ = [
    "configure_runtime_services",
    "create_bys360_application",
    "run_startup_validation_pipeline",
]
