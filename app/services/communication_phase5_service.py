from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import Notification, SupportTicket, Survey, User
from app.models.communication_phase3_models import CommunicationSupportSlaPolicy
from app.models.communication_phase5_models import (
    CommunicationAutomationLog,
    CommunicationDigestJob,
    CommunicationEscalationRule,
    CommunicationNotificationPreference,
    CommunicationOperationHealth,
    CommunicationRetentionPolicy,
)
from app.models.support_models import SupportTicketStatusHistory
from app.services.communication_gate_status_labels import gate_status_label
from app.services.surveys.listing import get_assigned_surveys_for_user

MANAGER_ROLES = {
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "birim_sorumlusu",
}
OPEN_TICKET_STATUSES = {"open", "reviewing", "waiting_info", "assigned", "planned", "acik", "islemde", "beklemede"}
PRIORITY_LABELS = {"low": "Düşük", "normal": "Normal", "high": "Yüksek", "critical": "Kritik"}
ROLE_LABELS = {
    "admin": "Admin",
    "baskan": "Başkan",
    "baskan_yardimcisi": "Başkan Yardımcısı",
    "grup_baskani": "Grup Başkanı",
    "mali_musavir": "Mali Müşavir",
    "birim_sorumlusu": "Birim Sorumlusu",
    "koordinator": "Koordinatör",
    "personel": "Personel",
}


class CommunicationPhase5Error(RuntimeError):
    pass


def _now() -> datetime:
    return utc_now()


def safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _coerce_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return safe_str(value).lower() in {"1", "true", "on", "yes", "evet"}


def _priority_rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "normal": 2, "low": 3}.get(safe_str(priority).lower(), 9)


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


def role_label(role_slug: str) -> str:
    return ROLE_LABELS.get(safe_str(role_slug).lower(), safe_str(role_slug) or "-")


def _get_or_create_preference(user_id: int) -> CommunicationNotificationPreference:
    row = CommunicationNotificationPreference.query.filter_by(user_id=user_id).first()
    if row:
        return row
    row = CommunicationNotificationPreference(user_id=user_id)
    db.session.add(row)
    db.session.flush()
    return row


def _active_user_count() -> int:
    query = User.query
    if hasattr(User, "is_active"):
        query = query.filter_by(is_active=True)
    return query.count()


def notification_preferences_snapshot(user: Any) -> dict[str, Any]:
    row = _get_or_create_preference(int(user.id))
    db.session.commit()
    digest_jobs = CommunicationDigestJob.query.filter_by(user_id=user.id).order_by(CommunicationDigestJob.created_at.desc()).limit(10).all()
    return {
        "preference": row,
        "digest_jobs": digest_jobs,
        "summary": {
            "digest_job_count": len(digest_jobs),
            "daily_enabled": bool(getattr(row, "daily_digest_enabled", False)),
            "weekly_enabled": bool(getattr(row, "weekly_digest_enabled", False)),
            "quiet_hours": bool(getattr(row, "quiet_hours_enabled", False)),
        },
    }


def update_notification_preferences(user: Any, form: Any) -> CommunicationNotificationPreference:
    row = _get_or_create_preference(int(user.id))
    row.in_app_enabled = _coerce_bool(form.get("in_app_enabled"))
    row.email_enabled = _coerce_bool(form.get("email_enabled"))
    row.daily_digest_enabled = _coerce_bool(form.get("daily_digest_enabled"))
    row.weekly_digest_enabled = _coerce_bool(form.get("weekly_digest_enabled"))
    row.quiet_hours_enabled = _coerce_bool(form.get("quiet_hours_enabled"))
    row.digest_hour = _coerce_int(form.get("digest_hour"), 9, 0, 23)
    row.quiet_hours_start = _coerce_int(form.get("quiet_hours_start"), 20, 0, 23)
    row.quiet_hours_end = _coerce_int(form.get("quiet_hours_end"), 8, 0, 23)
    db.session.add(row)
    log_action("update_preferences", user, "communication_notification_preferences", row.id, "Bildirim tercihleri güncellendi.")
    db.session.commit()
    return row


