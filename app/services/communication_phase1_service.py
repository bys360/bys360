from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    Notification,
    OrganizationUnit,
    SupportHelpArticle,
    SupportTicket,
    Survey,
    User,
)
from app.models.communication_phase1_models import (
    CommunicationBulletin,
    CommunicationBulletinAudience,
    CommunicationBulletinReceipt,
)
from app.services.communication_phase2_service import SURVEY_STATUS_LABELS, SURVEY_TYPE_LABELS
from app.services.role_display import ROLE_DISPLAY_LABELS, UNKNOWN_ROLE_DISPLAY_LABEL
from app.services.support_ticket_access import support_ticket_visibility_clause

MANAGER_ROLES = {
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "birim_sorumlusu",
}


BULLETIN_PRIORITY_LABELS = {
    "low": "Düşük",
    "normal": "Normal",
    "high": "Yüksek",
    "critical": "Kritik",
}


BULLETIN_STATUS_LABELS = {
    "draft": "Taslak",
    "published": "Yayında",
    "archived": "Arşiv",
}


SUPPORT_OPEN_STATUSES = {"open", "reviewing", "waiting_info", "assigned", "planned"}


class CommunicationPhase1Error(RuntimeError):
    pass


def _now() -> datetime:
    return utc_now()


def safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def user_role_slug(user: Any) -> str:
    return safe_str(getattr(user, "role", "")).lower()


def is_manager(user: Any) -> bool:
    return user_role_slug(user) in MANAGER_ROLES


def _active_user_query():
    query = User.query
    if hasattr(User, "is_active"):
        query = query.filter(User.is_active.is_(True))
    return query


def _user_display_name(user: Any) -> str:
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


def _resolve_users_for_audience(target_type: str, raw_values: Iterable[str]) -> list[Any]:
    query = _active_user_query()
    target_type = safe_str(target_type).lower() or "all"
    values = [safe_str(v) for v in raw_values if safe_str(v)]

    if target_type == "all" or not values:
        return query.all()

    matched_ids: set[int] = set()

    if target_type == "role":
        for value in values:
            rows = query.filter(User.role == value).all() if hasattr(User, "role") else []
            matched_ids.update(row.id for row in rows)
    elif target_type == "unit":
        if hasattr(User, "organization_unit_id"):
            numeric_values = [int(v) for v in values if v.isdigit()]
            if numeric_values:
                rows = query.filter(User.organization_unit_id.in_(numeric_values)).all()
                matched_ids.update(row.id for row in rows)
        if hasattr(User, "birim"):
            for value in values:
                rows = query.filter(User.birim == value).all()
                matched_ids.update(row.id for row in rows)
    elif target_type == "user":
        numeric_values = [int(v) for v in values if v.isdigit()]
        if numeric_values:
            rows = query.filter(User.id.in_(numeric_values)).all()
            matched_ids.update(row.id for row in rows)
    else:
        return query.all()

    return query.filter(User.id.in_(sorted(matched_ids))).all() if matched_ids else []


def _normalize_target_values(target_type: str, raw_text: str) -> list[str]:
    values = [safe_str(part) for part in (raw_text or "").replace("\n", ",").split(",")]
    clean_values = [value for value in values if value]
    if target_type == "all":
        return ["all"]
    return list(dict.fromkeys(clean_values))


def create_bulletin(
    *,
    title: str,
    summary: str,
    content: str,
    bulletin_type: str,
    priority: str,
    target_type: str,
    target_values_text: str,
    creator_user_id: int | None,
    is_pinned: bool = False,
    require_ack: bool = False,
    publish_now: bool = False,
) -> CommunicationBulletin:
    title = safe_str(title)
    content = safe_str(content)
    if not title:
        raise CommunicationPhase1Error("Başlık zorunludur.")
    if not content:
        raise CommunicationPhase1Error("İçerik zorunludur.")

    bulletin = CommunicationBulletin(
        title=title,
        summary=safe_str(summary) or None,
        content=content,
        bulletin_type=safe_str(bulletin_type) or "duyuru",
        priority=safe_str(priority) or "normal",
        status="draft",
        is_pinned=bool(is_pinned),
        require_ack=bool(require_ack),
        created_by_user_id=creator_user_id,
    )
    db.session.add(bulletin)
    db.session.flush()

    norm_target_type = safe_str(target_type).lower() or "all"
    norm_values = _normalize_target_values(norm_target_type, target_values_text)
    for value in norm_values:
        db.session.add(
            CommunicationBulletinAudience(
                bulletin_id=bulletin.id,
                target_type=norm_target_type,
                target_value=None if value == "all" else value,
            )
        )

    db.session.flush()

    if publish_now:
        publish_bulletin(bulletin.id, actor_user_id=creator_user_id)
    else:
        db.session.commit()

    return bulletin


