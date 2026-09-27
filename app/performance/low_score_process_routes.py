

# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V4
# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V3
# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V2
"""70 altı performans Başkan onay ve personel süreç zinciri ekranları.

# BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN

# BYS360_PHASE6_3_DIRECT_TO_PRESIDENT_APPROVAL
"""
from __future__ import annotations

# BYS360_PHASE6_4_DUPLICATE_ENDPOINT_V4_ROUTES_NORMALIZED
# BYS360_PHASE6_4_DUPLICATE_ENDPOINT_V2_FIX
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import PerformanceLowScoreProcess, PerformancePeriod
from app.route_registry import main_bp
from app.route_support import admin_required, menu_key_required
from app.services.performance.low_score_process_service import (
    add_low_score_process_note,
    build_low_score_period_summary,
    build_low_score_process_rows,
    ensure_low_score_processes_for_period,
    president_approve_process,
    president_reject_process,
    record_first_warning,
    start_second_repeat_admin_process,
)


def _resolve_period(period_id: int | None = None):
    period = db.session.get(PerformancePeriod, period_id) if period_id else None
    if period is None:
        period = PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
    return period


@main_bp.route("/performance/low-score-processes")
@main_bp.route("/performans/70-alti-surecler")
@main_bp.route("/performans/dusuk-performans-surecleri")
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_processes():
    period = _resolve_period(request.args.get("period_id", type=int))
    processes: list[PerformanceLowScoreProcess] = []
    if period:
        result = ensure_low_score_processes_for_period(period, actor_user_id=getattr(current_user, "id", None))
        if not result.get("schema_missing"):
            db.session.commit()
            processes = PerformanceLowScoreProcess.query.filter_by(period_id=period.id).order_by(PerformanceLowScoreProcess.id.asc()).all()
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    rows = build_low_score_process_rows(processes)
    summary = build_low_score_period_summary(period)
    return render_template("performance_low_score_processes.html", period=period, periods=periods, rows=rows, summary=summary)


@main_bp.route("/performance/low-score-processes/sync/<int:period_id>", methods=["POST"])
@main_bp.route("/performans/70-alti-surecler/senkron/<int:period_id>", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_process_sync(period_id: int):
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return redirect(url_for("main.performance_low_score_processes"))
    result = ensure_low_score_processes_for_period(period, actor_user_id=current_user.id)
    db.session.commit()
    if result.get("schema_missing"):
        flash("70 altı süreç tabloları bulunamadı. Önce V2 şema scriptini çalıştırın.", "danger")
    else:
        flash(f"70 altı süreç zinciri kontrol edildi. Oluşturulan/güncellenen kayıt: {result.get('created_or_updated', 0)}", "success")
    return redirect(url_for("main.performance_low_score_processes", period_id=period.id))


def _load_process_or_redirect(process_id: int):
    process = db.session.get(PerformanceLowScoreProcess, process_id)
    if not process:
        flash("Süreç kaydı bulunamadı.", "danger")
        return None
    return process


def _process_redirect(process):
    return redirect(url_for("main.performance_low_score_processes", period_id=getattr(process, "period_id", None)))


@main_bp.route("/performance/low-score-process/<int:process_id>/hr-check", methods=["POST"])
@main_bp.route("/performans/70-alti-surec/<int:process_id>/ik-kontrol", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_hr_check(process_id: int):
    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN
    process = _load_process_or_redirect(process_id)
    if process:
        flash("70 altı süreçler İK/Admin ara onayında beklemez; kayıt doğrudan Başkan/Üst Onay ekranındadır.", "info")
        return _process_redirect(process)
    return redirect(url_for("main.performance_low_score_processes"))
@main_bp.route("/performance/low-score-process/<int:process_id>/president-approve", methods=["POST"])
@main_bp.route("/performans/70-alti-surec/<int:process_id>/baskan-onay", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_president_approve(process_id: int):
    process = _load_process_or_redirect(process_id)
    if process:
        president_approve_process(process, actor=current_user, note=(request.form.get("note") or "").strip() or None)
        db.session.commit()
        flash("Başkan onayı kaydedildi.", "success")
        return _process_redirect(process)
    return redirect(url_for("main.performance_low_score_processes"))


@login_required
@admin_required
@menu_key_required("performance_publish")

@login_required
@admin_required
@menu_key_required("performance_publish")
# BYS360_PHASE6_4_DUPLICATE_ENDPOINT_V3_GUARD: canonical Başkan/Üst Onay iade endpoint
@main_bp.route("/performance/low-score-process/<int:process_id>/president-reject", methods=["POST"])
@main_bp.route("/performans/70-alti-surec/<int:process_id>/baskan-iade", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_president_reject(process_id: int):
    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN
    process = _load_process_or_redirect(process_id)
    if process:
        note_text = (request.form.get("note") or "").strip()
        president_reject_process(process, actor=current_user, note=note_text or None)
        db.session.commit()
        flash("Başkan/Üst Onay iadesi kaydedildi. Yayın kilidi devam ediyor.", "warning")
        return _process_redirect(process)
    return redirect(url_for("main.performance_low_score_processes"))
@main_bp.route("/performance/low-score-process/<int:process_id>/note", methods=["POST"])
@main_bp.route("/performans/70-alti-surec/<int:process_id>/not-ekle", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_add_note(process_id: int):
    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN
    process = _load_process_or_redirect(process_id)
    if process:
        note_text = (request.form.get("note") or "").strip()
        if not note_text:
            flash("Süreç notu boş bırakılamaz.", "warning")
            return _process_redirect(process)
        add_low_score_process_note(process, user_or_id=current_user, note=note_text)
        db.session.commit()
        flash("Süreç notu kaydedildi.", "success")
        return _process_redirect(process)
    return redirect(url_for("main.performance_low_score_processes"))
@main_bp.route("/performance/low-score-process/<int:process_id>/record-warning", methods=["POST"])
@main_bp.route("/performans/70-alti-surec/<int:process_id>/uyari-kaydi", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_record_warning(process_id: int):
    process = _load_process_or_redirect(process_id)
    if process:
        record_first_warning(process, actor=current_user, note=(request.form.get("note") or "").strip() or None)
        db.session.commit()
        flash("Personel uyarı/süreç kaydı oluşturuldu.", "success")
        return _process_redirect(process)
    return redirect(url_for("main.performance_low_score_processes"))
@main_bp.route("/performance/low-score-process/<int:process_id>/start-admin-process", methods=["POST"])
@main_bp.route("/performans/70-alti-surec/<int:process_id>/idari-surec", methods=["POST"])
@login_required
@admin_required
@menu_key_required("performance_publish")
def performance_low_score_start_admin_process(process_id: int):
    process = _load_process_or_redirect(process_id)
    if process:
        start_second_repeat_admin_process(process, actor=current_user, note=(request.form.get("note") or "").strip() or None)
        db.session.commit()
        flash("İkinci 70 altı sonucuna ilişkin idari süreç kaydı oluşturuldu.", "success")
        return _process_redirect(process)
    return redirect(url_for("main.performance_low_score_processes"))


# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_FORCE_ROUTES
# performance_low_score_president_reject / performance_low_score_add_note / performance_low_score_president_approve
# İK/Admin ara onayında beklemez; 70 altı kayıt doğrudan Başkan/Üst Onay ekranına düşer.
