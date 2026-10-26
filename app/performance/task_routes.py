from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from flask import Response, current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import PerformancePeriod, User
from app.route_registry import main_bp
from app.route_support import admin_required, menu_key_required, safe_all, safe_render
from app.security.critical_operations import (
    critical_operation_required,
    frozen_period_generation_refusal,
)
from app.services.availability_service import refresh_assignment_live_coverages
from app.services.performance.assignments import build_assignment_log_summary
from app.services.performance.hardening_service import (
    build_period_download_name,
    humanize_export_exception,
)
from app.services.performance.health_report import build_performance_task_health_report
from app.services.performance.preflight import (
    build_task_management_preflight_report,
    preflight_has_blockers,
)
from app.services.performance.task_management_service import (
    build_assignment_recommendation_payload as _build_assignment_recommendation_payload,
    build_audit_employee_options as _build_audit_employee_options,
    build_task_audit_csv_text,
    build_task_health_csv_text,
    build_task_management_dashboard_payload,
    build_task_recommendation_export_response,
    build_task_scope_context,
    clear_period_task_records,
    filter_audit_rows as _filter_audit_rows,
    get_selected_period_from_args,
    log_performance_recommendation_export as _log_performance_recommendation_export,
)
from app.services.performance_service import (
    generate_assignments_for_active_period,
    is_informational_special_case,
)
from app.services.performance_v2 import build_assignment_preview

"""Performans görev yönetimi route ailesi.

Bu dosya performans görev yönetimi ekranlarının istek/yanıt akışını
modüler yapı altında yönetir.
"""

"""Görev yönetimi yardımcıları service katmanında çalışır.
Bu route dosyası yalnızca istek/yanıt akışını yönetir.
"""
logger = logging.getLogger(__name__)

@main_bp.route("/performance/task-management")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    manager_level = request.args.get("manager_level", type=int)
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)

    periods = safe_all(
        PerformancePeriod.query
        .order_by(PerformancePeriod.start_date.desc(), PerformancePeriod.id.desc()),
        label="task_management_periods",
    )

    selected_period = get_selected_period_from_args(request.args)
    if selected_period:
        refresh_assignment_live_coverages(period_id=selected_period.id)

    dashboard_payload = build_task_management_dashboard_payload(
        selected_period,
        q=q,
        status=status,
        manager_level=manager_level,
        scope_user_ids=scope_user_ids,
        selected_scope=scope.get("selected_scope") or "",
    )

    return safe_render(
        "task_management.html",
        "<h3>Görev Yönetimi</h3>",
        periods=periods,
        selected_period=selected_period,
        q=q,
        selected_scope=scope.get("selected_scope"),
        scope_options=scope.get("scope_options"),
        scope_label=scope.get("scope_label"),
        scope_hint=scope.get("scope_hint"),
        scope_user_count=scope.get("scope_user_count"),
        scope_unit_count=scope.get("scope_unit_count"),
        is_assignment_log_special_case=is_informational_special_case,
        **dashboard_payload,
    )


