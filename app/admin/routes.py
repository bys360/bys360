
"""Phase 37 modular admin/personnel route family for the shared main blueprint.

Bu modül kendi `admin_bp` blueprint'ini canlıda register etmez. Bunun yerine
`app.route_registry.main_bp` üzerine admin ve personel ekranlarını modüler
şekilde ekler.
"""
from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict

from flask import current_app, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import (
    EvaluationAssignment,
    OrganizationUnit,
    PerformanceCriteria,
    PerformanceEvaluation,
    PerformancePeriod,
    User,
)
from app.route_registry import main_bp
from app.route_support import admin_required, bool_from_form, menu_key_required, safe_render
from app.security import (
    get_default_first_login_password,
    save_profile_photo_to_user,
    validate_excel_file,
)
from app.services.account_change_guard import (
    ADMIN_CONTINUITY_MESSAGE,
    MANAGER_CHAIN_REFUSAL_MESSAGE,
    REFUSAL_MESSAGE,
    ROLE_REFUSAL_MESSAGE,
    admin_continuity_refusal,
    audit_account_change,
    audit_refusal,
    is_real_admin,
    kept_role,
    login_identity_changes,
    may_assign_role,
    may_change_account_state,
    may_change_manager_chain,
    may_change_role,
    record_account_changes,
    role_changes,
    security_flags_change,
)
from app.services.ai import (
    build_admin_user_form_ai_panel,
    build_admin_users_risk_ai_panel,
    build_personnel_density_ai_panel,
    build_personnel_list_ai_panel,
)
from app.services.auto_hierarchy_service import auto_apply_manager_chains, infer_role_from_profile
from app.services.excel_workbook_reader import ExcelWorkbookReadError, read_active_sheet_rows
from app.services.hierarchy_admin_service import ensure_unit_exists_strict, normalize_text
from app.services.performance_service import generate_assignments_for_active_period
from app.services.personnel import (
    apply_admin_user_org_hierarchy_fields,
    apply_personnel_profile_photo_action,
    assign_user_performance_category,
    build_new_personnel_user_from_payload,
    build_personnel_create_form_context,
    build_personnel_edit_form_context,
    build_personnel_excel_row_payload,
    build_personnel_list_context,
    get_personnel_category_options,
    has_explicit_personnel_excel_manager_columns,
    normalize_personnel_category_label,
    preflight_personnel_excel_headers,
    read_personnel_form_payload,
    row_has_required_personnel_excel_fields,
    update_existing_personnel_user_from_payload,
    validate_admin_manager_sicil_conflicts,
    validate_personnel_identity_uniqueness,
    validate_personnel_manager_id_conflicts,
    validate_personnel_password_change_conflicts,
    validate_required_personnel_payload,
)
from app.services.personnel.excel_import_guard import validate_personnel_import_rows_for_commit
from app.services.personnel.excel_template import (
    build_personnel_import_template_bytes,
    personnel_import_template_filename,
)
from app.services.personnel.import_manager_chain_sync import (
    sync_touched_users_manager_ids_from_sicils,
)
from app.services.personnel_sync_service import canonical_role_label, canonical_role_value
from app.services.sql_refactor_query_helpers import distinct_non_empty_values
from app.services.ui_context.risk import _event_type_label
from app.view_helpers import build_dashboard_context

logger = logging.getLogger(__name__)

ROLE_CHOICES = [
    ("admin", "Admin"),
    ("baskan", "Başkan"),
    ("baskan_yardimcisi", "Başkan Yardımcısı"),
    ("grup_baskani", "Grup Başkanı"),
    ("mali_musavir", "Mali Müşavir"),
    ("birim_sorumlusu", "Birim Sorumlusu"),
    ("koordinator", "Koordinatör"),
    ("personel", "Personel"),
]

