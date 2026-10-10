from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from flask import url_for

from app.extensions import db
from app.models import Notification, User
from app.route_support import sanitize_free_text

logger = logging.getLogger(__name__)

"""BYS360 modüller arası sistem içi bildirim köprüsü.

Bu servis; destek/talep, hızlı geri bildirim, kurumsal geri bildirim
kampanyaları ve portal etkileşimlerinde bildirim üretimini tek noktadan
ve güvenli biçimde yönetir. Bildirim üretimi ana işlemi düşürmemelidir;
bu yüzden tüm yardımcılar kontrollü çalışır ve commit çağırmaz.
"""

_ADMIN_ROLE_TOKENS = {
    "admin",
    "sistem_yoneticisi",
    "sistem yöneticisi",
    "administrator",
}
_SUPPORT_ROLE_TOKENS = {
    "destek",
    "support",
    "ik",
    "insan kaynaklari",
    "insan kaynakları",
    "personel",
    "performans",
}
_PORTAL_MANAGER_ROLE_TOKENS = {
    "admin",
    "sistem_yoneticisi",
    "sistem yöneticisi",
    "portal",
    "kurumsal",
    "iletisim",
    "iletişim",
}


def _safe_int(value: Any) -> int | None:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return None
    return ivalue if ivalue > 0 else None


def _text(value: Any, *, limit: int = 255) -> str:
    return sanitize_free_text(str(value or ""), limit=limit)


def _user_label(user: Any) -> str:
    return (
        _text(getattr(user, "full_name", ""), limit=180)
        or " ".join(part for part in [_text(getattr(user, "ad", ""), limit=80), _text(getattr(user, "soyad", ""), limit=80)] if part)
        or _text(getattr(user, "email", ""), limit=180)
        or "BYS360 Kullanıcısı"
    )


def _role_text(user: Any) -> str:
    return " ".join([
        _text(getattr(user, "role", ""), limit=120).lower(),
        _text(getattr(user, "role_label", ""), limit=160).lower(),
        _text(getattr(user, "unvan", ""), limit=160).lower(),
    ])


def _role_matches(user: Any, tokens: set[str]) -> bool:
    blob = _role_text(user)
    return any(token in blob for token in tokens)


def _active_users_query():
    return User.query.filter(User.is_active.is_(True))


def _actor_id(actor: Any) -> int | None:
    return _safe_int(getattr(actor, "id", None))


def _unique_ids(values: Iterable[Any], *, exclude: Iterable[Any] | None = None, limit: int = 200) -> list[int]:
    excluded = {_safe_int(v) for v in (exclude or [])}
    excluded.discard(None)
    seen: set[int] = set()
    result: list[int] = []
    for value in values or []:
        user_id = _safe_int(value)
        if not user_id or user_id in excluded or user_id in seen:
            continue
        seen.add(user_id)
        result.append(user_id)
        if len(result) >= limit:
            break
    return result


def _support_manager_ids(*, exclude: Iterable[Any] | None = None, limit: int = 80) -> list[int]:
    rows = _active_users_query().limit(800).all()
    return _unique_ids(
        [u.id for u in rows if _role_matches(u, _ADMIN_ROLE_TOKENS | _SUPPORT_ROLE_TOKENS)],
        exclude=exclude,
        limit=limit,
    )


def _support_all_recipient_ids(ticket: Any, *, exclude: Iterable[Any] | None = None, limit: int = 80) -> list[int]:
    """K5-Q3: support ticket notifications reach the explicit support_all holders allowed to see the ticket.

    Not role, role_label or title matches (_support_manager_ids); the private-ticket unit rule applies.
    """
    from app.services.personnel_read_grant import SUPPORT_ALL_KEY, explicit_grant_holder_ids
    from app.services.support_ticket_access import can_view_private_support_ticket

    holder_ids = explicit_grant_holder_ids(SUPPORT_ALL_KEY, limit=800)
    if not holder_ids:
        return []
    holders = _active_users_query().filter(User.id.in_(holder_ids)).all()
    return _unique_ids(
        [u.id for u in holders if can_view_private_support_ticket(ticket, u)],
        exclude=exclude,
        limit=limit,
    )


