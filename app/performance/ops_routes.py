"""Performans operasyon merkezi route'u.

Tek endpoint: /performance/operations-center
Türkçe alias: /performans/operasyon-merkezi
"""
from __future__ import annotations

from flask import request
from flask_login import current_user, login_required

from app.models import PerformancePeriod
from app.route_registry import main_bp
from app.route_support import admin_required, menu_key_required, safe_render
from app.services.performance.common import get_period
from app.services.performance.ops_center import build_performance_operations_snapshot
from app.view_helpers import build_surface_scope_context  # doğru kaynak


@main_bp.route("/performance/operations-center", endpoint="performance_operations_center")
@main_bp.route("/performans/operasyon-merkezi")          # alias — endpoint adı aynı fonksiyona bağlı
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_operations_center():
    period = get_period(request.args.get("period_id", type=int))
    scope_ctx = build_surface_scope_context(current_user, request.args.get("scope")) or {}
    snapshot = build_performance_operations_snapshot(
        period=period,
        viewer=current_user,
        scope_user_ids=scope_ctx.get("employee_ids"),
    ) or {}
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    # The snapshot already carries "period"; passing it both explicitly and via
    # **snapshot raised "got multiple values for keyword argument" (HTTP 500).
    context = {
        **snapshot,
        "period": period,
        "periods": periods,
        "selected_scope": scope_ctx.get("selected_scope"),
        "scope_options": scope_ctx.get("scope_options"),
        "scope_option_pairs": scope_ctx.get("scope_option_pairs"),
        "scope_label": scope_ctx.get("scope_label"),
        "scope_role_title": scope_ctx.get("role_title"),
        "scope_user_count": scope_ctx.get("scope_user_count", 0),
        "scope_unit_count": scope_ctx.get("scope_unit_count", 0),
    }
    return safe_render(
        "performance_operations_center.html",
        "<h3>Performans Operasyon Merkezi</h3>",
        **context,
    )