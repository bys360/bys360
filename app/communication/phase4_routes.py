from __future__ import annotations

import logging

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_REQUIRED
# STATUS_SOURCE: app.communication.route_manifest REQUIRED_ROUTE_MODULES
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2, orphan-auth-key
# closure): two menu keys this file used were never declared in
# MENU_SECTIONS, so every route using them 403'd for every role including
# admin. "support" (communication_phase4_support_analytics) is a duplicate
# of the already-registered "support_all" capability (same SupportTicket
# data) -- repointed to reuse it. "reports" (dashboard/reports/export-
# center/governance/metrics-refresh) had no existing equivalent; registered
# it as a new menu item using this file's own pre-authored, never-wired
# app/templates/communication/phase4_base_menu_snippet.txt for its label/
# icon ("İletişim Faz 4 Paneli") and this file's own is_manager()/
# MANAGER_ROLES check (communication_phase4_service.py) for its
# required_roles -- not invented.
from io import BytesIO

from flask import flash, redirect, request, send_file, session, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.communication_phase4_service import (
    REPORT_STATUS_LABELS,
    CommunicationPhase4Error,
    create_executive_report,
    decide_governance,
    executive_summary_snapshot,
    export_center_snapshot,
    export_rows_csv,
    governance_snapshot,
    is_manager,
    refresh_daily_metrics,
    report_history_snapshot,
    sanitize_days,
    submit_report_for_review,
    support_analytics_snapshot,
    survey_analytics_snapshot,
)

logger = logging.getLogger(__name__)


_ALLOWED_EXPORT_TYPES = {"survey_analytics", "support_analytics", "executive_reports", "daily_metrics"}
_EXPORT_RATE_LIMIT_SECONDS = 12


def _export_rate_limit_key() -> str:
    user_id = getattr(current_user, "id", None) or "anonymous"
    return f"communication_phase4_export_at_{user_id}"


def _can_run_export_now() -> bool:
    import time

    now_ts = int(time.time())
    key = _export_rate_limit_key()
    last_ts = int(session.get(key, 0) or 0)
    if last_ts and (now_ts - last_ts) < _EXPORT_RATE_LIMIT_SECONDS:
        return False
    session[key] = now_ts
    session.modified = True
    return True


def _read_days(default: int = 30) -> int:
    raw = request.args.get("days")
    if raw in (None, ""):
        raw = request.form.get("days")
    return sanitize_days(raw, default=default)


@main_bp.route("/communication/faz4")
@login_required
@menu_key_required("reports")
def communication_phase4_dashboard_view():
    if not is_manager(current_user):
        flash("Bu ekran yönetici görünümü için tasarlanmıştır.", "warning")
    days = _read_days(30)
    payload = executive_summary_snapshot(days, viewer=current_user)  # K5: viewer-scoped ticket rows
    return safe_render("communication/phase4_dashboard.html", payload=payload)


@main_bp.route("/communication/faz4/reports")
@login_required
@menu_key_required("reports")
def communication_phase4_reports_view():
    days = _read_days(30)
    payload = executive_summary_snapshot(days, viewer=current_user)  # K5: viewer-scoped ticket rows
    history = report_history_snapshot(25)
    return safe_render("communication/phase4_reports.html", payload=payload, history=history)


@main_bp.route("/communication/faz4/reports/create", methods=["POST"])
@login_required
@menu_key_required("reports")
def communication_phase4_report_create():
    days = _read_days(30)
    try:
        row = create_executive_report(
            current_user,
            report_type=request.form.get("report_type") or "weekly_summary",
            days=days,
        )
        flash("Yönetici özeti oluşturuldu.", "success")
        return redirect(url_for("main.communication_phase4_report_detail", report_id=row.id))
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase4_routes.py | line=96 | exc=%s", exc)
        flash("Rapor oluşturulamadı.", "danger")
        return redirect(url_for("main.communication_phase4_reports_view", days=days))


@main_bp.route("/communication/faz4/reports/<int:report_id>")
@login_required
@menu_key_required("reports")
def communication_phase4_report_detail(report_id: int):
    from app.models.communication_phase4_models import CommunicationExecutiveReport

    row = CommunicationExecutiveReport.query.get_or_404(report_id)
    return safe_render("communication/phase4_report_detail.html", row=row, status_labels=REPORT_STATUS_LABELS)


