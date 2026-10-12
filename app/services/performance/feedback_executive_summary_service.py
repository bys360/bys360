from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from app.core.datetime_utils import utc_now
from app.models import FeedbackMeeting, FeedbackRequest, Notification, User
from app.services.mail_service import send_email
from app.services.message_service import notify_user
from app.services.performance.feedback_alert_service import (
    ACTIVE_MEETING_STATUSES,
    PENDING_REQUEST_STATUSES,
    build_feedback_alert_dashboard,
)

SUMMARY_PRESET_LABELS = {
    "manual": "Manuel",
    "daily": "Günlük",
    "weekly": "Haftalık",
}


def _full_name(user: Any) -> str:
    if not user:
        return "-"
    return (
        getattr(user, "full_name", None)
        or f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip()
        or getattr(user, "email", None)
        or "-"
    )

def _safe_email(user: User | None) -> str:
    raw = (getattr(user, "email", None) or "").strip()
    if "@" not in raw or " " in raw:
        return ""
    return raw

def _request_is_open(feedback_request: FeedbackRequest | None) -> bool:
    return (getattr(feedback_request, "status", None) or "") in PENDING_REQUEST_STATUSES

def _meeting_is_active(meeting: FeedbackMeeting | None) -> bool:
    return (getattr(meeting, "status", None) or "") in ACTIVE_MEETING_STATUSES

def _meeting_start_dt(meeting: FeedbackMeeting | None) -> datetime | None:
    if not meeting or not getattr(meeting, "meeting_date", None) or not getattr(meeting, "meeting_start", None):
        return None
    return datetime.combine(meeting.meeting_date, meeting.meeting_start)

def _summary_source_id(now: datetime, preset: str) -> int:
    preset = (preset or "daily").strip().lower()
    if preset == "weekly":
        iso = now.isocalendar()
        return int(f"{iso.year}{iso.week:02d}")
    return int(now.strftime("%Y%m%d"))

def _summary_notification_exists(*, user_id: int | None, preset: str, source_id: int) -> bool:
    if not user_id:
        return False
    return Notification.query.filter_by(
        user_id=int(user_id),
        notification_type=f"performance_feedback_digest_{preset}",
        source_type="feedback_digest",
        source_id=source_id,
        is_read=False,
    ).first() is not None

def _normalize_recipient_users(recipients: Iterable[Any] | None) -> list[User]:
    resolved: list[User] = []
    seen_ids: set[int] = set()
    if not recipients:
        return resolved
    for item in recipients:
        user = None
        if isinstance(item, User):
            user = item
        else:
            try:
                user_id = int(item)
            except (TypeError, ValueError):
                __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/feedback_executive_summary_service.py:95)")
                continue
            user = User.query.filter_by(id=user_id, is_active=True).first()
        if not user:
            continue
        resolved_user_id = getattr(user, "id", None)
        if not resolved_user_id or int(resolved_user_id) in seen_ids:
            continue
        seen_ids.add(int(resolved_user_id))
        resolved.append(user)
    return resolved

def _related_request_ids(req: Any) -> set[int]:
    ids: set[int] = set()
    for field in ("employee_id", "level_1_manager_id", "level_2_manager_id", "level_3_manager_id"):
        value = getattr(req, field, None)
        if isinstance(value, int):
            ids.add(value)
    return ids


def _related_meeting_ids(meeting: Any) -> set[int]:
    ids: set[int] = set()
    for value in (getattr(meeting, "employee_id", None), getattr(meeting, "manager_id", None)):
        if isinstance(value, int):
            ids.add(value)
    req = getattr(meeting, "feedback_request", None)
    for field in ("level_1_manager_id", "level_2_manager_id", "level_3_manager_id", "scheduled_by_id"):
        value = getattr(req, field, None) if req is not None else None
        if isinstance(value, int):
            ids.add(value)
    return ids


def _suggest_recipient_users(requests_list: list[Any], meetings: list[Any]) -> list[User]:
    user_ids: set[int] = set()
    for req in requests_list:
        for field in (
            getattr(req, "level_1_manager_id", None),
            getattr(req, "level_2_manager_id", None),
            getattr(req, "level_3_manager_id", None),
            getattr(req, "scheduled_by_id", None),
        ):
            try:
                if field is not None:
                    user_ids.add(int(field))
            except (TypeError, ValueError):
                __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/feedback_executive_summary_service.py:122)")
                continue
    for meeting in meetings:
        for field in (
            getattr(meeting, "manager_id", None),
            getattr(getattr(meeting, "feedback_request", None), "level_1_manager_id", None),
            getattr(getattr(meeting, "feedback_request", None), "level_2_manager_id", None),
            getattr(getattr(meeting, "feedback_request", None), "level_3_manager_id", None),
        ):
            try:
                if field is not None:
                    user_ids.add(int(field))
            except (TypeError, ValueError):
                __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/feedback_executive_summary_service.py:135)")
                continue

    if not user_ids:
        # #57: no role-based fallback; a digest goes only to people related to its records.
        return []

    return (
        User.query
        .filter(User.id.in_(list(user_ids)), User.is_active.is_(True))
        .order_by(User.ad.asc(), User.soyad.asc(), User.id.asc())
        .all()
    )

