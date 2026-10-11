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
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

PERSONNEL_READ_ALL_KEY = "personnel_read_all"

# Rendered on /settings only in the per-user matrix, outside the bulk-toggle menu groups.
PERSONNEL_READ_ALL_MENU_ITEM = {
    "key": PERSONNEL_READ_ALL_KEY,
    "label": "Kurum Geneli Personel Rehberi Okuma (personnel.read.all)",
    "icon": "fa-solid fa-address-book",
    "section": "Veri Erişim Yetkileri",
}


def without_personnel_read_all(keys: Iterable[Any] | None) -> list[str]:
    """Drop the grant key from role/unit profile key lists (they never carry it)."""
    return [str(key).strip() for key in keys or [] if str(key).strip() and str(key).strip() != PERSONNEL_READ_ALL_KEY]


def has_personnel_read_all_grant(user: Any) -> bool:
    """True only for an active user holding an explicit, visible user_override grant row."""
    user_id = getattr(user, "id", None)
    if user is None or user_id is None or not getattr(user, "is_active", False):
        return False
    try:
        from app.models import UserMenuPermission

        row = UserMenuPermission.query.filter_by(
            user_id=user_id,
            menu_key=PERSONNEL_READ_ALL_KEY,
            is_visible=True,
            source_type="user_override",
        ).first()
        return row is not None
    except SQLAlchemyError:
        # Fail closed on a database error; any other error propagates (no fail-open path).
        logger.exception("BYS360 personnel_read_all grant lookup failed; denying (fail closed).")
        from app.extensions import db

        try:
            db.session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 personnel_read_all grant lookup rollback failed.")
        return False
