from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

"""BYS360 Toplantı Kararları — Faz 8 P2 arşiv ve ara not servisi.

Bu servis, toplantıdan çıkan iki P2 ihtiyacını canlı omurgaya bağlar:
1) geçmiş yıl karne/puan arşivi,
2) performans dönemi içinde alınan olumlu/olumsuz ara notların puanlamada hatırlatılması.

Not: Tam Eğitim modülü canlı kapsamda açılmadan, gelişim önerisi yalnızca performans içi
rehber/gelişim notu seviyesinde tutulur.
"""

logger = logging.getLogger(__name__)

P2_ARCHIVE_NOTES_VERSION = "2026-04-30-meeting-p2-faz8"

P2_REQUIRED_SETTINGS = {
    "performance_archive_enabled": {"label": "Geçmiş karne arşivi aktif", "value": "true", "description": "Eski yıllara ait performans puanı ve karne özetlerinin sisteme alınmasını sağlar."},
    "performance_archive_employee_self_view": {"label": "Personel kendi geçmişini görebilir", "value": "true", "description": "Personel yalnızca kendi geçmiş performans kayıtlarını görür."},
    "performance_archive_manager_scope_view": {"label": "Yönetici kapsamlı geçmiş arşiv görür", "value": "true", "description": "Koordinatör ve grup başkanı yalnızca yetkili kapsamındaki geçmiş karne kayıtlarını görebilir."},
    "performance_interim_notes_enabled": {"label": "Ara dönem notları aktif", "value": "true", "description": "Performans dönemi içinde olumlu/olumsuz olay, başarı ve gelişim ihtiyacı notları tutulabilir."},
    "performance_interim_notes_scoring_reminder": {"label": "Ara notlar puanlamada hatırlatılır", "value": "true", "description": "Yetkili amire puanlama sırasında ara dönem notları hatırlatma olarak gösterilir."},
    "performance_interim_notes_no_auto_score": {"label": "Ara notlar otomatik puan üretmez", "value": "true", "description": "Ara dönem notları karar destek niteliğindedir; sistem otomatik performans puanı belirlemez."},
    "performance_interim_notes_scorecard_visibility": {"label": "Ara not karne görünürlüğü ayara bağlı", "value": "false", "description": "Ara notların karne çıktısına yansıyıp yansımayacağı ayrıca yönetilir."},
}

P2_ARCHIVE_TABLE = "performance_scorecard_archive"
P2_INTERIM_NOTES_TABLE = "performance_interim_notes"

P2_NOTE_TYPES = [
    {"value": "positive_event", "label": "Olumlu Olay", "description": "Dönem içinde personelin olumlu davranış, katkı veya iş çıktısı notu."},
    {"value": "negative_event", "label": "Olumsuz Olay", "description": "Dönem içinde gelişim veya dikkat gerektiren olay notu."},
    {"value": "success", "label": "Başarı", "description": "Somut başarı, proje katkısı veya güçlü performans notu."},
    {"value": "development_need", "label": "Gelişim İhtiyacı", "description": "Eğitim, rehberlik veya takip önerisi gerektiren gelişim alanı."},
    {"value": "general_observation", "label": "Genel Gözlem", "description": "Dönemsel izlenim ve yönetsel gözlem notu."},
]

P2_ARCHIVE_REQUIRED_COLUMNS = {"id", "employee_user_id", "registry_no", "year", "period_label", "score", "result_label", "explanation", "source_document", "created_by", "created_at", "updated_at"}
P2_INTERIM_REQUIRED_COLUMNS = {"id", "employee_user_id", "period_id", "note_type", "note_title", "note_body", "visibility_scope", "remind_during_scoring", "include_in_scorecard", "created_by", "created_at", "updated_at"}

@dataclass(slots=True)
class P2ArchiveNotesResult:
    ok: bool
    version: str
    settings_seeded: int = 0
    tables_ready: int = 0
    checks_passed: int = 0
    message: str = ""
    warnings: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "version": self.version, "settings_seeded": self.settings_seeded, "tables_ready": self.tables_ready, "checks_passed": self.checks_passed, "message": self.message, "warnings": list(self.warnings or [])}


def _dialect() -> str:
    try:
        return db.engine.dialect.name
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return "unknown"


