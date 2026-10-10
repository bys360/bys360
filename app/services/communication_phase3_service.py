from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import inspect, or_

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    Notification,
    SupportHelpArticle,
    SupportTicket,
    SupportTicketMessage,
    SupportTicketStatusHistory,
    Survey,
    SurveyAnswer,
    SurveyAssignment,
    SurveyQuestion,
    SurveyResponse,
    User,
)
from app.models.communication_phase3_models import (
    CommunicationHelpArticleViewLog,
    CommunicationSupportAssignmentLog,
    CommunicationSupportSlaPolicy,
    CommunicationSurveyReminderLog,
)
from app.services.communication_phase2_service import SURVEY_STATUS_LABELS
from app.services.support_ticket_access import (
    can_view_all_support_tickets,
    can_view_support_ticket,
    support_ticket_visibility_clause,
)

logger = logging.getLogger(__name__)

MANAGER_ROLES = {
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "birim_sorumlusu",
}

SURVEY_QUESTION_TYPE_LABELS = {
    "single_choice": "Tek seçim",
    "multi_choice": "Çoklu seçim",
    "text": "Açık uçlu",
    "yes_no": "Evet / Hayır",
    "score": "Puan",
    "likert": "Likert",
}

SUPPORT_STATUS_LABELS = {
    "open": "Açıldı",
    "reviewing": "İnceleniyor",
    "waiting_info": "Bilgi Bekleniyor",
    "assigned": "Atandı",
    "planned": "Geliştirme Planına Alındı",
    "resolved": "Çözüldü",
    "closed": "Kapatıldı",
    "rejected": "Reddedildi",
}

NOTIFICATION_TYPE_LABELS = {
    "system": "Sistem",
    "message": "Mesaj",
    "support": "Destek",
    "survey": "Anket",
    "announcement": "Duyuru",
    "portal": "Portal",
}

DEFAULT_SLA_POLICY = {
    "low": {"first_response_target_hours": 48, "resolution_target_hours": 120},
    "normal": {"first_response_target_hours": 24, "resolution_target_hours": 72},
    "high": {"first_response_target_hours": 8, "resolution_target_hours": 48},
    "critical": {"first_response_target_hours": 4, "resolution_target_hours": 24},
}


class CommunicationPhase3Error(RuntimeError):
    pass


def support_help_articles_table_ready() -> bool:
    try:
        return inspect(db.engine).has_table("support_help_articles")
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase3_service.py | line=87")
        return False


def _now() -> datetime:
    return utc_now()


def safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return safe_str(value).lower() in {"1", "true", "on", "yes", "evet"}


def user_role_slug(user: Any) -> str:
    return safe_str(getattr(user, "role", "")).lower()


def is_manager(user: Any) -> bool:
    return user_role_slug(user) in MANAGER_ROLES


def _active_user_query():
    query = User.query
    if hasattr(User, "is_active"):
        query = query.filter(User.is_active.is_(True))
    return query


def user_display_name(user: Any) -> str:
    if not user:
        return "-"
    for attr in ("full_name", "full_name_cache"):
        value = safe_str(getattr(user, attr, ""))
        if value:
            return value
    ad = safe_str(getattr(user, "ad", ""))
    soyad = safe_str(getattr(user, "soyad", ""))
    merged = f"{ad} {soyad}".strip()
    return merged or safe_str(getattr(user, "email", "")) or "-"


def _user_matches_assignment(user: Any, assignment: Any) -> bool:
    target_type = safe_str(getattr(assignment, "target_type", "")).lower()
    target_value = safe_str(getattr(assignment, "target_value", ""))

    if target_type in {"", "all"}:
        return True
    if target_type == "user":
        return str(getattr(user, "id", "")) == target_value
    if target_type == "role":
        return safe_str(getattr(user, "role", "")).lower() == target_value.lower()
    if target_type == "unit":
        if target_value.isdigit() and hasattr(user, "organization_unit_id"):
            return int(getattr(user, "organization_unit_id", 0) or 0) == int(target_value)
        return safe_str(getattr(user, "birim", "")).lower() == target_value.lower()
    return False


