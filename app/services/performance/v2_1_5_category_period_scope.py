from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from sqlalchemy import inspect, text

from app.services import runtime_schema
from app.services.performance.v2_1_2_category_engine import (
    canonical_category_key,
    ensure_category_schema,
    list_categories,
    provision_category_schema,
    seed_default_categories,
)
from app.services.performance.v2_1_3_personnel_category_card import (
    ensure_v2_1_3_schema,
    get_personnel_category_rows,
    provision_v2_1_3_schema,
)
from app.services.performance.v2_1_4_category_scope_visibility import (
    ensure_category_scope_schema,
    provision_category_scope_schema,
)

"""BYS360 Performans V2.1.5 kategoriye göre dönem kapsamı ve görev üretimi hazırlığı.

Bu servis gerçek dönem/görev üretimi yapmaz. Kategori bazlı kapsam planı ve
ön kontrol verisi üretir. Canlı performans tablolarına riskli yazım yapmadan
V2.1.6 dönem/görev entegrasyonuna zemin hazırlar.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_5_category_period_scope"
PLAN_TABLE = "performance_category_period_scope_plans"
PLAN_ITEM_TABLE = "performance_category_period_scope_plan_items"

PERIOD_TYPES = {
    "annual": "Yıllık",
    "six_months": "6 Aylık",
    "quarterly": "3 Aylık",
    "monthly": "Aylık",
    "special": "Özel Dönem",
}

PLAN_STATUSES = {
    "draft": "Taslak",
    "ready": "Görev Üretimine Hazır",
    "needs_review": "Kontrol Gerekiyor",
    "inactive": "Pasif",
}


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


def _bool_sql(value: bool = True) -> str:
    if _dialect_name() == "sqlite":
        return "1" if value else "0"
    return "TRUE" if value else "FALSE"


def _normalize_slug(value: Any, default: str = "plan") -> str:
    raw = str(value or "").strip().lower()
    raw = raw.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return raw or default


def _parse_date(value: Any) -> str | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        return date.fromisoformat(text_value[:10]).isoformat()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None


def _today() -> str:
    return date.today().isoformat()


def provision_category_period_scope_schema() -> dict[str, Any]:
    provision_category_schema()
    seed_default_categories(overwrite=False)
    provision_v2_1_3_schema()
    provision_category_scope_schema()
    db = _db()
    created: list[str] = []
    dialect = _dialect_name()
    if not _has_table(PLAN_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {PLAN_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_key VARCHAR(160) NOT NULL UNIQUE,
                plan_name VARCHAR(240) NOT NULL,
                category_key VARCHAR(80) NOT NULL,
                period_type VARCHAR(40) DEFAULT 'special',
                start_date DATE,
                end_date DATE,
                plan_status VARCHAR(60) DEFAULT 'draft',
                personnel_count INTEGER DEFAULT 0,
                ready_for_assignment BOOLEAN DEFAULT 0,
                scope_visibility_mode VARCHAR(80) DEFAULT 'summary_only',
                notes TEXT,
                created_by INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {PLAN_TABLE} (
                id SERIAL PRIMARY KEY,
                plan_key VARCHAR(160) NOT NULL UNIQUE,
                plan_name VARCHAR(240) NOT NULL,
                category_key VARCHAR(80) NOT NULL,
                period_type VARCHAR(40) DEFAULT 'special',
                start_date DATE,
                end_date DATE,
                plan_status VARCHAR(60) DEFAULT 'draft',
                personnel_count INTEGER DEFAULT 0,
                ready_for_assignment BOOLEAN DEFAULT FALSE,
                scope_visibility_mode VARCHAR(80) DEFAULT 'summary_only',
                notes TEXT,
                created_by INTEGER,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(PLAN_TABLE)
    if not _has_table(PLAN_ITEM_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {PLAN_ITEM_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_key VARCHAR(160) NOT NULL,
                user_id INTEGER NOT NULL,
                category_key VARCHAR(80) NOT NULL,
                eligibility_status VARCHAR(80) DEFAULT 'included',
                assignment_preview_status VARCHAR(100) DEFAULT 'gorev_uretimi_on_kontrol_bekliyor',
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {PLAN_ITEM_TABLE} (
                id SERIAL PRIMARY KEY,
                plan_key VARCHAR(160) NOT NULL,
                user_id INTEGER NOT NULL,
                category_key VARCHAR(80) NOT NULL,
                eligibility_status VARCHAR(80) DEFAULT 'included',
                assignment_preview_status VARCHAR(100) DEFAULT 'gorev_uretimi_on_kontrol_bekliyor',
                notes TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(PLAN_ITEM_TABLE)
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{PLAN_TABLE}_category_active ON {PLAN_TABLE} (category_key, is_active)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{PLAN_TABLE}_status_active ON {PLAN_TABLE} (plan_status, is_active)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{PLAN_ITEM_TABLE}_plan_user ON {PLAN_ITEM_TABLE} (plan_key, user_id)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{PLAN_ITEM_TABLE}_category ON {PLAN_ITEM_TABLE} (category_key)"))
    db.session.commit()
    return {"ok": True, "created": created, "dialect": dialect, "rule_version": RULE_VERSION}


CATEGORY_PERIOD_SCOPE_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.category_period_scope",
    tables=(PLAN_TABLE, PLAN_ITEM_TABLE),
    indexes=(
        (PLAN_TABLE, f"ix_{PLAN_TABLE}_category_active"),
        (PLAN_TABLE, f"ix_{PLAN_TABLE}_status_active"),
        (PLAN_ITEM_TABLE, f"ix_{PLAN_ITEM_TABLE}_plan_user"),
        (PLAN_ITEM_TABLE, f"ix_{PLAN_ITEM_TABLE}_category"),
    ),
    provision=provision_category_period_scope_schema,
))


def ensure_category_period_scope_schema() -> dict[str, Any]:
    """Verify this module's tables exist; never creates them (see app.services.runtime_schema)."""
    ensure_category_schema()
    seed_default_categories(overwrite=False)
    ensure_v2_1_3_schema()
    ensure_category_scope_schema()
    runtime_schema.require(CATEGORY_PERIOD_SCOPE_SCHEMA)
    return {"ok": True, "created": [], "dialect": _dialect_name(), "rule_version": RULE_VERSION}