@main_bp.route("/communication/faz4/reports/<int:report_id>/submit-review", methods=["POST"])
@login_required
@menu_key_required("reports")
def communication_phase4_submit_review(report_id: int):
    try:
        submit_report_for_review(report_id, current_user, note=request.form.get("note") or "")
        flash("Rapor incelemeye gönderildi.", "success")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase4_routes.py | line=118 | exc=%s", exc)
        flash("İncelemeye gönderilemedi.", "danger")
    return redirect(url_for("main.communication_phase4_report_detail", report_id=report_id))


@main_bp.route("/communication/faz4/surveys/analytics")
@login_required
@menu_key_required("surveys")
def communication_phase4_survey_analytics():
    days = _read_days(180)
    payload = survey_analytics_snapshot(days)
    return safe_render("communication/phase4_survey_analytics.html", payload=payload)


@main_bp.route("/communication/faz4/support/analytics")
@login_required
@menu_key_required("support_all")
def communication_phase4_support_analytics():
    days = _read_days(180)
    payload = support_analytics_snapshot(days, viewer=current_user)  # K5: viewer-scoped ticket rows
    return safe_render("communication/phase4_support_analytics.html", payload=payload)


@main_bp.route("/communication/faz4/export-center")
@login_required
@menu_key_required("reports")
def communication_phase4_export_center():
    days = _read_days(90)
    payload = export_center_snapshot(days)
    return safe_render("communication/phase4_export_center.html", payload=payload)


@main_bp.route("/communication/faz4/export", methods=["POST"])
@login_required
@menu_key_required("reports")
def communication_phase4_export():
    export_type = (request.form.get("export_type") or "survey_analytics").strip().lower()
    days = _read_days(180)
    if export_type not in _ALLOWED_EXPORT_TYPES:
        flash("Geçersiz dışa aktarma tipi seçildi.", "warning")
        return redirect(url_for("main.communication_phase4_export_center", days=days))
    if not _can_run_export_now():
        flash("Dışa aktarma işlemini çok sık tetiklediniz. Birkaç saniye sonra yeniden deneyin.", "warning")
        return redirect(url_for("main.communication_phase4_export_center", days=days))
    try:
        file_name, content, row_count = export_rows_csv(current_user, export_type, days=days)
        flash(f"{row_count} satırlık dışa aktarma hazırlandı.", "success")
        return send_file(
            BytesIO(content),
            mimetype="text/csv; charset=utf-8-sig",
            as_attachment=True,
            download_name=file_name,
        )
    except CommunicationPhase4Error as exc:
        flash(str(exc), "warning")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase4_routes.py | line=173 | exc=%s", exc)
        flash("Dışa aktarma üretilemedi.", "danger")
    return redirect(url_for("main.communication_phase4_export_center", days=days))


@main_bp.route("/communication/faz4/governance")
@login_required
@menu_key_required("reports")
def communication_phase4_governance():
    payload = governance_snapshot()
    return safe_render("communication/phase4_governance.html", payload=payload)


@main_bp.route("/communication/faz4/governance/<int:review_id>/decide", methods=["POST"])
@login_required
@menu_key_required("reports")
def communication_phase4_governance_decide(review_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase4_governance"))

    try:
        decide_governance(
            review_id,
            current_user,
            decision=request.form.get("decision") or "pending",
            note=request.form.get("note") or "",
        )
        flash("Yönetişim kararı kaydedildi.", "success")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase4_routes.py | line=202 | exc=%s", exc)
        flash("Karar kaydedilemedi.", "danger")
    return redirect(url_for("main.communication_phase4_governance"))


@main_bp.route("/communication/faz4/metrics/refresh", methods=["POST"])
@login_required
@menu_key_required("reports")
def communication_phase4_metrics_refresh():
    try:
        changed = refresh_daily_metrics(current_user)
        flash(f"{changed} günlük metrik kaydı güncellendi.", "success")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase4_routes.py | line=214 | exc=%s", exc)
        flash("Metrikler güncellenemedi.", "danger")
    return redirect(request.referrer or url_for("main.communication_phase4_dashboard_view"))
