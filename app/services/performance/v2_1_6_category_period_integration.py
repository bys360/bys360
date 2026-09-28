from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import inspect, text

from app import db
from app.models import PerformancePeriod, User
from app.services import runtime_schema
from app.services.performance.period_scope_assignment import employee_matches_period_scope
from app.services.performance.v2_1_2_category_engine import canonical_category_key, list_categories
from app.services.performance.v2_1_5_category_period_scope import (
    PLAN_TABLE,
    ensure_category_period_scope_schema,
    list_category_period_scope_plans,
    list_plan_items,
    provision_category_period_scope_schema,
)

"""BYS360 Performans V2.1.6 kategori dönem entegrasyonu.

Bu servis, V2.1.5 kategori dönem kapsam planını gerçek PerformancePeriod
kaydıyla bağlar ve görev üretimi ön entegrasyon raporu üretir. Bu faz doğrudan
`evaluation_assignments` yazmaz.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_6_category_period_integration"
INTEGRATION_TABLE = "performance_category_period_scope_integrations"
PRECHECK_TABLE = "performance_category_assignment_preintegrations"


@dataclass
class PreintegrationRow:
    user_id: int
    display_name: str
    sicil_no: str
    unit_name: str
    category_key: str
    scope_match: bool
    manager_summary: str
    precheck_status: str
    precheck_message: str


def _db():
    from app.extensions import db
    return db


def _dialect_name() -> str:
    try:
        return _db().engine.dialect.name
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return "unknown"


def _has_table(table_name: str) -> bool:
    try:
        return bool(inspect(_db().engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _bool_sql(value: bool) -> str:
    if _dialect_name() == "sqlite":
        return "1" if value else "0"
    return "TRUE" if value else "FALSE"


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        return date.fromisoformat(text_value[:10])
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _category_display_name(category_key: str) -> str:
    key = canonical_category_key(category_key)
    for cat in list_categories(include_inactive=True):
        if cat.category_key == key:
            return cat.display_name
    return key


def provision_category_period_integration_schema() -> dict[str, Any]:
    provision_category_period_scope_schema()
    db = _db()
    created: list[str] = []
    dialect = _dialect_name()

    if not _has_table(INTEGRATION_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {INTEGRATION_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_key VARCHAR(160) NOT NULL UNIQUE,
                period_id INTEGER,
                category_key VARCHAR(80) NOT NULL,
                integration_status VARCHAR(80) DEFAULT 'period_linked',
                local_mode BOOLEAN DEFAULT 1,
                assignment_precheck_status VARCHAR(80) DEFAULT 'not_started',
                assignment_precheck_summary TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {INTEGRATION_TABLE} (
                id SERIAL PRIMARY KEY,
                plan_key VARCHAR(160) NOT NULL UNIQUE,
                period_id INTEGER,
                category_key VARCHAR(80) NOT NULL,
                integration_status VARCHAR(80) DEFAULT 'period_linked',
                local_mode BOOLEAN DEFAULT TRUE,
                assignment_precheck_status VARCHAR(80) DEFAULT 'not_started',
                assignment_precheck_summary TEXT,
                created_by INTEGER,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(INTEGRATION_TABLE)

    if not _has_table(PRECHECK_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {PRECHECK_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_key VARCHAR(160) NOT NULL,
                period_id INTEGER,
                user_id INTEGER NOT NULL,
                category_key VARCHAR(80) NOT NULL,
                scope_match BOOLEAN DEFAULT 0,
                manager_summary TEXT,
                precheck_status VARCHAR(80) DEFAULT 'kontrol_gerekiyor',
                precheck_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {PRECHECK_TABLE} (
                id SERIAL PRIMARY KEY,
                plan_key VARCHAR(160) NOT NULL,
                period_id INTEGER,
                user_id INTEGER NOT NULL,
                category_key VARCHAR(80) NOT NULL,
                scope_match BOOLEAN DEFAULT FALSE,
                manager_summary TEXT,
                precheck_status VARCHAR(80) DEFAULT 'kontrol_gerekiyor',
                precheck_message TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(PRECHECK_TABLE)

    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{INTEGRATION_TABLE}_plan ON {INTEGRATION_TABLE} (plan_key)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{INTEGRATION_TABLE}_period ON {INTEGRATION_TABLE} (period_id)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{PRECHECK_TABLE}_plan_user ON {PRECHECK_TABLE} (plan_key, user_id)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{PRECHECK_TABLE}_period ON {PRECHECK_TABLE} (period_id)"))
    db.session.commit()
    return {"ok": True, "created": created, "dialect": dialect, "rule_version": RULE_VERSION}


CATEGORY_PERIOD_INTEGRATION_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.category_period_integration",
    tables=(INTEGRATION_TABLE, PRECHECK_TABLE),
    indexes=(
        (INTEGRATION_TABLE, f"ix_{INTEGRATION_TABLE}_plan"),
        (INTEGRATION_TABLE, f"ix_{INTEGRATION_TABLE}_period"),
        (PRECHECK_TABLE, f"ix_{PRECHECK_TABLE}_plan_user"),
        (PRECHECK_TABLE, f"ix_{PRECHECK_TABLE}_period"),
    ),
    provision=provision_category_period_integration_schema,
))


def ensure_category_period_integration_schema() -> dict[str, Any]:
    """Verify this module's tables exist; never creates them (see app.services.runtime_schema)."""
    ensure_category_period_scope_schema()
    runtime_schema.require(CATEGORY_PERIOD_INTEGRATION_SCHEMA)
    return {"ok": True, "created": [], "dialect": _dialect_name(), "rule_version": RULE_VERSION}