def make_plan_key(category_key: str, period_type: str, start_date: str | None, end_date: str | None) -> str:
    cat = canonical_category_key(category_key)
    ptype = _normalize_slug(period_type or "special", "special")
    s = _normalize_slug(start_date or _today(), "start")
    e = _normalize_slug(end_date or "open", "end")
    return f"cat_period_{cat}_{ptype}_{s}_{e}"[:150]


def _category_display_name(category_key: str) -> str:
    key = canonical_category_key(category_key)
    for cat in list_categories(include_inactive=True):
        if cat.category_key == key:
            return cat.display_name
    return key


def _valid_period_type(value: Any) -> str:
    key = str(value or "special").strip().lower()
    if key not in PERIOD_TYPES:
        return "special"
    return key


def preview_category_period_scope(category_key: str, include_person_details: bool = False, limit: int = 500) -> dict[str, Any]:
    ensure_category_period_scope_schema()
    key = canonical_category_key(category_key)
    rows = get_personnel_category_rows(limit=limit, category_key=key)
    active_rows = [row for row in rows if getattr(row, "is_active", True)]
    preview = []
    if include_person_details:
        for row in active_rows[:50]:
            preview.append({
                "user_id": row.user_id,
                "display_name": row.display_name,
                "sicil_no": row.sicil_no,
                "title": row.title,
                "unit_name": row.unit_name,
                "category_key": row.category_key,
                "category_name": row.category_name,
            })
    return {
        "category_key": key,
        "display_name": _category_display_name(key),
        "total_assignment_count": len(rows),
        "active_personnel_count": len(active_rows),
        "passive_personnel_count": max(len(rows) - len(active_rows), 0),
        "ready_for_plan": len(active_rows) > 0,
        "detail_locked": not include_person_details,
        "personnel_preview": preview,
        "rule_version": RULE_VERSION,
    }


def _date_range_status(start_date: str | None, end_date: str | None) -> tuple[bool, str]:
    if not start_date or not end_date:
        return False, "Başlangıç ve bitiş tarihi girilmelidir."
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
        if e < s:
            return False, "Bitiş tarihi başlangıç tarihinden önce olamaz."
        return True, "Tarih aralığı uygun."
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False, "Tarih formatı uygun değil."