def _notification_counts(user_id: int) -> dict[str, int]:
    query = Notification.query.filter_by(user_id=user_id)
    total = query.count()
    unread = query.filter_by(is_read=False).count()
    return {"total": total, "unread": unread}


def _pending_survey_count(user: Any) -> int:
    # Same "Açık" count the web /surveys list shows for this user.
    return sum(1 for row in get_assigned_surveys_for_user(user) if row["state"]["key"] == "active")


def create_digest_job(user: Any, digest_type: str = "daily") -> CommunicationDigestJob:
    counts = _notification_counts(user.id)
    survey_pending = _pending_survey_count(user)
    ticket_open = SupportTicket.query.filter_by(created_by_user_id=user.id).filter(SupportTicket.status.in_(list(OPEN_TICKET_STATUSES))).count()
    label = f"{digest_type.title()} özeti - {date.today().isoformat()}"
    payload = {
        "notifications_unread": counts["unread"],
        "notifications_total": counts["total"],
        "surveys_pending": survey_pending,
        "tickets_open": ticket_open,
    }
    row = CommunicationDigestJob(
        user_id=user.id,
        digest_type=digest_type,
        period_label=label,
        status="completed",
        scheduled_for=_now(),
        executed_at=_now(),
        payload_json=payload,
        result_summary=(
            f"Okunmamış bildirim: {counts['unread']} | Açık destek talebi: {ticket_open} | Bekleyen anket: {survey_pending}"
        ),
    )
    db.session.add(row)
    db.session.flush()
    log_action("create_digest", user, "communication_digest_jobs", row.id, f"{digest_type.title()} özet oluşturuldu.")
    db.session.commit()
    return row


def _sla_map() -> dict[str, dict[str, int]]:
    rows = CommunicationSupportSlaPolicy.query.filter_by(is_active=True).all()
    payload = {}
    for row in rows:
        payload[safe_str(getattr(row, "priority", "normal")).lower()] = {
            "first": int(getattr(row, "first_response_target_hours", 24) or 24),
            "resolution": int(getattr(row, "resolution_target_hours", 72) or 72),
        }
    return payload or {
        "low": {"first": 48, "resolution": 120},
        "normal": {"first": 24, "resolution": 72},
        "high": {"first": 8, "resolution": 48},
        "critical": {"first": 4, "resolution": 24},
    }


def _ticket_age_hours(ticket: Any, now: datetime | None = None) -> float:
    now = now or _now()
    created_at = getattr(ticket, "created_at", None) or now
    return round(max((now - created_at).total_seconds() / 3600, 0), 1)


def _ticket_owner_snapshot(ticket: Any) -> str:
    assigned = getattr(ticket, "assigned_to", None)
    if assigned:
        return user_display_name(assigned)
    snapshot = safe_str(getattr(ticket, "full_name_snapshot", ""))
    return snapshot or "-"


