from __future__ import annotations

import logging
from typing import Any, cast

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import asc, desc
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import (
    FeedbackMeeting,
    FeedbackRequest,
    PerformanceEvaluation,
    PerformancePeriod,
    User,
)
from app.performance.feedback_helpers import _meeting_relation_clause, _request_relation_clause
from app.route_registry import main_bp
from app.route_support import (
    ADMIN_FAMILY_ROLES,
    flask_render_template,
    manager_required,
    menu_key_required,
    safe_render,
    user_has_any_role,
)
from app.services.feedback_service import count_feedback_statuses
from app.services.live_surface_service import build_live_report_surface_context
from app.services.pdf_export_guard import validate_inline_pdf_export
from app.services.performance.category_stats import build_category_average_summary_for_users
from app.services.performance.export_service import build_performance_report_excel_download_response
from app.services.performance.phase3_backend_route_guard import (  # BYS360_PHASE3_3_REPORT_BACKEND_IMPORT
    phase3_allowed_employee_ids,
    phase3_can_open_performance_reports,
    phase3_denied_response,
)
from app.services.performance.reporting import attach_report_scores, filter_scope_users_by_query
from app.services.performance_service import (
    build_assignment_log_summary,
    build_assignment_unit_summary,
    get_latest_assignment_generation_logs,
)
from app.services.personnel.categories import (
    get_personnel_category_options,
    normalize_personnel_category_label,
    user_matches_personnel_category,
)
from app.services.sql_refactor_report_helpers import (
    build_period_evaluation_aggregates_sql,
    report_score_expr,
)
from app.view_helpers import build_user_scope_context

"""Phase 45 modular performance reporting route family."""
logger = logging.getLogger(__name__)


def _build_period_stats(visible_periods, filtered_user_ids):
    """Dönem rapor sayaçlarını SQL GROUP BY aggregate ile üretir."""
    period_rows = []
    overall_completed = 0
    overall_total = 0
    overall_score_sum = 0.0
    overall_score_count = 0
    visible_completed_sum = 0
    visible_partial_sum = 0
    visible_pending_sum = 0
    visible_high_score_count = 0
    visible_low_score_count = 0
    visible_log_rows = []

    visible_period_ids = [period.id for period in visible_periods]
    aggregates = build_period_evaluation_aggregates_sql(visible_period_ids, filtered_user_ids)

    for period in visible_periods:
        aggregate = aggregates.get(period.id)
        aggregate_row = aggregate.to_dict() if aggregate else {
            "total_eval": 0,
            "completed_eval": 0,
            "partial_eval": 0,
            "pending_eval": 0,
            "avg_score": 0,
            "score_sum": 0,
            "score_count": 0,
            "high_score_count": 0,
            "low_score_count": 0,
        }
        total_eval = int(aggregate_row.get("total_eval") or 0)
        completed_eval = int(aggregate_row.get("completed_eval") or 0)
        partial_eval = int(aggregate_row.get("partial_eval") or 0)
        pending_eval = int(aggregate_row.get("pending_eval") or 0)
        avg_score = round(float(aggregate_row.get("avg_score") or 0), 2)
        high_score_count = int(aggregate_row.get("high_score_count") or 0)
        low_score_count = int(aggregate_row.get("low_score_count") or 0)
        completion_rate = round((completed_eval / total_eval) * 100, 2) if total_eval else 0

        visible_completed_sum += completed_eval
        visible_partial_sum += partial_eval
        visible_pending_sum += pending_eval
        visible_high_score_count += high_score_count
        visible_low_score_count += low_score_count
        overall_completed += completed_eval
        overall_total += total_eval
        overall_score_sum += float(aggregate_row.get("score_sum") or 0)
        overall_score_count += int(aggregate_row.get("score_count") or 0)

        log_payload = get_latest_assignment_generation_logs(period.id, limit=800, employee_ids=filtered_user_ids)
        period_log_rows = log_payload.get("rows", [])
        period_log_summary = log_payload.get("summary", build_assignment_log_summary([]))
        visible_log_rows.extend(period_log_rows)

        period_rows.append({
            "id": period.id,
            "title": period.title,
            "period_type": period.period_type,
            "start_date": period.start_date,
            "end_date": period.end_date,
            "is_active": bool(period.is_active),
            "results_published": bool(getattr(period, "results_published", False)),
            "is_locked": bool(getattr(period, "is_locked", False)),
            "total_eval": total_eval,
            "completed_eval": completed_eval,
            "partial_eval": partial_eval,
            "pending_eval": pending_eval,
            "avg_score": avg_score,
            "completion_rate": completion_rate,
            "high_score_count": high_score_count,
            "low_score_count": low_score_count,
            "coverage_total_logs": len(period_log_rows),
            "coverage_delegated": period_log_summary.get("delegated", 0),
            "coverage_uncovered": period_log_summary.get("uncovered", 0),
            "coverage_exempted": period_log_summary.get("exempted", 0),
            "coverage_chain_issue": period_log_summary.get("chain_issue", 0),
            "coverage_latest_created_at": log_payload.get("created_at"),
            "coverage_unit_rows": build_assignment_unit_summary(period_log_rows, top_n=3),
        })

    summary = {
        "completion_rate": round((overall_completed / overall_total) * 100, 2) if overall_total else 0,
        "overall_avg_score": round((overall_score_sum / overall_score_count), 2) if overall_score_count else 0,
        "high_score_count": visible_high_score_count,
        "low_score_count": visible_low_score_count,
        "visible_completed_sum": visible_completed_sum,
        "visible_partial_sum": visible_partial_sum,
        "visible_pending_sum": visible_pending_sum,
        "visible_log_rows": visible_log_rows,
    }
    return period_rows, summary


