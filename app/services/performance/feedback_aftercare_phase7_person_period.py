"""BYS360 Görüşme Sonrası Notlar Faz 7.1 personel ve dönem görüşmesi servisi.

Bu servis, açık geri bildirim talebi oluşmamış durumlarda da personel + dönem seçilerek
ana görüşme kaydı açılmasını sağlar. Mevcut Faz 7 kullanım akışını bozmadan yalnızca
oluşturma alanını netleştirir.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import inspect, text

from app.extensions import db
from app.services.performance.feedback_meeting_access import duty_report_where, is_duty_manager_of

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


def _has_table(name: str) -> bool:
    try:
        return inspect(db.engine).has_table(name)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7_person_period.py | line=37")
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7_person_period.py | line=44")
        return set()


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in db.session.execute(text(sql), params or {}).mappings().all()]
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7_person_period.py | line=51")
        return []


def _row(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        value = db.session.execute(text(sql), params or {}).scalar()
        return default if value is None else value
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7_person_period.py | line=64")
        return default


def _form_value(form: Any, key: str, default: str = "") -> str:
    return (form.get(key) or default or "").strip()


def _role_value(role: str | None) -> str:
    return (role or "").strip().lower()


def can_create_person_period_meeting(role: str | None, is_admin: bool = False, is_superuser: bool = False) -> bool:
    return bool(is_admin or is_superuser or _role_value(role) in MANAGER_ROLES)


def _user_label_expr(alias: str) -> str:
    cols = _columns("users")
    parts: list[str] = []
    if {"ad", "soyad"}.issubset(cols):
        parts.append(f"NULLIF(TRIM(COALESCE({alias}.ad,'') || ' ' || COALESCE({alias}.soyad,'')), '')")
    if {"first_name", "last_name"}.issubset(cols):
        parts.append(f"NULLIF(TRIM(COALESCE({alias}.first_name,'') || ' ' || COALESCE({alias}.last_name,'')), '')")
    for col in ["full_name", "name", "username", "email", "sicil_no"]:
        if col in cols:
            parts.append(f"NULLIF(CAST({alias}.{col} AS TEXT), '')")
    parts.append(f"CAST({alias}.id AS TEXT)")
    return "COALESCE(" + ", ".join(parts) + ")"


def _period_label_expr(alias: str) -> str:
    cols = _columns("performance_periods")
    for col in ["name", "title", "period_name", "label", "code"]:
        if col in cols:
            return f"COALESCE(CAST({alias}.{col} AS TEXT), CAST({alias}.id AS TEXT))"
    return f"CAST({alias}.id AS TEXT)"


def list_person_options(current_user_id: int | None, limit: int = 1500) -> list[dict[str, Any]]:
    if not _has_table("users"):
        return []
    cols = _columns("users")
    label = _user_label_expr("u")
    sicil = "COALESCE(CAST(u.sicil_no AS TEXT), '')" if "sicil_no" in cols else "''"
    # #57: the picker offers only the user's own hierarchy reports (level 1-3), never the institution.
    duty_where, duty_params = duty_report_where("u", current_user_id)
    where: list[str] = [duty_where]
    if "is_active" in cols:
        where.append("COALESCE(u.is_active, TRUE) = TRUE")
    elif "active" in cols:
        where.append("COALESCE(u.active, TRUE) = TRUE")
    if "deleted_at" in cols:
        where.append("u.deleted_at IS NULL")
    if "role" in cols:
        where.append("COALESCE(u.role, '') NOT IN ('admin', 'super_admin', 'system_admin')")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT u.id, {label} AS label, {sicil} AS sicil_no
        FROM users u
        {where_sql}
        ORDER BY label ASC
        LIMIT :limit
    """
    return _rows(sql, {"limit": int(limit or 1500), **duty_params})


def list_period_options(limit: int = 200) -> list[dict[str, Any]]:
    if not _has_table("performance_periods"):
        return []
    cols = _columns("performance_periods")
    label = _period_label_expr("p")
    status = "COALESCE(CAST(p.status AS TEXT), '')" if "status" in cols else "''"
    date_bits: list[str] = []
    for col in ["start_date", "date_start", "period_start"]:
        if col in cols:
            date_bits.append(f"CAST(p.{col} AS TEXT)")
            break
    for col in ["end_date", "date_end", "period_end"]:
        if col in cols:
            date_bits.append(f"CAST(p.{col} AS TEXT)")
            break
    dates = " || ' / ' || ".join(date_bits) if date_bits else "''"
    order_col = "id"
    for col in ["start_date", "date_start", "created_at", "id"]:
        if col in cols:
            order_col = col
            break
    sql = f"""
        SELECT p.id, {label} AS label, {status} AS status_label, {dates} AS date_range
        FROM performance_periods p
        ORDER BY p.{order_col} DESC
        LIMIT :limit
    """
    return _rows(sql, {"limit": int(limit or 200)})