@main_bp.route("/performance/task-management/generate", methods=["POST"])
@login_required
@admin_required
@critical_operation_required("assignment_generate")
@menu_key_required("performance_task_management")
def performance_task_management_generate():
    period_id = request.form.get("period_id", type=int)
    selected_scope = (request.form.get("scope") or "").strip()
    q = (request.form.get("q") or "").strip()
    status = (request.form.get("status") or "").strip()
    manager_level = request.form.get("manager_level", type=int)
    force_generate = (request.form.get("force_generate") or "").strip().lower() in {"1", "true", "on", "yes"}

    redirect_args: dict[str, Any] = {"period_id": period_id, "scope": selected_scope or None}
    if q:
        redirect_args["q"] = q
    if status:
        redirect_args["status"] = status
    if manager_level in (1, 2, 3):
        redirect_args["manager_level"] = manager_level

    try:
        selected_period = db.session.get(PerformancePeriod, period_id) if period_id else None
        # P0 (M-1 Q3): kilitli/yayımlanmış dönemde görev üretimi yok (gerçek admin dahil).
        refusal = frozen_period_generation_refusal(selected_period, url_for("main.performance_task_management", **redirect_args))
        if refusal is not None:
            return refusal
        full_preflight_report = build_task_management_preflight_report(selected_period, None)

        if preflight_has_blockers(full_preflight_report) and not force_generate:
            flash(
                f"Görev üretimi ön kontrolde durduruldu. {len(full_preflight_report.get('blockers') or [])} blokaj var.",
                "warning",
            )
            return redirect(url_for("main.performance_task_management_preflight", **redirect_args))

        if force_generate and preflight_has_blockers(full_preflight_report):
            flash(
                "Ön kontrolde blokaj olmasına rağmen yönetici override ile görev üretimi başlatıldı.",
                "warning",
            )

        result = generate_assignments_for_active_period(period_id=period_id, actor_user_id=current_user.id)

        if not result.get("ok"):
            flash(result.get("message", "Görev üretilemedi."), "warning")
            return redirect(url_for("main.performance_task_management", **redirect_args))

        created = result.get("created", 0)
        skipped = result.get("skipped", 0)
        deduped = result.get("deduped", 0)
        warnings = result.get("warnings", [])
        infos = result.get("infos", [])
        breakdown = result.get("breakdown", {}) or {}

        if warnings:
            flash(
                f"Görev üretimi tamamlandı. Oluşturulan: {created}, atlanan/muaf kalan personel: {skipped}, temizlenen duplicate: {deduped}, uyarı sayısı: {len(warnings)}.",
                "warning",
            )
            detail_parts = []
            if breakdown.get("chain_issue"):
                detail_parts.append(f"zincir sorunu: {breakdown.get('chain_issue')}")
            if breakdown.get("uncovered"):
                detail_parts.append(f"vekâlet/amir kapsaması yok: {breakdown.get('uncovered')}")
            if breakdown.get("exempted"):
                detail_parts.append(f"muafiyet: {breakdown.get('exempted')}")
            if detail_parts:
                flash("Atlama özeti: " + ", ".join(detail_parts) + ".", "warning")
            sample = warnings[:10]
            if sample:
                current_app.logger.warning(
                    "Performans görev yönetimi ham uyarı örnekleri gizlendi: %s",
                    " | ".join(sample),
                )
                flash(
                    "Ham uyarı metinleri kullanıcı ekranında gizlendi. Detaylar yönetici logunda tutuldu.",
                    "info",
                )
        else:
            flash(
                f"Görev üretimi tamamlandı. Oluşturulan: {created}, atlanan/muaf kalan personel: {skipped}, temizlenen duplicate: {deduped}.",
                "success",
            )

        if infos:
            flash(f"Bilgi notları kaydedildi: {len(infos)}.", "info")

        return redirect(url_for("main.performance_task_management", **redirect_args))

    except Exception as exc:
        current_app.logger.exception("Görev üretimi route hatası: %s", exc)
        flash("Görev üretimi sırasında hata oluştu.", "danger")
        return redirect(url_for("main.performance_task_management", **redirect_args))


