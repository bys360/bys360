from __future__ import annotations

from typing import Any, cast

from flask_login import current_user

from app import db
from app.models import PerformanceEvaluation, PerformanceEvaluationItem, SupportTicket
from app.route_support import is_manager_family_user

from .guardrails import AIAccessDenied, AIInputError, AIResourceNotFound
from .redaction import redact_payload

_REMOVED_MODULE_MESSAGE = (
    "Bu alan canlı kapsamdan çıkarıldı. Eğitim/İSG, eski Strateji, İç Portal ve Belge-Medya Deposu "
    "modülleri artık AI karar destek sorgu kaynağı olarak kullanılmaz."
)


def _removed_module_payload(*_args: Any, **_kwargs: Any) -> Any:
    raise AIResourceNotFound(_REMOVED_MODULE_MESSAGE)


def get_performance_evaluation_payload(evaluation_id: int) -> tuple[PerformanceEvaluation, dict[str, Any]]:
    evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
    if evaluation is None:
        raise AIResourceNotFound("Performans değerlendirme kaydı bulunamadı.")
    # Local import: app.services.ai_decision imports this module at package import time.
    from app.services.ai_decision.permission_guard import can_view_evaluation

    if not can_view_evaluation(current_user, evaluation):
        raise AIAccessDenied("Bu performans değerlendirmesine erişim yetkiniz bulunmamaktadır.")

    item_rows = []
    item_query = evaluation.items.order_by(  # type: ignore[misc,operator]
        PerformanceEvaluationItem.manager_level.asc(),
        PerformanceEvaluationItem.criteria_id.asc(),
    ) if hasattr(evaluation.items, 'order_by') else evaluation.items
    for item in item_query.all() if hasattr(item_query, 'all') else list(item_query):
        item_rows.append(
            {
                "manager_level": item.manager_level,
                "criteria": getattr(getattr(item, "criteria", None), "title", None) or getattr(getattr(item, "criteria", None), "name", None),
                "score": item.score,
                "score_100": item.score_100,
                "comment": item.comment,
                "justification": item.justification,
            }
        )

    payload = {
        "evaluation_id": evaluation.id,
        "period": getattr(getattr(evaluation, "period", None), "title", None),
        "employee": {
            "id": evaluation.employee_id,
            "full_name": getattr(getattr(evaluation, "employee", None), "full_name", None),
            "sicil_no": getattr(getattr(evaluation, "employee", None), "sicil_no", None),
            "role": getattr(getattr(evaluation, "employee", None), "role", None),
        },
        "workflow_status": getattr(evaluation, 'workflow_status', None),
        "status": evaluation.status,
        "final_total_100": evaluation.final_total_100,
        "level_totals": {
            "level_1": evaluation.level_1_total_100,
            "level_2": evaluation.level_2_total_100,
            "level_3": evaluation.level_3_total_100,
        },
        "general_comments": {
            "level_1": evaluation.level_1_general_comment,
            "level_2": evaluation.level_2_general_comment,
            "level_3": evaluation.level_3_general_comment,
        },
        "published": getattr(evaluation, 'is_published_to_employee', None),
        "items": item_rows,
    }
    return evaluation, redact_payload(payload)


def get_support_ticket_payload(ticket_id: int) -> tuple[SupportTicket, dict[str, Any]]:
    ticket = db.session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise AIResourceNotFound("Destek talebi bulunamadı.")

    can_view = False
    if getattr(current_user, 'is_authenticated', False) and (is_manager_family_user(current_user) or int(getattr(ticket, 'created_by_user_id', 0) or 0) == int(getattr(current_user, 'id', 0) or 0) or int(getattr(ticket, 'assigned_to_user_id', 0) or 0) == int(getattr(current_user, 'id', 0) or 0)):
        can_view = True
    if not can_view:
        raise AIInputError("Bu destek talebi için AI triage görme yetkiniz yok.")

    latest_status_entry = cast("list[Any]", ticket.status_history)[0] if getattr(ticket, 'status_history', None) else None
    visible_messages = []
    for row in list(getattr(ticket, 'messages', []) or [])[-8:]:
        if getattr(row, 'is_internal', False) and not is_manager_family_user(current_user):
            continue
        visible_messages.append({
            'message_type': getattr(row, 'message_type', None),
            'message': getattr(row, 'message', None),
            'is_internal': bool(getattr(row, 'is_internal', False)),
        })

    payload = {
        'ticket_id': ticket.id,
        'ticket_no': ticket.ticket_no,
        'title': ticket.title,
        'description': ticket.description,
        'ticket_type': ticket.ticket_type,
        'module_name': ticket.module_name,
        'page_url': ticket.page_url,
        'priority': ticket.priority,
        'status': ticket.status,
        'category': getattr(getattr(ticket, 'category', None), 'name', None),
        'assigned_to': getattr(getattr(ticket, 'assigned_to', None), 'full_name', None),
        'organization_unit': getattr(getattr(ticket, 'organization_unit', None), 'name', None) or ticket.unit_name_snapshot,
        'attachment_count': len(list(getattr(ticket, 'attachments', []) or [])),
        'message_count': len(list(getattr(ticket, 'messages', []) or [])),
        'latest_status_note': getattr(latest_status_entry, 'note', None),
        'created_at': str(ticket.created_at) if getattr(ticket, 'created_at', None) else None,
        'updated_at': str(ticket.updated_at) if getattr(ticket, 'updated_at', None) else None,
        'recent_messages': visible_messages,
    }
    return ticket, redact_payload(payload)


# Canli kapsamdan cikarilan moduller icin geriye donuk fonksiyon adlari korunur;
# fakat artik veri sorgusu yapmazlar, net ve guvenli sekilde kapali cevap verirler.
def get_strategy_goal_payload(goal_id: int) -> Any:
    return _removed_module_payload(goal_id)


def get_strategy_plan_payload(plan_id: int) -> Any:
    return _removed_module_payload(plan_id)


def get_strategy_action_payload(action_id: int) -> Any:
    return _removed_module_payload(action_id)


def get_strategy_meeting_payload(meeting_id: int) -> Any:
    return _removed_module_payload(meeting_id)


def get_education_record_payload(record_id: int) -> Any:
    return _removed_module_payload(record_id)


def get_education_video_payload(video_id: int) -> Any:
    return _removed_module_payload(video_id)


def get_document_payload(document_id: int) -> Any:
    return _removed_module_payload(document_id)


def get_album_payload(album_id: int) -> Any:
    return _removed_module_payload(album_id)


def get_portal_post_payload(post_id: int) -> Any:
    return _removed_module_payload(post_id)


def get_repository_dashboard_payload() -> dict[str, Any]:
    return {"disabled": True, "message": _REMOVED_MODULE_MESSAGE, "items": []}


def get_portal_feed_payload() -> dict[str, Any]:
    return {"disabled": True, "message": _REMOVED_MODULE_MESSAGE, "items": []}
