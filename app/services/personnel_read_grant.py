"""Explicit, role-independent grant for institution-wide personnel directory reads.

B1-F1 (approved least-privilege policy, 2026-10-09): no role reads the whole personnel
directory automatically because of its name (ik, personel_yonetimi, performans_yetkilisi
included). A central HR user gets it only through an explicit per-user grant:

- storage: a ``user_menu_permissions`` row with ``menu_key="personnel_read_all"``,
  ``is_visible=True`` and ``source_type="user_override"`` (existing table, no migration);
- assignment: only the existing admin-only per-user matrix on /settings
  (``form_action=save_user_visibility``) for ANOTHER user; it writes a
  ``settings_change_logs`` row. Self-grant is refused. Role defaults and unit profiles
  never store the key; bulk apply, template import and archive apply leave it unchanged;
  reset and rollback can only remove it (rollback rows are ``source_type="rollback"``);
- scope: directory list/read only. It never opens performance data, personnel
  write/delete, personal documents or support tickets.

The reader ignores role, role_label, role defaults and unit profiles, and fails closed.

K5-Q1/K5-Q2 (approved policy, 2026-10-10): the institution-wide support ticket view
(``support_all``) is an explicit grant under the same rules: per person only (never from a
role default or a unit profile), assigned or removed only by the admin role for ANOTHER user
on the per-user matrix, never through self-grant, bulk apply, template import, archive apply
or rollback, and every change writes a ``settings_change_logs`` row. ``EXPLICIT_GRANT_KEYS``
lists the keys that follow these rules.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

PERSONNEL_READ_ALL_KEY = "personnel_read_all"
SUPPORT_ALL_KEY = "support_all"
EXPLICIT_GRANT_KEYS: tuple[str, ...] = (PERSONNEL_READ_ALL_KEY, SUPPORT_ALL_KEY)

# Rendered on /settings only in the per-user matrix, outside the bulk-toggle menu groups.
PERSONNEL_READ_ALL_MENU_ITEM = {
    "key": PERSONNEL_READ_ALL_KEY,
    "label": "Kurum Geneli Personel Rehberi Okuma (personnel.read.all)",
    "icon": "fa-solid fa-address-book",
    "section": "Veri Erişim Yetkileri",
}


def without_explicit_grants(keys: Iterable[Any] | None) -> list[str]:
    """Drop every explicit grant key from role/unit profile key lists (they never carry one)."""
    return [str(key).strip() for key in keys or [] if str(key).strip() and str(key).strip() not in EXPLICIT_GRANT_KEYS]


def _rollback_after_lookup_error(menu_key: str) -> None:
    logger.exception("BYS360 %s grant lookup failed; denying (fail closed).", menu_key)
    from app.extensions import db

    try:
        db.session.rollback()
    except SQLAlchemyError:
        logger.exception("BYS360 %s grant lookup rollback failed.", menu_key)


def has_explicit_grant(user: Any, menu_key: str) -> bool:
    """True only for an active user holding an explicit, visible user_override row for ``menu_key``."""
    user_id = getattr(user, "id", None)
    if menu_key not in EXPLICIT_GRANT_KEYS or user is None or user_id is None or not getattr(user, "is_active", False):
        return False
    try:
        from app.models import UserMenuPermission

        row = UserMenuPermission.query.filter_by(
            user_id=user_id,
            menu_key=menu_key,
            is_visible=True,
            source_type="user_override",
        ).first()
        return row is not None
    except SQLAlchemyError:
        # Fail closed on a database error; any other error propagates (no fail-open path).
        _rollback_after_lookup_error(menu_key)
        return False


def has_personnel_read_all_grant(user: Any) -> bool:
    """True only for an active user holding an explicit, visible user_override grant row."""
    return has_explicit_grant(user, PERSONNEL_READ_ALL_KEY)


def has_support_all_grant(user: Any) -> bool:
    """K5-Q1: the support_all grant, from the user's own explicit override row only."""
    return has_explicit_grant(user, SUPPORT_ALL_KEY)


def explicit_grant_holder_ids(menu_key: str, *, limit: int = 200) -> list[int]:
    """Ids of active users holding an explicit grant row for ``menu_key`` (fails closed)."""
    if menu_key not in EXPLICIT_GRANT_KEYS:
        return []
    try:
        from app.models import User, UserMenuPermission

        rows = (
            UserMenuPermission.query.join(User, User.id == UserMenuPermission.user_id)
            .filter(
                UserMenuPermission.menu_key == menu_key,
                UserMenuPermission.is_visible.is_(True),
                UserMenuPermission.source_type == "user_override",
                User.is_active.is_(True),
            )
            .order_by(UserMenuPermission.user_id.asc())
            .limit(limit)
            .all()
        )
        return [int(row.user_id) for row in rows]
    except SQLAlchemyError:
        _rollback_after_lookup_error(menu_key)
        return []
