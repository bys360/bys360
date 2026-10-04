"""Dönem içi notların değerlendirme ve karne ekranlarında güvenli gösterimi.

Kaynak ekran: /performance/interim-notes
- Faz 3 değerlendirme ekranı: personel için kaydedilmiş dönem içi notları salt okunur hatırlatma olarak gösterir.
- Karne detayı/PDF: yalnızca "Karne detayında gösterilsin" işaretli notları gösterir.

Notlar otomatik puan üretmez ve değerlendirme formundan yeni not kaydedilmez.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import EvaluationAssignment, PerformanceEvaluation

logger = logging.getLogger(__name__)

# BYS360_INTERIM_NOTES_FROM_MANAGER_PAGE_RUNTIME
# BYS360_INTERIM_NOTES_MANAGER_PAGE_SOURCE
# BYS360_INTERIM_NOTES_SCORECARD_MARKED_ONLY
# BYS360_INTERIM_NOTES_RUNTIME_BINDING

TABLE_NAME = "performance_interim_notes"
INDEXES = {
    "ix_perf_interim_notes_employee_period": "employee_id, period_id",
    "ix_perf_interim_notes_employee_user_period": "employee_user_id, period_id",
}

NOTE_TYPE_LABELS = {
    "olumlu_olay": "Olumlu Olay",
    "olumsuz_olay": "Olumsuz Olay",
    "basari": "Başarı",
    "gelisim_ihtiyaci": "Gelişim İhtiyacı",
    "genel_gozlem": "Genel Gözlem",
    "positive": "Olumlu Olay",
    "negative": "Olumsuz Olay",
    "success": "Başarı",
    "development": "Gelişim İhtiyacı",
    "general": "Genel Gözlem",
}

NOTE_TYPE_OPTIONS = [
    ("olumlu_olay", "Olumlu Olay"),
    ("olumsuz_olay", "Olumsuz Olay"),
    ("basari", "Başarı"),
    ("gelisim_ihtiyaci", "Gelişim İhtiyacı"),
    ("genel_gozlem", "Genel Gözlem"),
]


def _dialect_name() -> str:
    # BYS360 DEFECT AR: db.session.bind her zaman None doner (bu
    # SQLAlchemy/Flask-SQLAlchemy surumunde bagli motoru gostermiyor);
    # db.session.get_bind() gercek motoru dondurur. Eski kod bu yuzden
    # istisnaya duserek sessizce "postgresql" varsayilanina donuyordu --
    # yani _id_sql()/_bool_sql() SQLite'ta bile hep PostgreSQL dalini
    # aliyordu (id sutunu SQLite'ta kalici NULL kaliyordu).
    try:
        return db.session.get_bind().dialect.name
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return "postgresql"


def _bool_sql(default: bool | None = None) -> str:
    if _dialect_name() == "sqlite":
        if default is None:
            return "INTEGER"
        return "INTEGER DEFAULT " + ("1" if default else "0")
    if default is None:
        return "BOOLEAN"
    return "BOOLEAN DEFAULT " + ("TRUE" if default else "FALSE")


def _id_sql() -> str:
    # BYS360_PHASE10_INTERIM_NOTES_CREATE_TABLE_ID_FIX_V1_1
    # CREATE TABLE kolon tanımında kolon adı zorunludur.
    return "id INTEGER PRIMARY KEY AUTOINCREMENT" if _dialect_name() == "sqlite" else "id SERIAL PRIMARY KEY"


def _has_table(table_name: str) -> bool:
    try:
        return inspect(db.engine).has_table(table_name)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return set()


def _schema_complete(columns: dict[str, str]) -> bool:
    """Salt okuma: tablo, verilen kolonların tümü ve iki indeks zaten varsa True döner."""
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table(TABLE_NAME):
            return False
        existing_columns = {col["name"] for col in inspector.get_columns(TABLE_NAME)}
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(TABLE_NAME)}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False
    return set(columns) <= existing_columns and set(INDEXES) <= existing_indexes


def _safe_add_column(table_name: str, column: str, ddl: str, existing: set[str], warnings: list[str]) -> None:
    if column in existing:
        return
    try:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {ddl}"))
        db.session.commit()
        existing.add(column)
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        warnings.append(f"{column} kolonu eklenemedi: {exc.__class__.__name__}")


def ensure_interim_notes_table() -> tuple[bool, list[str]]:
    """Dönem içi not tablosunu idempotent biçimde hazırlar.

    Yönetim sayfası /performance/interim-notes bu tabloyu kullanır.
    Buradaki amaç tablo yoksa güvenli temel yapıyı kurmak; varsa mevcut veriye dokunmamaktır.
    """
    warnings: list[str] = []
    desired_columns = {
        "period_id": "INTEGER NULL",
        "employee_id": "INTEGER NULL",
        "employee_user_id": "INTEGER NULL",
        "manager_id": "INTEGER NULL",
        "created_by": "INTEGER NULL",
        "created_by_id": "INTEGER NULL",
        "note_type": "VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem'",
        "title": "VARCHAR(255) NULL",
        "note_title": "VARCHAR(255) NULL",
        "note": "TEXT NULL",
        "note_body": "TEXT NULL",
        "note_text": "TEXT NULL",
        "content": "TEXT NULL",
        "description": "TEXT NULL",
        "visibility_level": "VARCHAR(80) NULL DEFAULT 'manager_scope'",
        "visibility_scope": "VARCHAR(80) NULL DEFAULT 'manager_scope'",
        "remind_in_evaluation": _bool_sql(True) + " NULL",
        "remind_during_scoring": _bool_sql(True) + " NULL",
        "include_in_scorecard": _bool_sql(False) + " NULL",
        "visible_on_scorecard": _bool_sql(False) + " NULL",
        "is_active": _bool_sql(True) + " NULL",
        "active": _bool_sql(True) + " NULL",
        "occurred_at": "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
        "created_at": "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
    }
    if _schema_complete(desired_columns):
        # EC-AUD-016B-1: şema eksiksizse DDL çalıştırılmaz. Mevcut commit sınırı
        # (bekleyen oturum işini commit etmesi) ayrı bir kararla ele alınana kadar korunur.
        try:
            db.session.commit()
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            db.session.rollback()
            warnings.append(f"Dönem içi not tablosu hazırlanamadı: {exc.__class__.__name__}")
            return False, warnings
        return True, warnings

    try:
        db.session.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                {_id_sql()},
                period_id INTEGER NULL,
                employee_id INTEGER NULL,
                employee_user_id INTEGER NULL,
                manager_id INTEGER NULL,
                created_by INTEGER NULL,
                created_by_id INTEGER NULL,
                note_type VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem',
                title VARCHAR(255) NULL,
                note_title VARCHAR(255) NULL,
                note TEXT NULL,
                note_body TEXT NULL,
                note_text TEXT NULL,
                content TEXT NULL,
                description TEXT NULL,
                visibility_level VARCHAR(80) NOT NULL DEFAULT 'manager_scope',
                visibility_scope VARCHAR(80) NULL DEFAULT 'manager_scope',
                remind_in_evaluation {_bool_sql(True)} NULL,
                remind_during_scoring {_bool_sql(True)} NULL,
                include_in_scorecard {_bool_sql(False)} NULL,
                visible_on_scorecard {_bool_sql(False)} NULL,
                is_active {_bool_sql(True)} NULL,
                active {_bool_sql(True)} NULL,
                occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        warnings.append(f"Dönem içi not tablosu hazırlanamadı: {exc.__class__.__name__}")
        return False, warnings

    existing = _columns(TABLE_NAME)
    for column, ddl in desired_columns.items():
        _safe_add_column(TABLE_NAME, column, ddl, existing, warnings)

    for index_name, index_columns in INDEXES.items():
        try:
            db.session.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {TABLE_NAME}({index_columns})"))
            db.session.commit()
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            db.session.rollback()
    return _has_table(TABLE_NAME), warnings


def _pick_column(cols: set[str], *names: str) -> str | None:
    for name in names:
        if name in cols:
            return name
    return None


def _row_to_note(row: Any) -> dict[str, Any]:
    mapping = getattr(row, "_mapping", row)
    raw_type = str(mapping.get("note_type") or "genel_gozlem").strip()
    title = str(
        mapping.get("title")
        or mapping.get("note_title")
        or NOTE_TYPE_LABELS.get(raw_type)
        or "Dönem İçi Not"
    ).strip()
    body = str(
        mapping.get("note_body")
        or mapping.get("note")
        or mapping.get("note_text")
        or mapping.get("content")
        or mapping.get("description")
        or ""
    ).strip()
    created_at = mapping.get("created_at") or mapping.get("occurred_at")
    if isinstance(created_at, datetime):
        created_display = created_at.strftime("%d.%m.%Y %H:%M")
    else:
        created_display = str(created_at or "-")
    include_value = mapping.get("include_in_scorecard") or mapping.get("visible_on_scorecard")
    return {
        "id": mapping.get("id"),
        "note_type": raw_type,
        "note_type_label": NOTE_TYPE_LABELS.get(raw_type, "Bilinmiyor"),
        "title": title,
        "body": body,
        "note_body": body,
        "created_at": created_at,
        "created_display": created_display,
        "include_in_scorecard": bool(include_value),
    }


def _fetch_notes_from_manager_page(
    *,
    employee_id: int | None,
    period_id: int | None,
    employee_visible_only: bool = False,
    scorecard_marked_only: bool = False,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Aynı /performance/interim-notes sayfasının kullandığı tablodan okur.

    Değerlendirme ekranında remind_in_evaluation/remind_during_scoring filtresi uygulanmaz;
    çünkü yönetim sayfasından eklenen eski kayıtlarda bu alanlar FALSE olabilir.

    Karne/PDF yüzeylerinde ise yalnızca "Karne detayında gösterilsin" işaretli
    kayıtlar döner. Böylece dönem içi özel çalışma notları, işaretlenmeden karneye taşınmaz.
    """
    if not employee_id:
        return []
    ensure_interim_notes_table()
    cols = _columns(TABLE_NAME)
    if not cols or "id" not in cols:
        return []

    employee_col = _pick_column(cols, "employee_id", "employee_user_id")
    if not employee_col:
        return []

    title_col = _pick_column(cols, "title", "note_title")
    body_col = _pick_column(cols, "note_body", "note", "note_text", "content", "description")
    include_col = _pick_column(cols, "include_in_scorecard", "visible_on_scorecard")
    active_col = _pick_column(cols, "is_active", "active")
    occurred_col = _pick_column(cols, "created_at", "occurred_at", "updated_at")
    type_col = _pick_column(cols, "note_type", "type")

    # Karne yüzeyinde işaret alanı yoksa güvenli davran: hiçbir ara notu karneye taşıma.
    if scorecard_marked_only and not include_col:
        return []

    select_cols = ["id"]
    select_cols.append(f"{type_col} AS note_type" if type_col else "'genel_gozlem' AS note_type")
    select_cols.append(f"{title_col} AS title" if title_col else "'' AS title")
    select_cols.append(f"{body_col} AS note_body" if body_col else "'' AS note_body")
    select_cols.append(f"{occurred_col} AS created_at" if occurred_col else "NULL AS created_at")
    select_cols.append(f"{include_col} AS include_in_scorecard" if include_col else "FALSE AS include_in_scorecard")

    where = [f"{employee_col} = :employee_id"]
    params: dict[str, Any] = {"employee_id": int(employee_id), "limit": int(limit)}
    if "period_id" in cols and period_id:
        where.append("(period_id = :period_id OR period_id IS NULL)")
        params["period_id"] = int(period_id)
    if scorecard_marked_only or employee_visible_only:
        where.append(f"COALESCE({include_col}, FALSE) = TRUE")
    if active_col:
        where.append(f"COALESCE({active_col}, TRUE) = TRUE")

    order_col = occurred_col or "id"
    sql = text(f"""
        SELECT {', '.join(select_cols)}
        FROM {TABLE_NAME}
        WHERE {' AND '.join(where)}
        ORDER BY {order_col} DESC NULLS LAST, id DESC
        LIMIT :limit
    """)
    try:
        rows = db.session.execute(sql, params).mappings().all()
    except SQLAlchemyError:
        db.session.rollback()
        try:
            rows = db.session.execute(text(str(sql).replace(" DESC NULLS LAST", " DESC")), params).mappings().all()
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            db.session.rollback()
            return []
    return [_row_to_note(row) for row in rows]


