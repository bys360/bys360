from __future__ import annotations

import logging

from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import (
    EvaluationAssignment,
    OrganizationUnit,
    PerformanceCriteria,
    PerformanceEvaluation,
    PerformanceEvaluationItem,
    PerformancePeriod,
    PerformanceWeightConfig,
    PersonnelCategory,
    User,
)
from app.route_registry import main_bp
from app.route_support import admin_required, ensure_boolean_toggle, menu_key_required, safe_render
from app.security.critical_operations import (
    critical_operation_required,
    frozen_period_generation_refusal,
)
from app.services.ai.dashboard_panels import build_period_form_ai_panel, build_periods_ai_panel
from app.services.hierarchy_admin_service import parse_date
from app.services.performance.assignment_rule_audit import build_assignment_generation_preflight
from app.services.performance.common import _safe_float, get_evaluation_window_state
from app.services.performance.period_delete_service import (
    delete_performance_period_with_related_records,
)
from app.services.performance.period_forms import parse_period_form
from app.services.performance_admin_service import seed_default_performance_criteria
from app.services.performance_service import (
    build_assignment_log_summary,
    build_assignment_unit_summary,
    generate_assignments_for_active_period,
    get_latest_assignment_generation_logs,
)

"""Performans yönetimi admin çekirdek rotaları.

Bu dosya değerlendirme kriterleri, dönem yönetimi ve görev üretimi
akışlarını modüler yapı altında yönetir.
"""
logger = logging.getLogger(__name__)


def _bool_from_form(field_name: str, default: bool = False) -> bool:
    value = request.form.get(field_name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "on", "yes", "evet"}


def _availability_summary(period: PerformancePeriod) -> str:
    pieces = []
    min_presence = _safe_float(getattr(period, "minimum_presence_days_for_evaluation", None), 0.0) or 0.0
    leave_skip = _safe_float(getattr(period, "leave_skip_threshold_days", None), None)
    absence_skip = _safe_float(getattr(period, "absence_skip_threshold_days", None), None)

    if min_presence > 0:
        pieces.append(f"Asgari fiili gün: {min_presence:g}")
    else:
        pieces.append("Asgari fiili gün kuralı kapalı")

    if leave_skip not in (None, "") and leave_skip and leave_skip > 0:
        pieces.append(f"İzin eşiği: {leave_skip:g}")
    else:
        pieces.append("İzin eşiği kapalı")

    if absence_skip not in (None, "") and absence_skip and absence_skip > 0:
        pieces.append(f"Devamsızlık eşiği: {absence_skip:g}")
    else:
        pieces.append("Devamsızlık eşiği kapalı")

    if bool(getattr(period, "auto_skip_if_fully_absent", True)):
        pieces.append("Tam yoklukta otomatik muafiyet açık")
    else:
        pieces.append("Tam yoklukta otomatik muafiyet kapalı")

    if bool(getattr(period, "manager_delegation_required", True)):
        pieces.append("Yönetici izninde vekâlet zorunlu")
    else:
        pieces.append("Yönetici izninde vekâlet opsiyonel")

    window = get_evaluation_window_state(period)
    window_start = window.get("start")
    window_end = window.get("end")
    if window_start and window_end:
        pieces.append(f"Puanlama penceresi: {window_start.strftime('%d.%m.%Y')} - {window_end.strftime('%d.%m.%Y')}")
    due_days = window.get("due_days")
    if due_days:
        pieces.append(f"Görev tamamlanma süresi: {due_days} gün")

    return " • ".join(pieces)

# Dönem arşivleme ihtiyacı ayrıca değerlendirilecektir.

