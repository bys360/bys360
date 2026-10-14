from __future__ import annotations

import logging

from flask import current_app, request, url_for
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import EvaluationAssignment, FeedbackMeeting, FeedbackRequest, User
from app.services.feedback_service import FEEDBACK_REQUEST_STATUS_LABELS
from app.services.message_service import notify_user
from app.services.performance.common import get_period
from app.services.performance.feedback_audit_service import record_feedback_audit_event
from app.services.performance.feedback_executive_summary_service import SUMMARY_PRESET_LABELS
from app.services.performance.hierarchy import build_manager_chain_for_user
from app.view_helpers import build_surface_scope_context

logger = logging.getLogger(__name__)

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

"""Performans geri bildirim helper ailesi.

Bu modül feedback request, meeting, audit ve görünürlük yardımcılarını
tek noktada toplar. Route gövdelerinin sadece akışa odaklanması için
ortak sorgu ve bildirim mantığı burada tutulur.
"""


def _get_scope_context(scope_value: str | None = None):
    """İstek kapsamını tek yerden çözer."""
    resolved_scope = request.args.get("scope") if scope_value is None else scope_value
    scope_ctx = build_surface_scope_context(current_user, resolved_scope)
    selected_scope = scope_ctx["selected_scope"]
    scope_employee_ids = scope_ctx.get("employee_ids") or [current_user.id]
    return scope_ctx, selected_scope, scope_employee_ids


def _scope_render_kwargs(scope_ctx: dict) -> dict:
    """Template tarafında ortak kullanılan kapsam alanlarını döndürür."""
    return {
        "selected_scope": scope_ctx.get("selected_scope"),
        "scope_options": scope_ctx.get("scope_options"),
        "scope_label": scope_ctx.get("scope_label"),
        "scope_role_title": scope_ctx.get("role_title"),
        "scope_user_count": scope_ctx.get("scope_user_count", 0),
        "scope_unit_count": scope_ctx.get("scope_unit_count", 0),
    }


def _feedback_manager_ids(feedback_request) -> set[int]:
    ids: set[int] = set()
    if not feedback_request:
        return ids
    for manager_id in (
        getattr(feedback_request, "level_1_manager_id", None),
        getattr(feedback_request, "level_2_manager_id", None),
        getattr(feedback_request, "level_3_manager_id", None),
        getattr(feedback_request, "scheduled_by_id", None),
    ):
        try:
            if manager_id is not None:
                ids.add(int(manager_id))
        except (TypeError, ValueError):
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/performance/feedback_helpers.py:70)")
            continue
    return ids


def _request_visible_to_user(feedback_request, user_id: int | None) -> bool:
    """#57: a request reaches its employee and the managers it names (level 1-3); no role widens it."""
    if not feedback_request or user_id is None:
        return False
    return user_id in {
        getattr(feedback_request, "employee_id", None),
        getattr(feedback_request, "level_1_manager_id", None),
        getattr(feedback_request, "level_2_manager_id", None),
        getattr(feedback_request, "level_3_manager_id", None),
    }


def _request_relation_clause(user_id: int | None):
    """SQL form of ``_request_visible_to_user``."""
    uid = int(user_id or 0)
    return or_(
        FeedbackRequest.employee_id == uid,
        FeedbackRequest.level_1_manager_id == uid,
        FeedbackRequest.level_2_manager_id == uid,
        FeedbackRequest.level_3_manager_id == uid,
    )


def _meeting_relation_clause(user_id: int | None):
    """SQL form of ``_meeting_visible_to_user``: parties, or a manager the meeting's request names."""
    uid = int(user_id or 0)
    return or_(
        FeedbackMeeting.employee_id == uid,
        FeedbackMeeting.manager_id == uid,
        FeedbackMeeting.feedback_request.has(
            or_(
                FeedbackRequest.level_1_manager_id == uid,
                FeedbackRequest.level_2_manager_id == uid,
                FeedbackRequest.level_3_manager_id == uid,
                FeedbackRequest.scheduled_by_id == uid,
            )
        ),
    )


def _meeting_visible_to_user(meeting, user_id: int) -> bool:
    if not meeting or user_id is None:
        return False
    if getattr(meeting, "employee_id", None) == user_id:
        return True
    if getattr(meeting, "manager_id", None) == user_id:
        return True
    return user_id in _feedback_manager_ids(getattr(meeting, "feedback_request", None))


