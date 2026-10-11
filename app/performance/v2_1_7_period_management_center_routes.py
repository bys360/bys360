from __future__ import annotations

import logging
from functools import wraps

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.performance.v2_1_6_category_period_integration import (
    build_assignment_preintegration,
    create_or_update_period_from_plan,
)
from app.services.performance.v2_1_6a_category_ui_cleanup import corporate_gate_label, label_status
from app.services.performance.v2_1_7_period_management_center import (
    build_period_management_center_state,
    create_center_period_plan,
    ensure_period_management_center_ready,
)
from app.services.performance.v2_1_7_period_management_center_gate import (
    run_v2_1_7_period_management_center_gate,
)
from app.services.performance.v2_1_8_period_center_assignment_launch import (
    build_assignment_launch_guard,
    launch_assignments_from_period_center,
)
from app.services.performance.v2_1_8_period_center_assignment_launch_gate import (
    run_v2_1_8_period_center_assignment_launch_gate,
)
from app.services.performance.v2_1_9_period_center_process_notifications import (
    build_period_center_process_state,
    prepare_period_center_notifications,
    run_v2_1_9_period_center_process_gate,
)
from app.services.performance.v2_1_14_period_center_real_summary import (
    build_period_center_real_summary,
    run_v2_1_14_period_center_real_summary_gate,
)
from app.services.performance.v2_1_15_period_selection_status_flow import (
    build_period_center_selection_flow,
    run_v2_1_15_period_selection_status_flow_gate,
)
from app.services.performance.v2_1_16_scope_chain_control_panel import (
    build_scope_chain_control_panel,
    run_v2_1_16_scope_chain_control_panel_gate,
)
from app.services.performance.v2_1_17_reminder_approval_prep import (
    build_reminder_approval_prep_state,
    prepare_reminder_approval_preview,
    run_v2_1_17_reminder_approval_prep_gate,
)
from app.services.performance.v2_1_18_executive_view import (
    build_period_center_executive_view,
    collect_user_role_terms,
    run_v2_1_18_executive_view_gate,
)
from app.services.performance.v2_1_19_admin_workflow import (
    build_period_center_admin_workflow,
    run_v2_1_19_admin_workflow_gate,
)
from app.services.performance.v2_1_20_final_gate_language_cleanup import (
    build_period_center_final_gate,
    run_v2_1_20_final_gate,
)

logger = logging.getLogger(__name__)

# BYS360_PERFORMANCE_V2_1_21_PERIOD_CENTER_ROLE_MATRIX_HELPERS_BEGIN
PERIOD_CENTER_MENU_KEY = "performance_period_management_center"
_PERIOD_CENTER_OPERATOR_ROLES = {
    "admin", "administrator", "super_admin", "system_admin", "sistem_yoneticisi",
    "grup_baskani", "mali_musavir", "performans_yetkilisi", "performance_officer",
    "ik", "insan_kaynaklari", "personel_yetkilisi",
}


def _period_center_norm(value):
    text = str(value or "").strip().lower()
    return (text
            .replace("İ", "i").replace("ı", "i")
            .replace("ğ", "g").replace("ü", "u").replace("ş", "s")
            .replace("ö", "o").replace("ç", "c")
            .replace(" ", "_").replace("-", "_"))


