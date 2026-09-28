from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.services import runtime_schema
from app.services.performance.v2_1_6_category_period_integration import (
    INTEGRATION_TABLE,
    ensure_category_period_integration_schema,
    list_integrations,
    provision_category_period_integration_schema,
)

logger = logging.getLogger(__name__)

"""BYS360 Performans V2.1.9 dönem merkezi süreç izleme ve bildirim hazırlığı.

Bu servis V2.1.7/V2.1.8 dönem yönetim merkezini bozmadan iki hafif katman ekler:
- Görev üretiminden sonraki süreç durumunu tek ekranda izleme.
- Değerlendirme çağrısı ve hatırlatma bildirimlerini göndermeden önce kurumsal ön izleme/hazırlık kaydı.

Not: Bu faz gerçek e-posta göndermez; yalnızca güvenli hazırlık ve görünürlük katmanıdır.
"""

RULE_VERSION = "performance_v2_1_9_period_center_process_notifications"
ASSIGNMENT_TABLE = "evaluation_assignments"
PERIOD_TABLE = "performance_periods"
MAIL_LOG_TABLE = "mail_logs"
NOTIFICATION_TABLE = "notifications"


def _db():
    from app.extensions import db
    return db


def _safe_json(payload: Any) -> str:
    try:
        return json.dumps(payload or {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=37")
        return "{}"


def _parse_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=48")
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=55")
        return default


def _safe_percent(done: int, total: int) -> int:
    if total <= 0:
        return 0
    try:
        return max(0, min(100, int(round((done / total) * 100))))
    except (TypeError, ValueError):
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=64")
        return 0


def _dialect_name() -> str:
    try:
        return _db().engine.dialect.name
    except RuntimeError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=71")
        return "unknown"


def _inspector():
    return inspect(_db().engine)


def _has_table(table_name: str) -> bool:
    try:
        return bool(_inspector().has_table(table_name))
    except (SQLAlchemyError, RuntimeError):
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=82")
        return False


def _columns(table_name: str) -> set[str]:
    try:
        if not _has_table(table_name):
            return set()
        return {str(col.get("name")) for col in _inspector().get_columns(table_name)}
    except (SQLAlchemyError, RuntimeError):
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=91")
        return set()


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in _columns(table_name)


def _alter_add_column_sql(table_name: str, column_name: str, column_type: str) -> str:
    return f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"


def _integration_for_plan(plan_key: str) -> dict[str, Any] | None:
    key = str(plan_key or "").strip()
    if not key:
        return None
    try:
        for item in list_integrations():
            if str(item.get("plan_key") or "") == key:
                return item
    except SQLAlchemyError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=111")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=114")
            pass
    return None


NOTIFICATION_PREPARATION_COLUMNS = (
    "notification_preparation_status",
    "notification_preparation_summary",
    "notification_prepared_at",
    "notification_prepared_by_id",
)


def provision_period_center_process_notification_schema() -> dict[str, Any]:
    """Add the notification-preparation columns (explicit maintenance only: flask runtime-schema provision)."""
    try:
        provision_category_period_integration_schema()
    except SQLAlchemyError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=123")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=126")
            pass
    db = _db()
    added: list[str] = []
    if not _has_table(INTEGRATION_TABLE):
        return {"ok": False, "message": "Dönem entegrasyon tablosu bulunamadı.", "added_columns": added, "rule_version": RULE_VERSION}
    dialect = _dialect_name()
    timestamp_type = "TIMESTAMP WITHOUT TIME ZONE" if dialect != "sqlite" else "DATETIME"
    columns = dict(zip(NOTIFICATION_PREPARATION_COLUMNS, ("VARCHAR(80)", "TEXT", timestamp_type, "INTEGER"), strict=True))
    for name, sql_type in columns.items():
        if not _has_column(INTEGRATION_TABLE, name):
            try:
                db.session.execute(text(_alter_add_column_sql(INTEGRATION_TABLE, name, sql_type)))
                added.append(name)
            except SQLAlchemyError:
                logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
                db.session.rollback()
                if not _has_column(INTEGRATION_TABLE, name):
                    raise
    db.session.commit()
    return {"ok": True, "added_columns": added, "dialect": dialect, "rule_version": RULE_VERSION}


