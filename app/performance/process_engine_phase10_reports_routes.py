from __future__ import annotations

import logging
from typing import Any

from flask import abort, render_template, request
from flask_login import current_user, login_required

from app.routes import main
from app.services.performance.process_engine_phase8_tracking import (
    can_view_process_tracking,
    process_flow_scope_clause,
)

logger = logging.getLogger(__name__)
@main.route("/performans/surec-raporlari", methods=["GET"])
@main.route("/performance/process-reports", methods=["GET"])
@login_required
def performance_process_reports():
    # P0-01: same gate as the sibling Süreç Takibi page and the menu registry
    # entry; a direct URL must not bypass it.
    if not can_view_process_tracking(current_user):
        abort(403)
    status_filter = request.args.get('status') or request.args.get('status_filter') or ''
    context = _bys360_process_reports_advanced_context(viewer=current_user, status_filter=status_filter)
    return render_template('performance/process_reports_advanced.html', **context)

    # BYS360_V55_DEAD_CODE_CLEANUP: return sonrası erişilemeyen eski Faz 10 kodu kaldırıldı.

# BYS360_PROCESS_REPORTS_ADVANCED_V2_BEGIN
def _bys360_process_reports_advanced_context(viewer=None, status_filter=None):
    from sqlalchemy import text as _sql_text

    from app.extensions import db

    def _rows(sql, params=None):
        try:
            return list(db.session.execute(_sql_text(sql), params or {}).mappings())
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return []

    def _table_exists(table_name):
        # BYS360 DEFECT AL: raw dialect-branched information_schema/sqlite_master
        # query replaced with SQLAlchemy's inspect(), which is dialect-neutral
        # by construction.
        try:
            from sqlalchemy import inspect as _sa_inspect

            return bool(_sa_inspect(db.session.get_bind()).has_table(table_name))
        except Exception:
            logger.exception(
                "BYS360 process reports table_exists guvenli fallback | table=%s",
                table_name,
            )
            return False

    def _table_columns(table_name):
        try:
            from sqlalchemy import inspect as _sa_inspect

            return {col["name"] for col in _sa_inspect(db.session.get_bind()).get_columns(table_name)}
        except Exception:
            logger.exception(
                "BYS360 process reports table_columns guvenli fallback | table=%s",
                table_name,
            )
            return set()

    table_exists = _table_exists("performance_process_flows")

    if not table_exists:
        return {
            "summary": {},
            "status_rows": [],
            "owner_rows": [],
            "recent_rows": [],
            "president_rows": [],
            "status_filter": status_filter or "",
        }

    # BYS360 DEFECT AN: this whole context builder referenced a wide set of
    # performance_process_flows columns (is_overdue, president_required,
    # tracking_label, tracking_status, current_owner_name,
    # current_owner_user_id, waiting_days, last_action_title,
    # tracking_priority, president_status, president_requested_at,
    # updated_by_engine_at) that no migration and no reachable runtime
    # schema path ever creates -- confirmed against a real, migration-built
    # database. The broad try/except in _rows() above meant every one of
    # these queries failed silently, always rendering an empty/all-zero
    # report page instead of raising. Each ghost reference is gated with a
    # real-schema check below; current_owner_user_id/president_required map
    # to their real, canonical equivalents (current_owner_id/
    # president_approval_required). CONCAT_WS()/::numeric are also
    # PostgreSQL-only with no SQLite equivalent -- replaced with the
    # ANSI-portable ``||`` operator and a plain ROUND(), since the column
    # fix alone would still leave these queries failing on SQLite.
    flow_cols = _table_columns("performance_process_flows")

    def _flow_expr(name, real_name=None):
        candidate = real_name or name
        return f"f.{candidate}" if candidate in flow_cols else "NULL"

    is_overdue_expr = _flow_expr("is_overdue")
    president_required_expr = _flow_expr("president_required", "president_approval_required")
    tracking_label_expr = _flow_expr("tracking_label")
    tracking_status_expr = _flow_expr("tracking_status")
    current_owner_name_expr = _flow_expr("current_owner_name")
    current_owner_id_expr = _flow_expr("current_owner_id")
    waiting_days_expr = _flow_expr("waiting_days")
    last_action_title_expr = _flow_expr("last_action_title")
    tracking_priority_expr = _flow_expr("tracking_priority")
    president_status_expr = _flow_expr("president_status")
    president_requested_at_expr = _flow_expr("president_requested_at")
    updated_by_engine_at_expr = _flow_expr("updated_by_engine_at")
    owner_join = f"LEFT JOIN users owner ON owner.id = {current_owner_id_expr}" if current_owner_id_expr != "NULL" else ""
    owner_name_from_join = (
        "TRIM(COALESCE(owner.ad, '') || ' ' || COALESCE(owner.soyad, ''))" if owner_join else "NULL"
    )
    emp_name_from_join = "TRIM(COALESCE(emp.ad, '') || ' ' || COALESCE(emp.soyad, ''))"

    # P0-01: rows are limited to the viewer's canonical process-flow scope
    # (admin/başkan unrestricted, others own or owned flows, unresolved -> none).
    scope_sql, scope_params = process_flow_scope_clause(viewer)
    where = f"WHERE 1=1 {scope_sql}"
    params: dict[str, Any] = dict(scope_params)

    if status_filter == "pending":
        where += " AND COALESCE(f.is_finalized, FALSE) = FALSE"
    elif status_filter == "overdue":
        where += f" AND COALESCE({is_overdue_expr}, FALSE) = TRUE"
    elif status_filter == "president":
        where += f" AND COALESCE({president_required_expr}, FALSE) = TRUE"
    elif status_filter == "finalized":
        where += " AND COALESCE(f.is_finalized, FALSE) = TRUE"

    summary_rows = _rows(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE(f.is_finalized, FALSE) = FALSE THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN COALESCE({is_overdue_expr}, FALSE) = TRUE THEN 1 ELSE 0 END) AS overdue,
            SUM(CASE WHEN COALESCE({president_required_expr}, FALSE) = TRUE THEN 1 ELSE 0 END) AS president_required,
            SUM(CASE WHEN COALESCE(f.is_finalized, FALSE) = TRUE THEN 1 ELSE 0 END) AS finalized
        FROM performance_process_flows f
        {where}
    """, params)

    raw_summary = dict(summary_rows[0]) if summary_rows else {}
    total = int(raw_summary.get("total") or 0)

    summary = {
        "total": total,
        "pending": int(raw_summary.get("pending") or 0),
        "overdue": int(raw_summary.get("overdue") or 0),
        "president_required": int(raw_summary.get("president_required") or 0),
        "finalized": int(raw_summary.get("finalized") or 0),
    }

    status_data = _rows(f"""
        SELECT
            COALESCE(NULLIF({tracking_label_expr}, ''), NULLIF(f.current_status, ''), 'Süreçte') AS label,
            COALESCE(NULLIF({tracking_status_expr}, ''), NULLIF(f.current_status, ''), 'process') AS status,
            COUNT(*) AS count
        FROM performance_process_flows f
        {where}
        GROUP BY 1, 2
        ORDER BY COUNT(*) DESC, 1
        LIMIT 12
    """, params)

    status_rows = []
    for row in status_data:
        count = int(row.get("count") or 0)
        percent = int(round((count / total) * 100)) if total else 0
        status_rows.append({
            "label": row.get("label"),
            "status": row.get("status"),
            "count": count,
            "percent": percent,
        })

    owner_rows = _rows(f"""
        SELECT
            COALESCE(
                NULLIF({owner_name_from_join}, ''),
                NULLIF({current_owner_name_expr}, ''),
                'Sorumlu belirtilmedi'
            ) AS owner_name,
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE({is_overdue_expr}, FALSE) = TRUE THEN 1 ELSE 0 END) AS overdue,
            ROUND(AVG(COALESCE({waiting_days_expr}, 0)), 1) AS avg_waiting_days
        FROM performance_process_flows f
        {owner_join}
        {where}
        GROUP BY 1
        ORDER BY
            SUM(CASE WHEN COALESCE({is_overdue_expr}, FALSE) = TRUE THEN 1 ELSE 0 END) DESC,
            COUNT(*) DESC
        LIMIT 12
    """, params)

    recent_rows = _rows(f"""
        SELECT
            f.id AS flow_id,
            COALESCE(NULLIF({emp_name_from_join}, ''), 'Personel') AS employee_name,
            COALESCE(NULLIF({owner_name_from_join}, ''), NULLIF({current_owner_name_expr}, ''), '-') AS owner_name,
            COALESCE(NULLIF({tracking_label_expr}, ''), NULLIF(f.current_status, ''), 'Süreçte') AS status_label,
            COALESCE(NULLIF({last_action_title_expr}, ''), '-') AS last_action_title,
            COALESCE({waiting_days_expr}, 0) AS waiting_days,
            COALESCE({is_overdue_expr}, FALSE) AS is_overdue,
            COALESCE(f.is_finalized, FALSE) AS is_finalized,
            COALESCE(NULLIF({tracking_priority_expr}, ''), 'Normal') AS priority_label
        FROM performance_process_flows f
        LEFT JOIN users emp ON emp.id = f.employee_id
        {owner_join}
        {where}
        ORDER BY
            COALESCE({is_overdue_expr}, FALSE) DESC,
            COALESCE({waiting_days_expr}, 0) DESC,
            COALESCE(f.last_action_at, {updated_by_engine_at_expr}, f.created_at, CURRENT_TIMESTAMP) DESC
        LIMIT 60
    """, params)

    president_rows = _rows(f"""
        SELECT
            f.id AS flow_id,
            COALESCE(NULLIF({emp_name_from_join}, ''), 'Personel') AS employee_name,
            COALESCE(NULLIF({owner_name_from_join}, ''), NULLIF({current_owner_name_expr}, ''), '-') AS owner_name,
            f.final_score,
            COALESCE(NULLIF(f.president_approval_status, ''), NULLIF({president_status_expr}, ''), 'Üst Onay Bekliyor') AS president_status_label,
            COALESCE(NULLIF({last_action_title_expr}, ''), '-') AS last_action_title,
            COALESCE({waiting_days_expr}, 0) AS waiting_days
        FROM performance_process_flows f
        LEFT JOIN users emp ON emp.id = f.employee_id
        {owner_join}
        {where}
          AND COALESCE({president_required_expr}, FALSE) = TRUE
        ORDER BY
            COALESCE({waiting_days_expr}, 0) DESC,
            COALESCE({president_requested_at_expr}, f.created_at, CURRENT_TIMESTAMP) DESC
        LIMIT 40
    """, params)

    return {
        "summary": summary,
        "status_rows": [dict(r) for r in status_rows],
        "owner_rows": [dict(r) for r in owner_rows],
        "recent_rows": [dict(r) for r in recent_rows],
        "president_rows": [dict(r) for r in president_rows],
        "status_filter": status_filter or "",
    }
# BYS360_PROCESS_REPORTS_ADVANCED_V2_END

# BYS360_PERFORMANCE_COMPLETION_PHASE7_SCORECARD_ARCHIVE_BOUND
# Geçmiş yıl karne/puan arşivi phase7_scorecard_archive_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE11_REPORTING_RISK_BOUND
# Raporlama, dashboard ve risk analizi phase11_reporting_risk_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE12_FINAL_READINESS_BOUND
# Final gate, 10 senaryo testi ve canlı hazırlık phase12_final_readiness_policy sözleşmesini kullanır.
