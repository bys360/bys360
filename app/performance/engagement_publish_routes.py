from __future__ import annotations

import logging
from typing import Any, cast

from flask import current_app, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import PerformanceEvaluation, PerformancePeriod, PerformancePublishLog
from app.route_registry import main_bp
from app.route_support import admin_required, ensure_state_change, menu_key_required
from app.services.mail_service import send_published_evaluation_notifications
from app.services.performance.hardening_service import (
    build_period_download_name,
    humanize_export_exception,
)
from app.services.performance_admin_service import create_publish_log, humanize_publish_log_action
from app.services.performance_snapshot_service import (
    backfill_snapshots_for_published_periods,
    create_snapshot_for_evaluation,
    create_snapshots_for_period,
)
from app.services.publish_service import (
    publish_evaluation,
    publish_period_results,
    summarize_skip_reasons,
    unpublish_evaluation,
    unpublish_period_results,
)
from app.view_helpers import build_surface_scope_context

from .mail_helpers import build_styled_excel_bytes
from .publish_helpers import _filter_publish_logs

"""Performans yayınlama ve snapshot route ailesi."""
logger = logging.getLogger(__name__)

@main_bp.route("/performance/publish")
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_publish_dashboard():
    return redirect(url_for("main.performance_v2_phase5_publish", **cast(dict[str, Any], request.args.to_dict(flat=True))))


def _redirect_publish_dashboard(period_id=None, selected_scope="", q="", status=""):
    params = {}
    if period_id:
        params["period_id"] = period_id
    if selected_scope:
        params["scope"] = selected_scope
    if q:
        params["q"] = q
    if status:
        params["status"] = status
    return redirect(url_for("main.performance_publish_dashboard", **params))


