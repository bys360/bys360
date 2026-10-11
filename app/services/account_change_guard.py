"""R05: who may change another account's role, password or active state, and the audit trail.

Approved least-privilege policy (HUMAN_POLICY_APPROVED, 2026-10-09/10): only the admin role
assigns broad rights; broad data rights are explicit, per person and auditable; role_label,
title or free text never creates authority; an unknown scope is denied.

``admin_required`` admits the whole admin family, so the web user-management routes check
these rules themselves:

- only a real admin (stored ``role`` exactly ``admin``) changes a stored role; anyone else
  creates accounts only with the baseline role and keeps every other role as it is;
- a non-admin editor never sets the password of, activates, deactivates, archives or deletes
  a protected account: their own, any role other than the baseline (unknown roles included)
  or a holder of a visible ``personnel_read_all`` / ``support_all`` row (any source, active
  or not, so a disabled holder cannot be revived and taken over);
- a non-admin editor never changes the manager chain of a protected account and never adds
  themselves to anyone's manager chain;
- a password set by another user, and a deactivation, end the target's other sessions;
- every change and every refusal writes an ``audit_logs`` row without password material.

The checks read the stored values only and fail closed.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.route_support import normalize_role_name
from app.services.personnel_read_grant import PERSONNEL_READ_ALL_KEY

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"
BASELINE_ROLE = "personel"
SUPPORT_ALL_KEY = "support_all"
# Read only: holders of these explicit grants are protected; this module never writes them.
PROTECTED_GRANT_KEYS: tuple[str, ...] = (PERSONNEL_READ_ALL_KEY, SUPPORT_ALL_KEY)

REFUSAL_MESSAGE = "Bu hesap değişikliği (rol, şifre veya aktiflik) yalnız sistem admini tarafından yapılabilir."
MANAGER_CHAIN_REFUSAL_MESSAGE = (
    "Bu hesabın amir zinciri yalnız sistem admini tarafından değiştirilebilir; kendinizi bir personelin amiri yapamazsınız."
)
ROLE_REFUSAL_MESSAGE = "Rol ataması ve rol değişikliği yalnız sistem admini tarafından yapılabilir."


def is_real_admin(actor: Any) -> bool:
    """The stored role is exactly ``admin`` (no role_label, title or admin-family alias)."""
    return bool(
        actor is not None
        and getattr(actor, "id", None) is not None
        and normalize_role_name(getattr(actor, "role", "")) == ADMIN_ROLE
    )


def holds_protected_grant(user: Any) -> bool:
    """A visible ``personnel_read_all`` / ``support_all`` row of any source; fails closed."""
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    try:
        from app.models import UserMenuPermission

        row = UserMenuPermission.query.filter(
            UserMenuPermission.user_id == user_id,
            UserMenuPermission.menu_key.in_(PROTECTED_GRANT_KEYS),
            UserMenuPermission.is_visible.is_(True),
        ).first()
        return row is not None
    except SQLAlchemyError:
        logger.exception("BYS360 R05 protected grant lookup failed; treating the account as protected.")
        _safe_rollback()
        return True


def holds_support_all_row(user: Any) -> bool:
    """A visible ``support_all`` row of any source (fails closed). Full matrix saves also store
    invisible rows for every menu key, so an invisible row is not a holder."""
    user_id = getattr(user, "id", None)
    if user_id is None:
        return True
    try:
        from app.models import UserMenuPermission

        return (
            UserMenuPermission.query.filter_by(user_id=user_id, menu_key=SUPPORT_ALL_KEY, is_visible=True).first()
            is not None
        )
    except SQLAlchemyError:
        logger.exception("BYS360 R05 support_all lookup failed; treating the account as protected.")
        _safe_rollback()
        return True


def is_protected_account(target: Any, actor: Any) -> bool:
    """The accounts a non-admin editor may not take over or switch on/off."""
    if target is None or getattr(target, "id", None) is None:
        return True
    if getattr(actor, "id", None) is not None and getattr(target, "id", None) == getattr(actor, "id", None):
        return True
    if normalize_role_name(getattr(target, "role", "")) != BASELINE_ROLE:
        return True
    return holds_protected_grant(target)


def role_changes(old_role: Any, new_role: Any) -> bool:
    return normalize_role_name(old_role) != normalize_role_name(new_role)


def may_assign_role(actor: Any, new_role: Any) -> bool:
    """New accounts: a non-admin creates only the baseline role."""
    return is_real_admin(actor) or normalize_role_name(new_role or BASELINE_ROLE) == BASELINE_ROLE


def may_change_role(actor: Any, target: Any, new_role: Any) -> bool:
    return is_real_admin(actor) or not role_changes(getattr(target, "role", ""), new_role)


def may_change_account_state(actor: Any, target: Any) -> bool:
    """Password, activation, archive, deletion, login identifiers and security flags of an account."""
    return is_real_admin(actor) or not is_protected_account(target, actor)


def kept_role(old_role: Any, new_role: Any) -> Any:
    """Keep the stored spelling when the role does not change (no "ADMIN" for "admin")."""
    return old_role if not role_changes(old_role, new_role) else new_role


def login_identity_changes(target: Any, *, sicil_no: Any, email: Any) -> bool:
    """sicil_no / e-mail are the login identifiers."""
    return (str(sicil_no or "").strip() != str(getattr(target, "sicil_no", "") or "").strip()) or (
        str(email or "").strip().lower() != str(getattr(target, "email", "") or "").strip().lower()
    )


def security_flags_change(target: Any, *, must_change_password: Any, must_set_security_question: Any) -> bool:
    return bool(must_change_password) != bool(getattr(target, "must_change_password", False)) or bool(
        must_set_security_question
    ) != bool(getattr(target, "must_set_security_question", False))


MANAGER_FIELDS: tuple[str, ...] = ("yonetici_sicil", "ikinci_yonetici_sicil", "ucuncu_yonetici_sicil")


def _sicil(value: Any) -> str:
    return str(value or "").strip().upper()


def may_change_manager_chain(actor: Any, target: Any, new_sicils: Any) -> bool:
    """Manager (evaluator) chain: a non-admin never changes the chain of a protected account and
    never adds themselves to anyone's chain (that would create an evaluator relation)."""
    if is_real_admin(actor):
        return True
    old = tuple(_sicil(getattr(target, field, None)) for field in MANAGER_FIELDS)
    new = tuple(_sicil(value) for value in (list(new_sicils or ()) + [None] * len(MANAGER_FIELDS))[: len(MANAGER_FIELDS)])
    if old == new:
        return True
    if is_protected_account(target, actor):
        return False
    actor_sicil = _sicil(getattr(actor, "sicil_no", None))
    return not actor_sicil or actor_sicil in old or actor_sicil not in new