def support_operations_snapshot(limit: int = 200) -> dict[str, Any]:
    from app.support.routes import SUPPORT_STATUS_CHOICES

    status_labels = dict(SUPPORT_STATUS_CHOICES)
    now = _now()
    tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).limit(limit).all()
    open_rows = []
    priority_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    assignee_counter: dict[tuple[int | None, str], int] = defaultdict(int)
    stale_rows = []
    unassigned_rows = []
    recent_history = SupportTicketStatusHistory.query.order_by(SupportTicketStatusHistory.created_at.desc()).limit(30).all()
    policies = _sla_map()

    for row in tickets:
        status = safe_str(getattr(row, "status", "")).lower()
        if status not in OPEN_TICKET_STATUSES:
            continue
        priority = safe_str(getattr(row, "priority", "normal")).lower() or "normal"
        age_hours = _ticket_age_hours(row, now)
        resolution_target = policies.get(priority, policies.get("normal", {"resolution": 72}))["resolution"]
        risk_ratio = 0 if resolution_target <= 0 else age_hours / float(resolution_target)
        payload = {
            "ticket": row,
            "priority": priority,
            "priority_label": PRIORITY_LABELS.get(priority, priority.title()),
            "status": status,
            "age_hours": age_hours,
            "target_hours": resolution_target,
            "risk_ratio": round(risk_ratio, 2),
            "assigned_name": _ticket_owner_snapshot(row),
        }
        open_rows.append(payload)
        priority_counts[priority] += 1
        status_counts[status] += 1
        assigned = getattr(row, "assigned_to", None)
        assignee_counter[(getattr(assigned, "id", None), user_display_name(assigned) if assigned else "Atanmamış")] += 1
        if not getattr(row, "assigned_to_user_id", None):
            unassigned_rows.append(payload)
        last_touch = getattr(row, "updated_at", None) or getattr(row, "created_at", None) or now
        if (now - last_touch) >= timedelta(hours=48):
            stale_rows.append(payload)

    open_rows.sort(key=lambda item: (_priority_rank(item["priority"]), -item["risk_ratio"], -item["age_hours"]))
    stale_rows.sort(key=lambda item: (-item["age_hours"], _priority_rank(item["priority"])))
    unassigned_rows.sort(key=lambda item: (_priority_rank(item["priority"]), -item["age_hours"]))
    assignee_load: list[dict[str, Any]] = [
        {"user_id": key[0], "name": key[1], "open_count": count}
        for key, count in assignee_counter.items()
    ]
    assignee_load.sort(key=lambda item: (-item["open_count"], item["name"].lower()))

    return {
        "summary": {
            "open_total": len(open_rows),
            "unassigned_total": len(unassigned_rows),
            "stale_total": len(stale_rows),
            "critical_total": priority_counts.get("critical", 0),
        },
        "priority_counts": dict(priority_counts),
        "status_counts": dict(status_counts),
        "queue": open_rows[:50],
        "stale_rows": stale_rows[:20],
        "unassigned_rows": unassigned_rows[:20],
        "assignee_load": assignee_load[:20],
        "recent_history": recent_history,
        "status_labels": status_labels,
    }


def automation_center_snapshot() -> dict[str, Any]:
    prefs_total = CommunicationNotificationPreference.query.count()
    active_users = _active_user_count()
    digest_total = CommunicationDigestJob.query.count()
    failed_logs = CommunicationAutomationLog.query.filter_by(status="failed").count()
    active_rules = CommunicationEscalationRule.query.filter_by(is_active=True).count()
    inactive_rules = CommunicationEscalationRule.query.filter_by(is_active=False).count()
    logs = CommunicationAutomationLog.query.order_by(CommunicationAutomationLog.executed_at.desc()).limit(20).all()
    policies = CommunicationRetentionPolicy.query.order_by(CommunicationRetentionPolicy.data_scope.asc()).all()
    rules = CommunicationEscalationRule.query.order_by(CommunicationEscalationRule.priority.asc(), CommunicationEscalationRule.threshold_hours.asc()).all()
    enabled_daily = CommunicationNotificationPreference.query.filter_by(daily_digest_enabled=True).count()
    enabled_weekly = CommunicationNotificationPreference.query.filter_by(weekly_digest_enabled=True).count()
    quiet_hours = CommunicationNotificationPreference.query.filter_by(quiet_hours_enabled=True).count()
    recent_failures = CommunicationAutomationLog.query.filter_by(status="failed").order_by(CommunicationAutomationLog.executed_at.desc()).limit(10).all()
    recent_jobs = CommunicationDigestJob.query.order_by(CommunicationDigestJob.executed_at.desc().nullslast(), CommunicationDigestJob.created_at.desc()).limit(12).all()
    coverage_rate = round((prefs_total / active_users) * 100, 1) if active_users else 0.0
    return {
        "summary": {
            "preference_count": prefs_total,
            "active_user_count": active_users,
            "coverage_rate": coverage_rate,
            "digest_job_count": digest_total,
            "active_rule_count": active_rules,
            "inactive_rule_count": inactive_rules,
            "recent_log_count": len(logs),
            "failed_log_count": failed_logs,
            "daily_enabled_count": enabled_daily,
            "weekly_enabled_count": enabled_weekly,
            "quiet_hours_count": quiet_hours,
        },
        "recent_logs": [
            {
                "action_type": row.action_type,
                "status": row.status,
                "status_label": gate_status_label(row.status),
                "executed_at": row.executed_at,
            }
            for row in logs
        ],
        "recent_jobs": [
            {
                "user_id": row.user_id,
                "digest_type": row.digest_type,
                "status": row.status,
                "status_label": gate_status_label(row.status),
                "result_summary": row.result_summary,
            }
            for row in recent_jobs
        ],
        "recent_failures": recent_failures,
        "rules": rules,
        "policies": policies,
    }