def get_scope_plan(plan_key: str) -> dict[str, Any] | None:
    ensure_category_period_integration_schema()
    row = _db().session.execute(text(f"SELECT * FROM {PLAN_TABLE} WHERE plan_key=:plan_key"), {"plan_key": str(plan_key or "")}).mappings().first()
    return dict(row) if row else None


def _period_title_for_plan(plan: dict[str, Any]) -> str:
    return _safe_text(plan.get("plan_name")) or f"{_category_display_name(str(plan.get('category_key') or 'diger'))} Performans Dönemi"


def _find_period(period_id: Any) -> PerformancePeriod | None:
    try:
        pid = int(period_id or 0)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None
    if not pid:
        return None
    return db.session.get(PerformancePeriod, pid)


def _set_if_has(obj: Any, attr: str, value: Any) -> None:
    if hasattr(obj, attr):
        setattr(obj, attr, value)


def create_or_update_period_from_plan(plan_key: str, *, created_by: int | None = None, activate_period: bool = False) -> dict[str, Any]:
    """V2.1.5 planını gerçek performans dönemine bağlar.

    Bu işlem local geliştirme için gerçek `performance_periods` kaydı oluşturabilir.
    Görev üretimi yapılmaz.
    """
    ensure_category_period_integration_schema()
    plan = get_scope_plan(plan_key)
    if not plan:
        return {"ok": False, "message": "Kategori dönem kapsam planı bulunamadı.", "plan_key": plan_key}

    start = _parse_date(plan.get("start_date"))
    end = _parse_date(plan.get("end_date"))
    if not start or not end:
        return {"ok": False, "message": "Plan başlangıç/bitiş tarihi eksik olduğu için dönem oluşturulmadı.", "plan_key": plan_key}
    if end < start:
        return {"ok": False, "message": "Plan bitiş tarihi başlangıç tarihinden önce olamaz.", "plan_key": plan_key}

    category_key = canonical_category_key(plan.get("category_key"))
    category_label = _category_display_name(category_key)
    title = _period_title_for_plan(plan)

    existing = _db().session.execute(text(f"SELECT period_id FROM {INTEGRATION_TABLE} WHERE plan_key=:plan_key"), {"plan_key": plan_key}).mappings().first()
    period = _find_period(existing.get("period_id") if existing else None)
    action = "updated"
    if period is None:
        # BYS360 DEFECT AD: this new row is ALWAYS flushed (real INSERT)
        # below, before the deactivate-others step further down runs.
        # Constructing it with is_active=True directly would momentarily
        # coexist with any already-active period at flush time -- fine
        # under the old no-DB-constraint world, but a real IntegrityError
        # once the AD single-active-period partial unique index exists.
        # is_active is set to True only after that deactivation has run
        # (see below), never here.
        period = PerformancePeriod(
            title=title,
            name=title,
            period_type=_safe_text(plan.get("period_type")) or "special",
            start_date=start,
            end_date=end,
            description="BYS360 V2.1.6 kategori kapsam planından local ortamda oluşturuldu.",
            is_active=False,
        )
        _db().session.add(period)
        _db().session.flush()
        action = "created"
    else:
        period.title = title
        _set_if_has(period, "name", title)
        period.period_type = _safe_text(plan.get("period_type")) or "special"
        period.start_date = start
        period.end_date = end
        if not _safe_text(getattr(period, "description", "")):
            period.description = "BYS360 V2.1.6 kategori kapsam planı bağlantısı."

    _set_if_has(period, "scope_type", "category")
    _set_if_has(period, "scope_category_label", category_label)
    _set_if_has(period, "scope_unit_label", None)
    _set_if_has(period, "scope_personnel_filter", None)
    _set_if_has(period, "special_scenario_type", "category_scope")
    _set_if_has(period, "results_published", False)
    _set_if_has(period, "is_locked", False)

    if activate_period:
        # BYS360 DEFECT W: reuses the same canonical single-active-period
        # invariant enforced by performance_period_toggle_active
        # (app/performance/admin_core_routes.py) -- activating a period
        # through this integration path must not leave two periods active.
        #
        # BYS360 DEFECT AD: this deactivation MUST be issued, and its
        # autoflush-triggered SQL MUST execute, before `period.is_active`
        # is set to True in Python below. SQLAlchemy autoflushes ALL
        # pending object changes before running a new Query.update() --
        # if `period.is_active = True` were already pending when this
        # runs, that autoflush would emit period's own UPDATE ... is_active=1
        # BEFORE the deactivation UPDATE below, momentarily leaving two
        # active rows and violating the AD unique index. Setting it True
        # only after this call keeps every emitted statement at
        # zero-or-one active rows, never two.
        (
            PerformancePeriod.query
            .filter(PerformancePeriod.is_active.is_(True), PerformancePeriod.id != period.id)
            .update({PerformancePeriod.is_active: False}, synchronize_session=False)
        )
        period.is_active = True

    _db().session.flush()
    payload = {
        "plan_key": plan_key,
        "period_id": int(period.id),
        "category_key": category_key,
        "integration_status": "period_linked",
        "created_by": created_by,
    }
    if existing:
        _db().session.execute(text(f"""
            UPDATE {INTEGRATION_TABLE}
               SET period_id=:period_id,
                   category_key=:category_key,
                   integration_status=:integration_status,
                   local_mode={_bool_sql(True)},
                   updated_at=CURRENT_TIMESTAMP,
                   created_by=:created_by
             WHERE plan_key=:plan_key
        """), payload)
    else:
        _db().session.execute(text(f"""
            INSERT INTO {INTEGRATION_TABLE}
                (plan_key, period_id, category_key, integration_status, local_mode, created_by)
            VALUES
                (:plan_key, :period_id, :category_key, :integration_status, {_bool_sql(True)}, :created_by)
        """), payload)
    _db().session.commit()
    return {
        "ok": True,
        "action": action,
        "plan_key": plan_key,
        "period_id": int(period.id),
        "period_title": period.title,
        "category_key": category_key,
        "category_label": category_label,
        "is_active": bool(getattr(period, "is_active", False)),
        "assignment_created": False,
        "rule_version": RULE_VERSION,
    }


