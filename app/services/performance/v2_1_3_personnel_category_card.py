from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text

from app.services import runtime_schema
from app.services.performance.v2_1_2_category_engine import (
    RULE_VERSION as V212_RULE_VERSION,
    assign_user_category,
    canonical_category_key,
    ensure_category_schema,
    get_user_category,
    list_categories,
    provision_category_schema,
    seed_default_categories,
)

"""BYS360 Performans V2.1.3 personel kartı kategori entegrasyonu.

Bu servis V2.1.2 kategori tablolarını kullanır; mevcut `users` tablosunu
şema olarak değiştirmez. Personel kartı, toplu atama ve audit takibi için
kademeli ve canlı güvenli entegrasyon sağlar.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_3_personnel_category_card"
AUDIT_TABLE = "performance_personnel_category_audit_logs"


@dataclass(frozen=True)
class PersonnelCategoryRow:
    user_id: int
    display_name: str
    email: str = ""
    sicil_no: str = ""
    title: str = ""
    unit_name: str = ""
    is_active: bool = True
    category_key: str = ""
    category_name: str = "Kategori Atanmamış"
    category_source: str = ""
    category_since: str = ""


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


def _bool_expr_for_dialect(value: bool) -> str:
    if _dialect_name() == "sqlite":
        return "1" if value else "0"
    return "TRUE" if value else "FALSE"


def provision_v2_1_3_schema() -> dict[str, Any]:
    """Explicit maintenance only (flask runtime-schema provision). V2.1.3 audit tablosunu kurar ve V2.1.2 temelini doğrular."""
    provision_category_schema()
    seed_default_categories(overwrite=False)
    db = _db()
    created: list[str] = []
    dialect = _dialect_name()
    if not _has_table(AUDIT_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                old_category_key VARCHAR(80),
                new_category_key VARCHAR(80) NOT NULL,
                action VARCHAR(80) DEFAULT 'assign',
                source VARCHAR(80) DEFAULT 'manual_v2_1_3',
                actor_user_id INTEGER,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                old_category_key VARCHAR(80),
                new_category_key VARCHAR(80) NOT NULL,
                action VARCHAR(80) DEFAULT 'assign',
                source VARCHAR(80) DEFAULT 'manual_v2_1_3',
                actor_user_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(AUDIT_TABLE)
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{AUDIT_TABLE}_user_created ON {AUDIT_TABLE} (user_id, created_at)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{AUDIT_TABLE}_new_category ON {AUDIT_TABLE} (new_category_key)"))
    db.session.commit()
    return {"ok": True, "created": created, "dialect": dialect, "rule_version": RULE_VERSION}


CATEGORY_AUDIT_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.personnel_category_audit",
    tables=(AUDIT_TABLE,),
    indexes=(
        (AUDIT_TABLE, f"ix_{AUDIT_TABLE}_user_created"),
        (AUDIT_TABLE, f"ix_{AUDIT_TABLE}_new_category"),
    ),
    provision=provision_v2_1_3_schema,
))


def ensure_v2_1_3_schema() -> dict[str, Any]:
    """Verify this module's tables exist; never creates them (see app.services.runtime_schema)."""
    ensure_category_schema()
    seed_default_categories(overwrite=False)
    runtime_schema.require(CATEGORY_AUDIT_SCHEMA)
    return {"ok": True, "created": [], "dialect": _dialect_name(), "rule_version": RULE_VERSION}


