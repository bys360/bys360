"""BYS360 Performans Görüşme Sonrası Notlar ve Eylem Planı servisi.

Bu servis mevcut feedback_meetings tablosunu bozmadan üç tamamlayıcı kayıt alanı ekler:
- görüşme hazırlığı,
- görüşme sonrası notlar,
- eylem planı ve takip.

Tüm işlemler idempotent DDL ve güvenli raw SQL ile yapılır; model import zincirine bağımlı değildir.
"""
from __future__ import annotations

import contextlib
import logging
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.services import runtime_schema

logger = logging.getLogger(__name__)

GLOBAL_ROLES = {
    "admin",
    "super_admin",
    "system_admin",
    "sistem_yoneticisi",
    "baskan",
    "baskan_yardimcisi",
}
MANAGER_ROLES = GLOBAL_ROLES | {
    "grup_baskani",
    "mali_musavir",
    "koordinator",
    "birim_sorumlusu",
    "yonetici",
    "manager",
}

STATUS_LABELS = {
    "planlandi": "Planlandı",
    "tamamlandi": "Tamamlandı",
    "ertelendi": "Ertelendi",
    "iptal_edildi": "İptal Edildi",
}

ACTION_STATUS_LABELS = {
    "acik": "Açık",
    "takipte": "Takipte",
    "tamamlandi": "Tamamlandı",
    "gecikti": "Gecikti",
    "iptal": "İptal Edildi",
}

RESPONSIBLE_LABELS = {
    "personel": "Personel",
    "amir": "Amir",
    "ortak": "Ortak",
}

STEP_CARDS = [
    {"no": "01", "title": "Hazırlık", "desc": "Görüşme amacı, somut örnekler ve açılış cümlesi netleşir."},
    {"no": "02", "title": "Görüşme", "desc": "Önce çalışan dinlenir, sonra yönetici gözlemi paylaşılır."},
    {"no": "03", "title": "Sonrası", "desc": "Özet, güçlü yönler, gelişim alanları ve son söz kayda alınır."},
    {"no": "04", "title": "Takip", "desc": "SMART eylem planı ve kontrol tarihi görünür kalır."},
]

OPENING_SENTENCES = [
    "Bugün geçen dönemi birlikte konuşacağız. Önce senin gözünden dinlemek, sonra kendi gözlemlerimi paylaşmak istiyorum.",
    "Bu görüşmenin amacı seni yargılamak değil; nerede olduğumuzu ve bir sonraki adımı birlikte netleştirmek.",
    "Önce güçlü taraflarını ve bu dönem seni zorlayan noktaları senin cümlelerinle duymak istiyorum.",
    "Konuşmanın sonunda birkaç somut adım üzerinde anlaşalım; böylece görüşme havada kalmasın.",
]


def _dialect() -> str:
    try:
        return (db.engine.dialect.name or "").lower()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare.py | line=78")
        return ""


def _pk_sql() -> str:
    return "INTEGER PRIMARY KEY AUTOINCREMENT" if _dialect() == "sqlite" else "SERIAL PRIMARY KEY"


def _bool_default(value: bool = False) -> str:
    if _dialect() == "sqlite":
        return "1" if value else "0"
    return "TRUE" if value else "FALSE"


def _has_table(name: str) -> bool:
    try:
        return inspect(db.engine).has_table(name)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare.py | line=95")
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare.py | line=102")
        return set()

def _ensure_sqlite_database_parent_exists() -> None:
    """SQLite dosya yolu parent klas?r? yoksa test/dev ortam?nda olu?turur."""
    try:
        from pathlib import Path as _Path

        engine = db.engine
        url = getattr(engine, "url", None)
        drivername = str(getattr(url, "drivername", "") or "")
        database = getattr(url, "database", None)

        if not drivername.startswith("sqlite"):
            return
        if not database or database == ":memory:":
            return

        db_path = _Path(str(database))
        if not db_path.is_absolute():
            db_path = _Path.cwd() / db_path

        db_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return


def _execute(sql: str, params: dict[str, Any] | None = None) -> None:
    # BYS360_A5_P2D7B_EXECUTE_SQLALCHEMY_GUARD
    try:
        db.session.execute(text(sql), params or {})
    except SQLAlchemyError:
        with contextlib.suppress(SQLAlchemyError):
            db.session.rollback()
        return None


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        result = db.session.execute(text(sql), params or {}).mappings().all()
        return [_stringify_dict(dict(row)) for row in result]
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare.py | line=114")
        return []