def _portal_manager_ids(*, exclude: Iterable[Any] | None = None, limit: int = 80) -> list[int]:
    rows = _active_users_query().limit(800).all()
    return _unique_ids(
        [u.id for u in rows if _role_matches(u, _PORTAL_MANAGER_ROLE_TOKENS)],
        exclude=exclude,
        limit=limit,
    )


def _priority(value: Any) -> str:
    p = _text(value, limit=20).lower() or "normal"
    if p in {"critical", "kritik"}:
        return "high"
    if p in {"high", "yüksek", "yuksek"}:
        return "high"
    if p in {"low", "düşük", "dusuk"}:
        return "low"
    return "normal"


def create_notification(
    *,
    user_id: int | None,
    title: str,
    body: str = "",
    notification_type: str = "system",
    source_type: str | None = None,
    source_id: int | None = None,
    link_url: str | None = None,
    priority: str = "normal",
    actor_user_id: int | None = None,
) -> bool:
    """Commit etmeden tek bildirim oluşturur."""
    try:
        uid = _safe_int(user_id)
        if not uid or (actor_user_id and uid == _safe_int(actor_user_id)):
            return False
        db.session.add(
            Notification(
                user_id=uid,
                title=_text(title, limit=255) or "BYS360 Bildirimi",
                body=_text(body, limit=900) or None,
                notification_type=_text(notification_type, limit=50) or "system",
                source_type=_text(source_type, limit=50) or None,
                source_id=_safe_int(source_id),
                link_url=_text(link_url, limit=500) or None,
                priority=_priority(priority),
                is_read=False,
            )
        )
        return True
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/bys360_notification_bridge.py | line=166")
        return False


def create_notifications(
    *,
    user_ids: Iterable[Any],
    title: str,
    body: str = "",
    notification_type: str = "system",
    source_type: str | None = None,
    source_id: int | None = None,
    link_url: str | None = None,
    priority: str = "normal",
    actor_user_id: int | None = None,
    limit: int = 200,
) -> int:
    count = 0
    for uid in _unique_ids(user_ids, exclude=[actor_user_id], limit=limit):
        if create_notification(
            user_id=uid,
            title=title,
            body=body,
            notification_type=notification_type,
            source_type=source_type,
            source_id=source_id,
            link_url=link_url,
            priority=priority,
            actor_user_id=actor_user_id,
        ):
            count += 1
    return count


def _support_link(ticket: Any) -> str:
    ticket_id = _safe_int(getattr(ticket, "id", None))
    return url_for("main.support_detail", ticket_id=ticket_id) if ticket_id else "/support"


def notify_support_ticket_created(ticket: Any, actor: Any) -> int:
    actor_id = _actor_id(actor)
    ticket_no = _text(getattr(ticket, "ticket_no", ""), limit=40)
    recipients = _support_all_recipient_ids(ticket, exclude=[actor_id])
    assigned_id = _safe_int(getattr(ticket, "assigned_to_user_id", None))
    if assigned_id:
        recipients.append(assigned_id)
    return create_notifications(
        user_ids=recipients,
        title="Yeni talep oluşturuldu",
        body=f"{_user_label(actor)} tarafından {ticket_no or 'yeni bir talep'} kaydı açıldı.",
        notification_type="support_ticket_created",
        source_type="support_ticket",
        source_id=getattr(ticket, "id", None),
        link_url=_support_link(ticket),
        priority=getattr(ticket, "priority", "normal"),
        actor_user_id=actor_id,
    )


def notify_user_feedback_created(ticket: Any, actor: Any, *, kind_label: str | None = None) -> int:
    actor_id = _actor_id(actor)
    recipients = _support_all_recipient_ids(ticket, exclude=[actor_id])
    label = _text(kind_label, limit=80) or "Geri bildirim"
    return create_notifications(
        user_ids=recipients,
        title="Yeni geri bildirim alındı",
        body=f"{_user_label(actor)} tarafından {label.lower()} kaydı oluşturuldu.",
        notification_type="user_feedback_created",
        source_type="support_ticket",
        source_id=getattr(ticket, "id", None),
        link_url=_support_link(ticket),
        priority=getattr(ticket, "priority", "normal"),
        actor_user_id=actor_id,
    )


