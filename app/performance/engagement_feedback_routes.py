from __future__ import annotations

import logging
from datetime import datetime

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import FeedbackMeeting, FeedbackRequest, PerformancePeriod
from app.route_registry import main_bp
from app.route_support import manager_required, menu_key_required, safe_render
from app.services.ai.dashboard_panels import (
    build_feedback_meetings_ai_panel,
    build_feedback_requests_ai_panel,
    build_feedback_schedule_ai_panel,
)
from app.services.feedback_service import (
    can_create_feedback_request,
    get_feedback_evaluation,
    get_feedback_meeting,
    get_feedback_meeting_status_label,
    get_feedback_request_status_label,
    get_feedback_response_text,
    get_open_feedback_request,
    persist_feedback_response,
)
from app.services.mail_service import (
    send_feedback_meeting_created_mail,
    send_feedback_meeting_status_update_mail,
    send_feedback_request_mail,
    send_feedback_response_mail,
)
from app.services.performance.common import get_period
from app.services.performance.feedback_alert_service import (
    build_feedback_alert_dashboard,
    dispatch_feedback_alerts,
)
from app.services.performance.feedback_audit_service import (
    build_feedback_audit_dashboard,
    get_feedback_meeting_timeline,
    get_feedback_request_timeline,
    record_feedback_audit_event,
)
from app.services.performance.feedback_executive_summary_service import (
    SUMMARY_PRESET_LABELS,
    build_feedback_executive_summary,
    dispatch_feedback_executive_summary,
)
from app.services.performance.feedback_ops_service import (
    build_feedback_operations_dashboard,
    build_feedback_schedule_preview,
)
from app.services.performance.final_pack_service import (
    build_go_live_smoke_report,
    export_go_live_management_brief_txt,
    export_go_live_smoke_csv,
)
from app.services.performance.go_live_service import build_performance_go_live_center
from app.services.performance.uat_service import (
    build_go_live_uat_report,
    export_go_live_issues_csv,
    export_go_live_release_packet_txt,
    export_go_live_uat_txt,
)
from app.services.pilot_execution_service import build_pilot_execution_context
from app.services.pilot_readiness_service import build_pilot_readiness_context

from .feedback_helpers import (
    _feedback_manager_ids,
    _find_feedback_meeting_conflict,
    _get_scope_context,
    _load_scoped_feedback_data,
    _meeting_visible_to_user,
    _notify_feedback_meeting_created,
    _notify_feedback_meeting_updated,
    _notify_feedback_request_created,
    _notify_feedback_request_status_changed,
    _record_feedback_digest_audit,
    _record_meeting_alert_audit,
    _record_request_alert_audit,
    _resolve_feedback_managers,
    _scope_render_kwargs,
    _serialize_feedback_meeting_state,
    _serialize_feedback_request_state,
)

logger = logging.getLogger(__name__)
"""Performans geri bildirim, görüşme ve audit route ailesi."""

@main_bp.route("/performance/feedback-request/<int:period_id>", methods=["GET", "POST"])
@login_required
def performance_feedback_request(period_id):
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return redirect(url_for("main.dashboard"))

    employee = current_user
    evaluation = get_feedback_evaluation(period.id, employee.id)
    allowed, deny_message = can_create_feedback_request(period, evaluation)
    if not allowed:
        flash(deny_message or "Bu dönem için geri bildirim talebi açılamaz.", "warning")
        return redirect(url_for("main.performance_scorecard", period_id=period.id))

    existing_request = get_open_feedback_request(period.id, employee.id)
    if existing_request:
        flash("Bu dönem için zaten açık bir geri bildirim talebiniz bulunuyor.", "warning")
        return redirect(url_for("main.manager_feedback_request_detail", request_id=existing_request.id, scope="mine"))

    if request.method == "POST":
        reason = (request.form.get("reason") or "").strip()
        if not reason:
            flash("Açıklama yazmalısınız.", "warning")
            return redirect(request.url)

        level_1_manager, level_2_manager, level_3_manager = _resolve_feedback_managers(
            employee,
            evaluation=evaluation,
            period_id=period.id,
        )

        if not any([level_1_manager, level_2_manager, level_3_manager]):
            flash("Bu personel için geri bildirim talebini iletecek amir zinciri bulunamadı.", "danger")
            return redirect(url_for("main.performance_scorecard", period_id=period.id))

        feedback = FeedbackRequest(
            evaluation_id=evaluation.id,
            period_id=period.id,
            employee_id=employee.id,
            level_1_manager_id=level_1_manager.id if level_1_manager else None,
            level_2_manager_id=level_2_manager.id if level_2_manager else None,
            level_3_manager_id=level_3_manager.id if level_3_manager else None,
            reason=reason,
            status="bekliyor",
        )

        db.session.add(feedback)
        db.session.flush()
        current_app.logger.info(
            "Feedback talebi oluşturuldu | request_id=%s employee_id=%s period_id=%s managers=%s/%s/%s",
            feedback.id,
            employee.id,
            period.id,
            getattr(level_1_manager, 'id', None),
            getattr(level_2_manager, 'id', None),
            getattr(level_3_manager, 'id', None),
        )
        _notify_feedback_request_created(feedback)
        record_feedback_audit_event(
            entity_type="feedback_request",
            entity_id=feedback.id,
            action="feedback_request_created",
            actor_user_id=current_user.id,
            summary=f"{employee.ad} {employee.soyad} geri bildirim talebi oluşturdu.",
            new_data=_serialize_feedback_request_state(feedback),
        )
        db.session.commit()
        mail_result = send_feedback_request_mail(feedback)
        if int(mail_result.get("failed_count", 0) or 0) > 0:
            flash("Talebiniz sisteme düştü ancak bazı e-posta bildirimleri gönderilemedi. Uygulama içi bildirim oluşturuldu.", "warning")
        else:
            flash("Talebiniz amirlerinize iletilmiştir.", "success")
        return redirect(url_for("main.manager_feedback_request_detail", request_id=feedback.id, scope="mine"))

    return safe_render("performance_feedback_request.html", "<h3>Geri Bildirim Talebi</h3>", period=period, evaluation=evaluation)


