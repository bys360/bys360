from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp

# BYS360_STUB_AI_V60_FOLLOWUP_IMPORT
from app.services.ai.stub_panel_bridge import attach_followup_ai_panel

# /BYS360_STUB_AI_V60_FOLLOWUP_IMPORT
from app.services.performance.feedback_followup_phase4 import (
    build_followup_context,
    generate_followup_notices,
    get_action_for_user,
    is_manager_user,
    update_followup_action,
)


def _role() -> str:
    return (getattr(current_user, "role", "") or "").strip().lower()


def _is_admin() -> bool:
    return bool(getattr(current_user, "is_admin", False) or _role() in {"admin", "super_admin", "system_admin", "sistem_yoneticisi"})


def _is_superuser() -> bool:
    return bool(getattr(current_user, "is_superuser", False))


def _ctx():
    ctx = build_followup_context(
        current_user_id=getattr(current_user, "id", None),
        current_user_role=_role(),
        is_admin=_is_admin(),
        is_superuser=_is_superuser(),
        due_filter=(request.args.get("filter") or "open").strip(),
        query=(request.args.get("q") or "").strip(),
    )
    # BYS360_STUB_AI_V60_FOLLOWUP_CONTEXT_ATTACH
    return attach_followup_ai_panel(ctx)
    # /BYS360_STUB_AI_V60_FOLLOWUP_CONTEXT_ATTACH


@main_bp.route("/performance/feedback-followup", endpoint="performance_feedback_followup")
@main_bp.route("/performans/eylem-plani-takibi", endpoint="performance_feedback_followup_tr")
@login_required
def performance_feedback_followup():
    return render_template("performance/feedback_followup_phase4.html", **_ctx())


@main_bp.route("/performance/feedback-followup/generate-notices", methods=["POST"], endpoint="performance_feedback_followup_generate_notices")
@login_required
def performance_feedback_followup_generate_notices():
    if not is_manager_user(_role(), is_admin=_is_admin(), is_superuser=_is_superuser()):
        flash("Takip bildirimi üretme yetkiniz bulunmamaktadır.", "danger")
        return redirect(url_for("main.performance_feedback_followup"))
    result = generate_followup_notices(
        current_user_id=getattr(current_user, "id", None),
        current_user_role=_role(),
        is_admin=_is_admin(),
        is_superuser=_is_superuser(),
        days_ahead=7,
    )
    if result.get("ok"):
        flash(f"Takip bildirimi kontrolü tamamlandı. Oluşturulan kayıt: {result.get('created', 0)}", "success")
    else:
        flash(result.get("reason") or "Takip bildirimi üretilemedi.", "warning")
    return redirect(url_for("main.performance_feedback_followup"))


@main_bp.route("/performance/feedback-followup/actions/<int:action_id>/quick-update", methods=["POST"], endpoint="performance_feedback_followup_quick_update")
@login_required
def performance_feedback_followup_quick_update(action_id: int):
    action = get_action_for_user(
        action_id,
        current_user_id=getattr(current_user, "id", None),
        current_user_role=_role(),
        is_admin=_is_admin(),
        is_superuser=_is_superuser(),
    )
    if not action:
        flash("Eylem planı bulunamadı veya bu kayda erişim yetkiniz yok.", "danger")
        return redirect(url_for("main.performance_feedback_followup"))
    # update_followup_action returns None only when the update failed and was rolled back.
    if update_followup_action(action_id, request.form) is None:
        flash("Eylem planı takip bilgisi kaydedilemedi. Lütfen tekrar deneyin.", "danger")
    else:
        flash("Eylem planı takip bilgisi güncellendi.", "success")
    return redirect(url_for("main.performance_feedback_followup"))
