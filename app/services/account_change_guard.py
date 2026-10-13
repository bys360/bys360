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

R05c (owner decisions K1-K5, 2026-10-13) extends the same rules to the access matrices:

- role defaults: a non-admin changes the baseline role only; nobody removes ``admin_users`` /
  ``settings`` from the admin role (K4);
- unit profiles: real admin only (K2);
- per-user matrices: a non-admin never changes its own (K3) nor a protected account's (K1);
- bulk changes skip every protected account, also for a real admin (F3);
- the last active admin is never demoted or deactivated, and an admin never demotes or
  deactivates itself; the check row-locks the active admins (``SELECT ... FOR UPDATE``).

The checks read the stored values only and fail closed.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.route_support import normalize_role_name
from app.services.personnel_read_grant import EXPLICIT_GRANT_KEYS

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"
BASELINE_ROLE = "personel"
# Read only: holders of these explicit grants are protected; this module never writes them.
# One source (S): the explicit grant keys of personnel_read_grant (personnel_read_all, support_all).
PROTECTED_GRANT_KEYS: tuple[str, ...] = tuple(EXPLICIT_GRANT_KEYS)

REFUSAL_MESSAGE = "Bu hesap değişikliği (rol, şifre veya aktiflik) yalnız sistem admini tarafından yapılabilir."
MANAGER_CHAIN_REFUSAL_MESSAGE = (
    "Bu hesabın amir zinciri yalnız sistem admini tarafından değiştirilebilir; kendinizi bir personelin amiri yapamazsınız."
)
ROLE_REFUSAL_MESSAGE = "Rol ataması ve rol değişikliği yalnız sistem admini tarafından yapılabilir."
ADMIN_CONTINUITY_MESSAGE = (
    "Bu işlem yapılmadı: admin kendi admin rolünü düşüremez veya kendi hesabını pasifleştiremez ve "
    "sistemde en az bir aktif admin kalmalıdır."
)


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


def is_protected_role(role: Any) -> bool:
    """Every stored role other than the baseline (admin, leadership, technical, unknown, blank)."""
    return normalize_role_name(role) != BASELINE_ROLE


def is_protected_account(target: Any, actor: Any) -> bool:
    """The accounts a non-admin editor may not take over, switch on/off or re-scope (K1): their
    own, a protected role, or a holder of a visible explicit grant row of any source."""
    if target is None or getattr(target, "id", None) is None:
        return True
    if getattr(actor, "id", None) is not None and getattr(target, "id", None) == getattr(actor, "id", None):
        return True
    if is_protected_role(getattr(target, "role", "")):
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
    # A new account (no target yet) only refuses self-assignment; an existing protected one refuses all.
    if target is not None and is_protected_account(target, actor):
        return False
    actor_sicil = _sicil(getattr(actor, "sicil_no", None))
    return not actor_sicil or actor_sicil in old or actor_sicil not in new


# --------------------------------------------------------------------------------------------
# R05c: menu/access matrices (/settings, assistant matrices, file center) and admin continuity.
# Each check returns None when the change is allowed, otherwise the refusal reason to audit.
# --------------------------------------------------------------------------------------------