def _full_name(user: User | None) -> str:
    if not user:
        return ""
    for attr in ("full_name", "full_name_cache"):
        value = _safe_text(getattr(user, attr, None))
        if value:
            return value
    return " ".join(x for x in [_safe_text(getattr(user, "ad", None)), _safe_text(getattr(user, "soyad", None))] if x)


def _manager_summary(user: User) -> tuple[str, bool]:
    parts = []
    has_manager = False
    fields = [("1. Amir", "yonetici_sicil"), ("2. Amir", "ikinci_yonetici_sicil"), ("3. Amir", "ucuncu_yonetici_sicil")]
    for label, attr in fields:
        value = _safe_text(getattr(user, attr, None))
        if value:
            has_manager = True
            parts.append(f"{label}: {value}")
    return (" • ".join(parts) if parts else "Tanımlı amir sicili bulunamadı", has_manager)


def build_assignment_preintegration(plan_key: str, period_id: int | None = None, *, write: bool = True) -> dict[str, Any]:
    ensure_category_period_integration_schema()
    plan = get_scope_plan(plan_key)
    if not plan:
        return {"ok": False, "message": "Plan bulunamadı.", "rows": []}
    if not period_id:
        integ = _db().session.execute(text(f"SELECT period_id FROM {INTEGRATION_TABLE} WHERE plan_key=:plan_key"), {"plan_key": plan_key}).mappings().first()
        period_id = int(integ.get("period_id") or 0) if integ else 0
    period = _find_period(period_id)
    if period is None:
        return {"ok": False, "message": "Bağlı performans dönemi bulunamadı.", "rows": []}

    items = list_plan_items(plan_key, include_person_details=False, limit=5000)
    rows: list[PreintegrationRow] = []
    ok_count = 0
    warn_count = 0
    mismatch_count = 0

    if write:
        _db().session.execute(text(f"DELETE FROM {PRECHECK_TABLE} WHERE plan_key=:plan_key AND period_id=:period_id"), {"plan_key": plan_key, "period_id": int(period.id)})

    for item in items:
        try:
            user_id = int(item.get("user_id") or 0)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            continue
        user = db.session.get(User, user_id)
        if user is None:
            continue
        scope_match = bool(employee_matches_period_scope(user, period))
        manager_summary, has_manager = _manager_summary(user)
        if not scope_match:
            status = "kapsam_uyumsuz"
            message = "Personel plan içinde var ancak gerçek dönem kategori filtresiyle eşleşmedi."
            mismatch_count += 1
        elif not has_manager:
            status = "amir_kontrol_gerekiyor"
            message = "Personelin amir sicil bilgisi kontrol edilmelidir."
            warn_count += 1
        else:
            status = "gorev_uretimi_on_hazir"
            message = "Personel kategori kapsamı ve temel amir alanları ön kontrolden geçti."
            ok_count += 1
        row = PreintegrationRow(
            user_id=user_id,
            display_name=_full_name(user),
            sicil_no=_safe_text(getattr(user, "sicil_no", "")),
            unit_name=_safe_text(getattr(user, "birim", None) or getattr(user, "ust_birim", None)),
            category_key=canonical_category_key(plan.get("category_key")),
            scope_match=scope_match,
            manager_summary=manager_summary,
            precheck_status=status,
            precheck_message=message,
        )
        rows.append(row)
        if write:
            _db().session.execute(text(f"""
                INSERT INTO {PRECHECK_TABLE}
                    (plan_key, period_id, user_id, category_key, scope_match, manager_summary, precheck_status, precheck_message)
                VALUES
                    (:plan_key, :period_id, :user_id, :category_key, :scope_match, :manager_summary, :precheck_status, :precheck_message)
            """), {
                "plan_key": plan_key,
                "period_id": int(period.id),
                "user_id": user_id,
                "category_key": row.category_key,
                "scope_match": row.scope_match,
                "manager_summary": row.manager_summary,
                "precheck_status": row.precheck_status,
                "precheck_message": row.precheck_message,
            })

    summary = {
        "total": len(rows),
        "ready": ok_count,
        "needs_manager_review": warn_count,
        "scope_mismatch": mismatch_count,
        "assignment_created": False,
        "period_id": int(period.id),
        "plan_key": plan_key,
    }
    if write:
        status = "ready" if rows and mismatch_count == 0 and warn_count == 0 else "needs_review"
        _db().session.execute(text(f"""
            UPDATE {INTEGRATION_TABLE}
               SET assignment_precheck_status=:status,
                   assignment_precheck_summary=:summary,
                   updated_at=CURRENT_TIMESTAMP
             WHERE plan_key=:plan_key
        """), {"status": status, "summary": json.dumps(summary, ensure_ascii=False), "plan_key": plan_key})
        _db().session.commit()
    return {"ok": bool(rows), "message": "Görev üretimi ön entegrasyon kontrolü tamamlandı.", "summary": summary, "rows": [r.__dict__ for r in rows], "rule_version": RULE_VERSION}