def notify_support_ticket_comment(ticket: Any, actor: Any, *, is_internal: bool = False) -> int:
    actor_id = _actor_id(actor)
    recipients: list[int] = []
    creator_id = _safe_int(getattr(ticket, "created_by_user_id", None))
    assigned_id = _safe_int(getattr(ticket, "assigned_to_user_id", None))
    if is_internal:
        recipients.extend(_support_all_recipient_ids(ticket, exclude=[actor_id]))
        if assigned_id:
            recipients.append(assigned_id)
    elif creator_id and creator_id != actor_id:
        recipients.append(creator_id)
    else:
        if assigned_id:
            recipients.append(assigned_id)
        recipients.extend(_support_all_recipient_ids(ticket, exclude=[actor_id]))
    return create_notifications(
        user_ids=recipients,
        title="Talebe yeni not eklendi",
        body=f"{_user_label(actor)} talep kaydına yeni bir not ekledi.",
        notification_type="support_ticket_comment",
        source_type="support_ticket",
        source_id=getattr(ticket, "id", None),
        link_url=_support_link(ticket),
        priority=getattr(ticket, "priority", "normal"),
        actor_user_id=actor_id,
    )


def notify_support_ticket_status_changed(ticket: Any, actor: Any, *, old_status: str | None = None, new_status: str | None = None, note: str | None = None) -> int:
    actor_id = _actor_id(actor)
    recipients = _unique_ids([
        getattr(ticket, "created_by_user_id", None),
        getattr(ticket, "assigned_to_user_id", None),
    ], exclude=[actor_id], limit=20)
    status_label = _text(getattr(ticket, "status_label", ""), limit=80) or _text(new_status, limit=80) or "Güncellendi"
    note_part = f" Açıklama: {_text(note, limit=250)}" if _text(note, limit=250) else ""
    return create_notifications(
        user_ids=recipients,
        title="Talep durumu güncellendi",
        body=f"Talep durumu '{status_label}' olarak güncellendi.{note_part}",
        notification_type="support_ticket_status_changed",
        source_type="support_ticket",
        source_id=getattr(ticket, "id", None),
        link_url=_support_link(ticket),
        priority=getattr(ticket, "priority", "normal"),
        actor_user_id=actor_id,
    )


def notify_support_ticket_assigned(ticket: Any, actor: Any, *, assignee: Any | None = None) -> int:
    actor_id = _actor_id(actor)
    assignee_id = _safe_int(getattr(assignee, "id", None) or getattr(ticket, "assigned_to_user_id", None))
    recipients = _unique_ids([assignee_id, getattr(ticket, "created_by_user_id", None)], exclude=[actor_id], limit=20)
    assignee_label = _user_label(assignee) if assignee else "ilgili kullanıcı"
    return create_notifications(
        user_ids=recipients,
        title="Talep ataması güncellendi",
        body=f"Talep {assignee_label} üzerine atanarak güncellendi.",
        notification_type="support_ticket_assigned",
        source_type="support_ticket",
        source_id=getattr(ticket, "id", None),
        link_url=_support_link(ticket),
        priority=getattr(ticket, "priority", "normal"),
        actor_user_id=actor_id,
    )


def notify_support_ticket_rating(ticket: Any, actor: Any, *, rating: int | None = None, note: str | None = None) -> int:
    actor_id = _actor_id(actor)
    recipients = _support_all_recipient_ids(ticket, exclude=[actor_id])
    assigned_to_user_id = _safe_int(getattr(ticket, "assigned_to_user_id", None))
    if assigned_to_user_id:
        recipients.append(assigned_to_user_id)
    return create_notifications(
        user_ids=recipients,
        title="Talep değerlendirmesi kaydedildi",
        body=f"{_user_label(actor)} destek talebi için değerlendirme yaptı.",
        notification_type="support_ticket_rating",
        source_type="support_ticket",
        source_id=getattr(ticket, "id", None),
        link_url=_support_link(ticket),
        priority="normal",
        actor_user_id=actor_id,
    )


def _feedback_link(campaign: Any | None = None) -> str:
    try:
        if campaign and getattr(campaign, "id", None):
            return url_for("main.feedback_campaign_detail", campaign_id=campaign.id)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/bys360_notification_bridge.py | line=331")
        pass
    return "/communication/feedback"