@main_bp.route("/performance/task-management/audit")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_audit_detail():
    severity = (request.args.get("severity") or "").strip()
    event_type = (request.args.get("event_type") or "").strip()
    q = (request.args.get("q") or "").strip()
    employee_id = request.args.get("employee_id", type=int)
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)
    selected_period = get_selected_period_from_args(request.args)
    payload = _build_assignment_recommendation_payload(
        selected_period,
        scope.get("selected_scope") or "",
        scope_user_ids,
        severity=severity,
        event_type=event_type,
    )
    base_rows = payload.get("visible_rows") or []
    visible_rows = _filter_audit_rows(base_rows, severity=severity, event_type=event_type, employee_id=employee_id, q=q)
    summary = build_assignment_log_summary(visible_rows)
    severity_summary = Counter(str(getattr(row, "severity", "warning") or "warning").strip().lower() or "warning" for row in visible_rows)
    selected_employee = db.session.get(User, employee_id) if employee_id else None
    selected_employee_preview = None
    if selected_period is not None and selected_employee is not None:
        try:
            selected_employee_preview = build_assignment_preview(selected_employee, selected_period)
        except Exception as exc:
            current_app.logger.exception("Atama önizlemesi oluşturulamadı: %s", exc)
            selected_employee_preview = None
    return safe_render(
        "assignment_audit_detail.html",
        "<h3>Atama Denetim Detayı</h3>",
        selected_period=selected_period,
        selected_scope=scope.get("selected_scope"),
        scope_label=scope.get("scope_label"),
        severity=severity,
        event_type=event_type,
        q=q,
        employee_id=employee_id,
        employee_options=_build_audit_employee_options(scope_user_ids),
        selected_employee=selected_employee,
        selected_employee_preview=selected_employee_preview,
        visible_rows=visible_rows,
        summary=summary,
        severity_summary=severity_summary,
        pressure_rows=payload.get("pressure_rows"),
        reason_rows=payload.get("reason_rows"),
        shortcut_rows=payload.get("shortcut_rows"),
        ai_recommendation_panel=payload.get("ai_recommendation_panel"),
    )


@main_bp.route("/performance/task-management/audit/export")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_audit_export():
    severity = (request.args.get("severity") or "").strip()
    event_type = (request.args.get("event_type") or "").strip()
    q = (request.args.get("q") or "").strip()
    employee_id = request.args.get("employee_id", type=int)
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)
    selected_period = get_selected_period_from_args(request.args)
    try:
        payload = _build_assignment_recommendation_payload(
            selected_period,
            scope.get("selected_scope") or "",
            scope_user_ids,
            severity=severity,
            event_type=event_type,
        )
        visible_rows = _filter_audit_rows(payload.get("visible_rows") or [], severity=severity, event_type=event_type, employee_id=employee_id, q=q)
        csv_text = build_task_audit_csv_text(visible_rows)
        filename = build_period_download_name("performans_atama_denetim", selected_period, "csv")
        return Response(
            csv_text,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as exc:
        current_app.logger.exception("Atama denetim export hatası: %s", exc)
        flash(f"Atama denetim dışa aktarma sırasında hata oluştu: {humanize_export_exception(exc)}", "danger")
        return redirect(url_for("main.performance_task_management_audit_detail", **request.args.to_dict(flat=True)))  # type: ignore[arg-type]


@main_bp.route("/performance/task-management/recommendations")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_recommendations():
    severity = (request.args.get("severity") or "").strip()
    event_type = (request.args.get("event_type") or "").strip()
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)
    selected_period = get_selected_period_from_args(request.args)
    payload = _build_assignment_recommendation_payload(
        selected_period,
        scope.get("selected_scope") or "",
        scope_user_ids,
        severity=severity,
        event_type=event_type,
    )
    return safe_render(
        "assignment_recommendations.html",
        "<h3>AI Öneri Merkezi</h3>",
        selected_period=selected_period,
        selected_scope=scope.get("selected_scope"),
        scope_label=scope.get("scope_label"),
        severity=severity,
        event_type=event_type,
        summary=payload.get("summary"),
        recommendation_rows=payload.get("recommendation_rows"),
        action_plan_rows=payload.get("action_plan_rows"),
        pressure_rows=payload.get("pressure_rows"),
        reason_rows=payload.get("reason_rows"),
        shortcut_rows=payload.get("shortcut_rows"),
        ai_recommendation_panel=payload.get("ai_recommendation_panel"),
        ai_pressure_panel=payload.get("ai_pressure_panel"),
    )


