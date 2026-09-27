from __future__ import annotations

from flask import has_request_context, jsonify, render_template, request

MOBILE_API_PREFIX = "/api/mobile"


def wants_mobile_json_error() -> bool:
    """Mobil API istekleri (eşleşmeyen /api/mobile/... adresleri dahil) HTML
    hata sayfası yerine mobil JSON sözleşmesini ({"message": ...}) alır."""
    if not has_request_context():
        return False
    path = str(request.path or "")
    return request.blueprint == "mobile_api" or path == MOBILE_API_PREFIX or path.startswith(MOBILE_API_PREFIX + "/")


def mobile_json_error(status_code: int, title: str, message: str):
    """Sabit, güvenli metinli JSON hata yanıtı; ham istisna bilgisi taşımaz."""
    return jsonify({"message": message, "title": title}), status_code


def render_error_page(status_code: int, title: str, message: str):
    """Standart hata sayfasini guvenli fallback ile dondurur."""
    if wants_mobile_json_error():
        return mobile_json_error(status_code, title, message)
    try:
        return render_template(
            f"errors/{status_code}.html",
            title=title,
            message=message,
        ), status_code
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/bootstrap/error_pages.py:16")
        return (
            f"""
            <html>
                <head><title>{status_code} - {title}</title></head>
                <body style="font-family: Arial, sans-serif; padding: 40px;">
                    <h2>{title}</h2>
                    <p>{message}</p>
                </body>
            </html>
            """,
            status_code,
        )