def _survey_is_open(survey: Any) -> bool:
    now = _now()
    start_at = getattr(survey, "start_at", None)
    end_at = getattr(survey, "end_at", None)
    if safe_str(getattr(survey, "status", "")) != "published":
        return False
    if start_at and start_at > now:
        return False
    return not (end_at and end_at < now)


def _find_matching_assignment(survey: Any, user: Any):
    assignments = survey.assignments.order_by(SurveyAssignment.id.asc()).all()
    for assignment in assignments:
        if _user_matches_assignment(user, assignment):
            return assignment
    return None


def _find_user_response(survey: Any, user: Any, assignment: Any | None = None):
    query = SurveyResponse.query.filter_by(survey_id=survey.id)
    if getattr(survey, "is_anonymous", False):
        token = f"anon-user-{getattr(user, 'id', 0)}"
        response = query.filter_by(anonymous_token=token).order_by(SurveyResponse.id.desc()).first()
        if response:
            return response
        if assignment is not None:
            return query.filter_by(assignment_id=getattr(assignment, "id", None)).order_by(SurveyResponse.id.desc()).first()
        return None
    return query.filter_by(user_id=user.id).order_by(SurveyResponse.id.desc()).first()


def _serialize_notification(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": safe_str(getattr(row, "title", "")) or "Bildirim",
        "body": safe_str(getattr(row, "body", "")),
        "notification_type": safe_str(getattr(row, "notification_type", "")) or "system",
        "notification_type_label": NOTIFICATION_TYPE_LABELS.get(safe_str(getattr(row, "notification_type", "")), "Genel"),
        "priority": safe_str(getattr(row, "priority", "")) or "normal",
        "is_read": bool(getattr(row, "is_read", False)),
        "link_url": safe_str(getattr(row, "link_url", "")),
        "source_type": safe_str(getattr(row, "source_type", "")),
        "created_at": getattr(row, "created_at", None),
    }


def notification_center_snapshot(user: Any, filter_name: str = "all", limit: int = 200) -> dict[str, Any]:
    query = Notification.query.filter_by(user_id=user.id)
    if filter_name == "unread":
        query = query.filter(Notification.is_read.is_(False))
    elif filter_name not in {"all", ""}:
        query = query.filter(Notification.notification_type == filter_name)

    rows = query.order_by(Notification.is_read.asc(), Notification.created_at.desc()).limit(limit).all()
    all_rows = Notification.query.filter_by(user_id=user.id).all()

    summary: Counter[str] = Counter()
    for row in all_rows:
        summary["all"] += 1
        if not getattr(row, "is_read", False):
            summary["unread"] += 1
        summary[safe_str(getattr(row, "notification_type", "")) or "system"] += 1

    return {
        "rows": [_serialize_notification(row) for row in rows],
        "summary": {
            "all": summary.get("all", 0),
            "unread": summary.get("unread", 0),
            "system": summary.get("system", 0),
            "message": summary.get("message", 0),
            "support": summary.get("support", 0),
            "survey": summary.get("survey", 0),
            "announcement": summary.get("announcement", 0),
            "portal": summary.get("portal", 0),
        },
        "filter_name": filter_name,
    }


def mark_all_notifications_read(user_id: int) -> int:
    rows = Notification.query.filter_by(user_id=user_id, is_read=False).all()
    now = _now()
    for row in rows:
        row.is_read = True
        row.read_at = now
        db.session.add(row)
    db.session.commit()
    return len(rows)


def _serialize_survey_card(survey: Any, user: Any) -> dict[str, Any]:
    assignment = _find_matching_assignment(survey, user)
    response = _find_user_response(survey, user, assignment)
    pending = not bool(response and getattr(response, "is_completed", False))
    return {
        "survey": survey,
        "assignment": assignment,
        "response": response,
        "question_count": survey.questions.count() if hasattr(survey.questions, "count") else len(list(survey.questions)),
        "is_open": _survey_is_open(survey),
        "pending": pending,
        "completed": bool(response and getattr(response, "is_completed", False)),
    }