def _load_scoped_feedback_data(
    selected_scope: str,
    scope_employee_ids: list[int] | set[int] | tuple[int, ...],
    *,
    meeting_desc: bool = False,
):
    """Kapsam filtresi uygulanmış geri bildirim talep ve görüşme listelerini döndürür."""
    requests_query = FeedbackRequest.query.options(
        joinedload(FeedbackRequest.employee),  # type: ignore[arg-type]
        joinedload(FeedbackRequest.period),  # type: ignore[arg-type]
        joinedload(FeedbackRequest.level_1_manager),  # type: ignore[arg-type]
        joinedload(FeedbackRequest.level_2_manager),  # type: ignore[arg-type]
        joinedload(FeedbackRequest.level_3_manager),  # type: ignore[arg-type]
    )
    meetings_query = FeedbackMeeting.query.options(
        joinedload(FeedbackMeeting.employee),  # type: ignore[arg-type]
        joinedload(FeedbackMeeting.manager),  # type: ignore[arg-type]
        joinedload(FeedbackMeeting.feedback_request).joinedload(FeedbackRequest.period),  # type: ignore[arg-type]
        joinedload(FeedbackMeeting.feedback_request).joinedload(FeedbackRequest.level_1_manager),  # type: ignore[arg-type]
        joinedload(FeedbackMeeting.feedback_request).joinedload(FeedbackRequest.level_2_manager),  # type: ignore[arg-type]
        joinedload(FeedbackMeeting.feedback_request).joinedload(FeedbackRequest.level_3_manager),  # type: ignore[arg-type]
    )

    # #57: every page built on this loader shows only the records the user has a duty relation to;
    # the role scope ("all", "team", unit) can only narrow that set, never widen it.
    requests_query = requests_query.filter(_request_relation_clause(current_user.id))
    meetings_query = meetings_query.filter(_meeting_relation_clause(current_user.id))
    if selected_scope != "mine" and scope_employee_ids:
        requests_query = requests_query.filter(FeedbackRequest.employee_id.in_(scope_employee_ids))
        meetings_query = meetings_query.filter(FeedbackMeeting.employee_id.in_(scope_employee_ids))

    requests_list = requests_query.order_by(FeedbackRequest.requested_at.desc(), FeedbackRequest.id.desc()).all()
    meeting_order = (
        FeedbackMeeting.meeting_date.desc(),
        FeedbackMeeting.meeting_start.desc(),
        FeedbackMeeting.id.desc(),
    ) if meeting_desc else (
        FeedbackMeeting.meeting_date.asc(),
        FeedbackMeeting.meeting_start.asc(),
        FeedbackMeeting.id.desc(),
    )
    meetings = meetings_query.order_by(*meeting_order).all()

    if selected_scope == "mine":
        requests_list = [req for req in requests_list if _request_visible_to_user(req, current_user.id)]
        meetings = [meeting for meeting in meetings if _meeting_visible_to_user(meeting, current_user.id)]

    return requests_list, meetings


def _record_request_alert_audit(
    feedback_request,
    *,
    is_sla: bool,
    sent_count: int,
    actor_user_id: int | None,
    age_days: int,
) -> None:
    record_feedback_audit_event(
        entity_type="feedback_request",
        entity_id=getattr(feedback_request, "id", None),
        action="feedback_request_sla_alert_sent" if is_sla else "feedback_request_alert_sent",
        actor_user_id=actor_user_id,
        summary=f"Talep için {sent_count} kişiye {'SLA uyarısı' if is_sla else 'hatırlatma'} gönderildi ({age_days} gün).",
        new_data={
            "status": getattr(feedback_request, "status", None),
            "sent_count": sent_count,
            "age_days": age_days,
            "alert_type": "sla" if is_sla else "reminder",
        },
    )


def _record_meeting_alert_audit(
    meeting,
    *,
    is_overdue: bool,
    sent_count: int,
    actor_user_id: int | None,
) -> None:
    record_feedback_audit_event(
        entity_type="feedback_meeting",
        entity_id=getattr(meeting, "id", None),
        action="feedback_meeting_overdue_alert_sent" if is_overdue else "feedback_meeting_alert_sent",
        actor_user_id=actor_user_id,
        summary=f"Görüşme için {sent_count} kişiye {'gecikme uyarısı' if is_overdue else 'yaklaşan görüşme hatırlatması'} gönderildi.",
        new_data={
            "status": getattr(meeting, "status", None),
            "sent_count": sent_count,
            "alert_type": "overdue" if is_overdue else "upcoming",
        },
    )


