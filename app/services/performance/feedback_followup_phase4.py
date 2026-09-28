"""BYS360 Performans Görüşme Takip Faz 4 servisi.

Bu servis Faz 1'de eklenen görüşme sonrası eylem planlarını takip eder:
- 30 günlük mini takip tarihi üretir,
- yaklaşan takipleri ve geciken aksiyonları listeler,
- sistem içi bildirim ve mail log kaydı oluşturmaya çalışır,
- hiçbir e-posta göndermeden önce izlenebilir kayıt üretir.

Tasarımdaki temel ilke: otomasyon karar vermez; yalnızca hatırlatır ve kayıt üretir.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import inspect, text

from app.extensions import db
from app.services import runtime_schema

logger = logging.getLogger(__name__)

GLOBAL_ROLES = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi"
}
MANAGER_ROLES = GLOBAL_ROLES | {
    "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "yonetici", "manager", "performans_yetkilisi"
}
OPEN_STATUSES = {"acik", "takipte", "gecikti"}
CLOSED_STATUSES = {"tamamlandi", "iptal", "iptal_edildi"}

ACTION_STATUS_LABELS = {
    "acik": "Açık",
    "takipte": "Takipte",
    "tamamlandi": "Tamamlandı",
    "gecikti": "Gecikti",
    "iptal": "İptal Edildi",
    "iptal_edildi": "İptal Edildi",
}
NOTICE_TYPE_LABELS = {
    "followup_due": "Takip Tarihi Yaklaşıyor",
    "followup_overdue": "Geciken Eylem Planı",
    "status_update": "Takip Durumu Güncellendi",
}
NOTICE_STATUS_LABELS = {
    "created": "Kayıt Oluşturuldu",
    "logged": "Mail Log Kaydı Oluşturuldu",
    "notification_logged": "Bildirim Kaydı Oluşturuldu",
    "skipped": "Atlandı",
}
RESPONSIBLE_LABELS = {
    "personel": "Personel",
    "amir": "Amir",
    "ortak": "Ortak",
}


def _dialect() -> str:
    try:
        return (db.engine.dialect.name or "").lower()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=61")
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
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=78")
        db.session.rollback()
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=86")
        db.session.rollback()
        return set()


def _execute(sql: str, params: dict[str, Any] | None = None) -> None:
    db.session.execute(text(sql), params or {})


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        result = db.session.execute(text(sql), params or {}).mappings().all()
        return [_stringify_dict(dict(row)) for row in result]
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=99")
        db.session.rollback()
        return []


def _row(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        value = db.session.execute(text(sql), params or {}).scalar()
        return default if value is None else value
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=113")
        db.session.rollback()
        return default


def _stringify(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _stringify_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _stringify(value) for key, value in row.items()}


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=139")
        return None


def _quote_col(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _name_expr(alias: str) -> str:
    cols = _columns("users")
    parts: list[str] = []
    if {"ad", "soyad"}.issubset(cols):
        parts.append(f"NULLIF(TRIM(COALESCE({alias}.ad,'') || ' ' || COALESCE({alias}.soyad,'')), '')")
    for col in ["full_name_cache", "full_name", "display_name", "name"]:
        if col in cols:
            parts.append(f"NULLIF({alias}.{col}, '')")
    if "email" in cols:
        parts.append(f"NULLIF({alias}.email, '')")
    if "sicil_no" in cols:
        parts.append(f"NULLIF({alias}.sicil_no, '')")
    parts.append(f"CAST({alias}.id AS TEXT)")
    return "COALESCE(" + ", ".join(parts) + ")"


def _user_email(user_id: int | None) -> str:
    if not user_id or not _has_table("users") or "email" not in _columns("users"):
        return ""
    return str(_scalar("SELECT email FROM users WHERE id=:uid", {"uid": int(user_id)}, default="") or "")


def _role_value(role: str | None) -> str:
    return (role or "").strip().lower()


def is_global_user(role: str | None, *, is_admin: bool = False, is_superuser: bool = False) -> bool:
    return bool(is_admin or is_superuser or _role_value(role) in GLOBAL_ROLES)


def is_manager_user(role: str | None, *, is_admin: bool = False, is_superuser: bool = False) -> bool:
    return bool(is_global_user(role, is_admin=is_admin, is_superuser=is_superuser) or _role_value(role) in MANAGER_ROLES)


def _add_column_if_missing(table_name: str, column_name: str, definition: str) -> bool:
    if column_name in _columns(table_name):
        return False
    try:
        _execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
        db.session.commit()
        return True
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=188")
        db.session.rollback()
        return False


_FOLLOWUP_BASE_MISSING = {"ok": False, "skipped": True, "reason": "Faz 1 eylem planı / görüşme / kullanıcı tabloları bulunamadı"}


def _followup_base_tables_exist() -> bool:
    return _has_table("feedback_meeting_action_plans") and _has_table("feedback_meetings") and _has_table("users")


def provision_followup_schema() -> dict[str, Any]:
    """Create the follow-up columns and notice table (explicit maintenance only: flask runtime-schema provision)."""
    if not _followup_base_tables_exist():
        return dict(_FOLLOWUP_BASE_MISSING)
    added = []
    for column, definition in [
        ("follow_up_check_date", "DATE NULL"),
        ("reminder_sent_at", "TIMESTAMP NULL"),
        ("overdue_notice_sent_at", "TIMESTAMP NULL"),
        ("last_followup_status_at", "TIMESTAMP NULL"),
    ]:
        if _add_column_if_missing("feedback_meeting_action_plans", column, definition):
            added.append(column)

    pk = _pk_sql()
    ddl = f"""
        CREATE TABLE IF NOT EXISTS feedback_action_followup_notices (
            id {pk},
            action_id INTEGER NOT NULL REFERENCES feedback_meeting_action_plans(id) ON DELETE CASCADE,
            meeting_id INTEGER NULL REFERENCES feedback_meetings(id) ON DELETE CASCADE,
            recipient_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            notice_type VARCHAR(60) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            body TEXT NULL,
            channel VARCHAR(40) NOT NULL DEFAULT 'system_mail_log',
            status VARCHAR(40) NOT NULL DEFAULT 'created',
            related_url VARCHAR(500) NULL,
            mail_log_id INTEGER NULL,
            notification_id INTEGER NULL,
            created_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP NULL
        )
    """
    try:
        _execute(ddl)
        _execute("CREATE INDEX IF NOT EXISTS ix_feedback_followup_notices_action ON feedback_action_followup_notices(action_id)")
        _execute("CREATE INDEX IF NOT EXISTS ix_feedback_followup_notices_recipient ON feedback_action_followup_notices(recipient_id)")
        _execute("CREATE INDEX IF NOT EXISTS ix_feedback_followup_notices_type ON feedback_action_followup_notices(notice_type)")
        db.session.commit()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=233")
        db.session.rollback()
    return {"ok": True, "added_columns": added, "table": "feedback_action_followup_notices"}


FOLLOWUP_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.feedback_followup",
    tables=("feedback_action_followup_notices",),
    indexes=(
        ("feedback_action_followup_notices", "ix_feedback_followup_notices_action"),
        ("feedback_action_followup_notices", "ix_feedback_followup_notices_recipient"),
        ("feedback_action_followup_notices", "ix_feedback_followup_notices_type"),
    ),
    columns=(
        ("feedback_meeting_action_plans", "follow_up_check_date"),
        ("feedback_meeting_action_plans", "reminder_sent_at"),
        ("feedback_meeting_action_plans", "overdue_notice_sent_at"),
        ("feedback_meeting_action_plans", "last_followup_status_at"),
    ),
    provision=provision_followup_schema,
))


def ensure_followup_schema() -> dict[str, Any]:
    """Verify the follow-up columns and notice table exist; never creates them (see app.services.runtime_schema)."""
    if not _followup_base_tables_exist():
        return dict(_FOLLOWUP_BASE_MISSING)
    runtime_schema.require(FOLLOWUP_SCHEMA)
    return {"ok": True, "added_columns": [], "table": "feedback_action_followup_notices"}


def normalize_30_day_followups() -> int:
    """Hedef tarihi boş olan aksiyonlara görüşme tarihinden 30 gün sonrası için takip tarihi verir."""
    schema = ensure_followup_schema()
    if not schema.get("ok"):
        return 0
    rows = _rows(
        """
        SELECT a.id, a.target_date, a.follow_up_check_date, m.meeting_date
        FROM feedback_meeting_action_plans a
        LEFT JOIN feedback_meetings m ON m.id = a.meeting_id
        WHERE (a.follow_up_check_date IS NULL OR a.follow_up_check_date = '')
        ORDER BY a.id DESC
        LIMIT 500
        """
    )
    count = 0
    for row in rows:
        base = _parse_date(row.get("target_date")) or _parse_date(row.get("meeting_date"))
        if not base:
            continue
        followup_date = base if row.get("target_date") else base + timedelta(days=30)
        try:
            _execute(
                "UPDATE feedback_meeting_action_plans SET follow_up_check_date=:followup_date WHERE id=:action_id",
                {"followup_date": followup_date.isoformat(), "action_id": int(row["id"])},
            )
            count += 1
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=265")
            db.session.rollback()
    if count:
        try:
            db.session.commit()
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=270")
            db.session.rollback()
    return count


def _visibility_where(role: str | None, current_user_id: int | None, *, is_admin: bool = False, is_superuser: bool = False) -> tuple[str, dict[str, Any]]:
    if is_global_user(role, is_admin=is_admin, is_superuser=is_superuser):
        return "", {}
    params = {"current_user_id": int(current_user_id or 0)}
    scope = ["m.employee_id=:current_user_id", "m.manager_id=:current_user_id", "a.employee_id=:current_user_id", "a.manager_id=:current_user_id"]
    return "WHERE (" + " OR ".join(scope) + ")", params


def _action_select_sql(where_sql: str = "") -> str:
    employee_name = _name_expr("e")
    manager_name = _name_expr("g")
    return f"""
        SELECT
            a.id AS action_id,
            a.meeting_id,
            a.employee_id,
            a.manager_id,
            a.title,
            a.smart_description,
            a.responsible_role,
            a.target_date,
            a.status,
            a.follow_up_note,
            a.result_summary,
            a.created_at,
            a.updated_at,
            a.follow_up_check_date,
            a.reminder_sent_at,
            a.overdue_notice_sent_at,
            a.last_followup_status_at,
            m.meeting_date,
            m.meeting_start,
            m.status AS meeting_status,
            {employee_name} AS employee_name,
            {manager_name} AS manager_name
        FROM feedback_meeting_action_plans a
        LEFT JOIN feedback_meetings m ON m.id = a.meeting_id
        LEFT JOIN users e ON e.id = COALESCE(a.employee_id, m.employee_id)
        LEFT JOIN users g ON g.id = COALESCE(a.manager_id, m.manager_id)
        {where_sql}
    """


def _decorate_action(row: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    due = _parse_date(row.get("target_date")) or _parse_date(row.get("follow_up_check_date"))
    row["due_date"] = due.isoformat() if due else ""
    row["status_label"] = ACTION_STATUS_LABELS.get(row.get("status") or "", row.get("status") or "-")
    row["responsible_label"] = RESPONSIBLE_LABELS.get(row.get("responsible_role") or "", row.get("responsible_role") or "-")
    status = (row.get("status") or "").strip().lower()
    if status in CLOSED_STATUSES:
        row["due_state"] = "closed"
        row["due_state_label"] = "Kapanmış"
        row["days_left"] = None
    elif not due:
        row["due_state"] = "no_date"
        row["due_state_label"] = "Takip tarihi yok"
        row["days_left"] = None
    else:
        diff = (due - today).days
        row["days_left"] = diff
        if diff < 0:
            row["due_state"] = "overdue"
            row["due_state_label"] = f"{abs(diff)} gün gecikti"
        elif diff == 0:
            row["due_state"] = "today"
            row["due_state_label"] = "Bugün takip edilmeli"
        elif diff <= 7:
            row["due_state"] = "upcoming"
            row["due_state_label"] = f"{diff} gün kaldı"
        else:
            row["due_state"] = "scheduled"
            row["due_state_label"] = f"{diff} gün kaldı"
    return row


def list_followup_actions(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    due_filter: str = "open",
    query: str = "",
    limit: int = 350,
) -> list[dict[str, Any]]:
    schema = ensure_followup_schema()
    if not schema.get("ok"):
        return []
    normalize_30_day_followups()
    where_sql, params = _visibility_where(current_user_role, current_user_id, is_admin=is_admin, is_superuser=is_superuser)
    sql = _action_select_sql(where_sql)
    if query:
        condition = "(LOWER(COALESCE(a.title,'')) LIKE :q OR LOWER(COALESCE(a.smart_description,'')) LIKE :q OR LOWER(COALESCE(a.follow_up_note,'')) LIKE :q OR LOWER(" + _name_expr("e") + ") LIKE :q OR LOWER(" + _name_expr("g") + ") LIKE :q)"
        if where_sql.strip():
            sql += " AND " + condition
        else:
            sql += " WHERE " + condition
        params["q"] = f"%{query.lower()}%"
    sql += " ORDER BY CASE WHEN a.follow_up_check_date IS NULL THEN 1 ELSE 0 END, a.follow_up_check_date ASC, a.target_date ASC, a.id DESC LIMIT :limit"
    params["limit"] = int(limit or 350)
    rows = [_decorate_action(row) for row in _rows(sql, params)]
    due_filter = (due_filter or "open").strip().lower()
    if due_filter == "all":
        return rows
    if due_filter == "open":
        return [r for r in rows if (r.get("status") or "").lower() in OPEN_STATUSES]
    if due_filter == "overdue":
        return [r for r in rows if r.get("due_state") == "overdue"]
    if due_filter == "upcoming":
        return [r for r in rows if r.get("due_state") in {"today", "upcoming"}]
    if due_filter == "no_date":
        return [r for r in rows if r.get("due_state") == "no_date"]
    if due_filter == "closed":
        return [r for r in rows if r.get("due_state") == "closed"]
    return rows


def build_dashboard(actions: list[dict[str, Any]]) -> dict[str, Any]:
    open_actions = [a for a in actions if (a.get("status") or "").lower() in OPEN_STATUSES]
    overdue = [a for a in actions if a.get("due_state") == "overdue"]
    upcoming = [a for a in actions if a.get("due_state") in {"today", "upcoming"}]
    no_date = [a for a in actions if a.get("due_state") == "no_date"]
    closed = [a for a in actions if a.get("due_state") == "closed"]
    return {
        "total": len(actions),
        "open": len(open_actions),
        "overdue": len(overdue),
        "upcoming": len(upcoming),
        "no_date": len(no_date),
        "closed": len(closed),
    }


def _dynamic_insert(table_name: str, values: dict[str, Any]) -> int | None:
    if not _has_table(table_name):
        return None
    cols = _columns(table_name)
    payload = {k: v for k, v in values.items() if k in cols}
    if not payload:
        return None
    names = list(payload.keys())
    col_sql = ", ".join(_quote_col(name) for name in names)
    bind_sql = ", ".join(f":{name}" for name in names)
    try:
        _execute(f"INSERT INTO {table_name} ({col_sql}) VALUES ({bind_sql})", payload)
        inserted_id = _scalar("SELECT last_insert_rowid()" if _dialect() == "sqlite" else f"SELECT MAX(id) FROM {table_name}", default=None)
        db.session.commit()
        return int(inserted_id) if inserted_id else None
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=424")
        db.session.rollback()
        return None


def _log_to_notifications(recipient_id: int | None, subject: str, body: str, url: str, notice_type: str) -> int | None:
    values = {
        "user_id": recipient_id,
        "recipient_id": recipient_id,
        "title": subject,
        "subject": subject,
        "message": body,
        "body": body,
        "content": body,
        "type": notice_type,
        "notification_type": notice_type,
        "priority": "normal" if notice_type == "followup_due" else "high",
        "url": url,
        "link": url,
        "is_read": False,
        "read": False,
        "created_at": datetime.now(),
    }
    return _dynamic_insert("notifications", values)


def _log_to_mail_logs(recipient_id: int | None, subject: str, body: str, url: str, notice_type: str, created_by_id: int | None) -> int | None:
    email = _user_email(recipient_id)
    values = {
        "user_id": recipient_id,
        "recipient_id": recipient_id,
        "to_user_id": recipient_id,
        "recipient_email": email,
        "to_email": email,
        "email": email,
        "to": email,
        "subject": subject,
        "body": body,
        "message": body,
        "content": body,
        "status": "created",
        "module": "performance",
        "event": notice_type,
        "event_type": notice_type,
        "category": "performance_followup",
        "related_url": url,
        "url": url,
        "created_by_id": created_by_id,
        "created_at": datetime.now(),
    }
    return _dynamic_insert("mail_logs", values)


def _existing_notice(action_id: int, recipient_id: int | None, notice_type: str) -> int | None:
    if not _has_table("feedback_action_followup_notices"):
        return None
    return _scalar(
        """
        SELECT id FROM feedback_action_followup_notices
        WHERE action_id=:action_id
          AND notice_type=:notice_type
          AND COALESCE(recipient_id, 0)=COALESCE(:recipient_id, 0)
        ORDER BY id DESC LIMIT 1
        """,
        {"action_id": action_id, "recipient_id": recipient_id, "notice_type": notice_type},
    )


def _create_notice_for_recipient(action: dict[str, Any], recipient_id: int | None, notice_type: str, created_by_id: int | None) -> dict[str, Any]:
    ensure_followup_schema()
    action_id = int(action.get("action_id") or 0)
    if not action_id:
        return {"created": False, "reason": "action_id yok"}
    existing = _existing_notice(action_id, recipient_id, notice_type)
    if existing:
        return {"created": False, "existing_id": existing, "reason": "önceden oluşturulmuş"}

    employee = action.get("employee_name") or "Personel"
    due = action.get("due_date") or "takip tarihi"
    title = action.get("title") or "Eylem planı"
    if notice_type == "followup_overdue":
        subject = "BYS360 | Geciken performans eylem planı"
        body = f"{employee} için tanımlanan '{title}' eylem planının takip tarihi ({due}) geçmiştir. Lütfen görüşme sonrası takip kaydını güncelleyiniz."
    elif notice_type == "status_update":
        subject = "BYS360 | Performans eylem planı güncellendi"
        body = f"{employee} için tanımlanan '{title}' eylem planının takip durumu güncellendi."
    else:
        subject = "BYS360 | Performans eylem planı takip hatırlatması"
        body = f"{employee} için tanımlanan '{title}' eylem planının takip tarihi yaklaşıyor: {due}. Lütfen görüşme sonrası takip kaydını kontrol ediniz."
    url = f"/performance/feedback-aftercare/{action.get('meeting_id')}"
    notification_id = _log_to_notifications(recipient_id, subject, body, url, notice_type)
    mail_log_id = _log_to_mail_logs(recipient_id, subject, body, url, notice_type, created_by_id)
    status = "created"
    if notification_id and mail_log_id:
        status = "notification_logged"
    elif mail_log_id:
        status = "logged"
    elif notification_id:
        status = "notification_logged"
    try:
        _execute(
            """
            INSERT INTO feedback_action_followup_notices
                (action_id, meeting_id, recipient_id, notice_type, subject, body, channel, status, related_url, mail_log_id, notification_id, created_by_id, created_at)
            VALUES
                (:action_id, :meeting_id, :recipient_id, :notice_type, :subject, :body, 'system_mail_log', :status, :related_url, :mail_log_id, :notification_id, :created_by_id, CURRENT_TIMESTAMP)
            """,
            {
                "action_id": action_id,
                "meeting_id": action.get("meeting_id"),
                "recipient_id": recipient_id,
                "notice_type": notice_type,
                "subject": subject,
                "body": body,
                "status": status,
                "related_url": url,
                "mail_log_id": mail_log_id,
                "notification_id": notification_id,
                "created_by_id": created_by_id,
            },
        )
        notice_id = _scalar("SELECT MAX(id) FROM feedback_action_followup_notices", default=None)
        db.session.commit()
        return {"created": True, "notice_id": notice_id, "mail_log_id": mail_log_id, "notification_id": notification_id, "status": status}
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=548")
        db.session.rollback()
        return {"created": False, "reason": str(exc)}


def _notice_recipients(action: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for key in ["employee_id", "manager_id"]:
        try:
            value = int(action.get(key) or 0)
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=558")
            value = 0
        if value and value not in values:
            values.append(value)
    return values


def generate_followup_notices(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    days_ahead: int = 7,
) -> dict[str, Any]:
    schema = ensure_followup_schema()
    if not schema.get("ok"):
        return {"ok": False, "created": 0, "reason": schema.get("reason")}
    actions = list_followup_actions(
        current_user_id=current_user_id,
        current_user_role=current_user_role,
        is_admin=is_admin,
        is_superuser=is_superuser,
        due_filter="open",
        limit=700,
    )
    today = date.today()
    created = 0
    skipped = 0
    reminder_actions: list[int] = []
    overdue_actions: list[int] = []
    details: list[dict[str, Any]] = []
    for action in actions:
        due = _parse_date(action.get("due_date"))
        if not due:
            skipped += 1
            continue
        notice_type = ""
        if due < today and not action.get("overdue_notice_sent_at"):
            notice_type = "followup_overdue"
        elif today <= due <= today + timedelta(days=int(days_ahead or 7)) and not action.get("reminder_sent_at"):
            notice_type = "followup_due"
        if not notice_type:
            skipped += 1
            continue
        action_created = 0
        for recipient_id in _notice_recipients(action):
            result = _create_notice_for_recipient(action, recipient_id, notice_type, current_user_id)
            details.append({"action_id": action.get("action_id"), "recipient_id": recipient_id, "notice_type": notice_type, **result})
            if result.get("created"):
                action_created += 1
                created += 1
        if action_created:
            if notice_type == "followup_overdue":
                overdue_actions.append(int(action["action_id"]))
            else:
                reminder_actions.append(int(action["action_id"]))
        else:
            skipped += 1
    for action_id in reminder_actions:
        try:
            _execute("UPDATE feedback_meeting_action_plans SET reminder_sent_at=CURRENT_TIMESTAMP WHERE id=:id", {"id": action_id})
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=620")
            db.session.rollback()
    for action_id in overdue_actions:
        try:
            _execute("UPDATE feedback_meeting_action_plans SET overdue_notice_sent_at=CURRENT_TIMESTAMP, status=CASE WHEN status IN ('acik','takipte') THEN 'gecikti' ELSE status END WHERE id=:id", {"id": action_id})
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=625")
            db.session.rollback()
    try:
        db.session.commit()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=629")
        db.session.rollback()
    return {"ok": True, "created": created, "skipped": skipped, "details": details}


def list_recent_notices(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    limit: int = 80,
) -> list[dict[str, Any]]:
    schema = ensure_followup_schema()
    if not schema.get("ok"):
        return []
    where = ""
    params: dict[str, Any] = {"limit": int(limit or 80)}
    if not is_global_user(current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        where = "WHERE n.recipient_id=:current_user_id OR n.created_by_id=:current_user_id"
        params["current_user_id"] = int(current_user_id or 0)
    sql = f"""
        SELECT n.*, a.title AS action_title, {_name_expr('u')} AS recipient_name
        FROM feedback_action_followup_notices n
        LEFT JOIN feedback_meeting_action_plans a ON a.id = n.action_id
        LEFT JOIN users u ON u.id = n.recipient_id
        {where}
        ORDER BY n.created_at DESC, n.id DESC
        LIMIT :limit
    """
    rows = _rows(sql, params)
    for row in rows:
        row["notice_type_label"] = NOTICE_TYPE_LABELS.get(row.get("notice_type") or "", row.get("notice_type") or "-")
        row["status_label"] = NOTICE_STATUS_LABELS.get(row.get("status") or "", row.get("status") or "-")
    return rows


def update_followup_action(action_id: int, form: Any) -> int | None:
    ensure_followup_schema()
    status = (form.get("status") or "takipte").strip()
    follow_up_note = (form.get("follow_up_note") or "").strip()
    result_summary = (form.get("result_summary") or "").strip()
    follow_up_check_date = (form.get("follow_up_check_date") or "").strip() or None
    try:
        _execute(
            """
            UPDATE feedback_meeting_action_plans
            SET status=:status,
                follow_up_note=:follow_up_note,
                result_summary=:result_summary,
                follow_up_check_date=COALESCE(:follow_up_check_date, follow_up_check_date),
                last_followup_status_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=:action_id
            """,
            {
                "action_id": int(action_id),
                "status": status,
                "follow_up_note": follow_up_note,
                "result_summary": result_summary,
                "follow_up_check_date": follow_up_check_date,
            },
        )
        meeting_id = _scalar("SELECT meeting_id FROM feedback_meeting_action_plans WHERE id=:action_id", {"action_id": int(action_id)})
        db.session.commit()
        return int(meeting_id) if meeting_id else None
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_followup_phase4.py | line=695")
        db.session.rollback()
        return None


def get_action_for_user(
    action_id: int,
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
) -> dict[str, Any] | None:
    schema = ensure_followup_schema()
    if not schema.get("ok"):
        return None
    where_sql, params = _visibility_where(current_user_role, current_user_id, is_admin=is_admin, is_superuser=is_superuser)
    sql = _action_select_sql(where_sql)
    if where_sql.strip():
        sql += " AND a.id=:action_id"
    else:
        sql += " WHERE a.id=:action_id"
    params["action_id"] = int(action_id)
    row = _row(sql, params)
    return _decorate_action(row) if row else None


def build_followup_context(
    *,
    current_user_id: int | None,
    current_user_role: str | None,
    is_admin: bool = False,
    is_superuser: bool = False,
    due_filter: str = "open",
    query: str = "",
) -> dict[str, Any]:
    schema = ensure_followup_schema()
    actions_all = list_followup_actions(
        current_user_id=current_user_id,
        current_user_role=current_user_role,
        is_admin=is_admin,
        is_superuser=is_superuser,
        due_filter="all",
        query=query,
    ) if schema.get("ok") else []
    filtered = actions_all
    if due_filter and due_filter != "all":
        filtered = list_followup_actions(
            current_user_id=current_user_id,
            current_user_role=current_user_role,
            is_admin=is_admin,
            is_superuser=is_superuser,
            due_filter=due_filter,
            query=query,
        )
    return {
        "schema_ready": bool(schema.get("ok")),
        "schema_message": schema.get("reason", ""),
        "actions": filtered,
        "all_actions": actions_all,
        "dashboard": build_dashboard(actions_all),
        "recent_notices": list_recent_notices(
            current_user_id=current_user_id,
            current_user_role=current_user_role,
            is_admin=is_admin,
            is_superuser=is_superuser,
        ),
        "due_filter": due_filter or "open",
        "query": query or "",
        "status_options": [{"value": key, "label": value} for key, value in ACTION_STATUS_LABELS.items()],
        "filter_options": [
            {"value": "open", "label": "Açık / Takipte"},
            {"value": "overdue", "label": "Gecikenler"},
            {"value": "upcoming", "label": "Yaklaşanlar"},
            {"value": "no_date", "label": "Takip Tarihi Yok"},
            {"value": "closed", "label": "Kapananlar"},
            {"value": "all", "label": "Tümü"},
        ],
        "can_generate_notices": is_manager_user(current_user_role, is_admin=is_admin, is_superuser=is_superuser),
    }
