from __future__ import annotations

import re
from typing import Any

from flask import g, request


def client_ip() -> str:
    """Proxy arkasinda da okunabilir istemci IP degerini dondurur."""
    try:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        return request.remote_addr or "-"
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/bootstrap/request_context.py:20")
        return "-"


# Misafir dosya bağlantılarında yoldaki belirteç bağlantının tek sırrıdır; günlüğe maskeli yazılır.
_SECRET_PATH_SEGMENT = re.compile(r"^(/guest/(?:files|upload)/)[^/?]+")


def redact_log_path(path: str | None) -> str:
    """Günlük için yol: misafir bağlantı belirteci ``***`` olur, diğer yollar aynen kalır."""
    return _SECRET_PATH_SEGMENT.sub(r"\1***", str(path or ""))


def request_log_context() -> dict[str, Any]:
    """Guvenlik ve operasyon loglari icin standart istek baglami."""
    try:
        return {
            "request_id": getattr(g, "request_id", "-"),
            "method": request.method,
            "path": redact_log_path(request.path),
            "full_path": redact_log_path(request.full_path),
            "endpoint": request.endpoint,
            "ip": client_ip(),
            "remote_addr": request.remote_addr or "-",
            "referer": request.headers.get("Referer", "-"),
            "origin": request.headers.get("Origin", "-"),
            "user_agent": request.headers.get("User-Agent", "-"),
            "content_type": request.headers.get("Content-Type", "-"),
            "content_length": request.content_length,
        }
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/bootstrap/request_context.py:41")
        return {"request_id": getattr(g, "request_id", "-")}


def is_ops_bypass_user(user: Any) -> bool:
    """Bakim modunu gecebilmesine izin verilen operasyonel roller."""
    role_value = str(getattr(user, "role", "") or "").strip().lower()
    admin_roles = {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "koordinator"}
    return role_value in admin_roles
