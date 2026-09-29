from __future__ import annotations

import logging
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
    category_card_summary,
    ensure_v2_1_3_schema,
    get_personnel_category_rows,
    provision_v2_1_3_schema,
)

"""BYS360 Performans V2.1.4 kategori kapsam ve görünürlük hazırlığı.

Bu servis kategori verisini doğrudan dönem motoruna bağlamaz; canlı güvenli
hazırlık katmanı oluşturur. V2.1.5 ile dönem kapsam motoru bu yapı üzerinden
ilerleyebilir.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_4_category_scope_visibility"
SCOPE_DRAFT_TABLE = "performance_category_scope_drafts"

MANAGEMENT_ROLES = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi",
    "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "performans_yetkilisi"
}
DETAIL_ROLES = {"admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan"}


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


def _bool_true_sql() -> str:
    return "1" if _dialect_name() == "sqlite" else "TRUE"


def provision_category_scope_schema() -> dict[str, Any]:
    provision_category_schema()
    seed_default_categories(overwrite=False)
    provision_v2_1_3_schema()
    db = _db()
    created: list[str] = []
    dialect = _dialect_name()
    if not _has_table(SCOPE_DRAFT_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {SCOPE_DRAFT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_key VARCHAR(120) NOT NULL UNIQUE,
                scope_name VARCHAR(220) NOT NULL,
                scope_type VARCHAR(60) DEFAULT 'category',
                category_key VARCHAR(80) NOT NULL,
                visibility_mode VARCHAR(80) DEFAULT 'summary_only',
                notes TEXT,
                created_by INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {SCOPE_DRAFT_TABLE} (
                id SERIAL PRIMARY KEY,
                scope_key VARCHAR(120) NOT NULL UNIQUE,
                scope_name VARCHAR(220) NOT NULL,
                scope_type VARCHAR(60) DEFAULT 'category',
                category_key VARCHAR(80) NOT NULL,
                visibility_mode VARCHAR(80) DEFAULT 'summary_only',
                notes TEXT,
                created_by INTEGER,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(SCOPE_DRAFT_TABLE)
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{SCOPE_DRAFT_TABLE}_category_active ON {SCOPE_DRAFT_TABLE} (category_key, is_active)"))
    db.session.commit()
    return {"ok": True, "created": created, "dialect": dialect, "rule_version": RULE_VERSION}


CATEGORY_SCOPE_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.category_scope_drafts",
    tables=(SCOPE_DRAFT_TABLE,),
    indexes=(
        (SCOPE_DRAFT_TABLE, f"ix_{SCOPE_DRAFT_TABLE}_category_active"),
    ),
    provision=provision_category_scope_schema,
))


def ensure_category_scope_schema() -> dict[str, Any]:
    """Verify this module's tables exist; never creates them (see app.services.runtime_schema)."""
    ensure_category_schema()
    seed_default_categories(overwrite=False)
    ensure_v2_1_3_schema()
    runtime_schema.require(CATEGORY_SCOPE_SCHEMA)
    return {"ok": True, "created": [], "dialect": _dialect_name(), "rule_version": RULE_VERSION}


def normalize_role(value: Any) -> str:
    return str(value or "").strip().lower()


def can_see_category_person_details(user: Any) -> bool:
    role = normalize_role(getattr(user, "role", ""))
    return bool(role in DETAIL_ROLES or getattr(user, "is_admin", False) or getattr(user, "is_superuser", False))


def category_visibility_policy_for_user(user: Any) -> dict[str, Any]:
    role = normalize_role(getattr(user, "role", ""))
    detail = can_see_category_person_details(user)
    return {
        "role": role,
        "can_manage_scope": bool(detail or role in MANAGEMENT_ROLES),
        "can_see_person_details": detail,
        "default_visibility_mode": "detail_allowed" if detail else "summary_only",
        "person_detail_message": "Kişi detayı yetki kapsamında gösterilebilir." if detail else "Bu rolde kişi detayı gösterilmez; kategori özeti kullanılır.",
        "rule_version": RULE_VERSION,
    }


def category_scope_summaries(include_person_details: bool = False, limit_per_category: int = 25) -> list[dict[str, Any]]:
    ensure_category_scope_schema()
    cats = list_categories(include_inactive=True)
    output: list[dict[str, Any]] = []
    for cat in cats:
        rows = get_personnel_category_rows(limit=500, category_key=cat.category_key)
        active_count = sum(1 for row in rows if row.is_active)
        passive_count = max(len(rows) - active_count, 0)
        item = {
            "category_key": cat.category_key,
            "display_name": cat.display_name,
            "description": cat.description,
            "assignment_count": len(rows),
            "active_personnel_count": active_count,
            "passive_personnel_count": passive_count,
            "visibility_mode": "detail_allowed" if include_person_details else "summary_only",
            "detail_locked": not include_person_details,
            "scope_ready": len(rows) > 0,
            "draft_count": count_scope_drafts(cat.category_key),
        }
        if include_person_details:
            item["personnel_preview"] = [row.__dict__ for row in rows[:max(1, min(limit_per_category, 50))]]
        else:
            item["personnel_preview"] = []
        output.append(item)
    return output