def upsert_category_period_scope_plan(
    category_key: str,
    plan_name: str | None = None,
    period_type: str = "special",
    start_date: Any = None,
    end_date: Any = None,
    notes: str | None = None,
    created_by: int | None = None,
    scope_visibility_mode: str = "summary_only",
) -> dict[str, Any]:
    ensure_category_period_scope_schema()
    key = canonical_category_key(category_key)
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    ptype = _valid_period_type(period_type)
    ok_dates, date_message = _date_range_status(start, end)
    preview = preview_category_period_scope(key, include_person_details=False)
    personnel_count = int(preview.get("active_personnel_count") or 0)
    ready = bool(ok_dates and personnel_count > 0)
    status = "ready" if ready else "needs_review"
    if not plan_name:
        label = _category_display_name(key)
        plan_name = f"{label} {PERIOD_TYPES.get(ptype, 'Özel Dönem')} Performans Kapsamı"
    plan_key = make_plan_key(key, ptype, start, end)
    vm = scope_visibility_mode if scope_visibility_mode in {"summary_only", "detail_allowed"} else "summary_only"
    db = _db()
    exists = db.session.execute(text(f"SELECT id FROM {PLAN_TABLE} WHERE plan_key=:plan_key"), {"plan_key": plan_key}).mappings().first()
    payload = {
        "plan_key": plan_key,
        "plan_name": str(plan_name).strip(),
        "category_key": key,
        "period_type": ptype,
        "start_date": start,
        "end_date": end,
        "plan_status": status,
        "personnel_count": personnel_count,
        "ready_for_assignment": ready,
        "scope_visibility_mode": vm,
        "notes": notes or date_message,
        "created_by": created_by,
    }
    if exists:
        db.session.execute(text(f"""
            UPDATE {PLAN_TABLE}
               SET plan_name=:plan_name, category_key=:category_key, period_type=:period_type,
                   start_date=:start_date, end_date=:end_date, plan_status=:plan_status,
                   personnel_count=:personnel_count, ready_for_assignment=:ready_for_assignment,
                   scope_visibility_mode=:scope_visibility_mode, notes=:notes, created_by=:created_by,
                   is_active={_bool_sql(True)}, updated_at=CURRENT_TIMESTAMP
             WHERE plan_key=:plan_key
        """), payload)
        action = "updated"
    else:
        db.session.execute(text(f"""
            INSERT INTO {PLAN_TABLE}
                (plan_key, plan_name, category_key, period_type, start_date, end_date, plan_status,
                 personnel_count, ready_for_assignment, scope_visibility_mode, notes, created_by, is_active)
            VALUES
                (:plan_key, :plan_name, :category_key, :period_type, :start_date, :end_date, :plan_status,
                 :personnel_count, :ready_for_assignment, :scope_visibility_mode, :notes, :created_by, {_bool_sql(True)})
        """), payload)
        action = "created"
    db.session.execute(text(f"DELETE FROM {PLAN_ITEM_TABLE} WHERE plan_key=:plan_key"), {"plan_key": plan_key})
    if personnel_count > 0:
        rows = get_personnel_category_rows(limit=1000, category_key=key)
        for row in rows:
            if not getattr(row, "is_active", True):
                continue
            db.session.execute(text(f"""
                INSERT INTO {PLAN_ITEM_TABLE} (plan_key, user_id, category_key, eligibility_status, assignment_preview_status, notes)
                VALUES (:plan_key, :user_id, :category_key, 'included', :preview_status, :notes)
            """), {
                "plan_key": plan_key,
                "user_id": int(row.user_id),
                "category_key": key,
                "preview_status": "gorev_uretimi_hazir" if ready else "gorev_uretimi_on_kontrol_bekliyor",
                "notes": "V2.1.5 kategori dönem kapsam planına dahil edildi.",
            })
    db.session.commit()
    return {"ok": True, "action": action, "date_message": date_message, **payload, "rule_version": RULE_VERSION}