NOTIFICATION_PREPARATION_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.period_center_notification_preparation",
    tables=(INTEGRATION_TABLE,),
    columns=tuple((INTEGRATION_TABLE, name) for name in NOTIFICATION_PREPARATION_COLUMNS),
    provision=provision_period_center_process_notification_schema,
))


def ensure_period_center_process_notification_schema() -> dict[str, Any]:
    """Verify the notification-preparation columns exist; never alters the table."""
    ensure_category_period_integration_schema()
    runtime_schema.require(NOTIFICATION_PREPARATION_SCHEMA)
    return {"ok": True, "added_columns": [], "dialect": _dialect_name(), "rule_version": RULE_VERSION}


def _period_summary(period_id: int | None) -> dict[str, Any]:
    pid = _safe_int(period_id)
    if not pid or not _has_table(PERIOD_TABLE):
        return {"ok": False, "period_id": pid, "title": "-", "message": "Bağlı performans dönemi bulunamadı."}
    cols = _columns(PERIOD_TABLE)
    select_cols = ["id"]
    for name in ["title", "name", "period_type", "start_date", "end_date", "evaluation_start_date", "evaluation_end_date", "is_active", "results_published", "is_locked"]:
        if name in cols:
            select_cols.append(name)
    try:
        row = _db().session.execute(
            text(f"SELECT {', '.join(select_cols)} FROM {PERIOD_TABLE} WHERE id=:pid"),
            {"pid": pid},
        ).mappings().first()
    except SQLAlchemyError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=167")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=170")
            pass
        row = None
    if not row:
        return {"ok": False, "period_id": pid, "title": "-", "message": "Bağlı performans dönemi bulunamadı."}
    data = dict(row)
    data["ok"] = True
    data["period_id"] = pid
    data["title"] = data.get("title") or data.get("name") or f"Performans Dönemi #{pid}"
    return data


def _assignment_status_counts(period_id: int | None) -> dict[str, int]:
    pid = _safe_int(period_id)
    if not pid or not _has_table(ASSIGNMENT_TABLE) or not _has_column(ASSIGNMENT_TABLE, "period_id"):
        return {}
    try:
        rows = _db().session.execute(
            text(f"SELECT COALESCE(status, 'bekliyor') AS status, COUNT(*) AS total FROM {ASSIGNMENT_TABLE} WHERE period_id=:pid GROUP BY COALESCE(status, 'bekliyor')"),
            {"pid": pid},
        ).mappings().all()
        return {str(row.get("status") or "bekliyor"): int(row.get("total") or 0) for row in rows}
    except SQLAlchemyError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=192")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=195")
            pass
        return {}


def _assignment_scalar(period_id: int | None, expression: str, fallback: int = 0) -> int:
    pid = _safe_int(period_id)
    if not pid or not _has_table(ASSIGNMENT_TABLE) or not _has_column(ASSIGNMENT_TABLE, "period_id"):
        return fallback
    try:
        value = _db().session.execute(text(f"SELECT {expression} FROM {ASSIGNMENT_TABLE} WHERE period_id=:pid"), {"pid": pid}).scalar()
        return int(value or 0)
    except SQLAlchemyError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=207")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=210")
            pass
        return fallback


def _assignment_count_where(period_id: int | None, where_clause: str) -> int:
    pid = _safe_int(period_id)
    if not pid or not _has_table(ASSIGNMENT_TABLE) or not _has_column(ASSIGNMENT_TABLE, "period_id"):
        return 0
    try:
        value = _db().session.execute(text(f"SELECT COUNT(*) FROM {ASSIGNMENT_TABLE} WHERE period_id=:pid AND ({where_clause})"), {"pid": pid}).scalar()
        return int(value or 0)
    except SQLAlchemyError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=222")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=225")
            pass
        return 0


