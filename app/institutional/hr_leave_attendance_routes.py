from __future__ import annotations

import logging

from app.institutional.hr_common import (
    build_hr_attendance_ai_panel,
    build_hr_leave_ai_panel,
)
from app.institutional.hr_form_helpers import (
    AttendanceException,
    DelegationAssignment,
    LeaveBalance,
    PersonnelLeave,
    _create_delegation_from_form,
    _handle_attendance_post,
    _handle_leave_balance_post,
    _handle_leave_post,
    _handle_manual_delegation_post,
)
from app.institutional.hr_scope_helpers import (
    ACTIVE_STATUSES,
    ATTENDANCE_TYPE_CHOICES,
    DELEGATION_SCOPE_CHOICES,
    DELEGATION_STATUS_CHOICES,
    LEAVE_STATUS_CHOICES,
    LEAVE_TYPE_CHOICES,
    LEGACY_NOTE,
    LEGACY_ROUTE_FAMILY,
    LEGACY_RUNTIME_STATUS,
    LEGACY_SHIM,
    PENDING_STATUSES,
    PERFORMANCE_MODE_LABELS,
    Any,
    BuildError,
    Iterable,
    Response,
    SimpleNamespace,
    _active_delegation_exists,
    _active_period,
    _all_personnel,
    _attendance_overlaps,
    _attendance_type_label,
    _bool_from_form,
    _calculate_leave_day_count,
    _count_rows,
    _current_user_id,
    _date_range_weekday_count,
    _delegation_health,
    _delegation_status_label,
    _empty_overview,
    _endpoint_registered,
    _fallback_scope_context,
    _filter_users_in_scope,
    _full_name,
    _hr_scope_context,
    _leave_date_range_label,
    _leave_duration_label,
    _leave_overlaps,
    _leave_overview,
    _leave_status_label,
    _leave_type_label,
    _model_ready,
    _parse_date,
    _performance_mode_label,
    _period_options,
    _profile_missing_fields,
    _profile_score,
    _query_rows,
    _requested_scope_mode,
    _resolve_period_id_from_form,
    _role_key,
    _safe_commit,
    _safe_float,
    _safe_import,
    _safe_int,
    _safe_text,
    _scope_bundle,
    _scope_label,
    _scope_user_ids,
    _selected_period_id,
    _selected_user_guard,
    _selected_user_id,
    _status_label,
    _table_exists,
    _unit_name,
    _unit_pulse,
    _url_or_hash,
    consume_form_token,
    csv,
    current_app,
    current_user,
    date,
    datetime,
    db,
    flash,
    import_module,
    inspect,
    io,
    issue_form_token,
    jsonify,
    login_required,
    main_bp,
    manager_required,
    menu_key_required,
    or_,
    redirect,
    request,
    safe_db_rollback,
    safe_render,
    timedelta,
    url_for,
    utc_now,
)
from app.services.ui_context.scope import build_user_scope_context

logger = logging.getLogger(__name__)


# BYS360 V1E2: lazy export bridge for split HR report helper
def _export_simple_report(filename: str, context: dict[str, Any]) -> Response:
    from app.institutional.hr_reports_routes import (
        _export_simple_report as _real_export_simple_report,
    )

    return _real_export_simple_report(filename, context)