def notify_feedback_campaign_created(campaign: Any, actor: Any) -> int:
    return create_notifications(
        user_ids=_support_manager_ids(exclude=[_actor_id(actor)]),
        title="Yeni geri bildirim kampanyası oluşturuldu",
        body=f"{_user_label(actor)} tarafından '{_text(getattr(campaign, 'title', ''), limit=160)}' kampanyası hazırlandı.",
        notification_type="feedback_campaign_created",
        source_type="feedback_campaign",
        source_id=getattr(campaign, "id", None),
        link_url=_feedback_link(campaign),
        priority="normal",
        actor_user_id=_actor_id(actor),
    )


def notify_feedback_campaign_status_changed(campaign: Any, actor: Any, *, target_status: str | None = None) -> int:
    actor_id = _actor_id(actor)
    recipients: list[int] = []
    created_by_id = _safe_int(getattr(campaign, "created_by_user_id", None))
    if created_by_id:
        recipients.append(created_by_id)
    recipients.extend(_support_manager_ids(exclude=[actor_id]))
    status = _text(target_status or getattr(campaign, "status", ""), limit=60) or "güncellendi"
    return create_notifications(
        user_ids=recipients,
        title="Geri bildirim kampanyası güncellendi",
        body=f"'{_text(getattr(campaign, 'title', ''), limit=160)}' kampanyasının durumu güncellendi: {status}.",
        notification_type="feedback_campaign_status_changed",
        source_type="feedback_campaign",
        source_id=getattr(campaign, "id", None),
        link_url=_feedback_link(campaign),
        priority="normal",
        actor_user_id=actor_id,
    )


def notify_feedback_submission_received(campaign: Any, actor: Any, submission: Any) -> int:
    creator_id = _safe_int(getattr(campaign, "created_by_user_id", None))
    return create_notifications(
        user_ids=[creator_id],
        title="Geri bildirim yanıtı alındı",
        body=f"'{_text(getattr(campaign, 'title', ''), limit=160)}' kampanyasına yeni yanıt geldi.",
        notification_type="feedback_submission_received",
        source_type="feedback_submission",
        source_id=getattr(submission, "id", None),
        link_url=_feedback_link(campaign),
        priority="normal",
        actor_user_id=_actor_id(actor),
    )


def notify_feedback_action_plan_created(plan: Any, actor: Any) -> int:
    recipients = _unique_ids([getattr(plan, "assigned_manager_id", None), getattr(plan, "created_by_user_id", None)], exclude=[_actor_id(actor)], limit=20)
    return create_notifications(
        user_ids=recipients,
        title="Geri bildirim aksiyonu oluşturuldu",
        body=f"'{_text(getattr(plan, 'title', ''), limit=180)}' aksiyonu için sorumluluk tanımlandı.",
        notification_type="feedback_action_plan_created",
        source_type="feedback_action_plan",
        source_id=getattr(plan, "id", None),
        link_url="/communication/feedback/actions",
        priority=getattr(plan, "priority", "normal"),
        actor_user_id=_actor_id(actor),
    )


def notify_feedback_action_plan_status_changed(plan: Any, actor: Any, *, status: str | None = None) -> int:
    recipients = _unique_ids([getattr(plan, "assigned_manager_id", None), getattr(plan, "created_by_user_id", None)], exclude=[_actor_id(actor)], limit=20)
    return create_notifications(
        user_ids=recipients,
        title="Geri bildirim aksiyonu güncellendi",
        body=f"'{_text(getattr(plan, 'title', ''), limit=180)}' aksiyonunun durumu güncellendi.",
        notification_type="feedback_action_plan_status_changed",
        source_type="feedback_action_plan",
        source_id=getattr(plan, "id", None),
        link_url="/communication/feedback/actions",
        priority=getattr(plan, "priority", "normal"),
        actor_user_id=_actor_id(actor),
    )


def _portal_post_link(post: Any) -> str:
    return url_for("main.portal_feed", _anchor=f"post-{getattr(post, 'id', '')}") if getattr(post, "id", None) else "/portal"