def list_integrations() -> list[dict[str, Any]]:
    ensure_category_period_integration_schema()
    rows = _db().session.execute(text(f"SELECT * FROM {INTEGRATION_TABLE} ORDER BY updated_at DESC, id DESC")).mappings().all()
    output = []
    for row in rows:
        item = dict(row)
        period = _find_period(item.get("period_id"))
        item["period_title"] = getattr(period, "title", None) if period else "Dönem bulunamadı"
        item["period_active"] = bool(getattr(period, "is_active", False)) if period else False
        item["category_label"] = _category_display_name(str(item.get("category_key") or ""))
        output.append(item)
    return output


def list_preintegration_rows(plan_key: str, period_id: int | None = None, limit: int = 120) -> list[dict[str, Any]]:
    ensure_category_period_integration_schema()
    params = {"plan_key": plan_key, "limit": max(1, min(int(limit or 120), 500))}
    where = "plan_key=:plan_key"
    if period_id:
        where += " AND period_id=:period_id"
        params["period_id"] = int(period_id)
    rows = _db().session.execute(text(f"SELECT * FROM {PRECHECK_TABLE} WHERE {where} ORDER BY id ASC LIMIT :limit"), params).mappings().all()
    output = []
    for row in rows:
        item = dict(row)
        user = db.session.get(User, int(item.get("user_id") or 0)) if item.get("user_id") else None
        item["display_name"] = _full_name(user)
        item["sicil_no"] = _safe_text(getattr(user, "sicil_no", "")) if user else ""
        item["unit_name"] = _safe_text(getattr(user, "birim", None) or getattr(user, "ust_birim", None)) if user else ""
        output.append(item)
    return output


def integration_summary() -> dict[str, Any]:
    ensure_category_period_integration_schema()
    plan_count = len(list_category_period_scope_plans(include_inactive=False))
    integration_count = int(_db().session.execute(text(f"SELECT COUNT(*) FROM {INTEGRATION_TABLE}")).scalar() or 0)
    precheck_count = int(_db().session.execute(text(f"SELECT COUNT(*) FROM {PRECHECK_TABLE}")).scalar() or 0)
    ready_count = int(_db().session.execute(text(f"SELECT COUNT(*) FROM {INTEGRATION_TABLE} WHERE assignment_precheck_status='ready'")).scalar() or 0)
    return {
        "rule_version": RULE_VERSION,
        "v215_plan_count": plan_count,
        "integration_count": integration_count,
        "preintegration_row_count": precheck_count,
        "ready_integration_count": ready_count,
        "assignment_table_touched": False,
    }