def make_scope_key(category_key: str, suffix: str | None = None) -> str:
    key = canonical_category_key(category_key)
    if suffix:
        normalized_suffix = str(suffix).strip().lower().replace(" ", "_")[:40]
        if normalized_suffix:
            return f"category_{key}_{normalized_suffix}"
    return f"category_{key}"


def upsert_category_scope_draft(category_key: str, scope_name: str | None = None, notes: str | None = None, created_by: int | None = None, visibility_mode: str = "summary_only") -> dict[str, Any]:
    ensure_category_scope_schema()
    key = canonical_category_key(category_key)
    categories = {cat.category_key: cat.display_name for cat in list_categories(include_inactive=True)}
    if key not in categories:
        key = "diger"
    name = (scope_name or f"{categories.get(key, 'Diğer')} Kategori Kapsamı").strip()
    scope_key = make_scope_key(key)
    vm = visibility_mode if visibility_mode in {"summary_only", "detail_allowed"} else "summary_only"
    existing = _db().session.execute(text(f"SELECT id FROM {SCOPE_DRAFT_TABLE} WHERE scope_key=:scope_key"), {"scope_key": scope_key}).mappings().first()
    if existing:
        _db().session.execute(
            text(f"""
                UPDATE {SCOPE_DRAFT_TABLE}
                SET scope_name=:scope_name, category_key=:category_key, visibility_mode=:visibility_mode,
                    notes=:notes, created_by=:created_by, is_active={_bool_true_sql()}, updated_at=CURRENT_TIMESTAMP
                WHERE scope_key=:scope_key
            """),
            {"scope_name": name, "category_key": key, "visibility_mode": vm, "notes": notes, "created_by": created_by, "scope_key": scope_key},
        )
        action = "updated"
    else:
        _db().session.execute(
            text(f"""
                INSERT INTO {SCOPE_DRAFT_TABLE} (scope_key, scope_name, scope_type, category_key, visibility_mode, notes, created_by, is_active)
                VALUES (:scope_key, :scope_name, 'category', :category_key, :visibility_mode, :notes, :created_by, {_bool_true_sql()})
            """),
            {"scope_key": scope_key, "scope_name": name, "category_key": key, "visibility_mode": vm, "notes": notes, "created_by": created_by},
        )
        action = "created"
    _db().session.commit()
    return {"ok": True, "action": action, "scope_key": scope_key, "category_key": key, "scope_name": name, "rule_version": RULE_VERSION}


def deactivate_scope_draft(scope_key: str) -> dict[str, Any]:
    ensure_category_scope_schema()
    _db().session.execute(text(f"UPDATE {SCOPE_DRAFT_TABLE} SET is_active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE scope_key=:scope_key"), {"scope_key": str(scope_key)})
    _db().session.commit()
    return {"ok": True, "scope_key": scope_key, "rule_version": RULE_VERSION}


def list_scope_drafts(include_inactive: bool = False) -> list[dict[str, Any]]:
    ensure_category_scope_schema()
    where = "" if include_inactive else f"WHERE is_active={_bool_true_sql()}"
    rows = _db().session.execute(text(f"SELECT * FROM {SCOPE_DRAFT_TABLE} {where} ORDER BY created_at DESC, id DESC")).mappings().all()
    return [dict(row) for row in rows]


def count_scope_drafts(category_key: str) -> int:
    if not _has_table(SCOPE_DRAFT_TABLE):
        return 0
    value = _db().session.execute(
        text(f"SELECT COUNT(*) FROM {SCOPE_DRAFT_TABLE} WHERE category_key=:category_key AND is_active={_bool_true_sql()}"),
        {"category_key": canonical_category_key(category_key)},
    ).scalar()
    return int(value or 0)


def category_scope_dashboard_summary() -> dict[str, Any]:
    ensure_category_scope_schema()
    cats = category_scope_summaries(include_person_details=False)
    assigned_total = sum(int(item.get("assignment_count") or 0) for item in cats)
    ready_count = sum(1 for item in cats if item.get("scope_ready"))
    drafts = list_scope_drafts(include_inactive=False)
    v213 = category_card_summary()
    return {
        "rule_version": RULE_VERSION,
        "category_count": len(cats),
        "assigned_total": assigned_total,
        "ready_category_count": ready_count,
        "draft_count": len(drafts),
        "unassigned_count": v213.get("unassigned_count", 0),
        "visibility_mode": "summary_only",
    }