@main_bp.route("/performance/criteria", methods=["GET", "POST"])
@login_required
@admin_required
def performance_criteria():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        weight_raw = (request.form.get("weight") or "").strip()
        sort_order_raw = (request.form.get("sort_order") or "").strip()

        if not name:
            flash("Kriter adı zorunludur.", "warning")
            return redirect(url_for("main.performance_criteria"))

        try:
            weight = float(weight_raw or 0)
            sort_order = int(sort_order_raw or 0)
        except ValueError:
            flash("Ağırlık veya sıralama değeri geçersiz.", "warning")
            return redirect(url_for("main.performance_criteria"))

        try:
            exists = PerformanceCriteria.query.filter(PerformanceCriteria.name.ilike(name)).first()
            if exists:
                flash("Bu kriter zaten mevcut.", "warning")
                return redirect(url_for("main.performance_criteria"))

            db.session.add(
                PerformanceCriteria(
                    name=name,
                    description=description or None,
                    weight=weight,
                    sort_order=sort_order,
                    is_active=True,
                )
            )
            db.session.commit()
            flash("Kriter eklendi.", "success")
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            db.session.rollback()
            flash("Kriter eklenirken hata oluştu.", "danger")

        return redirect(url_for("main.performance_criteria"))

    criteria_list = PerformanceCriteria.query.order_by(
        PerformanceCriteria.sort_order.asc(),
        PerformanceCriteria.id.asc(),
    ).all()
    total_count = len(criteria_list)
    active_count = len([x for x in criteria_list if x.is_active])
    passive_count = len([x for x in criteria_list if not x.is_active])

    return safe_render(
        "criteria.html",
        "<h3>Kriterler</h3>",
        criteria_list=criteria_list,
        total_count=total_count,
        active_count=active_count,
        passive_count=passive_count,
    )

@main_bp.route("/performance/criteria/<int:criteria_id>/edit", methods=["POST"])
@login_required
@admin_required
def performance_criteria_edit(criteria_id):
    criteria = db.session.get(PerformanceCriteria, criteria_id)
    if not criteria:
        flash("Kriter bulunamadı.", "danger")
        return redirect(url_for("main.performance_criteria"))

    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    weight_raw = (request.form.get("weight") or "").strip()
    sort_order_raw = (request.form.get("sort_order") or "").strip()

    if not name:
        flash("Kriter adı zorunludur.", "warning")
        return redirect(url_for("main.performance_criteria"))

    try:
        weight = float(weight_raw or 0)
        sort_order = int(sort_order_raw or 0)
    except ValueError:
        flash("Ağırlık veya sıra değeri geçersiz.", "warning")
        return redirect(url_for("main.performance_criteria"))

    duplicate = PerformanceCriteria.query.filter(
        PerformanceCriteria.name.ilike(name),
        PerformanceCriteria.id != criteria.id,
    ).first()
    if duplicate:
        flash("Bu isimde başka kriter zaten var.", "warning")
        return redirect(url_for("main.performance_criteria"))

    try:
        criteria.name = name
        criteria.description = description or None
        criteria.weight = weight
        criteria.sort_order = sort_order
        db.session.commit()
        flash("Kriter güncellendi.", "success")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Kriter güncellenirken hata oluştu.", "danger")
    return redirect(url_for("main.performance_criteria"))

@main_bp.route("/performance/criteria/<int:criteria_id>/toggle-active", methods=["POST"])
@login_required
@admin_required
def performance_criteria_toggle_active(criteria_id):
    criteria = db.session.get(PerformanceCriteria, criteria_id)
    if not criteria:
        flash("Kriter bulunamadı.", "danger")
        return redirect(url_for("main.performance_criteria"))
    try:
        criteria.is_active = ensure_boolean_toggle(current_value=getattr(criteria, "is_active", False), entity_label="Kriter aktiflik durumu", requested_state=request.form.get("target_state"))
        db.session.commit()
        flash("Kriter durumu güncellendi.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Kriter durumu güncellenirken hata oluştu.", "danger")
    return redirect(url_for("main.performance_criteria"))

@main_bp.route("/performance/criteria/<int:criteria_id>/delete", methods=["POST"])
@login_required
@admin_required
def performance_criteria_delete(criteria_id):
    criteria = db.session.get(PerformanceCriteria, criteria_id)
    if not criteria:
        flash("Kriter bulunamadı.", "danger")
        return redirect(url_for("main.performance_criteria"))
    try:
        related_item = PerformanceEvaluationItem.query.filter_by(criteria_id=criteria.id).first()
        if related_item:
            flash(
                "Bu kriter değerlendirmelerde kullanıldığı için silinemez. Pasif yapmayı tercih edin.",
                "warning",
            )
            return redirect(url_for("main.performance_criteria"))
        db.session.delete(criteria)
        db.session.commit()
        flash("Kriter silindi.", "success")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Kriter silinirken hata oluştu.", "danger")
    return redirect(url_for("main.performance_criteria"))