def _has_table(table_name: str) -> bool:
    try:
        return bool(inspect(db.engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return set()


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        return db.session.execute(text(sql), params or {}).scalar()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in db.session.execute(text(sql), params or {}).mappings().all()]
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return []


def _setting_exists(setting_key: str) -> bool:
    if not _has_table("module_settings"):
        return False
    return bool(_scalar("""SELECT id FROM module_settings WHERE module_key='performance' AND setting_key=:setting_key LIMIT 1""", {"setting_key": setting_key}))


def ensure_p2_settings() -> int:
    if not _has_table("module_settings"):
        return 0
    seeded = 0
    for key, payload in P2_REQUIRED_SETTINGS.items():
        if _setting_exists(key):
            continue
        db.session.execute(text("""
            INSERT INTO module_settings
                (module_key, setting_key, label, value_text, value_type, description, is_active, created_at, updated_at)
            VALUES
                ('performance', :key, :label, :value, 'boolean', :description, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"key": key, "label": payload["label"], "value": payload["value"], "description": payload["description"]})
        seeded += 1
    return seeded


def _id_column_sql() -> str:
    if _dialect() == "postgresql":
        return "id SERIAL PRIMARY KEY"
    return "id INTEGER PRIMARY KEY AUTOINCREMENT"


def ensure_archive_table() -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if _has_table(P2_ARCHIVE_TABLE):
        return True, warnings
    try:
        db.session.execute(text(f"""
            CREATE TABLE {P2_ARCHIVE_TABLE} (
                {_id_column_sql()}, employee_user_id INTEGER NOT NULL, registry_no VARCHAR(64), year INTEGER NOT NULL,
                period_label VARCHAR(255), score NUMERIC(6,2), result_label VARCHAR(255), explanation TEXT,
                source_document VARCHAR(500), created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        warnings.append(f"Geçmiş karne arşiv tablosu oluşturulamadı: {exc.__class__.__name__}")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        warnings.append("Geçmiş karne arşiv tablosu oluşturulamadı.")
    return _has_table(P2_ARCHIVE_TABLE), warnings


def ensure_interim_notes_table() -> tuple[bool, list[str]]:
    # performance_interim_notes Alembic'e aittir (migrations/versions/x1f3a9c5e7b2);
    # P2 uygulaması tabloyu oluşturmaz, yalnız varlığını denetler.
    warnings: list[str] = []
    if _has_table(P2_INTERIM_NOTES_TABLE):
        return True, warnings
    warnings.append("Ara dönem not tablosu bulunamadı; veritabanı migration'ı (flask db upgrade) çalıştırılmalıdır.")
    return False, warnings


def p2_status_checks() -> list[dict[str, Any]]:
    archive_cols = _columns(P2_ARCHIVE_TABLE) if _has_table(P2_ARCHIVE_TABLE) else set()
    note_cols = _columns(P2_INTERIM_NOTES_TABLE) if _has_table(P2_INTERIM_NOTES_TABLE) else set()
    p1_ready = _setting_exists("performance_period_scope_enabled") and _setting_exists("performance_scorecard_readability_enabled")
    checks = [
        ("p2_archive_setting", "Geçmiş karne arşivi ayarı hazır.", _setting_exists("performance_archive_enabled")),
        ("p2_archive_table", "Geçmiş karne/puan arşiv tablosu hazır.", _has_table(P2_ARCHIVE_TABLE)),
        ("p2_archive_columns", "Arşiv tablosunda yıl, dönem, puan, açıklama ve kaynak belge alanları var.", P2_ARCHIVE_REQUIRED_COLUMNS.issubset(archive_cols)),
        ("p2_employee_self_history", "Personel yalnızca kendi geçmiş performansını görebilir kuralı ayara bağlı.", _setting_exists("performance_archive_employee_self_view")),
        ("p2_manager_scope_history", "Yönetici geçmiş arşiv görünürlüğü kendi kapsamıyla sınırlıdır.", _setting_exists("performance_archive_manager_scope_view")),
        ("p2_interim_notes_setting", "Ara dönem notları ayarı hazır.", _setting_exists("performance_interim_notes_enabled")),
        ("p2_interim_notes_table", "Ara dönem not tablosu hazır.", _has_table(P2_INTERIM_NOTES_TABLE)),
        ("p2_interim_notes_columns", "Ara dönem notlarında tür, başlık, açıklama, görünürlük ve hatırlatma alanları var.", P2_INTERIM_REQUIRED_COLUMNS.issubset(note_cols)),
        ("p2_scoring_reminder", "Ara notlar puanlamada hatırlatma olarak gösterilebilir.", _setting_exists("performance_interim_notes_scoring_reminder")),
        ("p2_no_auto_score", "Ara notların otomatik puan üretmemesi güvenceye alınmıştır.", _setting_exists("performance_interim_notes_no_auto_score")),
        ("p2_p1_dependency", "P1 dönem kapsamı ve karne okunabilirliği korunuyor.", p1_ready),
    ]
    return [{"code": code, "title": title, "ok": bool(ok), "status": "Hazır" if ok else "Kontrol gerekli"} for code, title, ok in checks]


def p2_summary_cards() -> list[dict[str, Any]]:
    checks = p2_status_checks()
    archive_count = _scalar(f"SELECT COUNT(*) FROM {P2_ARCHIVE_TABLE}", default=0) if _has_table(P2_ARCHIVE_TABLE) else 0
    note_count = _scalar(f"SELECT COUNT(*) FROM {P2_INTERIM_NOTES_TABLE}", default=0) if _has_table(P2_INTERIM_NOTES_TABLE) else 0
    return [
        {"label": "P2 Kontrol", "value": f"{sum(1 for item in checks if item['ok'])}/{len(checks)}", "note": "Hazır olan P2 başlığı"},
        {"label": "Geçmiş Karne", "value": str(archive_count or 0), "note": "Arşiv kayıt sayısı"},
        {"label": "Ara Not", "value": str(note_count or 0), "note": "Dönem içi not sayısı"},
        {"label": "Not Türü", "value": str(len(P2_NOTE_TYPES)), "note": "Olumlu/olumsuz/başarı/gelişim/gözlem"},
    ]


def build_p2_archive_notes_context(viewer: Any | None = None) -> dict[str, Any]:
    return {"title": "P2 Arşiv ve Ara Notlar", "version": P2_ARCHIVE_NOTES_VERSION, "cards": p2_summary_cards(), "checks": p2_status_checks(), "note_types": P2_NOTE_TYPES, "archive_rows": _rows(f"SELECT year, period_label, score, result_label, registry_no FROM {P2_ARCHIVE_TABLE} ORDER BY year DESC, id DESC LIMIT 10") if _has_table(P2_ARCHIVE_TABLE) else [], "interim_rows": _rows(f"SELECT note_type, note_title, visibility_scope, remind_during_scoring, created_at FROM {P2_INTERIM_NOTES_TABLE} ORDER BY id DESC LIMIT 10") if _has_table(P2_INTERIM_NOTES_TABLE) else [], "settings": _rows("SELECT setting_key, label, value_text, description FROM module_settings WHERE module_key='performance' ORDER BY setting_key") if _has_table("module_settings") else [], "viewer": viewer}


def run_p2_archive_notes(actor_user_id: int | None = None) -> P2ArchiveNotesResult:
    warnings: list[str] = []
    seeded = 0
    try:
        seeded = ensure_p2_settings()
        _, archive_warnings = ensure_archive_table()
        _, interim_warnings = ensure_interim_notes_table()
        warnings.extend(archive_warnings)
        warnings.extend(interim_warnings)
        db.session.commit()
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        warnings.append("P2 arşiv/ara not hazırlığı tamamlanamadı.")
    checks = p2_status_checks()
    passed = sum(1 for item in checks if item["ok"])
    tables_ready = int(_has_table(P2_ARCHIVE_TABLE)) + int(_has_table(P2_INTERIM_NOTES_TABLE))
    ok = passed == len(checks)
    return P2ArchiveNotesResult(ok=ok, version=P2_ARCHIVE_NOTES_VERSION, settings_seeded=seeded, tables_ready=tables_ready, checks_passed=passed, message="P2 geçmiş karne arşivi ve ara dönem notları hazır." if ok else "P2 arşiv/ara not kontrollerinde eksik başlık var.", warnings=warnings)