def end_other_sessions(target: Any) -> None:
    """Invalidate the target's existing web sessions (see User.get_id / load_user)."""
    rotate = getattr(target, "rotate_security_stamp", None)
    if callable(rotate):
        rotate()


def audit_account_change(action: str, target: Any, *, old: Any = None, new: Any = None, summary: str = "") -> None:
    """Add an ``audit_logs`` row to the caller's transaction (never password material)."""
    from app.services.audit_service import write_audit_log

    write_audit_log(
        action,
        "user",
        getattr(target, "id", None),
        old_data=old,
        new_data=new,
        summary=summary or f"{action} sicil={getattr(target, 'sicil_no', '') or '-'}",
    )


def record_account_changes(target: Any, *, old_role: Any, old_active: Any, password_set: bool = False) -> None:
    """Audit what changed on ``target`` (in the caller's transaction) and end sessions if needed."""
    new_role = getattr(target, "role", None)
    if role_changes(old_role, new_role):
        audit_account_change("account.role_change", target, old={"role": old_role}, new={"role": new_role})
    if old_active is not None and bool(old_active) != bool(getattr(target, "is_active", False)):
        audit_account_change(
            "account.activation_change",
            target,
            old={"is_active": bool(old_active)},
            new={"is_active": bool(getattr(target, "is_active", False))},
        )
        if not getattr(target, "is_active", False):
            end_other_sessions(target)
    if password_set:
        audit_account_change("account.password_set", target, new={"must_change_password": bool(getattr(target, "must_change_password", False))})
        end_other_sessions(target)


def audit_refusal(target: Any, reason: str, *, target_id: int | None = None) -> None:
    """Record a refused change in its own transaction (nothing else is pending at refusal time).

    An account created earlier in the same request disappears with the rollback, so its id is
    not recorded; the sicil is always kept in the row.
    """
    from sqlalchemy import inspect as sa_inspect

    from app.extensions import db
    from app.services.audit_service import write_audit_log

    entity_id = target_id if target_id is not None else getattr(target, "id", None)
    sicil_no = getattr(target, "sicil_no", None) if target is not None else None
    try:
        db.session.rollback()
        state = sa_inspect(target, raiseerr=False) if target is not None and target_id is None else None
        if target is not None and target_id is None and (state is None or not state.persistent):
            entity_id = None
        write_audit_log(
            "account.change_refused",
            "user",
            entity_id,
            new_data={"reason": reason, "sicil_no": sicil_no},
            summary=f"R05 refused: {reason}",
        )
        db.session.commit()
    except SQLAlchemyError:
        logger.exception("BYS360 R05 refusal audit write failed | reason=%s | target=%s", reason, entity_id)
        _safe_rollback()
    logger.warning("BYS360 R05 account change refused | reason=%s | target=%s", reason, entity_id)


def _safe_rollback() -> None:
    from app.extensions import db

    try:
        db.session.rollback()
    except SQLAlchemyError:
        logger.exception("BYS360 R05 rollback failed.")