@main_bp.route("/performance/task-management/preflight")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_preflight():
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)
    selected_period = get_selected_period_from_args(request.args)
    preflight_report = build_task_management_preflight_report(selected_period, scope_user_ids)
    return safe_render(
        "performance_task_preflight.html",
        "<h3>Görev Üretimi Ön Kontrolü</h3>",
        selected_period=selected_period,
        selected_scope=scope.get("selected_scope"),
        scope_label=scope.get("scope_label"),
        scope_hint=scope.get("scope_hint"),
        scope_user_count=scope.get("scope_user_count"),
        scope_unit_count=scope.get("scope_unit_count"),
        preflight_report=preflight_report,
    )


@main_bp.route("/performance/task-management/health")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_health():
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)
    selected_period = get_selected_period_from_args(request.args)
    health_report = build_performance_task_health_report(selected_period, scope_user_ids)
    return safe_render(
        "performance_task_health.html",
        "<h3>Görev Sağlık Raporu</h3>",
        selected_period=selected_period,
        selected_scope=scope.get("selected_scope"),
        scope_label=scope.get("scope_label"),
        scope_hint=scope.get("scope_hint"),
        scope_user_count=scope.get("scope_user_count"),
        health_report=health_report,
    )


@main_bp.route("/performance/task-management/health/export")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_health_export():
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)
    selected_period = get_selected_period_from_args(request.args)
    try:
        health_report = build_performance_task_health_report(selected_period, scope_user_ids)
        csv_text = build_task_health_csv_text(health_report)
        filename = build_period_download_name("performans_gorev_saglik_raporu", selected_period, "csv")
        return Response(
            csv_text,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as exc:
        current_app.logger.exception("Görev sağlık export hatası: %s", exc)
        flash(f"Görev sağlık raporu dışa aktarma sırasında hata oluştu: {humanize_export_exception(exc)}", "danger")
        return redirect(url_for("main.performance_task_management_health", **request.args.to_dict(flat=True)))  # type: ignore[arg-type]


@main_bp.route("/performance/task-management/recommendations/export")
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_recommendations_export():
    severity = (request.args.get("severity") or "").strip()
    event_type = (request.args.get("event_type") or "").strip()
    selected_scope = (request.args.get("scope") or "").strip()
    scope, scope_user_ids = build_task_scope_context(current_user, selected_scope)
    selected_period = get_selected_period_from_args(request.args)
    export_format = (request.args.get("format") or request.args.get("fmt") or "csv").strip().lower()
    try:
        payload = _build_assignment_recommendation_payload(
            selected_period,
            scope.get("selected_scope") or "",
            scope_user_ids,
            severity=severity,
            event_type=event_type,
        )
        try:
            _log_performance_recommendation_export(
                selected_period=selected_period,
                selected_scope=scope.get("selected_scope") or "",
                export_format=export_format,
                payload=payload,
            )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Performans AI öneri export audit log hatası: %s", exc)
        export_payload = build_task_recommendation_export_response(
            payload.get("action_plan_rows") or [],
            export_format=export_format,
        )
        filename = build_period_download_name("ai_aksiyon_plani", selected_period, export_payload["extension"])
        return Response(
            export_payload["content"],
            mimetype=export_payload["mimetype"],
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as exc:
        current_app.logger.exception("AI öneri export hatası: %s", exc)
        flash(f"AI öneri dışa aktarma sırasında hata oluştu: {humanize_export_exception(exc)}", "danger")
        return redirect(url_for("main.performance_task_management_recommendations", **request.args.to_dict(flat=True)))  # type: ignore[arg-type]


@main_bp.route("/performance/task-management/clear/<int:period_id>", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_task_management")
def performance_task_management_clear(period_id):
    selected_scope = (request.form.get("scope") or request.args.get("scope") or "").strip()
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return redirect(url_for("main.performance_task_management", scope=selected_scope or None))

    try:
        clear_period_task_records(period.id)
        db.session.commit()
        flash("Seçili dönemin görevleri ve değerlendirme kayıtları temizlendi.", "success")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Görevler temizlenirken hata oluştu.", "danger")

    return redirect(url_for("main.performance_task_management", period_id=period.id, scope=selected_scope or None))