@main_bp.route("/performance/feedback-requests")
@login_required
def manager_feedback_requests():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()

    query = FeedbackRequest.query.options(
        joinedload(FeedbackRequest.employee),  # type: ignore[arg-type]
        joinedload(FeedbackRequest.period),  # type: ignore[arg-type]
    )
    if selected_scope == "mine":
        query = query.filter(
            (FeedbackRequest.level_1_manager_id == current_user.id)
            | (FeedbackRequest.level_2_manager_id == current_user.id)
            | (FeedbackRequest.level_3_manager_id == current_user.id)
            | (FeedbackRequest.employee_id == current_user.id)
        )
    elif scope_employee_ids:
        query = query.filter(FeedbackRequest.employee_id.in_(scope_employee_ids))

    requests_list = query.order_by(FeedbackRequest.requested_at.desc(), FeedbackRequest.id.desc()).limit(120).all()
    return safe_render(
        "manager_feedback_requests.html",
        "<h3>Geri Bildirim Talepleri</h3>",
        requests=requests_list,
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        ai_feedback_requests_panel=build_feedback_requests_ai_panel(requests_list, current_user=current_user),
    )


@main_bp.route("/performance/feedback-ops")
@login_required
@menu_key_required("performance_feedback_meetings")
def feedback_operations_dashboard():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    dashboard = build_feedback_operations_dashboard(
        requests_list,
        meetings,
        today=utc_now().date(),
    )

    return safe_render(
        "feedback_operations_dashboard.html",
        "<h3>Geri Bildirim Operasyon Paneli</h3>",
        **_scope_render_kwargs(scope_ctx),
        **dashboard,
    )


@main_bp.route("/performance/feedback-watch")
@login_required
@menu_key_required("performance_feedback_meetings")
def feedback_watch_dashboard():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    dashboard = build_feedback_alert_dashboard(
        requests_list,
        meetings,
        today=utc_now().date(),
    )
    return safe_render(
        "feedback_watch_dashboard.html",
        "<h3>Takip ve Uyarı Paneli</h3>",
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        **dashboard,
    )


@main_bp.route("/performance/feedback-watch/run-alerts", methods=["POST"])
@login_required
@manager_required  # K13: the operation keeps its own role check; a menu row or exception never triggers it
@menu_key_required("performance_feedback_meetings")
def feedback_watch_run_alerts():
    scope_value = (request.form.get("scope") or request.args.get("scope") or "").strip()
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context(scope_value)
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    send_mail = str(request.form.get("send_email") or "").strip().lower() in {"1", "true", "on", "yes", "evet"}
    try:
        result = dispatch_feedback_alerts(
            requests_list,
            meetings,
            actor_user_id=current_user.id,
            send_mail=send_mail,
            request_audit_callback=_record_request_alert_audit,
            meeting_audit_callback=_record_meeting_alert_audit,
        )
        db.session.commit()
        flash(
            (
                f"Takip uyarıları çalıştırıldı. Talep hatırlatması: {result['request_reminder_notifications']}, "
                f"talep SLA uyarısı: {result['request_sla_notifications']}, "
                f"görüşme hatırlatması: {result['meeting_reminder_notifications']}, "
                f"görüşme gecikme uyarısı: {result['meeting_overdue_notifications']}."
            ),
            "success",
        )
        if send_mail and result.get("email_failed_count"):
            flash(f"Bazı e-postalar gönderilemedi: {result['email_failed_count']}. Uygulama içi bildirimler yine üretildi.", "warning")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Faz 6 takip uyarıları çalıştırılamadı: %s", exc)
        flash("Takip uyarıları çalıştırılırken hata oluştu.", "danger")
    return redirect(url_for("main.feedback_watch_dashboard", scope=selected_scope))