def build_feedback_executive_summary(
    requests_list: list[Any],
    meetings: list[Any],
    *,
    preset: str = "daily",
    scope_label: str | None = None,
    scope_role_title: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    preset = (preset or "daily").strip().lower()
    if preset not in SUMMARY_PRESET_LABELS:
        preset = "daily"

    alert_dashboard = build_feedback_alert_dashboard(requests_list, meetings, today=now.date(), now=now)
    active_meetings = [meeting for meeting in meetings if _meeting_is_active(meeting)]

    request_age_buckets = {"0_1": 0, "2_4": 0, "5_plus": 0}
    request_status_counts: Counter[str] = Counter()
    for req in requests_list:
        status = (getattr(req, "status", None) or "-").strip() or "-"
        request_status_counts[status] += 1
        if not _request_is_open(req):
            continue
        requested_at = getattr(req, "requested_at", None) or now
        age_days = max(int((now - requested_at).total_seconds() // 86400), 0)
        if age_days <= 1:
            request_age_buckets["0_1"] += 1
        elif age_days <= 4:
            request_age_buckets["2_4"] += 1
        else:
            request_age_buckets["5_plus"] += 1

    upcoming_week_count = 0
    next_meetings: list[dict[str, Any]] = []
    for meeting in active_meetings:
        start_dt = _meeting_start_dt(meeting)
        if not start_dt:
            continue
        if now <= start_dt <= now + timedelta(days=7):
            upcoming_week_count += 1
            next_meetings.append(
                {
                    "meeting_id": getattr(meeting, "id", None),
                    "employee_name": _full_name(getattr(meeting, "employee", None)),
                    "manager_name": _full_name(getattr(meeting, "manager", None)),
                    "when_text": start_dt.strftime("%d.%m.%Y %H:%M"),
                    "status": getattr(meeting, "status", None) or "-",
                    "location": getattr(meeting, "location", None) or "Konum girilmedi",
                }
            )
    next_meetings.sort(key=lambda item: item["when_text"])

    recipient_suggestions = _suggest_recipient_users(requests_list, meetings)
    preset_label = SUMMARY_PRESET_LABELS.get(preset, "Günlük")
    subject = f"BYS360 {preset_label} performans geri bildirim özeti | {now.strftime('%d.%m.%Y')}"
    body_lines = [
        f"Kapsam: {scope_role_title or 'Kapsam görünümü'} · {scope_label or 'Kurum geneli'}",
        f"Açık talep: {alert_dashboard['alert_counts'].get('open_requests', 0)}",
        f"Hatırlatma eşiğinde talep: {alert_dashboard['alert_counts'].get('request_reminder_candidates', 0)}",
        f"SLA riski: {alert_dashboard['alert_counts'].get('request_sla_risks', 0)}",
        f"24 saat içinde görüşme: {alert_dashboard['alert_counts'].get('meetings_next_24h', 0)}",
        f"7 gün içinde görüşme: {upcoming_week_count}",
        f"Geciken görüşme: {alert_dashboard['alert_counts'].get('meeting_overdue', 0)}",
        f"Yoğun yönetici: {alert_dashboard['alert_counts'].get('manager_hotspots', 0)}",
    ]
    if alert_dashboard.get("manager_rows"):
        top_names = ", ".join(row.get("manager_name", "-") for row in alert_dashboard["manager_rows"][:3] if row.get("manager_name"))
        if top_names:
            body_lines.append(f"Yoğunluk üst sırası: {top_names}")
    if alert_dashboard.get("request_alerts"):
        top_request = alert_dashboard["request_alerts"][0]
        body_lines.append(
            f"Öncelikli talep: {top_request.get('employee_name', '-')} · {top_request.get('age_days', 0)} gündür açık · {top_request.get('manager_text', '-') }"
        )
    if next_meetings:
        first_meeting = next_meetings[0]
        body_lines.append(
            f"En yakın görüşme: {first_meeting['employee_name']} · {first_meeting['when_text']} · {first_meeting['manager_name']}"
        )
    body_plain = "\n".join(body_lines)

    return {
        "preset": preset,
        "preset_label": preset_label,
        "generated_at": now,
        "cards": {
            "open_requests": alert_dashboard["alert_counts"].get("open_requests", 0),
            "request_reminders": alert_dashboard["alert_counts"].get("request_reminder_candidates", 0),
            "request_sla_risks": alert_dashboard["alert_counts"].get("request_sla_risks", 0),
            "meetings_next_24h": alert_dashboard["alert_counts"].get("meetings_next_24h", 0),
            "meetings_next_7d": upcoming_week_count,
            "meeting_overdue": alert_dashboard["alert_counts"].get("meeting_overdue", 0),
            "manager_hotspots": alert_dashboard["alert_counts"].get("manager_hotspots", 0),
            "recipient_suggestions": len(recipient_suggestions),
        },
        "request_status_rows": [
            {"status": key, "count": value}
            for key, value in sorted(request_status_counts.items(), key=lambda item: (-int(item[1]), item[0]))
        ],
        "request_age_buckets": request_age_buckets,
        "priority_requests": alert_dashboard.get("request_alerts", [])[:6],
        "priority_meetings": alert_dashboard.get("meeting_alerts", [])[:6],
        "manager_rows": alert_dashboard.get("manager_rows", [])[:8],
        "next_meetings": next_meetings[:8],
        "recipient_rows": [
            {
                "user_id": getattr(user, "id", None),
                "name": _full_name(user),
                "role": getattr(user, "role", None) or "-",
                "email": _safe_email(user) or "-",
            }
            for user in recipient_suggestions[:12]
        ],
        "suggested_recipient_ids": [int(user.id) for user in recipient_suggestions if getattr(user, "id", None)],
        "digest_subject": subject,
        "digest_body_plain": body_plain,
    }

def dispatch_feedback_executive_summary(
    requests_list: list[Any],
    meetings: list[Any],
    *,
    preset: str = "daily",
    recipients: Iterable[Any] | None = None,
    actor_user_id: int | None = None,
    scope_label: str | None = None,
    scope_role_title: str | None = None,
    now: datetime | None = None,
    send_mail: bool = False,
) -> dict[str, Any]:
    now = now or utc_now()
    preset = (preset or "daily").strip().lower()
    if preset not in SUMMARY_PRESET_LABELS:
        preset = "daily"

    overall_summary = build_feedback_executive_summary(
        requests_list,
        meetings,
        preset=preset,
        scope_label=scope_label,
        scope_role_title=scope_role_title,
        now=now,
    )
    recipient_users = _normalize_recipient_users(recipients) or _suggest_recipient_users(requests_list, meetings)
    source_id = _summary_source_id(now, preset)
    result = {
        "preset": preset,
        "recipient_count": len(recipient_users),
        "notification_sent": 0,
        "notification_skipped": 0,
        "mail_success_count": 0,
        "mail_failed_count": 0,
        "mail_failed_items": [],
        "subject": overall_summary["digest_subject"],
    }

    for user in recipient_users:
        user_id = getattr(user, "id", None)
        if not user_id:
            continue
        # #57: each recipient's digest is built only from the records that recipient is related to
        # (the same party/duty rule as the pages); a recipient with no such record gets nothing.
        own_requests = [req for req in requests_list if int(user_id) in _related_request_ids(req)]
        own_meetings = [meeting for meeting in meetings if int(user_id) in _related_meeting_ids(meeting)]
        if not own_requests and not own_meetings:
            result["notification_skipped"] += 1
            continue
        summary = build_feedback_executive_summary(
            own_requests,
            own_meetings,
            preset=preset,
            scope_label=scope_label,
            scope_role_title=scope_role_title,
            now=now,
        )
        notification_body = (
            f"Açık talep: {summary['cards']['open_requests']} · "
            f"SLA riski: {summary['cards']['request_sla_risks']} · "
            f"24 saat içinde görüşme: {summary['cards']['meetings_next_24h']} · "
            f"Geciken görüşme: {summary['cards']['meeting_overdue']}"
        )
        priority = "high" if summary["cards"].get("request_sla_risks") or summary["cards"].get("meeting_overdue") else "normal"
        if _summary_notification_exists(user_id=int(user_id), preset=preset, source_id=source_id):
            result["notification_skipped"] += 1
        else:
            notify_user(
                int(user_id),
                title=summary["digest_subject"],
                body=notification_body,
                notification_type=f"performance_feedback_digest_{preset}",
                source_type="feedback_digest",
                source_id=source_id,
                link_url=f"/performance/feedback-executive-summary?preset={preset}",
                priority=priority,
            )
            result["notification_sent"] += 1

        if send_mail:
            email = _safe_email(user)
            if email:
                ok, message = send_email(email, summary["digest_subject"], summary["digest_body_plain"])
                if ok:
                    result["mail_success_count"] += 1
                else:
                    result["mail_failed_count"] += 1
                    result["mail_failed_items"].append(
                        {
                            "user_id": int(user_id),
                            "name": _full_name(user),
                            "email": email,
                            "error": message,
                        }
                    )

    return {**result, "summary": overall_summary, "source_id": source_id}