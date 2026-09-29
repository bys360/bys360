from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.models import PerformancePeriod
from app.services import runtime_schema
from app.services.performance.assignment_rule_audit import build_assignment_generation_preflight
from app.services.performance.v2_1_6_category_period_integration import (
    INTEGRATION_TABLE,
    PRECHECK_TABLE,
    build_assignment_preintegration,
    ensure_category_period_integration_schema,
    list_integrations,
    provision_category_period_integration_schema,
)
from app.services.performance_service import generate_assignments_for_active_period

"""BYS360 Performans V2.1.8 dönem merkezi görev üretimi güvenlik kapısı.

V2.1.8A HOTFIX: Sayfa ilk açılışında ağır zincir audit kontrolü çalıştırılmaz.
Ayrıntılı audit yalnızca görev üretimi başlatılırken çalışır.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_8a_period_center_assignment_launch_fast_open"


def _db():
    from app.extensions import db
    return db


def _dialect_name() -> str:
    try:
        return _db().engine.dialect.name
    except RuntimeError:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return "unknown"


def _has_column(table_name: str, column_name: str) -> bool:
    try:
        inspector = inspect(_db().engine)
        if not inspector.has_table(table_name):
            return False
        return column_name in {col.get("name") for col in inspector.get_columns(table_name)}
    except (SQLAlchemyError, RuntimeError):
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _alter_add_column_sql(table_name: str, column_name: str, column_type: str) -> str:
    return f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"


def _safe_json(payload: Any) -> str:
    try:
        return json.dumps(payload or {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return "{}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


ASSIGNMENT_LAUNCH_COLUMNS = (
    "assignment_generation_status",
    "assignment_generation_summary",
    "assignment_generation_run_key",
    "assignment_generation_at",
)


def provision_period_center_assignment_launch_schema() -> dict[str, Any]:
    """Add the assignment-generation summary columns (explicit maintenance only: flask runtime-schema provision)."""
    provision_category_period_integration_schema()
    db = _db()
    added: list[str] = []
    dialect = _dialect_name()
    columns = dict(zip(ASSIGNMENT_LAUNCH_COLUMNS, (
        "VARCHAR(80)",
        "TEXT",
        "VARCHAR(160)",
        "TIMESTAMP WITHOUT TIME ZONE" if dialect != "sqlite" else "DATETIME",
    ), strict=True))
    # Inspect before any ALTER: on PostgreSQL an uncommitted ALTER locks the table and
    # _has_column() inspects through another connection, which would wait forever.
    missing = [name for name in columns if not _has_column(INTEGRATION_TABLE, name)]
    for name in missing:
        try:
            db.session.execute(text(_alter_add_column_sql(INTEGRATION_TABLE, name, columns[name])))
            added.append(name)
        except SQLAlchemyError:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            db.session.rollback()
            if not _has_column(INTEGRATION_TABLE, name):
                raise
    db.session.commit()
    return {"ok": True, "added_columns": added, "dialect": dialect, "rule_version": RULE_VERSION}


ASSIGNMENT_LAUNCH_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.period_center_assignment_launch",
    tables=(INTEGRATION_TABLE,),
    columns=tuple((INTEGRATION_TABLE, name) for name in ASSIGNMENT_LAUNCH_COLUMNS),
    provision=provision_period_center_assignment_launch_schema,
))


def ensure_period_center_assignment_launch_schema() -> dict[str, Any]:
    """Verify the assignment-generation summary columns exist; never alters the table."""
    ensure_category_period_integration_schema()
    runtime_schema.require(ASSIGNMENT_LAUNCH_SCHEMA)
    return {"ok": True, "added_columns": [], "dialect": _dialect_name(), "rule_version": RULE_VERSION}


def _integration_for_plan(plan_key: str) -> dict[str, Any] | None:
    key = str(plan_key or "").strip()
    if not key:
        return None
    try:
        for item in list_integrations():
            if str(item.get("plan_key") or "") == key:
                return item
    except SQLAlchemyError:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
    return None


def _period_for_integration(integration: dict[str, Any] | None) -> PerformancePeriod | None:
    if not integration:
        return None
    period_id = _safe_int(integration.get("period_id"))
    if not period_id:
        return None
    try:
        return _db().session.get(PerformancePeriod, period_id)
    except SQLAlchemyError:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
        return None


def _precheck_count(plan_key: str, period_id: int) -> int:
    try:
        return int(_db().session.execute(
            text(f"SELECT COUNT(*) FROM {PRECHECK_TABLE} WHERE plan_key=:plan_key AND period_id=:period_id"),
            {"plan_key": plan_key, "period_id": period_id},
        ).scalar() or 0)
    except SQLAlchemyError:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
        return 0


def _precheck_status_counts(plan_key: str, period_id: int) -> dict[str, int]:
    try:
        rows = _db().session.execute(
            text(f"SELECT precheck_status, COUNT(*) AS total FROM {PRECHECK_TABLE} WHERE plan_key=:plan_key AND period_id=:period_id GROUP BY precheck_status"),
            {"plan_key": plan_key, "period_id": period_id},
        ).mappings().all()
        return {str(row.get("precheck_status") or ""): int(row.get("total") or 0) for row in rows}
    except SQLAlchemyError:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            _db().session.rollback()
        except SQLAlchemyError:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
        return {}


def build_assignment_launch_guard(
    plan_key: str,
    *,
    rebuild_missing_precheck: bool = True,
    include_audit: bool = False,
) -> dict[str, Any]:
    """Plan görev üretimine güvenli şekilde geçebilir mi kontrol eder.

    include_audit=False iken yalnızca hafif dönem/ön kontrol durumuna bakar.
    Ağır zincir audit kontrolü görev üretimi başlatılırken include_audit=True ile yapılır.
    """
    ensure_period_center_assignment_launch_schema()
    key = str(plan_key or "").strip()
    if not key:
        return {
            "ok": False,
            "can_launch": False,
            "status": "plan_secilmedi",
            "message": "Görev üretimi için önce bir dönem hazırlık planı seçilmelidir.",
            "rule_version": RULE_VERSION,
        }

    integration = _integration_for_plan(key)
    if not integration:
        return {
            "ok": False,
            "can_launch": False,
            "plan_key": key,
            "status": "donem_baglantisi_yok",
            "message": "Plan henüz gerçek performans dönemine bağlanmamış.",
            "rule_version": RULE_VERSION,
        }

    period = _period_for_integration(integration)
    if period is None:
        return {
            "ok": False,
            "can_launch": False,
            "plan_key": key,
            "period_id": integration.get("period_id"),
            "status": "donem_bulunamadi",
            "message": "Bağlı performans dönemi bulunamadı.",
            "rule_version": RULE_VERSION,
        }

    period_id = int(period.id)
    if rebuild_missing_precheck and _precheck_count(key, period_id) == 0:
        build_assignment_preintegration(key, period_id, write=True)
        integration = _integration_for_plan(key) or integration

    precheck_status = str(integration.get("assignment_precheck_status") or "not_started")
    status_counts = _precheck_status_counts(key, period_id)
    precheck_total = sum(status_counts.values())
    if precheck_status != "ready":
        return {
            "ok": False,
            "can_launch": False,
            "plan_key": key,
            "period_id": period_id,
            "period_title": getattr(period, "title", None) or getattr(period, "name", None),
            "status": "on_kontrol_temiz_degil",
            "message": "Görev üretimi başlatılmadı. Önce amir/kapsam ön kontrolünde kalan uyarılar temizlenmelidir.",
            "precheck_status": precheck_status,
            "precheck_status_counts": status_counts,
            "precheck_total": precheck_total,
            "rule_version": RULE_VERSION,
        }

    audit = {
        "ok": True,
        "can_auto_repair": True,
        "message": "Ön kontroller temiz. Detaylı zincir kontrolü görev üretimi başlatılırken yapılacak.",
    }
    if include_audit:
        audit = build_assignment_generation_preflight(period_id=period_id, limit=800)
        can_auto_repair = bool(audit.get("can_auto_repair"))
        if not can_auto_repair:
            return {
                "ok": False,
                "can_launch": False,
                "plan_key": key,
                "period_id": period_id,
                "period_title": getattr(period, "title", None) or getattr(period, "name", None),
                "status": "zincir_blokaji_var",
                "message": audit.get("message") or "Görev üretimi ön kontrolde bloklandı.",
                "audit": audit,
                "precheck_status": precheck_status,
                "precheck_status_counts": status_counts,
                "precheck_total": precheck_total,
                "rule_version": RULE_VERSION,
            }

    return {
        "ok": True,
        "can_launch": True,
        "plan_key": key,
        "period_id": period_id,
        "period_title": getattr(period, "title", None) or getattr(period, "name", None),
        "period_active": bool(getattr(period, "is_active", False)),
        "status": "gorev_uretimi_baslatilabilir",
        "message": "Ön kontroller temiz. Görev üretimi başlatılabilir.",
        "audit": audit,
        "precheck_status": precheck_status,
        "precheck_status_counts": status_counts,
        "precheck_total": precheck_total,
        "rule_version": RULE_VERSION,
    }


def _mark_generation_result(plan_key: str, status: str, summary: dict[str, Any]) -> None:
    ensure_period_center_assignment_launch_schema()
    run_key = str((summary or {}).get("run_key") or "")[:160]
    _db().session.execute(text(f"""
        UPDATE {INTEGRATION_TABLE}
           SET assignment_generation_status=:status,
               assignment_generation_summary=:summary,
               assignment_generation_run_key=:run_key,
               assignment_generation_at=CURRENT_TIMESTAMP,
               updated_at=CURRENT_TIMESTAMP
         WHERE plan_key=:plan_key
    """), {
        "plan_key": plan_key,
        "status": status,
        "summary": _safe_json(summary),
        "run_key": run_key,
    })
    _db().session.commit()


def launch_assignments_from_period_center(plan_key: str, *, actor_user_id: int | None = None) -> dict[str, Any]:
    """V2.1.7 merkezindeki seçili plan için güvenli görev üretimini başlatır."""
    guard = build_assignment_launch_guard(plan_key, include_audit=True)
    if not guard.get("can_launch"):
        _mark_generation_result(str(plan_key or ""), "blocked", {"guard": guard}) if plan_key else None
        return {"ok": False, "launched": False, "guard": guard, "message": guard.get("message")}

    period_id = int(guard.get("period_id") or 0)
    result = generate_assignments_for_active_period(period_id=period_id, actor_user_id=actor_user_id)
    status = "generated" if result.get("ok") else "failed"
    _mark_generation_result(str(plan_key or ""), status, {"guard": guard, "result": result})
    return {
        "ok": bool(result.get("ok")),
        "launched": bool(result.get("ok")),
        "guard": guard,
        "result": result,
        "message": result.get("message") or ("Görev üretimi tamamlandı." if result.get("ok") else "Görev üretimi tamamlanamadı."),
        "rule_version": RULE_VERSION,
    }


__all__ = [
    "RULE_VERSION",
    "ensure_period_center_assignment_launch_schema",
    "build_assignment_launch_guard",
    "launch_assignments_from_period_center",
]