def _is_period_center_operator_user(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return True
    terms = set()
    try:
        for term in collect_user_role_terms(user):
            terms.add(_period_center_norm(term))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        pass
    # R05/R1: the stored role only; title, unvan, position or gorev never create authority.
    for attr in ("role", "role_name", "user_role", "authority_level"):
        try:
            terms.add(_period_center_norm(getattr(user, attr, "")))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
    return bool(terms & _PERIOD_CENTER_OPERATOR_ROLES)
# BYS360_PERFORMANCE_V2_1_21_PERIOD_CENTER_ROLE_MATRIX_HELPERS_END


# BYS360_PERFORMANCE_V2_1_22A_PERIOD_CENTER_ADMIN_ACCESS_BEGIN
_PERIOD_CENTER_MENU_KEY_V222A = "performance_period_management_center"
_PERIOD_CENTER_MENU_DECORATOR_V222A = menu_key_required(_PERIOD_CENTER_MENU_KEY_V222A)
_PERIOD_CENTER_ADMIN_TERMS_V222A = {
    "admin", "administrator", "super_admin", "system_admin", "sistem_yoneticisi",
    "sistem yoneticisi", "sistem_yöneticisi", "yonetici", "yönetici",
}


def _period_center_norm_v222a(value):
    text = str(value or "").strip().lower()
    return (text
            .replace("İ", "i").replace("ı", "i")
            .replace("ğ", "g").replace("ü", "u").replace("ş", "s")
            .replace("ö", "o").replace("ç", "c")
            .replace("-", "_").replace("/", "_").replace(".", "_").strip())


def _period_center_collect_terms_v222a(user):
    terms: set[str] = set()
    if not user:
        return terms
    # R05/R1: the stored role only; title, unvan, position, gorev or username never create authority.
    for attr in ("role", "role_name", "user_role", "authority_level"):
        try:
            terms.add(_period_center_norm_v222a(getattr(user, attr, "")))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
    for rel in ("roles", "user_roles"):
        try:
            values = getattr(user, rel, None)
            if values:
                for item in values:
                    terms.add(_period_center_norm_v222a(getattr(item, "name", item)))
                    terms.add(_period_center_norm_v222a(getattr(item, "role_name", "")))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
    try:
        role_obj = getattr(user, "role", None)
        terms.add(_period_center_norm_v222a(getattr(role_obj, "name", "")))
        terms.add(_period_center_norm_v222a(getattr(role_obj, "role_name", "")))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        pass
    return {t for t in terms if t}


def _period_center_is_admin_user_v222a(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    for attr in ("is_admin", "is_superuser", "is_system_admin", "is_sistem_yoneticisi"):
        try:
            if bool(getattr(user, attr, False)):
                return True
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
    try:
        has_role = getattr(user, "has_role", None)
        if callable(has_role) and any(has_role(role) for role in ("admin", "Admin", "Sistem Yöneticisi", "sistem_yoneticisi")):
            return True
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        pass
    return bool(_period_center_collect_terms_v222a(user) & _PERIOD_CENTER_ADMIN_TERMS_V222A)


def period_center_menu_or_admin_required(view_func):
    menu_protected = _PERIOD_CENTER_MENU_DECORATOR_V222A(view_func)

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if _period_center_is_admin_user_v222a(current_user):
            return view_func(*args, **kwargs)
        return menu_protected(*args, **kwargs)

    return wrapper
# BYS360_PERFORMANCE_V2_1_22A_PERIOD_CENTER_ADMIN_ACCESS_END

@main_bp.route("/performance/v2-1-7-period-management-center", methods=["GET", "POST"])
@main_bp.route("/performans/donem-yonetim-merkezi", methods=["GET", "POST"])
@login_required
@period_center_menu_or_admin_required
def performance_v2_1_7_period_management_center():
    ensure_period_management_center_ready()
    selected_plan = request.args.get("plan") or ""
    selected_category = request.args.get("category") or ""
    if request.method == "POST" and not _is_period_center_operator_user(current_user):
        flash("Bu görünüm izleme amaçlıdır. İşlem yapmak için Admin veya Performans Yetkilisi yetkisi gerekir.", "warning")
        return redirect(url_for("main.performance_v2_1_7_period_management_center", plan=selected_plan, category=selected_category))

    if request.method == "POST":
        action = request.form.get("action") or "prepare_plan"
        try:
            if action in {"prepare_plan", "prepare_and_link", "prepare_link_precheck"}:
                result = create_center_period_plan(
                    category_key=request.form.get("category_key") or "diger",
                    plan_name=request.form.get("plan_name") or None,
                    period_type=request.form.get("period_type") or "special",
                    start_date=request.form.get("start_date") or None,
                    end_date=request.form.get("end_date") or None,
                    notes=request.form.get("notes") or "Performans Dönemi Yönetim Merkezi üzerinden hazırlandı.",
                    created_by=getattr(current_user, "id", None),
                    scope_visibility_mode=request.form.get("scope_visibility_mode") or "summary_only",
                    link_period=action in {"prepare_and_link", "prepare_link_precheck"},
                    activate_period=bool(request.form.get("activate_period")),
                    run_precheck=action == "prepare_link_precheck",
                )
                plan = result.get("plan") or {}
                selected_plan = str(plan.get("plan_key") or "")
                if action == "prepare_plan":
                    flash(f"Dönem hazırlık planı oluşturuldu: {plan.get('plan_name')}", "success")
                elif action == "prepare_and_link":
                    link = result.get("link") or {}
                    if link.get("ok"):
                        flash(f"Dönem hazırlandı ve gerçek performans dönemine bağlandı: {link.get('period_title')}", "success")
                    else:
                        flash(link.get("message") or "Dönem bağlantısı oluşturulamadı.", "warning")
                else:
                    pre = result.get("precheck") or {}
                    summary = pre.get("summary") or {}
                    flash(f"Dönem hazırlandı, bağlandı ve ön kontrol yapıldı. Hazır: {summary.get('ready', 0)}, kontrol gereken: {summary.get('needs_manager_review', 0)}", "success" if pre.get("ok") else "warning")
            elif action == "link_period":
                selected_plan = request.form.get("plan_key") or ""
                result = create_or_update_period_from_plan(
                    selected_plan,
                    created_by=getattr(current_user, "id", None),
                    activate_period=bool(request.form.get("activate_period")),
                )
                if result.get("ok"):
                    flash(f"Plan gerçek performans dönemine bağlandı: {result.get('period_title')}", "success")
                else:
                    flash(result.get("message") or "Dönem bağlantısı oluşturulamadı.", "warning")
            elif action == "precheck":
                selected_plan = request.form.get("plan_key") or ""
                period_id = request.form.get("period_id") or None
                result = build_assignment_preintegration(selected_plan, int(period_id) if period_id else None, write=True)
                summary = result.get("summary") or {}
                if result.get("ok"):
                    flash(f"Ön kontrol tamamlandı. Hazır: {summary.get('ready', 0)}, kontrol gereken: {summary.get('needs_manager_review', 0)}, kapsam uyumsuz: {summary.get('scope_mismatch', 0)}", "success")
                else:
                    flash(result.get("message") or "Ön kontrol tamamlanamadı.", "warning")
            elif action == "launch_assignments":
                selected_plan = request.form.get("plan_key") or ""
                result = launch_assignments_from_period_center(selected_plan, actor_user_id=getattr(current_user, "id", None))
                guard = result.get("guard") or {}
                if result.get("ok"):
                    raw = result.get("result") or {}
                    flash(
                        f"Görev üretimi tamamlandı. Oluşturulan: {raw.get('created', 0)}, güncellenen: {raw.get('updated', 0)}, atlanan: {raw.get('skipped', 0)}, uyarı: {raw.get('warning_count', len(raw.get('warnings', []) or []))}.",
                        "success" if not (raw.get("warnings") or []) else "warning",
                    )
                else:
                    flash(guard.get("message") or result.get("message") or "Görev üretimi güvenlik kontrolünde durduruldu.", "warning")
            elif action == "prepare_reminder_approval":
                selected_plan = request.form.get("plan_key") or selected_plan
                period_id_raw = request.form.get("period_id") or None
                result = prepare_reminder_approval_preview(int(period_id_raw) if period_id_raw else None, due_days=2, limit=80)
                flash(result.get("message") or "Hatırlatma hazırlığı tamamlandı.", "success" if result.get("ok") else "warning")
            elif action == "prepare_notifications":
                selected_plan = request.form.get("plan_key") or ""
                result = prepare_period_center_notifications(selected_plan, actor_user_id=getattr(current_user, "id", None))
                flash(result.get("message") or "Bildirim hazırlığı tamamlandı.", "success" if result.get("ok") else "warning")
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            flash("Dönem yönetim işlemi tamamlanamadı. Lütfen kayıtları kontrol edip tekrar deneyin.", "danger")
        return redirect(url_for("main.performance_v2_1_7_period_management_center", plan=selected_plan, category=selected_category))

    state = build_period_management_center_state(selected_plan, selected_category)
    embedded_summary = build_period_center_real_summary(state)
    period_flow = build_period_center_selection_flow(state, embedded_summary)
    scope_control = build_scope_chain_control_panel(state, limit=80)
    reminder_approval = build_reminder_approval_prep_state(period_id=period_flow.get('selected_period_id'), period_title=period_flow.get('selected_title') or '', due_days=2, limit=60)
    executive_view = build_period_center_executive_view(user=current_user, state=state, embedded_summary=embedded_summary, period_flow=period_flow, scope_control=scope_control, reminder_approval=reminder_approval)
    admin_workflow = build_period_center_admin_workflow(state=state, embedded_summary=embedded_summary, period_flow=period_flow, scope_control=scope_control, reminder_approval=reminder_approval, executive_view=executive_view)
    final_gate = build_period_center_final_gate(state=state, embedded_summary=embedded_summary, period_flow=period_flow, scope_control=scope_control, reminder_approval=reminder_approval, executive_view=executive_view, admin_workflow=admin_workflow)

    # V2.1.9A: Sayfa ilk açılışta süreç/görev istatistiklerini ve bildirim hazırlığını
    # otomatik yüklemez. Bu alanlar plan seçildikten sonra kullanıcı isteğiyle açılır.
    # Böylece V2.1.8A hızlı açılış davranışı korunur.
    show_process = request.args.get("process") == "1"
    process_state = None
    if selected_plan and show_process:
        try:
            process_state = build_period_center_process_state(selected_plan)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            try:
                from app.extensions import db
                db.session.rollback()
            except Exception:
                logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
                pass
            flash("Süreç izleme bilgisi şu anda yüklenemedi. Dönem merkezi açık; detay kontrol daha sonra yeniden denenebilir.", "warning")
            process_state = None

    return safe_render(
        "performance/v2_1_7_period_management_center.html",
        page_title="Performans Dönemi Yönetim Merkezi",
        state=state,
        gate=run_v2_1_7_period_management_center_gate(),
        gate_v218=run_v2_1_8_period_center_assignment_launch_gate(),
        # V2.1.9A: İlk açılışta ALTER/DB yazan ağır gate yok; yalnızca hafif varlık kontrolü.
        gate_v219=run_v2_1_9_period_center_process_gate(),
        # V2.1.8A: İlk açılışta ağır görev üretimi/audit kontrolü çalıştırma.
        launch_guard=build_assignment_launch_guard(selected_plan, rebuild_missing_precheck=False, include_audit=False) if selected_plan else None,
        process_state=process_state,
        embedded_summary=embedded_summary,
        period_flow=period_flow,
        scope_control=scope_control,
        reminder_approval=reminder_approval,
        executive_view=executive_view,
        admin_workflow=admin_workflow,
        final_gate=final_gate,
        gate_v2120=run_v2_1_20_final_gate(final_gate),
        gate_v2119=run_v2_1_19_admin_workflow_gate(admin_workflow),
        gate_v2118=run_v2_1_18_executive_view_gate(executive_view),
        gate_v217=run_v2_1_17_reminder_approval_prep_gate(period_flow.get('selected_period_id')),
        gate_v216=run_v2_1_16_scope_chain_control_panel_gate(state),
        gate_v215=run_v2_1_15_period_selection_status_flow_gate(state, embedded_summary),
        gate_v214=run_v2_1_14_period_center_real_summary_gate(state),
        show_process=show_process,
        label_status=label_status,
        corporate_gate_label=corporate_gate_label,
    )