def _assignment_process_summary(period_id: int | None) -> dict[str, Any]:
    pid = _safe_int(period_id)
    cols = _columns(ASSIGNMENT_TABLE)
    status_counts = _assignment_status_counts(pid)
    total = sum(status_counts.values())
    completed = 0
    for key, value in status_counts.items():
        if str(key).strip().lower() in {"tamamlandi", "tamamlandı", "completed", "done"}:
            completed += value
    if "completed_at" in cols:
        completed = max(completed, _assignment_count_where(pid, "completed_at IS NOT NULL"))
    pending = max(0, total - completed)
    evaluator_count = _assignment_scalar(pid, "COUNT(DISTINCT evaluator_id)") if "evaluator_id" in cols else 0
    employee_count = _assignment_scalar(pid, "COUNT(DISTINCT employee_id)") if "employee_id" in cols else 0
    overdue = _assignment_count_where(pid, "completed_at IS NULL AND due_date IS NOT NULL AND due_date < CURRENT_TIMESTAMP") if {"completed_at", "due_date"}.issubset(cols) else 0
    due_soon = 0
    if {"completed_at", "due_date"}.issubset(cols):
        if _dialect_name() == "sqlite":
            due_soon = _assignment_count_where(pid, "completed_at IS NULL AND due_date IS NOT NULL AND due_date >= CURRENT_TIMESTAMP AND due_date <= datetime(CURRENT_TIMESTAMP, '+2 day')")
        else:
            due_soon = _assignment_count_where(pid, "completed_at IS NULL AND due_date IS NOT NULL AND due_date >= CURRENT_TIMESTAMP AND due_date <= CURRENT_TIMESTAMP + INTERVAL '2 days'")
    progress = _safe_percent(completed, total)
    if total <= 0:
        stage = "Görev üretimi bekliyor"
        status_class = "muted"
        message = "Bu dönem için henüz değerlendirme görevi görünmüyor. Ön kontroller tamamlandıysa görev üretimi başlatılabilir."
    elif completed >= total:
        stage = "Değerlendirmeler tamamlandı"
        status_class = "ok"
        message = "Bu dönem için görünen değerlendirme görevleri tamamlanmış görünüyor. Yayın/karne kontrollerine geçilebilir."
    elif overdue > 0:
        stage = "Geciken değerlendirme var"
        status_class = "warn"
        message = "Süresi geçen değerlendirme görevleri var. Hatırlatma bildirimi hazırlanmalı."
    else:
        stage = "Değerlendirme süreci devam ediyor"
        status_class = "info"
        message = "Görevler üretilmiş; tamamlanma durumu bu merkezden izlenebilir."
    return {
        "period_id": pid,
        "total": total,
        "completed": completed,
        "pending": pending,
        "evaluator_count": evaluator_count,
        "employee_count": employee_count,
        "overdue": overdue,
        "due_soon": due_soon,
        "progress": progress,
        "status_counts": status_counts,
        "stage": stage,
        "status_class": status_class,
        "message": message,
    }


def _recent_mail_count(period_id: int | None) -> int:
    pid = _safe_int(period_id)
    if not pid or not _has_table(MAIL_LOG_TABLE):
        return 0
    cols = _columns(MAIL_LOG_TABLE)
    # Bazı canlı sürümlerde period_id olmayabilir; bu durumda ekranda 0 göstermek güvenlidir.
    if "period_id" not in cols:
        return 0
    try:
        return int(_db().session.execute(text(f"SELECT COUNT(*) FROM {MAIL_LOG_TABLE} WHERE period_id=:pid"), {"pid": pid}).scalar() or 0)
    except SQLAlchemyError:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=295")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/v2_1_9_period_center_process_notifications.py | line=298")
            pass
        return 0


