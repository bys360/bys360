from __future__ import annotations

from typing import Any

from app.route_support import can_access_menu, is_admin_family_user

SUPPORT_ALL_MENU_KEY = "support_all"


def can_view_private_support_ticket(ticket: Any, user: Any) -> bool:
    """Phase 13B unit scope of a support ticket for everyone but its creator and assignee.

    A private ticket is visible only to the admin family and to users whose unit
    (birim or ust_birim) matches the ticket's unit snapshot; other tickets are not limited.
    Shared by /support/* and /communication/faz3/support/* so both apply the same rule.
    """
    if is_admin_family_user(user):
        return True
    if not bool(getattr(ticket, "is_private", False)):
        return True
    ticket_unit = getattr(ticket, "unit_name_snapshot", None)
    if not ticket_unit:
        return False
    return ticket_unit in {getattr(user, "birim", None), getattr(user, "ust_birim", None)}


def can_view_all_support_tickets(user: Any) -> bool:
    """K5 (approved policy, 2026-10-10): the institution-wide support view is ``support_all``.

    The permission as Settings resolves it (role matrix, unit profile, per-user override), the
    same rule for /support/* and /api/mobile/support/*. No role-name shortcut: the technical
    roles, ``role_label`` and the title grant nothing on their own.
    """
    return can_access_menu(user, SUPPORT_ALL_MENU_KEY)


def can_view_support_ticket(ticket: Any, user: Any) -> bool:
    """K5: the creator and the assignee, or a ``support_all`` holder within the private-ticket rule."""
    user_id = int(getattr(user, "id", 0) or 0)
    if user_id and user_id in {
        int(getattr(ticket, "created_by_user_id", 0) or 0),
        int(getattr(ticket, "assigned_to_user_id", 0) or 0),
    }:
        return True
    return can_view_all_support_tickets(user) and can_view_private_support_ticket(ticket, user)
