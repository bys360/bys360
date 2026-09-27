from __future__ import annotations

from typing import Any

from flask import (
    Flask,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, logout_user
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException, MethodNotAllowed, RequestEntityTooLarge
from werkzeug.wrappers import Response

from app.bootstrap.error_pages import mobile_json_error, wants_mobile_json_error
from app.extensions import db


def render_error_page(status_code: int, title: str, message: str):
    """Kurumsal hata sayfasini guvenli fallback ile render eder.

    Mobil API istekleri aynı durum kodu ve güvenli metinle JSON alır
    (Flutter istemcisi gövdeyi {"message": ...} olarak okur)."""
    if wants_mobile_json_error():
        return mobile_json_error(status_code, title, message)
    try:
        return render_template(
            f"errors/{status_code}.html",
            title=title,
            message=message,
        ), status_code
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:24")
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

def _safe_logout_after_expired_csrf() -> bool:
    """CSRF suresi dolmus logout POST isteginde beyaz hata yerine guvenli cikis yapar."""
    try:
        is_logout_post = request.method == "POST" and str(request.path or "").rstrip("/") == "/logout"
        if not is_logout_post:
            return False

        # Sadece cikis islemi icin yumuşak davranilir. Diger tum POST islemlerinde
        # CSRF korumasi aynen devam eder.
        if getattr(current_user, "is_authenticated", False):
            logout_user()

        session.clear()
        session.permanent = False
        session.modified = True
        current_app.logger.info("CSRF süresi dolmuş logout isteği güvenli çıkış olarak tamamlandı | detay=%s", request_log_context())
        return True
    except Exception:
        current_app.logger.exception("CSRF logout toparlama islemi sirasinda hata olustu | detay=%s", request_log_context())
        return False


# BYS360_LOGOUT_FORCE_CLEAR_V2_15_12_BEGIN
def _bys360_csrf_logout_cookie_domains():
    host = (request.host or "").split(":", 1)[0].strip().lower()
    configured = current_app.config.get("SESSION_COOKIE_DOMAIN")
    domains = [None, configured]
    if host and host not in {"localhost", "127.0.0.1", "::1"}:
        domains.append(host)
        parts = [part for part in host.split(".") if part]
        if len(parts) >= 2:
            domains.append("." + ".".join(parts[-2:]))
        if len(parts) >= 3:
            domains.append("." + ".".join(parts[-3:]))
    seen = set()
    out = []
    for item in domains:
        key = "__none__" if item is None else str(item).lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _bys360_csrf_logout_delete_auth_cookies(response):
    cookie_names = [
        current_app.config.get("SESSION_COOKIE_NAME") or "session",
        current_app.config.get("REMEMBER_COOKIE_NAME") or "remember_token",
        "session",
        "remember_token",
        "bys360_session",
        "bys360_remember_token",
    ]
    cookie_names = list(dict.fromkeys([str(x) for x in cookie_names if x]))
    cookie_paths = list(dict.fromkeys(["/", current_app.config.get("APPLICATION_ROOT") or "/"]))
    for name in cookie_names:
        for path in cookie_paths:
            for domain in _bys360_csrf_logout_cookie_domains():
                try:
                    response.delete_cookie(name, path=path, domain=domain)
                except TypeError:
                    response.delete_cookie(name, path=path)
                except Exception:
                    current_app.logger.debug("CSRF logout cookie temizleme atlandı", exc_info=True)
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Clear-Site-Data"] = '"cache"'
    response.headers["X-BYS360-Logout-Fix"] = "V2.15.12-CSRF"
    return response
# BYS360_LOGOUT_FORCE_CLEAR_V2_15_12_END

def _safe_rollback() -> None:
    try:
        db.session.rollback()
    except Exception:
        current_app.logger.exception("Rollback da takildi. Veritabani da yoruldu sanirim.")


def _client_ip() -> str:
    try:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        return request.remote_addr or "-"
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:128")
        return "-"


def request_log_context() -> dict[str, Any]:
    try:
        return {
            "request_id": getattr(g, "request_id", "-"),
            "method": request.method,
            "path": request.path,
            "full_path": request.full_path,
            "endpoint": request.endpoint,
            "ip": _client_ip(),
            "remote_addr": request.remote_addr or "-",
            "referer": request.headers.get("Referer", "-"),
            "origin": request.headers.get("Origin", "-"),
            "user_agent": request.headers.get("User-Agent", "-"),
            "content_type": request.headers.get("Content-Type", "-"),
            "content_length": request.content_length,
        }
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:148")
        return {"request_id": getattr(g, "request_id", "-")}

# Compatibility guard.
# BYS360_PHASE5_3C_A2_ERROR_HANDLERS_CSRF_REFERER_OPEN_REDIRECT_HARDENING
# Eskiden burada `request.host_url` tabanlı bağımsız bir "aynı origin mi?"
# kontrolü vardı (`referer.startswith(host_url)`), ardından yol kısmı elle
# kesiliyordu. `request.host_url`, istemcinin gönderdiği `Host` başlığından
# türer ve bir ters-proxy/IIS zincirinde yanlış yapılandırılmışsa saldırgan
# tarafından belirlenebilir (host-header poisoning); ayrıca backslash
# ("/\\evil.example") ve percent-encode edilmiş ayraç
# ("/%2Fevil.example", "%5cevil.example") varyantlarına karşı da
# savunmasızdı. Tek doğruluk kaynağı artık kanonik `APP_BASE_URL`'e dayanan
# `app.route_support.is_safe_redirect_target`. Import fonksiyon içinde
# tutulur: bu modül çok erken bootstrap zincirinde
# (`app.bootstrap.application_bootstrap`) yüklenir; modül seviyesinde bir
# import gereksiz döngüsel import riski taşır.
def _safe_csrf_referer_target() -> str:
    """Ayni site icinde guvenli geri donus adresi uretir."""
    from app.route_support import is_safe_redirect_target

    try:
        referer = (request.headers.get("Referer") or "").strip()
        if referer and is_safe_redirect_target(referer):
            return referer
    except Exception:
        try:
            current_app.logger.debug("CSRF guvenli geri donus adresi hesaplanamadi", exc_info=True)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:170")
            pass
    for endpoint in ("main.dashboard", "dashboard.index", "main.login"):
        try:
            return url_for(endpoint)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:175")
            continue
    return "/"


def _handle_expired_csrf_response(error: CSRFError):
    """CSRF korumasini gevsetmeden kullaniciyi temiz GET ekranina dondurur."""
    message = "Güvenlik doğrulaması yenilendi. Lütfen işlemi tekrar deneyin."
    try:
        current_app.logger.warning(
            "CSRF yenileme gerektiren istek | hata=%s | detay=%s",
            getattr(error, "description", "-"),
            request_log_context(),
        )
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:189")
        pass
    try:
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in (request.headers.get("Accept") or "")
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:193")
        wants_json = False
    if wants_json:
        response: Response = jsonify({"ok": False, "message": message, "csrf_refresh_url": "/pwa/csrf-refresh"})
        response.status_code = 400
    else:
        try:
            flash(message, "warning")
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:201")
            pass
        response = redirect(_safe_csrf_referer_target())
    try:
        response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-BYS360-CSRF-Recover"] = "V2.17.61"
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/error_handlers.py:209")
        pass
    return response
# Compatibility guard.

def register_service_unavailable_handler(app: Flask) -> None:
    @app.errorhandler(503)
    def service_unavailable(_error: Any):
        return render_error_page(
            503,
            "Bakım Modu",
            app.config.get("MAINTENANCE_MESSAGE") or "Sistem geçici olarak bakım modunda.",
        )


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(_error: Any):
        return render_error_page(
            403,
            "Erişim Yetkisi Bulunmamaktadır",
            "Bu sayfaya erişim yetkiniz bulunmamaktadır.",
        )  # BYS360_PHASE3_4_CORPORATE_ACCESS_DENIED_ERROR_HANDLER

    @app.errorhandler(404)
    def not_found(_error: Any):
        return render_error_page(404, "Sayfa Bulunamadı", "İstediğiniz sayfa sistemde bulunamadı.")

    @app.errorhandler(MethodNotAllowed)
    def handle_method_not_allowed(error: MethodNotAllowed):
        current_app.logger.warning(
            "405 Method Not Allowed | izinli_methodlar=%s | detay=%s",
            getattr(error, "valid_methods", None),
            request_log_context(),
        )
        if request.method == "POST" and request.path == "/":
            return render_error_page(
                405,
                "İşlem Yöntemi Desteklenmiyor",
                "Ana adrese POST isteği gönderildi. Bu adres POST kabul etmiyor.",
            )
        return render_error_page(
            405,
            "İşlem Yöntemi Desteklenmiyor",
            "Bu adres için kullanılan istek yöntemi desteklenmiyor.",
        )

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error: CSRFError):
        # BYS360_V60_1_LOGOUT_CSRF_GRACEFUL_EXIT
        # Ekran uzun sure acik kaldiginda logout formundaki token suresi dolabilir.
        # Bu durumda kullaniciya CSRF hata sayfasi gostermek yerine yalnizca logout
        # istegini guvenli cikis olarak tamamliyoruz. Diger tum POST isteklerinde
        # CSRF korumasi kesintisiz devam eder.
        if _safe_logout_after_expired_csrf():
            response = redirect(url_for("main.login"))
            return _bys360_csrf_logout_delete_auth_cookies(response)
        return _handle_expired_csrf_response(error)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_error: RequestEntityTooLarge):
        return render_error_page(413, "Dosya Çok Büyük", "Yüklenen içerik izin verilen boyut sınırını aşıyor.")

    @app.errorhandler(SQLAlchemyError)
    def handle_db_error(error: SQLAlchemyError):
        _safe_rollback()
        current_app.logger.exception("Veritabanı tarafı yine homurdandı: %s", error)
        return render_error_page(
            500,
            "Veritabanı Hatası",
            "İşlem sırasında veritabanı kaynaklı bir sorun oluştu. Bir işlem koyup tekrar deneyelim.",
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        # Werkzeug'un kendi .name / .description alanları (ör. 409, 422 gibi
        # ayrı bir errors/<kod>.html şablonu bulunmayan kodlarda) İngilizce
        # varsayılan metin taşır; kullanıcıya asla ham haliyle gösterilmez.
        # Operatör için gerçek ad/detay aşağıdaki log satırında korunur.
        current_app.logger.warning(
            "HTTP hata yakalandi | kod=%s | ad=%s | detay=%s",
            getattr(error, "code", 500),
            getattr(error, "name", "HTTPException"),
            request_log_context(),
        )
        return render_error_page(
            getattr(error, "code", 500) or 500,
            "İşlem Tamamlanamadı",
            "İsteğiniz işlenirken bir sorun oluştu. Lütfen tekrar deneyin.",
        )

    @app.errorhandler(Exception)
    def handle_generic_error(error: Exception):
        _safe_rollback()
        current_app.logger.exception("Beklenmeyen hata yakalandi: %s | detay=%s", error, request_log_context())
        return render_error_page(
            500,
            "Sistem Hatası",
            "Beklenmeyen bir hata oluştu. İşlem geri alındı; veri dağılmasın diye orada kestim.",
        )