def build_notification_preview(period: dict[str, Any], process: dict[str, Any]) -> list[dict[str, Any]]:
    title = period.get("title") or "Performans dönemi"
    evaluator_count = _safe_int(process.get("evaluator_count"))
    pending = _safe_int(process.get("pending"))
    overdue = _safe_int(process.get("overdue"))
    due_soon = _safe_int(process.get("due_soon"))
    total = _safe_int(process.get("total"))
    preview: list[dict[str, Any]] = [
        {
            "key": "start_call",
            "title": "Değerlendirme Başlangıç Bildirimi",
            "audience": "Görev atanmış amirler",
            "recipient_count": evaluator_count,
            "status": "Hazırlanabilir" if total else "Görev bekliyor",
            "subject": f"{title} değerlendirme süreci başladı",
            "message": "Size atanan değerlendirme görevlerini BYS360 Performans Yönetimi ekranından tamamlayabilirsiniz.",
        },
        {
            "key": "pending_reminder",
            "title": "Bekleyen Değerlendirme Hatırlatması",
            "audience": "Tamamlanmamış görevi olan amirler",
            "recipient_count": pending,
            "status": "Hazırlanabilir" if pending else "Bekleyen yok",
            "subject": f"{title} bekleyen değerlendirme hatırlatması",
            "message": "Dönem kapanmadan önce bekleyen değerlendirme görevlerinin tamamlanması gerekmektedir.",
        },
        {
            "key": "deadline_attention",
            "title": "Son Tarih / Gecikme Bilgilendirmesi",
            "audience": "Son tarihi yaklaşan veya geciken görevi olan amirler",
            "recipient_count": overdue + due_soon,
            "status": "Dikkat" if (overdue or due_soon) else "Şu an gerek yok",
            "subject": f"{title} son tarih bilgilendirmesi",
            "message": "Süresi yaklaşan veya geciken değerlendirme görevleri için süreç takibi yapılmalıdır.",
        },
        {
            "key": "executive_summary",
            "title": "Yönetici Süreç Özeti",
            "audience": "Başkan / Üst Yönetim / Performans Yetkilisi",
            "recipient_count": 1 if total else 0,
            "status": "Özet hazır" if total else "Görev bekliyor",
            "subject": f"{title} süreç özeti",
            "message": f"Toplam {total} görev, tamamlanan {process.get('completed', 0)}, bekleyen {pending}, geciken {overdue}.",
        },
    ]
    return preview