def _resolve_report_scope(raw_scope: str | None, q: str):
    scope = build_user_scope_context(current_user, (raw_scope or "").strip().lower() or None)
    scope_users = scope.get("scope_users", [])
    filtered_users = filter_scope_users_by_query(scope_users, q)
    filtered_user_ids = [user.id for user in filtered_users]
    return scope, filtered_users, filtered_user_ids

def _resolve_report_scope_with_category(raw_scope: str | None, q: str, category: str | None):
    scope, filtered_users, filtered_user_ids = _resolve_report_scope(raw_scope, q)
    phase3_allowed_ids = phase3_allowed_employee_ids(current_user)  # BYS360_PHASE3_3_REPORT_SCOPE_BACKEND_INTERSECTION
    filtered_users = [user for user in filtered_users if getattr(user, "id", None) in phase3_allowed_ids]
    filtered_user_ids = [user.id for user in filtered_users]
    selected_category = normalize_personnel_category_label(category) if (category or "").strip() else ""
    if selected_category:
        filtered_users = [user for user in filtered_users if user_matches_personnel_category(user, selected_category)]
        filtered_user_ids = [user.id for user in filtered_users]
    return scope, filtered_users, filtered_user_ids, selected_category


def _build_report_evaluations(filtered_user_ids, selected_period_id: int | None = None, status: str | None = None):
    query = (
        PerformanceEvaluation.query
        .options(
            joinedload(PerformanceEvaluation.employee),  # type: ignore[arg-type]
            joinedload(PerformanceEvaluation.period),  # type: ignore[arg-type]
        )
        .join(User, PerformanceEvaluation.employee_id == User.id)
        .outerjoin(PerformancePeriod, PerformanceEvaluation.period_id == PerformancePeriod.id)
    )

    if filtered_user_ids:
        query = query.filter(PerformanceEvaluation.employee_id.in_(filtered_user_ids))
    else:
        query = query.filter(PerformanceEvaluation.id == -1)

    if selected_period_id:
        query = query.filter(PerformanceEvaluation.period_id == selected_period_id)

    status = (status or "").strip()
    if status:
        query = query.filter(PerformanceEvaluation.status == status)

    evaluations = query.order_by(
        PerformancePeriod.start_date.desc(),
        PerformanceEvaluation.id.desc(),
    ).all()
    return attach_report_scores(evaluations)


def _build_report_filter_summary(scope, selected_period=None, q: str = "", status: str = "", row_count: int = 0):
    return {
        "scope_label": scope.get("scope_label") or "Kurum geneli",
        "scope_description": scope.get("scope_description") or "Yalnızca yetkili görünüm kapsamındaki personel listelenir.",
        "period_title": getattr(selected_period, "title", None) or "Tüm dönemler",
        "query_text": q or "-",
        "status": status or "Tümü",
        "row_count": row_count,
    }


