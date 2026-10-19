from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

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
# Referer başka bir mount prefix'i (/bys) veya kodlanmış bölü işaretiyle gelebilir; yol bileşeninin
# herhangi bir segmentinde aranır (başa çapalı yol kalıbı tam URL'ye uygulanmaz).
_SECRET_SEGMENT_ANYWHERE = re.compile(r"(/guest/(?:files|upload)/)[^/?#]+")
_SECRET_MARKER = re.compile(r"/guest/(?:files|upload)/")
UNPARSEABLE_REFERER = "[ayrıştırılamayan referer]"


def redact_log_path(path: str | None) -> str:
    """Günlük için yol: misafir bağlantı belirteci ``***`` olur, diğer yollar aynen kalır."""
    return _SECRET_PATH_SEGMENT.sub(r"\1***", str(path or ""))


def _decoded(value: str) -> str:
    """Çift kodlamaya karşı birkaç tur çözülmüş metin (yalnız arama ve maskeleme için)."""
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def redact_log_referer(value: str | None) -> str:
    """Günlük için Referer: misafir belirteci yolda ``***`` olur, sorgu/parçadaysa o alan çıkarılır.

    Belirteç yolu içermeyen değer aynen kalır. Ayrıştırılamayan başlık ham yazılmaz.
    """
    raw = str(value or "").strip()
    if not raw:
        return "-"
    try:
        parts = urlsplit(raw)
        if not _SECRET_MARKER.search(_decoded(raw)):
            return raw
        path = _SECRET_SEGMENT_ANYWHERE.sub(r"\1***", _decoded(parts.path))
        query = "***" if _SECRET_MARKER.search(_decoded(parts.query)) else parts.query
        fragment = "***" if _SECRET_MARKER.search(_decoded(parts.fragment)) else parts.fragment
        netloc = parts.netloc.rsplit("@", 1)[-1]
        redacted = urlunsplit((parts.scheme, netloc, path, query, fragment))
    except (TypeError, ValueError):
        return UNPARSEABLE_REFERER
    # Son kontrol: maskelenmemiş bir belirteç yolu kalmışsa değer hiç yazılmaz.
    if _SECRET_SEGMENT_ANYWHERE.sub(r"\1***", _decoded(redacted)) != _decoded(redacted):
        return UNPARSEABLE_REFERER
    return redacted


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
            "referer": redact_log_referer(request.headers.get("Referer")),
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
