from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import abort, current_app, flash, make_response, redirect, request, session, url_for
from flask_login import current_user, login_user, logout_user

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.main_handlers.constants import SECURITY_QUESTION_CHOICES
from app.models import User
from app.route_support import create_login_captcha, get_login_captcha_question, safe_render
from app.security.email_policy import corporate_email_error_message, is_allowed_corporate_email
from app.security.request_guard import (
    clear_auth_failures,
    clear_reset_failures,
    get_auth_throttle_state,
    get_client_ip,
    get_reset_throttle_state,
    mask_identity,
    record_auth_failure,
    record_reset_attempt,
    should_log_auth_throttle,
)
from app.services.account_lookup import find_user_by_login_identifier, normalize_login_identifier

_MIN_PASSWORD_LENGTH = 8

logger = logging.getLogger(__name__)


_AUTH_FAILURE_COUNT_KEY = "auth.failure_count"
_AUTH_FAILURE_AT_KEY = "auth.last_failed_at"


def _login_captcha_threshold() -> int:
    try:
        return max(3, int(current_app.config.get("LOGIN_CAPTCHA_THRESHOLD", 3) or 3))
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/main_handlers/auth_handlers.py | line=34")
        return 3


def _login_failure_window() -> timedelta:
    try:
        minutes = int(current_app.config.get("LOGIN_FAILURE_WINDOW_MINUTES", 30) or 30)
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/main_handlers/auth_handlers.py | line=41")
        minutes = 30
    return timedelta(minutes=max(1, minutes))


def _reset_auth_challenge_state() -> None:
    for key in (
        _AUTH_FAILURE_COUNT_KEY,
        _AUTH_FAILURE_AT_KEY,
        "login_captcha_question",
        "login_captcha_answer",
    ):
        session.pop(key, None)
    session.modified = True


def _get_auth_failure_count() -> int:
    raw_count = session.get(_AUTH_FAILURE_COUNT_KEY)
    raw_at = session.get(_AUTH_FAILURE_AT_KEY)
    if not raw_count or not raw_at:
        return 0

    try:
        failed_at = datetime.fromisoformat(str(raw_at))
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/main_handlers/auth_handlers.py | line=65")
        _reset_auth_challenge_state()
        return 0

    if utc_now() - failed_at > _login_failure_window():
        _reset_auth_challenge_state()
        return 0

    try:
        return max(0, int(raw_count))
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/main_handlers/auth_handlers.py | line=75")
        _reset_auth_challenge_state()
        return 0


def _register_failed_login_attempt() -> int:
    count = _get_auth_failure_count() + 1
    session[_AUTH_FAILURE_COUNT_KEY] = count
    session[_AUTH_FAILURE_AT_KEY] = utc_now().isoformat()
    session.modified = True
    return count


def _should_require_captcha(user=None) -> bool:
    if user and bool(getattr(user, "captcha_required", False)):
        return True
    return _get_auth_failure_count() >= _login_captcha_threshold()


def _login_error_message() -> str:
    return str(
        current_app.config.get(
            "LOGIN_GENERIC_ERROR_MESSAGE",
            "Giriş başarısız. Bilgilerinizi kontrol edip tekrar deneyin.",
        )
        or "Giriş başarısız. Bilgilerinizi kontrol edip tekrar deneyin."
    )


def _render_login(captcha_required: bool = False, captcha_question: str | None = None):
    if captcha_required and not captcha_question:
        captcha_question = get_login_captcha_question()
    return safe_render(
        "login.html",
        "<h3>Giriş</h3>",
        captcha_required=captcha_required,
        captcha_question=captcha_question,
        security_questions=SECURITY_QUESTION_CHOICES,
    )