class ChangeRefused(Exception):
    """A pre-write authority check refused the change; the caller audits ``reason``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# K4: the admin role profile always keeps these keys, and no other layer hides them from an
# active admin (see effective_menu's lockout floor).
LOCKOUT_CRITICAL_ADMIN_KEYS: tuple[str, ...] = ("admin_users", "settings")


def role_profile_change_refusal(actor: Any, role: Any, *, before: Any, after: Any) -> str | None:
    """Role defaults (R05-1, R05-3, K4): nobody removes a lockout key from the admin role; a
    non-admin changes the baseline role only."""
    before_keys, after_keys = set(before or ()), set(after or ())
    if before_keys == after_keys:
        return None
    is_admin_role = normalize_role_name(role) == ADMIN_ROLE
    if not is_real_admin(actor) and is_protected_role(role):
        return "settings_admin_role_profile" if is_admin_role else "settings_role_profile"
    if is_admin_role and any(key in before_keys and key not in after_keys for key in LOCKOUT_CRITICAL_ADMIN_KEYS):
        return "admin_role_lockout_keys"
    return None


def own_matrix_lockout_refusal(actor: Any, target: Any, *, revoked_keys: Any) -> str | None:
    """K4: an admin never revokes admin_users / settings on its own account (a per-user revocation
    is authoritative over the effective-menu floor, so this is the self-lockout guard)."""
    actor_id = getattr(actor, "id", None)
    if not is_real_admin(actor) or actor_id is None or getattr(target, "id", None) != actor_id:
        return None
    revoked = set(revoked_keys or ())
    return "admin_self_lockout_keys" if any(key in revoked for key in LOCKOUT_CRITICAL_ADMIN_KEYS) else None


def lockout_revocation_refusal(actor: Any, target: Any, *, revoked_keys: Any) -> str | None:
    """K4: revoking admin_users / settings for an active admin never leaves no active admin with
    access to them. Row-locks the active admins, so two admins revoking each other at the same
    time are serialised and the second is refused."""
    if not any(key in set(revoked_keys or ()) for key in LOCKOUT_CRITICAL_ADMIN_KEYS):
        return None
    target_id = getattr(target, "id", None)
    if target_id is None or not (bool(getattr(target, "is_active", False)) and is_real_admin(target)):
        return None
    from app.extensions import db
    from app.models import UserMenuPermission

    others = lock_active_admin_ids() - {int(target_id)}
    if not others:
        return "last_admin_with_access"
    revoked_ids = {
        int(row.user_id)
        for row in db.session.query(UserMenuPermission.user_id).filter(
            UserMenuPermission.user_id.in_(others),
            UserMenuPermission.menu_key.in_(LOCKOUT_CRITICAL_ADMIN_KEYS),
            UserMenuPermission.is_visible.is_(False),
        )
    }
    return None if others - revoked_ids else "last_admin_with_access"


def unit_profile_change_refusal(actor: Any) -> str | None:
    """K2 / N3: unit rows override the role defaults of every member, admins included."""
    return None if is_real_admin(actor) else "settings_unit_profile"


def user_matrix_change_refusal(actor: Any, target: Any) -> str | None:
    """Per-user matrix (R05-2, K1, K3): a non-admin never changes its own matrix nor that of a
    protected account."""
    if is_real_admin(actor):
        return None
    actor_id = getattr(actor, "id", None)
    if target is not None and actor_id is not None and getattr(target, "id", None) == actor_id:
        return "settings_own_matrix"
    return "settings_user_matrix" if is_protected_account(target, actor) else None


def role_membership_change_refusal(actor: Any, *, before: Any, after: Any, reason: str) -> str | None:
    """Settings that list roles (assistant visibility): a non-admin adds or removes the baseline
    role only."""
    if is_real_admin(actor):
        return None
    changed = {normalize_role_name(role) for role in set(before or ()) ^ set(after or ())}
    return reason if any(is_protected_role(role) for role in changed) else None


def split_bulk_targets(actor: Any, targets: Any) -> tuple[list[Any], list[Any]]:
    """F3: a bulk change never touches a protected account, whoever runs it (single-account
    admin edits stay possible and audited)."""
    allowed: list[Any] = []
    skipped: list[Any] = []
    for target in targets or ():
        (skipped if is_protected_account(target, actor) else allowed).append(target)
    return allowed, skipped


def active_admin_lock_statement() -> Any:
    """Every active account whose role may be ``admin``, row-locked in a fixed order.

    PostgreSQL READ COMMITTED: a second transaction blocks here until the first commits, then
    re-checks the WHERE clause on the new row versions, so a just-demoted or deactivated admin
    drops out. The order avoids deadlocks; an inserted admin only adds an admin (safe).
    """
    from sqlalchemy import func, select

    from app.models import User

    return (
        select(User.id, User.role)
        .where(User.is_active.is_(True), func.lower(User.role).contains(ADMIN_ROLE))
        .order_by(User.id)
        .with_for_update()
    )


def lock_active_admin_ids() -> set[int]:
    """Ids of the active real admins, locked until the caller's transaction ends."""
    from app.extensions import db

    rows = db.session.execute(active_admin_lock_statement()).all()
    return {int(row.id) for row in rows if normalize_role_name(row.role) == ADMIN_ROLE}


def admin_continuity_refusal(actor: Any, target: Any, *, new_role: Any, new_active: Any) -> str | None:
    """K4 / R05-5 / C: an admin never demotes or deactivates itself and the last active admin is
    never removed. Call before writing the change, inside the transaction that commits it."""
    if normalize_role_name(new_role) == ADMIN_ROLE and bool(new_active):
        return None
    target_id = getattr(target, "id", None)
    if target_id is None:
        return None
    locked = lock_active_admin_ids()
    if int(target_id) not in locked:
        return None
    if getattr(actor, "id", None) == target_id:
        return "admin_self_demotion"
    if not locked - {int(target_id)}:
        return "last_active_admin"
    return None


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
