
"""Phase 47 organizasyon birimi route ailesi.

Personel – , mesai dışı saat:28.
Birim/pozisyon ekranlari bir suredir cekirdek routes dosyasinda kalmisti.
Aslinda en cok beni bunaltan bloklardan biriydi; hem admin hem kurumsal modul
hissi veriyor. Buraya alinca ana omurga daha net gorunmeye basladi.
"""
from __future__ import annotations

import logging

from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import OrganizationUnit, User
from app.route_registry import main_bp
from app.route_support import (
    admin_required,
    ensure_boolean_toggle,
    menu_key_required,
    safe_all,
    safe_db_rollback,
    safe_render,
)
from app.security.critical_operations import hierarchy_sync_refusal
from app.services.ai import build_org_unit_detail_ai_panel, build_org_units_risk_map_ai_panel
from app.services.hierarchy_admin_service import (
    sync_organization_units_from_users_if_stale,
)
from app.services.performance.hierarchy_assignment_sync_guard import (
    begin_hierarchy_change,
    commit_hierarchy_change,
    hierarchy_change_refusal,
)
from app.utils.turkish_text import turkish_casefold

logger = logging.getLogger(__name__)

LEGACY_SHIM = False
LEGACY_RUNTIME_STATUS = "active_modular_main_blueprint_routes"
LEGACY_ROUTE_FAMILY = "institutional_org_unit_management"
LEGACY_NOTE = (
    "Phase 47 ile organizasyon birimi CRUD ve listeleme route'lari "
    "app.institutional.org_unit_routes modülüne taşındı."
)

UNIT_TYPE_CHOICES = [
    ("baskanlik", "Başkanlık"),
    ("baskan_yardimciligi", "Başkan Yardımcılığı"),
    ("grup_baskanligi", "Grup Başkanlığı"),
    ("calisma_grubu", "Çalışma Grubu"),
    ("koordinatorluk", "Koordinatörlük"),
    ("diger", "Diğer"),
]


def collect_descendant_unit_ids(root_unit: OrganizationUnit) -> set[int]:
    """Birimi kendi altına bağlama kazasını önlemek için basit DFS."""
    seen: set[int] = set()
    stack = [root_unit.id]
    while stack:
        current_id = stack.pop()
        children = (
            OrganizationUnit.query
            .filter(OrganizationUnit.parent_id == current_id)
            .with_entities(OrganizationUnit.id)
            .all()
        )
        for child_id, in children:
            if child_id in seen:
                continue
            seen.add(child_id)
            stack.append(child_id)
    return seen


@main_bp.route("/admin/org-units")
@login_required
@admin_required
@menu_key_required("org_units")
def admin_org_units():
    q = (request.args.get("q") or "").strip()
    ust_birim = (request.args.get("ust_birim") or "").strip()
    durum = (request.args.get("durum") or "").strip()
    return redirect(url_for("main.org_units_list", q=q, ust_birim=ust_birim, durum=durum))