def _leave_page_context() -> dict[str, Any]:
    hr_scope, scope_users, scope_user_ids = _scope_bundle()
    selected_scope_mode = hr_scope.get("scope_mode") or "personal"
    selected_user_id = _selected_user_id()
    selected_period_id = _selected_period_id()
    active_period = _active_period()
    effective_period = next((p for p in _period_options() if getattr(p, "id", None) == selected_period_id), None) or active_period
    overview = _leave_overview()
    health = _delegation_health(getattr(effective_period, "id", None))
    leaves = _query_rows(PersonnelLeave, scope_user_ids=scope_user_ids, date_field="start_date", limit=80)
    balances = _query_rows(LeaveBalance, scope_user_ids=scope_user_ids, date_field="id", limit=80)
    delegations = []
    if _model_ready(DelegationAssignment):
        try:
            q = DelegationAssignment.query
            if scope_user_ids:
                q = q.filter(or_(DelegationAssignment.delegator_user_id.in_(scope_user_ids), DelegationAssignment.delegate_user_id.in_(scope_user_ids)))
            delegations = q.order_by(DelegationAssignment.start_date.desc(), DelegationAssignment.id.desc()).limit(80).all()
        except Exception:
            safe_db_rollback()
    selected_user_guard = _selected_user_guard(selected_user_id, effective_period)
    leave_ai_panel = {"headline": "İzin ve vekâlet özeti", "bullets": list(getattr(overview, "notes", []) or [])[:4], "tone": "calm"}
    if build_hr_leave_ai_panel is not None:
        try:
            leave_ai_panel = build_hr_leave_ai_panel(summary=getattr(overview, "summary", {}) or {}, period=effective_period, scope_label=hr_scope.get("scope_label"))
        except Exception:
            safe_db_rollback()
    return {
        "hr_scope": hr_scope,
        "selected_scope_mode": selected_scope_mode,
        "scope_label": hr_scope.get("scope_label") or "Kapsam",
        "scope_heading": hr_scope.get("scope_heading") or "Kapsam",
        "scope_description": hr_scope.get("scope_description") or "",
        "scope_options": hr_scope.get("scope_options") or [],
        "scope_user_count": len(scope_users),
        "users": scope_users,
        "delegate_candidates": scope_users,
        "periods": _period_options(),
        "active_period": active_period,
        "effective_period": effective_period,
        "selected_period_id": selected_period_id,
        "selected_user_id": selected_user_id,
        "selected_user_guard": selected_user_guard,
        "leave_overview": overview,
        "delegation_health": health,
        "leave_ai_panel": leave_ai_panel,
        "leaves": leaves,
        "balances": balances,
        "active_delegations": delegations,
        "leave_type_choices": LEAVE_TYPE_CHOICES,
        "leave_status_choices": LEAVE_STATUS_CHOICES,
        "performance_mode_label": _performance_mode_label,
        "leave_type_label": _leave_type_label,
        "leave_status_label": _leave_status_label,
        "delegation_status_label": _delegation_status_label,
        "delegation_scope_label": _scope_label,
        "leave_date_range_label": _leave_date_range_label,
        "leave_duration_label": _leave_duration_label,
        "leave_create_submit_token": issue_form_token("hr_management", scope="leave_create"),
        "leave_balance_submit_token": issue_form_token("hr_management", scope="leave_balance"),
        "can_view_ai_admin": False,
        "leave_action_rows": [],
        "leave_pressure_rows": [],
        "exemption_candidates": [],
        "today": date.today(),
    }