@main_bp.route("/performance/feedback-executive-summary")
@login_required
@menu_key_required("performance_feedback_meetings")
def feedback_executive_summary_dashboard():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    preset = (request.args.get("preset") or "daily").strip().lower()
    if preset not in SUMMARY_PRESET_LABELS:
        preset = "daily"
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    dashboard = build_feedback_executive_summary(
        requests_list,
        meetings,
        preset=preset,
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        now=utc_now(),
    )
    return safe_render(
        "feedback_executive_summary_dashboard.html",
        "<h3>Yönetici Özet Merkezi</h3>",
        selected_scope=selected_scope,
        # `preset` is intentionally NOT passed explicitly here: `dashboard`
        # (from build_feedback_executive_summary) already carries the same
        # resolved/validated preset string under its own "preset" key.
        # Passing it twice raised `TypeError: safe_render() got multiple
        # values for keyword argument 'preset'`.
        preset_options=[{"value": key, "label": value} for key, value in SUMMARY_PRESET_LABELS.items() if key in {"daily", "weekly"}],
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        **dashboard,
    )


@main_bp.route("/performance/feedback-executive-summary/run-digest", methods=["POST"])
@login_required
@manager_required  # K13: the operation keeps its own role check; a menu row or exception never triggers it
@menu_key_required("performance_feedback_meetings")
def feedback_executive_summary_run_digest():
    scope_value = (request.form.get("scope") or request.args.get("scope") or "").strip()
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context(scope_value)
    preset = (request.form.get("preset") or request.args.get("preset") or "daily").strip().lower()
    if preset not in SUMMARY_PRESET_LABELS:
        preset = "daily"
    send_mail = str(request.form.get("send_email") or "").strip().lower() in {"1", "true", "on", "yes", "evet"}
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    try:
        result = dispatch_feedback_executive_summary(
            requests_list,
            meetings,
            preset=preset,
            actor_user_id=current_user.id,
            scope_label=scope_ctx.get("scope_label"),
            scope_role_title=scope_ctx.get("role_title"),
            send_mail=send_mail,
            now=utc_now(),
        )
        _record_feedback_digest_audit(
            source_id=int(result.get("source_id") or 0),
            preset=preset,
            actor_user_id=current_user.id,
            recipient_count=int(result.get("recipient_count") or 0),
            mail_success_count=int(result.get("mail_success_count") or 0),
        )
        db.session.commit()
        flash(
            (
                f"{SUMMARY_PRESET_LABELS.get(preset, 'Bilinmiyor')} yönetici özeti çalıştırıldı. "
                f"Bildirim: {result['notification_sent']}, atlanan mevcut bildirim: {result['notification_skipped']}, "
                f"e-posta başarılı: {result['mail_success_count']}."
            ),
            "success",
        )
        if send_mail and result.get("mail_failed_count"):
            flash(f"Bazı özet e-postaları gönderilemedi: {result['mail_failed_count']}.", "warning")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Performans yönetici özeti çalıştırılamadı: %s", exc)
        flash("Yönetici özeti çalıştırılırken hata oluştu.", "danger")
    return redirect(url_for("main.feedback_executive_summary_dashboard", scope=selected_scope, preset=preset))