def escalation_snapshot() -> dict[str, Any]:
    rules = CommunicationEscalationRule.query.order_by(CommunicationEscalationRule.priority.asc(), CommunicationEscalationRule.threshold_hours.asc()).all()
    policies = _sla_map()
    tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).limit(300).all()
    breaches = []
    nearing = []
    now = _now()
    assignee_counter: dict[tuple[int | None, str], int] = defaultdict(int)
    for row in tickets:
        status = safe_str(getattr(row, "status", "")).lower()
        if status not in OPEN_TICKET_STATUSES:
            continue
        priority = safe_str(getattr(row, "priority", "normal")).lower() or "normal"
        cfg = policies.get(priority, policies.get("normal", {"resolution": 72}))
        created_at = getattr(row, "created_at", None) or now
        age_hours = round((now - created_at).total_seconds() / 3600, 1)
        target_hours = int(cfg.get("resolution", 72) or 72)
        breach_hours = round(age_hours - target_hours, 1)
        payload = {
            "ticket": row,
            "priority": priority,
            "priority_label": PRIORITY_LABELS.get(priority, priority.title()),
            "age_hours": age_hours,
            "target_hours": target_hours,
            "breach_hours": breach_hours,
        }
        if age_hours >= target_hours:
            breaches.append(payload)
        elif target_hours and age_hours >= target_hours * 0.8:
            nearing.append(payload)
        assigned = getattr(row, "assigned_to", None)
        assignee_counter[(getattr(assigned, "id", None), user_display_name(assigned) if assigned else "Atanmamış")] += 1
    breaches.sort(key=lambda item: (-item["breach_hours"], -item["age_hours"]))
    nearing.sort(key=lambda item: (_priority_rank(item["priority"]), -item["age_hours"]))
    assignee_load: list[dict[str, Any]] = [{"user_id": key[0], "name": key[1], "open_count": count} for key, count in assignee_counter.items()]
    assignee_load.sort(key=lambda item: (-item["open_count"], item["name"].lower()))
    return {
        "rules": rules,
        "breaches": breaches[:50],
        "nearing": nearing[:30],
        "assignee_load": assignee_load[:20],
        "summary": {
            "rule_count": len(rules),
            "breach_count": len(breaches),
            "nearing_count": len(nearing),
            "critical_breach_count": sum(1 for item in breaches if item["priority"] == "critical"),
        },
    }


