
"""BYS360 Dashboard Rebuild D1-D4 gerçek veri servisi.

Bu servis dashboard ekranını tek modülün temsili kartlarından çıkarıp personel,
performans, destek, bildirim, anket, geri bildirim ve karar destek özetlerini tek
kurumsal yönetici yüzeyinde toplar. Sorgular tablo/kolon farklılıklarına karşı
korumalıdır; eksik tablo veya boş veri dashboard'u beyaz ekrana düşürmez.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask import current_app
from sqlalchemy import bindparam, inspect as sa_inspect, text

from app.extensions import db

try:  # Canlı projede var; yoksa servis güvenli dar kapsamla çalışır.
    from app.services.ui_context.scope import build_user_scope_context
except Exception:  # pragma: no cover
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/dashboard_rebuild_service.py:21")
    build_user_scope_context = None  # type: ignore[assignment]

BYS360_DASHBOARD_REBUILD_SERVICE_OK = True
BYS360_DASHBOARD_REBUILD_PHASES = ("D1", "D2", "D3", "D4", "D5")

GLOBAL_ROLES = {
    "admin",
    "sistem_yoneticisi",
    "system_admin",
    "baskan",
    "başkan",
    "baskan_yardimcisi",
    "başkan_yardımcısı",
    "mali_musavir",
    "mali_müşavir",
}

MANAGER_ROLES = GLOBAL_ROLES | {
    "grup_baskani",
    "grup_başkanı",
    "koordinator",
    "koordinatör",
    "performans_yetkilisi",
    "ik",
    "ik_yetkilisi",
    "personel_yetkilisi",
    "personel_ve_destek_grup_baskani",
}

OPEN_SUPPORT_STATUSES = {"open", "reviewing", "waiting_info", "assigned", "planned", "in_progress", "islemde", "işlemde", "açık", "acik"}
CLOSED_SUPPORT_STATUSES = {"resolved", "closed", "rejected", "completed", "kapali", "kapalı", "çözüldü", "cozuldu"}
COMPLETED_ASSIGNMENT_STATUSES = {"tamamlandi", "tamamlandı", "completed", "final", "yayinda", "yayında"}
OPEN_ACTION_STATUSES = {"open", "in_progress", "planned", "waiting", "bekliyor", "açık", "acik", "islemde", "işlemde"}
ACTIVE_SURVEY_STATUSES = {"active", "published", "open", "yayinda", "yayında", "açık", "acik"}


class _Reader:
    def __init__(self) -> None:
        self._inspector: Any = None
        self._tables: set[str] | None = None
        self._columns: dict[str, set[str]] = {}

    @property
    def inspector(self):
        if self._inspector is None:
            self._inspector = sa_inspect(db.engine)
        return self._inspector

    @property
    def tables(self) -> set[str]:
        if self._tables is None:
            try:
                self._tables = set(self.inspector.get_table_names())
            except Exception as exc:
                current_app.logger.warning("Dashboard tablo listesi okunamadı: %s", exc)
                db.session.rollback()
                self._tables = set()
        return self._tables

    def has_table(self, table: str) -> bool:
        return table in self.tables

    def columns(self, table: str) -> set[str]:
        if table not in self._columns:
            if not self.has_table(table):
                self._columns[table] = set()
            else:
                try:
                    self._columns[table] = {col["name"] for col in self.inspector.get_columns(table)}
                except Exception as exc:
                    current_app.logger.warning("Dashboard kolon listesi okunamadı (%s): %s", table, exc)
                    db.session.rollback()
                    self._columns[table] = set()
        return self._columns[table]

    def has_col(self, table: str, column: str) -> bool:
        return column in self.columns(table)

    def first_col(self, table: str, candidates: list[str], default: str | None = None) -> str | None:
        cols = self.columns(table)
        for col in candidates:
            if col in cols:
                return col
        return default

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        try:
            stmt = text(sql)
            if "scope_ids" in params:
                stmt = stmt.bindparams(bindparam("scope_ids", expanding=True))
            return db.session.execute(stmt, params).scalar()
        except Exception as exc:
            current_app.logger.warning("Dashboard sorgusu güvenli boş döndü: %s", exc)
            db.session.rollback()
            return None

    def rows(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        params = params or {}
        try:
            stmt = text(sql)
            if "scope_ids" in params:
                stmt = stmt.bindparams(bindparam("scope_ids", expanding=True))
            return [dict(row._mapping) for row in db.session.execute(stmt, params).all()]
        except Exception as exc:
            current_app.logger.warning("Dashboard liste sorgusu güvenli boş döndü: %s", exc)
            db.session.rollback()
            return []


def _normalize_role(user: Any) -> str:
    return str(getattr(user, "role", "") or "").strip().lower()


def _user_id(user: Any) -> int | None:
    try:
        value = int(getattr(user, "id", 0) or 0)
        return value or None
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/dashboard_rebuild_service.py:140")
        return None


def _user_label(user: Any) -> str:
    full = str(getattr(user, "full_name", "") or getattr(user, "full_name_cache", "") or "").strip()
    if full:
        return full
    return f"{getattr(user, 'ad', '') or ''} {getattr(user, 'soyad', '') or ''}".strip() or "Kullanıcı"


def _is_manager(user: Any) -> bool:
    # BYS360 DEFECT FS (Final Sweep A2-04): the substring fallback
    # (`"baskan" in role`) matched any role string merely *containing* those
    # letters, which could surface manager-only quick-action navigation
    # links to a non-manager. UI/navigation exposure only -- this flag never
    # gated real data (see _resolve_scope_ids, an independent exact-match
    # function used for all actual scope filtering). MANAGER_ROLES already
    # lists every legitimate manager role variant explicitly.
    return _normalize_role(user) in MANAGER_ROLES


def _resolve_scope_ids(user: Any) -> list[int] | None:
    """None = geniş yetki; liste = kısıtlı kişi kapsamı."""
    role = _normalize_role(user)
    uid = _user_id(user)
    if role in GLOBAL_ROLES:
        return None
    if build_user_scope_context is not None:
        try:
            scope = build_user_scope_context(user, None) or {}
            raw_ids = scope.get("scope_user_ids") or scope.get("user_ids") or []
            ids = sorted({int(x) for x in raw_ids if x})
            if ids:
                return ids
        except Exception as exc:
            current_app.logger.warning("Dashboard yetki kapsamı güvenli daraltıldı: %s", exc)
            db.session.rollback()
    return [uid] if uid else []


def _scope_clause(alias: str, column: str, scope_ids: list[int] | None, prefix: str = " AND ") -> tuple[str, dict[str, Any]]:
    if scope_ids is None:
        return "", {}
    if not scope_ids:
        return f"{prefix}1=0", {}
    return f"{prefix}{alias}.{column} IN :scope_ids", {"scope_ids": scope_ids}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/dashboard_rebuild_service.py:186")
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/dashboard_rebuild_service.py:193")
        return default


def _pct(part: Any, total: Any) -> float:
    total_f = _float(total)
    if total_f <= 0:
        return 0.0
    return round((_float(part) / total_f) * 100, 1)


def _short(text_value: Any, max_len: int = 24) -> str:
    value = str(text_value or "-").strip() or "-"
    return value if len(value) <= max_len else value[: max_len - 1] + "…"


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().strftime("%d.%m.%Y %H:%M")


def _active_period(reader: _Reader) -> dict[str, Any] | None:
    if not reader.has_table("performance_periods"):
        return None
    cols = reader.columns("performance_periods")
    label_col = reader.first_col("performance_periods", ["title", "name", "period_name"], "id")
    start_col = reader.first_col("performance_periods", ["start_date", "start_at"], None)
    end_col = reader.first_col("performance_periods", ["end_date", "end_at"], None)
    is_active = "is_active" in cols
    select_parts = ["id", f"{label_col} AS label"]
    select_parts.append(f"{start_col} AS start_value" if start_col else "NULL AS start_value")
    select_parts.append(f"{end_col} AS end_value" if end_col else "NULL AS end_value")
    where = "WHERE COALESCE(is_active, false) = true" if is_active else ""
    order_col = start_col or "id"
    rows = reader.rows(
        f"SELECT {', '.join(select_parts)} FROM performance_periods {where} ORDER BY {order_col} DESC NULLS LAST, id DESC LIMIT 1"
    )
    if not rows and is_active:
        rows = reader.rows(
            f"SELECT {', '.join(select_parts)} FROM performance_periods ORDER BY {order_col} DESC NULLS LAST, id DESC LIMIT 1"
        )
    return rows[0] if rows else None


def _period_range(period: dict[str, Any] | None) -> str:
    if not period:
        return "Aktif dönem bulunamadı"
    start = period.get("start_value")
    end = period.get("end_value")
    if start and end:
        try:
            return f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/dashboard_rebuild_service.py:244")
            return f"{start} – {end}"
    return "Tarih aralığı tanımlı değil"


def _count_users(reader: _Reader, scope_ids: list[int] | None, active_only: bool = False) -> int:
    if not reader.has_table("users"):
        return 0
    where = "WHERE 1=1"
    params: dict[str, Any] = {}
    clause, scope_params = _scope_clause("u", "id", scope_ids)
    where += clause
    params.update(scope_params)
    if active_only and reader.has_col("users", "is_active"):
        where += " AND COALESCE(u.is_active, false) = true"
    return _int(reader.scalar(f"SELECT COUNT(*) FROM users u {where}", params))


def _performance_distribution(reader: _Reader, period_id: int | None, scope_ids: list[int] | None) -> dict[str, Any]:
    labels = ["70 altı", "70–89", "90 üstü"]
    if not reader.has_table("performance_evaluations") or not reader.has_col("performance_evaluations", "final_total_100"):
        return _chart("performance_distribution", "Performans Dağılımı", labels, [0, 0, 0], "donut")
    where = "WHERE pe.final_total_100 IS NOT NULL AND pe.final_total_100 > 0"
    params: dict[str, Any] = {}
    if period_id and reader.has_col("performance_evaluations", "period_id"):
        where += " AND pe.period_id = :period_id"
        params["period_id"] = period_id
    if reader.has_col("performance_evaluations", "employee_id"):
        clause, scope_params = _scope_clause("pe", "employee_id", scope_ids)
        where += clause
        params.update(scope_params)
    row = reader.rows(
        f"""
        SELECT
          SUM(CASE WHEN pe.final_total_100 < 70 THEN 1 ELSE 0 END) AS low_count,
          SUM(CASE WHEN pe.final_total_100 >= 70 AND pe.final_total_100 < 90 THEN 1 ELSE 0 END) AS mid_count,
          SUM(CASE WHEN pe.final_total_100 >= 90 THEN 1 ELSE 0 END) AS high_count
        FROM performance_evaluations pe {where}
        """,
        params,
    )
    values = [0, 0, 0]
    if row:
        values = [_int(row[0].get("low_count")), _int(row[0].get("mid_count")), _int(row[0].get("high_count"))]
    return _chart("performance_distribution", "Performans Dağılımı", labels, values, "donut")


def _period_completion(reader: _Reader, period_id: int | None, scope_ids: list[int] | None) -> dict[str, Any]:
    labels = ["Tamamlanan", "Bekleyen", "Geciken"]
    if not reader.has_table("evaluation_assignments"):
        return _chart("period_completion", "Dönem Tamamlama", labels, [0, 0, 0], "bars")
    cols = reader.columns("evaluation_assignments")
    where = "WHERE 1=1"
    params: dict[str, Any] = {"now_value": datetime.now(UTC)}
    if period_id and "period_id" in cols:
        where += " AND ea.period_id = :period_id"
        params["period_id"] = period_id
    if "employee_id" in cols:
        clause, scope_params = _scope_clause("ea", "employee_id", scope_ids)
        where += clause
        params.update(scope_params)
    status_expr = "LOWER(COALESCE(ea.status, ''))"
    completed_sql = "ea.completed_at IS NOT NULL" if "completed_at" in cols else "false"
    overdue_sql = "ea.due_date IS NOT NULL AND ea.due_date < :now_value" if "due_date" in cols else "false"
    row = reader.rows(
        f"""
        SELECT
          SUM(CASE WHEN {completed_sql} OR {status_expr} IN ('tamamlandi','tamamlandı','completed','final','yayinda','yayında') THEN 1 ELSE 0 END) AS completed_count,
          SUM(CASE WHEN NOT ({completed_sql} OR {status_expr} IN ('tamamlandi','tamamlandı','completed','final','yayinda','yayında')) AND NOT ({overdue_sql}) THEN 1 ELSE 0 END) AS pending_count,
          SUM(CASE WHEN NOT ({completed_sql} OR {status_expr} IN ('tamamlandi','tamamlandı','completed','final','yayinda','yayında')) AND ({overdue_sql}) THEN 1 ELSE 0 END) AS overdue_count
        FROM evaluation_assignments ea {where}
        """,
        params,
    )
    values = [0, 0, 0]
    if row:
        values = [_int(row[0].get("completed_count")), _int(row[0].get("pending_count")), _int(row[0].get("overdue_count"))]
    return _chart("period_completion", "Dönem Tamamlama", labels, values, "bars")


def _unit_average(reader: _Reader, period_id: int | None, scope_ids: list[int] | None) -> dict[str, Any]:
    if not reader.has_table("performance_evaluations") or not reader.has_table("users"):
        return _chart("unit_average", "Birim / Grup Ortalaması", [], [], "hbars")
    if not reader.has_col("performance_evaluations", "final_total_100"):
        return _chart("unit_average", "Birim / Grup Ortalaması", [], [], "hbars")
    where = "WHERE pe.final_total_100 IS NOT NULL AND pe.final_total_100 > 0"
    params: dict[str, Any] = {}
    if period_id and reader.has_col("performance_evaluations", "period_id"):
        where += " AND pe.period_id = :period_id"
        params["period_id"] = period_id
    clause, scope_params = _scope_clause("pe", "employee_id", scope_ids)
    where += clause
    params.update(scope_params)
    label_parts = []
    if reader.has_col("users", "ust_birim"):
        label_parts.append("NULLIF(u.ust_birim,'')")
    if reader.has_col("users", "birim"):
        label_parts.append("NULLIF(u.birim,'')")
    if reader.has_col("users", "unit_name"):
        label_parts.append("NULLIF(u.unit_name,'')")
    if reader.has_col("users", "personnel_category"):
        label_parts.append("NULLIF(u.personnel_category,'')")
    label_expr = "COALESCE(" + ", ".join(label_parts + ["'Birim bilgisi yok'"]) + ")"
    rows = reader.rows(
        f"""
        SELECT {label_expr} AS label, ROUND(CAST(AVG(pe.final_total_100) AS NUMERIC), 1) AS avg_score, COUNT(*) AS row_count
        FROM performance_evaluations pe
        JOIN users u ON u.id = pe.employee_id
        {where}
        GROUP BY {label_expr}
        ORDER BY AVG(pe.final_total_100) DESC NULLS LAST, COUNT(*) DESC
        LIMIT 8
        """,
        params,
    )
    labels = [_short(r.get("label"), 26) for r in rows]
    values = [_float(r.get("avg_score")) for r in rows]
    counts = [_int(r.get("row_count")) for r in rows]
    return _chart("unit_average", "Birim / Grup Ortalaması", labels, values, "hbars", counts=counts)


def _category_average(reader: _Reader, period_id: int | None, scope_ids: list[int] | None) -> dict[str, Any]:
    if not reader.has_table("performance_evaluations") or not reader.has_table("users") or not reader.has_col("users", "personnel_category"):
        return _chart("category_average", "Kategori Ortalaması", [], [], "bars")
    where = "WHERE pe.final_total_100 IS NOT NULL AND pe.final_total_100 > 0"
    params: dict[str, Any] = {}
    if period_id and reader.has_col("performance_evaluations", "period_id"):
        where += " AND pe.period_id = :period_id"
        params["period_id"] = period_id
    clause, scope_params = _scope_clause("pe", "employee_id", scope_ids)
    where += clause
    params.update(scope_params)
    rows = reader.rows(
        f"""
        SELECT COALESCE(NULLIF(u.personnel_category,''), 'Diğer') AS label,
               ROUND(CAST(AVG(pe.final_total_100) AS NUMERIC), 1) AS avg_score,
               COUNT(*) AS row_count
        FROM performance_evaluations pe
        JOIN users u ON u.id = pe.employee_id
        {where}
        GROUP BY COALESCE(NULLIF(u.personnel_category,''), 'Diğer')
        ORDER BY AVG(pe.final_total_100) DESC NULLS LAST, COUNT(*) DESC
        LIMIT 8
        """,
        params,
    )
    return _chart(
        "category_average",
        "Kategori Ortalaması",
        [_short(r.get("label"), 20) for r in rows],
        [_float(r.get("avg_score")) for r in rows],
        "bars",
        counts=[_int(r.get("row_count")) for r in rows],
    )


def _low_score_trend(reader: _Reader, scope_ids: list[int] | None) -> dict[str, Any]:
    if not reader.has_table("performance_evaluations") or not reader.has_col("performance_evaluations", "final_total_100"):
        return _chart("low_score_trend", "Düşük Performans Trendi", [], [], "line")
    where = "WHERE pe.final_total_100 IS NOT NULL AND pe.final_total_100 > 0 AND pe.final_total_100 < 70"
    params: dict[str, Any] = {}
    clause, scope_params = _scope_clause("pe", "employee_id", scope_ids)
    where += clause
    params.update(scope_params)
    if not reader.has_col("performance_evaluations", "period_id"):
        return _chart("low_score_trend", "Düşük Performans Trendi", ["Dönem"], [_int(reader.scalar(f"SELECT COUNT(*) FROM performance_evaluations pe {where}", params))], "line")
    period_label = "('Dönem ' || CAST(pe.period_id AS TEXT))"
    join_period = ""
    group_cols = "pe.period_id"
    order_cols = "pe.period_id"
    if reader.has_table("performance_periods"):
        label_col = reader.first_col("performance_periods", ["title", "name", "period_name"], "id")
        period_label = f"COALESCE(CAST(p.{label_col} AS TEXT), 'Dönem ' || CAST(pe.period_id AS TEXT))"
        join_period = "LEFT JOIN performance_periods p ON p.id = pe.period_id"
        group_cols = f"pe.period_id, {period_label}"
        order_cols = "pe.period_id"
    rows = reader.rows(
        f"""
        SELECT {period_label} AS label, COUNT(*) AS row_count
        FROM performance_evaluations pe
        {join_period}
        {where}
        GROUP BY {group_cols}
        ORDER BY {order_cols} ASC
        LIMIT 10
        """,
        params,
    )
    return _chart("low_score_trend", "Düşük Performans Trendi", [_short(r.get("label"), 18) for r in rows], [_int(r.get("row_count")) for r in rows], "line")


_SUPPORT_OPEN = frozenset({"open", "açık", "acik"})
_SUPPORT_PROGRESS = frozenset({"reviewing", "waiting_info", "assigned", "planned", "in_progress", "islemde", "işlemde"})
_SUPPORT_CLOSED = frozenset({"resolved", "closed", "rejected", "completed", "kapalı", "kapali", "çözüldü", "cozuldu"})


def _visible_support_status_counts(reader: _Reader, user: Any) -> dict[str, int]:
    """K5 F4: ticket counts by status, only over the tickets inside ``user``'s scope.

    The support figures follow ``support_ticket_visibility_clause`` (own tickets, plus what an explicit
    ``support_all`` grant opens). A role in ``GLOBAL_ROLES`` or a manager's team scope widens nothing.
    """
    if not reader.has_table("support_tickets"):
        return {}
    try:
        from sqlalchemy import func

        from app.models import SupportTicket
        from app.services.support_ticket_access import support_ticket_visibility_clause

        rows = (
            db.session.query(SupportTicket.status, func.count(SupportTicket.id))
            .filter(support_ticket_visibility_clause(user))
            .group_by(SupportTicket.status)
            .all()
        )
    except Exception as exc:
        current_app.logger.warning("Dashboard destek sayacı güvenli boş döndü: %s", type(exc).__name__)
        db.session.rollback()
        return {}
    counts: dict[str, int] = {}
    for status, total in rows:
        key = str(status or "").strip().lower()
        counts[key] = counts.get(key, 0) + _int(total)
    return counts


def _support_status(reader: _Reader, scope_ids: list[int] | None, user: Any) -> dict[str, Any]:
    labels = ["Açık", "İşlemde", "Kapalı"]
    if not reader.has_table("support_tickets") or not reader.has_col("support_tickets", "status"):
        return _chart("support_status", "Destek Talepleri", labels, [0, 0, 0], "donut")
    counts = _visible_support_status_counts(reader, user)  # K5 F4: scope_ids does not apply here
    values = [
        sum(total for status, total in counts.items() if status in _SUPPORT_OPEN),
        sum(total for status, total in counts.items() if status in _SUPPORT_PROGRESS),
        sum(total for status, total in counts.items() if status in _SUPPORT_CLOSED),
    ]
    return _chart("support_status", "Destek Talepleri", labels, values, "donut")


def _participation(reader: _Reader, user: Any) -> dict[str, Any]:
    survey_total = 0
    survey_done = 0
    feedback_total = 0
    feedback_done = 0
    if reader.has_table("survey_assignments"):
        survey_total = _int(reader.scalar("SELECT COUNT(*) FROM survey_assignments"))
    if reader.has_table("survey_responses"):
        if reader.has_col("survey_responses", "is_completed"):
            survey_done = _int(reader.scalar("SELECT COUNT(*) FROM survey_responses WHERE COALESCE(is_completed, false) = true"))
        else:
            survey_done = _int(reader.scalar("SELECT COUNT(*) FROM survey_responses"))
    if reader.has_table("feedback_campaign_assignments"):
        feedback_total = _int(reader.scalar("SELECT COUNT(*) FROM feedback_campaign_assignments"))
    if reader.has_table("feedback_submissions"):
        if reader.has_col("feedback_submissions", "is_completed"):
            feedback_done = _int(reader.scalar("SELECT COUNT(*) FROM feedback_submissions WHERE COALESCE(is_completed, false) = true"))
        else:
            feedback_done = _int(reader.scalar("SELECT COUNT(*) FROM feedback_submissions"))
    labels = ["Anket katılımı", "Geri bildirim katılımı"]
    values = [_pct(survey_done, survey_total), _pct(feedback_done, feedback_total)]
    return _chart(
        "participation",
        "Anket / Geri Bildirim Katılımı",
        labels,
        values,
        "bars",
        counts=[survey_done, feedback_done],
        totals=[survey_total, feedback_total],
        value_suffix="%",
    )


def _chart(key: str, title: str, labels: list[str], values: list[Any], chart_type: str, **extra: Any) -> dict[str, Any]:
    clean_values = [_float(v) for v in values]
    total = sum(clean_values)
    max_value = max(clean_values) if clean_values else 0
    rows = []
    counts = extra.get("counts") or [None] * len(labels)
    totals = extra.get("totals") or [None] * len(labels)
    for idx, label in enumerate(labels):
        value = clean_values[idx] if idx < len(clean_values) else 0
        rows.append(
            {
                "label": label,
                "value": value,
                "value_display": _format_number(value),
                "percent": _pct(value, total) if chart_type == "donut" else (round((value / max_value) * 100, 1) if max_value else 0),
                "count": counts[idx] if idx < len(counts) else None,
                "total": totals[idx] if idx < len(totals) else None,
            }
        )
    chart = {
        "key": key,
        "title": title,
        "type": chart_type,
        "labels": labels,
        "values": clean_values,
        "rows": rows,
        "total": total,
        "max_value": max_value,
        "empty": total == 0,
        "value_suffix": extra.get("value_suffix", ""),
    }
    chart["line_points"] = _line_points(labels, clean_values)
    chart["gradient"] = _gradient(rows)
    chart.update({k: v for k, v in extra.items() if k not in {"counts", "totals"}})
    return chart


def _format_number(value: Any) -> str:
    number = _float(value)
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return str(round(number, 1)).replace(".", ",")


def _line_points(labels: list[str], values: list[float]) -> str:
    if not labels or not values:
        return "8,86 92,86"
    max_value = max(max(values), 1)
    step = 84 / max(len(values) - 1, 1)
    points = []
    for idx, value in enumerate(values):
        x = 8 + (step * idx)
        y = 86 - ((value / max_value) * 68)
        points.append(f"{round(x, 2)},{round(y, 2)}")
    return " ".join(points)


def _gradient(rows: list[dict[str, Any]]) -> str:
    colors = ["#8B0000", "#b91c1c", "#c2410c", "#2563eb", "#15803d", "#6d28d9"]
    if not rows or sum(_float(r.get("value")) for r in rows) <= 0:
        return "conic-gradient(#e7dada 0deg 360deg)"
    start = 0.0
    parts = []
    for idx, row in enumerate(rows):
        pct = _float(row.get("percent"))
        end = start + pct * 3.6
        if pct > 0:
            parts.append(f"{colors[idx % len(colors)]} {start:.1f}deg {end:.1f}deg")
        start = end
    return "conic-gradient(" + ", ".join(parts) + ")"


def _count_low_processes(reader: _Reader, period_id: int | None, scope_ids: list[int] | None) -> int:
    if not reader.has_table("performance_low_score_processes"):
        return 0
    where = "WHERE 1=1"
    params: dict[str, Any] = {}
    if period_id and reader.has_col("performance_low_score_processes", "period_id"):
        where += " AND p.period_id = :period_id"
        params["period_id"] = period_id
    if reader.has_col("performance_low_score_processes", "employee_id"):
        clause, scope_params = _scope_clause("p", "employee_id", scope_ids)
        where += clause
        params.update(scope_params)
    if reader.has_col("performance_low_score_processes", "president_approved_at"):
        where += " AND p.president_approved_at IS NULL"
    if reader.has_col("performance_low_score_processes", "president_rejected_at"):
        where += " AND p.president_rejected_at IS NULL"
    return _int(reader.scalar(f"SELECT COUNT(*) FROM performance_low_score_processes p {where}", params))


def _count_unread_notifications(reader: _Reader, user: Any) -> int:
    uid = _user_id(user)
    if not uid or not reader.has_table("notifications"):
        return 0
    where = "WHERE n.user_id = :uid"
    if reader.has_col("notifications", "is_read"):
        where += " AND COALESCE(n.is_read, false) = false"
    return _int(reader.scalar(f"SELECT COUNT(*) FROM notifications n {where}", {"uid": uid}))


def _count_support(reader: _Reader, scope_ids: list[int] | None, user: Any, open_only: bool = True) -> int:
    counts = _visible_support_status_counts(reader, user)  # K5 F4: scope_ids does not apply here
    if open_only:
        return sum(total for status, total in counts.items() if status not in _SUPPORT_CLOSED)
    return sum(counts.values())


def _count_open_surveys(reader: _Reader) -> int:
    if not reader.has_table("surveys"):
        return 0
    where = "WHERE 1=1"
    if reader.has_col("surveys", "status"):
        where += " AND LOWER(COALESCE(status,'')) IN ('active','published','open','yayinda','yayında','açık','acik')"
    return _int(reader.scalar(f"SELECT COUNT(*) FROM surveys {where}"))


def _count_open_feedback(reader: _Reader, scope_ids: list[int] | None, user: Any) -> int:
    count = 0
    if reader.has_table("feedback_action_plans"):
        where = "WHERE 1=1"
        params: dict[str, Any] = {}
        if reader.has_col("feedback_action_plans", "status"):
            where += " AND LOWER(COALESCE(status,'')) NOT IN ('resolved','closed','completed','done','kapalı','kapali','tamamlandı','tamamlandi')"
        if scope_ids is not None and reader.has_col("feedback_action_plans", "assigned_manager_id"):
            where += " AND assigned_manager_id IN :scope_ids"
            params["scope_ids"] = scope_ids or ([_user_id(user)] if _user_id(user) else [])
        count += _int(reader.scalar(f"SELECT COUNT(*) FROM feedback_action_plans {where}", params))
    if reader.has_table("feedback_requests"):
        where = "WHERE 1=1"
        params = {}
        if reader.has_col("feedback_requests", "status"):
            where += " AND LOWER(COALESCE(status,'')) NOT IN ('closed','completed','resolved','kapalı','kapali')"
        if scope_ids is not None:
            uid = _user_id(user)
            parts = []
            if reader.has_col("feedback_requests", "created_by_user_id"):
                parts.append("created_by_user_id IN :scope_ids")
            if reader.has_col("feedback_requests", "target_user_id"):
                parts.append("target_user_id IN :scope_ids")
            if reader.has_col("feedback_requests", "employee_id"):
                parts.append("employee_id IN :scope_ids")
            if parts:
                where += " AND (" + " OR ".join(parts) + ")"
                params["scope_ids"] = scope_ids or ([uid] if uid else [])
            else:
                where += " AND 1=0"
        count += _int(reader.scalar(f"SELECT COUNT(*) FROM feedback_requests {where}", params))
    return count


def _pending_assignments(reader: _Reader, period_id: int | None, scope_ids: list[int] | None, evaluator_id: int | None = None) -> int:
    if not reader.has_table("evaluation_assignments"):
        return 0
    cols = reader.columns("evaluation_assignments")
    where = "WHERE 1=1"
    params: dict[str, Any] = {}
    if period_id and "period_id" in cols:
        where += " AND period_id = :period_id"
        params["period_id"] = period_id
    if evaluator_id and "evaluator_id" in cols:
        where += " AND evaluator_id = :evaluator_id"
        params["evaluator_id"] = evaluator_id
    elif "employee_id" in cols:
        clause, scope_params = _scope_clause("ea", "employee_id", scope_ids)
        where += clause
        params.update(scope_params)
    if "completed_at" in cols:
        where += " AND completed_at IS NULL"
    if "status" in cols:
        where += " AND LOWER(COALESCE(status,'')) NOT IN ('tamamlandi','tamamlandı','completed','final','yayinda','yayında')"
    return _int(reader.scalar(f"SELECT COUNT(*) FROM evaluation_assignments ea {where}", params))


def _personal_surveys(reader: _Reader, user: Any) -> int:
    uid = _user_id(user)
    if not uid:
        return 0
    if reader.has_table("survey_assignments") and reader.has_table("survey_responses"):
        # Kullanıcıya doğrudan atanmış veya genel atanmış cevaplanmamış anketler.
        return _int(
            reader.scalar(
                """
                SELECT COUNT(*)
                FROM survey_assignments sa
                LEFT JOIN survey_responses sr ON sr.assignment_id = sa.id AND sr.user_id = :uid AND COALESCE(sr.is_completed, false) = true
                WHERE sr.id IS NULL AND (sa.target_type = 'all' OR (sa.target_type = 'user' AND sa.target_value = :uid_text))
                """,
                {"uid": uid, "uid_text": str(uid)},
            )
        )
    return 0


def _my_support(reader: _Reader, user: Any) -> int:
    uid = _user_id(user)
    if not uid or not reader.has_table("support_tickets") or not reader.has_col("support_tickets", "created_by_user_id"):
        return 0
    where = "WHERE created_by_user_id = :uid"
    if reader.has_col("support_tickets", "status"):
        where += " AND LOWER(COALESCE(status,'')) NOT IN ('resolved','closed','rejected','completed','kapalı','kapali','çözüldü','cozuldu')"
    return _int(reader.scalar(f"SELECT COUNT(*) FROM support_tickets {where}", {"uid": uid}))


def _recent_activity(reader: _Reader, user: Any, scope_ids: list[int] | None) -> list[dict[str, str]]:
    rows_out: list[dict[str, str]] = []
    uid = _user_id(user)
    if uid and reader.has_table("notifications"):
        title_col = "title" if reader.has_col("notifications", "title") else "notification_type"
        body_col = "body" if reader.has_col("notifications", "body") else "notification_type"
        date_col = reader.first_col("notifications", ["created_at", "updated_at", "read_at"], None)
        order = f"ORDER BY {date_col} DESC NULLS LAST" if date_col else "ORDER BY id DESC"
        rows = reader.rows(
            f"SELECT {title_col} AS title, {body_col} AS body FROM notifications WHERE user_id = :uid {order} LIMIT 4",
            {"uid": uid},
        )
        for r in rows:
            rows_out.append({"title": _short(r.get("title"), 36), "body": _short(r.get("body"), 72), "tone": "info"})
    if len(rows_out) < 4 and reader.has_table("performance_low_score_processes"):
        clause, params = _scope_clause("p", "employee_id", scope_ids, prefix=" WHERE ")
        rows = reader.rows(f"SELECT final_total_100 FROM performance_low_score_processes p {clause} ORDER BY id DESC LIMIT {4-len(rows_out)}", params)
        for r in rows:
            rows_out.append({"title": "Düşük performans süreci", "body": f"{_format_number(r.get('final_total_100'))} puanlık kayıt üst onay takibinde.", "tone": "risk"})
    if not rows_out:
        rows_out.append({"title": "Süreç takibi hazır", "body": "Canlı veri oluştukça son bildirim ve süreç hareketleri burada görünür.", "tone": "ok"})
    return rows_out[:4]


def _build_ai_summary(metrics: dict[str, int], charts: dict[str, dict[str, Any]], manager_view: bool) -> dict[str, Any]:
    risks: list[dict[str, str]] = []
    recommendations: list[dict[str, str]] = []
    actions: list[dict[str, str]] = []

    low_count = metrics.get("low_score", 0)
    pending_approval = metrics.get("president_pending", 0)
    pending_tasks = metrics.get("pending_performance", 0)
    support_open = metrics.get("open_support", 0)
    open_feedback = metrics.get("open_feedback", 0)

    if pending_approval:
        risks.append({"title": "Üst onay bekleyen düşük performans", "body": f"{pending_approval} kayıt yayın öncesi üst onay sürecinde bekliyor."})
        actions.append({"label": "Başkan Onayları", "url": "/performance/president-approvals", "priority": "Yüksek"})
    if low_count:
        risks.append({"title": "70 altı performans yoğunluğu", "body": f"Yetki kapsamında {low_count} düşük performans kaydı var; gelişim ve süreç zinciri birlikte izlenmeli."})
        recommendations.append({"title": "Gelişim takibi", "body": "Düşük performans kayıtları için gelişim notu, uyarı/tekrar durumu ve dönem içi gözlemler aynı ekranda kontrol edilmeli."})
    if pending_tasks:
        risks.append({"title": "Bekleyen performans görevleri", "body": f"{pending_tasks} değerlendirme görevi tamamlanmayı bekliyor; dönem kapanışını geciktirebilir."})
        actions.append({"label": "Performans Raporları", "url": "/performance/reports", "priority": "Orta"})
    if support_open:
        risks.append({"title": "Açık destek talepleri", "body": f"{support_open} açık destek talebi kullanıcı deneyimi ve canlı kullanım memnuniyetini etkileyebilir."})
        actions.append({"label": "Destek Talepleri", "url": "/support/tickets", "priority": "Orta"})
    if open_feedback:
        recommendations.append({"title": "Geri bildirim aksiyonları", "body": f"{open_feedback} açık geri bildirim veya eylem planı karar takibine bağlanmalı."})

    participation = charts.get("participation", {})
    low_participation = any(_float(row.get("value")) and _float(row.get("value")) < 60 for row in participation.get("rows", []))
    if low_participation:
        risks.append({"title": "Katılım oranı düşük", "body": "Anket veya geri bildirim katılımı düşük görünüyor; hatırlatma ve duyuru akışı güçlendirilebilir."})

    if not risks:
        risks.append({"title": "Kritik eşik görünmüyor", "body": "Yetki kapsamındaki temel göstergelerde yüksek öncelikli risk oluşmadı."})
    if not recommendations:
        recommendations.append({"title": "Dönem kontrolü", "body": "Veriler güncellendikçe tamamlanma, destek ve katılım eğilimleri birlikte izlenmeli."})
    if not actions:
        actions.append({"label": "Dashboard izleme", "url": "/performance/dashboard", "priority": "Normal"})

    summary = "Dashboard; performans, destek, anket, geri bildirim ve bildirim kayıtlarını yetki sınırı içinde birleştirerek yöneticiye kısa durum resmi sunar."
    if pending_approval or low_count or pending_tasks:
        summary = "Öncelik performans sürecinde: düşük performans, üst onay ve bekleyen değerlendirme görevleri birlikte takip edilmeli."
    elif support_open or open_feedback:
        summary = "Öncelik kullanıcı deneyiminde: destek talepleri ve geri bildirim aksiyonları düzenli kapatılmalı."
    if not manager_view:
        summary = "Bana özel görünüm aktif: yalnızca kendi bekleyen işleriniz, bildirimleriniz ve size açık süreçler özetlenir."

    return {
        "summary": summary,
        "risks": risks[:4],
        "recommendations": recommendations[:4],
        "actions": actions[:4],
        "guardrail": "AI karar vermez; yalnızca yetki kapsamındaki verilerden özet, risk farkındalığı ve öneri sunar.",
    }


def build_dashboard_rebuild_context(user: Any) -> dict[str, Any]:
    reader = _Reader()
    role = _normalize_role(user)
    uid = _user_id(user)
    manager_view = _is_manager(user)
    scope_ids = _resolve_scope_ids(user)
    period = _active_period(reader)
    period_id = _int(period.get("id")) if period else None

    charts = {
        "performance_distribution": _performance_distribution(reader, period_id, scope_ids),
        "period_completion": _period_completion(reader, period_id, scope_ids),
        "unit_average": _unit_average(reader, period_id, scope_ids),
        "category_average": _category_average(reader, period_id, scope_ids),
        "low_score_trend": _low_score_trend(reader, scope_ids),
        "support_status": _support_status(reader, scope_ids, user),
        "participation": _participation(reader, user),
    }

    top_metrics = {
        "total_personnel": _count_users(reader, scope_ids, active_only=False),
        "active_users": _count_users(reader, scope_ids, active_only=True),
        "open_support": _count_support(reader, scope_ids, user, open_only=True),
        "pending_performance": _pending_assignments(reader, period_id, scope_ids),
        "president_pending": _count_low_processes(reader, period_id, scope_ids),
        "unread_notifications": _count_unread_notifications(reader, user),
        "open_surveys": _count_open_surveys(reader),
        "open_feedback": _count_open_feedback(reader, scope_ids, user),
        "low_score": _int(charts["performance_distribution"]["values"][0]) if charts["performance_distribution"].get("values") else 0,
    }

    kpi_cards = [
        {"key": "total_personnel", "label": "Toplam Personel", "value": top_metrics["total_personnel"], "icon": "fa-users", "tone": "red", "note": "Yetki kapsamındaki kayıt"},
        {"key": "active_users", "label": "Aktif Kullanıcı", "value": top_metrics["active_users"], "icon": "fa-user-check", "tone": "green", "note": "Sistemde aktif görünen"},
        {"key": "open_support", "label": "Açık Destek Talebi", "value": top_metrics["open_support"], "icon": "fa-life-ring", "tone": "amber", "note": "Açık / işlemde"},
        {"key": "pending_performance", "label": "Bekleyen Performans Görevi", "value": top_metrics["pending_performance"], "icon": "fa-clipboard-check", "tone": "blue", "note": "Tamamlanmamış görev"},
        {"key": "president_pending", "label": "Üst Onay Bekleyen", "value": top_metrics["president_pending"], "icon": "fa-user-shield", "tone": "danger", "note": "70 altı / yayın kilidi"},
        {"key": "unread_notifications", "label": "Okunmamış Bildirim", "value": top_metrics["unread_notifications"], "icon": "fa-bell", "tone": "violet", "note": "Bana özel"},
        {"key": "open_surveys", "label": "Açık Anket", "value": top_metrics["open_surveys"], "icon": "fa-square-poll-vertical", "tone": "teal", "note": "Yayında olan"},
        {"key": "open_feedback", "label": "Açık Geri Bildirim / Eylem", "value": top_metrics["open_feedback"], "icon": "fa-comments", "tone": "rose", "note": "Kapanmamış aksiyon"},
    ]

    personal = {
        "pending_tasks": _pending_assignments(reader, period_id, scope_ids, evaluator_id=uid),
        "notifications": top_metrics["unread_notifications"],
        "surveys": _personal_surveys(reader, user),
        "support_tickets": _my_support(reader, user),
        "feedback_actions": _count_open_feedback(reader, [uid] if uid else [], user),
    }

    quick_actions = [
        {"label": "Başkan Onayları", "url": "/performance/president-approvals", "icon": "fa-user-shield", "manager_only": True},
        {"label": "Performans Raporları", "url": "/performance/reports", "icon": "fa-chart-column", "manager_only": True},
        {"label": "Personel Yönetimi", "url": "/personnel", "icon": "fa-id-card", "manager_only": True},
        {"label": "Dönem İçi Notlar", "url": "/performance/interim-notes", "icon": "fa-clipboard-list", "manager_only": False},
        {"label": "Gelişim Önerileri", "url": "/performance/meeting-development/faz10", "icon": "fa-seedling", "manager_only": False},
        {"label": "Destek Talepleri", "url": "/support/tickets", "icon": "fa-life-ring", "manager_only": False},
        {"label": "Anket Yönetimi", "url": "/communication/surveys", "icon": "fa-square-poll-vertical", "manager_only": True},
        {"label": "AI Karar Destek Merkezi", "url": "/admin/ai/decision-dashboard", "icon": "fa-brain", "manager_only": True},
    ]
    quick_actions = [item for item in quick_actions if manager_view or not item.get("manager_only")]

    context = {
        "marker": "BYS360_DASHBOARD_REBUILD_V1_OK",
        "generated_at": _now_iso(),
        "user": {"id": uid, "label": _user_label(user), "role": role or "personel", "manager_view": manager_view},
        "scope": {"is_global": scope_ids is None, "count": top_metrics["total_personnel"], "mode_label": "Genel yönetim kapsamı" if scope_ids is None else "Yetki kapsamı"},
        "period": {"id": period_id, "label": str(period.get("label") if period else "Aktif dönem yok"), "range": _period_range(period)},
        "kpi_cards": kpi_cards,
        "metrics": top_metrics,
        "charts": charts,
        "ai": _build_ai_summary(top_metrics, charts, manager_view),
        "personal": personal,
        "quick_actions": quick_actions,
        "recent_activity": _recent_activity(reader, user, scope_ids),
        "empty_note": "Veri oluşmadığında alanlar kaybolmaz; güvenli boş durumla açılır.",
    }
    return context


def build_dashboard_chart_payload(user: Any, chart_key: str) -> dict[str, Any]:
    context = build_dashboard_rebuild_context(user)
    chart = context.get("charts", {}).get(chart_key)
    if not chart:
        return {"ok": False, "chart_key": chart_key, "message": "Grafik anahtarı bulunamadı."}
    return {"ok": True, "chart": chart, "generated_at": context.get("generated_at")}


def build_dashboard_json_payload(user: Any) -> dict[str, Any]:
    context = build_dashboard_rebuild_context(user)
    return {"ok": True, "dashboard": context, "generated_at": context.get("generated_at")}
