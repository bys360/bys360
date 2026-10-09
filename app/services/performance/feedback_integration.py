"""BYS360 Performans Görüşme Entegrasyonu Faz 3 servisi.

Bu servis; Not Karnesi, Dönem İçi Notlar ve Görüşme Sonrası Notlar kayıtlarını
aynı personel / dönem bağlamında bir araya getirir. Yeni bir iş kuralı icat etmez;
mevcut kayıtları yetki sınırı içinde okur ve kurumsal süreç hafızası olarak sunar.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import inspect, text

from app.extensions import db
from app.services.performance.history import humanize_workflow_status

logger = logging.getLogger(__name__)

GLOBAL_ROLES = {
    "admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "baskan_yardimcisi"
}
MANAGER_ROLES = GLOBAL_ROLES | {
    "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "yonetici", "manager"
}

NOTE_TYPE_LABELS = {
    "olumlu": "Olumlu Olay",
    "basari": "Başarı Notu",
    "gelisim": "Gelişim İhtiyacı",
    "olumsuz": "Dikkat Alanı",
    "genel": "Genel Gözlem",
    "genel_gozlem": "Genel Gözlem",
    "strength_note": "Güçlü Yön Notu",
    "development_need": "Gelişim İhtiyacı",
}

AFTERCARE_STATUS_LABELS = {
    "taslak": "Taslak",
    "tamamlandi": "Tamamlandı",
    "takipte": "Takipte",
    "planlandi": "Planlandı",
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


def _dialect() -> str:
    try:
        return (db.engine.dialect.name or "").lower()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_integration.py | line=58")
        return ""


def _has_table(table_name: str) -> bool:
    try:
        return inspect(db.engine).has_table(table_name)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_integration.py | line=65")
        db.session.rollback()
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_integration.py | line=73")
        db.session.rollback()
        return set()


def _first(cols: set[str], names: list[str]) -> str | None:
    for name in names:
        if name in cols:
            return name
    return None


def _col(alias: str, cols: set[str], name: str, default: str = "NULL") -> str:
    return f"{alias}.{name}" if name in cols else default


def _text_cast(expr: str) -> str:
    return f"CAST({expr} AS TEXT)"


def _name_expr(alias: str, cols: set[str]) -> str:
    parts: list[str] = []
    for c in ["full_name_cache", "full_name", "name", "display_name"]:
        if c in cols:
            parts.append(f"NULLIF({alias}.{c}, '')")
    if "ad" in cols or "soyad" in cols:
        ad = f"COALESCE({alias}.ad, '')" if "ad" in cols else "''"
        soyad = f"COALESCE({alias}.soyad, '')" if "soyad" in cols else "''"
        parts.append(f"NULLIF(TRIM({ad} || ' ' || {soyad}), '')")
    if "email" in cols:
        parts.append(f"NULLIF({alias}.email, '')")
    parts.append(_text_cast(f"{alias}.id"))
    return "COALESCE(" + ", ".join(parts) + ")"


def _stringify(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        rows = db.session.execute(text(sql), params or {}).mappings().all()
        return [{k: _stringify(v) for k, v in dict(row).items()} for row in rows]
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_integration.py | line=120")
        db.session.rollback()
        return []


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = 0) -> Any:
    try:
        value = db.session.execute(text(sql), params or {}).scalar()
        return default if value is None else value
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_integration.py | line=129")
        db.session.rollback()
        return default


def _role_value(role: str | None) -> str:
    return (role or "").strip().lower()


def is_global_user(role: str | None, *, is_admin: bool = False, is_superuser: bool = False) -> bool:
    return bool(is_admin or is_superuser or _role_value(role) in GLOBAL_ROLES)


def is_manager_user(role: str | None, *, is_admin: bool = False, is_superuser: bool = False) -> bool:
    return bool(is_global_user(role, is_admin=is_admin, is_superuser=is_superuser) or _role_value(role) in MANAGER_ROLES)


def list_periods(limit: int = 80) -> list[dict[str, Any]]:
    cols = _columns("performance_periods")
    if not cols or "id" not in cols:
        return []
    title = _first(cols, ["title", "name", "period_name"]) or "id"
    start = _first(cols, ["start_date", "period_start", "created_at"])
    end = _first(cols, ["end_date", "period_end"])
    select = ["id", f"{title} AS title"]
    if start:
        select.append(f"{start} AS start_date")
    if end:
        select.append(f"{end} AS end_date")
    order = start or "id"
    sql = f"SELECT {', '.join(select)} FROM performance_periods ORDER BY {order} DESC NULLS LAST, id DESC LIMIT :limit"
    rows = _rows(sql, {"limit": int(limit)})
    if not rows and "NULLS LAST" in sql:
        rows = _rows(sql.replace(" DESC NULLS LAST", " DESC"), {"limit": int(limit)})
    return rows


def list_people(*, current_user_id: int | None, current_user_role: str | None, is_admin: bool = False, is_superuser: bool = False, limit: int = 1500) -> list[dict[str, Any]]:
    cols = _columns("users")
    if not cols or "id" not in cols:
        return []
    name = _name_expr("u", cols)
    select = [
        "u.id AS id",
        f"{name} AS full_name",
        _col("u", cols, "sicil_no", "''") + " AS sicil_no",
        _col("u", cols, "unvan", "''") + " AS unvan",
        _col("u", cols, "birim", "''") + " AS birim",
        _col("u", cols, "ust_birim", "''") + " AS ust_birim",
    ]
    where: list[str] = []
    params: dict[str, Any] = {"limit": int(limit)}
    if "is_active" in cols:
        where.append("COALESCE(u.is_active, TRUE)=TRUE")
    if not is_manager_user(current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        where.append("u.id=:current_user_id")
        params["current_user_id"] = int(current_user_id or 0)
    elif not is_global_user(current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        scope: list[str] = ["u.id=:current_user_id"]
        params["current_user_id"] = int(current_user_id or 0)
        for c in ["manager_id", "supervisor_id", "direct_manager_id", "first_manager_id", "second_manager_id", "third_manager_id"]:
            if c in cols:
                scope.append(f"u.{c}=:current_user_id")
        sicil = _scalar("SELECT sicil_no FROM users WHERE id=:uid", {"uid": int(current_user_id or 0)}, default="") if "sicil_no" in cols else ""
        if sicil:
            params["sicil"] = str(sicil)
            for c in ["yonetici_sicil", "ikinci_yonetici_sicil", "ucuncu_yonetici_sicil", "manager_sicil_no", "supervisor_sicil_no"]:
                if c in cols:
                    scope.append(f"u.{c}=:sicil")
        where.append("(" + " OR ".join(scope) + ")")
    sql = "SELECT " + ", ".join(select) + " FROM users u"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY full_name ASC LIMIT :limit"
    return _rows(sql, params)


def _allowed_employee(employee_id: int | None, people: list[dict[str, Any]], *, current_user_id: int | None, current_user_role: str | None, is_admin: bool = False, is_superuser: bool = False) -> bool:
    if not employee_id:
        return False
    if is_global_user(current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        return True
    return any(int(p.get("id") or 0) == int(employee_id) for p in people) or int(employee_id) == int(current_user_id or 0)


def _in_clause(ids: list[int], prefix: str = "scope") -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}
    keys = []
    for idx, value in enumerate(ids):
        key = f"{prefix}_{idx}"
        keys.append(":" + key)
        params[key] = int(value)
    return ",".join(keys) or "NULL", params


def scorecard_rows(employee_id: int | None = None, period_id: int | None = None, people: list[dict[str, Any]] | None = None, limit: int = 12) -> list[dict[str, Any]]:
    people = people or []
    cols = _columns("performance_evaluations")
    ucols = _columns("users")
    pcols = _columns("performance_periods")
    if not cols or "id" not in cols:
        return []
    emp_col = _first(cols, ["employee_id", "user_id", "personnel_id", "employee_user_id"])
    per_col = _first(cols, ["period_id", "performance_period_id"])
    if not emp_col:
        return []
    score_col = _first(cols, ["final_total_100", "final_score_100", "final_score", "score_100", "average_score_100", "total_score_100"])
    status_col = _first(cols, ["status", "workflow_status", "publish_status", "state"])
    published_col = _first(cols, ["is_published", "published", "employee_visible"])
    created_col = _first(cols, ["updated_at", "created_at", "completed_at"])
    employee_name = _name_expr("u", ucols) if ucols else "'Personel'"
    period_title = f"p.{_first(pcols, ['title','name','period_name'])}" if pcols and _first(pcols, ["title", "name", "period_name"]) else "''"
    select = [
        "e.id AS evaluation_id",
        f"e.{emp_col} AS employee_id",
        f"{employee_name} AS employee_name",
        f"{('e.' + per_col) if per_col else 'NULL'} AS period_id",
        f"{period_title} AS period_title",
        f"{('e.' + score_col) if score_col else 'NULL'} AS final_score",
        f"{('e.' + status_col) if status_col else "''"} AS status",
        f"{('e.' + published_col) if published_col else 'NULL'} AS is_published",
        f"{('e.' + created_col) if created_col else 'NULL'} AS updated_at",
    ]
    where: list[str] = []
    params: dict[str, Any] = {"limit": int(limit)}
    if employee_id:
        where.append(f"e.{emp_col}=:employee_id")
        params["employee_id"] = int(employee_id)
    elif people:
        ids = [int(p.get("id") or 0) for p in people if p.get("id") is not None]
        if ids:
            placeholders, scope_params = _in_clause(ids, "emp")
            where.append(f"e.{emp_col} IN ({placeholders})")
            params.update(scope_params)
    if period_id and per_col:
        where.append(f"e.{per_col}=:period_id")
        params["period_id"] = int(period_id)
    sql = "SELECT " + ", ".join(select) + " FROM performance_evaluations e"
    if ucols:
        sql += f" LEFT JOIN users u ON u.id=e.{emp_col}"
    if pcols and per_col:
        sql += f" LEFT JOIN performance_periods p ON p.id=e.{per_col}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order_expr = f"e.{created_col}" if created_col else "e.id"
    sql += f" ORDER BY {order_expr} DESC NULLS LAST, e.id DESC LIMIT :limit"
    rows = _rows(sql, params)
    if not rows and "NULLS LAST" in sql:
        rows = _rows(sql.replace(" DESC NULLS LAST", " DESC"), params)
    for row in rows:
        score = row.get("final_score")
        try:
            score_float = float(score or 0)
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/performance/feedback_integration.py | line=282")
            score_float = 0.0
        row["score_band"] = "low" if score_float < 70 and score is not None else ("high" if score_float > 90 else "mid")
        row["score_label"] = "70 Altı İzlem" if row["score_band"] == "low" else ("90 Üstü Başarı" if row["score_band"] == "high" else "Denge Bandı")
        row["status"] = humanize_workflow_status(row.get("status"))
    return rows


def interim_note_rows(employee_id: int | None = None, period_id: int | None = None, people: list[dict[str, Any]] | None = None, limit: int = 80) -> list[dict[str, Any]]:
    people = people or []
    tables = [t for t in ["performance_interim_notes", "performance_interim_notes_live"] if _has_table(t)]
    out: list[dict[str, Any]] = []
    for table_name in tables:
        cols = _columns(table_name)
        ucols = _columns("users")
        pcols = _columns("performance_periods")
        emp_col = _first(cols, ["employee_id", "employee_user_id", "personnel_id", "user_id"])
        per_col = _first(cols, ["period_id", "performance_period_id"])
        if not emp_col:
            continue
        title_expr = "COALESCE(" + ", ".join([f"NULLIF(n.{c}, '')" for c in ["title", "note_title"] if c in cols] + ["''"]) + ")"
        body_expr = "COALESCE(" + ", ".join([f"NULLIF(n.{c}, '')" for c in ["note_text", "note_body", "note", "content", "description"] if c in cols] + ["''"]) + ")"
        type_col = _first(cols, ["note_type", "type", "category"])
        include_col = _first(cols, ["include_in_scorecard", "visible_on_scorecard", "scorecard_visible"])
        created_col = _first(cols, ["created_at", "occurred_at", "updated_at"])
        employee_name = _name_expr("u", ucols) if ucols else "'Personel'"
        period_title = f"p.{_first(pcols, ['title','name','period_name'])}" if pcols and _first(pcols, ["title", "name", "period_name"]) else "''"
        select = [
            "n.id AS id",
            f"n.{emp_col} AS employee_id",
            f"{employee_name} AS employee_name",
            f"{('n.' + per_col) if per_col else 'NULL'} AS period_id",
            f"{period_title} AS period_title",
            f"{('n.' + type_col) if type_col else "'genel'"} AS note_type",
            f"{title_expr} AS title",
            f"{body_expr} AS body",
            f"{('n.' + include_col) if include_col else 'NULL'} AS include_in_scorecard",
            f"{('n.' + created_col) if created_col else 'NULL'} AS created_at",
            f"'{table_name}' AS source_table",
        ]
        where: list[str] = []
        params: dict[str, Any] = {"limit": int(limit)}
        active_col = _first(cols, ["is_active", "active"])
        if active_col:
            where.append(f"COALESCE(n.{active_col}, TRUE)=TRUE")
        if employee_id:
            where.append(f"n.{emp_col}=:employee_id")
            params["employee_id"] = int(employee_id)
        elif people:
            ids = [int(p.get("id") or 0) for p in people if p.get("id") is not None]
            if ids:
                placeholders, scope_params = _in_clause(ids, "note_emp")
                where.append(f"n.{emp_col} IN ({placeholders})")
                params.update(scope_params)
        if period_id and per_col:
            where.append(f"(n.{per_col}=:period_id OR n.{per_col} IS NULL)")
            params["period_id"] = int(period_id)
        sql = "SELECT " + ", ".join(select) + f" FROM {table_name} n"
        if ucols:
            sql += f" LEFT JOIN users u ON u.id=n.{emp_col}"
        if pcols and per_col:
            sql += f" LEFT JOIN performance_periods p ON p.id=n.{per_col}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        order_expr = f"n.{created_col}" if created_col else "n.id"
        sql += f" ORDER BY {order_expr} DESC NULLS LAST, n.id DESC LIMIT :limit"
        rows = _rows(sql, params)
        if not rows and "NULLS LAST" in sql:
            rows = _rows(sql.replace(" DESC NULLS LAST", " DESC"), params)
        for row in rows:
            row["note_type_label"] = NOTE_TYPE_LABELS.get(str(row.get("note_type") or ""), "Genel Not")
            out.append(row)
    return sorted(out, key=lambda r: str(r.get("created_at") or ""), reverse=True)[:limit]


def aftercare_rows(employee_id: int | None = None, period_id: int | None = None, people: list[dict[str, Any]] | None = None, limit: int = 50) -> list[dict[str, Any]]:
    people = people or []
    if not (_has_table("feedback_meetings") and _has_table("users")):
        return []
    cols = _columns("feedback_meetings")
    ucols = _columns("users")
    pcols = _columns("performance_periods")
    if "id" not in cols:
        return []
    emp_col = _first(cols, ["employee_id", "employee_user_id", "personnel_id", "user_id"])
    manager_col = _first(cols, ["manager_id", "created_by_id"])
    per_col = _first(cols, ["period_id", "performance_period_id"])
    if not emp_col:
        return []
    employee_name = _name_expr("u", ucols) if ucols else "'Personel'"
    manager_name = _name_expr("mngr", ucols) if ucols and manager_col else "''"
    # performance_periods p is joined only when feedback_meetings has a period column.
    period_title = f"p.{_first(pcols, ['title','name','period_name'])}" if pcols and per_col and _first(pcols, ["title", "name", "period_name"]) else "''"
    meeting_date = _first(cols, ["meeting_date", "scheduled_date", "created_at"])
    status_col = _first(cols, ["status", "meeting_status", "state"])
    note_col = _first(cols, ["note", "description"])
    prep_join = "LEFT JOIN feedback_meeting_preparations prep ON prep.meeting_id=f.id" if _has_table("feedback_meeting_preparations") else ""
    after_join = "LEFT JOIN feedback_meeting_after_notes aft ON aft.meeting_id=f.id" if _has_table("feedback_meeting_after_notes") else ""
    action_join = """
        LEFT JOIN (
            SELECT meeting_id, COUNT(*) AS action_count,
                   SUM(CASE WHEN status IN ('acik','takipte','gecikti') THEN 1 ELSE 0 END) AS open_action_count
            FROM feedback_meeting_action_plans
            GROUP BY meeting_id
        ) act ON act.meeting_id=f.id
    """ if _has_table("feedback_meeting_action_plans") else ""
    select = [
        "f.id AS meeting_id",
        f"f.{emp_col} AS employee_id",
        f"{employee_name} AS employee_name",
        f"{('f.' + manager_col) if manager_col else 'NULL'} AS manager_id",
        f"{manager_name} AS manager_name",
        f"{('f.' + per_col) if per_col else 'NULL'} AS period_id",
        f"{period_title} AS period_title",
        f"{('f.' + meeting_date) if meeting_date else 'NULL'} AS meeting_date",
        f"{('f.' + status_col) if status_col else "''"} AS status",
        f"{('f.' + note_col) if note_col else "''"} AS meeting_note",
        "CASE WHEN prep.id IS NULL THEN 0 ELSE 1 END AS has_preparation" if _has_table("feedback_meeting_preparations") else "0 AS has_preparation",
        "CASE WHEN aft.id IS NULL THEN 0 ELSE 1 END AS has_after_note" if _has_table("feedback_meeting_after_notes") else "0 AS has_after_note",
        "COALESCE(aft.meeting_summary, '') AS meeting_summary" if _has_table("feedback_meeting_after_notes") else "'' AS meeting_summary",
        "COALESCE(aft.closure_status, '') AS closure_status" if _has_table("feedback_meeting_after_notes") else "'' AS closure_status",
        "COALESCE(act.action_count, 0) AS action_count" if _has_table("feedback_meeting_action_plans") else "0 AS action_count",
        "COALESCE(act.open_action_count, 0) AS open_action_count" if _has_table("feedback_meeting_action_plans") else "0 AS open_action_count",
    ]
    where: list[str] = []
    params: dict[str, Any] = {"limit": int(limit)}
    if employee_id:
        where.append(f"f.{emp_col}=:employee_id")
        params["employee_id"] = int(employee_id)
    elif people:
        ids = [int(p.get("id") or 0) for p in people if p.get("id") is not None]
        if ids:
            placeholders, scope_params = _in_clause(ids, "mt_emp")
            where.append(f"f.{emp_col} IN ({placeholders})")
            params.update(scope_params)
    if period_id and per_col:
        where.append(f"f.{per_col}=:period_id")
        params["period_id"] = int(period_id)
    sql = "SELECT " + ", ".join(select) + " FROM feedback_meetings f"
    if ucols:
        sql += f" LEFT JOIN users u ON u.id=f.{emp_col}"
        if manager_col:
            sql += f" LEFT JOIN users mngr ON mngr.id=f.{manager_col}"
    if pcols and per_col:
        sql += f" LEFT JOIN performance_periods p ON p.id=f.{per_col}"
    sql += " " + prep_join + " " + after_join + " " + action_join
    if where:
        sql += " WHERE " + " AND ".join(where)
    order_expr = f"f.{meeting_date}" if meeting_date else "f.id"
    sql += f" ORDER BY {order_expr} DESC NULLS LAST, f.id DESC LIMIT :limit"
    rows = _rows(sql, params)
    if not rows and "NULLS LAST" in sql:
        rows = _rows(sql.replace(" DESC NULLS LAST", " DESC"), params)
    for row in rows:
        status = row.get("closure_status") or row.get("status") or ""
        row["status_label"] = AFTERCARE_STATUS_LABELS.get(str(status), "Bilinmiyor" if status else "Kayıt")
        row["is_prepared"] = bool(int(row.get("has_preparation") or 0))
        row["is_closed"] = bool(int(row.get("has_after_note") or 0))
    return rows


def action_rows(employee_id: int | None = None, period_id: int | None = None, people: list[dict[str, Any]] | None = None, limit: int = 80) -> list[dict[str, Any]]:
    people = people or []
    if not (_has_table("feedback_meeting_action_plans") and _has_table("feedback_meetings")):
        return []
    acols = _columns("feedback_meeting_action_plans")
    mcols = _columns("feedback_meetings")
    ucols = _columns("users")
    if "meeting_id" not in acols or "id" not in mcols:
        return []
    emp_expr = "a.employee_id" if "employee_id" in acols else ("m.employee_id" if "employee_id" in mcols else "NULL")
    emp_filter_expr = emp_expr
    per_col = _first(mcols, ["period_id", "performance_period_id"])
    employee_name = _name_expr("u", ucols) if ucols else "'Personel'"
    select = [
        "a.id AS action_id",
        "a.meeting_id",
        f"{emp_expr} AS employee_id",
        f"{employee_name} AS employee_name",
        "a.title AS title" if "title" in acols else "'' AS title",
        "a.smart_description AS smart_description" if "smart_description" in acols else "'' AS smart_description",
        "a.responsible_role AS responsible_role" if "responsible_role" in acols else "'' AS responsible_role",
        "a.target_date AS target_date" if "target_date" in acols else "NULL AS target_date",
        "a.status AS status" if "status" in acols else "'' AS status",
        "a.follow_up_note AS follow_up_note" if "follow_up_note" in acols else "'' AS follow_up_note",
        "a.result_summary AS result_summary" if "result_summary" in acols else "'' AS result_summary",
    ]
    where: list[str] = []
    params: dict[str, Any] = {"limit": int(limit)}
    if employee_id and emp_filter_expr != "NULL":
        where.append(f"{emp_filter_expr}=:employee_id")
        params["employee_id"] = int(employee_id)
    elif people and emp_filter_expr != "NULL":
        ids = [int(p.get("id") or 0) for p in people if p.get("id") is not None]
        if ids:
            placeholders, scope_params = _in_clause(ids, "ac_emp")
            where.append(f"{emp_filter_expr} IN ({placeholders})")
            params.update(scope_params)
    if period_id and per_col:
        where.append(f"m.{per_col}=:period_id")
        params["period_id"] = int(period_id)
    sql = "SELECT " + ", ".join(select) + " FROM feedback_meeting_action_plans a LEFT JOIN feedback_meetings m ON m.id=a.meeting_id"
    if ucols and emp_expr != "NULL":
        sql += f" LEFT JOIN users u ON u.id={emp_expr}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE WHEN a.target_date IS NULL THEN 1 ELSE 0 END, a.target_date ASC, a.id DESC LIMIT :limit"
    rows = _rows(sql, params)
    for row in rows:
        row["status_label"] = ACTION_STATUS_LABELS.get(str(row.get("status") or ""), "Bilinmiyor" if row.get("status") else "-")
    return rows


def build_timeline(scorecards: list[dict[str, Any]], notes: list[dict[str, Any]], meetings: list[dict[str, Any]], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for item in scorecards:
        timeline.append({
            "kind": "scorecard",
            "kind_label": "Not Karnesi",
            "icon": "fa-solid fa-chart-line",
            "date": item.get("updated_at"),
            "title": f"{item.get('employee_name') or 'Personel'} için karne kaydı",
            "body": f"Nihai puan: {item.get('final_score') if item.get('final_score') is not None else '-'} · {item.get('score_label') or ''}",
            "url": f"/performance/scorecard/{item.get('evaluation_id')}" if item.get("evaluation_id") else "",
        })
    for item in notes:
        timeline.append({
            "kind": "interim_note",
            "kind_label": "Dönem İçi Not",
            "icon": "fa-regular fa-note-sticky",
            "date": item.get("created_at"),
            "title": item.get("title") or item.get("note_type_label") or "Dönem İçi Not",
            "body": item.get("body") or "Açıklama girilmemiş.",
            "url": "/performance/interim-notes",
        })
    for item in meetings:
        timeline.append({
            "kind": "aftercare",
            "kind_label": "Görüşme Sonrası",
            "icon": "fa-solid fa-clipboard-check",
            "date": item.get("meeting_date"),
            "title": f"Geri bildirim görüşmesi · {item.get('status_label') or '-'}",
            "body": item.get("meeting_summary") or item.get("meeting_note") or "Görüşme özeti bekleniyor.",
            "url": f"/performance/feedback-aftercare/{item.get('meeting_id')}" if item.get("meeting_id") else "/performance/feedback-aftercare",
        })
    for item in actions:
        timeline.append({
            "kind": "action",
            "kind_label": "Eylem Planı",
            "icon": "fa-solid fa-list-check",
            "date": item.get("target_date"),
            "title": item.get("title") or "Eylem planı",
            "body": item.get("smart_description") or item.get("follow_up_note") or item.get("status_label") or "Takip bilgisi bekleniyor.",
            "url": f"/performance/feedback-aftercare/{item.get('meeting_id')}" if item.get("meeting_id") else "/performance/feedback-aftercare",
        })
    return sorted(timeline, key=lambda r: str(r.get("date") or ""), reverse=True)[:120]


def build_summary(scorecards: list[dict[str, Any]], notes: list[dict[str, Any]], meetings: list[dict[str, Any]], actions: list[dict[str, Any]]) -> dict[str, Any]:
    open_actions = sum(1 for a in actions if str(a.get("status") or "") in {"acik", "takipte", "gecikti"})
    low_scorecards = sum(1 for s in scorecards if s.get("score_band") == "low")
    high_scorecards = sum(1 for s in scorecards if s.get("score_band") == "high")
    closed_meetings = sum(1 for m in meetings if m.get("is_closed"))
    return {
        "scorecard_count": len(scorecards),
        "note_count": len(notes),
        "scorecard_note_count": sum(1 for n in notes if n.get("include_in_scorecard")),
        "meeting_count": len(meetings),
        "closed_meeting_count": closed_meetings,
        "action_count": len(actions),
        "open_action_count": open_actions,
        "low_scorecard_count": low_scorecards,
        "high_scorecard_count": high_scorecards,
        "integration_readiness": round(((closed_meetings + len(notes) + len(scorecards)) / max(1, len(meetings) + len(notes) + len(scorecards))) * 100),
    }


def build_integration_context(*, current_user_id: int | None, current_user_role: str | None, is_admin: bool = False, is_superuser: bool = False, employee_id: int | None = None, period_id: int | None = None) -> dict[str, Any]:
    people = list_people(current_user_id=current_user_id, current_user_role=current_user_role, is_admin=is_admin, is_superuser=is_superuser)
    if employee_id and not _allowed_employee(employee_id, people, current_user_id=current_user_id, current_user_role=current_user_role, is_admin=is_admin, is_superuser=is_superuser):
        return {
            "access_denied": True,
            "people": people,
            "periods": list_periods(),
            "selected_employee_id": employee_id,
            "selected_period_id": period_id,
            "scorecards": [],
            "interim_notes": [],
            "aftercare_meetings": [],
            "action_plans": [],
            "timeline": [],
            "summary": build_summary([], [], [], []),
        }
    if not employee_id and not is_manager_user(current_user_role, is_admin=is_admin, is_superuser=is_superuser) and current_user_id:
        employee_id = int(current_user_id)
    scorecards = scorecard_rows(employee_id=employee_id, period_id=period_id, people=people)
    notes = interim_note_rows(employee_id=employee_id, period_id=period_id, people=people)
    meetings = aftercare_rows(employee_id=employee_id, period_id=period_id, people=people)
    actions = action_rows(employee_id=employee_id, period_id=period_id, people=people)
    return {
        "access_denied": False,
        "people": people,
        "periods": list_periods(),
        "selected_employee_id": employee_id,
        "selected_period_id": period_id,
        "scorecards": scorecards,
        "interim_notes": notes,
        "aftercare_meetings": meetings,
        "action_plans": actions,
        "timeline": build_timeline(scorecards, notes, meetings, actions),
        "summary": build_summary(scorecards, notes, meetings, actions),
        "is_manager_like": is_manager_user(current_user_role, is_admin=is_admin, is_superuser=is_superuser),
    }
