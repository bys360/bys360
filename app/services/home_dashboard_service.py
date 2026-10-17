
"""BYS360 Anasayfa Faz 1 günlük özet servisi."""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_

from app.core.datetime_utils import utc_now
from app.models import (
    DelegationAssignment,
    EvaluationAssignment,
    MessageThreadParticipant,
    Notification,
    PerformancePeriod,
    PersonnelLeave,
    SupportTicket,
    Survey,
    User,
)
from app.services.weather_recommendation_service import get_home_weather_context


def _safe_value(factory: Callable[[], Any], default: Any = 0) -> Any:
    try:
        return factory()
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/home_dashboard_service.py:29")
        return default


def _safe_count(factory: Callable[[], Any]) -> int:
    value = _safe_value(lambda: factory().count(), 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _user_id(user: Any) -> int:
    try:
        return int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _role(user: Any) -> str:
    return str(getattr(user, "role", "") or "")


def _is_managerial(user: Any) -> bool:
    return _role(user) in {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator"}


def build_home_summary_context(user: Any) -> dict[str, Any]:
    uid = _user_id(user)
    today = date.today()
    now = utc_now()

    pending_tasks = _safe_count(lambda: EvaluationAssignment.query.filter(
        EvaluationAssignment.evaluator_id == uid,
        EvaluationAssignment.status.in_(["bekliyor", "kismen_tamamlandi"]),
    ))
    overdue_tasks = _safe_count(lambda: EvaluationAssignment.query.filter(
        EvaluationAssignment.evaluator_id == uid,
        EvaluationAssignment.status != "tamamlandi",
        EvaluationAssignment.due_date.isnot(None),
        EvaluationAssignment.due_date < now,
    ))
    unread_notifications = _safe_count(lambda: Notification.query.filter_by(user_id=uid, is_read=False))
    active_messages = _safe_count(lambda: MessageThreadParticipant.query.filter(
        MessageThreadParticipant.user_id == uid,
        MessageThreadParticipant.left_at.is_(None),
        MessageThreadParticipant.is_archived.is_(False),
    ))
    my_support_tickets = _safe_count(lambda: SupportTicket.query.filter(
        SupportTicket.created_by_user_id == uid,
        SupportTicket.status.in_(["open", "in_progress", "pending", "waiting", "bekliyor", "inceleniyor"]),
    ))
    assigned_support_tickets = _safe_count(lambda: SupportTicket.query.filter(
        SupportTicket.assigned_to_user_id == uid,
        SupportTicket.status.in_(["open", "in_progress", "pending", "waiting", "bekliyor", "inceleniyor"]),
    )) if _is_managerial(user) else 0
    active_surveys = _safe_count(lambda: Survey.query.filter(
        Survey.status.in_(["published", "active", "yayinda", "aktif"]),
        or_(Survey.end_at.is_(None), Survey.end_at >= now),
    ))
    active_delegations = _safe_count(lambda: DelegationAssignment.query.filter(
        or_(DelegationAssignment.delegator_user_id == uid, DelegationAssignment.delegate_user_id == uid),
        DelegationAssignment.status.in_(["aktif", "active"]),
        DelegationAssignment.start_date <= today,
        DelegationAssignment.end_date >= today,
    ))
    approved_leaves_today = _safe_count(lambda: PersonnelLeave.query.filter(
        PersonnelLeave.user_id == uid,
        PersonnelLeave.status.in_(["onaylandi", "approved"]),
        PersonnelLeave.start_date <= today,
        PersonnelLeave.end_date >= today,
    ))
    active_period = _safe_value(lambda: PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first(), None)
    user_count = _safe_count(lambda: User.query.filter(User.role != "admin")) if _is_managerial(user) else 0

    return {
        "active_period": active_period,
        "today_label": today.strftime("%d.%m.%Y"),
        "pending_tasks": pending_tasks,
        "overdue_tasks": overdue_tasks,
        "unread_notifications": unread_notifications,
        "active_messages": active_messages,
        "my_support_tickets": my_support_tickets,
        "assigned_support_tickets": assigned_support_tickets,
        "active_surveys": active_surveys,
        "active_delegations": active_delegations,
        "approved_leaves_today": approved_leaves_today,
        "user_count": user_count,
    }


_LOCAL_TZ = ZoneInfo("Europe/Istanbul")


def _local_time_label(iso_value: Any) -> str:
    """Hava durumu servisinin UTC ISO zamanını ekranda yerel saat (SS:DD) olarak gösterir."""
    try:
        moment = datetime.fromisoformat(str(iso_value))
    except (TypeError, ValueError):
        return ""
    if moment.tzinfo is None:
        return ""
    return moment.astimezone(_LOCAL_TZ).strftime("%H:%M")


def build_home_page_context(user: Any) -> dict[str, Any]:
    summary = build_home_summary_context(user)
    weather = get_home_weather_context()
    weather = dict(weather or {})
    weather["updated_label"] = _local_time_label(weather.get("updated_at"))
    quick_actions = [
        {
            "label": "Görevlerim",
            "value": summary["pending_tasks"],
            "note": "Bekleyen / kısmi görev",
            "icon": "fa-list-check",
            "endpoint": "main.performance_tasks",
            "tone": "primary" if summary["pending_tasks"] else "neutral",
        },
        {
            "label": "Bildirimler",
            "value": summary["unread_notifications"],
            "note": "Okunmamış bildirim",
            "icon": "fa-bell",
            "endpoint": "main.notifications_list",
            "tone": "warning" if summary["unread_notifications"] else "neutral",
        },
        {
            "label": "Mesajlar",
            "value": summary["active_messages"],
            "note": "Aktif konuşma",
            "icon": "fa-envelope",
            "endpoint": "main.messages_inbox",
            "tone": "neutral",
        },
        {
            "label": "Destek",
            "value": summary["my_support_tickets"] + summary["assigned_support_tickets"],
            "note": "Açık destek kaydı",
            "icon": "fa-circle-info",
            "endpoint": "main.support_my_tickets",
            "tone": "warning" if summary["my_support_tickets"] or summary["assigned_support_tickets"] else "neutral",
        },
    ]
    operational_cards = [
        {
            "title": "Performans süreci",
            "text": "Açık görevler, yayın ve görünürlük kontrolleri için performans ekranlarını izleyin.",
            "icon": "fa-chart-line",
            "endpoint": "main.dashboard",
        },
        {
            "title": "İzin–vekâlet",
            "text": f"Bugünkü izin kaydı: {summary['approved_leaves_today']} · aktif vekâlet: {summary['active_delegations']}",
            "icon": "fa-user-clock",
            "endpoint": "main.hr_leave_management",
        },
        {
            "title": "Anket ve geri bildirim",
            "text": f"Aktif anket sayısı: {summary['active_surveys']}. Nabız, kampanya ve sonuç ekranlarını takip edin.",
            "icon": "fa-square-poll-vertical",
            "endpoint": "main.surveys_list",
        },
    ]
    return {
        "home_summary": summary,
        "home_weather": weather,
        "home_quick_actions": quick_actions,
        "home_operational_cards": operational_cards,
    }

# BYS360_RUNTIME_LOGGEDIN_SLOW_PAGES_V3_HOME_SUMMARY_CACHE
_HOME_SUMMARY_CACHE_TTL_SECONDS = 45
_HOME_SUMMARY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _home_summary_cache_key(user: Any) -> str:
    uid = _user_id(user)
    role = _role(user)
    # Günlük özet sayıları kullanıcı bazlıdır; tarih değişince cache doğal olarak ayrılır.
    return f"home_summary:v3:{date.today().isoformat()}:user:{uid}:role:{role}"


def _home_summary_cache_get(key: str) -> dict[str, Any] | None:
    row = _HOME_SUMMARY_CACHE.get(key)
    if not row:
        return None
    expires_at, payload = row
    if expires_at < time.time():
        _HOME_SUMMARY_CACHE.pop(key, None)
        return None
    return dict(payload)


def _home_summary_cache_set(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    # ORM nesnesi olan active_period cache'e alınmaz; her istekte taze okunur.
    safe_payload = dict(payload or {})
    safe_payload.pop("active_period", None)
    _HOME_SUMMARY_CACHE[key] = (time.time() + _HOME_SUMMARY_CACHE_TTL_SECONDS, safe_payload)
    return dict(safe_payload)


_build_home_summary_context_uncached = build_home_summary_context


def build_home_summary_context(user: Any) -> dict[str, Any]:  # type: ignore[no-redef]
    cache_key = _home_summary_cache_key(user)
    cached = _home_summary_cache_get(cache_key)
    if cached is None:
        cached = _home_summary_cache_set(cache_key, _build_home_summary_context_uncached(user))
    summary = dict(cached)
    # Aktif dönem ORM nesnesi template içinde .title ile kullanıldığı için cache dışı taze okunur.
    summary["active_period"] = _safe_value(
        lambda: PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first(),
        None,
    )
    return summary


__all__ = ["build_home_page_context", "build_home_summary_context"]
