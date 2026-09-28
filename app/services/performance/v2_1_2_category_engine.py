from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text

from app.services import runtime_schema

"""BYS360 Performans V2.1.2 personel grup/kategori altyapısı.

Bu servis mevcut personel tablosunu değiştirmeden, performans kategori bilgisini
ayrı bir eşleme tablosu ile yönetir. Böylece canlı ortamda personel kartı,
Excel import ve kategori bazlı dönem/kapsam entegrasyonu sonraki fazlarda
kademeli ve güvenli biçimde bağlanabilir.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_2_personnel_category"
CATEGORY_TABLE = "performance_personnel_categories"
ASSIGNMENT_TABLE = "performance_personnel_category_assignments"

DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {
        "category_key": "guvenlik",
        "display_name": "Güvenlik",
        "description": "Güvenlik personeline özel dönem, ortalama ve raporlama kapsamı.",
        "display_order": 10,
    },
    {
        "category_key": "temizlik",
        "display_name": "Temizlik",
        "description": "Temizlik personeline özel dönem, ortalama ve raporlama kapsamı.",
        "display_order": 20,
    },
    {
        "category_key": "idari_personel",
        "display_name": "İdari Personel",
        "description": "İdari görevlerde çalışan personelin performans görünümü.",
        "display_order": 30,
    },
    {
        "category_key": "teknik_personel",
        "display_name": "Teknik Personel",
        "description": "Teknik görevlerde çalışan personelin ayrı izlenmesi.",
        "display_order": 40,
    },
    {
        "category_key": "deneme_sureli_personel",
        "display_name": "Deneme Süreli Personel",
        "description": "Deneme süresi veya geçici değerlendirme ihtiyacı olan personel.",
        "display_order": 50,
    },
    {
        "category_key": "diger",
        "display_name": "Diğer",
        "description": "Standart kategorilere girmeyen kayıtlar.",
        "display_order": 90,
    },
]

_CATEGORY_ALIASES = {
    "güvenlik": "guvenlik",
    "guvenlik": "guvenlik",
    "güvenlik personeli": "guvenlik",
    "guvenlik personeli": "guvenlik",
    "temizlik": "temizlik",
    "temizlik personeli": "temizlik",
    "idari": "idari_personel",
    "idari personel": "idari_personel",
    "idari_personel": "idari_personel",
    "teknik": "teknik_personel",
    "teknik personel": "teknik_personel",
    "teknik_personel": "teknik_personel",
    "deneme": "deneme_sureli_personel",
    "deneme süreli": "deneme_sureli_personel",
    "deneme sureli": "deneme_sureli_personel",
    "deneme süreli personel": "deneme_sureli_personel",
    "deneme sureli personel": "deneme_sureli_personel",
    "diğer": "diger",
    "diger": "diger",
}

_TITLE_HINTS = [
    ("guvenlik", ("güvenlik", "guvenlik")),
    ("temizlik", ("temizlik",)),
    ("teknik_personel", ("mühendis", "muhendis", "mimar", "tekniker", "teknisyen", "teknik")),
    ("idari_personel", ("memur", "büro", "buro", "idari", "uzman", "şef", "sef")),
]


@dataclass(frozen=True)
class CategorySummary:
    category_key: str
    display_name: str
    description: str = ""
    display_order: int = 0
    is_active: bool = True
    assignment_count: int = 0


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


def has_category_tables() -> bool:
    return _has_table(CATEGORY_TABLE) and _has_table(ASSIGNMENT_TABLE)


def provision_category_schema() -> dict[str, Any]:
    """Create the category tables (explicit maintenance only: flask runtime-schema provision).

    Mevcut çekirdek personel/performance tablolarına dokunmaz.
    """
    db = _db()
    created: list[str] = []
    dialect = _dialect_name()

    if not _has_table(CATEGORY_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {CATEGORY_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_key VARCHAR(80) NOT NULL UNIQUE,
                display_name VARCHAR(160) NOT NULL,
                description TEXT,
                display_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {CATEGORY_TABLE} (
                id SERIAL PRIMARY KEY,
                category_key VARCHAR(80) NOT NULL UNIQUE,
                display_name VARCHAR(160) NOT NULL,
                description TEXT,
                display_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(CATEGORY_TABLE)

    if not _has_table(ASSIGNMENT_TABLE):
        if dialect == "sqlite":
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {ASSIGNMENT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category_id INTEGER,
                category_key VARCHAR(80) NOT NULL,
                source VARCHAR(80) DEFAULT 'manual',
                notes TEXT,
                valid_from DATE,
                valid_to DATE,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {ASSIGNMENT_TABLE} (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                category_id INTEGER,
                category_key VARCHAR(80) NOT NULL,
                source VARCHAR(80) DEFAULT 'manual',
                notes TEXT,
                valid_from DATE,
                valid_to DATE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        db.session.execute(text(ddl))
        created.append(ASSIGNMENT_TABLE)

    # İndeksler idempotent tutulur. SQLite ve PostgreSQL IF NOT EXISTS destekler.
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{ASSIGNMENT_TABLE}_user_active ON {ASSIGNMENT_TABLE} (user_id, is_active)"))
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{ASSIGNMENT_TABLE}_category_active ON {ASSIGNMENT_TABLE} (category_key, is_active)"))
    db.session.commit()
    return {"ok": True, "created": created, "dialect": dialect}


CATEGORY_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.personnel_categories",
    tables=(CATEGORY_TABLE, ASSIGNMENT_TABLE),
    indexes=(
        (ASSIGNMENT_TABLE, f"ix_{ASSIGNMENT_TABLE}_user_active"),
        (ASSIGNMENT_TABLE, f"ix_{ASSIGNMENT_TABLE}_category_active"),
    ),
    provision=provision_category_schema,
))


def ensure_category_schema() -> dict[str, Any]:
    """Verify the category tables exist; never creates them (see app.services.runtime_schema)."""
    runtime_schema.require(CATEGORY_SCHEMA)
    return {"ok": True, "created": [], "dialect": _dialect_name()}


def normalize_category_key(value: Any) -> str:
    raw = "" if value is None else str(value).strip().lower()
    if not raw:
        return "diger"
    raw = raw.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return raw or "diger"


def canonical_category_key(value: Any) -> str:
    raw = "" if value is None else str(value).strip().lower()
    if raw in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[raw]
    normalized = normalize_category_key(raw)
    return _CATEGORY_ALIASES.get(normalized.replace("_", " "), _CATEGORY_ALIASES.get(normalized, normalized))


def seed_default_categories(overwrite: bool = False) -> dict[str, Any]:
    ensure_category_schema()
    db = _db()
    created = updated = unchanged = 0
    details: list[dict[str, str]] = []
    dialect = _dialect_name()

    for item in DEFAULT_CATEGORIES:
        exists = db.session.execute(
            text(f"SELECT id, display_name, description, display_order, is_active FROM {CATEGORY_TABLE} WHERE category_key=:key"),
            {"key": item["category_key"]},
        ).mappings().first()
        if exists:
            if overwrite:
                db.session.execute(
                    text(
                        f"""
                        UPDATE {CATEGORY_TABLE}
                        SET display_name=:display_name, description=:description, display_order=:display_order, is_active=:is_active, updated_at=CURRENT_TIMESTAMP
                        WHERE category_key=:category_key
                        """
                    ),
                    {**item, "is_active": True},
                )
                updated += 1
                details.append({"category_key": item["category_key"], "action": "updated"})
            else:
                unchanged += 1
                details.append({"category_key": item["category_key"], "action": "unchanged"})
            continue
        db.session.execute(
            text(
                f"""
                INSERT INTO {CATEGORY_TABLE} (category_key, display_name, description, display_order, is_active)
                VALUES (:category_key, :display_name, :description, :display_order, :is_active)
                """
            ),
            {**item, "is_active": True},
        )
        created += 1
        details.append({"category_key": item["category_key"], "action": "created"})

    db.session.commit()
    return {"ok": True, "created": created, "updated": updated, "unchanged": unchanged, "details": details, "rule_version": RULE_VERSION, "dialect": dialect}


def list_categories(include_inactive: bool = False) -> list[CategorySummary]:
    ensure_category_schema()
    where = "" if include_inactive else "WHERE c.is_active = TRUE"
    if _dialect_name() == "sqlite" and where:
        where = "WHERE c.is_active = 1"
    rows = _db().session.execute(
        text(
            f"""
            SELECT c.category_key, c.display_name, c.description, c.display_order, c.is_active,
                   COALESCE(SUM(CASE WHEN a.is_active THEN 1 ELSE 0 END), 0) AS assignment_count
            FROM {CATEGORY_TABLE} c
            LEFT JOIN {ASSIGNMENT_TABLE} a ON a.category_key = c.category_key
            {where}
            GROUP BY c.category_key, c.display_name, c.description, c.display_order, c.is_active
            ORDER BY c.display_order ASC, c.display_name ASC
            """
        )
    ).mappings().all()
    return [
        CategorySummary(
            category_key=row["category_key"],
            display_name=row["display_name"],
            description=row.get("description") or "",
            display_order=int(row.get("display_order") or 0),
            is_active=bool(row.get("is_active")),
            assignment_count=int(row.get("assignment_count") or 0),
        )
        for row in rows
    ]


def get_category_key_set() -> set[str]:
    return {item.category_key for item in list_categories(include_inactive=True)}


def assign_user_category(user_id: int, category_key: str, source: str = "manual", notes: str | None = None, actor_user_id: int | None = None) -> dict[str, Any]:
    ensure_category_schema()
    key = canonical_category_key(category_key)
    valid_keys = get_category_key_set()
    if key not in valid_keys:
        key = "diger"
    db = _db()
    category = db.session.execute(text(f"SELECT id FROM {CATEGORY_TABLE} WHERE category_key=:key"), {"key": key}).mappings().first()
    category_id = category["id"] if category else None
    # Önce kullanıcının aktif kategori kaydını kapat, sonra yeni aktif kayıt oluştur.
    db.session.execute(
        text(f"UPDATE {ASSIGNMENT_TABLE} SET is_active=FALSE, valid_to=CURRENT_DATE, updated_at=CURRENT_TIMESTAMP WHERE user_id=:user_id AND is_active=TRUE"),
        {"user_id": int(user_id)},
    )
    db.session.execute(
        text(
            f"""
            INSERT INTO {ASSIGNMENT_TABLE} (user_id, category_id, category_key, source, notes, valid_from, is_active)
            VALUES (:user_id, :category_id, :category_key, :source, :notes, CURRENT_DATE, TRUE)
            """
        ),
        {"user_id": int(user_id), "category_id": category_id, "category_key": key, "source": source[:80], "notes": notes},
    )
    db.session.commit()
    return {"ok": True, "user_id": int(user_id), "category_key": key, "source": source, "actor_user_id": actor_user_id}


def get_user_category(user_id: int) -> dict[str, Any] | None:
    ensure_category_schema()
    row = _db().session.execute(
        text(
            f"""
            SELECT a.user_id, a.category_key, c.display_name, a.source, a.valid_from, a.created_at
            FROM {ASSIGNMENT_TABLE} a
            LEFT JOIN {CATEGORY_TABLE} c ON c.category_key = a.category_key
            WHERE a.user_id=:user_id AND a.is_active=TRUE
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 1
            """
        ),
        {"user_id": int(user_id)},
    ).mappings().first()
    return dict(row) if row else None


def infer_category_from_title(title: Any) -> str:
    text_value = "" if title is None else str(title).strip().lower()
    if not text_value:
        return "diger"
    for category_key, needles in _TITLE_HINTS:
        if any(needle in text_value for needle in needles):
            return category_key
    return "diger"


def infer_category_from_import_row(row: dict[str, Any]) -> str:
    """Excel/import entegrasyonu için kategori sütunu yakalama yardımcısı.

    Bu fonksiyon veri yazmaz; yalnızca sonraki import fazlarında kullanılacak
    güvenli kategori anahtarını döndürür.
    """
    category_columns = ("kategori", "personel_kategorisi", "performans_kategorisi", "grup", "personel_grubu")
    lower_row = {str(k).strip().lower(): v for k, v in (row or {}).items()}
    for col in category_columns:
        if lower_row.get(col):
            key = canonical_category_key(lower_row[col])
            if key in {item["category_key"] for item in DEFAULT_CATEGORIES}:
                return key
    title_columns = ("unvan", "gorev", "görev", "pozisyon")
    for col in title_columns:
        if lower_row.get(col):
            return infer_category_from_title(lower_row[col])
    return "diger"


def category_scope_summary() -> dict[str, Any]:
    cats = list_categories()
    return {
        "rule_version": RULE_VERSION,
        "table": CATEGORY_TABLE,
        "assignment_table": ASSIGNMENT_TABLE,
        "category_count": len(cats),
        "assignment_total": sum(item.assignment_count for item in cats),
        "categories": [item.__dict__ for item in cats],
    }
