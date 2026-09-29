from __future__ import annotations

from typing import Any

from app.route_support import is_admin_family_user


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