def survey_center_for_user(user: Any, filter_name: str = "all") -> dict[str, Any]:
    all_rows = []
    open_count = 0
    completed_count = 0

    for survey in Survey.query.order_by(Survey.created_at.desc()).all():
        assignment = _find_matching_assignment(survey, user)
        if not assignment:
            continue
        payload = _serialize_survey_card(survey, user)
        all_rows.append(payload)
        if payload["completed"]:
            completed_count += 1
        elif payload["is_open"]:
            open_count += 1

    def _matches(row: dict[str, Any]) -> bool:
        if filter_name in {"", "all"}:
            return True
        if filter_name == "open":
            return bool(row["is_open"])
        if filter_name == "pending":
            return (not row["completed"]) and bool(row["is_open"])
        if filter_name == "completed":
            return bool(row["completed"])
        if filter_name == "closed":
            return not bool(row["is_open"]) and not bool(row["completed"])
        return True

    rows = [row for row in all_rows if _matches(row)]

    return {
        "rows": rows,
        "summary": {
            "all": len(all_rows),
            "open": open_count,
            "completed": completed_count,
            "pending": max(len(all_rows) - completed_count, 0),
        },
        "question_type_labels": SURVEY_QUESTION_TYPE_LABELS,
        "filter_name": filter_name or "all",
    }


def get_survey_for_user(survey_id: int, user: Any) -> dict[str, Any]:
    survey = Survey.query.get_or_404(survey_id)
    assignment = _find_matching_assignment(survey, user)
    if not assignment:
        raise CommunicationPhase3Error("Bu anket size atanmış görünmüyor.")

    response = _find_user_response(survey, user, assignment)
    questions = survey.questions.order_by(SurveyQuestion.sort_order.asc(), SurveyQuestion.id.asc()).all()
    answers_map: dict[int, list[Any]] = {}
    if response:
        for answer in response.answers.all():
            answers_map.setdefault(int(answer.question_id), []).append(answer)

    return {
        "survey": survey,
        "assignment": assignment,
        "response": response,
        "questions": questions,
        "answers_map": answers_map,
        "is_open": _survey_is_open(survey),
        "question_type_labels": SURVEY_QUESTION_TYPE_LABELS,
        "status_labels": SURVEY_STATUS_LABELS,
    }


def _ensure_response_for_user(survey: Any, user: Any, assignment: Any):
    response = _find_user_response(survey, user, assignment)
    if response and not getattr(survey, "allow_multiple_submissions", False):
        return response

    response = SurveyResponse(
        survey_id=survey.id,
        assignment_id=getattr(assignment, "id", None),
        user_id=None if getattr(survey, "is_anonymous", False) else user.id,
        anonymous_token=(f"anon-user-{user.id}" if getattr(survey, "is_anonymous", False) else None),
        is_completed=False,
    )
    db.session.add(response)
    db.session.flush()
    return response


def _upsert_answer(response: Any, question: Any, *, selected_option_id: int | None = None, answer_text: str | None = None, answer_number: float | None = None):
    answer = SurveyAnswer(
        response_id=response.id,
        question_id=question.id,
        selected_option_id=selected_option_id,
        answer_text=answer_text,
        answer_number=answer_number,
    )
    db.session.add(answer)
    return answer