def _row(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        value = db.session.execute(text(sql), params or {}).scalar()
        return default if value is None else value
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_aftercare.py | line=127")
        return default


def _stringify(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return value


def _stringify_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _stringify(value) for key, value in row.items()}


def _coalesce_user_label(alias: str) -> str:
    cols = _columns("users")
    parts: list[str] = []
    if {"ad", "soyad"}.issubset(cols):
        parts.append(f"NULLIF(TRIM(COALESCE({alias}.ad,'') || ' ' || COALESCE({alias}.soyad,'')), '')")
    if "full_name" in cols:
        parts.append(f"NULLIF({alias}.full_name, '')")
    if "name" in cols:
        parts.append(f"NULLIF({alias}.name, '')")
    if "email" in cols:
        parts.append(f"NULLIF({alias}.email, '')")
    if "sicil_no" in cols:
        parts.append(f"NULLIF({alias}.sicil_no, '')")
    parts.append(f"CAST({alias}.id AS TEXT)")
    return "COALESCE(" + ", ".join(parts) + ")"


def _user_sicil_expr(alias: str) -> str:
    return f"COALESCE({alias}.sicil_no, '')" if "sicil_no" in _columns("users") else "''"


def provision_feedback_aftercare_schema() -> dict[str, Any]:
    """Create the after-meeting tables (explicit maintenance only: flask runtime-schema provision)."""
    pk = _pk_sql()
    false_default = _bool_default(False)
    ddl = [
        f"""
        CREATE TABLE IF NOT EXISTS feedback_meeting_preparations (
            id {pk},
            meeting_id INTEGER NOT NULL UNIQUE REFERENCES feedback_meetings(id) ON DELETE CASCADE,
            manager_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            purpose TEXT NULL,
            employee_summary TEXT NULL,
            strong_points TEXT NULL,
            development_areas TEXT NULL,
            sbi_examples TEXT NULL,
            opening_sentence TEXT NULL,
            sensitive_topics TEXT NULL,
            draft_actions TEXT NULL,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS feedback_meeting_after_notes (
            id {pk},
            meeting_id INTEGER NOT NULL UNIQUE REFERENCES feedback_meetings(id) ON DELETE CASCADE,
            manager_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            meeting_summary TEXT NULL,
            employee_self_assessment TEXT NULL,
            manager_observation TEXT NULL,
            strong_points TEXT NULL,
            development_areas TEXT NULL,
            agreed_actions_summary TEXT NULL,
            employee_final_words TEXT NULL,
            summary_mail_sent BOOLEAN NOT NULL DEFAULT {false_default},
            closure_status VARCHAR(40) NOT NULL DEFAULT 'taslak',
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS feedback_meeting_action_plans (
            id {pk},
            meeting_id INTEGER NOT NULL REFERENCES feedback_meetings(id) ON DELETE CASCADE,
            employee_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            manager_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            title VARCHAR(255) NOT NULL,
            smart_description TEXT NULL,
            responsible_role VARCHAR(40) NOT NULL DEFAULT 'ortak',
            target_date DATE NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'acik',
            follow_up_note TEXT NULL,
            result_summary TEXT NULL,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_feedback_aftercare_actions_meeting ON feedback_meeting_action_plans(meeting_id)",
        "CREATE INDEX IF NOT EXISTS ix_feedback_aftercare_actions_target ON feedback_meeting_action_plans(target_date)",
        "CREATE INDEX IF NOT EXISTS ix_feedback_aftercare_actions_status ON feedback_meeting_action_plans(status)",
    ]
    for statement in ddl:
        _execute(statement)
    db.session.commit()
    return {"ok": True, "tables": list(FEEDBACK_AFTERCARE_TABLES)}


FEEDBACK_AFTERCARE_TABLES = ("feedback_meeting_preparations", "feedback_meeting_after_notes", "feedback_meeting_action_plans")
FEEDBACK_AFTERCARE_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.feedback_aftercare",
    tables=FEEDBACK_AFTERCARE_TABLES,
    indexes=(
        ("feedback_meeting_action_plans", "ix_feedback_aftercare_actions_meeting"),
        ("feedback_meeting_action_plans", "ix_feedback_aftercare_actions_target"),
        ("feedback_meeting_action_plans", "ix_feedback_aftercare_actions_status"),
    ),
    provision=provision_feedback_aftercare_schema,
))


def ensure_feedback_aftercare_schema() -> dict[str, Any]:
    """Verify the after-meeting tables exist; never creates them (see app.services.runtime_schema)."""
    runtime_schema.require(FEEDBACK_AFTERCARE_SCHEMA)
    return {"ok": True, "tables": list(FEEDBACK_AFTERCARE_TABLES)}


def _has_existing_core_tables() -> bool:
    return _has_table("feedback_meetings") and _has_table("users")


def _is_global_user(role: str | None, is_admin: bool = False, is_superuser: bool = False) -> bool:
    role_value = (role or "").strip().lower()
    return bool(is_admin or is_superuser or role_value in GLOBAL_ROLES)


def _meeting_visibility_where(role: str | None, user_id: int | None, is_admin: bool = False, is_superuser: bool = False) -> tuple[str, dict[str, Any]]:
    if _is_global_user(role, is_admin=is_admin, is_superuser=is_superuser):
        return "", {}
    return "WHERE (m.employee_id = :current_user_id OR m.manager_id = :current_user_id)", {"current_user_id": user_id or 0}


def _meeting_select_sql(where_sql: str = "") -> str:
    employee_label = _coalesce_user_label("e")
    manager_label = _coalesce_user_label("g")
    employee_sicil = _user_sicil_expr("e")
    return f"""
        SELECT
            m.id,
            m.feedback_request_id,
            m.employee_id,
            m.manager_id,
            m.meeting_date,
            m.meeting_start,
            m.meeting_end,
            m.location,
            m.meeting_type,
            m.note,
            m.status,
            m.created_at,
            {employee_label} AS employee_label,
            {employee_sicil} AS employee_sicil,
            {manager_label} AS manager_label,
            CASE WHEN p.id IS NULL THEN 0 ELSE 1 END AS has_preparation,
            CASE WHEN n.id IS NULL THEN 0 ELSE 1 END AS has_after_note,
            COALESCE(a.action_count, 0) AS action_count,
            COALESCE(a.open_action_count, 0) AS open_action_count
        FROM feedback_meetings m
        LEFT JOIN users e ON e.id = m.employee_id
        LEFT JOIN users g ON g.id = m.manager_id
        LEFT JOIN feedback_meeting_preparations p ON p.meeting_id = m.id
        LEFT JOIN feedback_meeting_after_notes n ON n.meeting_id = m.id
        LEFT JOIN (
            SELECT
                meeting_id,
                COUNT(*) AS action_count,
                SUM(CASE WHEN status IN ('acik', 'takipte', 'gecikti') THEN 1 ELSE 0 END) AS open_action_count
            FROM feedback_meeting_action_plans
            GROUP BY meeting_id
        ) a ON a.meeting_id = m.id
        {where_sql}
    """


def list_meetings_for_aftercare(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    query: str = "",
    status: str = "all",
    limit: int = 80,
) -> list[dict[str, Any]]:
    ensure_feedback_aftercare_schema()
    if not _has_existing_core_tables():
        return []
    where_sql, params = _meeting_visibility_where(current_user_role, current_user_id, is_admin=is_admin, is_superuser=is_superuser)
    conditions: list[str] = []
    if query:
        conditions.append("(LOWER(employee_label) LIKE :q OR LOWER(manager_label) LIKE :q OR LOWER(COALESCE(location,'')) LIKE :q OR LOWER(COALESCE(note,'')) LIKE :q)")
        params["q"] = f"%{query.lower()}%"
    if status and status != "all":
        conditions.append("status = :status")
        params["status"] = status
    sql = _meeting_select_sql(where_sql)
    if conditions:
        if where_sql.strip():
            sql += " AND " + " AND ".join(conditions)
        else:
            sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY m.meeting_date DESC, m.meeting_start DESC LIMIT :limit"
    params["limit"] = int(limit or 80)
    rows = _rows(sql, params)
    for row in rows:
        row["status_label"] = STATUS_LABELS.get(row.get("status") or "", row.get("status") or "-")
        row["is_prepared"] = bool(int(row.get("has_preparation") or 0))
        row["is_closed"] = bool(int(row.get("has_after_note") or 0))
    return rows


def get_meeting_aftercare_detail(
    meeting_id: int,
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
) -> dict[str, Any]:
    ensure_feedback_aftercare_schema()
    if not _has_existing_core_tables():
        return {"meeting": None, "preparation": {}, "after_note": {}, "actions": [], "can_edit": False}
    where_sql, params = _meeting_visibility_where(current_user_role, current_user_id, is_admin=is_admin, is_superuser=is_superuser)
    sql = _meeting_select_sql(where_sql)
    if where_sql.strip():
        sql += " AND m.id = :meeting_id"
    else:
        sql += " WHERE m.id = :meeting_id"
    params["meeting_id"] = meeting_id
    meeting = _row(sql, params)
    if not meeting:
        return {"meeting": None, "preparation": {}, "after_note": {}, "actions": [], "can_edit": False}
    meeting["status_label"] = STATUS_LABELS.get(meeting.get("status") or "", meeting.get("status") or "-")
    preparation = _row("SELECT * FROM feedback_meeting_preparations WHERE meeting_id = :meeting_id", {"meeting_id": meeting_id}) or {}
    after_note = _row("SELECT * FROM feedback_meeting_after_notes WHERE meeting_id = :meeting_id", {"meeting_id": meeting_id}) or {}
    actions = _rows(
        """
        SELECT *
        FROM feedback_meeting_action_plans
        WHERE meeting_id = :meeting_id
        ORDER BY
            CASE WHEN target_date IS NULL THEN 1 ELSE 0 END,
            target_date ASC,
            id DESC
        """,
        {"meeting_id": meeting_id},
    )
    for action in actions:
        action["status_label"] = ACTION_STATUS_LABELS.get(action.get("status") or "", action.get("status") or "-")
        action["responsible_label"] = RESPONSIBLE_LABELS.get(action.get("responsible_role") or "", action.get("responsible_role") or "-")
    role = (current_user_role or "").lower()
    can_edit = bool(_is_global_user(role, is_admin=is_admin, is_superuser=is_superuser) or current_user_id in {meeting.get("manager_id"), meeting.get("employee_id")})
    mail_draft = build_summary_mail_draft(meeting, after_note, actions)
    return {
        "meeting": meeting,
        "preparation": preparation,
        "after_note": after_note,
        "actions": actions,
        "can_edit": can_edit,
        "mail_draft": mail_draft,
        "readiness": build_readiness(preparation, after_note, actions),
    }


def build_aftercare_dashboard(meetings: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(meetings)
    prepared = sum(1 for item in meetings if item.get("is_prepared"))
    closed = sum(1 for item in meetings if item.get("is_closed"))
    open_actions = sum(int(item.get("open_action_count") or 0) for item in meetings)
    return {
        "total_meetings": total,
        "prepared_meetings": prepared,
        "closed_meetings": closed,
        "open_actions": open_actions,
        "preparation_rate": round((prepared / total) * 100) if total else 0,
        "closure_rate": round((closed / total) * 100) if total else 0,
    }


def build_readiness(preparation: dict[str, Any], after_note: dict[str, Any], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = [
        {"label": "Görüşme amacı yazıldı", "ok": bool((preparation or {}).get("purpose"))},
        {"label": "Somut güçlü yön / gelişim alanı hazır", "ok": bool((preparation or {}).get("strong_points") or (preparation or {}).get("development_areas"))},
        {"label": "Görüşme özeti kaydedildi", "ok": bool((after_note or {}).get("meeting_summary"))},
        {"label": "Eylem planı oluşturuldu", "ok": bool(actions)},
        {"label": "Takip tarihi var", "ok": any(action.get("target_date") for action in actions)},
    ]
    return checks


def build_summary_mail_draft(meeting: dict[str, Any], after_note: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    employee = meeting.get("employee_label") or "Personel"
    date_text = meeting.get("meeting_date") or ""
    lines = [
        f"Sayın {employee},",
        "",
        f"{date_text} tarihli performans geri bildirim görüşmemizin kısa özeti aşağıdadır.",
        "",
        "Görüşme Özeti:",
        (after_note or {}).get("meeting_summary") or "-",
        "",
        "Güçlü Yönler:",
        (after_note or {}).get("strong_points") or "-",
        "",
        "Gelişim Alanları:",
        (after_note or {}).get("development_areas") or "-",
        "",
        "Kararlaştırılan Aksiyonlar:",
    ]
    if actions:
        for action in actions:
            target = f" | Hedef: {action.get('target_date')}" if action.get("target_date") else ""
            lines.append(f"- {action.get('title') or '-'} ({action.get('responsible_label') or '-'}){target}")
    else:
        lines.append("-")
    lines.extend(["", "Bu kayıt, görüşme sonrası takip amacıyla BYS360 üzerinde tutulmaktadır.", "", "İyi çalışmalar."])
    return "\n".join(lines)


def _form_value(form: Any, key: str, default: str = "") -> str:
    return " ".join((form.get(key) or default or "").replace("\r\n", "\n").split()) if key.endswith("_short") else (form.get(key) or default or "").strip()


def save_preparation(meeting_id: int, manager_id: int | None, form: Any) -> None:
    ensure_feedback_aftercare_schema()
    params = {
        "meeting_id": meeting_id,
        "manager_id": manager_id,
        "purpose": _form_value(form, "purpose"),
        "employee_summary": _form_value(form, "employee_summary"),
        "strong_points": _form_value(form, "strong_points"),
        "development_areas": _form_value(form, "development_areas"),
        "sbi_examples": _form_value(form, "sbi_examples"),
        "opening_sentence": _form_value(form, "opening_sentence"),
        "sensitive_topics": _form_value(form, "sensitive_topics"),
        "draft_actions": _form_value(form, "draft_actions"),
    }
    _execute(
        """
        INSERT INTO feedback_meeting_preparations
            (meeting_id, manager_id, purpose, employee_summary, strong_points, development_areas, sbi_examples, opening_sentence, sensitive_topics, draft_actions, created_at, updated_at)
        VALUES
            (:meeting_id, :manager_id, :purpose, :employee_summary, :strong_points, :development_areas, :sbi_examples, :opening_sentence, :sensitive_topics, :draft_actions, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (meeting_id) DO UPDATE SET
            manager_id = excluded.manager_id,
            purpose = excluded.purpose,
            employee_summary = excluded.employee_summary,
            strong_points = excluded.strong_points,
            development_areas = excluded.development_areas,
            sbi_examples = excluded.sbi_examples,
            opening_sentence = excluded.opening_sentence,
            sensitive_topics = excluded.sensitive_topics,
            draft_actions = excluded.draft_actions,
            updated_at = CURRENT_TIMESTAMP
        """,
        params,
    )
    db.session.commit()


def save_after_note(meeting_id: int, manager_id: int | None, form: Any) -> None:
    ensure_feedback_aftercare_schema()
    mail_sent = str(form.get("summary_mail_sent") or "").lower() in {"1", "true", "on", "yes", "evet"}
    params = {
        "meeting_id": meeting_id,
        "manager_id": manager_id,
        "meeting_summary": _form_value(form, "meeting_summary"),
        "employee_self_assessment": _form_value(form, "employee_self_assessment"),
        "manager_observation": _form_value(form, "manager_observation"),
        "strong_points": _form_value(form, "strong_points"),
        "development_areas": _form_value(form, "development_areas"),
        "agreed_actions_summary": _form_value(form, "agreed_actions_summary"),
        "employee_final_words": _form_value(form, "employee_final_words"),
        "summary_mail_sent": mail_sent,
        "closure_status": _form_value(form, "closure_status") or "taslak",
    }
    _execute(
        """
        INSERT INTO feedback_meeting_after_notes
            (meeting_id, manager_id, meeting_summary, employee_self_assessment, manager_observation, strong_points, development_areas, agreed_actions_summary, employee_final_words, summary_mail_sent, closure_status, created_at, updated_at)
        VALUES
            (:meeting_id, :manager_id, :meeting_summary, :employee_self_assessment, :manager_observation, :strong_points, :development_areas, :agreed_actions_summary, :employee_final_words, :summary_mail_sent, :closure_status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (meeting_id) DO UPDATE SET
            manager_id = excluded.manager_id,
            meeting_summary = excluded.meeting_summary,
            employee_self_assessment = excluded.employee_self_assessment,
            manager_observation = excluded.manager_observation,
            strong_points = excluded.strong_points,
            development_areas = excluded.development_areas,
            agreed_actions_summary = excluded.agreed_actions_summary,
            employee_final_words = excluded.employee_final_words,
            summary_mail_sent = excluded.summary_mail_sent,
            closure_status = excluded.closure_status,
            updated_at = CURRENT_TIMESTAMP
        """,
        params,
    )
    db.session.commit()


def add_action_plan(meeting_id: int, employee_id: int | None, manager_id: int | None, form: Any) -> None:
    ensure_feedback_aftercare_schema()
    title = _form_value(form, "title")
    if not title:
        raise ValueError("Eylem başlığı zorunludur.")
    target_date = _form_value(form, "target_date") or None
    params = {
        "meeting_id": meeting_id,
        "employee_id": employee_id,
        "manager_id": manager_id,
        "title": title,
        "smart_description": _form_value(form, "smart_description"),
        "responsible_role": _form_value(form, "responsible_role") or "ortak",
        "target_date": target_date,
        "status": _form_value(form, "status") or "acik",
        "follow_up_note": _form_value(form, "follow_up_note"),
        "result_summary": _form_value(form, "result_summary"),
    }
    _execute(
        """
        INSERT INTO feedback_meeting_action_plans
            (meeting_id, employee_id, manager_id, title, smart_description, responsible_role, target_date, status, follow_up_note, result_summary, created_at, updated_at)
        VALUES
            (:meeting_id, :employee_id, :manager_id, :title, :smart_description, :responsible_role, :target_date, :status, :follow_up_note, :result_summary, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        params,
    )
    db.session.commit()


def action_plan_meeting_id(action_id: int) -> int | None:
    """Return the meeting of an action plan without changing it, so callers can authorize first."""
    ensure_feedback_aftercare_schema()
    meeting_id = _scalar("SELECT meeting_id FROM feedback_meeting_action_plans WHERE id = :action_id", {"action_id": action_id})
    return int(meeting_id) if meeting_id else None


def update_action_plan(action_id: int, form: Any) -> int | None:
    ensure_feedback_aftercare_schema()
    status = _form_value(form, "status") or "takipte"
    follow_up_note = _form_value(form, "follow_up_note")
    result_summary = _form_value(form, "result_summary")
    _execute(
        """
        UPDATE feedback_meeting_action_plans
        SET status = :status,
            follow_up_note = :follow_up_note,
            result_summary = :result_summary,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :action_id
        """,
        {"action_id": action_id, "status": status, "follow_up_note": follow_up_note, "result_summary": result_summary},
    )
    meeting_id = _scalar("SELECT meeting_id FROM feedback_meeting_action_plans WHERE id = :action_id", {"action_id": action_id})
    db.session.commit()
    return int(meeting_id) if meeting_id else None


def build_full_context(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    selected_meeting_id: int | None = None,
    query: str = "",
    status: str = "all",
) -> dict[str, Any]:
    ensure_feedback_aftercare_schema()
    meetings = list_meetings_for_aftercare(
        current_user_id=current_user_id,
        current_user_role=current_user_role,
        is_admin=is_admin,
        is_superuser=is_superuser,
        query=query,
        status=status,
    )
    selected_id = selected_meeting_id or (meetings[0]["id"] if meetings else None)
    detail = get_meeting_aftercare_detail(
        int(selected_id),
        current_user_id=current_user_id,
        current_user_role=current_user_role,
        is_admin=is_admin,
        is_superuser=is_superuser,
    ) if selected_id else {"meeting": None, "preparation": {}, "after_note": {}, "actions": [], "can_edit": False, "mail_draft": "", "readiness": []}
    return {
        "meetings": meetings,
        "dashboard": build_aftercare_dashboard(meetings),
        "detail": detail,
        "selected_meeting": detail.get("meeting"),
        "preparation": detail.get("preparation") or {},
        "after_note": detail.get("after_note") or {},
        "actions": detail.get("actions") or [],
        "mail_draft": detail.get("mail_draft") or "",
        "readiness": detail.get("readiness") or [],
        "can_edit_aftercare": detail.get("can_edit", False),
        "status_options": [{"value": key, "label": value} for key, value in STATUS_LABELS.items()],
        "action_status_options": [{"value": key, "label": value} for key, value in ACTION_STATUS_LABELS.items()],
        "responsible_options": [{"value": key, "label": value} for key, value in RESPONSIBLE_LABELS.items()],
        "step_cards": STEP_CARDS,
        "opening_sentences": OPENING_SENTENCES,
        "query": query,
        "status": status,
        "schema_ready": _has_existing_core_tables(),
    }