def login():
    if current_user.is_authenticated:
        if getattr(current_user, "must_set_security_question", False):
            return redirect(url_for("main.account_security_setup"))
        if getattr(current_user, "must_change_password", False):
            return redirect(url_for("main.account_change_password"))
        return redirect(url_for("main.home"))

    captcha_required = _should_require_captcha()
    captcha_question = get_login_captcha_question() if captcha_required else None

    if request.method == "POST":
        sicil_or_email = normalize_login_identifier(request.form.get("sicil_or_email") or request.form.get("email"))
        password = request.form.get("password") or ""
        captcha_answer = (request.form.get("captcha_answer") or "").strip()
        client_ip = get_client_ip()

        throttle_state = get_auth_throttle_state(client_ip, sicil_or_email)
        if not throttle_state.allowed:
            if should_log_auth_throttle(client_ip, sicil_or_email):
                current_app.logger.warning(
                    "Login gecici olarak kilitlendi | ip=%s | kimlik=%s | ip_count=%s/%s | identity_count=%s/%s | retry_after=%s",
                    client_ip,
                    mask_identity(sicil_or_email),
                    throttle_state.ip_count,
                    throttle_state.ip_limit,
                    throttle_state.identity_count,
                    throttle_state.identity_limit,
                    throttle_state.retry_after_seconds,
                )
            flash("Çok fazla başarısız giriş denemesi algılandı. Lütfen birkaç dakika sonra tekrar deneyin.", "danger")
            captcha_question = create_login_captcha()
            return _render_login(True, captcha_question)

        user = find_user_by_login_identifier(sicil_or_email)

        captcha_required = _should_require_captcha(user)
        if captcha_required:
            captcha_question = get_login_captcha_question()
            expected = session.get("login_captcha_answer")
            if not captcha_answer or captcha_answer != str(expected):
                flash("Robot doğrulaması başarısız.", "danger")
                return _render_login(True, captcha_question)

        if not user or not user.check_password(password):
            throttle_state = record_auth_failure(client_ip, sicil_or_email)
            attempt_count = _register_failed_login_attempt()
            if user:
                user.failed_login_attempts = int(getattr(user, "failed_login_attempts", 0) or 0) + 1
                if user.failed_login_attempts >= _login_captcha_threshold():
                    user.captcha_required = True
                db.session.commit()

            force_unknown = bool(current_app.config.get("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", True))
            captcha_required = (
                captcha_required
                or attempt_count >= _login_captcha_threshold()
                or (force_unknown and _get_auth_failure_count() >= _login_captcha_threshold())
                or not throttle_state.allowed
            )
            if captcha_required:
                captcha_question = create_login_captcha()
            flash(_login_error_message(), "danger")
            return _render_login(captcha_required, captcha_question)

        if not user.is_active:
            record_auth_failure(client_ip, sicil_or_email)
            _register_failed_login_attempt()
            captcha_required = _should_require_captcha(user)
            if captcha_required:
                captcha_question = create_login_captcha()
            flash("Hesap erişime kapalı. Yöneticiyle görüşün.", "danger")
            return _render_login(captcha_required, captcha_question)

        user.failed_login_attempts = 0
        user.captcha_required = False
        db.session.commit()
        clear_auth_failures(client_ip, sicil_or_email)
        _reset_auth_challenge_state()

        login_user(user, remember=False)
        session.permanent = False

        if getattr(user, "must_set_security_question", False):
            flash("İlk girişte gizli soru tanımlamanız gerekiyor.", "warning")
            return redirect(url_for("main.account_security_setup"))
        if getattr(user, "must_change_password", False):
            flash("İlk girişte şifrenizi değiştirmeniz gerekiyor.", "warning")
            return redirect(url_for("main.account_change_password"))

        flash("Giriş başarılı.", "success")
        return redirect(url_for("main.home"))

    return _render_login(captcha_required, captcha_question)