@main_bp.route("/performance/criteria/seed-defaults", methods=["POST"])
@login_required
@admin_required
def performance_criteria_seed_defaults():
    try:
        added = seed_default_performance_criteria()
        db.session.commit()
        if added > 0:
            flash(
                f"Varsayılan performans kriterleri eklendi. Eklenen kayıt sayısı: {added}",
                "success",
            )
        else:
            flash("Varsayılan performans kriterleri zaten mevcut.", "info")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Kriterler eklenirken hata oluştu.", "danger")
    return redirect(url_for("main.performance_criteria"))

@main_bp.route("/performance/periods")
@login_required
@admin_required
@critical_operation_required("period_manage")
@menu_key_required("performance_periods")
def performance_periods():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()

    query = PerformancePeriod.query.order_by(
        PerformancePeriod.is_active.desc(),
        PerformancePeriod.start_date.desc(),
        PerformancePeriod.id.desc(),
    )

    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                PerformancePeriod.title.ilike(like_q),
                PerformancePeriod.period_type.ilike(like_q),
                PerformancePeriod.description.ilike(like_q),
            )
        )

    periods = query.all()

    if status == "active":
        periods = [p for p in periods if bool(p.is_active)]
    elif status == "inactive":
        periods = [p for p in periods if not bool(p.is_active)]
    elif status == "published":
        periods = [p for p in periods if bool(getattr(p, "results_published", False))]
    elif status == "unpublished":
        periods = [p for p in periods if not bool(getattr(p, "results_published", False))]
    elif status == "locked":
        periods = [p for p in periods if bool(getattr(p, "is_locked", False))]
    elif status == "unlocked":
        periods = [p for p in periods if not bool(getattr(p, "is_locked", False))]

    total_all = PerformancePeriod.query.count()
    active_count = PerformancePeriod.query.filter_by(is_active=True).count()
    published_count = PerformancePeriod.query.filter_by(results_published=True).count()
    locked_count = PerformancePeriod.query.filter_by(is_locked=True).count()

    period_rows = []
    for period in periods:
        weight_config = (
            PerformanceWeightConfig.query
            .filter_by(period_id=period.id, is_active=True)
            .order_by(PerformanceWeightConfig.id.desc())
            .first()
        )

        if weight_config:
            weight_summary = (
                f"1. Amir %{weight_config.evaluator_1_weight:.0f} • "
                f"2. Amir %{weight_config.evaluator_2_weight:.0f} • "
                f"3. Amir %{weight_config.evaluator_3_weight:.0f}"
            )
        else:
            weight_summary = "Varsayılan ağırlık kullanılacak"

        assignment_count = EvaluationAssignment.query.filter_by(period_id=period.id).count()
        evaluation_count = PerformanceEvaluation.query.filter_by(period_id=period.id).count()
        completed_count = PerformanceEvaluation.query.filter_by(period_id=period.id, status="tamamlandi").count()
        log_payload = get_latest_assignment_generation_logs(period.id, limit=800)
        coverage_summary = log_payload.get("summary", build_assignment_log_summary([]))

        period_rows.append({
            "period": period,
            "weight_summary": weight_summary,
            "availability_summary": _availability_summary(period),
            "assignment_count": assignment_count,
            "evaluation_count": evaluation_count,
            "completed_count": completed_count,
            "coverage_summary": coverage_summary,
            "coverage_latest_created_at": log_payload.get("created_at"),
            "coverage_unit_rows": build_assignment_unit_summary(log_payload.get("rows", []), top_n=3),
        })

    ai_periods_panel = build_periods_ai_panel(
        period_rows=period_rows,
        totals={
            "total_count": total_all,
            "active_count": active_count,
            "published_count": published_count,
            "locked_count": locked_count,
        },
        selected_status=status,
        q=q,
    )

    return safe_render(
        "periods.html",
        "<h3>Dönemler</h3>",
        period_rows=period_rows,
        periods=periods,
        total_count=total_all,
        active_count=active_count,
        published_count=published_count,
        locked_count=locked_count,
        selected_status=status,
        q=q,
        ai_periods_panel=ai_periods_panel,
    )


def _unique_clean_labels(*value_groups, limit: int = 400) -> list[str]:
    """Dönem kapsam seçimlerinde gösterilecek güvenli ve tekrarsız etiket listesi."""
    labels: list[str] = []
    seen: set[str] = set()
    for values in value_groups:
        for value in values or []:
            label = str(value or "").strip()
            if not label:
                continue
            key = label.casefold()
            if key in seen:
                continue
            seen.add(key)
            labels.append(label)
            if len(labels) >= limit:
                return sorted(labels, key=lambda item: item.casefold())
    return sorted(labels, key=lambda item: item.casefold())