def _insert_and_get_id(table_name: str, values: dict[str, Any], lookup_where: str, lookup_params: dict[str, Any]) -> int | None:
    cols = list(values.keys())
    placeholders = [f":{col}" for col in cols]
    sql = f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
    db.session.execute(text(sql), values)
    new_id = _scalar(f"SELECT id FROM {table_name} WHERE {lookup_where} ORDER BY id DESC LIMIT 1", lookup_params)
    return int(new_id) if new_id else None


def _create_feedback_request(employee_id: int, period_id: int, manager_id: int | None, reason: str) -> int | None:
    if not _has_table("feedback_requests"):
        return None
    existing = _scalar(
        "SELECT id FROM feedback_requests WHERE employee_id = :employee_id AND period_id = :period_id ORDER BY id DESC LIMIT 1",
        {"employee_id": employee_id, "period_id": period_id},
    )
    if existing:
        return int(existing)
    cols = _columns("feedback_requests")
    values: dict[str, Any] = {}
    candidates = {
        "employee_id": employee_id,
        "period_id": period_id,
        "manager_id": manager_id,
        "level_1_manager_id": manager_id,
        "requested_by_id": manager_id,
        "created_by_id": manager_id,
        "scheduled_by_id": manager_id,
        "reason": reason or "Personel ve dönem görüşmesi kaydı oluşturuldu.",
        "note": reason or "Personel ve dönem görüşmesi kaydı oluşturuldu.",
        "status": "gorusme_planlandi",
        "request_type": "personel_donem_gorusmesi",
    }
    for key, value in candidates.items():
        if key in cols and value is not None:
            values[key] = value
    if "created_at" in cols:
        values["created_at"] = date.today().isoformat()
    if "updated_at" in cols:
        values["updated_at"] = date.today().isoformat()
    if not {"employee_id", "period_id"}.issubset(values):
        return None
    try:
        return _insert_and_get_id(
            "feedback_requests",
            values,
            "employee_id = :employee_id AND period_id = :period_id",
            {"employee_id": employee_id, "period_id": period_id},
        )
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7_person_period.py | line=207")
        # Bazı canlı şemalarda ek zorunlu alanlar olabilir. Bu durumda doğrudan meeting tablosu denenir.
        db.session.rollback()
        return None

# BYS360_FEEDBACK_AFTERCARE_PHASE7_3_ADVANCED_PREPARATION_HELPER
PREPARATION_FORM_FIELDS = {
    "purpose",
    "employee_summary",
    "strong_points",
    "development_areas",
    "sbi_examples",
    "opening_sentence",
    "sensitive_topics",
    "draft_actions",
}


def _save_initial_preparation_if_any(meeting_id: int, manager_id: int | None, form: Any) -> None:
    """Yeni kayıt sayfasındaki hazırlık taslağını görüşme detayına aktarır.

    Bu alanlar zorunlu değildir. Boş bırakılırsa görüşme kaydı normal şekilde açılır.
    Kayıt başarılı, hazırlık taslağı kaydı başarısız olursa ana görüşme kaydı bozulmaz.
    """
    try:
        has_any = any((_form_value(form, key) or "").strip() for key in PREPARATION_FORM_FIELDS)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare_phase7_person_period.py | line=235")
        has_any = False
    if not has_any:
        return
    try:
        from app.services.performance.feedback_aftercare import save_preparation
        save_preparation(meeting_id, manager_id, form)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            db.session.rollback()
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/feedback_aftercare_phase7_person_period.py")


