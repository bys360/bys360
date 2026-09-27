from __future__ import annotations

from flask import request
from flask_login import current_user, login_required

from app.models import PerformancePeriod
from app.route_registry import main_bp
from app.route_support import admin_required, menu_key_required, safe_render
from app.services.performance.common import get_period
from app.services.performance.core_health_panel import build_core_health_panel_snapshot


@main_bp.route("/performance/core-health", endpoint="performance_core_health")
@main_bp.route("/performans/cekirdek-saglik")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_core_health():
    period = get_period(request.args.get("period_id", type=int))
    snapshot = build_core_health_panel_snapshot(period=period, viewer=current_user)
    periods = snapshot.get("periods") or PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    # The snapshot already carries "periods"; passing it both explicitly and via
    # **snapshot raised "got multiple values for keyword argument" (HTTP 500).
    context = {**snapshot, "periods": periods, "selected_period": snapshot.get("period")}
    return safe_render(
        "performance_core_health.html",
        "<h3>Çekirdek Sağlık Paneli</h3>",
        **context,
    )