def save_or_submit_survey(survey_id: int, user: Any, form_data: Any, complete: bool = False) -> Any:
    payload = get_survey_for_user(survey_id, user)
    survey = payload["survey"]
    assignment = payload["assignment"]

    if not _survey_is_open(survey):
        raise CommunicationPhase3Error("Anket şu an yanıtlamaya açık değil.")

    response = _ensure_response_for_user(survey, user, assignment)

    # Mevcut cevapları temizle ve formdan yeniden yaz.
    for old in response.answers.all():
        db.session.delete(old)
    db.session.flush()

    missing_required: list[str] = []

    for question in payload["questions"]:
        qid = int(question.id)
        qtype = safe_str(getattr(question, "question_type", "")).lower()
        required = bool(getattr(question, "is_required", False))

        text_key = f"q_{qid}_text"
        single_key = f"q_{qid}_single"
        number_key = f"q_{qid}_number"
        multi_key = f"q_{qid}_multi"

        if qtype in {"text"}:
            value = safe_str(form_data.get(text_key))
            if value:
                _upsert_answer(response, question, answer_text=value)
            elif required and complete:
                missing_required.append(question.question_text)

        elif qtype in {"single_choice", "yes_no", "likert"}:
            value = safe_str(form_data.get(single_key))
            if value:
                _upsert_answer(response, question, selected_option_id=int(value) if value.isdigit() else None, answer_text=None)
            elif required and complete:
                missing_required.append(question.question_text)

        elif qtype in {"score"}:
            raw = safe_str(form_data.get(number_key))
            if raw:
                try:
                    number = float(raw)
                except ValueError:
                    raise CommunicationPhase3Error(f"'{question.question_text}' için sayısal değer giriniz.") from None
                _upsert_answer(response, question, answer_number=number)
            elif required and complete:
                missing_required.append(question.question_text)

        elif qtype in {"multi_choice"}:
            values = form_data.getlist(multi_key) if hasattr(form_data, "getlist") else []
            values = [safe_str(item) for item in values if safe_str(item)]
            if values:
                for value in values:
                    _upsert_answer(response, question, selected_option_id=int(value) if value.isdigit() else None)
            elif required and complete:
                missing_required.append(question.question_text)

        else:
            value = safe_str(form_data.get(text_key) or form_data.get(single_key))
            if value:
                _upsert_answer(response, question, answer_text=value)
            elif required and complete:
                missing_required.append(question.question_text)

    if missing_required:
        raise CommunicationPhase3Error(
            "Zorunlu sorular eksik: " + ", ".join(missing_required[:5])
        )

    response.is_completed = bool(complete)
    response.submitted_at = _now() if complete else None

    if complete:
        row = Notification(
            user_id=user.id,
            title=f"Anket tamamlandı: {survey.title}",
            body="Yanıtınız başarıyla kaydedildi.",
            notification_type="survey",
            source_type="survey",
            source_id=survey.id,
            link_url=f"/communication/faz3/surveys/{survey.id}/take",
            priority="normal",
            is_read=False,
        )
        db.session.add(row)

    db.session.add(response)
    db.session.commit()
    return response


def reminder_candidates_for_survey(survey_id: int) -> list[dict[str, Any]]:
    survey = Survey.query.get_or_404(survey_id)
    rows = []
    for user in _active_user_query().all():
        assignment = _find_matching_assignment(survey, user)
        if not assignment:
            continue
        response = _find_user_response(survey, user, assignment)
        if response and response.is_completed:
            continue
        rows.append({
            "user": user,
            "assignment": assignment,
            "response": response,
        })
    return rows


def _recent_survey_reminder_exists(survey_id: int, user_id: int, hours: int = 24) -> bool:
    threshold = _now() - timedelta(hours=hours)
    row = (
        CommunicationSurveyReminderLog.query
        .filter(
            CommunicationSurveyReminderLog.survey_id == survey_id,
            CommunicationSurveyReminderLog.user_id == user_id,
            CommunicationSurveyReminderLog.sent_at >= threshold,
        )
        .order_by(CommunicationSurveyReminderLog.sent_at.desc())
        .first()
    )
    return row is not None


def create_survey_reminders(survey_id: int, actor_user_id: int, note: str = "") -> dict[str, Any]:
    survey = Survey.query.get_or_404(survey_id)
    candidates = reminder_candidates_for_survey(survey_id)
    created = 0
    skipped_recent = 0
    for row in candidates:
        user = row["user"]
        assignment = row["assignment"]
        if _recent_survey_reminder_exists(survey.id, user.id, hours=24):
            skipped_recent += 1
            continue
        db.session.add(
            CommunicationSurveyReminderLog(
                survey_id=survey.id,
                user_id=user.id,
                assignment_id=getattr(assignment, "id", None),
                reminder_type="in_app",
                note=note or None,
            )
        )
        db.session.add(
            Notification(
                user_id=user.id,
                title=f"Anket hatırlatması: {survey.title}",
                body="Henüz tamamlamadığınız anket için hatırlatma gönderildi.",
                notification_type="survey",
                source_type="survey",
                source_id=survey.id,
                link_url=f"/communication/faz3/surveys/{survey.id}/take",
                priority="normal",
                is_read=False,
            )
        )
        created += 1
    db.session.commit()
    return {"survey": survey, "created": created, "skipped_recent": skipped_recent, "actor_user_id": actor_user_id}