def _portal_audience_user_ids(post: Any, *, limit: int = 160) -> list[int]:
    ids: list[int] = []
    try:
        from app.models import PortalGroupMember, PortalPostAudience
        scope = _text(getattr(post, "visibility_scope", ""), limit=30)
        wall_owner_user_id = _safe_int(getattr(post, "wall_owner_user_id", None))
        if wall_owner_user_id:
            ids.append(wall_owner_user_id)
        if scope == "selected_users":
            rows = PortalPostAudience.query.filter_by(post_id=post.id, audience_type="user").limit(limit).all()
            ids.extend([v for v in (_safe_int(getattr(row, "audience_value", None)) for row in rows) if v])
        elif scope == "group" and _safe_int(getattr(post, "group_id", None)):
            # Same membership rule as portal_service.is_group_member (who can see the post).
            rows = PortalGroupMember.query.filter_by(group_id=post.group_id, status="active").limit(limit).all()
            ids.extend([v for v in (_safe_int(getattr(row, "user_id", None)) for row in rows) if v])
        elif scope == "role" and _text(getattr(post, "target_role_name", ""), limit=80):
            role = _text(getattr(post, "target_role_name", ""), limit=80).lower()
            rows = _active_users_query().limit(1000).all()
            ids.extend([u.id for u in rows if role and (role in _role_text(u))])
        elif scope == "unit" and _text(getattr(post, "target_unit_name", ""), limit=180):
            unit = _text(getattr(post, "target_unit_name", ""), limit=180)
            rows = _active_users_query().filter(User.birim == unit).limit(limit).all()
            ids.extend([u.id for u in rows])
        elif scope == "upper_unit" and _text(getattr(post, "target_upper_unit_name", ""), limit=180):
            unit = _text(getattr(post, "target_upper_unit_name", ""), limit=180)
            rows = _active_users_query().filter(User.ust_birim == unit).limit(limit).all()
            ids.extend([u.id for u in rows])
        elif _text(getattr(post, "post_type", ""), limit=40) in {"announcement", "duyuru"} or getattr(post, "is_pinned", False):
            ids.extend([u.id for u in _active_users_query().limit(limit).all()])
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/bys360_notification_bridge.py | line=447")
        pass
    return _unique_ids(ids, exclude=[getattr(post, "author_user_id", None)], limit=limit)


def notify_portal_post_created(post: Any, actor: Any) -> int:
    return create_notifications(
        user_ids=_portal_audience_user_ids(post),
        title="Portalda yeni paylaşım var",
        body=f"{_user_label(actor)} yeni bir portal paylaşımı yayınladı.",
        notification_type="portal_post_created",
        source_type="portal_post",
        source_id=getattr(post, "id", None),
        link_url=_portal_post_link(post),
        priority="normal",
        actor_user_id=_actor_id(actor),
        limit=160,
    )


def notify_portal_reaction(post: Any, actor: Any, *, action: str | None = None) -> int:
    if _text(action, limit=30) == "removed":
        return 0
    return create_notifications(
        user_ids=[getattr(post, "author_user_id", None)],
        title="Portal paylaşımınıza tepki geldi",
        body=f"{_user_label(actor)} portal paylaşımınıza tepki verdi.",
        notification_type="portal_post_reaction",
        source_type="portal_post",
        source_id=getattr(post, "id", None),
        link_url=_portal_post_link(post),
        priority="low",
        actor_user_id=_actor_id(actor),
    )


def notify_portal_comment_added(post: Any, comment: Any, actor: Any, *, already_notified: Iterable[Any] | None = None) -> int:
    return create_notifications(
        user_ids=[getattr(post, "author_user_id", None)],
        title="Portal paylaşımınıza yorum geldi",
        body=f"{_user_label(actor)} portal paylaşımınıza yorum yazdı.",
        notification_type="portal_post_comment",
        source_type="portal_comment",
        source_id=getattr(comment, "id", None),
        link_url=_portal_post_link(post),
        priority="normal",
        actor_user_id=_actor_id(actor),
        limit=20,
    )


def notify_portal_report_created(post: Any, actor: Any, *, report_id: int | None = None) -> int:
    return create_notifications(
        user_ids=_portal_manager_ids(exclude=[_actor_id(actor)]),
        title="Portal paylaşımı incelemeye bildirildi",
        body=f"{_user_label(actor)} bir portal paylaşımını inceleme için bildirdi.",
        notification_type="portal_post_report",
        source_type="portal_post_report",
        source_id=report_id or getattr(post, "id", None),
        link_url="/portal/moderation",
        priority="high",
        actor_user_id=_actor_id(actor),
    )