LEGACY_SHIM = False
LEGACY_RUNTIME_STATUS = "active_modular_main_blueprint_routes"
LEGACY_ARCHIVE_MODULE = "app.legacy_routes_archive.routes_admin_personnel"
LEGACY_ROUTE_FAMILY = "admin_and_personnel"
LEGACY_NOTE = (
    "Bu modül artık shim değildir. Phase 37 ile admin ve personel route aileleri "
    "app.route_registry.main_bp üzerine modüler olarak burada tanımlanır."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
# Faz 9 notu: Excel amir kolon tespiti ve model yazim helperlari servis
# katmanina tasindi. Bu dosyada yalnizca route sozlesmesi ve Flask akis
# kontrolu kalir.

def _get_role_values():
    role_values = []
    if hasattr(User, "role"):
        role_values = distinct_non_empty_values(User.role)
    elif hasattr(User, "role_label"):
        role_values = distinct_non_empty_values(User.role_label)

    if not role_values:
        role_values = [
            "admin",
            "Grup Başkanı",
            "Başkan Yardımcısı",
            "Koordinatör",
            "Personel",
        ]
    return role_values


def _get_managers(exclude_user_id=None):
    query = User.query
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    return query.order_by(User.ad.asc(), User.soyad.asc()).all()


def _get_user_role_text(user):
    if hasattr(user, "role") and (getattr(user, "role", "") or "").strip():
        return user.role
    if hasattr(user, "role_label") and (getattr(user, "role_label", "") or "").strip():
        return user.role_label
    return ""

def _refresh_active_period_assignments(actor_user_id=None):
    active_period = (
        PerformancePeriod.query
        .filter_by(is_active=True)
        .order_by(PerformancePeriod.id.desc())
        .first()
    )
    if not active_period:
        return None
    return generate_assignments_for_active_period(period_id=active_period.id, actor_user_id=actor_user_id)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@main_bp.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    dashboard_context = build_dashboard_context(current_user)
    user_count = User.query.filter(User.role != "admin").count()
    active_user_count = User.query.filter(
        User.role != "admin",
        User.is_active.is_(True),
    ).count()
    unit_count = OrganizationUnit.query.count()
    active_period = dashboard_context.get("active_period")
    period_count = PerformancePeriod.query.count()
    criteria_count = PerformanceCriteria.query.count()
    total_assignments = EvaluationAssignment.query.count()
    pending_assignments = EvaluationAssignment.query.filter_by(status="bekliyor").count()
    partial_assignments = EvaluationAssignment.query.filter_by(status="kismen_tamamlandi").count()
    completed_assignments = EvaluationAssignment.query.filter_by(status="tamamlandi").count()
    total_evaluations = PerformanceEvaluation.query.count()
    completed_evaluations = PerformanceEvaluation.query.filter_by(status="tamamlandi").count()
    published_period_count = PerformancePeriod.query.filter_by(results_published=True).count()
    completion_rate = round((completed_assignments / total_assignments) * 100, 2) if total_assignments > 0 else 0

    page_context = {
        **dashboard_context,
        "user_count": user_count,
        "active_user_count": active_user_count,
        "unit_count": unit_count,
        "active_period": active_period,
        "period_count": period_count,
        "criteria_count": criteria_count,
        "total_assignments": total_assignments,
        "pending_assignments": pending_assignments,
        "partial_assignments": partial_assignments,
        "completed_assignments": completed_assignments,
        "total_evaluations": total_evaluations,
        "completed_evaluations": completed_evaluations,
        "published_period_count": published_period_count,
        "completion_rate": completion_rate,
        "event_type_label": _event_type_label,
    }

    return safe_render(
        "admin_dashboard.html",
        "<h3>Yönetim Dashboard</h3>",
        **page_context,
    )


@main_bp.route("/admin/users")
@login_required
@admin_required
def admin_users():
    q = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip()
    birim = (request.args.get("birim") or "").strip()
    ust_birim = (request.args.get("ust_birim") or "").strip()
    manager_sicil = (request.args.get("manager_sicil") or "").strip()
    status = (request.args.get("status") or "").strip()
    view_mode = (request.args.get("view_mode") or "list").strip()

    query = User.query.filter(User.role != "admin")

    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                User.ad.ilike(like_q),
                User.soyad.ilike(like_q),
                User.sicil_no.ilike(like_q),
                User.email.ilike(like_q),
                User.unvan.ilike(like_q),
                User.birim.ilike(like_q),
                User.ust_birim.ilike(like_q),
            )
        )

    if role:
        query = query.filter(User.role == role)
    if birim:
        query = query.filter(User.birim == birim)
    if ust_birim:
        query = query.filter(User.ust_birim == ust_birim)
    if manager_sicil:
        query = query.filter(
            or_(
                User.yonetici_sicil == manager_sicil,
                User.ikinci_yonetici_sicil == manager_sicil,
                User.ucuncu_yonetici_sicil == manager_sicil,
            )
        )
    if status == "active":
        query = query.filter(User.is_active.is_(True))
    elif status == "passive":
        query = query.filter(User.is_active.is_(False))

    users = query.order_by(
        User.ust_birim.asc(),
        User.birim.asc(),
        User.ad.asc(),
        User.soyad.asc(),
    ).all()

    role_options = distinct_non_empty_values(User.role, exclude={"admin"})
    birim_options = distinct_non_empty_values(User.birim)
    ust_birim_options = distinct_non_empty_values(User.ust_birim)

    manager_candidates = (
        User.query
        .filter(User.role != "admin", User.is_active.is_(True))
        .order_by(User.ad.asc(), User.soyad.asc())
        .all()
    )

    manager_map = {u.sicil_no: u for u in manager_candidates if u.sicil_no}

    grouped_by_unit = defaultdict(list)
    for user in users:
        unit_key = f"{user.ust_birim or '-'} / {user.birim or '-'}"
        grouped_by_unit[unit_key].append(user)

    grouped_by_manager = defaultdict(list)
    for user in users:
        if user.yonetici_sicil and user.yonetici_sicil in manager_map:
            key = f"{manager_map[user.yonetici_sicil].ad} {manager_map[user.yonetici_sicil].soyad} ({user.yonetici_sicil})"
        elif user.yonetici_sicil:
            key = f"Tanımsız Amir ({user.yonetici_sicil})"
        else:
            key = "Amir Atanmamış"
        grouped_by_manager[key].append(user)

    total_count = User.query.filter(User.role != "admin").count()
    active_count = User.query.filter(User.role != "admin", User.is_active.is_(True)).count()
    passive_count = User.query.filter(User.role != "admin", User.is_active.is_(False)).count()

    return safe_render(
        "admin_users.html",
        "<h3>Personel Yönetimi</h3>",
        users=users,
        q=q,
        selected_role=role,
        selected_birim=birim,
        selected_ust_birim=ust_birim,
        selected_manager_sicil=manager_sicil,
        selected_status=status,
        selected_view_mode=view_mode,
        role_options=role_options,
        birim_options=birim_options,
        ust_birim_options=ust_birim_options,
        manager_candidates=manager_candidates,
        grouped_by_unit=dict(grouped_by_unit),
        grouped_by_manager=dict(grouped_by_manager),
        total_count=total_count,
        active_count=active_count,
        passive_count=passive_count,
        ai_admin_users_panel=build_admin_users_risk_ai_panel(users=users, manager_candidates=manager_candidates),
    )