@main_bp.route("/performance/go-live-center")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_center():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    dashboard = build_performance_go_live_center(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    return safe_render(
        "feedback_go_live_center.html",
        "<h3>Canlıya Çıkış Merkezi</h3>",
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        active_period=active_period,
        **dashboard,
    )

@main_bp.route("/performance/go-live-center/uat")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_uat():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    return safe_render(
        "feedback_go_live_uat.html",
        "<h3>Canlı Öncesi UAT Özeti</h3>",
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        active_period=active_period,
        **report,
    )


@main_bp.route("/performance/go-live-center/uat/export.txt")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_uat_export_txt():
    _, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    payload = export_go_live_uat_txt(report)
    response = current_app.response_class(payload, mimetype="text/plain; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=performance_go_live_uat.txt"
    return response


@main_bp.route("/performance/go-live-center/issues.csv")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_issues_csv():
    _, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    payload = export_go_live_issues_csv(report)
    response = current_app.response_class(payload, mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=performance_go_live_issues.csv"
    return response


@main_bp.route("/performance/go-live-center/release-packet.txt")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_release_packet_txt():
    _, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    payload = export_go_live_release_packet_txt(report)
    response = current_app.response_class(payload, mimetype="text/plain; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=performance_go_live_release_packet.txt"
    return response


@main_bp.route("/performance/go-live-center/smoke-test")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_smoke_test():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    smoke = build_go_live_smoke_report(report)
    return safe_render(
        "feedback_go_live_smoke.html",
        "<h3>Canlı Öncesi Final Smoke Test</h3>",
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        active_period=active_period,
        report=report,
        cards=report.get("cards") or {},
        signoff=report.get("signoff") or {},
        generated_at=report.get("generated_at"),
        smoke=smoke,
        smoke_rows=smoke.get("rows") or [],
        smoke_summary=smoke.get("summary") or {},
        smoke_decision=smoke.get("decision") or {},
    )


@main_bp.route("/performance/go-live-center/smoke-test.csv")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_smoke_csv():
    _, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    smoke = build_go_live_smoke_report(report)
    payload = export_go_live_smoke_csv(smoke)
    response = current_app.response_class(payload, mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=performance_go_live_smoke_test.csv"
    return response


@main_bp.route("/performance/go-live-center/management-brief.txt")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_go_live_management_brief_txt():
    _, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    smoke = build_go_live_smoke_report(report)
    payload = export_go_live_management_brief_txt(report, smoke)
    response = current_app.response_class(payload, mimetype="text/plain; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=performance_go_live_management_brief.txt"
    return response

@main_bp.route("/performance/feedback-audit")
@login_required
@menu_key_required("performance_feedback_meetings")
def feedback_audit_dashboard():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    requests_list, meetings = _load_scoped_feedback_data(
        selected_scope,
        scope_employee_ids,
        meeting_desc=True,
    )
    dashboard = build_feedback_audit_dashboard(
        requests_list,
        meetings,
        today=utc_now().date(),
    )

    return safe_render(
        "feedback_audit_dashboard.html",
        "<h3>Geri Bildirim Denetim ve SLA Paneli</h3>",
        **_scope_render_kwargs(scope_ctx),
        **dashboard,
    )


@main_bp.route("/performance/feedback-requests/<int:request_id>", methods=["GET", "POST"])
@login_required
def manager_feedback_request_detail(request_id):
    req = db.session.get(FeedbackRequest, request_id)
    if not req:
        flash("Talep bulunamadı.", "danger")
        return redirect(url_for("main.manager_feedback_requests"))

    scope_ctx, _, _ = _get_scope_context()
    allowed_manager_ids = {req.level_1_manager_id, req.level_2_manager_id, req.level_3_manager_id}
    can_manage_request = current_user.role == "admin" or current_user.id in allowed_manager_ids
    can_view_request = can_manage_request or current_user.id == req.employee_id
    if not can_view_request:
        flash("Bu talebe erişim yetkiniz yok.", "danger")
        return redirect(url_for("main.manager_feedback_requests", scope=scope_ctx.get("selected_scope")))

    scheduled_meeting = get_feedback_meeting(req.id)
    request_timeline = get_feedback_request_timeline(req.id)

    if request.method == "POST":
        if not can_manage_request:
            flash("Bu talebi güncelleme yetkiniz yok.", "danger")
            return redirect(url_for("main.manager_feedback_request_detail", request_id=req.id, scope=scope_ctx.get("selected_scope")))
        response_text = (request.form.get("response") or "").strip()
        status = (request.form.get("status") or "incelendi").strip()
        valid_statuses = {"bekliyor", "incelendi", "cevaplandi", "kapatildi", "randevulandi", "gorusme_tamamlandi", "randevu_ertelendi", "randevu_iptal"}
        if status not in valid_statuses:
            flash("Geçersiz geri bildirim durumu.", "warning")
            return redirect(url_for("main.manager_feedback_request_detail", request_id=req.id, scope=scope_ctx.get("selected_scope")))

        if status == "cevaplandi" and not response_text:
            flash("Cevaplandı durumunda personele iletilecek yanıt metni zorunludur.", "warning")
            return redirect(url_for("main.manager_feedback_request_detail", request_id=req.id, scope=scope_ctx.get("selected_scope")))

        old_state = _serialize_feedback_request_state(req)
        req.status = status
        req.closed_at = utc_now() if status == "kapatildi" else None

        if response_text:
            persist_feedback_response(
                req,
                response_text,
                actor_user_id=current_user.id,
                recipient_email=getattr(req.employee, "email", None),
            )
            req._response_preview_cache = response_text

        summary = f"{current_user.ad} {current_user.soyad} talep durumunu {_serialize_feedback_request_state(req).get('status')} olarak güncelledi."
        action_name = "feedback_request_closed" if status == "kapatildi" else ("feedback_request_responded" if response_text else "feedback_request_status_updated")
        record_feedback_audit_event(
            entity_type="feedback_request",
            entity_id=req.id,
            action=action_name,
            actor_user_id=current_user.id,
            summary=summary,
            old_data=old_state,
            new_data=_serialize_feedback_request_state(req),
        )
        _notify_feedback_request_status_changed(req, actor_user=current_user)
        db.session.commit()

        if response_text and status in {"cevaplandi", "kapatildi"}:
            ok, message = send_feedback_response_mail(req)
            flash("Talep güncellendi. Yanıt personele iletildi." if ok else f"Talep güncellendi ancak e-posta gönderilemedi: {message}", "success" if ok else "warning")
        else:
            flash("Talep güncellendi.", "success")

        return redirect(url_for("main.manager_feedback_request_detail", request_id=req.id, scope=scope_ctx.get("selected_scope")))

    return safe_render(
        "manager_feedback_request_detail.html",
        "<h3>Talep Detayı</h3>",
        req=req,
        scheduled_meeting=scheduled_meeting,
        response_text=get_feedback_response_text(req),
        request_timeline=request_timeline,
        **_scope_render_kwargs(scope_ctx),
    )


@main_bp.route("/performance/feedback-requests/<int:request_id>/schedule-preview")
@login_required
def manager_feedback_request_schedule_preview(request_id):
    req = db.session.get(FeedbackRequest, request_id)
    if not req:
        return jsonify({"ok": False, "message": "Talep bulunamadı."}), 404

    allowed_manager_ids = {req.level_1_manager_id, req.level_2_manager_id, req.level_3_manager_id}
    can_manage_request = current_user.role == "admin" or current_user.id in allowed_manager_ids
    if not can_manage_request:
        return jsonify({"ok": False, "message": "Bu talep için randevu planlama yetkiniz yok."}), 403

    meeting_date_raw = (request.args.get("meeting_date") or "").strip()
    if not meeting_date_raw:
        return jsonify({"ok": False, "message": "Tarih bilgisi gereklidir."}), 400

    try:
        meeting_date = datetime.strptime(meeting_date_raw, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"ok": False, "message": "Tarih formatı geçersiz."}), 400

    selected_start = None
    selected_end = None
    meeting_start_raw = (request.args.get("meeting_start") or "").strip()
    meeting_end_raw = (request.args.get("meeting_end") or "").strip()
    try:
        if meeting_start_raw:
            selected_start = datetime.strptime(meeting_start_raw, "%H:%M").time()
        if meeting_end_raw:
            selected_end = datetime.strptime(meeting_end_raw, "%H:%M").time()
    except ValueError:
        return jsonify({"ok": False, "message": "Saat formatı geçersiz."}), 400

    related_manager_ids = _feedback_manager_ids(req) or {current_user.id}
    meetings = FeedbackMeeting.query.options(
        joinedload(FeedbackMeeting.employee),  # type: ignore[arg-type]
        joinedload(FeedbackMeeting.manager),  # type: ignore[arg-type]
    ).filter(
        FeedbackMeeting.meeting_date == meeting_date,
        FeedbackMeeting.status != "iptal_edildi",
        or_(
            FeedbackMeeting.employee_id == req.employee_id,
            FeedbackMeeting.manager_id.in_(sorted(related_manager_ids)),
        ),
    ).order_by(FeedbackMeeting.meeting_start.asc(), FeedbackMeeting.id.asc()).all()

    payload = build_feedback_schedule_preview(
        req,
        meetings,
        meeting_date=meeting_date,
        selected_start=selected_start,
        selected_end=selected_end,
    )
    payload["ok"] = True
    return jsonify(payload)


@main_bp.route("/performance/feedback-requests/<int:request_id>/schedule", methods=["GET", "POST"])
@login_required
def manager_feedback_request_schedule(request_id):
    req = db.session.get(FeedbackRequest, request_id)
    if not req:
        flash("Talep bulunamadı.", "danger")
        return redirect(url_for("main.manager_feedback_requests"))

    scope_ctx, _, _ = _get_scope_context()
    allowed_manager_ids = {req.level_1_manager_id, req.level_2_manager_id, req.level_3_manager_id}
    can_manage_request = current_user.role == "admin" or current_user.id in allowed_manager_ids
    if not can_manage_request:
        flash("Bu talep için randevu oluşturma yetkiniz yok.", "danger")
        return redirect(url_for("main.manager_feedback_requests", scope=scope_ctx.get("selected_scope")))

    existing_meeting = FeedbackMeeting.query.filter_by(feedback_request_id=req.id).first()
    if existing_meeting:
        flash("Bu talep için zaten randevu oluşturulmuş.", "warning")
        return redirect(url_for("main.manager_feedback_request_detail", request_id=req.id, scope=scope_ctx.get("selected_scope")))

    if request.method == "POST":
        meeting_date_raw = (request.form.get("meeting_date") or "").strip()
        meeting_start_raw = (request.form.get("meeting_start") or "").strip()
        meeting_end_raw = (request.form.get("meeting_end") or "").strip()
        meeting_type = (request.form.get("meeting_type") or "yuz_yuze").strip()
        location = (request.form.get("location") or "").strip()
        note = (request.form.get("note") or "").strip()

        if not meeting_date_raw or not meeting_start_raw or not meeting_end_raw:
            flash("Tarih ve saat alanları zorunludur.", "warning")
            return redirect(request.url)

        try:
            meeting_date = datetime.strptime(meeting_date_raw, "%Y-%m-%d").date()
            meeting_start = datetime.strptime(meeting_start_raw, "%H:%M").time()
            meeting_end = datetime.strptime(meeting_end_raw, "%H:%M").time()
        except ValueError:
            flash("Tarih veya saat formatı geçersiz.", "warning")
            return redirect(request.url)

        if meeting_start >= meeting_end:
            flash("Başlangıç saati bitiş saatinden küçük olmalıdır.", "warning")
            return redirect(request.url)

        related_manager_ids = _feedback_manager_ids(req) or {current_user.id}
        conflict_meeting, conflict_message = _find_feedback_meeting_conflict(
            manager_ids=related_manager_ids,
            employee_id=req.employee_id,
            meeting_date=meeting_date,
            meeting_start=meeting_start,
            meeting_end=meeting_end,
        )
        if conflict_meeting:
            flash(conflict_message, "danger")
            return redirect(request.url)

        try:
            meeting = FeedbackMeeting(
                feedback_request_id=req.id,
                employee_id=req.employee_id,
                manager_id=current_user.id,
                meeting_date=meeting_date,
                meeting_start=meeting_start,
                meeting_end=meeting_end,
                location=location or None,
                meeting_type=meeting_type,
                note=note or None,
                status="planlandi",
            )
            db.session.add(meeting)
            db.session.flush()
            previous_request_state = _serialize_feedback_request_state(req)
            req.status = "randevulandi"
            req.scheduled_by_id = current_user.id
            req.scheduled_meeting_id = meeting.id
            _notify_feedback_meeting_created(meeting)
            record_feedback_audit_event(
                entity_type="feedback_meeting",
                entity_id=meeting.id,
                action="feedback_meeting_created",
                actor_user_id=current_user.id,
                summary=f"{current_user.ad} {current_user.soyad} görüşme randevusu planladı.",
                new_data=_serialize_feedback_meeting_state(meeting),
            )
            record_feedback_audit_event(
                entity_type="feedback_request",
                entity_id=req.id,
                action="feedback_request_status_updated",
                actor_user_id=current_user.id,
                summary="Talep randevuya bağlandı.",
                old_data=previous_request_state,
                new_data=_serialize_feedback_request_state(req),
            )
            db.session.commit()
            mail_result = send_feedback_meeting_created_mail(meeting)
            if int(mail_result.get("failed_count", 0) or 0) > 0:
                flash("Randevu oluşturuldu. Uygulama içi bildirimler kaydedildi, ancak bazı e-posta bildirimleri gönderilemedi.", "warning")
            else:
                flash("Randevu oluşturuldu ve bildirimler gönderildi.", "success")
            return redirect(url_for("main.manager_feedback_request_detail", request_id=req.id, scope=scope_ctx.get("selected_scope")))
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/performance/engagement_feedback_routes.py | line=819 | exc=%s", exc)
            db.session.rollback()
            flash("Randevu oluşturulurken hata oluştu.", "danger")
            return redirect(request.url)

    return safe_render(
        "manager_feedback_request_schedule.html",
        "<h3>Randevu Oluştur</h3>",
        req=req,
        **_scope_render_kwargs(scope_ctx),
        ai_feedback_schedule_panel=build_feedback_schedule_ai_panel(req, actor=current_user),
    )


@main_bp.route("/performance/feedback-meetings/<int:meeting_id>")
@login_required
def feedback_meeting_detail(meeting_id):
    meeting = db.session.get(FeedbackMeeting, meeting_id)
    if not meeting:
        flash("Randevu bulunamadı.", "danger")
        return redirect(url_for("main.dashboard"))

    scope_ctx, _, _ = _get_scope_context()
    allowed_ids = {meeting.employee_id, meeting.manager_id} | _feedback_manager_ids(getattr(meeting, "feedback_request", None))
    scope_employee_ids = set(scope_ctx.get("employee_ids") or [])
    if current_user.id not in allowed_ids and meeting.employee_id not in scope_employee_ids:
        flash("Bu randevuya erişim yetkiniz yok.", "danger")
        return redirect(url_for("main.dashboard"))

    response_text = get_feedback_response_text(meeting.feedback_request) if meeting.feedback_request else ""  # type: ignore[arg-type]
    meeting_timeline = get_feedback_meeting_timeline(meeting.id)
    can_manage_meeting = current_user.role == "admin" or current_user.id in allowed_ids
    return safe_render(
        "feedback_meeting_detail.html",
        "<h3>Randevu Detayı</h3>",
        meeting=meeting,
        response_text=response_text,
        meeting_timeline=meeting_timeline,
        can_manage_meeting=can_manage_meeting,
        get_feedback_meeting_status_label=get_feedback_meeting_status_label,
        get_feedback_request_status_label=get_feedback_request_status_label,
        **_scope_render_kwargs(scope_ctx),
    )


@main_bp.route("/performance/feedback-meetings")
@login_required
@menu_key_required("performance_feedback_meetings")
def feedback_meetings_list():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()

    meetings_query = FeedbackMeeting.query.options(joinedload(FeedbackMeeting.feedback_request))  # type: ignore[arg-type]
    if selected_scope != "mine" and scope_employee_ids:
        meetings_query = meetings_query.filter(FeedbackMeeting.employee_id.in_(scope_employee_ids))

    meetings = meetings_query.order_by(FeedbackMeeting.meeting_date.desc(), FeedbackMeeting.meeting_start.desc()).all()
    if selected_scope == "mine":
        meetings = [meeting for meeting in meetings if _meeting_visible_to_user(meeting, current_user.id)]

    today = utc_now().date()
    current_view = (request.args.get("view") or "all").strip().lower()
    search_query = " ".join((request.args.get("q") or "").strip().split())
    allowed_views = {"all", "upcoming", "past", "planlandi", "tamamlandi", "ertelendi", "iptal_edildi", "my_managed", "my_employee"}
    if current_view not in allowed_views:
        current_view = "all"

    def _meeting_matches_query(meeting, query: str) -> bool:
        if not query:
            return True
        q = query.casefold()
        haystack = " ".join(
            [
                getattr(meeting.employee, "full_name", "") or f"{getattr(meeting.employee, 'ad', '')} {getattr(meeting.employee, 'soyad', '')}",
                getattr(meeting.employee, "sicil_no", "") or "",
                getattr(meeting.manager, "full_name", "") or f"{getattr(meeting.manager, 'ad', '')} {getattr(meeting.manager, 'soyad', '')}",
                getattr(meeting, "location", "") or "",
                getattr(meeting, "meeting_type", "") or "",
                getattr(meeting, "note", "") or "",
                getattr(getattr(meeting, "feedback_request", None), "reason", "") or "",
                getattr(getattr(getattr(meeting, "feedback_request", None), "period", None), "title", "") or "",
            ]
        ).casefold()
        return q in haystack

    filter_counts = {
        "all": len(meetings),
        "upcoming": 0,
        "past": 0,
        "planlandi": 0,
        "tamamlandi": 0,
        "ertelendi": 0,
        "iptal_edildi": 0,
        "my_managed": 0,
        "my_employee": 0,
    }

    for meeting in meetings:
        is_upcoming = bool(meeting.meeting_date and meeting.meeting_date >= today)
        if is_upcoming:
            filter_counts["upcoming"] += 1
        else:
            filter_counts["past"] += 1
        if meeting.status in filter_counts:
            filter_counts[meeting.status] += 1
        if _meeting_visible_to_user(meeting, current_user.id) and meeting.employee_id != current_user.id:
            filter_counts["my_managed"] += 1
        if meeting.employee_id == current_user.id:
            filter_counts["my_employee"] += 1

    def _meeting_matches_view(meeting) -> bool:
        is_upcoming = bool(meeting.meeting_date and meeting.meeting_date >= today)
        if current_view == "all":
            return True
        if current_view == "upcoming":
            return is_upcoming
        if current_view == "past":
            return not is_upcoming
        if current_view == "my_managed":
            return _meeting_visible_to_user(meeting, current_user.id) and meeting.employee_id != current_user.id
        if current_view == "my_employee":
            return meeting.employee_id == current_user.id
        return (meeting.status or "") == current_view

    visible_meetings = [
        meeting
        for meeting in meetings
        if _meeting_matches_view(meeting) and _meeting_matches_query(meeting, search_query)
    ]

    upcoming_meetings = [meeting for meeting in visible_meetings if meeting.meeting_date and meeting.meeting_date >= today]
    past_meetings = [meeting for meeting in visible_meetings if not meeting.meeting_date or meeting.meeting_date < today]
    next_meeting = upcoming_meetings[0] if upcoming_meetings else None

    return safe_render(
        "feedback_meetings_list.html",
        "<h3>Geri Bildirim Randevuları</h3>",
        upcoming_meetings=upcoming_meetings,
        past_meetings=past_meetings,
        all_meetings=visible_meetings,
        next_meeting=next_meeting,
        current_view=current_view,
        search_query=search_query,
        filter_counts=filter_counts,
        visible_count=len(visible_meetings),
        today=today,
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        ai_feedback_meetings_panel=build_feedback_meetings_ai_panel(visible_meetings, current_user=current_user, next_meeting=next_meeting),
    )


@main_bp.route("/performance/feedback-meetings/<int:meeting_id>/update", methods=["POST"])
@login_required
def feedback_meeting_update(meeting_id):
    meeting = db.session.get(FeedbackMeeting, meeting_id)
    if not meeting:
        flash("Randevu bulunamadı.", "danger")
        return redirect(url_for("main.feedback_meetings_list"))

    scope_ctx, _, _ = _get_scope_context()
    allowed_ids = {meeting.manager_id} | _feedback_manager_ids(getattr(meeting, "feedback_request", None))
    can_manage_meeting = current_user.role == "admin" or current_user.id in allowed_ids
    if not can_manage_meeting:
        flash("Bu randevuyu güncelleme yetkiniz yok.", "danger")
        return redirect(url_for("main.feedback_meetings_list", scope=scope_ctx.get("selected_scope")))

    status = (request.form.get("status") or "").strip()
    note = (request.form.get("note") or "").strip()
    meeting_date_raw = (request.form.get("meeting_date") or "").strip()
    meeting_start_raw = (request.form.get("meeting_start") or "").strip()
    meeting_end_raw = (request.form.get("meeting_end") or "").strip()
    meeting_type = (request.form.get("meeting_type") or meeting.meeting_type or "yuz_yuze").strip()
    location = (request.form.get("location") or "").strip()
    valid_statuses = {"planlandi", "tamamlandi", "ertelendi", "iptal_edildi"}
    if status not in valid_statuses:
        flash("Geçersiz randevu durumu.", "warning")
        return redirect(url_for("main.feedback_meeting_detail", meeting_id=meeting.id, scope=scope_ctx.get("selected_scope")))

    try:
        meeting_date = datetime.strptime(meeting_date_raw, "%Y-%m-%d").date() if meeting_date_raw else meeting.meeting_date
        meeting_start = datetime.strptime(meeting_start_raw, "%H:%M").time() if meeting_start_raw else meeting.meeting_start
        meeting_end = datetime.strptime(meeting_end_raw, "%H:%M").time() if meeting_end_raw else meeting.meeting_end
    except ValueError:
        flash("Tarih veya saat formatı geçersiz.", "warning")
        return redirect(url_for("main.feedback_meeting_detail", meeting_id=meeting.id, scope=scope_ctx.get("selected_scope")))

    if meeting_start >= meeting_end:
        flash("Başlangıç saati bitiş saatinden küçük olmalıdır.", "warning")
        return redirect(url_for("main.feedback_meeting_detail", meeting_id=meeting.id, scope=scope_ctx.get("selected_scope")))

    related_manager_ids = _feedback_manager_ids(getattr(meeting, "feedback_request", None)) or {meeting.manager_id}
    conflict_meeting, conflict_message = _find_feedback_meeting_conflict(
        manager_ids=related_manager_ids,
        employee_id=meeting.employee_id,
        meeting_date=meeting_date,
        meeting_start=meeting_start,
        meeting_end=meeting_end,
        exclude_meeting_id=meeting.id,
    )
    if conflict_meeting:
        flash(conflict_message, "danger")
        return redirect(url_for("main.feedback_meeting_detail", meeting_id=meeting.id, scope=scope_ctx.get("selected_scope")))

    old_meeting_state = _serialize_feedback_meeting_state(meeting)
    old_request_state = _serialize_feedback_request_state(meeting.feedback_request) if meeting.feedback_request else {}
    meeting.meeting_date = meeting_date
    meeting.meeting_start = meeting_start
    meeting.meeting_end = meeting_end
    meeting.meeting_type = meeting_type or "yuz_yuze"
    meeting.location = location or None
    if current_user.id in related_manager_ids:
        meeting.manager_id = current_user.id

    meeting.status = status
    if note:
        existing_note = (meeting.note or "").strip()
        stamped_note = f"Durum Güncelleme Notu ({utc_now().strftime('%d.%m.%Y %H:%M')}):\n{note}"
        if existing_note:
            meeting.note = f"{existing_note}\n\n{stamped_note}"
        else:
            meeting.note = stamped_note

    if meeting.feedback_request:
        meeting.feedback_request.scheduled_by_id = current_user.id  # type: ignore[attr-defined]
        meeting.feedback_request.scheduled_meeting_id = meeting.id  # type: ignore[attr-defined]
        if status == "tamamlandi":
            meeting.feedback_request.status = "gorusme_tamamlandi"  # type: ignore[attr-defined]
        elif status == "ertelendi":
            meeting.feedback_request.status = "randevu_ertelendi"  # type: ignore[attr-defined]
        elif status == "iptal_edildi":
            meeting.feedback_request.status = "randevu_iptal"  # type: ignore[attr-defined]
        else:
            meeting.feedback_request.status = "randevulandi"  # type: ignore[attr-defined]

    record_feedback_audit_event(
        entity_type="feedback_meeting",
        entity_id=meeting.id,
        action="feedback_meeting_status_updated",
        actor_user_id=current_user.id,
        summary=f"{current_user.ad} {current_user.soyad} randevuyu güncelledi.",
        old_data=old_meeting_state,
        new_data=_serialize_feedback_meeting_state(meeting),
    )
    if meeting.feedback_request:
        record_feedback_audit_event(
            entity_type="feedback_request",
            entity_id=meeting.feedback_request.id,
            action="feedback_request_status_updated",
            actor_user_id=current_user.id,
            summary="Bağlı talep randevu durumuna göre güncellendi.",
            old_data=old_request_state,
            new_data=_serialize_feedback_request_state(meeting.feedback_request),
        )
    _notify_feedback_meeting_updated(meeting)
    db.session.commit()
    mail_result = send_feedback_meeting_status_update_mail(meeting)
    if int(mail_result.get("failed_count", 0) or 0) > 0:
        flash("Randevu kaydı güncellendi. Uygulama içi bildirim oluşturuldu, ancak bazı e-posta bildirimleri gönderilemedi.", "warning")
    else:
        flash("Randevu kaydı güncellendi.", "success")
    return redirect(url_for("main.feedback_meeting_detail", meeting_id=meeting.id, scope=scope_ctx.get("selected_scope")))


@main_bp.route("/performance/pilot-simulation-center")
@login_required
@menu_key_required("performance_feedback_meetings")
def performance_pilot_simulation_center():
    scope_ctx, selected_scope, scope_employee_ids = _get_scope_context()
    active_period = get_period()
    requests_list, meetings = _load_scoped_feedback_data(selected_scope, scope_employee_ids)
    report = build_go_live_uat_report(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
    )
    smoke = build_go_live_smoke_report(report)
    readiness = build_pilot_readiness_context(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
        report=report,
        smoke=smoke,
    )
    execution = build_pilot_execution_context(
        active_period=active_period,
        requests_list=requests_list,
        meetings=meetings,
        now=utc_now(),
        scope_employee_ids=scope_employee_ids,
        report=report,
        smoke=smoke,
    )
    return safe_render(
        "performance_pilot_simulation_center.html",
        "<h3>Pilot Simülasyon Merkezi</h3>",
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        active_period=active_period,
        report=report,
        cards=report.get("cards") or {},
        signoff=report.get("signoff") or {},
        generated_at=report.get("generated_at"),
        smoke=smoke,
        smoke_rows=smoke.get("rows") or [],
        smoke_summary=smoke.get("summary") or {},
        smoke_decision=smoke.get("decision") or {},
        readiness=readiness,
        execution=execution,
    )