def create_or_update_escalation_rule(actor: Any, form: Any) -> CommunicationEscalationRule:
    rule_id = _coerce_int(form.get("rule_id"), 0, 0)
    if rule_id:
        row = db.session.get(CommunicationEscalationRule, rule_id)
        if not row:
            raise CommunicationPhase5Error("Güncellenecek kural bulunamadı.")
        action = "update_escalation_rule"
    else:
        row = CommunicationEscalationRule()
        action = "create_escalation_rule"
    row.module_name = safe_str(form.get("module_name") or "support") or "support"
    row.priority = safe_str(form.get("priority") or "normal") or "normal"
    row.trigger_type = safe_str(form.get("trigger_type") or "sla_breach") or "sla_breach"
    row.threshold_hours = _coerce_int(form.get("threshold_hours"), 24, 1, 720)
    row.target_role = safe_str(form.get("target_role") or "") or None
    target_user_id = _coerce_int(form.get("target_user_id"), 0, 0)
    row.target_user_id = target_user_id or None
    row.notify_template = safe_str(form.get("notify_template") or "") or None
    row.is_active = _coerce_bool(form.get("is_active") or True)
    db.session.add(row)
    db.session.flush()
    log_action(action, actor, "communication_escalation_rules", row.id, "SLA/escalation kuralı kaydedildi.")
    db.session.commit()
    return row


RETENTION_SCOPE_LABELS = {
    "notifications": "Bildirimler",
    "support": "Destek",
    "surveys": "Anketler",
    "digest_logs": "Özet Logları",
    "automation_logs": "Otomasyon Logları",
}


def retention_snapshot() -> dict[str, Any]:
    policies = CommunicationRetentionPolicy.query.order_by(CommunicationRetentionPolicy.data_scope.asc()).all()
    now = _now()
    stats = []
    for scope in ("notifications", "support", "surveys", "digest_logs", "automation_logs"):
        if scope == "notifications":
            total = Notification.query.count()
            old = Notification.query.filter(Notification.created_at < now - timedelta(days=365)).count()
        elif scope == "support":
            total = SupportTicket.query.count()
            old = SupportTicket.query.filter(SupportTicket.created_at < now - timedelta(days=365)).count()
        elif scope == "surveys":
            total = Survey.query.count()
            old = Survey.query.filter(Survey.created_at < now - timedelta(days=365)).count()
        elif scope == "digest_logs":
            total = CommunicationDigestJob.query.count()
            old = CommunicationDigestJob.query.filter(CommunicationDigestJob.created_at < now - timedelta(days=365)).count()
        else:
            total = CommunicationAutomationLog.query.count()
            old = CommunicationAutomationLog.query.filter(CommunicationAutomationLog.created_at < now - timedelta(days=365)).count()
        ratio = round((old / total) * 100, 1) if total else 0.0
        status = "warning" if old > 0 and ratio >= 50 else "ok"
        stats.append({
            "scope": scope,
            "scope_label": RETENTION_SCOPE_LABELS.get(scope, "Bilinmiyor"),
            "total": total,
            "older_than_1y": old,
            "old_ratio": ratio,
            "status": status,
            "status_label": gate_status_label(status),
        })
    return {
        "policies": policies,
        "stats": stats,
        "scope_labels": RETENTION_SCOPE_LABELS,
        "summary": {
            "policy_count": len(policies),
            "warning_scope_count": sum(1 for item in stats if item["status"] == "warning"),
        },
    }


def create_or_update_retention_policy(actor: Any, form: Any) -> CommunicationRetentionPolicy:
    policy_id = _coerce_int(form.get("policy_id"), 0, 0)
    if policy_id:
        row = db.session.get(CommunicationRetentionPolicy, policy_id)
        if not row:
            raise CommunicationPhase5Error("Güncellenecek saklama politikası bulunamadı.")
        action = "update_retention_policy"
    else:
        row = CommunicationRetentionPolicy()
        action = "create_retention_policy"
    row.data_scope = safe_str(form.get("data_scope") or "notifications") or "notifications"
    row.keep_days = _coerce_int(form.get("keep_days"), 365, 1, 3650)
    row.archive_after_days = _coerce_int(form.get("archive_after_days"), row.keep_days, 0, 3650) or None
    row.anonymize_after_days = _coerce_int(form.get("anonymize_after_days"), 0, 0, 3650) or None
    row.purge_after_days = _coerce_int(form.get("purge_after_days"), row.keep_days, 0, 3650) or None
    row.is_active = _coerce_bool(form.get("is_active") or True)
    row.notes = safe_str(form.get("notes") or "") or None
    db.session.add(row)
    db.session.flush()
    log_action(action, actor, "communication_retention_policies", row.id, "Saklama politikası kaydedildi.")
    db.session.commit()
    return row


