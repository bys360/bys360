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

from app.extensions import db
from app.models import EvaluationAssignment, PerformanceEvaluation

logger = logging.getLogger(__name__)

# BYS360_INTERIM_NOTES_FROM_MANAGER_PAGE_RUNTIME
# BYS360_INTERIM_NOTES_MANAGER_PAGE_SOURCE
# BYS360_INTERIM_NOTES_SCORECARD_MARKED_ONLY
# BYS360_INTERIM_NOTES_RUNTIME_BINDING

TABLE_NAME = "performance_interim_notes"
# Şema sahibi Alembic revision x1f3a9c5e7b2'dir (flask db upgrade). İstek kodu bu tabloyu
# oluşturmaz, kolon veya indeks eklemez; yalnız hazır olup olmadığını salt okuma ile denetler.
REQUIRED_COLUMNS = frozenset({
    "id", "period_id", "employee_id", "employee_user_id", "manager_id", "created_by", "created_by_id",
    "note_type", "title", "note_title", "note", "note_body", "note_text", "content", "description",
    "visibility_level", "visibility_scope", "remind_in_evaluation", "remind_during_scoring",
    "include_in_scorecard", "visible_on_scorecard", "is_active", "active", "occurred_at", "created_at", "updated_at",
})
INDEXES = ("ix_perf_interim_notes_employee_period", "ix_perf_interim_notes_employee_user_period")

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


def _schema_ready() -> bool:
    """Salt okuma: tablo, kanonik kolonlar ve iki indeks migration ile hazırlanmışsa True döner."""
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table(TABLE_NAME):
            return False
        existing_columns = {col["name"] for col in inspector.get_columns(TABLE_NAME)}
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(TABLE_NAME)}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False
    return existing_columns >= REQUIRED_COLUMNS and existing_indexes >= set(INDEXES)


def ensure_interim_notes_table() -> tuple[bool, list[str]]:
    """Dönem içi not tablosunun hazır olup olmadığını salt okuma ile denetler.

    Tablo Alembic revision x1f3a9c5e7b2 ile oluşturulur/benimsenir; bu yardımcı DDL
    çalıştırmaz. Hazır değilse uyarı döner ve okuyucular boş sonuçla devam eder.
    İşlem sınırına dokunmaz: commit, rollback veya flush yapmaz; çağıranın bekleyen
    oturum işi çağıranın kendi iş işlemine aittir (G3-B, HD-10 Seçenek A).
    """
    warnings: list[str] = []
    ready = _schema_ready()
    if not ready:
        warnings.append("Dönem içi not tablosu hazır değil; veritabanı migration'ı (flask db upgrade) çalıştırılmalıdır.")
    return ready, warnings


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
    # NULLS LAST, her lehçede aynı tek sorguyla: boş tarihli kayıtlar en sona. Hata halinde
    # çağıranın işlemi geri alınmaz ve hata boş sonuçla gizlenmez; işlemin sahibi çağırandır.
    sql = text(f"""
        SELECT {', '.join(select_cols)}
        FROM {TABLE_NAME}
        WHERE {' AND '.join(where)}
        ORDER BY CASE WHEN {order_col} IS NULL THEN 1 ELSE 0 END, {order_col} DESC, id DESC
        LIMIT :limit
    """)
    rows = db.session.execute(sql, params).mappings().all()
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