@main_bp.route("/hr-management/leave", methods=["GET", "POST"])
@main_bp.route("/hr-management/leaves", methods=["GET", "POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_leave_management():
    if request.method == "POST":
        return _handle_leave_post()
    return safe_render("hr_leave.html", **_leave_page_context())


def _attendance_page_context() -> dict[str, Any]:
    ctx = _leave_page_context()
    hr_scope = ctx["hr_scope"]
    scope_users = ctx["users"]
    scope_user_ids = [int(u.id) for u in scope_users if getattr(u, "id", None)]
    attendance_rows = _query_rows(AttendanceException, scope_user_ids=scope_user_ids, date_field="record_date", limit=80)
    delegations = ctx.get("active_delegations") or []
    attendance_ai_panel = {"headline": "Devamsızlık ve vekâlet özeti", "bullets": list((ctx.get("delegation_health") or {}).get("notes") or [])[:4], "tone": "calm"}
    if build_hr_attendance_ai_panel is not None:
        try:
            attendance_ai_panel = build_hr_attendance_ai_panel(summary=ctx.get("delegation_health") or {}, period=ctx.get("effective_period"), scope_label=hr_scope.get("scope_label"))
        except Exception:
            safe_db_rollback()
    ctx.update({
        "attendance_rows": attendance_rows,
        "delegations": delegations,
        "attendance_ai_panel": attendance_ai_panel,
        "attendance_type_choices": ATTENDANCE_TYPE_CHOICES,
        "attendance_type_label": _attendance_type_label,
        "delegation_scope_choices": DELEGATION_SCOPE_CHOICES,
        "delegation_status_choices": DELEGATION_STATUS_CHOICES,
        "attendance_create_submit_token": issue_form_token("hr_management", scope="attendance_create"),
        "delegation_create_submit_token": issue_form_token("hr_management", scope="delegation_create"),
        "attendance_action_rows": [],
        "attendance_pressure_rows": [],
        "attendance_sources": attendance_rows,
        "leave_sources": ctx.get("leaves") or [],
        "active_delegation_count": len(delegations),
        "pending_delegation_count": sum(1 for row in delegations if _safe_text(getattr(row, "status", None)).lower() in PENDING_STATUSES),
        "expiring_count": sum(1 for row in delegations if getattr(row, "end_date", None) and row.end_date <= date.today() + timedelta(days=7)),
        "uncovered_count": int(((ctx.get("delegation_health") or {}).get("coverage_summary") or {}).get("uncovered") or 0),
    })
    return ctx


@main_bp.route("/hr-management/attendance", methods=["GET", "POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_attendance_management():
    if request.method == "POST":
        return _handle_attendance_post()
    return safe_render("hr_attendance.html", **_attendance_page_context())


@main_bp.route("/hr-management/leave/ai-report")
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_leave_ai_report_export():
    return _export_simple_report("izin_ve_vekalet_raporu", _leave_page_context())


@main_bp.route("/hr-management/attendance/ai-report")
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_attendance_ai_report_export():
    return _export_simple_report("devamsizlik_ve_vekalet_raporu", _attendance_page_context())


def _row_in_caller_scope(row: Any) -> bool:
    """The record's person is in the caller's widest scope (the population the management pages list)."""
    scope_ids = set(build_user_scope_context(current_user, "all").get("scope_user_ids") or [])
    owner_ids = {getattr(row, name, None) for name in ("user_id", "delegator_user_id", "delegate_user_id")}
    return bool(scope_ids & owner_ids)


def _set_status(model: Any, row_id: int, status: str, redirect_endpoint: str) -> Any:
    if not _model_ready(model):
        flash("İlgili tablo hazır değil.", "warning")
        return redirect(url_for(redirect_endpoint))
    try:
        row = db.session.get(model, int(row_id))
        if not row:
            flash("Kayıt bulunamadı.", "warning")
        elif not _row_in_caller_scope(row):
            flash("Bu kayıt yetki kapsamınız dışında.", "danger")
        else:
            row.status = status
            db.session.add(row)
            db.session.commit()
            flash("Durum güncellendi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Durum güncellenemedi.", "danger")
    return redirect(url_for(redirect_endpoint, scope=request.form.get("scope") or request.args.get("scope") or "personal"))


def _delete_row(model: Any, row_id: int, redirect_endpoint: str) -> Any:
    if not _model_ready(model):
        flash("İlgili tablo hazır değil.", "warning")
        return redirect(url_for(redirect_endpoint))
    try:
        row = db.session.get(model, int(row_id))
        if row and not _row_in_caller_scope(row):
            flash("Bu kayıt yetki kapsamınız dışında.", "danger")
        elif row:
            db.session.delete(row)
            db.session.commit()
            flash("Kayıt silindi.", "success")
        else:
            flash("Kayıt bulunamadı.", "warning")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Kayıt silinemedi.", "danger")
    return redirect(url_for(redirect_endpoint, scope=request.form.get("scope") or request.args.get("scope") or "personal"))


@main_bp.route("/hr-management/leave/<int:leave_id>/status", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_leave_update_status(leave_id: int):
    return _set_status(PersonnelLeave, leave_id, _safe_text(request.form.get("status"), "onaylandi"), "main.hr_leave_management")


@main_bp.route("/hr-management/leave/<int:leave_id>/delete", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_leave_delete(leave_id: int):
    return _delete_row(PersonnelLeave, leave_id, "main.hr_leave_management")


@main_bp.route("/hr-management/attendance/<int:attendance_id>/status", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_attendance_update_status(attendance_id: int):
    return _set_status(AttendanceException, attendance_id, _safe_text(request.form.get("status"), "onaylandi"), "main.hr_attendance_management")


@main_bp.route("/hr-management/attendance/<int:attendance_id>/delete", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_attendance_delete(attendance_id: int):
    return _delete_row(AttendanceException, attendance_id, "main.hr_attendance_management")


@main_bp.route("/hr-management/delegations/<int:delegation_id>/status", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_delegation_update_status(delegation_id: int):
    return _set_status(DelegationAssignment, delegation_id, _safe_text(request.form.get("status"), "aktif"), "main.hr_attendance_management")


@main_bp.route("/hr-management/delegations/<int:delegation_id>/delete", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_delegation_delete(delegation_id: int):
    return _delete_row(DelegationAssignment, delegation_id, "main.hr_attendance_management")

__all__ = [
    "annotations",
    "build_hr_attendance_ai_panel",
    "build_hr_leave_ai_panel",
    "AttendanceException",
    "DelegationAssignment",
    "LeaveBalance",
    "PersonnelLeave",
    "_create_delegation_from_form",
    "_handle_leave_post",
    "_handle_leave_balance_post",
    "_handle_attendance_post",
    "_handle_manual_delegation_post",
    "utc_now",
    "date",
    "datetime",
    "timedelta",
    "import_module",
    "SimpleNamespace",
    "Any",
    "Iterable",
    "csv",
    "io",
    "Response",
    "current_app",
    "flash",
    "jsonify",
    "redirect",
    "request",
    "url_for",
    "current_user",
    "login_required",
    "inspect",
    "or_",
    "BuildError",
    "db",
    "main_bp",
    "consume_form_token",
    "issue_form_token",
    "manager_required",
    "menu_key_required",
    "safe_db_rollback",
    "safe_render",
    "LEGACY_SHIM",
    "LEGACY_RUNTIME_STATUS",
    "LEGACY_ROUTE_FAMILY",
    "LEGACY_NOTE",
    "LEAVE_TYPE_CHOICES",
    "LEAVE_STATUS_CHOICES",
    "ATTENDANCE_TYPE_CHOICES",
    "DELEGATION_SCOPE_CHOICES",
    "DELEGATION_STATUS_CHOICES",
    "PERFORMANCE_MODE_LABELS",
    "ACTIVE_STATUSES",
    "PENDING_STATUSES",
    "_safe_import",
    "_endpoint_registered",
    "_url_or_hash",
    "_table_exists",
    "_model_ready",
    "_safe_text",
    "_safe_int",
    "_safe_float",
    "_current_user_id",
    "_safe_commit",
    "_resolve_period_id_from_form",
    "_date_range_weekday_count",
    "_calculate_leave_day_count",
    "_active_delegation_exists",
    "_leave_overlaps",
    "_attendance_overlaps",
    "_bool_from_form",
    "_active_period",
    "_parse_date",
    "_status_label",
    "_scope_label",
    "_leave_type_label",
    "_attendance_type_label",
    "_performance_mode_label",
    "_full_name",
    "_unit_name",
    "_role_key",
    "_profile_missing_fields",
    "_profile_score",
    "_period_options",
    "_selected_period_id",
    "_selected_user_id",
    "_all_personnel",
    "_requested_scope_mode",
    "_fallback_scope_context",
    "_hr_scope_context",
    "_scope_user_ids",
    "_filter_users_in_scope",
    "_scope_bundle",
    "_empty_overview",
    "_leave_overview",
    "_delegation_health",
    "_query_rows",
    "_count_rows",
    "_selected_user_guard",
    "_unit_pulse",
    "_export_simple_report",
    "_leave_page_context",
    "hr_leave_management",
    "_attendance_page_context",
    "hr_attendance_management",
    "hr_leave_ai_report_export",
    "hr_attendance_ai_report_export",
    "_set_status",
    "_delete_row",
    "hr_leave_update_status",
    "hr_leave_delete",
    "hr_attendance_update_status",
    "hr_attendance_delete",
    "hr_delegation_update_status",
    "hr_delegation_delete",
]