def _safe_row_value(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return default


def _build_display_name(row: dict[str, Any]) -> str:
    full = _safe_row_value(row, "full_name", "display_name", "name", default="")
    if full:
        return str(full).strip()
    first = _safe_row_value(row, "first_name", "ad", "adi", default="")
    last = _safe_row_value(row, "last_name", "soyad", "soyadi", default="")
    name = f"{first} {last}".strip()
    if name:
        return name
    email = _safe_row_value(row, "email", "mail", default="")
    if email:
        return str(email)
    return f"Kullanıcı #{row.get('id')}"


def _active_value(row: dict[str, Any]) -> bool:
    for key in ("is_active", "active", "status"):
        if key not in row:
            continue
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text_value = str(value).strip().lower()
        if text_value in {"active", "aktif", "1", "true", "evet"}:
            return True
        if text_value in {"passive", "pasif", "0", "false", "hayır", "hayir"}:
            return False
    return True


def _query_users(limit: int = 100, offset: int = 0, search: str | None = None) -> list[dict[str, Any]]:
    db = _db()
    if not _has_table("users"):
        return []
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    if search:
        # Kolon adları projeden projeye değişebildiği için güvenli ve sade arama yapılır.
        # PostgreSQL/SQLite uyumlu olması için CAST kullanılır.
        like = f"%{search.strip()}%"
        stmt = text("""
            SELECT * FROM users
            WHERE CAST(id AS TEXT) LIKE :q
               OR COALESCE(CAST(email AS TEXT), '') LIKE :q
               OR COALESCE(CAST(first_name AS TEXT), '') LIKE :q
               OR COALESCE(CAST(last_name AS TEXT), '') LIKE :q
               OR COALESCE(CAST(full_name AS TEXT), '') LIKE :q
            ORDER BY id ASC
            LIMIT :limit OFFSET :offset
        """)
        try:
            rows = db.session.execute(stmt, {"q": like, "limit": limit, "offset": offset}).mappings().all()
            return [dict(row) for row in rows]
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            # Bazı kurulumlarda first_name/full_name yoksa sade listeye düş.
            pass
    rows = db.session.execute(text("SELECT * FROM users ORDER BY id ASC LIMIT :limit OFFSET :offset"), {"limit": limit, "offset": offset}).mappings().all()
    return [dict(row) for row in rows]


def get_personnel_category_rows(limit: int = 100, offset: int = 0, search: str | None = None, category_key: str | None = None) -> list[PersonnelCategoryRow]:
    ensure_v2_1_3_schema()
    users = _query_users(limit=limit, offset=offset, search=search)
    wanted_category = canonical_category_key(category_key) if category_key else ""
    rows: list[PersonnelCategoryRow] = []
    for user in users:
        user_id = int(user.get("id") or 0)
        cat = get_user_category(user_id) or {}
        current_key = str(cat.get("category_key") or "")
        if wanted_category and current_key != wanted_category:
            continue
        row = PersonnelCategoryRow(
            user_id=user_id,
            display_name=_build_display_name(user),
            email=str(_safe_row_value(user, "email", "mail", default="") or ""),
            sicil_no=str(_safe_row_value(user, "sicil_no", "sicil", "employee_no", "employee_number", default="") or ""),
            title=str(_safe_row_value(user, "title", "unvan", "position", "gorev", "görev", default="") or ""),
            unit_name=str(_safe_row_value(user, "birim", "unit_name", "organization_unit_name", "department", default="") or ""),
            is_active=_active_value(user),
            category_key=current_key,
            category_name=str(cat.get("display_name") or "Kategori Atanmamış"),
            category_source=str(cat.get("source") or ""),
            category_since=str(cat.get("valid_from") or cat.get("created_at") or ""),
        )
        rows.append(row)
    return rows


def parse_user_ids(value: Any) -> list[int]:
    raw = "" if value is None else str(value)
    ids: list[int] = []
    for token in re.split(r"[\s,;]+", raw):
        token = token.strip()
        if token.isdigit():
            number = int(token)
            if number not in ids:
                ids.append(number)
    return ids


def _write_audit(user_id: int, old_key: str | None, new_key: str, action: str, source: str, actor_user_id: int | None, notes: str | None = None) -> None:
    ensure_v2_1_3_schema()
    _db().session.execute(
        text(
            f"""
            INSERT INTO {AUDIT_TABLE} (user_id, old_category_key, new_category_key, action, source, actor_user_id, notes)
            VALUES (:user_id, :old_category_key, :new_category_key, :action, :source, :actor_user_id, :notes)
            """
        ),
        {
            "user_id": int(user_id),
            "old_category_key": old_key,
            "new_category_key": new_key,
            "action": action[:80],
            "source": source[:80],
            "actor_user_id": actor_user_id,
            "notes": notes,
        },
    )
    _db().session.commit()


def assign_personnel_category_from_card(user_id: int, category_key: str, actor_user_id: int | None = None, notes: str | None = None, source: str = "manual_v2_1_3") -> dict[str, Any]:
    ensure_v2_1_3_schema()
    old = get_user_category(int(user_id)) or {}
    old_key = old.get("category_key")
    result = assign_user_category(int(user_id), category_key, source=source, notes=notes, actor_user_id=actor_user_id)
    new_key = result.get("category_key")
    _write_audit(int(user_id), old_key, str(new_key), "assign", source, actor_user_id, notes)
    return {"ok": True, "user_id": int(user_id), "old_category_key": old_key, "new_category_key": new_key, "source": source}


def bulk_assign_personnel_category(user_ids_value: Any, category_key: str, actor_user_id: int | None = None, notes: str | None = None) -> dict[str, Any]:
    ids = parse_user_ids(user_ids_value)
    assigned: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for user_id in ids:
        try:
            assigned.append(assign_personnel_category_from_card(user_id, category_key, actor_user_id=actor_user_id, notes=notes, source="bulk_v2_1_3"))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            errors.append({"user_id": user_id, "error": str(exc)})
    return {"ok": not errors, "requested_count": len(ids), "assigned_count": len(assigned), "assigned": assigned, "errors": errors, "rule_version": RULE_VERSION}


def get_category_audit(limit: int = 50, user_id: int | None = None) -> list[dict[str, Any]]:
    ensure_v2_1_3_schema()
    limit = max(1, min(int(limit or 50), 200))
    if user_id:
        rows = _db().session.execute(
            text(f"SELECT * FROM {AUDIT_TABLE} WHERE user_id=:user_id ORDER BY created_at DESC, id DESC LIMIT :limit"),
            {"user_id": int(user_id), "limit": limit},
        ).mappings().all()
    else:
        rows = _db().session.execute(text(f"SELECT * FROM {AUDIT_TABLE} ORDER BY created_at DESC, id DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def category_card_summary() -> dict[str, Any]:
    ensure_v2_1_3_schema()
    rows = get_personnel_category_rows(limit=500)
    assigned = sum(1 for row in rows if row.category_key)
    return {
        "rule_version": RULE_VERSION,
        "v212_rule_version": V212_RULE_VERSION,
        "visible_personnel_count": len(rows),
        "assigned_count": assigned,
        "unassigned_count": max(len(rows) - assigned, 0),
        "category_count": len(list_categories(include_inactive=True)),
        "audit_count": int(_db().session.execute(text(f"SELECT COUNT(*) FROM {AUDIT_TABLE}")).scalar() or 0) if _has_table(AUDIT_TABLE) else 0,
    }


def template_get_user_category(user_id: Any) -> dict[str, Any]:
    try:
        if not user_id:
            return {"category_key": "", "display_name": "Kategori Atanmamış"}
        cat = get_user_category(int(user_id)) or {}
        if not cat:
            return {"category_key": "", "display_name": "Kategori Atanmamış"}
        return cat
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return {"category_key": "", "display_name": "Kategori Atanmamış"}
