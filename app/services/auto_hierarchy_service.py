from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.extensions import db
from app.models import User
from app.services.explicit_manager_chain_service import has_explicit_manager_fields
from app.services.hierarchy_rulebook_service import (
    _norm as _norm_role,
    build_lookup,
    infer_role_from_profile as _infer_role_from_profile,
    is_system_user,
)
from app.services.performance.chain_rule_engine import resolve_authoritative_desired_chain

# --- BYS360 third-manager Excel import compatibility patch ---
THIRD_MANAGER_STANDARD_KEY = "ucuncu_yonetici_sicil"
THIRD_MANAGER_HEADER_ALIASES = [
    "ucuncu_yonetici_sicil",
    "üçüncü yönetici sicil",
    "ucuncu yonetici sicil",
    "3. amir sicil",
    "3 amir sicil",
    "new_y3",
]

try:
    from app.services.personnel_sync_service import canonical_role_label, canonical_role_value
except Exception:  # pragma: no cover
    from app.services.role_display import ROLE_DISPLAY_LABELS, UNKNOWN_ROLE_DISPLAY_LABEL

    def canonical_role_value(raw_role: Any) -> str:
        return str(raw_role or 'personel').strip().lower().replace(' ', '_') or 'personel'

    def canonical_role_label(raw_role: Any) -> str:
        role = canonical_role_value(raw_role)
        return ROLE_DISPLAY_LABELS.get(role, UNKNOWN_ROLE_DISPLAY_LABEL)


# The role spellings infer_role_from_profile maps from the role alone (hierarchy_rulebook_service).
_RECOGNIZED_ROLE_SPELLINGS = frozenset({
    'admin', 'baskan', 'baskan yardimcisi', 'grup baskani', 'mali musavir',
    'koordinator', 'birim sorumlusu', 'personel',
})


@dataclass(slots=True)
class AutoHierarchyResult:
    updated_count: int = 0
    skipped_count: int = 0
    warnings: list[str] | None = None


def infer_role_from_profile(*, raw_role: str | None = None, unvan: str | None = None, birim: str | None = None, ust_birim: str | None = None) -> tuple[str, str]:
    role_value, role_label = _infer_role_from_profile(raw_role=raw_role, unvan=unvan, birim=birim, ust_birim=ust_birim)
    return canonical_role_value(role_value), canonical_role_label(role_value)


def _audit_inferred_role_change(user: User, old_role: Any) -> None:
    from flask import has_request_context

    from app.services.account_change_guard import record_account_changes

    if has_request_context():
        record_account_changes(user, old_role=old_role, old_active=None)


def _is_recognized_role(raw_role: Any) -> bool:
    """A stored role that infer_role_from_profile resolves from the role alone (no title)."""
    return bool(str(raw_role or '').strip()) and _norm_role(raw_role) in _RECOGNIZED_ROLE_SPELLINGS


def auto_apply_manager_chains(
    scope_users: Iterable[User] | None = None,
    *,
    fill_only_missing: bool = True,
    commit: bool = False,
    preserve_explicit_chain: bool = True,
    persist_inferred_roles: bool = False,
) -> dict[str, Any]:
    """Rebuild manager chains.

    R05: with ``persist_inferred_roles=True`` (a real admin) the stored role of a user in
    ``scope_users`` is rewritten only to the canonical spelling of the role it already holds;
    the title, unit or role_label never creates or changes a stored role (an account whose
    title a non-admin edited is not promoted, a technical account is not demoted). Every such
    change is audited. Otherwise the chains are built from the stored roles and no role changes.
    """
    users = User.query.order_by(User.id.asc()).all()
    scope_list = list(scope_users) if scope_users is not None else None
    persist_ids = {getattr(u, 'id', None) for u in scope_list} if scope_list is not None else set()
    normalized_targets = []
    for user in users:
        if persist_inferred_roles and getattr(user, 'id', None) in persist_ids and _is_recognized_role(getattr(user, 'role', None)):
            try:
                role_value, role_label = infer_role_from_profile(raw_role=getattr(user, 'role', None))
                old_role = getattr(user, 'role', None)
                if hasattr(user, 'role') and user.role != role_value:
                    user.role = role_value
                if hasattr(user, 'role_label') and user.role_label != role_label:
                    user.role_label = role_label
                _audit_inferred_role_change(user, old_role)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/auto_hierarchy_service.py")
        normalized_targets.append(user)
    db.session.flush()
    lookup = build_lookup(normalized_targets)
    target_users = scope_list if scope_list is not None else list(lookup.users)

    updated_count = 0
    skipped_count = 0
    warnings: list[str] = []

    for user in target_users:
        if is_system_user(user):
            continue

        if preserve_explicit_chain and has_explicit_manager_fields(user):
            skipped_count += 1
            continue

        # Otomatik yeniden kur akışında preserve_explicit_chain=False ise
        # eski / yanlış 3. amir alanları da temizlenebilmelidir.
        desired = resolve_authoritative_desired_chain(
            user,
            lookup,
            preserve_explicit_level3=preserve_explicit_chain,
            prefer_explicit_chain=preserve_explicit_chain,  # BYS360_EXPLICIT_MANAGER_CHAIN_V2
        )
        current_1 = (getattr(user, 'yonetici_sicil', None) or '').strip() or None
        current_2 = (getattr(user, 'ikinci_yonetici_sicil', None) or '').strip() or None
        current_3 = (getattr(user, 'ucuncu_yonetici_sicil', None) or '').strip() or None

        new_1 = current_1 if (fill_only_missing and current_1) else desired.manager_1_sicil
        new_2 = current_2 if (fill_only_missing and current_2) else desired.manager_2_sicil
        new_3 = current_3 if (fill_only_missing and current_3) else desired.manager_3_sicil

        if (new_1, new_2, new_3) == (current_1, current_2, current_3):
            skipped_count += 1
        else:
            user.yonetici_sicil = new_1
            user.ikinci_yonetici_sicil = new_2
            user.ucuncu_yonetici_sicil = new_3
            updated_count += 1

        display = (getattr(user, 'full_name', None) or f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}").strip() or f"#{getattr(user, 'id', '')}"
        for item in desired.warnings:
            warnings.append(f"{display}: {item}")

    db.session.flush()
    if commit:
        db.session.commit()

    return {
        'updated_count': updated_count,
        'skipped_count': skipped_count,
        'warnings': warnings,
    }