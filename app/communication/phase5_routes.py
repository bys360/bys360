from __future__ import annotations

import logging

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_REQUIRED
# STATUS_SOURCE: app.communication.route_manifest REQUIRED_ROUTE_MODULES
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2, orphan-auth-key
# closure): same two-key gap as phase4_routes.py. "support"
# (support-operations, escalations) reads/writes the same SupportTicket/
# SupportTicketStatusHistory data as the already-registered "support_all"
# key -- repointed to reuse it. "reports" (health, audit-logs) shares the
# new "reports" registration added for phase4_routes.py's dashboard/
# reports/governance surface (see that file's own note) -- registered
# once, consumed by both.
from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.communication_phase5_service import (
    CommunicationPhase5Error,
    audit_logs_snapshot,
    automation_center_snapshot,
    create_digest_job,
    create_or_update_escalation_rule,
    create_or_update_retention_policy,
    ensure_default_phase5_data,
    escalation_snapshot,
    health_snapshot,
    is_manager,
    notification_preferences_snapshot,
    refresh_operation_health,
    retention_snapshot,
    support_operations_snapshot,
    update_notification_preferences,
)

logger = logging.getLogger(__name__)


@main_bp.route("/communication/faz5")
@login_required
@menu_key_required("settings")
def communication_phase5_dashboard_view():
    payload = {
        "automation": automation_center_snapshot(),
        "health": health_snapshot(),
        "retention": retention_snapshot(),
        "support_ops": support_operations_snapshot(viewer=current_user),  # K5: viewer-scoped rows
    }
    return safe_render("communication/phase5_dashboard.html", payload=payload)


@main_bp.route("/communication/faz5/automation-center")
@login_required
@menu_key_required("settings")
def communication_phase5_automation_center():
    payload = automation_center_snapshot()
    return safe_render("communication/phase5_automation_center.html", payload=payload)


@main_bp.route("/communication/faz5/automation-center/bootstrap", methods=["POST"])
@login_required
@menu_key_required("settings")
def communication_phase5_bootstrap_defaults():
    created = ensure_default_phase5_data()
    flash(f"Varsayılan işletim verileri kontrol edildi. Yeni kurallar={created['rules']} | politikalar={created['policies']}", "success")
    return redirect(url_for("main.communication_phase5_automation_center"))


@main_bp.route("/communication/faz5/preferences", methods=["GET", "POST"])
@login_required
@menu_key_required("settings")
def communication_phase5_preferences():
    if request.method == "POST":
        update_notification_preferences(current_user, request.form)
        flash("Bildirim tercihleri güncellendi.", "success")
        return redirect(url_for("main.communication_phase5_preferences"))
    payload = notification_preferences_snapshot(current_user)
    return safe_render("communication/phase5_preferences.html", payload=payload)


@main_bp.route("/communication/faz5/preferences/digest", methods=["POST"])
@login_required
@menu_key_required("settings")
def communication_phase5_create_digest():
    digest_type = (request.form.get("digest_type") or "daily").strip().lower()
    create_digest_job(current_user, digest_type=digest_type)
    flash("Özet kaydı oluşturuldu.", "success")
    return redirect(url_for("main.communication_phase5_preferences"))


@main_bp.route("/communication/faz5/support-operations")
@login_required
@menu_key_required("support_all")
def communication_phase5_support_operations():
    payload = support_operations_snapshot(viewer=current_user)  # K5: viewer-scoped rows
    return safe_render("communication/phase5_support_operations.html", payload=payload)


@main_bp.route("/communication/faz5/escalations")
@login_required
@menu_key_required("support_all")
def communication_phase5_escalations():
    if not is_manager(current_user):
        flash("Bu ekran yönetici kullanımına yöneliktir.", "warning")
    payload = escalation_snapshot(viewer=current_user)  # K5: viewer-scoped rows
    return safe_render("communication/phase5_escalation_center.html", payload=payload)


@main_bp.route("/communication/faz5/escalations/save", methods=["POST"])
@login_required
@menu_key_required("support_all")
def communication_phase5_save_escalation_rule():
    try:
        create_or_update_escalation_rule(current_user, request.form)
        flash("SLA/escalation kuralı kaydedildi.", "success")
    except CommunicationPhase5Error as exc:
        flash(str(exc), "danger")
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase5_routes.py | line=111")
        flash("Kural kaydedilirken bir hata oluştu.", "danger")
    return redirect(url_for("main.communication_phase5_escalations"))


@main_bp.route("/communication/faz5/retention")
@login_required
@menu_key_required("settings")
def communication_phase5_retention():
    payload = retention_snapshot()
    return safe_render("communication/phase5_retention_center.html", payload=payload)


@main_bp.route("/communication/faz5/retention/save", methods=["POST"])
@login_required
@menu_key_required("settings")
def communication_phase5_save_retention_policy():
    try:
        create_or_update_retention_policy(current_user, request.form)
        flash("Saklama politikası kaydedildi.", "success")
    except CommunicationPhase5Error as exc:
        flash(str(exc), "danger")
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase5_routes.py | line=133")
        flash("Saklama politikası kaydedilirken bir hata oluştu.", "danger")
    return redirect(url_for("main.communication_phase5_retention"))


@main_bp.route("/communication/faz5/health")
@login_required
@menu_key_required("reports")
def communication_phase5_health():
    payload = health_snapshot()
    return safe_render("communication/phase5_operational_health.html", payload=payload)


@main_bp.route("/communication/faz5/health/refresh", methods=["POST"])
@login_required
@menu_key_required("reports")
def communication_phase5_refresh_health():
    count = refresh_operation_health(current_user)
    flash(f"Operasyon sağlığı yenilendi. {count} kayıt eklendi.", "success")
    return redirect(url_for("main.communication_phase5_health"))


@main_bp.route("/communication/faz5/audit-logs")
@login_required
@menu_key_required("reports")
def communication_phase5_audit_logs():
    payload = audit_logs_snapshot(
        100,
        status_filter=request.args.get("status") or "",
        action_filter=request.args.get("action") or "",
    )
    return safe_render("communication/phase5_audit_logs.html", payload=payload)