def _load_sla_policy(ticket: Any) -> dict[str, int]:
    module_name = safe_str(getattr(ticket, "module_name", "")) or "genel"
    priority = safe_str(getattr(ticket, "priority", "")).lower() or "normal"
    row = CommunicationSupportSlaPolicy.query.filter_by(
        module_name=module_name,
        priority=priority,
        is_active=True,
    ).first()
    if row:
        return {
            "first_response_target_hours": int(getattr(row, "first_response_target_hours", 24) or 24),
            "resolution_target_hours": int(getattr(row, "resolution_target_hours", 72) or 72),
        }
    defaults = DEFAULT_SLA_POLICY.get(priority, DEFAULT_SLA_POLICY["normal"])
    return {
        "first_response_target_hours": int(defaults["first_response_target_hours"]),
        "resolution_target_hours": int(defaults["resolution_target_hours"]),
    }


def _sla_snapshot_for_ticket(ticket: Any) -> dict[str, Any]:
    created_at = getattr(ticket, "created_at", None) or _now()
    # "messages" is a plain list relationship ordered by created_at, not a dynamic query.
    first_message = next((row for row in (ticket.messages or []) if not getattr(row, "is_internal", False)), None)
    first_response_at = getattr(first_message, "created_at", None)
    resolved_at = getattr(ticket, "closed_at", None)
    now = _now()
    policy = _load_sla_policy(ticket)

    first_deadline = created_at + timedelta(hours=policy["first_response_target_hours"])
    resolve_deadline = created_at + timedelta(hours=policy["resolution_target_hours"])

    first_ok = bool(first_response_at and first_response_at <= first_deadline)
    if not first_response_at:
        first_state = "risk" if now > first_deadline else "tracking"
    else:
        first_state = "ok" if first_ok else "late"

    if safe_str(getattr(ticket, "status", "")) in {"resolved", "closed"}:
        resolution_state = "ok" if resolved_at and resolved_at <= resolve_deadline else "late"
    else:
        resolution_state = "risk" if now > resolve_deadline else "tracking"

    return {
        "policy": policy,
        "first_deadline": first_deadline,
        "resolve_deadline": resolve_deadline,
        "first_response_at": first_response_at,
        "resolution_state": resolution_state,
        "first_state": first_state,
    }


def support_queue_snapshot(user: Any, filter_name: str = "all") -> dict[str, Any]:
    query = SupportTicket.query.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
    # K5-Q3: the queue follows the central rule (own tickets, or support_all inside the
    # private-ticket unit rule); out-of-scope tickets never reach the rows or the counts.
    query = query.filter(support_ticket_visibility_clause(user))

    if filter_name == "open":
        query = query.filter(SupportTicket.status.in_(["open", "reviewing", "waiting_info", "assigned", "planned"]))
    elif filter_name == "closed":
        query = query.filter(SupportTicket.status.in_(["resolved", "closed", "rejected"]))
    elif filter_name == "mine":
        query = query.filter(SupportTicket.assigned_to_user_id == user.id)

    rows = query.all()
    counts: Counter[str] = Counter()
    for row in rows:
        counts["all"] += 1
        counts[safe_str(getattr(row, "status", "")) or "open"] += 1

    payload_rows = []
    for row in rows:
        payload_rows.append({
            "ticket": row,
            "sla": _sla_snapshot_for_ticket(row),
            "status_label": SUPPORT_STATUS_LABELS.get(safe_str(getattr(row, "status", "")), "-"),
            "creator_name": user_display_name(getattr(row, "created_by", None)),
            "assignee_name": user_display_name(getattr(row, "assigned_to", None)),
        })

    return {
        "rows": payload_rows,
        "counts": counts,
        "filter_name": filter_name,
        "status_labels": SUPPORT_STATUS_LABELS,
    }


def _can_access_ticket(ticket: Any, user: Any) -> bool:
    # K5-Q3: the same central rule as /support/* and the mobile API (creator, assignee, or
    # support_all within the Phase 13B private-ticket rule).
    return can_view_support_ticket(ticket, user)


def support_detail_payload(ticket_id: int, user: Any) -> dict[str, Any]:
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if not _can_access_ticket(ticket, user):
        raise CommunicationPhase3Error("Bu talebi görüntüleme yetkiniz yok.")

    users = []
    can_manage = can_view_all_support_tickets(user)
    if can_manage:
        users = _active_user_query().order_by(User.ad.asc(), User.soyad.asc()).all()

    return {
        "ticket": ticket,
        "sla": _sla_snapshot_for_ticket(ticket),
        "status_labels": SUPPORT_STATUS_LABELS,
        "can_manage": can_manage,
        "assignable_users": users,
    }


