from __future__ import annotations

from typing import Any

from sqlalchemy import false, or_, true

from app.route_support import is_admin_family_user
from app.services.personnel_read_grant import has_support_all_grant


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

    K5-Q1: only the user's own explicit grant counts (``has_support_all_grant``); no role
    default, unit profile, role name, ``role_label`` or title. K5-Q3: the same rule for
    /support/*, /communication/faz3/support/* and /api/mobile/support/*.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return has_support_all_grant(user)


def support_ticket_visibility_clause(user: Any) -> Any:
    """K5 (2026-10-10): the SQL form of ``can_view_support_ticket`` for every list and counter.

    Own tickets (created or assigned), or with ``support_all`` every ticket inside the Phase 13B
    private-ticket unit rule. Out-of-scope tickets are filtered in the query, so not even their
    title, number, status, requester or assignee reaches a list, a counter, an export or a report.
    """
    from app.models import SupportTicket

    user_id = int(getattr(user, "id", 0) or 0)
    if not user_id or not getattr(user, "is_authenticated", False):
        return false()
    own = or_(SupportTicket.created_by_user_id == user_id, SupportTicket.assigned_to_user_id == user_id)
    if not can_view_all_support_tickets(user):
        return own
    if is_admin_family_user(user):
        return true()
    units = sorted({str(value) for value in (getattr(user, "birim", None), getattr(user, "ust_birim", None)) if value})
    in_scope = [own, SupportTicket.is_private.is_(False), SupportTicket.is_private.is_(None)]
    if units:
        in_scope.append(SupportTicket.unit_name_snapshot.in_(units))
    return or_(*in_scope)


def can_view_support_ticket(ticket: Any, user: Any) -> bool:
    """K5: the creator and the assignee, or a ``support_all`` holder within the private-ticket rule."""
    user_id = int(getattr(user, "id", 0) or 0)
    if user_id and user_id in {
        int(getattr(ticket, "created_by_user_id", 0) or 0),
        int(getattr(ticket, "assigned_to_user_id", 0) or 0),
    }:
        return True
    return can_view_all_support_tickets(user) and can_view_private_support_ticket(ticket, user)
