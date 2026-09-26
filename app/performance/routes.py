from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, cast

from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import PerformancePeriod, PerformanceWeightConfig, User
from app.route_registry import main_bp
from app.route_support import (
    admin_required,
    manager_required,
    menu_key_required,
    safe_db_rollback,
    safe_render,
)
from app.services.ai.dashboard_panels import (
    build_hierarchy_ai_panel,
    build_hierarchy_assignment_person_ai_panel,
    build_hierarchy_bulk_edit_ai_panel,
    build_hierarchy_tree_ai_panel,
)
from app.services.auto_hierarchy_service import auto_apply_manager_chains
from app.services.hierarchy_admin_service import sync_organization_units_from_users
from app.services.performance.context import build_period_weight_context, list_performance_periods
from app.services.performance.reason_codes import (
    is_informational_reason,
    reason_message,
    reason_payload,
)
from app.services.performance_service import (
    _safe_str,
    analyze_hierarchy_rows,
    generate_assignments_for_active_period,
    get_period_level_3_flags,
    normalize_weight_inputs,
    recalculate_all_evaluations,
)
from app.services.personnel_sync_service import canonical_role_value

"""Performans hiyerarşi route ailesi — ağaç, atama, ayar, tekil düzenleme."""
logger = logging.getLogger(__name__)

def _build_surface_scope_context(user, raw_scope):
    """Surface scope context üretimini import anından çağrı anına taşır.

    view_helpers henüz yüklenirken performance route ailesi import edildiğinde
    circular import oluşmaması için gerçek helper import_module ile geç çağrılır.
    """
    from importlib import import_module

    helper = import_module("app.view_helpers").build_surface_scope_context
    return helper(user, raw_scope)


def _message_text(item):
    return reason_message(item)


def _is_info_message(item):
    """Gerçek zincir eksikleri ile bilgilendirme notlarını ayırır.

    Faz B ile bilgi notları metin eşleştirmesine göre değil, ortak reason_code
    çözümleyicisine göre değerlendirilir. Böylece Unicode/ASCII farkı veya
    kullanıcıya gösterilen metnin değişmesi ekran davranışını bozmaz.
    """
    return is_informational_reason(item)

def _dedupe_messages(items):
    seen = set()
    result = []
    for item in list(items or []):
        payload = reason_payload(item)
        message = payload.get("message") or _message_text(item)
        key = ((payload.get("code") or ""), message.lower())
        if not message or key in seen:
            continue
        seen.add(key)
        result.append(message)
    return result


def _chain_value(chain, key, default=None):
    if chain is None:
        return default
    if isinstance(chain, dict):
        return chain.get(key, default)
    return getattr(chain, key, default)


def _has_level_3_binding(row, chain, user_obj):
    # 3. amir opsiyoneldir. Ham sicil alanı veya istek bayrağı tek başına
    # bu ekranlarda "3 amirli" kabul etmek için yeterli değildir; yalnızca
    # gerçekten çözümlenmiş seviye 3 yöneticisi varsa görünür olmalıdır.
    return bool(
        _chain_value(chain, "manager_3_id")
        or row.get("manager_3_id")
        or row.get("has_level_3_resolved")
    )


def _get_managers(exclude_user_id=None):
    query = User.query
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    return query.order_by(User.ad.asc(), User.soyad.asc()).all()


