"""Secure management view of the admin accounts and a one-time initial password reissue.

Admin accounts stay hidden from the general user lists (/admin/users, /personnel). The view
``/admin/users?view=admins`` is the one place that lists them, and only for a real admin (stored
role exactly ``admin``). The reissue is the ``form_action=issue_initial_password`` POST of
``/admin/users/<id>/edit``. No new URL rule is added.

Recovery without deleting or re-creating an account: a real admin re-enters their own password
and reissues a random initial password for ANOTHER admin account. The new password is generated
here, stored only as a hash, shown once in the response body (no flash, no session, no URL,
``Cache-Control: no-store``) and never logged. The account must set a new security question and
change the password at the next login; its existing sessions end. The old password is never
read, shown or logged. Every reissue and every refused attempt writes an ``audit_logs`` row.
"""
from __future__ import annotations

import logging
import secrets

from flask import flash, make_response, redirect, request, url_for
from flask_login import current_user
from sqlalchemy import func

from app.extensions import db
from app.models import User
from app.route_support import normalize_role_name, render_access_denied, safe_render
from app.services.audit_service import write_audit_log

logger = logging.getLogger(__name__)

_ADMIN_ROLE = "admin"
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def is_real_admin(user) -> bool:
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and normalize_role_name(getattr(user, "role", "")) == _ADMIN_ROLE
    )


def new_initial_password() -> str:
    """A random one-time initial password (never the shared configured default)."""
    return secrets.token_urlsafe(12)


def credential_once_response(*, title: str, account: User, credential: str, note: str):
    """Render a credential exactly once in the response body, never cached or stored."""
    response = make_response(
        safe_render(
            "account_credential_once.html",
            "<h3>Başlangıç şifresi</h3>",
            title=title,
            account_sicil=getattr(account, "sicil_no", "") or "",
            account_name=getattr(account, "full_name", None) or f"{account.ad} {account.soyad}".strip(),
            account_email=getattr(account, "email", "") or "",
            credential=credential,
            note=note,
        )
    )
    for header, value in _NO_STORE_HEADERS.items():
        response.headers[header] = value
    return response


def _admin_rows() -> list[dict]:
    accounts = (
        User.query.filter(func.lower(func.trim(User.role)) == _ADMIN_ROLE)
        .order_by(User.id.asc())
        .all()
    )
    return [
        {
            "id": account.id,
            "sicil_no": account.sicil_no,
            "full_name": getattr(account, "full_name", None) or f"{account.ad} {account.soyad}".strip(),
            "email": account.email,
            "is_active": bool(account.is_active),
            "must_change_password": bool(getattr(account, "must_change_password", False)),
            "must_set_security_question": bool(getattr(account, "must_set_security_question", False)),
            "has_security_question": bool((getattr(account, "security_question", None) or "").strip()),
            "is_self": account.id == current_user.id,
        }
        for account in accounts
    ]


def _admin_view_url() -> str:
    return url_for("main.admin_users", view="admins")


def _refuse(target_id: int | None, reason: str, message: str):
    db.session.rollback()
    write_audit_log(
        "account.initial_password_reissue_refused",
        "user",
        target_id,
        new_data={"reason": reason},
        summary=f"Admin initial password reissue refused: {reason}",
    )
    db.session.commit()
    flash(message, "danger")
    return redirect(_admin_view_url())


def reissue_initial_password_impl(target_id: int):
    """POST /admin/users/<id>/edit with form_action=issue_initial_password (real admin only)."""
    if not is_real_admin(current_user):
        return render_access_denied()
    target = db.session.get(User, target_id) if target_id else None
    if target is None or normalize_role_name(target.role) != _ADMIN_ROLE:
        return _refuse(target_id, "not_an_admin_account", "Bu işlem yalnız admin hesapları için kullanılabilir.")
    if target.id == current_user.id:
        return _refuse(target.id, "self", "Kendi şifrenizi Hesabım > Şifre değiştir ekranından değiştirin.")
    if not current_user.check_password(request.form.get("actor_password") or ""):
        return _refuse(target.id, "reauthentication_failed", "Kimlik doğrulaması başarısız: kendi şifrenizi doğru girin.")

    credential = new_initial_password()
    target.set_password(credential)
    target.must_change_password = True
    target.must_set_security_question = True
    if hasattr(target, "is_first_login"):
        target.is_first_login = True
    if hasattr(target, "failed_login_attempts"):
        target.failed_login_attempts = 0
    if hasattr(target, "captcha_required"):
        target.captcha_required = False
    target.rotate_security_stamp()
    write_audit_log(
        "account.initial_password_reissued",
        "user",
        target.id,
        new_data={"must_change_password": True, "must_set_security_question": True, "sessions_ended": True},
        summary=f"Admin initial password reissued for sicil={target.sicil_no}",
    )
    db.session.commit()
    logger.info("BYS360 admin initial password reissued | target_id=%s | actor_id=%s", target.id, current_user.id)
    return credential_once_response(
        title="Yeni başlangıç şifresi",
        account=target,
        credential=credential,
        note="Hesap sahibi ilk girişte gizli sorusunu yeniden tanımlayıp şifresini değiştirecek. Açık oturumları sonlandırıldı.",
    )


def admin_accounts_view_impl():
    """GET /admin/users?view=admins (real admin only)."""
    if not is_real_admin(current_user):
        return render_access_denied()
    response = make_response(
        safe_render(
            "admin_accounts.html",
            "<h3>Admin hesapları</h3>",
            accounts=_admin_rows(),
        )
    )
    for header, value in _NO_STORE_HEADERS.items():
        response.headers[header] = value
    return response