def _scalar_distinct(model_column) -> list[str]:
    try:
        rows = (
            db.session.query(model_column)
            .filter(model_column.isnot(None))
            .filter(model_column != "")
            .distinct()
            .order_by(model_column.asc())
            .all()
        )
        return [row[0] for row in rows]
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Dönem kapsam seçim listesi okunamadı. | exc=%s", exc)
        return []


def _build_period_create_scope_options() -> dict[str, list]:
    """Yeni dönem ekranı için personel, birim, üst birim ve kategori seçimlerini hazırlar."""
    default_categories = [
        "Güvenlik",
        "Temizlik",
        "İdari Personel",
        "Teknik Personel",
        "Deneme Süreli Personel",
        "Ayrılacak Personel",
        "Diğer",
    ]

    personnel_options: list[dict[str, str]] = []
    try:
        users = (
            User.query
            .filter(User.is_active == True)  # noqa: E712
            .order_by(User.ad.asc(), User.soyad.asc(), User.sicil_no.asc())
            .limit(1200)
            .all()
        )
        for user in users:
            name = (getattr(user, "full_name", None) or f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}").strip()
            sicil_no = str(getattr(user, "sicil_no", "") or "").strip()
            if not name or not sicil_no:
                continue
            category = ""
            if getattr(user, "performance_category", None):
                category = getattr(user.performance_category, "name", "") or ""
            category = category or getattr(user, "personnel_category", "") or ""
            personnel_options.append({
                "name": name,
                "sicil_no": sicil_no,
                "birim": getattr(user, "birim", "") or "",
                "ust_birim": getattr(user, "ust_birim", "") or "",
                "category": category,
            })
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Yeni dönem personel seçim listesi hazırlanamadı. | exc=%s", exc)

    unit_labels_from_users = _scalar_distinct(User.birim)
    upper_unit_labels_from_users = _scalar_distinct(User.ust_birim)

    org_unit_labels: list[str] = []
    org_upper_unit_labels: list[str] = []
    try:
        org_units = (
            OrganizationUnit.query
            .filter(OrganizationUnit.is_active == True)  # noqa: E712
            .order_by(OrganizationUnit.sort_order.asc(), OrganizationUnit.name.asc())
            .limit(1200)
            .all()
        )
        org_unit_labels = [unit.name for unit in org_units if getattr(unit, "name", None)]
        org_upper_unit_labels = [unit.name for unit in org_units if getattr(unit, "name", None) and not getattr(unit, "parent_id", None)]
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Organizasyon birim seçim listesi hazırlanamadı. | exc=%s", exc)

    category_labels_from_users = _scalar_distinct(User.personnel_category)
    category_labels_from_table: list[str] = []
    try:
        category_labels_from_table = [
            category.name for category in (
                PersonnelCategory.query
                .filter(PersonnelCategory.is_active == True)  # noqa: E712
                .order_by(PersonnelCategory.sort_order.asc(), PersonnelCategory.name.asc())
                .all()
            )
            if getattr(category, "name", None)
        ]
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Personel kategori seçim listesi hazırlanamadı. | exc=%s", exc)

    return {
        "personnel_scope_options": personnel_options,
        "unit_scope_options": _unique_clean_labels(unit_labels_from_users, org_unit_labels),
        "upper_unit_scope_options": _unique_clean_labels(upper_unit_labels_from_users, org_upper_unit_labels),
        "category_scope_options": _unique_clean_labels(default_categories, category_labels_from_table, category_labels_from_users),
    }

@main_bp.route("/performance/periods/create", methods=["GET", "POST"])
@login_required
@admin_required
@critical_operation_required("period_manage")
@menu_key_required("performance_periods")
def performance_period_create():
    if request.method == "POST":
        try:
            period_payload = parse_period_form(request.form, parse_date=parse_date)
            db.session.add(
                PerformancePeriod(
                    **period_payload,
                    is_active=False,
                    is_locked=False,
                    results_published=False,
                )
            )
            db.session.commit()
            flash("Dönem oluşturuldu.", "success")
            return redirect(url_for("main.performance_periods"))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            db.session.rollback()
            flash("Dönem oluşturulurken hata oluştu.", "danger")
            return redirect(url_for("main.performance_period_create"))

    return safe_render(
        "period_create.html",
        "<h3>Yeni Dönem</h3>",
        ai_period_form_panel=build_period_form_ai_panel(),
        **_build_period_create_scope_options(),
    )