@main_bp.route("/admin/users/create", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_create():
    unit_name_options = distinct_non_empty_values(OrganizationUnit.name)

    parent_unit_options = distinct_non_empty_values(User.ust_birim)

    manager_candidates = (
        User.query
        .filter(User.is_active.is_(True), User.role != "admin")
        .order_by(User.ust_birim.asc(), User.birim.asc(), User.ad.asc(), User.soyad.asc())
        .all()
    )

    if request.method == "POST":
        try:
            ad = (request.form.get("ad") or "").strip()
            soyad = (request.form.get("soyad") or "").strip()
            sicil_no = (request.form.get("sicil_no") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            unvan = (request.form.get("unvan") or "").strip()
            role = (request.form.get("role") or "").strip() or "personel"
            birim = (request.form.get("birim") or "").strip()
            ust_birim = (request.form.get("ust_birim") or "").strip()
            yonetici_sicil = (request.form.get("yonetici_sicil") or "").strip() or None
            ikinci_yonetici_sicil = (request.form.get("ikinci_yonetici_sicil") or "").strip() or None
            ucuncu_yonetici_sicil = (request.form.get("ucuncu_yonetici_sicil") or "").strip() or None
            is_active = bool_from_form(request.form.get("is_active"))
            personnel_category = normalize_personnel_category_label(request.form.get("personnel_category"))  # BYS360_PHASE2_2_ADMIN_CREATE_CATEGORY_READ
            personnel_category = normalize_personnel_category_label(request.form.get("personnel_category"))

            create_form_ai_panel = build_admin_user_form_ai_panel(
                form_data=request.form.to_dict(flat=True),
                manager_candidates=manager_candidates,
                mode="create",
            )

            if not ad or not soyad or not sicil_no or not email or not unvan or not birim or not ust_birim:
                flash("Ad, soyad, sicil no, e-posta, unvan, birim ve üst birim zorunludur.", "warning")
                return safe_render(
                    "admin_user_create.html",
                    "<h3>Personel Ekle</h3>",
                    unit_name_options=unit_name_options,
                    parent_unit_options=parent_unit_options,
                    manager_candidates=manager_candidates,
                    role_choices=ROLE_CHOICES,
                    personnel_category_options=get_personnel_category_options(db.session),
                    ai_user_form_panel=create_form_ai_panel,
                )

            # R05: only a real admin creates an account with a role other than the baseline.
            if not may_assign_role(current_user, role):
                audit_refusal(None, "create_role_assign")
                flash(ROLE_REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.admin_user_create"))
            # R05: a non-admin never puts themselves in a new account's manager chain.
            if not may_change_manager_chain(current_user, None, [yonetici_sicil, ikinci_yonetici_sicil, ucuncu_yonetici_sicil]):
                audit_refusal(None, "create_manager_chain_self_assign")
                flash(MANAGER_CHAIN_REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.admin_user_create"))

            identity_conflicts = validate_personnel_identity_uniqueness(
                user_model=User,
                email=email,
                sicil_no=sicil_no,
            )
            if "sicil_no_exists" in identity_conflicts.errors:
                flash("Bu sicil numarası zaten kayıtlı.", "danger")
                return safe_render(
                    "admin_user_create.html",
                    "<h3>Personel Ekle</h3>",
                    unit_name_options=unit_name_options,
                    parent_unit_options=parent_unit_options,
                    manager_candidates=manager_candidates,
                    role_choices=ROLE_CHOICES,
                    personnel_category_options=get_personnel_category_options(db.session),
                    ai_user_form_panel=create_form_ai_panel,
                )
            if "email_exists" in identity_conflicts.errors:
                flash("Bu e-posta adresi zaten kayıtlı.", "danger")
                return safe_render(
                    "admin_user_create.html",
                    "<h3>Personel Ekle</h3>",
                    unit_name_options=unit_name_options,
                    parent_unit_options=parent_unit_options,
                    manager_candidates=manager_candidates,
                    role_choices=ROLE_CHOICES,
                    personnel_category_options=get_personnel_category_options(db.session),
                    ai_user_form_panel=create_form_ai_panel,
                )

            manager_validation = validate_admin_manager_sicil_conflicts(
                self_sicil_no=sicil_no,
                manager_sicils=[yonetici_sicil, ikinci_yonetici_sicil, ucuncu_yonetici_sicil],
            )
            if "self_manager_not_allowed" in manager_validation.errors:
                flash("Personel kendisini amir olarak seçemez.", "warning")
                return safe_render(
                    "admin_user_create.html",
                    "<h3>Personel Ekle</h3>",
                    unit_name_options=unit_name_options,
                    parent_unit_options=parent_unit_options,
                    manager_candidates=manager_candidates,
                    role_choices=ROLE_CHOICES,
                    personnel_category_options=get_personnel_category_options(db.session),
                    ai_user_form_panel=create_form_ai_panel,
                )
            if "duplicate_manager_not_allowed" in manager_validation.errors:
                flash("Aynı kişi birden fazla amir seviyesinde seçilemez.", "warning")
                return safe_render(
                    "admin_user_create.html",
                    "<h3>Personel Ekle</h3>",
                    unit_name_options=unit_name_options,
                    parent_unit_options=parent_unit_options,
                    manager_candidates=manager_candidates,
                    role_choices=ROLE_CHOICES,
                    personnel_category_options=get_personnel_category_options(db.session),
                    ai_user_form_panel=create_form_ai_panel,
                )

            initial_password = get_default_first_login_password()

            user = User(
                ad=ad,
                soyad=soyad,
                sicil_no=sicil_no,
                email=email,
                unvan=unvan,
                role=role,
                is_active=is_active,
            )
            assign_user_performance_category(user, personnel_category, db_session=db.session)  # BYS360_PHASE2_ADMIN_CREATE_CATEGORY_BINDING
            apply_admin_user_org_hierarchy_fields(
                user=user,
                birim=birim,
                ust_birim=ust_birim,
                role=role,
                yonetici_sicil=yonetici_sicil,
                ikinci_yonetici_sicil=ikinci_yonetici_sicil,
                ucuncu_yonetici_sicil=ucuncu_yonetici_sicil,
                ensure_unit_exists=ensure_unit_exists_strict,
            )
            user.set_password(initial_password)

            if hasattr(user, "must_change_password"):
                user.must_change_password = True
            if hasattr(user, "must_set_security_question"):
                user.must_set_security_question = True
            if hasattr(user, "is_first_login"):
                user.is_first_login = True
            if hasattr(user, "failed_login_attempts"):
                user.failed_login_attempts = 0
            if hasattr(user, "captcha_required"):
                user.captcha_required = False
            assign_user_performance_category(user, personnel_category, db_session=db.session)  # BYS360_PHASE2_2_ADMIN_CREATE_CATEGORY_BINDING

            db.session.add(user)
            db.session.flush()
            audit_account_change("account.create", user, new={"role": user.role, "is_active": bool(user.is_active)})

            photo = request.files.get("profile_photo")
            apply_personnel_profile_photo_action(
                user,
                photo_file=photo,
                app_root_path=current_app.root_path,
                logger=current_app.logger,
                save_photo_func=save_profile_photo_to_user,
            )

            db.session.commit()

            assignment_result = _refresh_active_period_assignments(actor_user_id=current_user.id)
            flash(f"Personel kaydı oluşturuldu. Başlangıç şifresi: {initial_password}", "success")
            if assignment_result and assignment_result.get("ok"):
                flash("Aktif dönem görevleri personel kaydı sonrası yeniden senkronlandı.", "success")
            elif assignment_result and not assignment_result.get("ok"):
                flash(assignment_result.get("message", "Aktif dönem görevleri yeniden senkronlanamadı."), "warning")
            return redirect(url_for("main.admin_users"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Personel oluşturulurken hata oluştu.", "danger")
            return safe_render(
                "admin_user_create.html",
                "<h3>Personel Ekle</h3>",
                unit_name_options=unit_name_options,
                parent_unit_options=parent_unit_options,
                manager_candidates=manager_candidates,
                role_choices=ROLE_CHOICES,
                personnel_category_options=get_personnel_category_options(db.session),
                ai_user_form_panel=build_admin_user_form_ai_panel(
                    form_data=request.form.to_dict(flat=True),
                    manager_candidates=manager_candidates,
                    mode="create",
                ),
            )

    return safe_render(
        "admin_user_create.html",
        "<h3>Personel Ekle</h3>",
        unit_name_options=unit_name_options,
        parent_unit_options=parent_unit_options,
        manager_candidates=manager_candidates,
        role_choices=ROLE_CHOICES,
        personnel_category_options=get_personnel_category_options(db.session),
        ai_user_form_panel=build_admin_user_form_ai_panel(manager_candidates=manager_candidates, mode="create"),
    )


@main_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_edit(user_id):
    user = User.query.get_or_404(user_id)

    unit_name_options = distinct_non_empty_values(OrganizationUnit.name)

    parent_unit_options = distinct_non_empty_values(User.ust_birim)

    manager_candidates = (
        User.query
        .filter(User.is_active.is_(True), User.role != "admin", User.id != user.id)
        .order_by(User.ust_birim.asc(), User.birim.asc(), User.ad.asc(), User.soyad.asc())
        .all()
    )

    if request.method == "POST":
        try:
            ad = (request.form.get("ad") or "").strip()
            soyad = (request.form.get("soyad") or "").strip()
            sicil_no = (request.form.get("sicil_no") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            unvan = (request.form.get("unvan") or "").strip()
            role = (request.form.get("role") or "").strip() or "personel"
            birim = (request.form.get("birim") or "").strip()
            ust_birim = (request.form.get("ust_birim") or "").strip()
            yonetici_sicil = (request.form.get("yonetici_sicil") or "").strip() or None
            ikinci_yonetici_sicil = (request.form.get("ikinci_yonetici_sicil") or "").strip() or None
            ucuncu_yonetici_sicil = (request.form.get("ucuncu_yonetici_sicil") or "").strip() or None
            is_active = bool_from_form(request.form.get("is_active"))
            edit_personnel_category = normalize_personnel_category_label(request.form.get("personnel_category", getattr(user, "personnel_category", "Diğer")))  # BYS360_PHASE2_2_ADMIN_EDIT_CATEGORY_READ
            edit_personnel_category = normalize_personnel_category_label(request.form.get("personnel_category", getattr(user, "personnel_category", "Diğer")))

            if not ad or not soyad or not sicil_no or not email or not unvan or not birim or not ust_birim:
                flash("Ad, soyad, sicil no, e-posta, unvan, birim ve üst birim zorunludur.", "warning")
                return redirect(url_for("main.admin_user_edit", user_id=user.id))

            identity_conflicts = validate_personnel_identity_uniqueness(
                user_model=User,
                email=email,
                sicil_no=sicil_no,
                exclude_user_id=user.id,
            )
            if "sicil_no_exists" in identity_conflicts.errors:
                flash("Bu sicil numarası başka bir kullanıcıda kayıtlı.", "danger")
                return redirect(url_for("main.admin_user_edit", user_id=user.id))
            if "email_exists" in identity_conflicts.errors:
                flash("Bu e-posta adresi başka bir kullanıcıda kayıtlı.", "danger")
                return redirect(url_for("main.admin_user_edit", user_id=user.id))

            manager_validation = validate_admin_manager_sicil_conflicts(
                self_sicil_no=sicil_no,
                manager_sicils=[yonetici_sicil, ikinci_yonetici_sicil, ucuncu_yonetici_sicil],
            )
            if "self_manager_not_allowed" in manager_validation.errors:
                flash("Personel kendisini amir olarak seçemez.", "warning")
                return redirect(url_for("main.admin_user_edit", user_id=user.id))
            if "duplicate_manager_not_allowed" in manager_validation.errors:
                flash("Aynı kişi birden fazla amir seviyesinde seçilemez.", "warning")
                return redirect(url_for("main.admin_user_edit", user_id=user.id))

            # R05: role and activation changes follow the account change rules.
            old_role, old_active = user.role, bool(user.is_active)
            if not may_change_role(current_user, user, role):
                audit_refusal(user, "role_change")
                flash(ROLE_REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.admin_user_edit", user_id=user_id))
            if bool(is_active) != old_active and not may_change_account_state(current_user, user):
                audit_refusal(user, "activation_change")
                flash(REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.admin_user_edit", user_id=user_id))
            if login_identity_changes(user, sicil_no=sicil_no, email=email) and not may_change_account_state(current_user, user):
                audit_refusal(user, "identity_change")
                flash(REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.admin_user_edit", user_id=user_id))
            if not may_change_manager_chain(current_user, user, [yonetici_sicil, ikinci_yonetici_sicil, ucuncu_yonetici_sicil]):
                audit_refusal(user, "manager_chain_change")
                flash(MANAGER_CHAIN_REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.admin_user_edit", user_id=user_id))
            role = kept_role(old_role, role)
            # R05-5 / K4 / C: no self-demotion or self-deactivation, never the last active admin.
            continuity_refusal = admin_continuity_refusal(current_user, user, new_role=role, new_active=is_active)
            if continuity_refusal:
                audit_refusal(user, continuity_refusal)
                flash(ADMIN_CONTINUITY_MESSAGE, "danger")
                return redirect(url_for("main.admin_user_edit", user_id=user_id))

            user.ad = ad
            user.soyad = soyad
            user.sicil_no = sicil_no
            user.email = email
            user.unvan = unvan
            user.role = role
            apply_admin_user_org_hierarchy_fields(
                user=user,
                birim=birim,
                ust_birim=ust_birim,
                role=role,
                yonetici_sicil=yonetici_sicil,
                ikinci_yonetici_sicil=ikinci_yonetici_sicil,
                ucuncu_yonetici_sicil=ucuncu_yonetici_sicil,
                ensure_unit_exists=ensure_unit_exists_strict,
            )
            assign_user_performance_category(user, edit_personnel_category, db_session=db.session)  # BYS360_PHASE2_ADMIN_EDIT_CATEGORY_BINDING
            assign_user_performance_category(user, edit_personnel_category, db_session=db.session)  # BYS360_PHASE2_2_ADMIN_EDIT_CATEGORY_BINDING
            user.is_active = is_active

            remove_photo = bool_from_form(request.form.get("remove_profile_photo"))
            photo = request.files.get("profile_photo")
            apply_personnel_profile_photo_action(
                user,
                photo_file=photo,
                remove_photo=remove_photo,
                app_root_path=current_app.root_path,
                logger=current_app.logger,
                save_photo_func=save_profile_photo_to_user,
            )

            record_account_changes(user, old_role=old_role, old_active=old_active)
            db.session.add(user)
            db.session.commit()

            assignment_result = _refresh_active_period_assignments(actor_user_id=current_user.id)
            flash("Personel bilgileri güncellendi.", "success")
            if assignment_result and assignment_result.get("ok"):
                flash("Aktif dönem görevleri personel güncellemesi sonrası yeniden senkronlandı.", "success")
            elif assignment_result and not assignment_result.get("ok"):
                flash(assignment_result.get("message", "Aktif dönem görevleri yeniden senkronlanamadı."), "warning")
            return redirect(url_for("main.admin_users"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Personel güncellenirken hata oluştu.", "danger")
            return redirect(url_for("main.admin_user_edit", user_id=user.id))

    return safe_render(
        "admin_user_edit.html",
        "<h3>Personel Düzenle</h3>",
        user_obj=user,
        unit_name_options=unit_name_options,
        parent_unit_options=parent_unit_options,
        manager_candidates=manager_candidates,
        role_choices=ROLE_CHOICES,
        personnel_category_options=get_personnel_category_options(db.session),
        current_personnel_category=getattr(user, "personnel_category", "Diğer") or "Diğer",
        ai_user_form_panel=build_admin_user_form_ai_panel(manager_candidates=manager_candidates, mode="edit", user_obj=user),
    )


# ---------------------------------------------------------------------------
# Personnel routes
# ---------------------------------------------------------------------------

@main_bp.route("/personnel")
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_list():
    list_context = build_personnel_list_context(
        request_args=request.args,
        user_model=User,
        db_session=db.session,
    )
    stats = list_context["stats"]
    user_rows = list_context["user_rows"]

    return safe_render(
        "personnel_list.html",
        "<h3>Personel Yönetimi</h3>",
        **list_context,
        ai_personnel_list_panel=build_personnel_list_ai_panel(stats=stats, user_rows=user_rows),
        ai_personnel_density_panel=build_personnel_density_ai_panel(stats=stats, user_rows=user_rows),
    )


@main_bp.route("/personnel/add", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_add():
    role_values = _get_role_values()
    managers = _get_managers()
    form_context = build_personnel_create_form_context(role_values=role_values, managers=managers)

    if request.method == "POST":
        try:
            payload = read_personnel_form_payload(request.form)
            form_context = build_personnel_create_form_context(role_values=role_values, managers=managers, payload=payload)
            required_validation = validate_required_personnel_payload(payload)
            sicil_no = payload.sicil_no
            email = payload.email

            if not required_validation.ok:
                flash("Zorunlu alanları eksiksiz doldurunuz.", "warning")
                return safe_render(
                    "personnel_add.html",
                    "<h3>Yeni Personel Ekle</h3>",
                    **form_context,
                )

            # R05: only a real admin creates an account with a role other than the baseline.
            if not may_assign_role(current_user, payload.role_value):
                audit_refusal(None, "create_role_assign")
                flash(ROLE_REFUSAL_MESSAGE, "danger")
                return safe_render(
                    "personnel_add.html",
                    "<h3>Yeni Personel Ekle</h3>",
                    **form_context,
                )
            # R05: a non-admin never puts themselves in a new account's manager chain.
            new_manager_sicils = [
                getattr(db.session.get(User, manager_id), "sicil_no", None) if manager_id else None
                for manager_id in (payload.manager_1_id, payload.manager_2_id, payload.manager_3_id)
            ]
            if not may_change_manager_chain(current_user, None, new_manager_sicils):
                audit_refusal(None, "create_manager_chain_self_assign")
                flash(MANAGER_CHAIN_REFUSAL_MESSAGE, "danger")
                return safe_render(
                    "personnel_add.html",
                    "<h3>Yeni Personel Ekle</h3>",
                    **form_context,
                )

            identity_conflicts = validate_personnel_identity_uniqueness(
                user_model=User,
                email=email,
                sicil_no=sicil_no,
            )
            if "email_exists" in identity_conflicts.errors:
                flash("Bu e-posta adresi ile kayıtlı bir kullanıcı zaten var.", "danger")
                return safe_render(
                    "personnel_add.html",
                    "<h3>Yeni Personel Ekle</h3>",
                    **form_context,
                )

            if "sicil_no_exists" in identity_conflicts.errors:
                flash("Bu sicil numarası ile kayıtlı bir kullanıcı zaten var.", "danger")
                return safe_render(
                    "personnel_add.html",
                    "<h3>Yeni Personel Ekle</h3>",
                    **form_context,
                )

            user = build_new_personnel_user_from_payload(
                payload=payload,
                user_model=User,
                db_session=db.session,
                ensure_unit_exists=ensure_unit_exists_strict,
                password_hasher=generate_password_hash,
                initial_password=get_default_first_login_password(),
            )

            db.session.add(user)
            db.session.flush()
            audit_account_change("account.create", user, new={"role": user.role, "is_active": bool(user.is_active)})

            photo = request.files.get("profile_photo")
            apply_personnel_profile_photo_action(
                user,
                photo_file=photo,
                app_root_path=current_app.root_path,
                logger=current_app.logger,
                save_photo_func=save_profile_photo_to_user,
            )

            db.session.commit()
            flash("Personel kaydı başarıyla oluşturuldu.", "success")
            return redirect(url_for("main.personnel_list"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Personel ekleme sırasında hata oluştu.", "danger")

    return safe_render(
        "personnel_add.html",
        "<h3>Yeni Personel Ekle</h3>",
        **form_context,
    )


@main_bp.route("/personnel/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Personel kaydı bulunamadı.", "danger")
        return redirect(url_for("main.personnel_list"))

    role_values = _get_role_values()
    managers = _get_managers(exclude_user_id=user.id)
    avatar_url = getattr(user, "profile_photo_url", None) or url_for("static", filename="img/default-avatar.svg")
    current_role = _get_user_role_text(user)
    form_context = build_personnel_edit_form_context(
        user,
        role_values=role_values,
        managers=managers,
        avatar_url=avatar_url,
        current_role=current_role,
        user_model=User,
    )

    if request.method == "POST":
        try:
            payload = read_personnel_form_payload(request.form, include_password_fields=True)
            required_validation = validate_required_personnel_payload(payload)
            sicil_no = payload.sicil_no
            email = payload.email
            new_password = payload.new_password
            new_password_repeat = payload.new_password_repeat
            new_manager_1_id = payload.manager_1_id
            new_manager_2_id = payload.manager_2_id
            new_manager_3_id = payload.manager_3_id

            if not required_validation.ok:
                flash("Ad, Soyad, Sicil No, E-Posta, Unvan, Birim ve Üst Birim alanları zorunludur.", "warning")
                return redirect(url_for("main.personnel_edit", user_id=user.id))

            identity_conflicts = validate_personnel_identity_uniqueness(
                user_model=User,
                email=email,
                sicil_no=sicil_no,
                exclude_user_id=user.id,
            )
            if "email_exists" in identity_conflicts.errors:
                flash("Bu e-posta başka bir kullanıcı tarafından kullanılıyor.", "danger")
                return redirect(url_for("main.personnel_edit", user_id=user.id))
            if "sicil_no_exists" in identity_conflicts.errors:
                flash("Bu sicil numarası başka bir kullanıcı tarafından kullanılıyor.", "danger")
                return redirect(url_for("main.personnel_edit", user_id=user.id))

            manager_validation = validate_personnel_manager_id_conflicts(
                current_user_id=user.id,
                manager_ids=[new_manager_1_id, new_manager_2_id, new_manager_3_id],
            )
            if "self_manager_not_allowed" in manager_validation.errors:
                flash("Personel kendisini amir olarak seçemez.", "danger")
                return redirect(url_for("main.personnel_edit", user_id=user.id))
            if "duplicate_manager_not_allowed" in manager_validation.errors:
                flash("Aynı kişi birden fazla amir seviyesinde seçilemez.", "danger")
                return redirect(url_for("main.personnel_edit", user_id=user.id))

            password_validation = validate_personnel_password_change_conflicts(
                new_password=new_password,
                new_password_repeat=new_password_repeat,
            )
            if "password_min_length" in password_validation.errors:
                flash("Yeni şifre en az 8 karakter olmalıdır.", "warning")
                return redirect(url_for("main.personnel_edit", user_id=user.id))
            if "password_repeat_mismatch" in password_validation.errors:
                flash("Yeni şifre alanları eşleşmiyor.", "warning")
                return redirect(url_for("main.personnel_edit", user_id=user.id))

            # R05: role, password and activation changes follow the account change rules.
            new_is_active = bool_from_form(request.form.get("is_active"))
            old_role, old_active = user.role, bool(user.is_active)
            if not may_change_role(current_user, user, payload.role_value or current_role or "Personel"):
                audit_refusal(user, "role_change")
                flash(ROLE_REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.personnel_edit", user_id=user_id))
            new_must_change_password = bool_from_form(request.form.get("must_change_password"))
            new_must_set_security_question = bool_from_form(request.form.get("must_set_security_question"))
            sensitive_change = (
                ("password_set" if new_password else "")
                or ("activation_change" if new_is_active != old_active else "")
                or ("identity_change" if login_identity_changes(user, sicil_no=sicil_no, email=email) else "")
                or (
                    "security_flags_change"
                    if security_flags_change(
                        user,
                        must_change_password=new_must_change_password,
                        must_set_security_question=new_must_set_security_question,
                    )
                    else ""
                )
            )
            if sensitive_change and not may_change_account_state(current_user, user):
                audit_refusal(user, sensitive_change)
                flash(REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.personnel_edit", user_id=user_id))
            new_manager_sicils = [
                getattr(db.session.get(User, manager_id), "sicil_no", None) if manager_id else None
                for manager_id in (new_manager_1_id, new_manager_2_id, new_manager_3_id)
            ]
            if not may_change_manager_chain(current_user, user, new_manager_sicils):
                audit_refusal(user, "manager_chain_change")
                flash(MANAGER_CHAIN_REFUSAL_MESSAGE, "danger")
                return redirect(url_for("main.personnel_edit", user_id=user_id))
            payload = dataclasses.replace(payload, role_value=kept_role(user.role, payload.role_value or current_role or "Personel"))
            # R05-5 / K4 / C: no self-demotion or self-deactivation, never the last active admin.
            continuity_refusal = admin_continuity_refusal(current_user, user, new_role=payload.role_value, new_active=new_is_active)
            if continuity_refusal:
                audit_refusal(user, continuity_refusal)
                flash(ADMIN_CONTINUITY_MESSAGE, "danger")
                return redirect(url_for("main.personnel_edit", user_id=user_id))

            password_reset_applied = update_existing_personnel_user_from_payload(
                user=user,
                payload=payload,
                current_role=current_role,
                user_model=User,
                db_session=db.session,
                ensure_unit_exists=ensure_unit_exists_strict,
                password_hasher=generate_password_hash,
                is_active=new_is_active,
                must_change_password=new_must_change_password,
                must_set_security_question=new_must_set_security_question,
            )

            remove_photo = bool_from_form(request.form.get("remove_profile_photo"))
            photo = request.files.get("profile_photo")
            apply_personnel_profile_photo_action(
                user,
                photo_file=photo,
                remove_photo=remove_photo,
                app_root_path=current_app.root_path,
                logger=current_app.logger,
                save_photo_func=save_profile_photo_to_user,
            )

            record_account_changes(user, old_role=old_role, old_active=old_active, password_set=password_reset_applied)
            db.session.commit()
            if password_reset_applied:
                flash("Personel kaydı güncellendi. Yönetici tarafından yeni geçici şifre tanımlandı; kullanıcı ilk girişte şifre değiştirip gizli sorusunu yeniden tanımlayacak.", "success")
            else:
                flash("Personel kaydı güncellendi.", "success")
            return redirect(url_for("main.personnel_list"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Personel güncelleme sırasında hata oluştu.", "danger")

    return safe_render(
        "personnel_edit.html",
        "<h3>Personel Düzenle</h3>",
        **form_context,
    )


@main_bp.route("/personnel/excel-template", methods=["GET"])
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_excel_template_download():
    """BYS360_PHASE2_3_PERSONNEL_EXCEL_TEMPLATE_DOWNLOAD"""
    stream = build_personnel_import_template_bytes()
    return send_file(
        stream,
        as_attachment=True,
        download_name=personnel_import_template_filename(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main_bp.route("/personnel/excel-upload", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_excel_upload():
    if request.method == "POST":
        try:
            file = request.files.get("excel_file")
            if not file or not file.filename:
                flash("Lütfen bir Excel dosyası seçiniz.", "warning")
                return redirect(url_for("main.personnel_excel_upload"))

            ok, validation_message = validate_excel_file(file)
            if not ok:
                flash(validation_message, "danger")
                return redirect(url_for("main.personnel_excel_upload"))

            update_existing = bool_from_form(request.form.get("update_existing"))
            activate_new_users = bool_from_form(request.form.get("activate_new_users"))

            try:
                rows_for_preflight = read_active_sheet_rows(file)
            except ExcelWorkbookReadError as exc:
                flash(exc.user_message, "danger")
                return redirect(url_for("main.personnel_excel_upload"))
            import_preflight = validate_personnel_import_rows_for_commit(rows_for_preflight)
            if not import_preflight.get("ok"):
                for error in list(import_preflight.get("errors") or [])[:12]:
                    flash(error, "danger")
                extra_count = max(len(list(import_preflight.get("errors") or [])) - 12, 0)
                if extra_count:
                    flash(f"Excel ön kontrolünde {extra_count} ek hata daha var. Dosya düzeltilmeden kayıt yapılmadı.", "danger")
                return redirect(url_for("main.personnel_excel_upload"))

            headers = list(rows_for_preflight[0] or [])
            preflight = preflight_personnel_excel_headers(headers, normalize_func=normalize_text)
            if not preflight.ok:
                for missing_header in preflight.missing_headers:
                    flash(f"Excel şablonunda zorunlu sütun eksik: {missing_header}", "danger")
                return redirect(url_for("main.personnel_excel_upload"))

            normalized_headers = list(preflight.normalized_headers)
            header_idx = preflight.required_header_indexes
            idx = preflight.column_index

            created_count = 0
            updated_count = 0
            skipped_count = 0
            initial_password = get_default_first_login_password()
            touched_users = []
            created_users = []

            for row_number, row in enumerate(rows_for_preflight[1:], start=2):
                row_payload = build_personnel_excel_row_payload(
                    row,
                    header_idx=header_idx,
                    column_index=idx,
                )
                sicil_no = row_payload.sicil_no
                ad = row_payload.ad
                soyad = row_payload.soyad
                email = row_payload.email
                unvan = row_payload.unvan
                birim = row_payload.birim
                ust_birim = row_payload.ust_birim
                yonetici_sicil = row_payload.yonetici_sicil
                ikinci_yonetici_sicil = row_payload.ikinci_yonetici_sicil
                ucuncu_yonetici_sicil = row_payload.ucuncu_yonetici_sicil
                raw_role = row_payload.raw_role
                personnel_category = normalize_personnel_category_label(row_payload.personnel_category)
                role_value = "personel"
                role_label_value = "Personel"

                inferred_role, inferred_role_label = infer_role_from_profile(
                    raw_role=raw_role,
                    unvan=unvan,
                    birim=birim,
                    ust_birim=ust_birim,
                )
                if raw_role:
                    role_value = canonical_role_value(raw_role)
                    role_label_value = canonical_role_label(raw_role)
                else:
                    role_value = inferred_role or "personel"
                    role_label_value = inferred_role_label or "Personel"

                if not row_has_required_personnel_excel_fields(row_payload):
                    skipped_count += 1
                    continue

                full_name_text = f"{ad} {soyad}".strip()
                org_unit = ensure_unit_exists_strict(
                    birim_name=birim,
                    ust_birim_name=ust_birim,
                    role=role_value,
                )

                user = None
                if hasattr(User, "sicil_no"):
                    user = User.query.filter_by(sicil_no=sicil_no).first()
                if not user and hasattr(User, "email"):
                    user = User.query.filter_by(email=email).first()

                # R05: a non-admin import never creates a non-baseline role or changes a stored
                # role (also one inferred from the title or unit); one such row refuses the file.
                if (user and update_existing and not may_change_role(current_user, user, role_value)) or (
                    not user and not may_assign_role(current_user, role_value)
                ):
                    audit_refusal(user, "excel_role_change" if user else "excel_role_assign")
                    flash(f"Satır {row_number}: {ROLE_REFUSAL_MESSAGE} Dosyadaki hiçbir kayıt yazılmadı.", "danger")
                    return redirect(url_for("main.personnel_excel_upload"))
                # R05: a non-admin import never adds the importer to a manager chain nor changes the
                # chain of a protected account; one such row refuses the file.
                if (not user or update_existing) and not may_change_manager_chain(
                    current_user, user, [yonetici_sicil, ikinci_yonetici_sicil, ucuncu_yonetici_sicil]
                ):
                    audit_refusal(user, "excel_manager_chain_change")
                    flash(f"Satır {row_number}: {MANAGER_CHAIN_REFUSAL_MESSAGE} Dosyadaki hiçbir kayıt yazılmadı.", "danger")
                    return redirect(url_for("main.personnel_excel_upload"))
                # R05: a non-admin import never rewrites a protected account matched by another sicil or
                # changes its e-mail (login identifiers).
                if (
                    user
                    and update_existing
                    and login_identity_changes(user, sicil_no=sicil_no, email=email)
                    and not may_change_account_state(current_user, user)
                ):
                    audit_refusal(user, "excel_identity_change")
                    flash(f"Satır {row_number}: {REFUSAL_MESSAGE} Dosyadaki hiçbir kayıt yazılmadı.", "danger")
                    return redirect(url_for("main.personnel_excel_upload"))
                # R05-5 / K4: an Excel file never changes an admin account's role (one such row
                # refuses the file); admin role changes go through the single-account edit.
                if user and update_existing and is_real_admin(user) and role_changes(user.role, role_value or "personel"):
                    audit_refusal(user, "excel_admin_role_change")
                    flash(f"Satır {row_number}: {ADMIN_CONTINUITY_MESSAGE} Admin hesaplarının rolü Excel ile değiştirilemez. Dosyadaki hiçbir kayıt yazılmadı.", "danger")
                    return redirect(url_for("main.personnel_excel_upload"))

                if user:
                    if not update_existing:
                        skipped_count += 1
                        continue

                    old_role = user.role
                    user.ad = ad
                    user.soyad = soyad
                    if hasattr(user, "email"):
                        user.email = email
                    if hasattr(user, "unvan"):
                        user.unvan = unvan
                    if hasattr(user, "birim"):
                        user.birim = birim
                    if hasattr(user, "ust_birim"):
                        user.ust_birim = ust_birim
                    if hasattr(user, "role"):
                        user.role = role_value or "personel"
                    if hasattr(user, "role_label"):
                        user.role_label = role_label_value or "Personel"
                    if hasattr(user, "yonetici_sicil"):
                        user.yonetici_sicil = yonetici_sicil or None
                    if hasattr(user, "ikinci_yonetici_sicil"):
                        user.ikinci_yonetici_sicil = ikinci_yonetici_sicil or None
                    if hasattr(user, "ucuncu_yonetici_sicil"):
                        user.ucuncu_yonetici_sicil = ucuncu_yonetici_sicil or None
                    if hasattr(user, "full_name_cache"):
                        user.full_name_cache = full_name_text
                    if hasattr(user, "organization_unit_id"):
                        user.organization_unit_id = org_unit.id if org_unit else None
                    assign_user_performance_category(user, personnel_category, db_session=db.session)  # BYS360_PHASE2_EXCEL_CATEGORY_EXISTING_BINDING
                    if role_changes(old_role, user.role):
                        audit_account_change("account.role_change", user, old={"role": old_role}, new={"role": user.role})
                    updated_count += 1
                    touched_users.append(user)
                else:
                    user = User()
                    user.ad = ad
                    user.soyad = soyad
                    if hasattr(user, "sicil_no"):
                        user.sicil_no = sicil_no
                    if hasattr(user, "email"):
                        user.email = email
                    if hasattr(user, "unvan"):
                        user.unvan = unvan
                    if hasattr(user, "birim"):
                        user.birim = birim
                    if hasattr(user, "ust_birim"):
                        user.ust_birim = ust_birim
                    if hasattr(user, "role"):
                        user.role = role_value or "personel"
                    if hasattr(user, "role_label"):
                        user.role_label = role_label_value or "Personel"
                    if hasattr(user, "yonetici_sicil"):
                        user.yonetici_sicil = yonetici_sicil or None
                    if hasattr(user, "ikinci_yonetici_sicil"):
                        user.ikinci_yonetici_sicil = ikinci_yonetici_sicil or None
                    if hasattr(user, "ucuncu_yonetici_sicil"):
                        user.ucuncu_yonetici_sicil = ucuncu_yonetici_sicil or None
                    if hasattr(user, "is_active"):
                        user.is_active = activate_new_users
                    if hasattr(user, "full_name_cache"):
                        user.full_name_cache = full_name_text
                    if hasattr(user, "organization_unit_id"):
                        user.organization_unit_id = org_unit.id if org_unit else None
                    assign_user_performance_category(user, personnel_category, db_session=db.session)  # BYS360_PHASE2_EXCEL_CATEGORY_NEW_BINDING

                    if hasattr(user, "set_password") and callable(user.set_password):
                        user.set_password(initial_password)
                    elif hasattr(user, "password_hash"):
                        user.password_hash = generate_password_hash(initial_password)

                    if hasattr(user, "must_change_password"):
                        user.must_change_password = True
                    if hasattr(user, "must_set_security_question"):
                        user.must_set_security_question = True
                    if hasattr(user, "is_first_login"):
                        user.is_first_login = True
                    if hasattr(user, "failed_login_attempts"):
                        user.failed_login_attempts = 0
                    if hasattr(user, "captcha_required"):
                        user.captcha_required = False

                    db.session.add(user)
                    created_count += 1
                    touched_users.append(user)
                    created_users.append(user)

            db.session.flush()
            for created_user in created_users:
                audit_account_change(
                    "account.create",
                    created_user,
                    new={"role": created_user.role, "is_active": bool(created_user.is_active)},
                )
            has_explicit_manager_columns = has_explicit_personnel_excel_manager_columns(normalized_headers)
            if has_explicit_manager_columns:
                # BYS360_IMPORT_EXPLICIT_MANAGER_CHAIN_PRESERVE_V1
                # Excel'de 1./2./3. amir sicili verilmişse bu kaynak veri ezilmez.
                # Sadece varsa manager_*_id alanları sicile göre senkronlanır ki düzenleme
                # ekranlarında amir dropdownları seçili gelsin.
                manager_sync_summary = sync_touched_users_manager_ids_from_sicils(
                    touched_users,
                    user_model=User,
                )
                auto_summary = {
                    "updated_count": 0,
                    "skipped_count": len(touched_users),
                    "warnings": manager_sync_summary.get("warnings", []),
                }
            else:
                auto_summary = auto_apply_manager_chains(
                    touched_users,
                    fill_only_missing=True,
                    commit=False,
                    preserve_explicit_chain=True,  # BYS360_EXPLICIT_MANAGER_CHAIN_V2
                    persist_inferred_roles=is_real_admin(current_user),  # R05
                )
                manager_sync_summary = sync_touched_users_manager_ids_from_sicils(
                    touched_users,
                    user_model=User,
                )
            db.session.commit()

            assignment_result = _refresh_active_period_assignments(actor_user_id=current_user.id)

            flash(
                f"Excel işlemi tamamlandı. Yeni: {created_count}, Güncellenen: {updated_count}, Atlanan: {skipped_count}, Otomatik yeniden kurulan zincir: {auto_summary.get('updated_count', 0)}",
                "success",
            )
            if has_explicit_manager_columns:
                flash('Excel içindeki yönetici sicil ve ikinci yönetici sicil alanları kaynak veri olarak korundu; amir seçili görünümü bu sicillere göre senkronlandı.', 'info')
            if auto_summary.get("warnings"):
                current_app.logger.warning(
                    "Amir zinciri senkron uyarıları gizlendi: %s",
                    " | ".join(auto_summary["warnings"][:10]),
                )
                flash(
                    f"Amir zinciri denetiminde {len(auto_summary.get('warnings', []))} kayıt için teknik not üretildi; ham liste kullanıcı ekranında gösterilmedi.",
                    "info",
                )
            if assignment_result and assignment_result.get("ok"):
                flash(
                    f"Aktif dönem için görevler otomatik yenilendi. Oluşturulan: {assignment_result.get('created', 0)}, atlanan/muaf kalan: {assignment_result.get('skipped', 0)}.",
                    "success",
                )
                assignment_result.get("info_notes", []) or []
                blocking_warnings = assignment_result.get("warnings", []) or []
                # Bilgi notlari teknik/kurala bagli istisnalardir; kullaniciya ham metin olarak gosterilmez.
                # Gerekirse coverage log kayitlarindan veya yonetici ekranlarindan incelenebilir.
                if blocking_warnings:
                    flash("Görev üretimi uyarıları: " + " | ".join(blocking_warnings[:4]), "warning")
            return redirect(url_for("main.personnel_list"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Excel yükleme sırasında hata oluştu.", "danger")

    return safe_render(
        "personnel_excel_upload.html",
        "<h3>Excel ile Personel Yükleme</h3>",
        sample_file_url=url_for("main.personnel_excel_template_download"),
    )


__all__ = [
    "LEGACY_SHIM",
    "LEGACY_RUNTIME_STATUS",
    "LEGACY_ARCHIVE_MODULE",
    "LEGACY_ROUTE_FAMILY",
    "LEGACY_NOTE",
    "admin_dashboard",
    "admin_users",
    "admin_user_create",
    "admin_user_edit",
    "personnel_list",
    "personnel_add",
    "personnel_edit",
    "personnel_excel_upload",
    "personnel_excel_template_download",
]

# BYS360_PERFORMANCE_COMPLETION_PHASE2_ADMIN_PERSONNEL_CATEGORY_MARKER
# Personel ekleme/düzenleme ekranlarında personel_category alanı kurumsal veri olarak tutulur.
try:
    from app.services.performance.phase2_category_center import (
        DEFAULT_CATEGORY_LABELS as PHASE2_DEFAULT_CATEGORY_LABELS,
    )
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/admin/routes.py:1152")
    PHASE2_DEFAULT_CATEGORY_LABELS = ("Güvenlik", "Temizlik", "İdari Personel", "Teknik Personel", "Deneme Süreli Personel", "Diğer")

