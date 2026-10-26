"""BYS360 P0: kritik işlemler için sabit rol sınırı.

``admin_required`` yalnız yönetim ailesi üyeliğine bakar; grup başkanı ve Hukuk Müşaviri
(``mali_musavir``) de bu ailededir. Aşağıdaki işlemler için proje sahibi kararıyla sabit bir
rol sınırı uygulanır. Rotalarda ``menu_key_required`` ile birlikte kullanılır: kullanıcının hem
kurumun canlı menü izni hem bu sınır içinde olması gerekir. Menü izni (Ayarlar > Rol Matrisi
veya kişi bazlı izin) bu sınırın üzerinde yetki vermez.

Dönem etkinleştirme, kilitleme ve görev üretimi için açık kurumsal yetki tanımı yoktur; bunlar
varsayımla genişletilmez ve proje sahibi kararına kadar yalnız gerçek admine açıktır.
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any

from flask import flash, redirect, request, url_for
from flask_login import current_user

from app.route_support import can_access_menu, normalize_role_name, render_access_denied
from app.services.account_change_guard import audit_refusal, is_real_admin

logger = logging.getLogger(__name__)

CRITICAL_OPERATION_ROLES: dict[str, frozenset[str]] = {
    "period_manage": frozenset({"admin", "baskan", "baskan_yardimcisi"}),
    "period_publish": frozenset({"admin", "baskan"}),
}

# Saklanan rolü tam olarak "admin" olan kullanıcı (rol etiketi, unvan veya takma ad yetki vermez).
REAL_ADMIN_OPERATIONS = frozenset({
    "period_delete",
    "period_activate",
    "period_lock",
    "assignment_generate",
})


def can_perform_critical_operation(user: Any, operation: str) -> bool:
    """Sabit rol sınırı; bilinmeyen işlem ve oturumsuz kullanıcı için kapalı."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if operation in REAL_ADMIN_OPERATIONS:
        return is_real_admin(user)
    allowed = CRITICAL_OPERATION_ROLES.get(operation)
    if allowed is None:
        return False
    return normalize_role_name(getattr(user, "role", "")) in allowed


def deny_critical_operation(operation: str):
    # Kalıcı denetim kaydı: mevcut red kaydıyla aynı tablo ve eylem (audit_logs, account.change_refused).
    # Form değeri, sorgu dizesi veya oturum bilgisi yazılmaz.
    audit_refusal(None, f"critical_operation:{operation}")
    logger.warning(
        "BYS360 P0 kritik işlem reddedildi | operation=%s | user_id=%s | role=%s | method=%s | path=%s",
        operation,
        getattr(current_user, "id", None),
        getattr(current_user, "role", None),
        request.method,
        request.path,
    )
    return render_access_denied()


def critical_action_refusal(operation: str, menu_key: str):
    """Tek rotada birden çok işlem varsa: işlem bazında menü izni + sabit rol sınırı; uygunsa None."""
    if can_access_menu(current_user, menu_key) and can_perform_critical_operation(current_user, operation):
        return None
    return deny_critical_operation(operation)


def period_reset_refusal(is_locked: bool, results_published: bool):
    """Mevcut dönemi plana yeniden bağlamak kilidi açar ve yayını kaldırır; bu yetkiler ayrıca istenir."""
    if is_locked:
        refusal = critical_action_refusal("period_lock", "performance_periods")
        if refusal is not None:
            return refusal
    if results_published:
        refusal = critical_action_refusal("period_publish", "performance_publish")
        if refusal is not None:
            return refusal
    return None


FROZEN_PERIOD_HIERARCHY_MESSAGE = (
    "Bu değişiklik kilitli veya sonuçları yayımlanmış dönemin görevlerini değiştirir; hiçbir kayıt "
    "yazılmadı. Önce dönemin kilidi veya yayını yetkili rotadan kaldırılmalıdır."
)


def hierarchy_sync_refusal(reason: str, target_user: Any, redirect_url: str):
    """M-1: hiyerarşi değişikliği bütün olarak reddedilir; oturumdaki her şey geri alınır.

    Gerçek admin olmayan için dönem geneli görev üretimi sabit sınırın dışındadır (403); kilitli
    veya yayımlanmış dönem için gerçek admin de reddedilir.
    """
    from app.services.performance.hierarchy_assignment_sync_guard import NON_ADMIN_PERIOD_SYNC

    if reason == NON_ADMIN_PERIOD_SYNC:
        return deny_critical_operation("assignment_generate")
    audit_refusal(target_user, "assignment_sync_frozen_period")
    flash(FROZEN_PERIOD_HIERARCHY_MESSAGE, "danger")
    return redirect(redirect_url)


def critical_operation_required(operation: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("main.login"))
            if not can_perform_critical_operation(current_user, operation):
                return deny_critical_operation(operation)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator
