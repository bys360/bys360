from __future__ import annotations

import csv
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    Notification,
    SupportHelpArticle,
    SupportTicket,
    Survey,
    SurveyAssignment,
    SurveyResponse,
)
from app.models.communication_phase1_models import (
    CommunicationBulletin,
    CommunicationBulletinReceipt,
)
from app.models.communication_phase3_models import CommunicationSupportSlaPolicy
from app.models.communication_phase4_models import (
    CommunicationDailyMetric,
    CommunicationExecutiveReport,
    CommunicationGovernanceReview,
    CommunicationReportExportLog,
)
from app.services.communication_phase1_service import BULLETIN_PRIORITY_LABELS
from app.services.communication_phase2_service import SURVEY_STATUS_LABELS
from app.services.communication_phase3_service import SUPPORT_STATUS_LABELS

logger = logging.getLogger(__name__)

MANAGER_ROLES = {
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "birim_sorumlusu",
}

SUPPORT_OPEN_STATUSES = {"open", "reviewing", "waiting_info", "assigned", "planned"}
BULLETIN_PUBLISHED_STATUSES = {"published", "yayinda"}
SURVEY_ACTIVE_STATUSES = {"published", "active", "yayinda"}

REPORT_STATUS_LABELS = {
    "draft": "Taslak",
    "review": "İncelemede",
    "approved": "Onaylandı",
    "revision": "Revizyon İstendi",
    "rejected": "Reddedildi",
}

# app/communication/phase4_routes.py'nin `report_type` form alanı yalnızca bu
# üç değeri gönderir (bkz. app/templates/communication/phase4_reports.html'in
# <select name="report_type"> seçenekleri) -- kapalı bir sözlük olduğu için
# etiketler burada sabit tutulur, `.replace('_', ' ').title()` gibi ham
# değeri yansıtan bir dönüştürme kullanılmaz.
REPORT_TYPE_LABELS = {
    "weekly_summary": "Haftalık Özet",
    "executive_brief": "Yönetici Brifi",
    "scorecard": "Skor Kartı",
}

# Phase 4 analytics rows also see the legacy ASCII-Turkish "yayinda" and the
# generic "active" values (see SURVEY_ACTIVE_STATUSES/BULLETIN_PUBLISHED_STATUSES
# above) alongside the standard Survey.status vocabulary -- extend the shared
# phase2 dict rather than duplicating it.
SURVEY_ANALYTICS_STATUS_LABELS = {
    **SURVEY_STATUS_LABELS,
    "active": "Aktif",
    "yayinda": "Yayında",
}


class CommunicationPhase4Error(RuntimeError):
    pass


def _now() -> datetime:
    return utc_now()


def safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase4_service.py | line=59")
        return default


def sanitize_days(value: Any, default: int = 30, minimum: int = 7, maximum: int = 365) -> int:
    days = _safe_int(value, default)
    if days < minimum:
        return minimum
    if days > maximum:
        return maximum
    return days


def is_manager(user: Any) -> bool:
    return safe_str(getattr(user, "role", "")).lower() in MANAGER_ROLES


def user_display_name(user: Any) -> str:
    if not user:
        return "-"
    for attr in ("full_name", "full_name_cache"):
        value = safe_str(getattr(user, attr, ""))
        if value:
            return value
    ad = safe_str(getattr(user, "ad", ""))
    soyad = safe_str(getattr(user, "soyad", ""))
    return f"{ad} {soyad}".strip() or safe_str(getattr(user, "email", "")) or "-"


def _query_count(query) -> int:
    try:
        return int(query.count())
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase4_service.py | line=91")
        return 0


def _safe_attr(row: Any, *names: str, default=None):
    for name in names:
        if hasattr(row, name):
            value = getattr(row, name)
            if value is not None:
                return value
    return default


def _labeled_counter(raw_counter: Counter, label_map: dict[str, str]) -> Counter:
    """Re-key a raw-value Counter through a display-label map, merging counts
    for any raw values that share the same label instead of dropping one."""
    labeled: Counter[str] = Counter()
    for raw_value, count in raw_counter.items():
        labeled[label_map.get(raw_value, "Bilinmiyor")] += count
    return labeled


def _period_range(days: int = 30) -> tuple[datetime, datetime]:
    clean_days = sanitize_days(days)
    end = _now()
    start = end - timedelta(days=clean_days)
    return start, end


def _load_bulletins(days: int = 30):
    start, _ = _period_range(days)
    query = CommunicationBulletin.query
    if hasattr(CommunicationBulletin, "created_at"):
        query = query.filter(CommunicationBulletin.created_at >= start)
    return query.order_by(CommunicationBulletin.created_at.desc()).all()


def _load_surveys(days: int = 90):
    start, _ = _period_range(days)
    query = Survey.query
    if hasattr(Survey, "created_at"):
        query = query.filter(Survey.created_at >= start)
    return query.order_by(Survey.created_at.desc()).all()


_ALL_TICKETS = object()


def _load_tickets(days: int = 90, viewer: Any = _ALL_TICKETS):
    """K5: a rendered or exported view passes its viewer; only institution-wide counts (no row
    data, refresh_daily_metrics) read every ticket."""
    start, _ = _period_range(days)
    query = SupportTicket.query
    if viewer is not _ALL_TICKETS:
        from app.services.support_ticket_access import support_ticket_visibility_clause

        query = query.filter(support_ticket_visibility_clause(viewer))
    if hasattr(SupportTicket, "created_at"):
        query = query.filter(SupportTicket.created_at >= start)
    return query.order_by(SupportTicket.created_at.desc()).all()


def _sla_policy_map() -> dict[str, dict[str, int]]:
    policies = {}
    try:
        rows = CommunicationSupportSlaPolicy.query.filter_by(is_active=True).all()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase4_service.py | line=139")
        rows = []
    for row in rows:
        policies[safe_str(getattr(row, "priority", "normal")).lower()] = {
            "first": int(getattr(row, "first_response_target_hours", 24) or 24),
            "resolution": int(getattr(row, "resolution_target_hours", 72) or 72),
        }
    if not policies:
        policies = {
            "low": {"first": 48, "resolution": 120},
            "normal": {"first": 24, "resolution": 72},
            "high": {"first": 8, "resolution": 48},
            "critical": {"first": 4, "resolution": 24},
        }
    return policies


def _metric_series(metric_group: str, metric_name: str, days: int = 14) -> dict[str, Any]:
    clean_days = sanitize_days(days, default=14, minimum=7, maximum=60)
    start_date = date.today() - timedelta(days=clean_days - 1)
    rows = CommunicationDailyMetric.query.filter(
        CommunicationDailyMetric.metric_group == metric_group,
        CommunicationDailyMetric.metric_name == metric_name,
        CommunicationDailyMetric.metric_date >= start_date,
    ).order_by(CommunicationDailyMetric.metric_date.asc()).all()

    value_map = {row.metric_date.isoformat(): float(getattr(row, "metric_value", 0) or 0) for row in rows}
    labels = []
    values = []
    current = start_date
    while current <= date.today():
        key = current.isoformat()
        labels.append(key)
        values.append(value_map.get(key, 0))
        current += timedelta(days=1)

    return {
        "labels": labels,
        "values": values,
        "max_value": max(values) if values else 0,
        "last_value": values[-1] if values else 0,
    }

def _json_safe(value: Any):
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value

def _score_band_label(rate: float) -> str:
    if rate >= 75:
        return "75-100"
    if rate >= 50:
        return "50-74"
    if rate >= 25:
        return "25-49"
    return "0-24"


def executive_summary_snapshot(days: int = 30, *, viewer: Any = _ALL_TICKETS) -> dict[str, Any]:
    clean_days = sanitize_days(days)
    bulletins = _load_bulletins(clean_days)
    surveys = _load_surveys(max(clean_days, 90))
    tickets = _load_tickets(max(clean_days, 90), viewer=viewer)

    unread_notifications = 0
    critical_unread = 0
    try:
        unread_notifications = _query_count(Notification.query.filter_by(is_read=False))
        critical_unread = _query_count(Notification.query.filter_by(is_read=False, priority="critical"))
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/communication_phase4_service.py")
    bulletin_published = [row for row in bulletins if safe_str(getattr(row, "status", "")).lower() in BULLETIN_PUBLISHED_STATUSES]
    bulletin_receipts = 0
    bulletin_reads = 0
    try:
        receipt_rows = CommunicationBulletinReceipt.query.filter(
            CommunicationBulletinReceipt.bulletin_id.in_([row.id for row in bulletin_published] or [-1])
        ).all()
        bulletin_receipts = len(receipt_rows)
        bulletin_reads = sum(1 for row in receipt_rows if bool(getattr(row, "is_read", False)))
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase4_service.py | line=227")
        receipt_rows = []

    survey_rows = [row for row in surveys if safe_str(getattr(row, "status", "")).lower() in SURVEY_ACTIVE_STATUSES | {"closed", "archived", "draft"}]
    survey_metrics = []
    low_completion_rows = []
    for survey in survey_rows[:20]:
        title = safe_str(getattr(survey, "title", "Anket"))
        assignments = _query_count(SurveyAssignment.query.filter_by(survey_id=survey.id))
        responses = _query_count(SurveyResponse.query.filter_by(survey_id=survey.id))
        completed = _query_count(SurveyResponse.query.filter_by(survey_id=survey.id, is_completed=True))
        rate = round((completed / assignments) * 100, 2) if assignments else 0.0
        row = {
            "id": survey.id,
            "title": title,
            "assignments": assignments,
            "responses": responses,
            "completed": completed,
            "completion_rate": rate,
            "status": safe_str(getattr(survey, "status", "")) or "draft",
        }
        survey_metrics.append(row)
        if assignments >= 5 and rate < 50:
            low_completion_rows.append(row)

    policy_map = _sla_policy_map()
    support_status_counter: Counter[str] = Counter()
    overdue_first = 0
    overdue_resolution = 0
    support_rows = []
    for ticket in tickets:
        status = safe_str(_safe_attr(ticket, "status", default="open")).lower() or "open"
        priority = safe_str(_safe_attr(ticket, "priority", default="normal")).lower() or "normal"
        created_at = _safe_attr(ticket, "created_at", default=_now())
        first_response_at = _safe_attr(ticket, "first_response_at")
        resolved_at = _safe_attr(ticket, "resolved_at")
        policy = policy_map.get(priority, policy_map.get("normal", {"first": 24, "resolution": 72}))
        support_status_counter[status] += 1

        first_due = bool(created_at and not first_response_at and (_now() - created_at).total_seconds() > policy["first"] * 3600)
        resolution_anchor = resolved_at or _now()
        resolution_due = bool(created_at and status in SUPPORT_OPEN_STATUSES and (resolution_anchor - created_at).total_seconds() > policy["resolution"] * 3600)
        if first_due:
            overdue_first += 1
        if resolution_due:
            overdue_resolution += 1

        support_rows.append({
            "id": ticket.id,
            "title": safe_str(getattr(ticket, "title", "Destek Talebi")),
            "status": status,
            "priority": priority,
            "created_by": user_display_name(getattr(ticket, "created_by", None)),
            "assigned_to": user_display_name(getattr(ticket, "assigned_to", None)),
            "created_at": created_at,
            "first_response_due": first_due,
            "resolution_due": resolution_due,
            "age_days": max((_now() - created_at).days, 0) if created_at else 0,
        })

    help_popular = []
    try:
        help_rows = SupportHelpArticle.query.order_by(SupportHelpArticle.view_count.desc(), SupportHelpArticle.id.desc()).limit(5).all()
        for row in help_rows:
            help_popular.append({
                "id": row.id,
                "title": safe_str(getattr(row, "title", "Makale")),
                "category": safe_str(getattr(row, "category", "Genel")) or "Genel",
                "view_count": int(getattr(row, "view_count", 0) or 0),
            })
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase4_service.py | line=297")
        help_popular = []

    recommendations = []
    if critical_unread:
        recommendations.append(f"Okunmamış kritik bildirim sayısı {critical_unread}; üst menü uyarı bandı güçlendirilmeli.")
    if overdue_first:
        recommendations.append(f"İlk geri dönüş SLA’sı aşılmış {overdue_first} destek kaydı var.")
    if overdue_resolution:
        recommendations.append(f"Çözüm SLA riski taşıyan {overdue_resolution} destek kaydı için sorumlu bazlı takip önerilir.")
    if low_completion_rows:
        recommendations.append(f"Katılımı düşük {len(low_completion_rows)} anket için toplu hatırlatma önerilir.")
    if bulletin_receipts and bulletin_reads / max(bulletin_receipts, 1) < 0.6:
        recommendations.append("Duyuru okuma oranı düşük; kritik duyurularda zorunlu okundu akışı değerlendirilmeli.")

    support_rows.sort(key=lambda item: (not item["resolution_due"], not item["first_response_due"], -item["age_days"]))
    low_completion_rows.sort(key=lambda item: (item["completion_rate"], -item["assignments"], item["title"].lower()))

    return {
        "days": clean_days,
        "headline": {
            "published_bulletins": len(bulletin_published),
            "bulletin_read_rate": round((bulletin_reads / bulletin_receipts) * 100, 2) if bulletin_receipts else 0.0,
            "survey_count": len(survey_rows),
            "open_tickets": sum(count for status, count in support_status_counter.items() if status in SUPPORT_OPEN_STATUSES),
            "unread_notifications": unread_notifications,
            "critical_unread": critical_unread,
            "overdue_first_response": overdue_first,
            "overdue_resolution": overdue_resolution,
        },
        "survey_metrics": survey_metrics[:8],
        "risk_surveys": low_completion_rows[:5],
        "survey_status_labels": SURVEY_ANALYTICS_STATUS_LABELS,
        "support_rows": support_rows[:10],
        "risk_support_rows": support_rows[:5],
        "support_status_breakdown": dict(support_status_counter),
        "top_help_articles": help_popular,
        "recommendations": recommendations,
        "trends": {
            "bulletins": _metric_series("bulletins", "published_count", min(clean_days, 30)),
            "read_rate": _metric_series("bulletins", "read_rate", min(clean_days, 30)),
            "surveys": _metric_series("surveys", "count", min(clean_days, 30)),
            "open_tickets": _metric_series("support", "open_count", min(clean_days, 30)),
            "unread_notifications": _metric_series("notifications", "unread_count", min(clean_days, 30)),
        },
    }


def survey_analytics_snapshot(days: int = 180) -> dict[str, Any]:
    clean_days = sanitize_days(days, default=180, minimum=30, maximum=365)
    rows = _load_surveys(clean_days)
    surveys = []
    status_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    band_counter = Counter({"0-24": 0, "25-49": 0, "50-74": 0, "75-100": 0})
    anonymous_count = 0
    submit_durations = []

    for survey in rows:
        assignments = _query_count(SurveyAssignment.query.filter_by(survey_id=survey.id))
        responses = SurveyResponse.query.filter_by(survey_id=survey.id).all()
        completed = sum(1 for row in responses if bool(getattr(row, "is_completed", False)))
        avg_submit_minutes = 0.0
        durations = []
        for response in responses:
            created_at = _safe_attr(response, "created_at")
            submitted_at = _safe_attr(response, "submitted_at")
            if created_at and submitted_at:
                durations.append(max((submitted_at - created_at).total_seconds() / 60.0, 0.0))
        if durations:
            avg_submit_minutes = round(sum(durations) / len(durations), 1)
            submit_durations.extend(durations)

        row = {
            "id": survey.id,
            "title": safe_str(getattr(survey, "title", "Anket")),
            "type": safe_str(getattr(survey, "survey_type", "genel")) or "genel",
            "status": safe_str(getattr(survey, "status", "draft")) or "draft",
            "assignments": assignments,
            "responses": len(responses),
            "completed": completed,
            "completion_rate": round((completed / assignments) * 100, 2) if assignments else 0.0,
            "avg_submit_minutes": avg_submit_minutes,
            "anonymous": bool(getattr(survey, "is_anonymous", False)),
            "created_at": _safe_attr(survey, "created_at"),
        }
        surveys.append(row)
        status_counter[row["status"]] += 1
        type_counter[row["type"]] += 1
        band_counter[_score_band_label(row["completion_rate"])] += 1
        if row["anonymous"]:
            anonymous_count += 1

    surveys.sort(key=lambda item: (item["completion_rate"], -item["assignments"], item["title"].lower()))
    low_completion_rows = [row for row in surveys if row["assignments"] >= 5 and row["completion_rate"] < 50][:10]
    fastest_rows = sorted([row for row in surveys if row["avg_submit_minutes"] > 0], key=lambda item: item["avg_submit_minutes"])[:5]
    slowest_rows = sorted([row for row in surveys if row["avg_submit_minutes"] > 0], key=lambda item: -item["avg_submit_minutes"])[:5]

    return {
        "days": clean_days,
        "totals": {
            "survey_count": len(surveys),
            "published_count": sum(1 for row in surveys if row["status"] in SURVEY_ACTIVE_STATUSES),
            "low_completion_count": sum(1 for row in surveys if row["completion_rate"] < 50 and row["assignments"] >= 5),
            "average_completion_rate": round(sum(row["completion_rate"] for row in surveys) / len(surveys), 2) if surveys else 0.0,
            "anonymous_count": anonymous_count,
            "average_submit_minutes": round(sum(submit_durations) / len(submit_durations), 1) if submit_durations else 0.0,
        },
        "status_breakdown": dict(status_counter),
        "status_label_breakdown": dict(_labeled_counter(status_counter, SURVEY_ANALYTICS_STATUS_LABELS)),
        "type_breakdown": dict(type_counter),
        "band_breakdown": dict(band_counter),
        "low_completion_rows": low_completion_rows,
        "fastest_rows": fastest_rows,
        "slowest_rows": slowest_rows,
        "rows": sorted(surveys, key=lambda item: (-item["completion_rate"], -item["responses"], item["title"].lower())),
        "survey_status_labels": SURVEY_ANALYTICS_STATUS_LABELS,
    }


def support_analytics_snapshot(days: int = 180, *, viewer: Any = _ALL_TICKETS) -> dict[str, Any]:
    clean_days = sanitize_days(days, default=180, minimum=30, maximum=365)
    rows = _load_tickets(clean_days, viewer=viewer)
    policy_map = _sla_policy_map()
    status_counter: Counter[str] = Counter()
    priority_counter: Counter[str] = Counter()
    assignee_counter: Counter[str] = Counter()
    age_buckets = {"0-2 gün": 0, "3-7 gün": 0, "8-14 gün": 0, "15+ gün": 0}
    detailed_rows = []
    total_age = 0

    for ticket in rows:
        status = safe_str(_safe_attr(ticket, "status", default="open")).lower() or "open"
        priority = safe_str(_safe_attr(ticket, "priority", default="normal")).lower() or "normal"
        created_at = _safe_attr(ticket, "created_at", default=_now())
        age_days = max((_now() - created_at).days, 0) if created_at else 0
        total_age += age_days
        if age_days <= 2:
            age_buckets["0-2 gün"] += 1
        elif age_days <= 7:
            age_buckets["3-7 gün"] += 1
        elif age_days <= 14:
            age_buckets["8-14 gün"] += 1
        else:
            age_buckets["15+ gün"] += 1

        status_counter[status] += 1
        priority_counter[priority] += 1
        assigned_to = user_display_name(getattr(ticket, "assigned_to", None))
        if assigned_to and assigned_to != "-":
            assignee_counter[assigned_to] += 1
        policy = policy_map.get(priority, policy_map.get("normal", {"first": 24, "resolution": 72}))
        first_response_due = bool(created_at and not _safe_attr(ticket, "first_response_at") and (_now() - created_at).total_seconds() > policy["first"] * 3600)
        resolution_due = bool(created_at and status in SUPPORT_OPEN_STATUSES and (_now() - created_at).total_seconds() > policy["resolution"] * 3600)

        detailed_rows.append({
            "id": ticket.id,
            "title": safe_str(getattr(ticket, "title", "Destek")),
            "status": status,
            "priority": priority,
            "age_days": age_days,
            "assigned_to": assigned_to,
            "first_response_due": first_response_due,
            "resolution_due": resolution_due,
            "created_at": created_at,
        })

    detailed_rows.sort(key=lambda item: (not item["resolution_due"], not item["first_response_due"], -item["age_days"]))
    risk_rows = [row for row in detailed_rows if row["first_response_due"] or row["resolution_due"]][:10]
    oldest_rows = sorted(detailed_rows, key=lambda item: -item["age_days"])[:10]

    return {
        "days": clean_days,
        "totals": {
            "ticket_count": len(detailed_rows),
            "open_count": sum(count for status, count in status_counter.items() if status in SUPPORT_OPEN_STATUSES),
            "sla_risk_count": sum(1 for row in detailed_rows if row["first_response_due"] or row["resolution_due"]),
            "average_age_days": round(total_age / len(detailed_rows), 1) if detailed_rows else 0.0,
        },
        "status_breakdown": dict(status_counter),
        "status_label_breakdown": dict(_labeled_counter(status_counter, SUPPORT_STATUS_LABELS)),
        "priority_breakdown": dict(priority_counter),
        "age_buckets": age_buckets,
        "top_assignees": [{"name": name, "count": count} for name, count in assignee_counter.most_common(5)],
        "risk_rows": risk_rows,
        "oldest_rows": oldest_rows,
        "rows": detailed_rows,
        "status_labels": SUPPORT_STATUS_LABELS,
        "priority_labels": BULLETIN_PRIORITY_LABELS,
    }


def governance_snapshot() -> dict[str, Any]:
    reviews = CommunicationGovernanceReview.query.order_by(CommunicationGovernanceReview.created_at.desc()).limit(100).all()
    pending = [row for row in reviews if safe_str(getattr(row, "decision", "pending")) == "pending"]
    rows = []
    for row in reviews:
        rows.append({
            "id": row.id,
            "review_type": safe_str(getattr(row, "review_type", "")).lower() or "report",
            "target_id": int(getattr(row, "target_id", 0) or 0),
            "decision": safe_str(getattr(row, "decision", "pending")) or "pending",
            "requested_by": user_display_name(getattr(row, "requested_by", None)),
            "reviewed_by": user_display_name(getattr(row, "reviewed_by", None)),
            "review_note": safe_str(getattr(row, "review_note", "")),
            "created_at": getattr(row, "created_at", None),
            "reviewed_at": getattr(row, "reviewed_at", None),
        })
    return {
        "pending_count": len(pending),
        "rows": rows,
    }


def report_history_snapshot(limit: int = 25) -> dict[str, Any]:
    clean_limit = max(1, min(_safe_int(limit, 25), 100))
    rows = []
    for row in CommunicationExecutiveReport.query.order_by(CommunicationExecutiveReport.created_at.desc()).limit(clean_limit).all():
        rows.append({
            "id": row.id,
            "title": safe_str(getattr(row, "title", "")),
            "report_type": safe_str(getattr(row, "report_type", "")),
            "period_label": safe_str(getattr(row, "period_label", "")),
            "status": safe_str(getattr(row, "status", "draft")) or "draft",
            "status_label": REPORT_STATUS_LABELS.get(safe_str(getattr(row, "status", "draft")) or "draft", safe_str(getattr(row, "status", "draft"))),
            "created_by": user_display_name(getattr(row, "created_by", None)),
            "approved_by": user_display_name(getattr(row, "approved_by", None)),
            "approved_at": getattr(row, "approved_at", None),
            "created_at": getattr(row, "created_at", None),
        })
    return {"rows": rows}


def create_executive_report(actor_user: Any, report_type: str = "weekly_summary", days: int = 30) -> CommunicationExecutiveReport:
    clean_days = sanitize_days(days)
    # K5: the stored report carries only the ticket rows inside its author's scope.
    payload = executive_summary_snapshot(clean_days, viewer=actor_user)
    survey_payload = survey_analytics_snapshot(max(clean_days, 30))
    support_payload = support_analytics_snapshot(max(clean_days, 30), viewer=actor_user)
    today = _now().date().isoformat()
    title = f"İletişim ve Anket Yönetimi {REPORT_TYPE_LABELS.get(report_type, 'Bilinmiyor')} Raporu"
    summary_text = (
        f"{today} itibarıyla son {clean_days} gün görünümünde {payload['headline']['published_bulletins']} yayımlanmış duyuru, "
        f"{payload['headline']['survey_count']} anket ve {payload['headline']['open_tickets']} açık destek talebi bulunmaktadır. "
        f"Anket ortalama tamamlama oranı %{survey_payload['totals']['average_completion_rate']:.1f}, "
        f"destek kayıtlarında SLA riski taşıyan kayıt sayısı {support_payload['totals']['sla_risk_count']} düzeyindedir."
    )
    row = CommunicationExecutiveReport(
        title=title,
        report_type=report_type,
        period_label=f"Son {clean_days} Gün · {today}",
        status="draft",
        summary_text=summary_text,
        metrics_json=_json_safe({
            "headline": payload,
            "surveys": survey_payload,
            "support": support_payload,
        }),
        recommendations_json=payload.get("recommendations", []),
        created_by_user_id=getattr(actor_user, "id", None),
    )
    db.session.add(row)
    db.session.commit()
    return row


def submit_report_for_review(report_id: int, actor_user: Any, note: str = "") -> CommunicationGovernanceReview:
    report = CommunicationExecutiveReport.query.get_or_404(report_id)
    review = CommunicationGovernanceReview(
        review_type="report",
        target_id=report.id,
        decision="pending",
        review_note=note or None,
        requested_by_user_id=getattr(actor_user, "id", None),
    )
    db.session.add(review)
    report.status = "review"
    db.session.add(report)
    db.session.commit()
    return review


def decide_governance(review_id: int, actor_user: Any, decision: str, note: str = "") -> CommunicationGovernanceReview:
    review = CommunicationGovernanceReview.query.get_or_404(review_id)
    decision = safe_str(decision).lower() or "pending"
    if decision not in {"approved", "revision", "rejected", "pending"}:
        raise CommunicationPhase4Error("Geçersiz karar tipi.")
    review.decision = decision
    review.review_note = note or review.review_note
    review.reviewed_by_user_id = getattr(actor_user, "id", None)
    review.reviewed_at = _now()
    db.session.add(review)

    if safe_str(getattr(review, "review_type", "")) == "report":
        report = db.session.get(CommunicationExecutiveReport, review.target_id)
        if report:
            report.status = {
                "approved": "approved",
                "revision": "revision",
                "rejected": "rejected",
                "pending": "review",
            }[decision]
            if decision == "approved":
                report.approved_by_user_id = getattr(actor_user, "id", None)
                report.approved_at = _now()
            db.session.add(report)

    db.session.commit()
    return review


def refresh_daily_metrics(actor_user: Any | None = None) -> int:
    payload = executive_summary_snapshot(30)
    today = date.today()
    metrics = [
        ("bulletins", "published_count", payload["headline"]["published_bulletins"]),
        ("bulletins", "read_rate", payload["headline"]["bulletin_read_rate"]),
        ("surveys", "count", payload["headline"]["survey_count"]),
        ("support", "open_count", payload["headline"]["open_tickets"]),
        ("notifications", "unread_count", payload["headline"]["unread_notifications"]),
        ("support", "overdue_first_response", payload["headline"]["overdue_first_response"]),
        ("support", "overdue_resolution", payload["headline"]["overdue_resolution"]),
    ]
    changed = 0
    for metric_group, metric_name, metric_value in metrics:
        row = CommunicationDailyMetric.query.filter_by(
            metric_date=today,
            metric_group=metric_group,
            metric_name=metric_name,
        ).first()
        if not row:
            row = CommunicationDailyMetric(
                metric_date=today,
                metric_group=metric_group,
                metric_name=metric_name,
                captured_by_user_id=getattr(actor_user, "id", None),
            )
        row.metric_value = metric_value
        row.snapshot_json = payload["headline"]
        db.session.add(row)
        changed += 1
    db.session.commit()
    return changed


def _daily_metrics_export_rows(days: int = 90) -> list[dict[str, Any]]:
    clean_days = sanitize_days(days, default=90, minimum=30, maximum=365)
    start_date = date.today() - timedelta(days=clean_days - 1)
    rows = []
    for row in CommunicationDailyMetric.query.filter(CommunicationDailyMetric.metric_date >= start_date).order_by(
        CommunicationDailyMetric.metric_date.desc(),
        CommunicationDailyMetric.metric_group.asc(),
        CommunicationDailyMetric.metric_name.asc(),
    ).all():
        rows.append({
            "metric_date": getattr(row, "metric_date", None),
            "metric_group": safe_str(getattr(row, "metric_group", "")),
            "metric_name": safe_str(getattr(row, "metric_name", "")),
            "metric_value": float(getattr(row, "metric_value", 0) or 0),
            "captured_at": getattr(row, "captured_at", None),
        })
    return rows


def export_rows_csv(actor_user: Any, export_type: str, days: int = 180) -> tuple[str, bytes, int]:
    export_type = safe_str(export_type).lower() or "survey_analytics"
    clean_days = sanitize_days(days, default=180, minimum=30, maximum=365)
    if export_type == "survey_analytics":
        payload = survey_analytics_snapshot(clean_days)
        rows = payload["rows"]
        headers = ["id", "title", "type", "status", "assignments", "responses", "completed", "completion_rate", "avg_submit_minutes", "anonymous"]
    elif export_type == "support_analytics":
        payload = support_analytics_snapshot(clean_days, viewer=actor_user)  # K5: scoped export
        rows = payload["rows"]
        headers = ["id", "title", "status", "priority", "age_days", "assigned_to", "first_response_due", "resolution_due", "created_at"]
    elif export_type == "executive_reports":
        rows = report_history_snapshot(limit=200)["rows"]
        headers = ["id", "title", "report_type", "period_label", "status", "created_by", "approved_by", "approved_at", "created_at"]
    elif export_type == "daily_metrics":
        rows = _daily_metrics_export_rows(clean_days)
        headers = ["metric_date", "metric_group", "metric_name", "metric_value", "captured_at"]
    else:
        raise CommunicationPhase4Error("Bilinmeyen dışa aktarma tipi.")

    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in headers})
    content = sio.getvalue().encode("utf-8-sig")
    file_name = f"communication_{export_type}_{_now().strftime('%Y%m%d_%H%M%S')}.csv"

    log = CommunicationReportExportLog(
        export_type=export_type,
        export_format="csv",
        file_name=file_name,
        created_by_user_id=getattr(actor_user, "id", None),
        criteria_json={"export_type": export_type, "days": clean_days},
        row_count=len(rows),
    )
    db.session.add(log)
    db.session.commit()
    return file_name, content, len(rows)


def export_center_snapshot(days: int = 90) -> dict[str, Any]:
    clean_days = sanitize_days(days, default=90, minimum=30, maximum=365)
    logs = CommunicationReportExportLog.query.order_by(CommunicationReportExportLog.created_at.desc()).limit(50).all()
    rows = []
    type_counter: Counter[str] = Counter()
    total_rows = 0
    for row in logs:
        export_type = safe_str(getattr(row, "export_type", ""))
        row_count = int(getattr(row, "row_count", 0) or 0)
        type_counter[export_type] += 1
        total_rows += row_count
        rows.append({
            "id": row.id,
            "export_type": export_type,
            "export_format": safe_str(getattr(row, "export_format", "csv")) or "csv",
            "file_name": safe_str(getattr(row, "file_name", "")),
            "row_count": row_count,
            "created_by": user_display_name(getattr(row, "created_by", None)),
            "created_at": getattr(row, "created_at", None),
            "criteria": getattr(row, "criteria_json", None) or {},
        })
    return {
        "days": clean_days,
        "rows": rows,
        "summary": {
            "export_count": len(rows),
            "total_rows": total_rows,
            "type_breakdown": dict(type_counter),
        },
    }