@main_bp.route("/performance/reports")
@login_required
@manager_required
def performance_reports():
    if not phase3_can_open_performance_reports(current_user):  # BYS360_PHASE3_3_REPORT_PAGE_BACKEND_GUARD
        return phase3_denied_response()
    if user_has_any_role(current_user, {"admin"}):
        return redirect(url_for("main.performance_v2_phase8_dashboard", **cast("dict[str, Any]", request.args.to_dict(flat=True))))

    selected_period_id = request.args.get("period_id", type=int)
    q = (request.args.get("q") or "").strip()
    
    selected_category = (request.args.get("category") or request.args.get("kategori") or "").strip()  # BYS360_PHASE2_4_REPORT_CATEGORY_PARAMselected_category = (request.args.get("category") or request.args.get("kategori") or "").strip()

    periods = (
        PerformancePeriod.query
        .order_by(PerformancePeriod.start_date.desc(), PerformancePeriod.id.desc())
        .all()
    )

    scope, filtered_users, filtered_user_ids, selected_category = _resolve_report_scope_with_category(request.args.get("scope"), q, selected_category)

    visible_periods = periods
    if selected_period_id:
        visible_periods = [period for period in periods if period.id == selected_period_id]

    total_people = len(filtered_users)
    published_period_count = sum(1 for period in periods if bool(getattr(period, "results_published", False)))
    period_rows, period_summary = _build_period_stats(visible_periods, filtered_user_ids)

    top_people = []
    low_people = []
    if filtered_user_ids:
        score_query = PerformanceEvaluation.query.filter(
            PerformanceEvaluation.employee_id.in_(filtered_user_ids),
            PerformanceEvaluation.status == "tamamlandi",
        )
        if selected_period_id:
            score_query = score_query.filter(PerformanceEvaluation.period_id == selected_period_id)

        score_expr = report_score_expr()
        score_query = score_query.options(joinedload(PerformanceEvaluation.employee), joinedload(PerformanceEvaluation.period))  # type: ignore[arg-type]
        top_eval_rows = attach_report_scores(
            score_query.order_by(desc(score_expr), PerformanceEvaluation.id.desc()).limit(5).all()
        )
        low_eval_rows = attach_report_scores(
            score_query.order_by(asc(score_expr), PerformanceEvaluation.id.asc()).limit(5).all()
        )

        top_people = [
            {
                "name": row.employee.full_name if row.employee else "-",
                "birim": row.employee.birim if row.employee else "-",
                "score": float(getattr(row, "report_final_score", 0) or 0),
                "period_title": row.period.title if row.period else "-",
            }
            for row in top_eval_rows
        ]
        low_people = [
            {
                "name": row.employee.full_name if row.employee else "-",
                "birim": row.employee.birim if row.employee else "-",
                "score": float(getattr(row, "report_final_score", 0) or 0),
                "period_title": row.period.title if row.period else "-",
            }
            for row in low_eval_rows
        ]

    coverage_stats = build_assignment_log_summary(period_summary["visible_log_rows"])
    coverage_unit_rows = build_assignment_unit_summary(period_summary["visible_log_rows"], top_n=10)

    category_average_summary = build_category_average_summary_for_users(filtered_user_ids, period_id=selected_period_id, category_label=selected_category)

    stats = {
        "total_people": total_people,
        "total_periods": len(periods),
        "published_period_count": published_period_count,
        "completion_rate": period_summary["completion_rate"],
        "overall_avg_score": period_summary["overall_avg_score"],
        "high_score_count": period_summary["high_score_count"],
        "low_score_count": period_summary["low_score_count"],
        "coverage_exempted": coverage_stats.get("exempted", 0),
        "coverage_uncovered": coverage_stats.get("uncovered", 0),
        "coverage_chain_issue": coverage_stats.get("chain_issue", 0),
        "coverage_delegated": coverage_stats.get("delegated", 0),
    }

    period_rows_chart = list(reversed(period_rows))

    report_surface = build_live_report_surface_context(
        scope=scope,
        stats=stats,
        selected_period=db.session.get(PerformancePeriod, selected_period_id) if selected_period_id else None,
    )

    chart_data = {
        "labels": [row["title"] for row in period_rows_chart],
        "avg_scores": [row["avg_score"] for row in period_rows_chart],
        "completion_rates": [row["completion_rate"] for row in period_rows_chart],
        "completed": [row["completed_eval"] for row in period_rows_chart],
        "partial": [row["partial_eval"] for row in period_rows_chart],
        "pending": [row["pending_eval"] for row in period_rows_chart],
        "top_names": [row["name"] for row in top_people],
        "top_scores": [row["score"] for row in top_people],
        "status_distribution": [
            period_summary["visible_completed_sum"],
            period_summary["visible_partial_sum"],
            period_summary["visible_pending_sum"],
        ],
    }

    return safe_render(
        "reports.html",
        "<h3>Raporlar</h3>",
        stats=stats,
        period_rows=period_rows,
        periods=periods,
        selected_period_id=selected_period_id,
        q=q,
        top_people=top_people,
        low_people=low_people,
        chart_data=chart_data,
        coverage_stats=coverage_stats,
        coverage_unit_rows=coverage_unit_rows,
        report_scope=scope,
        selected_scope_mode=scope.get("scope_mode"),
        selected_category=selected_category,
        category_options=get_personnel_category_options(db.session),
        category_average_summary=category_average_summary,
        report_surface=report_surface,
    )