def assign_support_ticket(
    ticket_id: int,
    assignee_user_id: int | None,
    actor_user_id: int,
    note: str = "",
    *,
    actor_user: Any = None,
) -> Any:
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if actor_user is not None and not _can_access_ticket(ticket, actor_user):
        raise CommunicationPhase3Error("Bu talebi yönetme yetkiniz yok.")
    old_user_id = getattr(ticket, "assigned_to_user_id", None)
    ticket.assigned_to_user_id = assignee_user_id
    old_status = safe_str(getattr(ticket, "status", "")) or "open"
    ticket.status = "assigned" if assignee_user_id else "reviewing"
    db.session.add(ticket)

    db.session.add(
        SupportTicketStatusHistory(
            ticket_id=ticket.id,
            old_status=old_status,
            new_status=ticket.status,
            changed_by_user_id=actor_user_id,
            note=note or "Atama güncellendi.",
        )
    )
    db.session.add(
        CommunicationSupportAssignmentLog(
            ticket_id=ticket.id,
            old_assigned_to_user_id=old_user_id,
            new_assigned_to_user_id=assignee_user_id,
            assigned_by_user_id=actor_user_id,
            note=note or None,
        )
    )

    notify_ids = {int(getattr(ticket, "created_by_user_id", 0) or 0)}
    if assignee_user_id:
        notify_ids.add(int(assignee_user_id))
    notify_ids.discard(0)
    notify_ids.discard(int(actor_user_id or 0))

    for user_id in notify_ids:
        db.session.add(
            Notification(
                user_id=user_id,
                title=f"Destek talebi ataması güncellendi: {ticket.ticket_no}",
                body=ticket.title,
                notification_type="support",
                source_type="support_ticket",
                source_id=ticket.id,
                link_url=f"/communication/faz3/support/{ticket.id}",
                priority=safe_str(getattr(ticket, "priority", "")) or "normal",
                is_read=False,
            )
        )

    db.session.commit()
    return ticket


def update_support_status(
    ticket_id: int,
    new_status: str,
    actor_user_id: int,
    note: str = "",
    *,
    actor_user: Any = None,
) -> Any:
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if actor_user is not None and not _can_access_ticket(ticket, actor_user):
        raise CommunicationPhase3Error("Bu talebi yönetme yetkiniz yok.")
    new_status = safe_str(new_status).lower()
    if new_status not in SUPPORT_STATUS_LABELS:
        raise CommunicationPhase3Error("Geçersiz destek talebi durumu.")

    old_status = safe_str(getattr(ticket, "status", "")) or "open"
    ticket.status = new_status
    if new_status in {"resolved", "closed"} and not getattr(ticket, "closed_at", None):
        ticket.closed_at = _now()
    db.session.add(ticket)
    db.session.add(
        SupportTicketStatusHistory(
            ticket_id=ticket.id,
            old_status=old_status,
            new_status=new_status,
            changed_by_user_id=actor_user_id,
            note=note or None,
        )
    )

    notify_ids = {
        int(getattr(ticket, "created_by_user_id", 0) or 0),
        int(getattr(ticket, "assigned_to_user_id", 0) or 0),
    }
    notify_ids.discard(0)
    notify_ids.discard(int(actor_user_id or 0))
    for user_id in notify_ids:
        db.session.add(
            Notification(
                user_id=user_id,
                title=f"Destek talebi durumu güncellendi: {ticket.ticket_no}",
                body=SUPPORT_STATUS_LABELS.get(new_status, "Bilinmiyor"),
                notification_type="support",
                source_type="support_ticket",
                source_id=ticket.id,
                link_url=f"/communication/faz3/support/{ticket.id}",
                priority=safe_str(getattr(ticket, "priority", "")) or "normal",
                is_read=False,
            )
        )

    db.session.commit()
    return ticket