@main_bp.route("/performance/periods/<int:period_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
@critical_operation_required("period_manage")
@menu_key_required("performance_periods")
def performance_period_edit(period_id):
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return redirect(url_for("main.performance_periods"))

    if request.method == "POST":
        try:
            period_payload = parse_period_form(request.form, parse_date=parse_date)
            for field_name, value in period_payload.items():
                setattr(period, field_name, value)
            db.session.commit()
            flash("Dönem güncellendi.", "success")
            return redirect(url_for("main.performance_periods"))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            db.session.rollback()
            flash("Dönem güncellenirken hata oluştu.", "danger")
            return redirect(url_for("main.performance_period_edit", period_id=period.id))

    return safe_render("period_edit.html", "<h3>Dönem Düzenle</h3>", period=period, ai_period_form_panel=build_period_form_ai_panel(period))

@main_bp.route("/performance/periods/<int:period_id>/toggle-active", methods=["POST"])
@login_required
@admin_required
@critical_operation_required("period_activate")
@menu_key_required("performance_periods")
def performance_period_toggle_active(period_id):
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return redirect(url_for("main.performance_periods"))

    try:
        target_state = ensure_boolean_toggle(current_value=getattr(period, "is_active", False), entity_label="Dönem aktiflik durumu", requested_state=request.form.get("target_state"))
        if target_state:
            (
                PerformancePeriod.query
                .filter(PerformancePeriod.is_active.is_(True), PerformancePeriod.id != period.id)
                .update({PerformancePeriod.is_active: False}, synchronize_session=False)
            )
            db.session.flush()
        period.is_active = target_state
        db.session.commit()
        flash("Dönem aktiflik durumu güncellendi.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Dönem aktiflik durumu güncellenirken hata oluştu.", "danger")

    return redirect(url_for("main.performance_periods"))

@main_bp.route("/performance/periods/<int:period_id>/toggle-lock", methods=["POST"])
@login_required
@admin_required
@critical_operation_required("period_lock")
@menu_key_required("performance_periods")
def performance_period_toggle_lock(period_id):
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return redirect(url_for("main.performance_periods"))

    try:
        period.is_locked = ensure_boolean_toggle(current_value=getattr(period, "is_locked", False), entity_label="Dönem kilit durumu", requested_state=request.form.get("target_state"))
        db.session.commit()

        if period.is_locked:
            flash("Dönem kilitlendi.", "success")
        else:
            flash("Dönem kilidi kaldırıldı.", "success")

    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Dönem kilit durumu güncellenirken hata oluştu.", "danger")

    return redirect(url_for("main.performance_periods"))

@main_bp.route("/performance/periods/<int:period_id>/toggle-publish", methods=["POST"])
@login_required
@admin_required
@critical_operation_required("period_publish")
@menu_key_required("performance_publish")
def performance_period_toggle_publish(period_id):
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        flash("Dönem bulunamadı.", "danger")
        return redirect(url_for("main.performance_periods"))

    try:
        period.results_published = ensure_boolean_toggle(current_value=getattr(period, "results_published", False), entity_label="Dönem yayın durumu", requested_state=request.form.get("target_state"))
        db.session.commit()
        flash("Dönem yayın durumu güncellendi.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Dönem yayın durumu güncellenirken hata oluştu.", "danger")

    return redirect(url_for("main.performance_periods"))

@main_bp.route("/performance/periods/<int:period_id>/delete", methods=["POST"])
@login_required
@admin_required
@critical_operation_required("period_delete")
@menu_key_required("performance_periods")
def performance_period_delete(period_id):
    try:
        result = delete_performance_period_with_related_records(period_id, actor=current_user)
        if result.ok:
            flash(result.message or "Dönem silindi.", "success")
        else:
            flash(result.message or "Dönem bulunamadı.", "warning")
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        flash("Dönem silinirken hata oluştu.", "danger")

    return redirect(url_for("main.performance_periods"))

@main_bp.route("/performance/assignments/generate", methods=["GET", "POST"])
@main_bp.route("/performance/evaluation-tasks/generate", methods=["GET", "POST"])
@login_required
@admin_required
@critical_operation_required("assignment_generate")
@menu_key_required("performance_task_management")
def performance_generate_assignments():
    periods = PerformancePeriod.query.order_by(
        PerformancePeriod.start_date.desc()
    ).all()

    if request.method == "POST":
        period_id = request.form.get("period_id", type=int)
        period = db.session.get(PerformancePeriod, period_id)

        if not period:
            flash("Geçerli bir dönem seçiniz.", "danger")
            return redirect(url_for("main.performance_generate_assignments"))
        # P0 (M-1 Q3): kilitli/yayımlanmış dönemde görev üretimi yok (gerçek admin dahil).
        refusal = frozen_period_generation_refusal(period, url_for("main.performance_generate_assignments"))
        if refusal is not None:
            return refusal

        try:
            preflight = build_assignment_generation_preflight(period_id=period.id)
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            db.session.rollback()
            flash("Görev üretimi ön kontrolü sırasında hata oluştu.", "danger")
            return redirect(url_for("main.performance_generate_assignments"))

        if not preflight.get("can_auto_repair", False):
            flash(
                "Görev üretimi durduruldu: tamamlanmış görevlerle çakışan veya bloklayan zincir farkı var. "
                "Önce Performans Zincir Ön Kontrol raporunu inceleyin; tamamlanmış kayıtlar otomatik ezilmez.",
                "danger",
            )
            current_app.logger.error(
                "Performans görev üretimi ön kontrol blokladı | period=%s | completed_conflict=%s | blocking=%s | issue_count=%s",
                period.id,
                preflight.get("completed_conflict_count"),
                preflight.get("blocking_issue_count"),
                preflight.get("issue_count"),
            )
            return redirect(url_for("main.performance_generate_assignments"))

        try:
            result = generate_assignments_for_active_period(period_id=period.id)
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            db.session.rollback()
            flash("Görev üretimi sırasında hata oluştu.", "danger")
            return redirect(url_for("main.performance_generate_assignments"))

        if not result.get("ok"):
            flash(result.get("message", "Görev üretilemedi."), "warning")
            return redirect(url_for("main.performance_generate_assignments"))

        created = int(result.get("created", 0) or 0)
        updated = int(result.get("updated", 0) or 0)
        skipped = int(result.get("skipped", 0) or 0)
        deduped = int(result.get("deduped", 0) or 0)
        warnings = result.get("warnings", [])
        info_count = int(result.get("info_count", 0) or 0)
        breakdown = result.get("breakdown", {}) or {}
        president_excluded = breakdown.get("president_excluded", 0)
        exempted = breakdown.get("exempted", 0)
        chain_issue = breakdown.get("chain_issue", 0)
        inactive_manager = breakdown.get("inactive_manager", 0)
        uncovered = breakdown.get("uncovered", 0)
        delegation_warning = breakdown.get("delegation_warning", 0)

        summary_text = (
            f"Görev üretimi tamamlandı. Oluşturulan: {created}, güncellenen: {updated}, atlanan/muaf kalan personel: {skipped}, "
            f"temizlenen duplicate: {deduped}, başkan dışı bırakıldı: {president_excluded}, "
            f"zincir sorunu: {chain_issue}, pasif amir: {inactive_manager}, "
            f"izin/devamsızlık muafiyeti: {exempted}, vekâletsiz amir: {uncovered}, "
            f"bloklamayan vekâlet uyarısı: {delegation_warning}, uyarı sayısı: {len(warnings)}, "
            f"bilgi amaçlı istisna: {info_count}."
        )

        flash(summary_text, "warning" if warnings else "success")
        if warnings:
            current_app.logger.warning(
                "Performans görev üretimi ham uyarı örnekleri gizlendi: %s",
                " | ".join(warnings[:10]),
            )
            flash(
                "Ham uyarı metinleri kullanıcı ekranında gizlendi. Detaylar yönetici logunda tutuldu.",
                "info",
            )

        return redirect(url_for("main.performance_evaluation_tasks"))

    return safe_render(
        "assignment_generate.html",
        "<h3>Görev Üret</h3>",
        periods=periods,
    )

# Kriter ve dönem yönetimi akışı modüler yapı altında sürdürülür.