@main_bp.route("/performance/feedback-reports")
@login_required
@manager_required
@menu_key_required("performance_reports")
def performance_feedback_reports():
    if not user_has_any_role(current_user, ADMIN_FAMILY_ROLES):
        flash("Bu sayfaya erişim yetkiniz yok.", "danger")
        return redirect(url_for("main.dashboard"))

    status_counts = count_feedback_statuses()
    total_feedback_requests = FeedbackRequest.query.count()
    pending_feedback_requests = status_counts.get("bekliyor", 0)
    reviewed_feedback_requests = status_counts.get("incelendi", 0)
    answered_feedback_requests = status_counts.get("cevaplandi", 0)
    closed_feedback_requests = status_counts.get("kapatildi", 0)
    scheduled_feedback_requests = status_counts.get("randevulandi", 0)
    meeting_closed_feedback_requests = status_counts.get("gorusme_tamamlandi", 0)

    total_meetings = FeedbackMeeting.query.count()
    planned_meetings = FeedbackMeeting.query.filter_by(status="planlandi").count()
    completed_meetings = FeedbackMeeting.query.filter_by(status="tamamlandi").count()
    postponed_meetings = FeedbackMeeting.query.filter_by(status="ertelendi").count()
    cancelled_meetings = FeedbackMeeting.query.filter_by(status="iptal_edildi").count()

    # #57: the counters above are totals; the record lists show only the user's own duty relations.
    latest_feedback_requests = (
        FeedbackRequest.query
        .filter(_request_relation_clause(current_user.id))
        .order_by(FeedbackRequest.requested_at.desc(), FeedbackRequest.id.desc())
        .limit(10)
        .all()
    )

    latest_meetings = (
        FeedbackMeeting.query
        .filter(_meeting_relation_clause(current_user.id))
        .order_by(FeedbackMeeting.created_at.desc(), FeedbackMeeting.id.desc())
        .limit(10)
        .all()
    )

    return safe_render(
        "performance_feedback_reports.html",
        "<h3>Geri Bildirim ve Randevu Raporları</h3>",
        total_feedback_requests=total_feedback_requests,
        pending_feedback_requests=pending_feedback_requests,
        reviewed_feedback_requests=reviewed_feedback_requests,
        answered_feedback_requests=answered_feedback_requests,
        closed_feedback_requests=closed_feedback_requests,
        scheduled_feedback_requests=scheduled_feedback_requests,
        meeting_closed_feedback_requests=meeting_closed_feedback_requests,
        total_meetings=total_meetings,
        planned_meetings=planned_meetings,
        completed_meetings=completed_meetings,
        postponed_meetings=postponed_meetings,
        cancelled_meetings=cancelled_meetings,
        latest_feedback_requests=latest_feedback_requests,
        latest_meetings=latest_meetings,
    )