def _record_feedback_digest_audit(
    *,
    source_id: int,
    preset: str,
    actor_user_id: int | None,
    recipient_count: int,
    mail_success_count: int,
) -> None:
    record_feedback_audit_event(
        entity_type="feedback_digest",
        entity_id=source_id,
        action="feedback_digest_sent",
        actor_user_id=actor_user_id,
        summary=f"{SUMMARY_PRESET_LABELS.get(preset, 'Bilinmiyor')} yönetici özeti {recipient_count} alıcı için çalıştırıldı.",
        new_data={
            "preset": preset,
            "recipient_count": recipient_count,
            "mail_success_count": mail_success_count,
        },
    )


def _resolve_feedback_managers(employee, evaluation=None, period_id=None):
    def _is_active_user(user):
        return bool(user is not None and getattr(user, "id", None) and bool(getattr(user, "is_active", True)))

    def _attach(level, manager, managers_by_level):
        try:
            normalized_level = int(level or 0)
        except (TypeError, ValueError):
            return
        if normalized_level not in (1, 2, 3):
            return
        if normalized_level in managers_by_level:
            return
        if not _is_active_user(manager):
            return
        if getattr(manager, "id", None) == getattr(employee, "id", None):
            return
        managers_by_level[normalized_level] = manager

    managers_by_level: dict[int, User] = {}

    for level, manager in (
        (1, getattr(evaluation, "level_1_evaluator", None) if evaluation is not None else None),
        (2, getattr(evaluation, "level_2_evaluator", None) if evaluation is not None else None),
        (3, getattr(evaluation, "level_3_evaluator", None) if evaluation is not None else None),
    ):
        _attach(level, manager, managers_by_level)

    resolved_period_id = period_id or getattr(evaluation, "period_id", None)
    employee_id = getattr(employee, "id", None)

    if resolved_period_id and employee_id and len(managers_by_level) < 3:
        assignments = (
            EvaluationAssignment.query.filter_by(period_id=resolved_period_id, employee_id=employee_id)
            .order_by(EvaluationAssignment.manager_level.asc(), EvaluationAssignment.id.desc())
            .all()
        )
        for assignment in assignments:
            _attach(getattr(assignment, "manager_level", None), getattr(assignment, "evaluator", None), managers_by_level)

    if len(managers_by_level) < 2:
        try:
            authoritative_chain = build_manager_chain_for_user(
                employee=employee,
                period=get_period(resolved_period_id),
            )
        except Exception as exc:
            current_app.logger.warning(
                "Geri bildirim yöneticileri çözümlenirken bağlayıcı zincir üretilemedi | employee_id=%s period_id=%s error=%s",
                employee_id,
                resolved_period_id,
                exc,
            )
            authoritative_chain = None

        if authoritative_chain is not None:
            for level, manager_id in (
                (1, getattr(authoritative_chain, "manager_1_id", None)),
                (2, getattr(authoritative_chain, "manager_2_id", None)),
                (3, getattr(authoritative_chain, "manager_3_id", None) if getattr(authoritative_chain, "level_3_enabled", False) else None),
            ):
                if not manager_id:
                    continue
                manager = db.session.get(User, manager_id)
                _attach(level, manager, managers_by_level)

    for level, sicil_field in (
        (1, "yonetici_sicil"),
        (2, "ikinci_yonetici_sicil"),
        (3, "ucuncu_yonetici_sicil"),
    ):
        if level in managers_by_level:
            continue
        sicil_no = (getattr(employee, sicil_field, None) or "").strip()
        if not sicil_no:
            continue
        manager = User.query.filter_by(sicil_no=sicil_no, is_active=True).first()
        _attach(level, manager, managers_by_level)

    seen_ids: set[int] = set()
    ordered: dict[int, User] = {}
    for level in (1, 2, 3):
        manager = managers_by_level.get(level)
        if not manager:
            continue
        manager_id = getattr(manager, "id", None)
        if not manager_id or manager_id in seen_ids:
            continue
        ordered[level] = manager
        seen_ids.add(int(manager_id))

    if not ordered:
        current_app.logger.warning(
            "Geri bildirim talebi için yönetici çözümlenemedi | employee_id=%s period_id=%s evaluation_id=%s",
            employee_id,
            resolved_period_id,
            getattr(evaluation, "id", None),
        )

    return (ordered.get(1), ordered.get(2), ordered.get(3))


