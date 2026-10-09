"""BYS360 Görüşme Sonrası Notlar Faz 7 kullanım netleştirme servisi.

Bu servis ana feedback_aftercare servisini bozmadan ek bağlam üretir ve açık geri
bildirim talebi varsa görüşme kaydı oluşturur. Amaç ekranın kullanımını netleştirmektir.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import inspect, text

from app.extensions import db

logger = logging.getLogger(__name__)

GLOBAL_ROLES = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan",
    "baskan_yardimcisi", "grup_baskani", "mali_musavir", "performans_yetkilisi",
}
MANAGER_ROLES = GLOBAL_ROLES | {"koordinator", "birim_sorumlusu", "yonetici", "manager"}

MEETING_TYPE_OPTIONS = [
    {"value": "donem_sonu", "label": "Dönem Sonu Görüşmesi"},
    {"value": "dusuk_performans", "label": "Düşük Performans Görüşmesi"},
    {"value": "gelisim", "label": "Gelişim Görüşmesi"},
    {"value": "takip", "label": "Takip Görüşmesi"},
    {"value": "yuz_yuze", "label": "Yüz Yüze Görüşme"},
]

USAGE_STEPS = [
    {
        "no": "01",
        "title": "Görüşme kaydını seç",
        "desc": "Sol listeden personel ve dönem görüşmesini aç. Yeni kayıt gerekiyorsa üstteki oluşturma alanını kullan.",
        "target": "liste",
    },
    {
        "no": "02",
        "title": "Görüşme notunu yaz",
        "desc": "Asıl not Görüşme Notları bölümüne yazılır: özet, personelin görüşü, amir gözlemi ve son söz aynı kayıttadır.",
        "target": "notlar",
    },
    {
        "no": "03",
        "title": "Eylem planını bağla",
        "desc": "Kararlaştırılan yapılacaklar aynı görüşmenin altındaki Eylem Planları bölümüne eklenir.",
        "target": "eylem",
    },
    {
        "no": "04",
        "title": "Takibi güncelle",
        "desc": "30 günlük kontrol, geciken aksiyon ve sonuç notu Eylem Planı Takibi ekranından da izlenir.",
        "target": "takip",
    },
]

DETAIL_MAP = [
    {"title": "Görüşme Bilgisi", "text": "Personel, dönem, tarih, görüşmeyi yapan amir ve görüşme türü burada görülür."},
    {"title": "Görüşme Notları", "text": "Görüşme özeti, personelin kendi değerlendirmesi, amir gözlemi, güçlü yönler ve gelişim alanları burada tutulur."},
    {"title": "Eylem Planları", "text": "Görüşmede kararlaştırılan aksiyonlar aynı kaydın altında satır satır eklenir."},
    {"title": "Takip Geçmişi", "text": "Hedef tarih, durum, takip notu ve sonuç özeti daha sonra buradan güncellenir."},
]


def _has_table(name: str) -> bool:
    try:
        return inspect(db.engine).has_table(name)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7.py | line=70")
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7.py | line=77")
        return set()


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        result = db.session.execute(text(sql), params or {}).mappings().all()
        return [dict(row) for row in result]
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7.py | line=85")
        return []


def _row(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        value = db.session.execute(text(sql), params or {}).scalar()
        return default if value is None else value
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7.py | line=98")
        return default


def _form_value(form: Any, key: str, default: str = "") -> str:
    return (form.get(key) or default or "").strip()


def _role_value(role: str | None) -> str:
    return (role or "").strip().lower()


def can_manage_aftercare(role: str | None, is_admin: bool = False, is_superuser: bool = False) -> bool:
    return bool(is_admin or is_superuser or _role_value(role) in MANAGER_ROLES)


def _user_label_expr(alias: str) -> str:
    cols = _columns("users")
    # users has no username column in any model or migration; reference it only if present.
    username = f"{alias}.username, " if "username" in cols else ""
    if {"first_name", "last_name"}.issubset(cols):
        return f"COALESCE(NULLIF(TRIM(CONCAT({alias}.first_name, ' ', {alias}.last_name)), ''), {username}{alias}.email, CAST({alias}.id AS TEXT))"
    if "full_name" in cols:
        return f"COALESCE({alias}.full_name, {username}{alias}.email, CAST({alias}.id AS TEXT))"
    if "name" in cols:
        return f"COALESCE({alias}.name, {username}{alias}.email, CAST({alias}.id AS TEXT))"
    if "username" in cols:
        return f"COALESCE({alias}.username, {alias}.email, CAST({alias}.id AS TEXT))"
    return f"CAST({alias}.id AS TEXT)"


def _period_label_expr(alias: str) -> str:
    cols = _columns("performance_periods")
    for col in ["name", "title", "period_name", "label"]:
        if col in cols:
            return f"COALESCE({alias}.{col}, CAST({alias}.id AS TEXT))"
    return f"CAST({alias}.id AS TEXT)"


def list_open_feedback_requests(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not (_has_table("feedback_requests") and _has_table("feedback_meetings") and _has_table("users")):
        return []
    user_label = _user_label_expr("u")
    period_join = ""
    period_label = "CAST(fr.period_id AS TEXT)"
    if _has_table("performance_periods"):
        period_join = "LEFT JOIN performance_periods pp ON pp.id = fr.period_id"
        period_label = _period_label_expr("pp")
    where = ["fm.id IS NULL"]
    params: dict[str, Any] = {"limit": int(limit or 100)}
    if not can_manage_aftercare(current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        where.append("fr.employee_id = :current_user_id")
        params["current_user_id"] = current_user_id or 0
    sql = f"""
        SELECT
            fr.id,
            fr.employee_id,
            fr.period_id,
            fr.reason,
            fr.status,
            {user_label} AS employee_label,
            {period_label} AS period_label
        FROM feedback_requests fr
        LEFT JOIN users u ON u.id = fr.employee_id
        {period_join}
        LEFT JOIN feedback_meetings fm ON fm.feedback_request_id = fr.id
        WHERE {' AND '.join(where)}
        ORDER BY fr.id DESC
        LIMIT :limit
    """
    return _rows(sql, params)


def _feedback_request_context(feedback_request_id: int) -> dict[str, Any] | None:
    if not _has_table("feedback_requests"):
        return None
    return _row(
        """
        SELECT id, employee_id, period_id, level_1_manager_id, level_2_manager_id, level_3_manager_id
        FROM feedback_requests
        WHERE id = :id
        """,
        {"id": feedback_request_id},
    )


def create_meeting_from_feedback_request(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    form: Any,
) -> int:
    if not can_manage_aftercare(current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        raise ValueError("Görüşme kaydı oluşturma yetkiniz yok.")
    if not _has_table("feedback_meetings"):
        raise ValueError("Görüşme tablosu bulunamadı. Önce geri bildirim görüşmeleri altyapısı kurulmalıdır.")
    feedback_request_id = int(_form_value(form, "feedback_request_id") or "0")
    if feedback_request_id <= 0:
        raise ValueError("Görüşme kaydı için açık geri bildirim talebi seçilmelidir.")
    existing_id = _scalar("SELECT id FROM feedback_meetings WHERE feedback_request_id = :rid", {"rid": feedback_request_id})
    if existing_id:
        return int(existing_id)
    request_row = _feedback_request_context(feedback_request_id)
    if not request_row:
        raise ValueError("Seçilen geri bildirim talebi bulunamadı.")
    meeting_date = _form_value(form, "meeting_date") or date.today().isoformat()
    meeting_start = _form_value(form, "meeting_start") or "09:00"
    meeting_end = _form_value(form, "meeting_end") or "10:00"
    meeting_type = _form_value(form, "meeting_type") or "donem_sonu"
    location = _form_value(form, "location") or "BYS360"
    note = _form_value(form, "note") or "Görüşme sonrası not ve eylem planı kaydı için oluşturuldu."
    manager_id = current_user_id or request_row.get("level_1_manager_id") or request_row.get("level_2_manager_id") or request_row.get("level_3_manager_id")
    if not manager_id:
        raise ValueError("Görüşmeyi yapacak amir belirlenemedi.")
    cols = _columns("feedback_meetings")
    values: dict[str, Any] = {}
    candidate_values = {
        "feedback_request_id": feedback_request_id,
        "employee_id": request_row.get("employee_id"),
        "manager_id": manager_id,
        "meeting_date": meeting_date,
        "meeting_start": meeting_start,
        "meeting_end": meeting_end,
        "location": location,
        "meeting_type": meeting_type,
        "note": note,
        "status": "planlandi",
    }
    for key, value in candidate_values.items():
        if key in cols:
            values[key] = value
    if "created_at" in cols:
        # created_at için CURRENT_TIMESTAMP kullanılacak.
        pass
    if not {"feedback_request_id", "employee_id", "manager_id", "meeting_date", "meeting_start", "meeting_end"}.issubset(values):
        raise ValueError("Görüşme tablosu beklenen alanları içermiyor.")
    columns = list(values.keys())
    placeholders = [f":{col}" for col in columns]
    if "created_at" in cols:
        columns.append("created_at")
        placeholders.append("CURRENT_TIMESTAMP")
    sql = f"INSERT INTO feedback_meetings ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
    db.session.execute(text(sql), values)
    meeting_id = _scalar("SELECT id FROM feedback_meetings WHERE feedback_request_id = :rid", {"rid": feedback_request_id})
    if _has_table("feedback_requests"):
        fr_cols = _columns("feedback_requests")
        updates = []
        params: dict[str, Any] = {"rid": feedback_request_id}
        if "scheduled_meeting_id" in fr_cols and meeting_id:
            updates.append("scheduled_meeting_id = :meeting_id")
            params["meeting_id"] = int(meeting_id)
        if "scheduled_by_id" in fr_cols and current_user_id:
            updates.append("scheduled_by_id = :scheduled_by_id")
            params["scheduled_by_id"] = current_user_id
        if "status" in fr_cols:
            updates.append("status = :status")
            params["status"] = "gorusme_planlandi"
        if updates:
            db.session.execute(text(f"UPDATE feedback_requests SET {', '.join(updates)} WHERE id = :rid"), params)
    db.session.commit()
    return int(meeting_id) if meeting_id else int(_scalar("SELECT MAX(id) FROM feedback_meetings", default=0))


def build_phase7_context(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
) -> dict[str, Any]:
    open_requests = list_open_feedback_requests(
        current_user_id=current_user_id,
        current_user_role=current_user_role,
        is_admin=is_admin,
        is_superuser=is_superuser,
    )
    return {
        "phase7_usage_steps": USAGE_STEPS,
        "phase7_detail_map": DETAIL_MAP,
        "feedback_request_options": open_requests,
        "meeting_type_options": MEETING_TYPE_OPTIONS,
        "can_create_aftercare_meeting": can_manage_aftercare(current_user_role, is_admin=is_admin, is_superuser=is_superuser),
        "phase7_schema_ready": _has_table("feedback_meetings") and _has_table("feedback_requests"),
    }