@main_bp.route("/performance/reports/export/excel")
@login_required
@manager_required
def performance_reports_export_excel():
    if not phase3_can_open_performance_reports(current_user):  # BYS360_PHASE3_3_REPORT_EXCEL_BACKEND_GUARD
        return phase3_denied_response()
    selected_period_id = request.args.get("period_id", type=int)
    q = (request.args.get("q") or "").strip()

    selected_category = (request.args.get("category") or request.args.get("kategori") or "").strip()
    scope, filtered_users, filtered_user_ids, selected_category = _resolve_report_scope_with_category(request.args.get("scope"), q, selected_category)
    evaluations = _build_report_evaluations(filtered_user_ids, selected_period_id)
    return build_performance_report_excel_download_response(evaluations)


@main_bp.route("/performance/reports/export/pdf")
@login_required
@manager_required
def performance_reports_export_pdf():
    if not phase3_can_open_performance_reports(current_user):  # BYS360_PHASE3_3_REPORT_PDF_BACKEND_GUARD
        return phase3_denied_response()
    selected_period_id = request.args.get("period_id", type=int)
    q = (request.args.get("q") or "").strip()

    (
        PerformancePeriod.query
        .order_by(PerformancePeriod.start_date.desc(), PerformancePeriod.id.desc())
        .all()
    )

    selected_category = (request.args.get("category") or request.args.get("kategori") or "").strip()
    scope, filtered_users, filtered_user_ids, selected_category = _resolve_report_scope_with_category(request.args.get("scope"), q, selected_category)
    selected_period = db.session.get(PerformancePeriod, selected_period_id) if selected_period_id else None
    evaluations = _build_report_evaluations(filtered_user_ids, selected_period_id)
    filter_summary = _build_report_filter_summary(
        scope,
        selected_period=selected_period,
        q=q,
        row_count=len(evaluations),
    )
    ok, pdf_message = validate_inline_pdf_export(len(evaluations), label="Performans raporu PDF")
    if not ok:
        flash(pdf_message, "warning")
        return redirect(url_for("main.performance_reports", period_id=selected_period_id, q=q, category=selected_category))

    return flask_render_template(
        "reports_pdf.html",
        evaluations=evaluations,
        filter_summary=filter_summary,
    )

@main_bp.route("/performance/reports/print")
@login_required
@manager_required
def performance_reports_print():
    if not phase3_can_open_performance_reports(current_user):  # BYS360_PHASE3_3_REPORT_PRINT_BACKEND_GUARD
        return phase3_denied_response()
    if not user_has_any_role(current_user, ADMIN_FAMILY_ROLES):
        flash("Bu işlem için yetkiniz yok.", "danger")
        return redirect(url_for("main.dashboard"))

    period_id = request.args.get("period_id", type=int)
    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()

    periods = (
        PerformancePeriod.query
        .order_by(PerformancePeriod.start_date.desc(), PerformancePeriod.id.desc())
        .all()
    )
    selected_category = (request.args.get("category") or request.args.get("kategori") or "").strip()
    scope, filtered_users, filtered_user_ids, selected_category = _resolve_report_scope_with_category(request.args.get("scope"), q, selected_category)
    selected_period = db.session.get(PerformancePeriod, period_id) if period_id else None
    evaluations = _build_report_evaluations(filtered_user_ids, period_id, status=status)
    filter_summary = _build_report_filter_summary(
        scope,
        selected_period=selected_period,
        q=q,
        status=status,
        row_count=len(evaluations),
    )
    report_surface = build_live_report_surface_context(
        scope=scope,
        stats={"row_count": len(evaluations)},
        selected_period=selected_period,
    )

    return safe_render(
        "performance_reports_print.html",
        "<h3>Yazdırılabilir Performans Raporu</h3>",
        evaluations=evaluations,
        periods=periods,
        selected_period_id=period_id,
        q=q,
        selected_scope_mode=scope.get("scope_mode"),
        report_surface=report_surface,
        selected_status=status,
        filter_summary=filter_summary,
    )


# BYS360_PHASE2_4_REPORT_CATEGORY_FILTER_READY

# BYS360_PERFORMANCE_COMPLETION_PHASE2_REPORT_CATEGORY_FILTER_MARKER
# Performans raporlarında kategori filtresi Faz 2 kategori merkezinin kalıcı sözleşmesine bağlıdır.
try:
    from app.services.performance.phase2_category_center import (
        PHASE2_CATEGORY_CENTER_VERSION as PHASE2_CATEGORY_CENTER_VERSION,
    )
except Exception:
    logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
    PHASE2_CATEGORY_CENTER_VERSION = "performance-completion-phase2-category-center-unavailable"

