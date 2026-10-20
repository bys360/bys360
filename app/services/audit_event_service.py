from __future__ import annotations

from typing import Any

from flask import current_app, has_app_context, request
from flask_login import current_user

from app.bootstrap.request_context import redact_log_path
from app.extensions import db
from app.models import AuditLog
from app.services.audit_service import write_audit_log


def _safe_request_info() -> dict[str, Any]:
    """Denetim kaydına eklenebilecek güvenli ve sınırlı istek bağlamını üretir."""
    if not has_app_context():
        return {}
    try:
        return {
            "method": request.method,
            "path": redact_log_path(request.path),
            "endpoint": request.endpoint,
            "ip": request.headers.get("X-Forwarded-For") or request.remote_addr,
            "user_agent": (request.headers.get("User-Agent") or "")[:240],
        }
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/services/audit_event_service.py:28")
        return {}


def record_security_event(
    action: str,
    *,
    entity_type: str = "security_event",
    entity_id: int | None = None,
    summary: str = "",
    old_data: Any = None,
    new_data: Any = None,
    commit: bool = True,
) -> AuditLog | None:
    """Kritik güvenlik olaylarını audit_logs tablosuna best-effort yazar.

    Bu yardımcı, canlı isteği bozmamak için audit yazma hatalarında exception yükseltmez.
    Şema hazır değilse veya veritabanı geçici olarak erişilemiyorsa sadece uygulama loguna düşer.
    """
    try:
        payload = dict(new_data or {})
        payload.setdefault("request", _safe_request_info())
        try:
            if getattr(current_user, "is_authenticated", False):
                payload.setdefault("actor", {"user_id": getattr(current_user, "id", None), "role": getattr(current_user, "role", None)})
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/audit_event_service.py")
        audit = write_audit_log(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_data=old_data,
            new_data=payload,
            summary=summary,
        )
        if commit:
            db.session.commit()
        return audit
    except Exception as exc:  # pragma: no cover - canlı akışı bozmamak için güvenli düşüş
        try:
            db.session.rollback()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/audit_event_service.py")
        try:
            current_app.logger.warning("Audit log yazilamadi | action=%s | hata=%s", action, exc)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/audit_event_service.py")
        return None
