from __future__ import annotations

import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import PerformanceEvaluation
from app.performance.phase10_development_guidance_ui import (
    build_phase10_meeting_development_context,
    save_phase10_recommendation_from_request,
)
from app.route_registry import main_bp
from app.route_support import manager_required

# BYS360_STUB_AI_V60_DEVELOPMENT_IMPORT
from app.services.ai.stub_panel_bridge import attach_development_guidance_ai_panel

# /BYS360_STUB_AI_V60_DEVELOPMENT_IMPORT
from app.services.performance.meeting_p4_development_guidance import (
    can_manage_development_guidance,
    run_p4_development_guidance,
)

logger = logging.getLogger(__name__)


@main_bp.route("/performance/meeting-development/faz10", methods=["GET", "POST"], endpoint="performance_meeting_p4_development_guidance")
@main_bp.route("/performans/toplanti-gelistirme/faz10-gelisim-rehberi", methods=["GET", "POST"], endpoint="performance_meeting_p4_development_guidance_tr")
@login_required
@manager_required
def performance_meeting_p4_development_guidance():
    if request.method == "POST":
        try:
            # On failure the save already flashed its own warning/error.
            if save_phase10_recommendation_from_request():
                flash("Gelişim rehberi kaydı alındı.", "success")
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            flash("Gelişim rehberi kaydı alınamadı.", "warning")
        return redirect(request.path)

    context = build_phase10_meeting_development_context()
    # BYS360_STUB_AI_V60_DEVELOPMENT_CONTEXT_ATTACH
    context = attach_development_guidance_ai_panel(context)
    # /BYS360_STUB_AI_V60_DEVELOPMENT_CONTEXT_ATTACH
    return render_template('performance/meeting_development_faz10.html', **context)

@main_bp.route("/performance/meeting-development/faz10/apply", methods=["POST"], endpoint="performance_meeting_p4_development_guidance_apply")
@main_bp.route("/performans/toplanti-gelistirme/faz10-gelisim-rehberi/uygula", methods=["POST"], endpoint="performance_meeting_p4_development_guidance_apply_tr")
@login_required
@manager_required
def performance_meeting_p4_development_guidance_apply():
    result = run_p4_development_guidance(actor_user_id=getattr(current_user, "id", None))
    flash(result.message, "success" if result.ok else "warning")
    for warning in result.warnings or []:
        flash(warning, "warning")
    return redirect(url_for("main.performance_meeting_p4_development_guidance"))


@main_bp.route("/performance/scorecard/<int:evaluation_id>/development-note", methods=["POST"], endpoint="performance_scorecard_development_note_save")
@login_required
@manager_required
def performance_scorecard_development_note_save(evaluation_id: int):
    evaluation = PerformanceEvaluation.query.get_or_404(evaluation_id)
    if not can_manage_development_guidance(current_user):
        flash("Gelişim önerisi kaydetme yetkiniz bulunmamaktadır.", "danger")
        return redirect(url_for("main.performance_scorecard_detail", evaluation_id=evaluation.id, period_id=evaluation.period_id or ""))

    # Karne üzerinden eski (P4) not kaydı kaldırıldı: tek kanonik yazıcı Gelişim Rehberi ekranıdır.
    # Eski tür/görünürlük alanlarının kanonik karşılığı olmadığı için içerik dönüştürülmez veya
    # kaydedilmez; kullanıcıya bu açıkça bildirilir.
    flash(
        "Karne üzerinden gelişim notu kaydı kaldırıldı; gönderdiğiniz not kaydedilmedi. "
        "Gelişim önerilerini Gelişim Rehberi ekranından kaydedebilirsiniz.",
        "warning",
    )
    return redirect(url_for("main.performance_meeting_p4_development_guidance"))

# BYS360_PHASE11_DEVELOPMENT_GUIDANCE_ROUTE_POST_READY: Gelişim Rehberi kayıt formu GET/POST uyumlu hale getirildi.
