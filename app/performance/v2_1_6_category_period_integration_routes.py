from __future__ import annotations

import logging

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import admin_required, safe_render
from app.security.critical_operations import critical_action_refusal
from app.services.performance.v2_1_5_category_period_scope import list_category_period_scope_plans
from app.services.performance.v2_1_6_category_period_integration import (
    build_assignment_preintegration,
    create_or_update_period_from_plan,
    ensure_category_period_integration_schema,
    integration_summary,
    list_integrations,
    list_preintegration_rows,
)
from app.services.performance.v2_1_6_category_period_integration_gate import (
    run_v2_1_6_category_period_integration_gate,
)
from app.services.performance.v2_1_6a_category_ui_cleanup import corporate_gate_label, label_status

logger = logging.getLogger(__name__)


@main_bp.route("/performance/v2-1-6-category-period-integration", methods=["GET", "POST"])
@login_required
@admin_required
def performance_v2_1_6_category_period_integration():
    # P0: plandan gerçek dönem oluşturma ve etkinleştirme sabit rol sınırına tabidir; kontrol
    # şema hazırlığı dahil hiçbir işlemden önce yapılır.
    if request.method == "POST" and (request.form.get("action") or "link_period") == "link_period":
        refusal = critical_action_refusal("period_manage", "performance_periods")
        if refusal is None and request.form.get("activate_period"):
            refusal = critical_action_refusal("period_activate", "performance_periods")
        if refusal is not None:
            return refusal
    ensure_category_period_integration_schema()
    if request.method == "POST":
        action = request.form.get("action") or "link_period"
        plan_key = request.form.get("plan_key") or ""
        try:
            if action == "link_period":
                result = create_or_update_period_from_plan(
                    plan_key,
                    created_by=getattr(current_user, "id", None),
                    activate_period=bool(request.form.get("activate_period")),
                )
                if result.get("ok"):
                    flash(f"Plan performans dönemine bağlandı: {result.get('period_title')}", "success")
                else:
                    flash(result.get("message") or "Dönem bağlantısı oluşturulamadı.", "warning")
            elif action == "precheck":
                period_id = request.form.get("period_id") or None
                result = build_assignment_preintegration(plan_key, int(period_id) if period_id else None, write=True)
                if result.get("ok"):
                    summary = result.get("summary") or {}
                    flash(f"Ön kontrol tamamlandı. Hazır: {summary.get('ready', 0)}, kontrol gereken: {summary.get('needs_manager_review', 0)}, kapsam uyumsuz: {summary.get('scope_mismatch', 0)}", "success")
                else:
                    flash(result.get("message") or "Ön kontrol tamamlanamadı.", "warning")
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            flash("Dönem entegrasyonu tamamlanamadı.", "danger")
        return redirect(url_for("main.performance_v2_1_6_category_period_integration", plan=plan_key))

    selected_plan = request.args.get("plan") or ""
    integrations = list_integrations()
    selected_integration = next((i for i in integrations if i.get("plan_key") == selected_plan), None) if selected_plan else None
    period_id_int = int(selected_integration.get("period_id") or 0) if selected_integration else None
    return safe_render(
        "performance/v2_1_6_category_period_integration.html",
        page_title="Kategori Dönem Bağlantısı",
        plans=list_category_period_scope_plans(include_inactive=False),
        integrations=integrations,
        selected_plan=selected_plan,
        selected_integration=selected_integration,
        pre_rows=list_preintegration_rows(selected_plan, period_id_int, limit=150) if selected_plan else [],
        summary=integration_summary(),
        gate=run_v2_1_6_category_period_integration_gate(),
        label_status=label_status,
        corporate_gate_label=corporate_gate_label,
    )