@main_bp.route("/performance/snapshots/backfill", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_snapshot_backfill():
    try:
        result = backfill_snapshots_for_published_periods(actor_user_id=current_user.id)
        db.session.commit()
        flash(
            f"Snapshot backfill tamamlandı. Dönem: {result['period_count']}, Yeni: {result['created']}, Atlanan: {result['skipped']}",
            "success",
        )
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Snapshot backfill sırasında hata oluştu.", "danger")

    selected_scope = (request.form.get("scope") or request.args.get("scope") or "").strip()
    q = (request.form.get("q") or request.args.get("q") or "").strip()
    status = (request.form.get("status") or request.args.get("status") or "").strip()
    return _redirect_publish_dashboard(selected_scope=selected_scope, q=q, status=status)


@main_bp.route("/performance/publish/period/<int:period_id>", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_publish_period(period_id):
    period = db.session.get(PerformancePeriod, period_id)
    selected_scope = (request.form.get("scope") or request.args.get("scope") or "").strip()
    q = (request.form.get("q") or request.args.get("q") or "").strip()
    status = (request.form.get("status") or request.args.get("status") or "").strip()
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return _redirect_publish_dashboard(selected_scope=selected_scope, q=q, status=status)

    try:
        if bool(getattr(period, "results_published", False)):
            flash("Bu dönem sonuçları zaten yayımlanmış görünüyor.", "warning")
            return _redirect_publish_dashboard(period_id=period.id, selected_scope=selected_scope, q=q, status=status)
        result = publish_period_results(period, current_user)
        published_count = int(result.get("published_count", 0) or 0)
        skipped_count = len(result.get("skipped", []))

        if published_count > 0:
            published_evaluations = (
                PerformanceEvaluation.query
                .filter(PerformanceEvaluation.id.in_(result.get("published_evaluation_ids", [])))
                .all()
            ) if result.get("published_evaluation_ids") else []
            for evaluation in published_evaluations:
                create_publish_log(period.id, current_user.id, "bulk_publish", evaluation.id, evaluation.employee_id, "Toplu yayın işlemi ile personele açıldı.")

        db.session.commit()

        try:
            create_snapshots_for_period(period.id, actor_user_id=current_user.id)
        except Exception as snap_exc:
            current_app.logger.exception("Snapshot create failed for period publish: %s", snap_exc)
            flash(f"Yayın tamamlandı ancak snapshot oluşturulurken hata oluştu: {snap_exc}", "warning")

        notification_result = send_published_evaluation_notifications(
            period,
            result.get("published_evaluation_ids", []),
            actor_user_id=current_user.id,
        )
        db.session.commit()

        skip_reason_summary = summarize_skip_reasons(result.get("skipped", []))
        if published_count > 0 and skipped_count > 0:
            flash(f"{published_count} sonuç yayımlandı. {skipped_count} bloklu kayıt atlandı.", "success")
            if skip_reason_summary:
                pieces = [f"{reason}: {count}" for reason, count in skip_reason_summary[:4]]
                flash("Atlama nedenleri: " + " | ".join(pieces), "warning")
        elif published_count > 0:
            flash(f"{published_count} sonuç yayımlandı.", "success")
            flash(f"Bilgilendirme e-postası sonucu: başarılı {notification_result.get('success_count', 0)}, hatalı {notification_result.get('failed_count', 0)}.", "info")
        else:
            flash("Yayınlanabilecek tamamlanmış kayıt bulunamadı.", "warning")
            if skip_reason_summary:
                pieces = [f"{reason}: {count}" for reason, count in skip_reason_summary[:4]]
                flash("Blok nedenleri: " + " | ".join(pieces), "info")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Toplu yayın sırasında hata oluştu.", "danger")

    return _redirect_publish_dashboard(period_id=period.id, selected_scope=selected_scope, q=q, status=status)


@main_bp.route("/performance/unpublish/period/<int:period_id>", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_unpublish_period(period_id):
    period = db.session.get(PerformancePeriod, period_id)
    selected_scope = (request.form.get("scope") or request.args.get("scope") or "").strip()
    q = (request.form.get("q") or request.args.get("q") or "").strip()
    status = (request.form.get("status") or request.args.get("status") or "").strip()
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return _redirect_publish_dashboard(selected_scope=selected_scope, q=q, status=status)

    try:
        if not bool(getattr(period, "results_published", False)) and not getattr(period, "published_at", None):
            flash("Bu dönem sonuçları zaten yayında değil.", "warning")
            return _redirect_publish_dashboard(period_id=period.id, selected_scope=selected_scope, q=q, status=status)
        result = unpublish_period_results(period, current_user)
        unpublished_ids = result.get("unpublished_evaluation_ids", []) or []
        for evaluation in PerformanceEvaluation.query.filter(PerformanceEvaluation.id.in_(unpublished_ids)).all() if unpublished_ids else []:
            create_publish_log(period.id, current_user.id, "bulk_unpublish", evaluation.id, evaluation.employee_id, "Toplu yayından kaldırma işlemi uygulandı.")

        db.session.commit()

        if result.get("unpublished_count", 0) > 0:
            flash(f"{result['unpublished_count']} sonuç yayından kaldırıldı.", "success")
        else:
            flash("Yayından kaldırılacak kayıt bulunamadı.", "warning")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Toplu yayından kaldırma sırasında hata oluştu.", "danger")

    return _redirect_publish_dashboard(period_id=period.id, selected_scope=selected_scope, q=q, status=status)


@main_bp.route("/performance/publish/evaluation/<int:evaluation_id>", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_publish_evaluation(evaluation_id):
    evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
    selected_scope = (request.form.get("scope") or request.args.get("scope") or "").strip()
    q = (request.form.get("q") or request.args.get("q") or "").strip()
    status = (request.form.get("status") or request.args.get("status") or "").strip()
    if not evaluation:
        flash("Değerlendirme kaydı bulunamadı.", "danger")
        return _redirect_publish_dashboard(selected_scope=selected_scope, q=q, status=status)

    try:
        ensure_state_change(current_value=getattr(evaluation, "is_published_to_employee", False), target_value=True, entity_label="Değerlendirme sonucu")
        ok, reason = publish_evaluation(evaluation, current_user)
        if not ok:
            flash(reason, "warning")
            return _redirect_publish_dashboard(period_id=evaluation.period_id, selected_scope=selected_scope, q=q, status=status)

        create_publish_log(evaluation.period_id, current_user.id, "publish", evaluation.id, evaluation.employee_id, "Tekil yayın işlemi ile personele açıldı.")
        db.session.commit()

        try:
            create_snapshot_for_evaluation(evaluation.id, actor_user_id=current_user.id)
        except Exception as snap_exc:
            current_app.logger.exception("Snapshot create failed for single publish: %s", snap_exc)
            flash(f"Yayın tamamlandı ancak snapshot oluşturulurken hata oluştu: {snap_exc}", "warning")

        notification_result = send_published_evaluation_notifications(
            cast(PerformancePeriod, evaluation.period),
            [evaluation.id],
            actor_user_id=current_user.id,
        )
        db.session.commit()

        flash("Sonuç personele yayımlandı.", "success")
        flash(f"Bilgilendirme e-postası sonucu: başarılı {notification_result.get('success_count', 0)}, hatalı {notification_result.get('failed_count', 0)}.", "info")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Tekil yayın sırasında hata oluştu.", "danger")

    return _redirect_publish_dashboard(period_id=evaluation.period_id, selected_scope=selected_scope, q=q, status=status)


@main_bp.route("/performance/unpublish/evaluation/<int:evaluation_id>", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_unpublish_evaluation(evaluation_id):
    evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
    selected_scope = (request.form.get("scope") or request.args.get("scope") or "").strip()
    q = (request.form.get("q") or request.args.get("q") or "").strip()
    status = (request.form.get("status") or request.args.get("status") or "").strip()
    if not evaluation:
        flash("Değerlendirme kaydı bulunamadı.", "danger")
        return _redirect_publish_dashboard(selected_scope=selected_scope, q=q, status=status)

    try:
        ensure_state_change(current_value=getattr(evaluation, "is_published_to_employee", False), target_value=False, entity_label="Değerlendirme sonucu")
        ok, reason = unpublish_evaluation(evaluation, current_user)
        if not ok:
            flash(reason, "warning")
            return _redirect_publish_dashboard(period_id=evaluation.period_id, selected_scope=selected_scope, q=q, status=status)

        create_publish_log(evaluation.period_id, current_user.id, "unpublish", evaluation.id, evaluation.employee_id, "Tekil yayından kaldırma işlemi uygulandı.")
        db.session.commit()
        flash("Sonuç yayından kaldırıldı.", "success")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Tekil yayından kaldırma sırasında hata oluştu.", "danger")

    return _redirect_publish_dashboard(period_id=evaluation.period_id, selected_scope=selected_scope, q=q, status=status)


@main_bp.route("/performance/publish/logs/export/excel")
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_publish_logs_export_excel():
    period_id = request.args.get("period_id", type=int)
    action_type = (request.args.get("log_action") or "").strip()
    actor_q = (request.args.get("log_actor") or "").strip()
    employee_q = (request.args.get("log_employee") or "").strip()
    selected_scope = (request.args.get("scope") or "").strip()
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    scope_ctx = build_surface_scope_context(current_user, selected_scope)
    scope_employee_ids = scope_ctx.get("employee_ids") or []
    period = db.session.get(PerformancePeriod, period_id) if period_id else None

    try:
        query = PerformancePublishLog.query
        if scope_employee_ids:
            query = query.filter(PerformancePublishLog.employee_id.in_(scope_employee_ids))
        if period_id:
            query = query.filter(PerformancePublishLog.period_id == period_id)
        if action_type:
            query = query.filter(PerformancePublishLog.action_type == action_type)

        logs = query.order_by(PerformancePublishLog.created_at.desc(), PerformancePublishLog.id.desc()).all()
        logs = _filter_publish_logs(logs, log_actor=actor_q, log_employee=employee_q)

        excel_rows = []
        for log in logs:
            actor_name = "-"
            if log.actor:
                actor_name = log.actor.full_name or f"{log.actor.ad or ''} {log.actor.soyad or ''}".strip() or "-"
            employee_name = "-"
            employee_sicil = "-"
            if log.employee:
                employee_name = log.employee.full_name or f"{log.employee.ad or ''} {log.employee.soyad or ''}".strip() or "-"
                employee_sicil = log.employee.sicil_no or "-"
            period_title = log.period.title if log.period else "-"
            excel_rows.append([
                log.created_at.strftime("%d.%m.%Y %H:%M") if log.created_at else "-",
                humanize_publish_log_action(log.action_type),
                period_title,
                employee_name,
                employee_sicil,
                actor_name,
                log.evaluation_id or "-",
                log.note or "-",
            ])

        output = build_styled_excel_bytes(
            title="Yayın Geçmişi",
            headers=["Tarih", "İşlem Türü", "Dönem", "Personel", "Sicil No", "İşlemi Yapan", "Değerlendirme ID", "Not"],
            rows=excel_rows,
            widths={"A": 22, "B": 20, "C": 28, "D": 28, "E": 16, "F": 28, "G": 18, "H": 40},
        )

        return send_file(
            output,
            as_attachment=True,
            download_name=build_period_download_name("bys360_yayin_gecmisi", period, "xlsx"),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        current_app.logger.exception("Yayın geçmişi export hatası: %s", exc)
        flash(f"Yayın geçmişi dışa aktarma sırasında hata oluştu: {humanize_export_exception(exc)}", "danger")
        return _redirect_publish_dashboard(period_id=period_id, selected_scope=selected_scope, q=q, status=status)