def _notification_preparation_status(integration: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    if not integration:
        return "Hazırlık bekliyor", None
    status = str(integration.get("notification_preparation_status") or "")
    summary = _parse_json(integration.get("notification_preparation_summary"))
    if status == "prepared":
        return "Hazırlık oluşturuldu", summary if isinstance(summary, dict) else None
    return "Hazırlık bekliyor", summary if isinstance(summary, dict) else None


def build_period_center_process_state(plan_key: str | None) -> dict[str, Any]:
    # V2.1.9A: Görüntüleme sırasında şema değiştiren/DB yazan işlem çalıştırılmaz.
    # Bildirim hazırlığı oluşturulurken gerekli alanlar ayrıca güvenli şekilde hazırlanır.
    key = str(plan_key or "").strip()
    integration = _integration_for_plan(key) if key else None
    period_id = _safe_int((integration or {}).get("period_id"))
    period = _period_summary(period_id)
    process = _assignment_process_summary(period_id)
    preview = build_notification_preview(period, process) if period.get("ok") else []
    status_label, stored_summary = _notification_preparation_status(integration)
    can_prepare = bool(period.get("ok") and process.get("total", 0) > 0)
    return {
        "ok": True,
        "rule_version": RULE_VERSION,
        "plan_key": key,
        "integration": integration,
        "period": period,
        "process": process,
        "notification_preview": preview,
        "notification_status_label": status_label,
        "notification_summary": stored_summary,
        "notification_can_prepare": can_prepare,
        "mail_log_count": _recent_mail_count(period_id),
        "notification_table_available": _has_table(NOTIFICATION_TABLE),
        "message": process.get("message") if key else "Plan seçildiğinde süreç izleme ve bildirim hazırlığı gösterilir.",
    }


def prepare_period_center_notifications(plan_key: str, *, actor_user_id: int | None = None) -> dict[str, Any]:
    ensure_period_center_process_notification_schema()
    state = build_period_center_process_state(plan_key)
    if not state.get("notification_can_prepare"):
        return {
            "ok": False,
            "prepared": False,
            "state": state,
            "message": "Bildirim hazırlığı için önce dönem bağlantısı ve değerlendirme görevleri oluşmalıdır.",
            "rule_version": RULE_VERSION,
        }
    summary = {
        "period": state.get("period"),
        "process": state.get("process"),
        "preview": state.get("notification_preview"),
        "mail_log_count": state.get("mail_log_count"),
        "prepared_by_id": actor_user_id,
        "note": "Bu kayıt yalnızca bildirim/e-posta gönderimi ön hazırlığıdır; gerçek gönderim yapmaz.",
    }
    _db().session.execute(text(f"""
        UPDATE {INTEGRATION_TABLE}
           SET notification_preparation_status=:status,
               notification_preparation_summary=:summary,
               notification_prepared_at=CURRENT_TIMESTAMP,
               notification_prepared_by_id=:actor_user_id,
               updated_at=CURRENT_TIMESTAMP
         WHERE plan_key=:plan_key
    """), {
        "status": "prepared",
        "summary": _safe_json(summary),
        "actor_user_id": actor_user_id,
        "plan_key": str(plan_key or ""),
    })
    _db().session.commit()
    return {
        "ok": True,
        "prepared": True,
        "summary": summary,
        "message": "Bildirim hazırlığı oluşturuldu. Bu fazda gerçek e-posta gönderimi yapılmadı.",
        "rule_version": RULE_VERSION,
    }


def run_v2_1_9_period_center_process_gate() -> dict[str, Any]:
    # V2.1.9A: Bu gate sayfa açılışında çalıştığı için kesinlikle ALTER/UPDATE/INSERT yapmaz.
    # Amaç sayfayı kilitlemeden güvenli ve hafif kontrol göstermektir.
    checks: list[dict[str, Any]] = []
    integration_ok = _has_table(INTEGRATION_TABLE)
    assignment_ok = _has_table(ASSIGNMENT_TABLE)
    checks.append({
        "name": "process_light_open",
        "ok": True,
        "message": "Dönem merkezi hızlı açılış modunda çalışıyor; süreç izleme plan seçildikten sonra isteğe bağlı açılır.",
    })
    checks.append({
        "name": "integration_source",
        "ok": integration_ok,
        "message": "Dönem bağlantı kayıtları okunabilir." if integration_ok else "Dönem bağlantı kayıt tablosu henüz bulunamadı.",
    })
    checks.append({
        "name": "assignment_source",
        "ok": assignment_ok,
        "message": "Değerlendirme görev tablosu mevcut." if assignment_ok else "Değerlendirme görev tablosu bulunamadı.",
    })
    checks.append({
        "name": "mail_log_visibility",
        "ok": True,
        "message": "Bu faz gerçek mail göndermez; yalnızca hazırlık ve görünürlük sağlar.",
    })
    # Entegrasyon/görev tabloları yoksa sayfa yine açılır; bu yalnızca bilgilendirme uyarısıdır.
    return {"ok": True, "checks": checks, "rule_version": RULE_VERSION}


__all__ = [
    "RULE_VERSION",
    "ensure_period_center_process_notification_schema",
    "build_period_center_process_state",
    "build_notification_preview",
    "prepare_period_center_notifications",
    "run_v2_1_9_period_center_process_gate",
]