def _serialize_feedback_request_state(feedback_request):
    if not feedback_request:
        return {}
    return {
        "id": getattr(feedback_request, "id", None),
        "status": getattr(feedback_request, "status", None),
        "scheduled_by_id": getattr(feedback_request, "scheduled_by_id", None),
        "scheduled_meeting_id": getattr(feedback_request, "scheduled_meeting_id", None),
        "closed_at": getattr(feedback_request, "closed_at", None),
        "level_1_manager_id": getattr(feedback_request, "level_1_manager_id", None),
        "level_2_manager_id": getattr(feedback_request, "level_2_manager_id", None),
        "level_3_manager_id": getattr(feedback_request, "level_3_manager_id", None),
    }


def _serialize_feedback_meeting_state(meeting):
    if not meeting:
        return {}
    return {
        "id": getattr(meeting, "id", None),
        "status": getattr(meeting, "status", None),
        "meeting_date": getattr(meeting, "meeting_date", None),
        "meeting_start": getattr(meeting, "meeting_start", None),
        "meeting_end": getattr(meeting, "meeting_end", None),
        "meeting_type": getattr(meeting, "meeting_type", None),
        "location": getattr(meeting, "location", None),
        "manager_id": getattr(meeting, "manager_id", None),
        "employee_id": getattr(meeting, "employee_id", None),
        "feedback_request_id": getattr(meeting, "feedback_request_id", None),
    }


def _notify_feedback_request_status_changed(feedback_request, *, actor_user=None):
    if not feedback_request:
        return
    employee_id = getattr(feedback_request, "employee_id", None)
    if not employee_id:
        return
    actor_name = ((getattr(actor_user, "full_name", None) or f"{getattr(actor_user, 'ad', '')} {getattr(actor_user, 'soyad', '')}").strip() or "Yönetici")
    status_value = str(getattr(feedback_request, "status", "") or "")
    status_label = FEEDBACK_REQUEST_STATUS_LABELS.get(status_value, "Güncellendi")
    detail_url = url_for("main.manager_feedback_request_detail", request_id=feedback_request.id, scope="mine")
    notify_user(
        int(employee_id),
        title=f"Geri bildirim talebiniz güncellendi | {status_label}",
        body=f"{actor_name} geri bildirim talebinizi güncelledi. Talep detayını açarak son durumu görebilirsiniz.",
        notification_type="performance_feedback_request",
        source_type="feedback_request",
        source_id=feedback_request.id,
        link_url=detail_url,
        priority="normal",
    )


def _notify_feedback_request_created(feedback_request):
    if not feedback_request:
        return
    employee = getattr(feedback_request, "employee", None)
    employee_name = ((getattr(employee, "full_name", None) or f"{getattr(employee, 'ad', '')} {getattr(employee, 'soyad', '')}").strip() or "Personel")
    detail_url = url_for("main.manager_feedback_request_detail", request_id=feedback_request.id, scope="mine")
    seen_user_ids: set[int] = set()
    for manager in (
        feedback_request.level_1_manager,
        feedback_request.level_2_manager,
        feedback_request.level_3_manager,
    ):
        manager_id = getattr(manager, "id", None)
        if not manager_id or manager_id in seen_user_ids:
            continue
        seen_user_ids.add(int(manager_id))
        notify_user(
            manager_id,
            title="Performans geri bildirim talebi bekliyor",
            body=f"{employee_name} geri bildirim toplantısı talep etti. Talebi inceleyip işlem başlatabilirsiniz.",
            notification_type="performance_feedback_request",
            source_type="feedback_request",
            source_id=feedback_request.id,
            link_url=detail_url,
            priority="warning",
        )


def _notify_feedback_meeting_created(meeting):
    if not meeting:
        return
    employee = getattr(meeting, "employee", None)
    employee_name = ((getattr(employee, "full_name", None) or f"{getattr(employee, 'ad', '')} {getattr(employee, 'soyad', '')}").strip() or "Personel")
    detail_url = url_for("main.feedback_meeting_detail", meeting_id=meeting.id, scope="mine")
    meeting_date = meeting.meeting_date.strftime("%d.%m.%Y") if getattr(meeting, "meeting_date", None) else "-"
    meeting_range = (
        f"{meeting.meeting_start.strftime('%H:%M')} - {meeting.meeting_end.strftime('%H:%M')}"
        if getattr(meeting, "meeting_start", None) and getattr(meeting, "meeting_end", None)
        else "-"
    )

    recipient_ids: set[int] = set()
    employee_id = getattr(employee, "id", None)
    if employee_id:
        recipient_ids.add(int(employee_id))
    manager_ids = _feedback_manager_ids(getattr(meeting, "feedback_request", None))
    if not manager_ids:
        fallback_manager_id = getattr(meeting, "manager_id", None)
        manager_ids = {int(fallback_manager_id)} if fallback_manager_id else set()
    for manager_id in manager_ids:
        recipient_ids.add(manager_id)

    for user_id in sorted(recipient_ids):
        notify_user(
            user_id,
            title="Geri bildirim görüşmesi planlandı",
            body=f"{employee_name} için {meeting_date} {meeting_range} saatinde görüşme planlandı.",
            notification_type="performance_feedback_meeting",
            source_type="feedback_meeting",
            source_id=meeting.id,
            link_url=detail_url,
            priority="normal",
        )