def create_person_period_meeting(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    form: Any,
) -> int:
    if not can_create_person_period_meeting(current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        raise ValueError("Personel ve dönem seçerek görüşme kaydı oluşturma yetkiniz yok.")
    if not (_has_table("feedback_meetings") and _has_table("users")):
        raise ValueError("Görüşme kaydı oluşturmak için feedback_meetings ve users tabloları bulunmalıdır.")
    employee_id = int(_form_value(form, "employee_id") or "0")
    period_id = int(_form_value(form, "period_id") or "0")
    if employee_id <= 0:
        raise ValueError("Personel seçilmelidir.")
    if not is_duty_manager_of(current_user_id, employee_id):  # #57: duty relation, not the role alone
        raise ValueError("Bu personel için görüşme oluşturma yetkiniz yok.")
    if period_id <= 0:
        raise ValueError("Performans dönemi seçilmelidir.")
    meeting_date = _form_value(form, "meeting_date") or date.today().isoformat()
    meeting_start = _form_value(form, "meeting_start") or "09:00"
    meeting_end = _form_value(form, "meeting_end") or "10:00"
    meeting_type = _form_value(form, "meeting_type") or "donem_sonu"
    location = _form_value(form, "location") or "BYS360"
    note = _form_value(form, "note") or "Personel ve dönem görüşmesi için oluşturuldu."
    manager_id = current_user_id
    feedback_request_id = _create_feedback_request(employee_id, period_id, manager_id, note)
    # Aynı personel + dönem için daha önce meeting varsa kullanıcıyı mevcut kayda götür.
    if feedback_request_id:
        existing_meeting = _scalar(
            "SELECT id FROM feedback_meetings WHERE feedback_request_id = :rid ORDER BY id DESC LIMIT 1",
            {"rid": feedback_request_id},
        )
        if existing_meeting:
            return int(existing_meeting)
    elif "period_id" in _columns("feedback_meetings"):
        existing_meeting = _scalar(
            "SELECT id FROM feedback_meetings WHERE employee_id = :employee_id AND period_id = :period_id ORDER BY id DESC LIMIT 1",
            {"employee_id": employee_id, "period_id": period_id},
        )
        if existing_meeting:
            return int(existing_meeting)
    cols = _columns("feedback_meetings")
    values: dict[str, Any] = {}
    candidates = {
        "feedback_request_id": feedback_request_id,
        "employee_id": employee_id,
        "period_id": period_id,
        "manager_id": manager_id,
        "meeting_date": meeting_date,
        "meeting_start": meeting_start,
        "meeting_end": meeting_end,
        "location": location,
        "meeting_type": meeting_type,
        "note": note,
        "status": "planlandi",
    }
    for key, value in candidates.items():
        if key in cols and value is not None:
            values[key] = value
    if "created_at" in cols:
        values["created_at"] = date.today().isoformat()
    if "updated_at" in cols:
        values["updated_at"] = date.today().isoformat()
    if "employee_id" not in values or "manager_id" not in values:
        raise ValueError("Görüşme tablosu personel veya amir alanlarını içermiyor.")
    try:
        meeting_id = _insert_and_get_id(
            "feedback_meetings",
            values,
            ("feedback_request_id = :rid" if feedback_request_id else "employee_id = :employee_id"),
            ({"rid": feedback_request_id} if feedback_request_id else {"employee_id": employee_id}),
        )
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        raise ValueError("Görüşme kaydı oluşturulamadı.") from exc
    if feedback_request_id and _has_table("feedback_requests"):
        fr_cols = _columns("feedback_requests")
        updates: list[str] = []
        params: dict[str, Any] = {"rid": feedback_request_id}
        if "scheduled_meeting_id" in fr_cols and meeting_id:
            updates.append("scheduled_meeting_id = :meeting_id")
            params["meeting_id"] = meeting_id
        if "scheduled_by_id" in fr_cols and manager_id:
            updates.append("scheduled_by_id = :scheduled_by_id")
            params["scheduled_by_id"] = manager_id
        if "status" in fr_cols:
            updates.append("status = :status")
            params["status"] = "gorusme_planlandi"
        if updates:
            db.session.execute(text(f"UPDATE feedback_requests SET {', '.join(updates)} WHERE id = :rid"), params)
    db.session.commit()
    if not meeting_id:
        meeting_id = _scalar("SELECT MAX(id) FROM feedback_meetings", default=0)
    _save_initial_preparation_if_any(int(meeting_id), manager_id, form)
    return int(meeting_id)


def build_meeting_period_map() -> dict[Any, str]:
    if not (_has_table("feedback_meetings") and _has_table("performance_periods")):
        return {}
    period_label = _period_label_expr("pp")
    if _has_table("feedback_requests"):
        sql = f"""
            SELECT fm.id AS meeting_id, {period_label} AS period_label
            FROM feedback_meetings fm
            LEFT JOIN feedback_requests fr ON fr.id = fm.feedback_request_id
            LEFT JOIN performance_periods pp ON pp.id = COALESCE(fr.period_id, NULL)
        """
        if "period_id" in _columns("feedback_meetings"):
            sql = f"""
                SELECT fm.id AS meeting_id, {period_label} AS period_label
                FROM feedback_meetings fm
                LEFT JOIN feedback_requests fr ON fr.id = fm.feedback_request_id
                LEFT JOIN performance_periods pp ON pp.id = COALESCE(fm.period_id, fr.period_id)
            """
    elif "period_id" in _columns("feedback_meetings"):
        sql = f"""
            SELECT fm.id AS meeting_id, {period_label} AS period_label
            FROM feedback_meetings fm
            LEFT JOIN performance_periods pp ON pp.id = fm.period_id
        """
    else:
        return {}
    rows = _rows(sql)
    return {row.get("meeting_id"): row.get("period_label") or "-" for row in rows if row.get("meeting_id") is not None}


def build_phase7_1_context(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
) -> dict[str, Any]:
    return {
        "person_options": list_person_options(current_user_id) if can_create_person_period_meeting(current_user_role, is_admin=is_admin, is_superuser=is_superuser) else [],
        "period_options": list_period_options(),
        "can_create_person_period_meeting": can_create_person_period_meeting(current_user_role, is_admin=is_admin, is_superuser=is_superuser),
        "meeting_period_map": build_meeting_period_map(),
        "meeting_type_options": MEETING_TYPE_OPTIONS,
        "active_create_tab": "person_period",
        "phase7_1_person_period_ready": _has_table("feedback_meetings") and _has_table("users") and _has_table("performance_periods"),
    }
