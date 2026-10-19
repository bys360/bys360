from __future__ import annotations

import os
import time

from flask import Flask, current_app, g, request
from flask_login import current_user

from app.bootstrap.error_pages import render_error_page
from app.bootstrap.request_context import is_ops_bypass_user, redact_log_path, request_log_context
from app.extensions import db
from app.security.request_guard import inspect_incoming_request
from app.services.audit_event_service import record_security_event


def _is_admin_path(path: str) -> bool:
    normalized = (path or "").strip().lower()
    return normalized == "/admin" or normalized.startswith("/admin/")


def _is_admin_gate_exempt_endpoint(endpoint: str | None) -> bool:
    return endpoint in {
        "static",
        "main.healthz",
        "main.readyz",
        "main.versionz",
        "main.login",
        "main.logout",
    }


def _has_admin_family_access(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    role_value = str(getattr(user, "role", "") or "").strip().lower()
    return role_value in {
        "admin",
        "baskan",
        "baskan_yardimcisi",
        "grup_baskani",
        "mali_musavir",
    }


def _enforce_admin_path_guard():
    """Admin alanını merkezi olarak kilitler ve reddedilen erişimleri denetim kaydına düşer."""
    if not _is_admin_path(request.path):
        return None
    if _is_admin_gate_exempt_endpoint(request.endpoint):
        return None
    if not getattr(current_user, "is_authenticated", False):
        current_app.logger.warning(
            "Admin alani oturumsuz erisim reddedildi | detay=%s",
            request_log_context(),
        )
        record_security_event(
            "admin_access_denied_unauthenticated",
            summary="Admin alanına oturumsuz erişim reddedildi.",
            new_data={"path": request.path, "endpoint": request.endpoint, "reason": "unauthenticated"},
        )
        return render_error_page(403, "Yetkisiz Erişim", "Bu alana erişmek için yetkili kullanıcı hesabıyla giriş yapılmalıdır.")
    if not _has_admin_family_access(current_user):
        current_app.logger.warning(
            "Admin alani rol yetkisi reddedildi | user_id=%s | role=%s | detay=%s",
            getattr(current_user, "id", None),
            getattr(current_user, "role", None),
            request_log_context(),
        )
        record_security_event(
            "admin_access_denied_role",
            summary="Admin alanına rol yetkisi olmayan kullanıcı erişimi reddedildi.",
            new_data={"path": request.path, "endpoint": request.endpoint, "reason": "role_denied", "role": getattr(current_user, "role", None)},
        )
        return render_error_page(403, "Yetkisiz Erişim", "Bu sayfaya erişim yetkiniz bulunmamaktadır.")
    return None


def register_teardown_guards(app: Flask) -> None:
    """Hata alan isteklerden sonra DB oturumunu temizler."""

    @app.teardown_request
    def cleanup_failed_session(_error: BaseException | None) -> None:
        if _error is None:
            return None
        try:
            db.session.rollback()
        except Exception:
            current_app.logger.exception("Teardown rollback basarisiz oldu.")
        finally:
            try:
                db.session.remove()
            except Exception:
                current_app.logger.exception("Teardown session remove basarisiz oldu.")
        return None


def register_operational_guards(app: Flask) -> None:
    """Request id, guvenlik tarama bloklari, bakim modu ve yavas istek loglarini baglar."""

    @app.before_request
    def prepare_request_context():
        g.request_started_at = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or request.environ.get("HTTP_X_REQUEST_ID") or os.urandom(8).hex()

        admin_guard_response = _enforce_admin_path_guard()
        if admin_guard_response is not None:
            return admin_guard_response

        security_decision = inspect_incoming_request()
        if security_decision:
            if security_decision.should_log:
                if security_decision.kind == "root_mutation":
                    current_app.logger.warning(
                        "Kok adrese mutasyon istegi engellendi | ip=%s | method=%s | count=%s/%s | retry_after=%s | detay=%s",
                        security_decision.client_ip,
                        security_decision.method,
                        security_decision.count,
                        security_decision.limit,
                        security_decision.retry_after_seconds,
                        request_log_context(),
                    )
                else:
                    current_app.logger.warning(
                        "Supheli tarama istegi engellendi | ip=%s | path=%s | method=%s | count=%s/%s | retry_after=%s",
                        security_decision.client_ip,
                        security_decision.path,
                        security_decision.method,
                        security_decision.count,
                        security_decision.limit,
                        security_decision.retry_after_seconds,
                    )
                record_security_event(
                    f"security_request_block_{security_decision.kind}",
                    summary="Şüpheli veya desteklenmeyen istek güvenlik katmanında yakalandı.",
                    new_data={
                        "kind": security_decision.kind,
                        "blocked": security_decision.blocked,
                        "count": security_decision.count,
                        "limit": security_decision.limit,
                        "retry_after_seconds": security_decision.retry_after_seconds,
                    },
                )
            if security_decision.kind == "root_mutation":
                if security_decision.blocked:
                    return render_error_page(429, "Çok Fazla İstek", "Aynı kaynaktan kısa sürede çok fazla hatalı istek algılandı.")
                return render_error_page(405, "İşlem Yöntemi Desteklenmiyor", "Ana adres yalnızca görüntüleme amaçlıdır; bu adrese veri gönderilemez.")
            if security_decision.kind == "suspicious_probe":
                if security_decision.blocked:
                    return render_error_page(429, "Çok Fazla İstek", "Kısa sürede çok fazla şüpheli istek algılandı.")
                return render_error_page(404, "Sayfa Bulunamadı", "İstediğiniz sayfa sistemde bulunamadı.")

        maintenance_mode = str(app.config.get("MAINTENANCE_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}
        if not maintenance_mode:
            return None

        exempt_endpoints = {
            "main.healthz",
            "main.readyz",
            "main.versionz",
            "health.health",
            "main.login",
            "static",
        }
        if request.endpoint in exempt_endpoints:
            return None

        if current_user.is_authenticated and is_ops_bypass_user(current_user):
            return None

        current_app.logger.warning("Bakim modu aktifken istek reddedildi: %s %s", request.method, redact_log_path(request.path))
        record_security_event(
            "maintenance_request_denied",
            summary="Bakım modu aktifken yetkisiz/istisna dışı istek reddedildi.",
            new_data={"path": redact_log_path(request.path), "endpoint": request.endpoint},
        )
        return render_error_page(503, "Bakım Modu", app.config.get("MAINTENANCE_MESSAGE") or "Sistem şu anda planlı bakım modunda. Lütfen kısa süre sonra tekrar deneyin.")

    @app.after_request
    def operational_access_log(response):
        started_at = getattr(g, "request_started_at", None)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at else None
        ops_logger = current_app.extensions.get("ops_logger")
        if ops_logger:
            ops_logger.info(
                "%s %s -> %s | endpoint=%s | duration_ms=%s | request_id=%s",
                request.method,
                redact_log_path(request.path),
                response.status_code,
                request.endpoint,
                duration_ms if duration_ms is not None else "-",
                getattr(g, "request_id", "-"),
            )
        if response.status_code >= 500:
            current_app.logger.error("5xx yanit verildi: %s %s -> %s", request.method, redact_log_path(request.path), response.status_code)
            record_security_event(
                "http_5xx_response",
                summary="Uygulama 5xx yanıt üretti.",
                new_data={"status_code": response.status_code, "duration_ms": duration_ms},
            )
        elif duration_ms is not None and duration_ms >= int(app.config.get("SLOW_REQUEST_THRESHOLD_MS", 1500)):
            current_app.logger.warning("Yavas istek: %s %s %sms", request.method, redact_log_path(request.path), duration_ms)
        return response