@main_bp.route("/performance/hierarchy-tree", endpoint="performance_hierarchy_tree")
@main_bp.route("/performance/hierarchy/tree")
@login_required
@manager_required
@menu_key_required("performance_hierarchy_tree")
def performance_hierarchy_tree():
    try:
        sync_organization_units_from_users(commit=True)
    except Exception as exc:
        safe_db_rollback()
        current_app.logger.exception("Hiyerarşi senkronu sırasında hata: %s", exc)

    period_id = request.args.get("period_id", type=int)
    birim = (request.args.get("birim") or "").strip()
    q = (request.args.get("q") or "").strip()
    scope_ctx = _build_surface_scope_context(current_user, request.args.get("scope"))
    selected_scope = scope_ctx["selected_scope"]
    scope_employee_ids = scope_ctx.get("employee_ids") or []

    periods = list_performance_periods()
    selected_period = db.session.get(PerformancePeriod, period_id) if period_id else None

    base_query = User.query.filter(User.role != "admin")
    if scope_employee_ids:
        base_query = base_query.filter(User.id.in_(scope_employee_ids))

    all_users = base_query.order_by(
        User.ust_birim.asc().nullsfirst(),
        User.birim.asc().nullsfirst(),
        User.ad.asc(),
        User.soyad.asc(),
    ).all()

    query = base_query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                User.ad.ilike(like),
                User.soyad.ilike(like),
                User.email.ilike(like),
                User.sicil_no.ilike(like),
                User.birim.ilike(like),
                User.ust_birim.ilike(like),
                User.unvan.ilike(like),
            )
        )
    if birim:
        query = query.filter(User.birim == birim)

    users = query.order_by(
        User.ust_birim.asc().nullsfirst(),
        User.birim.asc().nullsfirst(),
        User.ad.asc(),
        User.soyad.asc(),
    ).all()

    birimler = sorted({
        (u.birim or "").strip()
        for u in all_users
        if (u.birim or "").strip()
    })

    grouped_tree: OrderedDict[str, OrderedDict[str, list[User]]] = OrderedDict()
    active_count = 0
    passive_count = 0

    for user in users:
        parent_name = (getattr(user, "ust_birim", None) or "Üst Birim Tanımsız").strip() or "Üst Birim Tanımsız"
        child_name = (getattr(user, "birim", None) or "Birim Tanımsız").strip() or "Birim Tanımsız"

        grouped_tree.setdefault(parent_name, OrderedDict())
        grouped_tree[parent_name].setdefault(child_name, [])
        grouped_tree[parent_name][child_name].append(user)

        if bool(getattr(user, "is_active", True)):
            active_count += 1
        else:
            passive_count += 1

    return safe_render(
        "hierarchy_tree.html",
        "<h3>Hiyerarşi Ağacı</h3>",
        periods=periods,
        selected_period=selected_period,
        birimler=birimler,
        selected_birim=birim,
        q=q,
        grouped_tree=grouped_tree,
        total_user_count=len(users),
        scope_total_user_count=len(all_users),
        parent_count=len(grouped_tree),
        active_count=active_count,
        passive_count=passive_count,
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_option_pairs=scope_ctx.get("scope_option_pairs"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        ai_hierarchy_tree_panel=build_hierarchy_tree_ai_panel(
            grouped_tree=grouped_tree,
            users=users,
            q=q,
            birim=birim,
            scope_label=scope_ctx.get("scope_label"),
            total_user_count=len(all_users),
        ),
    )


@main_bp.route("/performance/hierarchy-tree-legacy", endpoint="hierarchy_tree")
@login_required
@manager_required
@menu_key_required("performance_hierarchy_tree")
def hierarchy_tree_legacy():
    return redirect(url_for("main.performance_hierarchy_tree", **cast("dict[str, Any]", request.args.to_dict(flat=True))))


@main_bp.route("/performance/hierarchy-assignments", methods=["GET", "POST"], endpoint="performance_hierarchy_assignments")
@main_bp.route("/performance/hierarchy-assignments-legacy", methods=["GET", "POST"], endpoint="hierarchy_assignments")
@login_required
@admin_required
@menu_key_required("performance_hierarchy_assignments")
def performance_hierarchy_assignments_alias():
    period_id = request.values.get("period_id", type=int)
    q = (request.values.get("q") or "").strip()
    birim = (request.values.get("birim") or "").strip()

    base_query = User.query.filter(User.role != "admin")
    if q:
        like = f"%{q}%"
        base_query = base_query.filter(
            or_(
                User.ad.ilike(like),
                User.soyad.ilike(like),
                User.email.ilike(like),
                User.sicil_no.ilike(like),
                User.birim.ilike(like),
                User.ust_birim.ilike(like),
                User.unvan.ilike(like),
            )
        )
    if birim:
        base_query = base_query.filter(User.birim == birim)

    personnel = base_query.order_by(
        User.ust_birim.asc().nullsfirst(),
        User.birim.asc().nullsfirst(),
        User.ad.asc(),
        User.soyad.asc(),
    ).all()
    all_users = _get_managers()
    user_by_sicil = {(_safe_str(getattr(u, "sicil_no", ""))): u for u in all_users if _safe_str(getattr(u, "sicil_no", ""))}

    selected_user_id = request.values.get("user_id", type=int)
    if not selected_user_id and personnel:
        selected_user_id = personnel[0].id
    selected_user = db.session.get(User, selected_user_id) if selected_user_id else None

    if request.method == "POST":
        target_user_id = request.form.get("user_id", type=int)
        target_user = db.session.get(User, target_user_id) if target_user_id else None
        if not target_user:
            flash("Personel bulunamadı.", "danger")
            return redirect(url_for("main.hierarchy_assignments", q=q, birim=birim, period_id=period_id))
        try:
            manager_1_id = request.form.get("manager_1_id", type=int)
            manager_2_id = request.form.get("manager_2_id", type=int)
            manager_3_id = request.form.get("manager_3_id", type=int)

            manager_1 = db.session.get(User, manager_1_id) if manager_1_id else None
            manager_2 = db.session.get(User, manager_2_id) if manager_2_id else None
            manager_3 = db.session.get(User, manager_3_id) if manager_3_id else None

            target_user.yonetici_sicil = _safe_str(getattr(manager_1, "sicil_no", "")) or None
            target_user.ikinci_yonetici_sicil = _safe_str(getattr(manager_2, "sicil_no", "")) or None
            target_user.ucuncu_yonetici_sicil = _safe_str(getattr(manager_3, "sicil_no", "")) or None
            db.session.commit()

            active_period = db.session.get(PerformancePeriod, period_id) if period_id else None
            if not active_period:
                active_period = PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
            if active_period:
                generate_assignments_for_active_period(period_id=active_period.id, actor_user_id=current_user.id)

            flash("Amir atamaları explicit zincir kaynağı olarak kaydedildi.", "success")
            return redirect(url_for("main.hierarchy_assignments", user_id=target_user.id, q=q, birim=birim, period_id=period_id))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            safe_db_rollback()
            flash("Amir atamaları kaydedilirken hata oluştu.", "danger")
            return redirect(url_for("main.hierarchy_assignments", user_id=target_user_id, q=q, birim=birim, period_id=period_id))

    analysis_rows = analyze_hierarchy_rows(period_id)
    # Admin kullanıcıların amir zinciri olmaz — servisten gelseler bile listeden çıkar.
    analysis_rows = [r for r in analysis_rows if getattr(r.get("user"), "role", None) != "admin"]
    row_map = {getattr(row.get("user"), "id", None): row for row in analysis_rows}
    # is_single_manager_case=True ve baskan rolü özel kurallar — "eksik" sayılmaz.
    def _is_chain_exempt(row) -> bool:
        u = row.get("user")
        rv = canonical_role_value(getattr(u, "role", "") or "personel")
        return bool(row.get("is_single_manager_case")) or rv == "baskan"

    incomplete_users = [
        row.get("user") for row in analysis_rows
        if row.get("issues") and not _is_chain_exempt(row)
    ][:20]
    complete_count = sum(1 for row in analysis_rows if not row.get("issues") or _is_chain_exempt(row))
    incomplete_count = sum(1 for row in analysis_rows if row.get("issues") and not _is_chain_exempt(row))

    selected_manager_1_id = None
    selected_manager_2_id = None
    selected_manager_3_id = None
    selected_chain_labels = {1: '1. Amir', 2: '2. Amir', 3: '3. Amir'}
    selected_flow_label = '-'
    if selected_user:
        # BYS360_EXPLICIT_MANAGER_CHAIN_V2
        # Dropdown seçili değerleri otomatik kural motorundan değil, personel kartında
        # kayıtlı açık amir sicillerinden alınır. Böylece Excel importla gelen
        # yönetici_sicil / ikinci_yönetici_sicil alanları ekranda seçili gelir.
        selected_manager_1_id = getattr(user_by_sicil.get(_safe_str(getattr(selected_user, "yonetici_sicil", None))), "id", None)
        selected_manager_2_id = getattr(user_by_sicil.get(_safe_str(getattr(selected_user, "ikinci_yonetici_sicil", None))), "id", None)
        selected_manager_3_id = getattr(user_by_sicil.get(_safe_str(getattr(selected_user, "ucuncu_yonetici_sicil", None))), "id", None)
        role_value = canonical_role_value(getattr(selected_user, "role", "") or "personel")
        if role_value in {"grup_baskani", "mali_musavir"}:
            selected_chain_labels = {1: '1. Amir (Başkan)', 2: '2. Amir (Başkan Yardımcısı)', 3: '3. Amir'}
            selected_flow_label = '2 → 1'
        elif role_value == "koordinator":
            selected_chain_labels = {1: '1. Amir (Başkan Yardımcısı)', 2: '2. Amir (Grup Başkanı)', 3: '3. Amir'}
            selected_flow_label = '2 → 1'
        else:
            selected_chain_labels = {1: '1. Amir (Grup Başkanı)', 2: '2. Amir (Koordinatör)', 3: '3. Amir'}
            selected_flow_label = '3 → 2 → 1' if selected_manager_3_id else '2 → 1'

    # birimler: ayrı sorgu yerine zaten yüklenmiş personnel listesinden türetilir.
    birimler = sorted({(u.birim or "").strip() for u in personnel if (u.birim or "").strip()})

    return safe_render(
        "hierarchy_assignments.html",
        "<h3>Hiyerarşi Atamaları</h3>",
        personnel=personnel,
        selected_user=selected_user,
        selected_manager_1_id=selected_manager_1_id,
        selected_manager_2_id=selected_manager_2_id,
        selected_manager_3_id=selected_manager_3_id,
        selected_row=row_map.get(getattr(selected_user, "id", None)),
        stats={
            "total_count": len([u for u in all_users if getattr(u, "role", None) != "admin"]),
            "filtered_count": len(personnel),
            "complete_count": complete_count,
            "incomplete_count": incomplete_count,
        },
        q=q,
        selected_birim=birim,
        birimler=birimler,
        all_users=all_users,
        incomplete_users=incomplete_users,
        selected_chain_labels=selected_chain_labels,
        selected_flow_label=selected_flow_label,
    )


@main_bp.route("/performance/hierarchy-settings", methods=["GET", "POST"], endpoint="performance_hierarchy_settings")
@main_bp.route("/performance/hierarchy/settings", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("performance_hierarchy_assignments")
def performance_hierarchy_settings():
    period_ctx = build_period_weight_context(request.values)
    periods = period_ctx["periods"]
    selected_period_id = period_ctx["selected_period_id"]
    selected_period = period_ctx["selected_period"]
    scope_ctx = _build_surface_scope_context(current_user, request.values.get("scope"))
    selected_scope = scope_ctx["selected_scope"]
    scope_employee_ids = scope_ctx.get("employee_ids") or []
    scope_label = scope_ctx.get("scope_label")
    scope_hint = scope_ctx.get("scope_hint")
    scope_options = scope_ctx.get("scope_options") or []
    scope_unit_count = scope_ctx.get("scope_unit_count") or 0

    weight_config = period_ctx["weight_config"]

    if request.method == "POST" and request.form.get("action") == "auto_build_chains":
        try:
            query = User.query.filter(User.role != "admin")
            if scope_employee_ids:
                query = query.filter(User.id.in_(scope_employee_ids))
            target_users = query.order_by(User.id.asc()).all()
            summary = auto_apply_manager_chains(target_users, fill_only_missing=True, commit=True, preserve_explicit_chain=True)  # BYS360_EXPLICIT_MANAGER_CHAIN_V2
            assignment_period_id = selected_period_id
            if not assignment_period_id:
                active_period = PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
                assignment_period_id = active_period.id if active_period else None
            assignment_result = None
            if assignment_period_id:
                assignment_result = generate_assignments_for_active_period(period_id=assignment_period_id, actor_user_id=current_user.id)
            flash(
                f"Excel/veri kartlarından otomatik amir zinciri yeniden kuruldu. Güncellenen: {summary.get('updated_count', 0)}, değişmeyen: {summary.get('skipped_count', 0)}",
                "success",
            )
            if assignment_result and assignment_result.get("ok"):
                flash(
                    f"Aktif dönem görevleri zincire göre otomatik senkronlandı. Oluşturulan/güncellenen görev: {assignment_result.get('created', 0)}, atlanan: {assignment_result.get('skipped', 0)}, gerçek uyarı: {assignment_result.get('warning_count', 0)}.",
                    "success" if not assignment_result.get("warning_count") else "warning",
                )
            elif assignment_result and not assignment_result.get("ok"):
                flash(assignment_result.get("message", "Aktif dönem görevleri senkronlanamadı."), "warning")
            if summary.get("warnings"):
                current_app.logger.warning(
                    "Performans hiyerarsi otomatik zincir ham uyarıları gizlendi: %s",
                    " | ".join(summary["warnings"][:10]),
                )
                flash(
                    f"Otomatik zincir denetiminde {len(summary.get('warnings', []))} kayıt için teknik not üretildi; ham liste kullanıcı ekranında gösterilmedi.",
                    "info",
                )
            return redirect(url_for("main.performance_hierarchy_settings", period_id=selected_period_id, scope=selected_scope))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            safe_db_rollback()
            flash("Otomatik amir zinciri kurulurken hata oluştu.", "danger")
            return redirect(url_for("main.performance_hierarchy_settings", period_id=selected_period_id, scope=selected_scope))

    if request.method == "POST" and request.form.get("action") == "save_weights":
        if not selected_period:
            flash("Önce bir dönem seçiniz.", "warning")
            return redirect(url_for("main.performance_hierarchy_settings"))
        try:
            w1 = int(float(request.form.get("evaluator_1_weight") or 0))
            w2 = int(float(request.form.get("evaluator_2_weight") or 0))
            w3 = int(float(request.form.get("evaluator_3_weight") or 0))
            level_3_enabled = bool(request.form.get("config_level_3_enabled"))
            level_3_scoring_enabled = bool(request.form.get("level_3_scoring_enabled"))

            normalized = normalize_weight_inputs(w1, w2, w3, level_3_enabled, level_3_scoring_enabled)
            i1 = int(round(normalized["evaluator_1_weight"]))
            i2 = int(round(normalized["evaluator_2_weight"]))
            i3 = int(round(normalized["evaluator_3_weight"]))
            diff = 100 - (i1 + i2 + i3)
            i1 += diff

            if not weight_config or weight_config.period_id != selected_period.id:
                weight_config = PerformanceWeightConfig(period_id=selected_period.id, name=f"{selected_period.title} Ağırlıkları")
                db.session.add(weight_config)

            weight_config.evaluator_1_weight = i1
            weight_config.evaluator_2_weight = i2
            weight_config.evaluator_3_weight = i3 if level_3_enabled and level_3_scoring_enabled else 0
            weight_config.level_3_enabled = level_3_enabled
            weight_config.level_3_mode = "scoring" if (level_3_enabled and level_3_scoring_enabled) else ("comment_only" if level_3_enabled else "off")
            weight_config.is_active = True

            selected_period.enable_level_3 = level_3_enabled
            selected_period.enable_level_3_scoring = bool(level_3_enabled and level_3_scoring_enabled)

            db.session.flush()
            recalculated_count = recalculate_all_evaluations(selected_period.id, actor_user_id=current_user.id)
            db.session.commit()
            flash("Dönem ağırlıkları güncellendi.", "success")
            flash(f"Seçili dönem için {recalculated_count} değerlendirme toplamı yeni 3. amir ayarına göre yeniden hesaplandı.", "info")
            return redirect(url_for("main.performance_hierarchy_settings", period_id=selected_period.id, scope=selected_scope))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            safe_db_rollback()
            flash("Ağırlık ayarları kaydedilirken hata oluştu.", "danger")

    analysis_rows = analyze_hierarchy_rows(selected_period.id if selected_period else None)
    # Admin kullanıcıların amir zinciri olmaz — servisten gelseler bile listeden çıkar.
    analysis_rows = [r for r in analysis_rows if getattr(r.get("user"), "role", None) != "admin"]
    if scope_employee_ids:
        analysis_rows = [row for row in analysis_rows if getattr(row.get("user"), "id", None) in scope_employee_ids]
    enriched_rows = []
    missing_count = 0
    complete_count = 0
    for row in analysis_rows:
        chain = row.get("chain")
        raw_issue_items = list(row.get("issue_items") or [])
        raw_info_note_items = list(row.get("info_note_items") or [])
        raw_issues = raw_issue_items or list(row.get("issues") or [])
        raw_warnings = list(row.get("warnings") or [])
        raw_info_notes = raw_info_note_items or list(row.get("info_notes") or [])
        info_notes = _dedupe_messages(
            [*raw_info_notes, *[item for item in [*raw_issues, *raw_warnings] if _is_info_message(item)]]
        )
        issues = _dedupe_messages([item for item in raw_issues if not _is_info_message(item)])
        warnings = _dedupe_messages([item for item in raw_warnings if not _is_info_message(item)])
        user_obj = row.get("user")
        role_value = canonical_role_value(getattr(user_obj, "role", "") or "personel")
        has_level_3 = _has_level_3_binding(row, chain, user_obj)
        is_single = bool(row.get("is_single_manager_case"))

        # Başkan zincire dahil edilmez; is_single_manager_case=True olanlar
        # özel tek amir kuralına tabidir. Her ikisi de "eksik" sayılmaz.
        _exempt_from_missing = is_single or role_value == "baskan"
        if issues and not _exempt_from_missing:
            missing_count += 1
        else:
            complete_count += 1
        info_blob = "\n".join(info_notes).lower()

        if is_single:
            if "hukuk" in info_blob and "tek amir" in info_blob:
                chain_type_label = "Hukuk tek amir"
                flow_label = "1"
                chain_hint = "Amir olan hukuk müşaviri tek değerlendiricidir"
            elif role_value == "baskan_yardimcisi":
                chain_type_label = "Tek amirli"
                flow_label = "1"
                chain_hint = "Başkan tarafından değerlendirilir"
            else:
                chain_type_label = "Tek amirli"
                flow_label = "1"
                chain_hint = "Kurallı özel tek amir akışı"
        elif role_value in {"grup_baskani", "mali_musavir"}:
            user_birim = str(getattr(user_obj, "birim", "") or "").lower()
            user_unvan = str(getattr(user_obj, "unvan", "") or "").lower()
            is_hukuk_chief_row = "hukuk" in user_birim or "hukuk" in user_unvan or "hukuk müşaviri için 1. amir başkan" in info_blob
            chain_type_label = "Başkanlık seviyesi" if not is_hukuk_chief_row else "Hukuk müşaviri özel kuralı"
            flow_label = "2 → 1"
            if is_hukuk_chief_row:
                chain_hint = "1. amir Başkan, 2. amir Başkan Yardımcısı olarak tutulur"
            else:
                chain_hint = "1. amir Başkan, 2. amir Başkan Yardımcısı olarak tutulur"
        elif role_value == "koordinator":
            chain_type_label = "Koordinatör zinciri"
            flow_label = "2 → 1"
            chain_hint = "Slotlar 1. amir Başkan Yardımcısı, 2. amir Grup Başkanıdır; işlem sırası 2 → 1 işler"
        elif has_level_3:
            chain_type_label = "3 amirli"
            flow_label = "3 → 2 → 1"
            chain_hint = "Varsa 3. amirden başlar"
        else:
            chain_type_label = "2 amirli"
            flow_label = "2 → 1"
            chain_hint = "Slotlar 1. amir Grup Başkanı, 2. amir Koordinatördür; işlem sırası 2 → 1 işler"

        weights = row.get("effective_weights") or {}
        weight_summary = "-"
        weight_1 = float(weights.get("evaluator_1_weight", 0) or 0)
        weight_2 = float(weights.get("evaluator_2_weight", 0) or 0)
        weight_3 = float(weights.get("evaluator_3_weight", 0) or 0)
        parts = []
        if weight_1:
            parts.append(f"1. amir %{int(round(weight_1))}")
        if weight_2:
            parts.append(f"2. amir %{int(round(weight_2))}")
        if weight_3:
            parts.append(f"3. amir %{int(round(weight_3))}")
        if parts:
            weight_summary = " • ".join(parts)
        elif has_level_3:
            weight_summary = "3. amir yorumcu / puan katkısı kapalı"

        enriched_rows.append({
            **row,
            "manager_1_name": getattr(chain, "manager_1_name", "-"),
            "manager_2_name": getattr(chain, "manager_2_name", "-"),
            "manager_3_name": getattr(chain, "manager_3_name", "-"),
            "warnings": warnings,
            "info_notes": info_notes,
            "chain_type_label": chain_type_label,
            "flow_label": flow_label,
            "chain_hint": chain_hint,
            "weight_summary": weight_summary,
            "has_level_3": has_level_3,
            "is_single_manager_case": is_single,
            "exempt_from_missing": _exempt_from_missing,
        })

    flags = get_period_level_3_flags(selected_period, weight_config)
    users_query = User.query.filter(User.role != "admin")
    if scope_employee_ids:
        users_query = users_query.filter(User.id.in_(scope_employee_ids))
    users = users_query.order_by(User.ad.asc(), User.soyad.asc()).all()
    manager_candidates = _get_managers()
    ust_birimler = sorted({(u.ust_birim or "").strip() for u in users if (u.ust_birim or "").strip()})
    birimler = sorted({(u.birim or "").strip() for u in users if (u.birim or "").strip()})
    roller = sorted({(u.role or "").strip() for u in users if (u.role or "").strip() and u.role != "admin"})

    return safe_render(
        "hierarchy_settings.html",
        "<h3>Hiyerarşi ve Ağırlık Yönetimi</h3>",
        users=users,
        manager_candidates=manager_candidates,
        periods=periods,
        selected_period=selected_period,
        weight_config=weight_config,
        ust_birimler=ust_birimler,
        birimler=birimler,
        roller=roller,
        analysis_rows=enriched_rows,
        missing_count=missing_count,
        complete_count=complete_count,
        period_level_3_enabled=flags.get("enabled", False),
        period_level_3_scoring_enabled=flags.get("scoring_enabled", False),
        period_level_3_mode=flags.get("mode", "off"),
        selected_scope=selected_scope,
        scope_label=scope_label,
        scope_hint=scope_hint,
        scope_options=scope_options,
        scope_user_count=len(users),
        scope_unit_count=scope_unit_count,
        can_manage_weights=True,
        ai_hierarchy_panel=build_hierarchy_ai_panel(
            analysis_rows=enriched_rows,
            missing_count=missing_count,
            complete_count=complete_count,
            period=selected_period,
            level_3_mode=flags.get("mode", "off"),
            scope_label=scope_label,
        ),
        ai_hierarchy_bulk_panel=build_hierarchy_bulk_edit_ai_panel(
            analysis_rows=enriched_rows,
            period=selected_period,
            scope_label=scope_label,
        ),
    )


@main_bp.route("/performance/hierarchy-assignments/<int:user_id>/edit", methods=["GET", "POST"], endpoint="performance_hierarchy_assignment_edit")
@login_required
@admin_required
@menu_key_required("performance_hierarchy_assignments")
def performance_hierarchy_assignment_edit(user_id):
    user_obj = db.session.get(User, user_id)
    selected_period_id = request.values.get("period_id", type=int)
    selected_scope = (request.values.get("scope") or "all").strip() or "all"
    if not user_obj:
        flash("Personel bulunamadı.", "danger")
        return redirect(url_for("main.performance_hierarchy_settings", period_id=selected_period_id, scope=selected_scope))

    manager_candidates = _get_managers(exclude_user_id=user_id)

    if request.method == "POST":
        try:
            yonetici_sicil = (request.form.get("yonetici_sicil") or "").strip() or None
            ikinci_yonetici_sicil = (request.form.get("ikinci_yonetici_sicil") or "").strip() or None
            ucuncu_yonetici_sicil = (request.form.get("ucuncu_yonetici_sicil") or "").strip() or None
            user_obj.yonetici_sicil = yonetici_sicil
            user_obj.ikinci_yonetici_sicil = ikinci_yonetici_sicil
            user_obj.ucuncu_yonetici_sicil = ucuncu_yonetici_sicil
            db.session.commit()

            assignment_result = None
            if selected_period_id:
                assignment_result = generate_assignments_for_active_period(
                    period_id=selected_period_id,
                    actor_user_id=current_user.id,
                )
            else:
                active_period = PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
                if active_period:
                    assignment_result = generate_assignments_for_active_period(
                        period_id=active_period.id,
                        actor_user_id=current_user.id,
                    )

            flash("Amir zinciri güncellendi.", "success")
            if assignment_result and assignment_result.get("ok"):
                flash("Görevler amir zinciri güncellemesi sonrası yeniden senkronlandı.", "success")
            elif assignment_result and not assignment_result.get("ok"):
                flash(assignment_result.get("message", "Görevler yeniden senkronlanamadı."), "warning")
            return redirect(url_for("main.performance_hierarchy_settings", period_id=selected_period_id, scope=selected_scope))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            safe_db_rollback()
            flash("Amir zinciri kaydedilirken hata oluştu.", "danger")

    return safe_render(
        "hierarchy_assignment_edit.html",
        "<h3>Hiyerarşi Ataması Düzenle</h3>",
        user_obj=user_obj,
        manager_candidates=manager_candidates,
        selected_period_id=selected_period_id,
        selected_scope=selected_scope,
        ai_assignment_person_panel=build_hierarchy_assignment_person_ai_panel(user_obj, manager_candidates),
    )


__all__ = [
    "performance_hierarchy_tree",
    "hierarchy_tree_legacy",
    "performance_hierarchy_assignments_alias",
    "performance_hierarchy_settings",
    "performance_hierarchy_assignment_edit",
]

# BYS360_PERFORMANCE_COMPLETION_PHASE7_SCORECARD_ARCHIVE_BOUND
# Geçmiş yıl karne/puan arşivi phase7_scorecard_archive_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE8_PERIOD_SCOPE_BOUND
# Çoklu dönem ve kapsamlı görev üretimi phase8_period_scope_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE9_REMINDER_BOUND
# Otomatik hatırlatma ve aksatan amir bildirimi phase9_reminder_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE10_INTERIM_GUIDANCE_BOUND
# Dönem içi not + gelişim önerisi bağı phase10_development_guidance_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE11_REPORTING_RISK_BOUND
# Raporlama, dashboard ve risk analizi phase11_reporting_risk_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE12_FINAL_READINESS_BOUND
# Final gate, 10 senaryo testi ve canlı hazırlık phase12_final_readiness_policy sözleşmesini kullanır.