def add_support_message(ticket_id: int, actor_user: Any, message: str, is_internal: bool = False) -> Any:
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if not _can_access_ticket(ticket, actor_user):
        raise CommunicationPhase3Error("Bu talebe mesaj yazma yetkiniz yok.")
    clean_message = safe_str(message)
    if not clean_message:
        raise CommunicationPhase3Error("Mesaj boş bırakılamaz.")

    row = SupportTicketMessage(
        ticket_id=ticket.id,
        user_id=actor_user.id,
        message=clean_message,
        is_internal=bool(is_internal),
        message_type="internal_note" if is_internal else "comment",
    )
    db.session.add(row)

    notify_ids = {
        int(getattr(ticket, "created_by_user_id", 0) or 0),
        int(getattr(ticket, "assigned_to_user_id", 0) or 0),
    }
    notify_ids.discard(0)
    notify_ids.discard(int(getattr(actor_user, "id", 0) or 0))

    for user_id in notify_ids:
        db.session.add(
            Notification(
                user_id=user_id,
                title=f"Destek talebinde yeni mesaj: {ticket.ticket_no}",
                body=ticket.title,
                notification_type="support",
                source_type="support_ticket",
                source_id=ticket.id,
                link_url=f"/communication/faz3/support/{ticket.id}",
                priority=safe_str(getattr(ticket, "priority", "")) or "normal",
                is_read=False,
            )
        )

    db.session.commit()
    return row


def help_center_snapshot(user: Any, query_text: str = "", category_slug: str = "") -> dict[str, Any]:
    if not support_help_articles_table_ready():
        return {
            "rows": [],
            "query_text": safe_str(query_text),
            "category_slug": category_slug,
            "categories": Counter(),
            "featured": [],
            "table_missing": True,
        }

    query = SupportHelpArticle.query.filter(SupportHelpArticle.is_published.is_(True))
    q = safe_str(query_text)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                SupportHelpArticle.title.ilike(like),
                SupportHelpArticle.summary.ilike(like),
                SupportHelpArticle.tags_text.ilike(like),
                SupportHelpArticle.content_text.ilike(like),
            )
        )
    if category_slug:
        query = query.filter(SupportHelpArticle.category_slug == category_slug)

    role_slug = user_role_slug(user)
    rows = []
    for article in query.order_by(SupportHelpArticle.is_featured.desc(), SupportHelpArticle.sort_order.asc(), SupportHelpArticle.title.asc()).all():
        article_roles = getattr(article, "role_slugs", []) or []
        if article_roles and role_slug not in article_roles and role_slug not in {"admin", "baskan", "grup_baskani", "mali_musavir", "birim_sorumlusu"}:
            continue
        rows.append(article)

    categories = Counter(safe_str(getattr(row, "category_slug", "genel")) or "genel" for row in rows)
    return {
        "rows": rows,
        "query_text": q,
        "category_slug": category_slug,
        "categories": categories,
        "featured": [row for row in rows if getattr(row, "is_featured", False)],
    }


def help_article_detail(slug: str, user: Any, search_term: str = "") -> dict[str, Any]:
    if not support_help_articles_table_ready():
        raise CommunicationPhase3Error("Bilgi bankası tabloları henüz kurulmamış.")

    article = SupportHelpArticle.query.filter_by(slug=slug, is_published=True).first()
    if not article:
        raise CommunicationPhase3Error("Bilgi bankası kaydı bulunamadı.")

    db.session.add(
        CommunicationHelpArticleViewLog(
            article_id=article.id,
            user_id=getattr(user, "id", None),
            search_term=safe_str(search_term) or None,
        )
    )
    db.session.commit()

    related_rows = []
    for related_slug in getattr(article, "related_slugs", []) or []:
        related = SupportHelpArticle.query.filter_by(slug=related_slug, is_published=True).first()
        if related:
            related_rows.append(related)

    recent_views = CommunicationHelpArticleViewLog.query.filter_by(article_id=article.id).count()
    return {
        "article": article,
        "related_rows": related_rows,
        "recent_views": recent_views,
    }


def phase3_dashboard_snapshot(user: Any) -> dict[str, Any]:
    notifications = notification_center_snapshot(user, filter_name="all", limit=8)
    surveys = survey_center_for_user(user)
    support = support_queue_snapshot(user, filter_name="mine" if can_view_all_support_tickets(user) else "all")
    help_rows = help_center_snapshot(user)

    return {
        "notifications": notifications,
        "surveys": surveys,
        "support": support,
        "help": help_rows,
        "manager_mode": is_manager(user),
    }