def forgot_password():
    found_user = None
    question = None

    if request.method == "POST":
        sicil_or_email = normalize_login_identifier(request.form.get("sicil_or_email"))
        answer = (request.form.get("security_answer") or "").strip()
        new_password = request.form.get("new_password") or ""
        new_password_repeat = request.form.get("new_password_repeat") or ""
        client_ip = get_client_ip()

        # BYS360_P13B_AUTH003_FIX: bu route hicbir throttle'a tabi degildi
        # (Phase 13B AUTH-003, confirmed - 40+ ardisik yanlis gizli soru
        # cevabi sifir kilitlenmeyle sonuclaniyor, tam hesap ele gecirmeyi
        # pratikte saniyeler icinde mumkun kiliyordu). Login ile ayni
        # IP+kimlik bazli kilitlenme burada da zorunlu kilinir.
        throttle_state = get_reset_throttle_state(client_ip, sicil_or_email)
        if not throttle_state.allowed:
            flash("Çok fazla deneme algılandı. Lütfen birkaç dakika sonra tekrar deneyin.", "danger")
            return safe_render("forgot_password.html", "<h3>Şifremi Unuttum</h3>", found_user=None)

        found_user = find_user_by_login_identifier(sicil_or_email)

        if not found_user:
            record_reset_attempt(client_ip, sicil_or_email)
            flash("Kullanıcı bulunamadı.", "danger")
            return safe_render("forgot_password.html", "<h3>Şifremi Unuttum</h3>", found_user=None)

        question = found_user.security_question
        if not question:
            record_reset_attempt(client_ip, sicil_or_email)
            flash("Bu kullanıcı için gizli soru tanımlı değil. Yöneticiyle görüşün.", "warning")
            return safe_render("forgot_password.html", "<h3>Şifremi Unuttum</h3>", found_user=found_user, question=None)

        if answer and new_password and new_password_repeat:
            if not found_user.check_security_answer(answer):
                record_reset_attempt(client_ip, sicil_or_email)
                flash("Gizli soru cevabı hatalı.", "danger")
                return safe_render("forgot_password.html", "<h3>Şifremi Unuttum</h3>", found_user=found_user, question=question)

            if len(new_password) < _MIN_PASSWORD_LENGTH:
                flash(f"Yeni şifre en az {_MIN_PASSWORD_LENGTH} karakter olmalıdır.", "warning")
                return safe_render("forgot_password.html", "<h3>Şifremi Unuttum</h3>", found_user=found_user, question=question)

            if new_password != new_password_repeat:
                flash("Yeni şifreler eşleşmiyor.", "warning")
                return safe_render("forgot_password.html", "<h3>Şifremi Unuttum</h3>", found_user=found_user, question=question)

            if found_user.check_password(new_password):
                flash("Yeni şifre mevcut şifre ile aynı olamaz.", "warning")
                return safe_render("forgot_password.html", "<h3>Şifremi Unuttum</h3>", found_user=found_user, question=question)

            found_user.set_password(new_password)
            found_user.failed_login_attempts = 0
            found_user.captcha_required = False
            if hasattr(found_user, "must_change_password"):
                found_user.must_change_password = False
            # BYS360_P13B_SESSION_STAMP: reset sonrasi baska bir cihazda acik
            # kalan onceki oturumlarin tamami bu satirla gecersiz kilinir
            # (Phase 13B, confirmed - reset onceden hicbir oturumu etkilemiyordu).
            found_user.rotate_security_stamp()
            db.session.commit()
            clear_reset_failures(client_ip, sicil_or_email)
            _reset_auth_challenge_state()

            current_app.logger.info(
                "Parola sifirlama tamamlandi | kimlik=%s | ip=%s",
                mask_identity(sicil_or_email),
                client_ip,
            )

            flash("Şifreniz güncellendi. Giriş yapabilirsiniz.", "success")
            return redirect(url_for("main.login"))

    return safe_render(
        "forgot_password.html",
        "<h3>Şifremi Unuttum</h3>",
        found_user=found_user,
        question=question,
    )

# BYS360_LOGOUT_FORCE_CLEAR_V2_15_12_BEGIN
def _bys360_unique_values(values):
    seen = set()
    result = []
    for value in values:
        if value is None:
            key = "__none__"
            normalized = None
        else:
            normalized = str(value).strip()
            if not normalized:
                continue
            key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized if key != "__none__" else None)
    return result


def _bys360_auth_cookie_domains():
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
    return _bys360_unique_values(domains)


def _bys360_delete_auth_cookies(response):
    cookie_names = _bys360_unique_values([
        current_app.config.get("SESSION_COOKIE_NAME") or "session",
        current_app.config.get("REMEMBER_COOKIE_NAME") or "remember_token",
        "session",
        "remember_token",
        "bys360_session",
        "bys360_remember_token",
    ])
    cookie_paths = _bys360_unique_values(["/", current_app.config.get("APPLICATION_ROOT") or "/"])
    for name in cookie_names:
        for path in cookie_paths:
            for domain in _bys360_auth_cookie_domains():
                try:
                    response.delete_cookie(name, path=path, domain=domain)
                except TypeError:
                    response.delete_cookie(name, path=path)
                except Exception:
                    current_app.logger.debug(
                        "Logout cookie temizleme atlandı | name=%s | domain=%s | path=%s",
                        name,
                        domain,
                        path,
                    )
    return response


def _bys360_no_store_response(response):
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Clear-Site-Data"] = '"cache"'
    response.headers["X-BYS360-Logout-Fix"] = "V2.15.12"
    return response
# BYS360_LOGOUT_FORCE_CLEAR_V2_15_12_END

def logout():
    try:
        _reset_auth_challenge_state()
    except Exception:
        current_app.logger.debug("Logout auth challenge temizliği atlandı", exc_info=True)

    try:
        logout_user()
    except Exception:
        current_app.logger.debug("Flask-Login logout_user atlandı", exc_info=True)

    try:
        session.clear()
        session.permanent = False
        session.modified = True
    except Exception:
        current_app.logger.debug("Logout session temizliği atlandı", exc_info=True)

    response = make_response(redirect(url_for("main.login")))
    _bys360_delete_auth_cookies(response)
    _bys360_no_store_response(response)
    return response

def _setup_admin_route_permitted() -> bool:
    # BYS360_P13B_SEC001_FIX: bu route'un tek korumasi "users tablosu bos mu"
    # kontroluydu; production'da acikca kapatan bir ortam/flag yoktu (Phase
    # 13B SEC-001, confirmed - production benzeri bir app'te anonim GET/POST
    # ile ilk admin olusturulabiliyordu). Varsayilan olarak production/staging
    # ortaminda fail-closed'dir; yalnizca acik SETUP_ADMIN_ENABLED bayragiyla
    # bilincli olarak yeniden acilabilir (ör. kontrollu ilk kurulum penceresi).
    app_env = str(current_app.config.get("APP_ENV") or "").strip().lower()
    if app_env not in {"production", "staging"}:
        return True
    return bool(current_app.config.get("SETUP_ADMIN_ENABLED", False))


def setup_admin():
    if not _setup_admin_route_permitted():
        abort(404)

    if User.query.count() > 0:
        return redirect(url_for("main.login"))

    if request.method == "POST":
        admin_email = (request.form.get("email") or "").strip().lower()
        if not is_allowed_corporate_email(admin_email):
            flash(corporate_email_error_message(), "warning")
            return safe_render("setup_admin.html", "<h3>İlk admin kurulumu</h3>")

        password = request.form.get("password") or ""
        if len(password) < _MIN_PASSWORD_LENGTH:
            flash(f"Parola en az {_MIN_PASSWORD_LENGTH} karakter olmalıdır.", "warning")
            return safe_render("setup_admin.html", "<h3>İlk admin kurulumu</h3>")

        user = User(
            ad=request.form["ad"].strip(),
            soyad=request.form["soyad"].strip(),
            sicil_no=request.form["sicil_no"].strip(),
            email=admin_email,
            unvan="Sistem Yöneticisi",
            role="admin",
            birim="Başkanlık",
            ust_birim="Başkanlık",
            yonetici_sicil=request.form["sicil_no"].strip(),
            ikinci_yonetici_sicil=request.form["sicil_no"].strip(),
            is_active=True,
        )
        user.set_password(password)
        if hasattr(user, "must_change_password"):
            user.must_change_password = False
        if hasattr(user, "must_set_security_question"):
            user.must_set_security_question = False
        if hasattr(user, "is_first_login"):
            user.is_first_login = False
        db.session.add(user)
        db.session.commit()
        current_app.logger.warning(
            "Ilk admin bootstrap ile olusturuldu | sicil=%s | ip=%s",
            user.sicil_no,
            get_client_ip(),
        )
        flash("İlk admin oluşturuldu.", "success")
        return redirect(url_for("main.login"))

    return safe_render("setup_admin.html", "<h3>İlk admin kurulumu</h3>")
