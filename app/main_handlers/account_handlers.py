from __future__ import annotations

import logging

from app.main_handlers.account_communication_helpers import (
    SECURITY_QUESTION_CHOICES,
    _delete_profile_photo_file,
    _save_profile_photo,
    current_user,
    db,
    enforce_first_login_security_flow,
    flash,
    redirect,
    request,
    safe_render,
    url_for,
    utc_now,
)
from app.main_handlers.account_settings_helpers import account, settings_page  # noqa: F401
from app.route_support import is_safe_redirect_target

logger = logging.getLogger(__name__)

# Hesap güvenliği ve profil fotoğrafı işlemleri burada kalır; hesap/ayar ekranları
# account_settings_helpers üzerinden geriye dönük uyumla dışa aktarılır.

# BYS360_PHASE5_3B_A2_ACCOUNT_CHANGE_PHOTO_OPEN_REDIRECT_HARDENING
# Eskiden burada bağımsız, zayıf bir kontrol vardı:
#   next_url.startswith("/") and not next_url.startswith("//")
# Bu; backslash ("/\\evil.example") ve percent-encode edilmiş ayraç
# ("/%2Fevil.example", "/%5Cevil.example") tabanlı open-redirect
# bypass'larına karşı savunmasızdı (tarayıcılar bu biçimleri "//evil.example"
# ile eşdeğer, şema-göreli bir authority olarak yorumlayabilir). Artık tek
# doğruluk kaynağı, host-header'a değil kanonik APP_BASE_URL'e dayanan ve
# bu saldırı ailesine karşı test edilmiş `app.route_support.is_safe_redirect_target`.
def account_change_photo():
    next_url = (request.form.get("next") or "").strip()
    redirect_target = next_url if is_safe_redirect_target(next_url) else url_for("main.account")

    try:
        remove_photo = (request.form.get("remove_profile_photo") or "").strip().lower() in {"1", "true", "on", "evet", "yes"}

        if remove_photo:
            _delete_profile_photo_file(current_user.profile_photo_path)
            current_user.profile_photo_path = None
            current_user.profile_photo_updated_at = utc_now()
            db.session.commit()
            flash("Profil fotoğrafınız kaldırıldı.", "success")
            return redirect(redirect_target)

        photo = request.files.get("profile_photo")
        if not photo or not getattr(photo, "filename", ""):
            flash("Lütfen bir fotoğraf seçin.", "warning")
            return redirect(redirect_target)

        _save_profile_photo(photo, current_user)
        db.session.commit()
        flash("Profil fotoğrafınız güncellendi.", "success")
        return redirect(redirect_target)

    except Exception:
        logger.warning("PROFILE_PHOTO_UPDATE_FAILED")
        db.session.rollback()
        flash("Profil fotoğrafı güncellenirken hata oluştu.", "danger")
        return redirect(redirect_target)


_MIN_SECURITY_ANSWER_LENGTH = 4


def account_security_setup():
    if request.method == "POST":
        question = (request.form.get("security_question") or "").strip()
        answer = (request.form.get("security_answer") or "").strip()
        if not question or not answer:
            flash("Gizli soru ve cevap zorunludur.", "warning")
            return safe_render(
                "account_security_setup.html",
                "<h3>Gizli soru</h3>",
                security_questions=SECURITY_QUESTION_CHOICES,
            )
        # BYS360_P13B_AUTH003_FIX: soru serbest metin olarak kabul ediliyor ve
        # cevap uzunlugu hic sinirlanmiyordu (Phase 13B, confirmed - tek
        # karakterlik cevap kabul edilmisti). Onaylanmis soru listesi ve
        # minimum cevap uzunlugu, parola sifirlamanin fiili guvenlik
        # faktorunu zayif tutmasini engeller.
        if question not in SECURITY_QUESTION_CHOICES:
            flash("Lütfen listeden geçerli bir gizli soru seçin.", "warning")
            return safe_render(
                "account_security_setup.html",
                "<h3>Gizli soru</h3>",
                security_questions=SECURITY_QUESTION_CHOICES,
            )
        if len(answer) < _MIN_SECURITY_ANSWER_LENGTH:
            flash(f"Gizli soru cevabı en az {_MIN_SECURITY_ANSWER_LENGTH} karakter olmalıdır.", "warning")
            return safe_render(
                "account_security_setup.html",
                "<h3>Gizli soru</h3>",
                security_questions=SECURITY_QUESTION_CHOICES,
            )
        current_user.security_question = question
        current_user.set_security_answer(answer)
        current_user.must_set_security_question = False
        db.session.commit()
        if getattr(current_user, "must_change_password", False):
            flash("Şimdi şifrenizi değiştirmeniz gerekiyor.", "warning")
            return redirect(url_for("main.account_change_password"))
        flash("Gizli soru kaydedildi.", "success")
        return redirect(url_for("main.account"))

    return safe_render(
        "account_security_setup.html",
        "<h3>Gizli soru</h3>",
        security_questions=SECURITY_QUESTION_CHOICES,
    )


def account_change_password():
    force_password_change = bool(getattr(current_user, "must_change_password", False))
    password_min_length = 8

    if request.method == "POST":
        current_password = (request.form.get("current_password") or "").strip()
        new_password = (request.form.get("new_password") or "").strip()
        new_password_repeat = (request.form.get("new_password_repeat") or "").strip()

        if not current_user.check_password(current_password):
            flash("Mevcut şifre yanlış.", "danger")
            return safe_render(
                "account_change_password.html",
                "<h3>Şifre değiştir</h3>",
                force_password_change=force_password_change,
                password_min_length=password_min_length,
            )

        if len(new_password) < password_min_length:
            flash(f"Yeni şifre en az {password_min_length} karakter olmalıdır.", "warning")
            return safe_render(
                "account_change_password.html",
                "<h3>Şifre değiştir</h3>",
                force_password_change=force_password_change,
                password_min_length=password_min_length,
            )

        if new_password != new_password_repeat:
            flash("Yeni şifreler eşleşmiyor.", "warning")
            return safe_render(
                "account_change_password.html",
                "<h3>Şifre değiştir</h3>",
                force_password_change=force_password_change,
                password_min_length=password_min_length,
            )

        if current_user.check_password(new_password):
            flash("Yeni şifre mevcut şifre ile aynı olamaz.", "warning")
            return safe_render(
                "account_change_password.html",
                "<h3>Şifre değiştir</h3>",
                force_password_change=force_password_change,
                password_min_length=password_min_length,
            )

        current_user.set_password(new_password)
        current_user.must_change_password = False
        current_user.is_first_login = False
        db.session.commit()

        flash("Şifreniz güncellendi.", "success")
        return redirect(url_for("main.account"))

    return safe_render(
        "account_change_password.html",
        "<h3>Şifre değiştir</h3>",
        force_password_change=force_password_change,
        password_min_length=password_min_length,
    )


__all__ = [
    "account",
    "settings_page",
    "enforce_first_login_security_flow",
    "account_change_photo",
    "account_security_setup",
    "account_change_password",
]
