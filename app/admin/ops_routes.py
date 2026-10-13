from __future__ import annotations

import logging
from typing import Any

from app.services.safe_user_delete_service import safe_delete_user_by_id

"""Admin operasyon route ailesi.

Bu dosya admin toplu işlemleri, personel profil/aksiyonları ve
hiyerarşi yardımcı rotalarını modüler yapı altında toplar.
"""


from flask import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    flash,
    redirect,
    url_for,
)
from flask_login import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    current_user,
    login_required,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)

from app.extensions import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    db,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from app.models import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    User,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from app.route_registry import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    main_bp,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from app.route_support import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    admin_required,
    menu_key_required,
)
from app.services.account_change_guard import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    ADMIN_CONTINUITY_MESSAGE,
    REFUSAL_MESSAGE,
    admin_continuity_refusal,
    audit_account_change,
    audit_refusal,
    may_change_account_state,
    record_account_changes,
)

from .ops_health_services import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    admin_import_health_report_impl,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from .ops_import_services import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    admin_user_import_impl,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from .ops_performance_services import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    performance_hierarchy_bulk_assign_impl,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from .ops_personnel_services import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    download_personnel_template_impl,
    personnel_profile_impl,
)
from .ops_user_action_services import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    admin_user_archive_impl,
    admin_user_change_photo_impl,
    admin_user_delete_impl,
    admin_user_toggle_active_impl,
    admin_users_bulk_archive_impl,
    admin_users_bulk_delete_impl,
    admin_users_bulk_passive_impl,
    admin_users_reset_all_impl,
)

logger = logging.getLogger(__name__)

LEGACY_SHIM = False
LEGACY_RUNTIME_STATUS = "active_modular_main_blueprint_routes"
LEGACY_ROUTE_FAMILY = "admin_bulk_ops_and_personnel_actions"
LEGACY_NOTE = (
    "Admin toplu işlemleri, personel profil/aksiyonları ve hiyerarşi "
    "yardımcı rotaları app.admin.ops_routes altında çalışır."
)








IMPORT_HEADER_ALIASES = {
    'kategori': 'personnel_category',
    'personel kategori': 'personnel_category',
    'personel kategorisi': 'personnel_category',
    'performans kategori': 'personnel_category',
    'performans kategorisi': 'personnel_category',
    'performance category': 'personnel_category',
    'performance_category': 'personnel_category',
    'personnel_category': 'personnel_category',
    'sicil no': 'sicil_no',
    'sicil': 'sicil_no',
    'e posta': 'email',
    'eposta': 'email',
    'mail': 'email',
    'ünvan': 'unvan',
    'ust birim': 'ust_birim',
    'üst birim': 'ust_birim',
    'rol': 'role',
    'yonetici sicil': 'yonetici_sicil',
    'yönetici sicil': 'yonetici_sicil',
    '1 amir': 'yonetici_sicil',
    '1. amir': 'yonetici_sicil',
    'ikinci yonetici sicil': 'ikinci_yonetici_sicil',
    'ikinci yönetici sicil': 'ikinci_yonetici_sicil',
    '2 amir': 'ikinci_yonetici_sicil',
    '2. amir': 'ikinci_yonetici_sicil',
    'ucuncu yonetici sicil': 'ucuncu_yonetici_sicil',
    'üçüncü yönetici sicil': 'ucuncu_yonetici_sicil',
    '3 amir': 'ucuncu_yonetici_sicil',
    '3. amir': 'ucuncu_yonetici_sicil',
    'aktif': 'is_active',
}