def resolve_bulletin_target_users(bulletin: CommunicationBulletin) -> list[Any]:
    if not bulletin:
        return []

    audiences = bulletin.audiences.order_by(CommunicationBulletinAudience.id.asc()).all()  # type: ignore[misc,operator]
    if not audiences:
        return _active_user_query().all()

    resolved: dict[int, Any] = {}
    for audience in audiences:
        rows = _resolve_users_for_audience(
            safe_str(audience.target_type),
            [safe_str(audience.target_value)] if safe_str(audience.target_value) else ["all"],
        )
        for row in rows:
            resolved[row.id] = row
    return list(resolved.values())


def publish_bulletin(bulletin_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
    bulletin = db.session.get(CommunicationBulletin, bulletin_id)
    if not bulletin:
        raise CommunicationPhase1Error("Duyuru kaydı bulunamadı.")

    target_users = resolve_bulletin_target_users(bulletin)
    publish_time = _now()

    bulletin.status = "published"
    bulletin.publish_at = publish_time
    bulletin.published_by_user_id = actor_user_id
    db.session.add(bulletin)

    delivered = 0
    for user in target_users:
        receipt = CommunicationBulletinReceipt.query.filter_by(bulletin_id=bulletin.id, user_id=user.id).first()
        if not receipt:
            receipt = CommunicationBulletinReceipt(
                bulletin_id=bulletin.id,
                user_id=user.id,
                delivered_at=publish_time,
            )
            db.session.add(receipt)
            delivered += 1

        db.session.add(
            Notification(
                user_id=user.id,
                title=bulletin.title,
                body=bulletin.summary or "Yeni duyuru yayımlandı.",
                notification_type="announcement",
                source_type="communication_bulletin",
                source_id=bulletin.id,
                link_url=f"/communication/faz1/bulletins/{bulletin.id}",
                priority=bulletin.priority or "normal",
                is_read=False,
            )
        )

    db.session.commit()
    return {"delivered_count": delivered, "target_count": len(target_users)}


def bulletin_dashboard_snapshot(limit: int = 8) -> dict[str, Any]:
    rows = (
        CommunicationBulletin.query.order_by(
            CommunicationBulletin.is_pinned.desc(),
            CommunicationBulletin.created_at.desc(),
        )
        .limit(limit)
        .all()
    )
    stats = Counter((safe_str(row.status) or "draft") for row in CommunicationBulletin.query.all())
    return {
        "rows": rows,
        "counts": {
            "total": CommunicationBulletin.query.count(),
            "draft": int(stats.get("draft", 0)),
            "published": int(stats.get("published", 0)),
            "archived": int(stats.get("archived", 0)),
        },
    }


def communication_phase1_dashboard(user: Any) -> dict[str, Any]:
    survey_rows = Survey.query.order_by(Survey.created_at.desc()).limit(6).all()
    # K5: the dashboard lists and counts only the tickets inside the viewer's scope.
    visible_support = SupportTicket.query.filter(support_ticket_visibility_clause(user))
    support_rows = visible_support.order_by(SupportTicket.created_at.desc()).limit(6).all()
    bulletin_data = bulletin_dashboard_snapshot(limit=6)

    my_unread_notifications = 0
    if user and getattr(user, "id", None):
        my_unread_notifications = Notification.query.filter_by(user_id=user.id, is_read=False).count()

    open_support_count = visible_support.filter(SupportTicket.status.in_(sorted(SUPPORT_OPEN_STATUSES))).count()
    active_surveys_count = Survey.query.filter(Survey.status.in_(["published", "active"])).count()

    return {
        "bulletins": bulletin_data,
        "recent_surveys": survey_rows,
        "recent_support": support_rows,
        "stats": {
            "my_unread_notifications": my_unread_notifications,
            "active_surveys": active_surveys_count,
            "open_support": open_support_count,
            "help_articles": SupportHelpArticle.query.filter_by(is_published=True).count() if hasattr(SupportHelpArticle, "is_published") else SupportHelpArticle.query.count(),
        },
        "bulletin_status_labels": BULLETIN_STATUS_LABELS,
        "bulletin_priority_labels": BULLETIN_PRIORITY_LABELS,
        "survey_status_labels": SURVEY_STATUS_LABELS,
        "survey_type_labels": SURVEY_TYPE_LABELS,
    }


def survey_center_snapshot() -> dict[str, Any]:
    surveys = Survey.query.order_by(Survey.created_at.desc()).all()
    rows: list[dict[str, Any]] = []

    for survey in surveys:
        assignment_count = survey.assignments.count() if hasattr(survey.assignments, "count") else len(survey.assignments)
        response_count = survey.responses.count() if hasattr(survey.responses, "count") else len(survey.responses)
        question_count = survey.questions.count() if hasattr(survey.questions, "count") else len(survey.questions)
        rows.append(
            {
                "survey": survey,
                "question_count": question_count,
                "assignment_count": assignment_count,
                "response_count": response_count,
                "completion_rate": round((response_count / assignment_count) * 100, 1) if assignment_count else 0.0,
            }
        )

    status_counter = Counter(safe_str(row.status) or "draft" for row in surveys)
    return {
        "rows": rows,
        "counts": {
            "total": len(surveys),
            "draft": int(status_counter.get("draft", 0)),
            "published": int(status_counter.get("published", 0) + status_counter.get("active", 0)),
            "closed": int(status_counter.get("closed", 0) + status_counter.get("archived", 0)),
        },
    }


def support_center_snapshot(viewer: Any) -> dict[str, Any]:
    # K5: rows and counters cover only the tickets inside the viewer's scope.
    tickets = (SupportTicket.query.filter(support_ticket_visibility_clause(viewer))
               .order_by(SupportTicket.created_at.desc()).all())
    rows: list[dict[str, Any]] = []

    for ticket in tickets:
        rows.append(
            {
                "ticket": ticket,
                "message_count": len(getattr(ticket, "messages", []) or []),
                "attachment_count": len(getattr(ticket, "attachments", []) or []),
                "assignee_name": _user_display_name(getattr(ticket, "assigned_to", None)),
                "creator_name": _user_display_name(getattr(ticket, "created_by", None)),
            }
        )

    status_counter = Counter(safe_str(ticket.status) or "open" for ticket in tickets)
    priority_counter = Counter(safe_str(ticket.priority) or "normal" for ticket in tickets)

    return {
        "rows": rows,
        "counts": {
            "total": len(tickets),
            "open": sum(status_counter.get(key, 0) for key in SUPPORT_OPEN_STATUSES),
            "resolved": int(status_counter.get("resolved", 0)),
            "closed": int(status_counter.get("closed", 0)),
            "critical": int(priority_counter.get("critical", 0)),
            "help_articles": SupportHelpArticle.query.filter_by(is_published=True).count() if hasattr(SupportHelpArticle, "is_published") else SupportHelpArticle.query.count(),
        },
    }


def manager_filter_options() -> dict[str, list[tuple[str, str]]]:
    users = _active_user_query().order_by(User.ad.asc(), User.soyad.asc()).all()
    roles_seen: list[tuple[str, str]] = []
    units_seen: list[tuple[str, str]] = []
    seen_role_values: set[str] = set()
    seen_unit_values: set[str] = set()

    for user in users:
        role = safe_str(getattr(user, "role", ""))
        if role and role not in seen_role_values:
            roles_seen.append((role, ROLE_DISPLAY_LABELS.get(role, UNKNOWN_ROLE_DISPLAY_LABEL)))
            seen_role_values.add(role)

    unit_rows = OrganizationUnit.query.order_by(OrganizationUnit.name.asc()).all()
    for row in unit_rows:
        value = str(row.id)
        label = safe_str(getattr(row, "name", "")) or value
        if value not in seen_unit_values:
            units_seen.append((value, label))
            seen_unit_values.add(value)

    return {
        "roles": roles_seen,
        "units": units_seen,
        "users": [(str(user.id), _user_display_name(user)) for user in users],
    }