def list_category_period_scope_plans(include_inactive: bool = False) -> list[dict[str, Any]]:
    ensure_category_period_scope_schema()
    where = "" if include_inactive else f"WHERE is_active={_bool_sql(True)}"
    rows = _db().session.execute(text(f"SELECT * FROM {PLAN_TABLE} {where} ORDER BY created_at DESC, id DESC")).mappings().all()
    output = []
    for row in rows:
        item = dict(row)
        item["category_name"] = _category_display_name(str(item.get("category_key") or ""))
        item["period_type_label"] = PERIOD_TYPES.get(str(item.get("period_type") or "special"), "Özel Dönem")
        item["plan_status_label"] = PLAN_STATUSES.get(str(item.get("plan_status") or "draft"), str(item.get("plan_status") or "Taslak"))
        output.append(item)
    return output


def list_plan_items(plan_key: str, include_person_details: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    ensure_category_period_scope_schema()
    rows = _db().session.execute(text(f"SELECT * FROM {PLAN_ITEM_TABLE} WHERE plan_key=:plan_key ORDER BY id ASC LIMIT :limit"), {"plan_key": str(plan_key), "limit": max(1, min(int(limit or 100), 500))}).mappings().all()
    output = [dict(row) for row in rows]
    if not include_person_details:
        return output
    user_map = {}
    for item in output:
        category_key = str(item.get("category_key") or "")
        for row in get_personnel_category_rows(limit=1000, category_key=category_key):
            user_map[int(row.user_id)] = row
    for item in output:
        matched_row = user_map.get(int(item.get("user_id") or 0))
        if matched_row:
            item.update({"display_name": matched_row.display_name, "sicil_no": matched_row.sicil_no, "title": matched_row.title, "unit_name": matched_row.unit_name})
    return output


def deactivate_category_period_scope_plan(plan_key: str) -> dict[str, Any]:
    ensure_category_period_scope_schema()
    _db().session.execute(text(f"UPDATE {PLAN_TABLE} SET is_active={_bool_sql(False)}, plan_status='inactive', updated_at=CURRENT_TIMESTAMP WHERE plan_key=:plan_key"), {"plan_key": str(plan_key)})
    _db().session.commit()
    return {"ok": True, "plan_key": plan_key, "rule_version": RULE_VERSION}


def category_period_scope_summary() -> dict[str, Any]:
    ensure_category_period_scope_schema()
    plans = list_category_period_scope_plans(include_inactive=False)
    ready = [p for p in plans if str(p.get("plan_status")) == "ready" or bool(p.get("ready_for_assignment"))]
    needs = [p for p in plans if str(p.get("plan_status")) == "needs_review"]
    total_personnel = sum(int(p.get("personnel_count") or 0) for p in plans)
    category_count = len(list_categories(include_inactive=True))
    return {
        "rule_version": RULE_VERSION,
        "category_count": category_count,
        "plan_count": len(plans),
        "ready_plan_count": len(ready),
        "needs_review_count": len(needs),
        "total_planned_personnel": total_personnel,
        "period_table_touched": False,
        "assignment_table_touched": False,
    }


def assignment_precheck_for_plan(plan_key: str) -> dict[str, Any]:
    ensure_category_period_scope_schema()
    plan = _db().session.execute(text(f"SELECT * FROM {PLAN_TABLE} WHERE plan_key=:plan_key"), {"plan_key": str(plan_key)}).mappings().first()
    if not plan:
        return {"ok": False, "message": "Kapsam planı bulunamadı.", "checks": []}
    items = list_plan_items(plan_key, include_person_details=False, limit=1000)
    checks = []
    def add(name: str, ok: bool, message: str):
        checks.append({"name": name, "ok": bool(ok), "message": message})
    add("date_range", bool(plan.get("start_date") and plan.get("end_date")), "Başlangıç ve bitiş tarihi kontrol edildi.")
    add("personnel_count", len(items) > 0, f"Kapsama giren personel sayısı: {len(items)}")
    add("category_key", bool(plan.get("category_key")), f"Kategori: {plan.get('category_key')}")
    add("safe_mode", True, "Bu faz gerçek değerlendirme görevi üretmez; yalnızca ön kontrol yapar.")
    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "plan_key": plan_key, "plan_name": plan.get("plan_name"), "checks": checks, "rule_version": RULE_VERSION}