@main_bp.route("/admin/users/<int:user_id>/photo", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_user_change_photo(user_id: int):
    return admin_user_change_photo_impl(user_id)


@main_bp.route("/admin/users/<int:user_id>/toggle-active", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_user_toggle_active(user_id: int):
    return admin_user_toggle_active_impl(user_id)


@main_bp.route("/admin/users/<int:user_id>/archive", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_user_archive(user_id: int):
    return admin_user_archive_impl(user_id)


@main_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_user_delete(user_id: int):
    return admin_user_delete_impl(user_id)


@main_bp.route("/admin/users/bulk-delete", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_users_bulk_delete():
    return admin_users_bulk_delete_impl()


@main_bp.route("/admin/users/bulk-archive", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_users_bulk_archive():
    return admin_users_bulk_archive_impl()


@main_bp.route("/admin/users/bulk-passive", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_users_bulk_passive():
    return admin_users_bulk_passive_impl()


@main_bp.route("/admin/users/import", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_user_import():
    return admin_user_import_impl()


@main_bp.route("/admin/import-health-report")
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_import_health_report():
    return admin_import_health_report_impl()


@main_bp.route("/admin/users/reset-all", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def admin_users_reset_all():
    return admin_users_reset_all_impl()


@main_bp.route("/performance/hierarchy-settings/bulk-assign", methods=["POST"])
@login_required
@admin_required
def performance_hierarchy_bulk_assign():
    return performance_hierarchy_bulk_assign_impl()


@main_bp.route("/personnel/template/download")
@login_required
@admin_required
@menu_key_required("admin_users")
def download_personnel_template():
    return download_personnel_template_impl()


@main_bp.route("/personnel/<int:user_id>/toggle-active", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_toggle_active(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        flash("Personel kaydı bulunamadı.", "danger")
        return redirect(url_for("main.personnel_list"))

    # R05: a non-admin editor never switches a protected account on or off.
    if not may_change_account_state(current_user, user):
        audit_refusal(user, "activation_change")
        flash(REFUSAL_MESSAGE, "danger")
        return redirect(url_for("main.personnel_list"))

    # R05-5 / K4 / C: an admin never deactivates itself; never the last active admin.
    continuity_refusal = admin_continuity_refusal(current_user, user, new_role=user.role, new_active=not bool(user.is_active))
    if continuity_refusal:
        audit_refusal(user, continuity_refusal)
        flash(ADMIN_CONTINUITY_MESSAGE, "danger")
        return redirect(url_for("main.personnel_list"))

    try:
        if hasattr(user, "is_active"):
            old_active = bool(user.is_active)
            user.is_active = not old_active
            record_account_changes(user, old_role=user.role, old_active=old_active)
            db.session.commit()
            flash("Personel aktiflik durumu güncellendi.", "success")
        else:
            flash("Bu kullanıcı modelinde aktiflik alanı bulunamadı.", "warning")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Durum güncelleme sırasında hata oluştu.", "danger")

    return redirect(url_for("main.personnel_list"))


@main_bp.route("/personnel/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_delete(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        flash("Personel kaydı bulunamadı.", "danger")
        return redirect(url_for("main.personnel_list"))

    # R05: a non-admin editor never deletes a protected account (their own included).
    if not may_change_account_state(current_user, user):
        audit_refusal(user, "delete")
        flash(REFUSAL_MESSAGE, "danger")
        return redirect(url_for("main.personnel_list"))

    try:
        audit_account_change(
            "account.delete",
            user,
            old={"role": user.role, "is_active": bool(user.is_active), "sicil_no": user.sicil_no},
        )
        safe_delete_user_by_id(getattr(user, "id", user), commit=False)
        db.session.commit()
        flash("Personel kaydı silindi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Silme işlemi sırasında hata oluştu.", "danger")

    return redirect(url_for("main.personnel_list"))


@main_bp.route("/personnel/<int:user_id>/profile")
@login_required
@admin_required
@menu_key_required("admin_users")
def personnel_profile(user_id: int):
    return personnel_profile_impl(user_id)


__all__ = [
    "LEGACY_SHIM",
    "LEGACY_RUNTIME_STATUS",
    "LEGACY_ROUTE_FAMILY",
    "LEGACY_NOTE",
    "admin_user_change_photo",
    "admin_user_toggle_active",
    "admin_user_archive",
    "admin_user_delete",
    "admin_users_bulk_delete",
    "admin_users_bulk_archive",
    "admin_users_bulk_passive",
    "admin_user_import",
    "admin_import_health_report",
    "admin_users_reset_all",
    "performance_hierarchy_bulk_assign",
    "download_personnel_template",
    "personnel_toggle_active",
    "personnel_delete",
    "personnel_profile",
]

# BYS360_PERFORMANCE_COMPLETION_PHASE2_IMPORT_CATEGORY_MARKER
# Toplu personel import tarafında kategori/personel kategorisi sütunları desteklenir.
try:
    from app.services.performance.phase2_category_center import (
        normalize_category_label as _phase2_normalize_category_label,
    )
except Exception:
    def _phase2_normalize_category_label(value: Any) -> str:
        return str(value or "Diğer").strip() or "Diğer"


# Compatibility guard.
def ensure_not_self_target(actor_id, target_id, entity_label="kayıt"):
    if actor_id is not None and target_id is not None and str(actor_id) == str(target_id):
        raise ValueError(f"Kendi {entity_label} kaydınız üzerinde bu işlem yapılamaz.")