@main_bp.route("/admin/org-units/create", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("org_units")
def admin_org_unit_create():
    parent_options = safe_all(
        OrganizationUnit.query.order_by(OrganizationUnit.name.asc()),
        label="org_unit_create_parents",
    )

    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            unit_type = (request.form.get("unit_type") or "diger").strip()
            parent_id_raw = (request.form.get("parent_id") or "").strip()
            sort_order_raw = (request.form.get("sort_order") or "0").strip()
            is_active = (request.form.get("is_active") or "").strip().lower() in {"1", "true", "on", "evet", "aktif", "yes"}

            if not name:
                flash("Birim adı zorunludur.", "warning")
                return redirect(url_for("main.admin_org_unit_create"))

            parent_id = int(parent_id_raw) if parent_id_raw.isdigit() else None
            sort_order = int(sort_order_raw) if sort_order_raw.isdigit() else 0

            # BYS360 DEFECT AR: karsilastirma artik veritabaninin LOWER()
            # uygulamasina guvenmiyor (SQLite Turkce buyuk/kucuk harf
            # donusumunu ASCII disinda uygulamaz, PostgreSQL davranisi ise
            # dogrulanamaz); ayni parent_id altindaki adaylar sorguyla
            # daraltilir, esitlik Python tarafinda turkish_casefold ile
            # tutarli sekilde kontrol edilir.
            name_fold = turkish_casefold(name)
            existing = next(
                (
                    candidate
                    for candidate in OrganizationUnit.query.filter(
                        OrganizationUnit.parent_id == parent_id,
                    ).all()
                    if turkish_casefold(candidate.name) == name_fold
                ),
                None,
            )

            if existing:
                flash("Aynı üst birim altında bu isimde bir birim zaten mevcut.", "warning")
                return redirect(url_for("main.admin_org_unit_create"))

            new_unit = OrganizationUnit(
                name=name,
                unit_type=unit_type,
                parent_id=parent_id,
                sort_order=sort_order,
                is_active=is_active,
            )

            db.session.add(new_unit)
            db.session.commit()
            flash("Yeni birim oluşturuldu.", "success")
            return redirect(url_for("main.admin_org_units"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            safe_db_rollback()
            flash("Birim oluşturulurken hata oluştu.", "danger")
            return redirect(url_for("main.admin_org_unit_create"))

    return safe_render(
        "org_unit_form.html",
        "<h3>Yeni Birim</h3>",
        page_title_text="Yeni Birim Oluştur",
        submit_label="Birimi Kaydet",
        unit_obj=None,
        parent_options=parent_options,
        unit_type_choices=UNIT_TYPE_CHOICES,
        ai_org_unit_panel=build_org_unit_detail_ai_panel(unit_obj=None, parent_options=parent_options),
    )


@main_bp.route("/admin/org-units/<int:unit_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("org_units")
def admin_org_unit_edit(unit_id: int):
    unit = OrganizationUnit.query.get_or_404(unit_id)

    parent_options = safe_all(
        OrganizationUnit.query
        .filter(OrganizationUnit.id != unit.id)
        .order_by(OrganizationUnit.name.asc()),
        label="org_unit_edit_parents",
    )

    if request.method == "POST":
        try:
            old_name = (unit.name or "").strip()
            old_parent_name = (unit.parent.name if unit.parent else "").strip()

            name = (request.form.get("name") or "").strip()
            unit_type = (request.form.get("unit_type") or "diger").strip()
            parent_id_raw = (request.form.get("parent_id") or "").strip()
            sort_order_raw = (request.form.get("sort_order") or "0").strip()
            is_active = (request.form.get("is_active") or "").strip().lower() in {"1", "true", "on", "evet", "aktif", "yes"}

            if not name:
                flash("Birim adı zorunludur.", "warning")
                return redirect(url_for("main.admin_org_unit_edit", unit_id=unit.id))

            parent_id = int(parent_id_raw) if parent_id_raw.isdigit() else None
            sort_order = int(sort_order_raw) if sort_order_raw.isdigit() else 0

            if parent_id == unit.id:
                flash("Bir birim kendisinin üst birimi olamaz.", "warning")
                return redirect(url_for("main.admin_org_unit_edit", unit_id=unit.id))

            descendant_ids = collect_descendant_unit_ids(unit)
            if parent_id and parent_id in descendant_ids:
                flash("Bir birim kendi alt birimlerinden birine bağlanamaz.", "warning")
                return redirect(url_for("main.admin_org_unit_edit", unit_id=unit.id))

            # BYS360 DEFECT AR: bkz. admin_org_unit_create() ayni not.
            name_fold = turkish_casefold(name)
            duplicate = next(
                (
                    candidate
                    for candidate in OrganizationUnit.query.filter(
                        OrganizationUnit.id != unit.id,
                        OrganizationUnit.parent_id == parent_id,
                    ).all()
                    if turkish_casefold(candidate.name) == name_fold
                ),
                None,
            )
            if duplicate:
                flash("Aynı üst birim altında bu isimde başka bir birim zaten mevcut.", "warning")
                return redirect(url_for("main.admin_org_unit_edit", unit_id=unit.id))

            plan = begin_hierarchy_change()
            unit.name = name
            unit.unit_type = unit_type
            unit.parent_id = parent_id
            unit.sort_order = sort_order
            unit.is_active = is_active

            new_parent_name = ""
            if parent_id:
                parent_obj = db.session.get(OrganizationUnit, parent_id)
                new_parent_name = (parent_obj.name if parent_obj else "").strip()

            linked_users = unit.users.all() if hasattr(unit.users, "all") else list(unit.users)
            for linked_user in linked_users:
                if (linked_user.birim or "").strip() == old_name or not (linked_user.birim or "").strip():
                    linked_user.birim = name

                if old_parent_name:
                    if (linked_user.ust_birim or "").strip() == old_parent_name:
                        linked_user.ust_birim = new_parent_name or name
                else:
                    if not (linked_user.ust_birim or "").strip() or (linked_user.ust_birim or "").strip() == old_name:
                        linked_user.ust_birim = new_parent_name or name

            # M-1: personelin birim/üst birim ve dönem kapsamını değiştiren düzenleme, aktif dönemde
            # gerçek admin dışında reddedilir; gerçek admin için görev senkronuyla birlikte yazılır.
            refusal = hierarchy_change_refusal(plan)
            if refusal is not None:
                return hierarchy_sync_refusal(refusal, None, url_for("main.admin_org_unit_edit", unit_id=unit.id))
            commit_hierarchy_change(plan, actor_user_id=getattr(current_user, "id", None))
            flash("Birim bilgileri güncellendi.", "success")
            return redirect(url_for("main.admin_org_units"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            safe_db_rollback()
            flash("Birim güncellenirken hata oluştu.", "danger")
            return redirect(url_for("main.admin_org_unit_edit", unit_id=unit.id))

    return safe_render(
        "org_unit_form.html",
        "<h3>Birim Düzenle</h3>",
        page_title_text="Birim Düzenle",
        submit_label="Değişiklikleri Kaydet",
        unit_obj=unit,
        parent_options=parent_options,
        unit_type_choices=UNIT_TYPE_CHOICES,
        ai_org_unit_panel=build_org_unit_detail_ai_panel(unit_obj=unit, parent_options=parent_options),
    )


@main_bp.route("/admin/org-units/<int:unit_id>/toggle-active", methods=["POST"])
@login_required
@admin_required
@menu_key_required("org_units")
def admin_org_unit_toggle_active(unit_id: int):
    unit = OrganizationUnit.query.get_or_404(unit_id)

    try:
        unit.is_active = ensure_boolean_toggle(current_value=getattr(unit, "is_active", False), entity_label="Birim aktiflik durumu", requested_state=request.form.get("target_state"))
        db.session.commit()
        if unit.is_active:
            flash("Birim aktif hale getirildi.", "success")
        else:
            flash("Birim pasif hale getirildi.", "warning")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Birim durumu güncellenirken hata oluştu.", "danger")

    return redirect(url_for("main.admin_org_units"))


@main_bp.route("/org-units")
@login_required
@admin_required
@menu_key_required("org_units")
def org_units_list():
    try:
        sync_organization_units_from_users_if_stale(commit=True)
    except Exception as exc:
        safe_db_rollback()
        current_app.logger.exception("Organizasyon birimi senkronu sırasında hata: %s", exc)

    q = (request.args.get("q") or "").strip()
    ust_birim = (request.args.get("ust_birim") or "").strip()
    durum = (request.args.get("durum") or "").strip()

    Parent = aliased(OrganizationUnit)
    Child = aliased(OrganizationUnit)

    child_counts_sq = (
        db.session.query(
            Child.parent_id.label("parent_id"),
            func.count(Child.id).label("child_count"),
        )
        .group_by(Child.parent_id)
        .subquery()
    )

    personnel_counts_sq = (
        db.session.query(
            User.organization_unit_id.label("unit_id"),
            func.count(User.id).label("personnel_count"),
        )
        .filter(User.role != "admin")
        .group_by(User.organization_unit_id)
        .subquery()
    )

    query = (
        db.session.query(
            OrganizationUnit,
            Parent.name.label("parent_name"),
            func.coalesce(child_counts_sq.c.child_count, 0).label("child_count"),
            func.coalesce(personnel_counts_sq.c.personnel_count, 0).label("personnel_count"),
        )
        .outerjoin(Parent, OrganizationUnit.parent_id == Parent.id)
        .outerjoin(child_counts_sq, child_counts_sq.c.parent_id == OrganizationUnit.id)
        .outerjoin(personnel_counts_sq, personnel_counts_sq.c.unit_id == OrganizationUnit.id)
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                OrganizationUnit.name.ilike(like),
                OrganizationUnit.unit_type.ilike(like),
                OrganizationUnit.unit_code.ilike(like),
                Parent.name.ilike(like),
            )
        )

    if ust_birim:
        query = query.filter(Parent.name == ust_birim)

    if durum == "aktif":
        query = query.filter(OrganizationUnit.is_active.is_(True))
    elif durum == "pasif":
        query = query.filter(OrganizationUnit.is_active.is_(False))

    rows_raw = query.order_by(Parent.name.asc().nullsfirst(), OrganizationUnit.name.asc()).all()
    all_units = OrganizationUnit.query.order_by(OrganizationUnit.name.asc()).all()

    parent_names = sorted({(parent_name or "").strip() for _, parent_name, _, _ in rows_raw if (parent_name or "").strip()})
    rows = []
    for unit, parent_name, child_count, personnel_count in rows_raw:
        rows.append({
            "unit": unit,
            "parent_name": parent_name or "-",
            "child_count": int(child_count or 0),
            "personnel_count": int(personnel_count or 0),
        })

    stats = {
        "total_count": len(all_units),
        "active_count": sum(1 for x in all_units if bool(getattr(x, "is_active", True))),
        "passive_count": sum(1 for x in all_units if not bool(getattr(x, "is_active", True))),
        "root_count": sum(1 for x in all_units if not getattr(x, "parent_id", None)),
        "position_count": len({(getattr(x, "unit_type", "") or "").strip() for x in all_units if (getattr(x, "unit_type", "") or "").strip()}),
        "filtered_count": len(rows),
    }

    return safe_render(
        "org_units_list.html",
        "<h3>Birim ve Pozisyon Yönetimi</h3>",
        stats=stats,
        rows=rows,
        q=q,
        selected_parent=ust_birim,
        selected_durum=durum,
        parent_names=parent_names,
        ai_org_units_risk_panel=build_org_units_risk_map_ai_panel(rows=rows, stats=stats),
    )


@main_bp.route("/org-units/add", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("org_units")
def org_unit_add():
    parent_units = OrganizationUnit.query.order_by(OrganizationUnit.name.asc()).all()

    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            unit_type = (request.form.get("position_name") or "").strip() or "diger"
            parent_id = request.form.get("parent_id", type=int)

            if not name:
                flash("Birim adı zorunludur.", "warning")
                return redirect(url_for("main.org_unit_add"))

            exists = OrganizationUnit.query.filter_by(name=name, parent_id=parent_id).first()
            if exists:
                flash("Aynı üst birim altında bu isimde bir kayıt zaten var.", "danger")
                return redirect(url_for("main.org_unit_add"))

            unit = OrganizationUnit()
            unit.name = name
            if hasattr(unit, "unit_type"):
                unit.unit_type = unit_type
            if hasattr(unit, "parent_id"):
                unit.parent_id = parent_id
            if hasattr(unit, "is_active"):
                unit.is_active = True

            db.session.add(unit)
            db.session.commit()
            flash("Birim kaydı oluşturuldu.", "success")
            return redirect(url_for("main.org_units_list"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Birim ekleme sırasında hata oluştu.", "danger")

    return safe_render(
        "org_unit_form.html",
        "<h3>Yeni Birim Ekle</h3>",
        mode="add",
        unit=None,
        parent_units=parent_units,
        parent_options=parent_units,
        ai_org_unit_panel=build_org_unit_detail_ai_panel(unit_obj=None, parent_options=parent_units),
    )


@main_bp.route("/org-units/<int:unit_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("org_units")
def org_unit_edit(unit_id: int):
    unit = db.session.get(OrganizationUnit, unit_id)
    if not unit:
        flash("Birim kaydı bulunamadı.", "danger")
        return redirect(url_for("main.org_units_list"))

    parent_units = OrganizationUnit.query.filter(OrganizationUnit.id != unit.id).order_by(OrganizationUnit.name.asc()).all()

    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            position_name = (request.form.get("position_name") or "").strip()
            parent_id = request.form.get("parent_id", type=int)
            description = (request.form.get("description") or "").strip()

            if not name:
                flash("Birim adı zorunludur.", "warning")
                return redirect(url_for("main.org_unit_edit", unit_id=unit.id))

            exists = OrganizationUnit.query.filter(
                OrganizationUnit.name == name,
                OrganizationUnit.parent_id == parent_id,
                OrganizationUnit.id != unit.id,
            ).first()
            if exists:
                flash("Aynı üst birim altında bu isimde başka bir kayıt zaten var.", "danger")
                return redirect(url_for("main.org_unit_edit", unit_id=unit.id))

            plan = begin_hierarchy_change()
            unit.name = name
            if hasattr(unit, "position_name"):
                unit.position_name = position_name
            if hasattr(unit, "parent_id"):
                unit.parent_id = parent_id
            if hasattr(unit, "description"):
                unit.description = description
            if hasattr(unit, "is_active"):
                unit.is_active = bool(request.form.get("is_active"))

            # M-1: birim adı/üst birimi dönem kapsamını değiştirir; aktif dönemde gerçek admin dışında reddedilir.
            refusal = hierarchy_change_refusal(plan)
            if refusal is not None:
                return hierarchy_sync_refusal(refusal, None, url_for("main.org_unit_edit", unit_id=unit.id))
            commit_hierarchy_change(plan, actor_user_id=getattr(current_user, "id", None))
            flash("Birim kaydı güncellendi.", "success")
            return redirect(url_for("main.org_units_list"))

        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            db.session.rollback()
            flash("Birim güncelleme sırasında hata oluştu.", "danger")

    return safe_render(
        "org_unit_form.html",
        "<h3>Birim Düzenle</h3>",
        mode="edit",
        unit=unit,
        parent_units=parent_units,
        parent_options=parent_units,
        ai_org_unit_panel=build_org_unit_detail_ai_panel(unit_obj=unit, parent_options=parent_units),
    )


@main_bp.route("/org-units/<int:unit_id>/delete", methods=["POST"])
@login_required
@admin_required
@menu_key_required("org_units")
def org_unit_delete(unit_id: int):
    unit = db.session.get(OrganizationUnit, unit_id)
    if not unit:
        flash("Birim kaydı bulunamadı.", "danger")
        return redirect(url_for("main.org_units_list"))

    try:
        child_exists = OrganizationUnit.query.filter_by(parent_id=unit.id).first()
        if child_exists:
            flash("Bu birime bağlı alt birimler olduğu için silinemez.", "warning")
            return redirect(url_for("main.org_units_list"))
        linked_user = User.query.filter_by(organization_unit_id=unit.id).first() if "User" in globals() else None
        if linked_user:
            flash("Bu birime bağlı personel olduğu için silinemez. Pasif yapmayı tercih edin.", "warning")
            return redirect(url_for("main.org_units_list"))

        db.session.delete(unit)
        db.session.commit()
        flash("Birim kaydı silindi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Silme işlemi sırasında hata oluştu.", "danger")

    return redirect(url_for("main.org_units_list"))


@main_bp.route("/admin/org-units/<int:unit_id>/delete", methods=["POST"], endpoint="admin_org_unit_delete")
@login_required
@admin_required
@menu_key_required("org_units")
def admin_org_unit_delete(unit_id: int):
    return org_unit_delete(unit_id)


__all__ = [
    "LEGACY_SHIM",
    "LEGACY_RUNTIME_STATUS",
    "LEGACY_ROUTE_FAMILY",
    "LEGACY_NOTE",
    "admin_org_units",
    "admin_org_unit_create",
    "admin_org_unit_edit",
    "admin_org_unit_toggle_active",
    "org_units_list",
    "org_unit_add",
    "org_unit_edit",
    "org_unit_delete",
    "admin_org_unit_delete",
]