def health_snapshot() -> dict[str, Any]:
    unread_total = Notification.query.filter_by(is_read=False).count()
    tickets_open = SupportTicket.query.filter(SupportTicket.status.in_(list(OPEN_TICKET_STATUSES))).count()
    survey_active = Survey.query.filter(Survey.status.in_(["published", "active", "yayinda"])).count()
    failed_logs = CommunicationAutomationLog.query.filter_by(status="failed").count()
    recent_checks = CommunicationOperationHealth.query.order_by(CommunicationOperationHealth.checked_at.desc()).limit(20).all()
    support_ops = support_operations_snapshot(150)
    stale_total = support_ops["summary"]["stale_total"]
    unassigned_total = support_ops["summary"]["unassigned_total"]
    risk_score = min(100, unread_total // 25 + tickets_open * 2 + failed_logs * 10 + stale_total * 3 + unassigned_total * 2)
    synthetic = [
        {"check_name": "Bildirim yükü", "status": "warning" if unread_total > 500 else "ok", "metric": unread_total},
        {"check_name": "Açık destek talebi", "status": "warning" if tickets_open > 50 else "ok", "metric": tickets_open},
        {"check_name": "Atanmamış destek", "status": "warning" if unassigned_total > 0 else "ok", "metric": unassigned_total},
        {"check_name": "Duran talepler", "status": "warning" if stale_total > 0 else "ok", "metric": stale_total},
        {"check_name": "Aktif anket", "status": "ok", "metric": survey_active},
        {"check_name": "Başarısız otomasyon", "status": "warning" if failed_logs > 0 else "ok", "metric": failed_logs},
    ]
    for item in synthetic:
        item["status_label"] = gate_status_label(item["status"])
    action_items = []
    if failed_logs > 0:
        action_items.append("Başarısız otomasyon loglarını kontrol edip aynı gün yeniden çalıştırma kararı verin.")
    if unassigned_total > 0:
        action_items.append("Atanmamış destek taleplerini sorumlu kişilere dağıtın.")
    if stale_total > 0:
        action_items.append("48 saattir güncellenmeyen destek taleplerini yeniden değerlendirin.")
    if unread_total > 500:
        action_items.append("Bildirim yoğunluğu yüksek; sindirim özetlerini ve sessiz saat ayarlarını gözden geçirin.")
    if not action_items:
        action_items.append("Operasyon sağlığı dengeli görünüyor; günlük izleme ritmi korunabilir.")
    return {
        "summary": {
            "unread_total": unread_total,
            "tickets_open": tickets_open,
            "survey_active": survey_active,
            "failed_logs": failed_logs,
            "risk_score": risk_score,
        },
        "synthetic_checks": synthetic,
        "recent_checks": [
            {
                "check_name": row.check_name,
                "status": row.status,
                "status_label": gate_status_label(row.status),
                "checked_at": row.checked_at,
            }
            for row in recent_checks
        ],
        "action_items": action_items,
        "support_ops": support_ops,
    }


def refresh_operation_health(actor: Any | None = None) -> int:
    snapshot = health_snapshot()
    rows = []
    for item in snapshot["synthetic_checks"]:
        rows.append(
            CommunicationOperationHealth(
                check_name=item["check_name"],
                status=item["status"],
                metric_value=str(item["metric"]),
                details=f"Otomatik yenileme | metric={item['metric']}",
                checked_at=_now(),
            )
        )
    for row in rows:
        db.session.add(row)
    db.session.flush()
    log_action("refresh_health", actor, "communication_operation_health", None, f"{len(rows)} sağlık kaydı yenilendi.")
    db.session.commit()
    return len(rows)


def audit_logs_snapshot(limit: int = 100, status_filter: str = "", action_filter: str = "") -> dict[str, Any]:
    query = CommunicationAutomationLog.query
    if safe_str(status_filter):
        query = query.filter_by(status=safe_str(status_filter))
    if safe_str(action_filter):
        query = query.filter_by(action_type=safe_str(action_filter))
    rows = query.order_by(CommunicationAutomationLog.executed_at.desc()).limit(limit).all()
    counter = Counter(safe_str(getattr(row, "action_type", "genel")) for row in rows)
    status_counter = Counter(safe_str(getattr(row, "status", "success")) for row in rows)
    status_label_counter: Counter[str] = Counter()
    for raw_status, count in status_counter.items():
        status_label_counter[gate_status_label(raw_status)] += count
    return {
        "rows": [
            {
                "action_type": row.action_type,
                "status": row.status,
                "status_label": gate_status_label(row.status),
                "target_table": row.target_table,
                "target_id": row.target_id,
                "summary": row.summary,
                "executed_at": row.executed_at,
            }
            for row in rows
        ],
        "action_breakdown": dict(counter),
        "status_breakdown": dict(status_counter),
        "status_label_breakdown": dict(status_label_counter),
        "filters": {"status": safe_str(status_filter), "action": safe_str(action_filter)},
        "actions": sorted(counter.keys()),
    }


def ensure_default_phase5_data() -> dict[str, int]:
    created = {"rules": 0, "policies": 0}
    defaults_rules = [
        ("support", "normal", 72, "grup_baskani"),
        ("support", "high", 48, "grup_baskani"),
        ("support", "critical", 24, "baskan_yardimcisi"),
    ]
    for module_name, priority, threshold_hours, target_role in defaults_rules:
        row = CommunicationEscalationRule.query.filter_by(module_name=module_name, priority=priority, trigger_type="sla_breach").first()
        if not row:
            db.session.add(
                CommunicationEscalationRule(
                    module_name=module_name,
                    priority=priority,
                    trigger_type="sla_breach",
                    threshold_hours=threshold_hours,
                    target_role=target_role,
                    notify_template="SLA ihlali bildirimi",
                    is_active=True,
                )
            )
            created["rules"] += 1
    defaults_policies = [
        ("notifications", 365, 180, None, 730),
        ("support", 1095, 365, None, 1825),
        ("surveys", 1095, 365, None, 1825),
        ("digest_logs", 365, 90, None, 730),
        ("automation_logs", 365, 90, None, 730),
    ]
    for scope, keep_days, archive_after_days, anonymize_after_days, purge_after_days in defaults_policies:
        row = CommunicationRetentionPolicy.query.filter_by(data_scope=scope).first()
        if not row:
            db.session.add(
                CommunicationRetentionPolicy(
                    data_scope=scope,
                    keep_days=keep_days,
                    archive_after_days=archive_after_days,
                    anonymize_after_days=anonymize_after_days,
                    purge_after_days=purge_after_days,
                    is_active=True,
                    notes="Faz 5 varsayılan saklama politikası",
                )
            )
            created["policies"] += 1
    db.session.flush()
    log_action("ensure_phase5_defaults", None, None, None, "Faz 5 varsayılan işletim verileri kontrol edildi.", created)
    db.session.commit()
    return created


def log_action(action_type: str, actor: Any | None, target_table: str | None, target_id: int | None, summary: str, payload: dict[str, Any] | None = None, status: str = "success") -> CommunicationAutomationLog:
    row = CommunicationAutomationLog(
        action_type=action_type,
        status=status,
        actor_user_id=getattr(actor, "id", None) if actor else None,
        target_table=target_table,
        target_id=target_id,
        summary=summary,
        payload_json=payload,
        executed_at=_now(),
    )
    db.session.add(row)
    db.session.flush()
    return row