def _notify_feedback_meeting_updated(meeting):
    if not meeting:
        return
    employee = getattr(meeting, "employee", None)
    employee_name = ((getattr(employee, "full_name", None) or f"{getattr(employee, 'ad', '')} {getattr(employee, 'soyad', '')}").strip() or "Personel")
    detail_url = url_for("main.feedback_meeting_detail", meeting_id=meeting.id, scope="mine")
    meeting_date = meeting.meeting_date.strftime("%d.%m.%Y") if getattr(meeting, "meeting_date", None) else "-"
    meeting_range = (
        f"{meeting.meeting_start.strftime('%H:%M')} - {meeting.meeting_end.strftime('%H:%M')}"
        if getattr(meeting, "meeting_start", None) and getattr(meeting, "meeting_end", None)
        else "-"
    )
    status_label_map = {
        "planlandi": "Planlandı",
        "tamamlandi": "Tamamlandı",
        "ertelendi": "Ertelendi",
        "iptal_edildi": "İptal edildi",
    }
    meeting_status_value = str(getattr(meeting, "status", "") or "")
    status_label = status_label_map.get(meeting_status_value, "Güncellendi")

    recipient_ids: set[int] = set()
    employee_id = getattr(employee, "id", None)
    if employee_id:
        recipient_ids.add(int(employee_id))
    manager_ids = _feedback_manager_ids(getattr(meeting, "feedback_request", None))
    if not manager_ids:
        fallback_manager_id = getattr(meeting, "manager_id", None)
        manager_ids = {int(fallback_manager_id)} if fallback_manager_id else set()
    for manager_id in manager_ids:
        recipient_ids.add(manager_id)

    for user_id in sorted(recipient_ids):
        notify_user(
            user_id,
            title=f"Geri bildirim görüşmesi güncellendi | {status_label}",
            body=f"{employee_name} için görüşme kaydı güncellendi. Tarih/Saat: {meeting_date} {meeting_range}.",
            notification_type="performance_feedback_meeting",
            source_type="feedback_meeting",
            source_id=meeting.id,
            link_url=detail_url,
            priority="normal",
        )


def _find_feedback_meeting_conflict(
    *,
    manager_ids,
    employee_id,
    meeting_date,
    meeting_start,
    meeting_end,
    exclude_meeting_id=None,
):
    base_query = FeedbackMeeting.query.filter(
        FeedbackMeeting.meeting_date == meeting_date,
        FeedbackMeeting.status != "iptal_edildi",
        FeedbackMeeting.meeting_start < meeting_end,
        FeedbackMeeting.meeting_end > meeting_start,
    )
    if exclude_meeting_id is not None:
        base_query = base_query.filter(FeedbackMeeting.id != exclude_meeting_id)

    employee_conflict = base_query.filter(FeedbackMeeting.employee_id == employee_id).first()
    if employee_conflict:
        return employee_conflict, "Personelin bu saat aralığında başka bir randevusu var."

    for manager_id in sorted({int(item) for item in manager_ids if item is not None}):
        manager_conflict = base_query.filter(FeedbackMeeting.manager_id == manager_id).first()
        if manager_conflict:
            return manager_conflict, "Bağlı amirlerden en az birinin bu saat aralığında başka bir randevusu var."

    return None, None


__all__ = [
    "_feedback_manager_ids",
    "_find_feedback_meeting_conflict",
    "_get_scope_context",
    "_load_scoped_feedback_data",
    "_meeting_relation_clause",
    "_meeting_visible_to_user",
    "_notify_feedback_meeting_created",
    "_notify_feedback_meeting_updated",
    "_notify_feedback_request_created",
    "_notify_feedback_request_status_changed",
    "_record_feedback_digest_audit",
    "_record_meeting_alert_audit",
    "_record_request_alert_audit",
    "_request_relation_clause",
    "_request_visible_to_user",
    "_resolve_feedback_managers",
    "_scope_render_kwargs",
    "_serialize_feedback_meeting_state",
    "_serialize_feedback_request_state",
]