def build_interim_notes_context(*, assignment: EvaluationAssignment, evaluation: PerformanceEvaluation | None = None, viewer: Any = None, surface: str = "scoring") -> dict[str, Any]:
    employee_id = getattr(assignment, "employee_id", None) or getattr(evaluation, "employee_id", None)
    period_id = getattr(assignment, "period_id", None) or getattr(evaluation, "period_id", None)
    notes = _fetch_notes_from_manager_page(
        employee_id=employee_id,
        period_id=period_id,
        employee_visible_only=False,
        scorecard_marked_only=False,
        limit=10,
    )
    return {
        "enabled": True,
        "source": "/performance/interim-notes",
        "surface": surface,
        "notes": notes,
        "count": len(notes),
        "note_type_options": NOTE_TYPE_OPTIONS,
        "no_auto_score_text": "Bu notlar otomatik puan üretmez; yalnızca değerlendirme sırasında hatırlatma sağlar.",
    }


def build_scorecard_interim_notes(*, evaluation: PerformanceEvaluation, viewer: Any = None) -> dict[str, Any]:
    """Karne detayı ve PDF için işaretli dönem içi notları döndürür."""
    employee_visible = bool(viewer and getattr(viewer, "id", None) == getattr(evaluation, "employee_id", None))
    notes = _fetch_notes_from_manager_page(
        employee_id=getattr(evaluation, "employee_id", None),
        period_id=getattr(evaluation, "period_id", None),
        employee_visible_only=False,
        scorecard_marked_only=True,
        limit=12,
    )
    return {
        "enabled": True,
        "source": "/performance/interim-notes",
        "surface": "scorecard",
        "notes": notes,
        "count": len(notes),
        "employee_visible_only": employee_visible,
        "scorecard_marked_only": True,
        "no_auto_score_text": "Dönem içi notlar karne puanını otomatik değiştirmez; yalnızca süreç hafızası ve gelişim takibi sağlar.",
    }


def add_interim_note_from_assignment(*args: Any, **kwargs: Any) -> None:
    """Geriye dönük import uyumluluğu.

    Değerlendirme çalışma alanından not ekleme kapatıldı. Notlar yalnızca
    /performance/interim-notes ekranından oluşturulmalıdır.
    """
    raise ValueError("Dönem içi notlar değerlendirme ekranından eklenmez; /performance/interim-notes sayfasından kaydedilir.")
