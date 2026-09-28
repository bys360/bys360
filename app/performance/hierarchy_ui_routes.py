from __future__ import annotations

import logging
from typing import cast

logger = logging.getLogger(__name__)

def _build_surface_scope_context(user, raw_scope):
    """view_helpers import döngüsünü kırmak için gerçek yardımcı çağrı anında
    yüklenir (app/performance/routes.py ile aynı desen). Eskiden kendi kendini
    çağırıyordu; /performance/hierarchy-tree-live her istekte RecursionError
    ile 500 dönüyordu."""
    from importlib import import_module

    helper = import_module("app.view_helpers").build_surface_scope_context
    return helper(user, raw_scope)


# --- BYS360 third-manager Excel import compatibility patch ---


def _phase2_build_surface_scope_context_lazy(*args, **kwargs):
    """view_helpers import döngüsünü kırmak için çağrı anında yükleme."""

    return _build_surface_scope_context(*args, **kwargs)
THIRD_MANAGER_STANDARD_KEY = "ucuncu_yonetici_sicil"
THIRD_MANAGER_HEADER_ALIASES = [
    "ucuncu_yonetici_sicil",
    "üçüncü yönetici sicil",
    "ucuncu yonetici sicil",
    "3. amir sicil",
    "3 amir sicil",
    "new_y3",
]

from flask import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    flash,
    redirect,
    request,
    url_for,
)
from flask_login import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    current_user,
    login_required,
)

from app.extensions import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    db,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from app.models import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    PerformancePeriod,
    User,
)
from app.route_registry import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    main_bp,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from app.route_support import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    admin_required,
    manager_required,
    menu_key_required,
    safe_db_rollback,
    safe_render,
)
from app.services.hierarchy_admin_service import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    sync_organization_units_from_users_if_stale,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from app.services.performance.context import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    list_performance_periods,  # noqa: E402 - deferred import (staged facade/route-registration architecture)
)
from app.services.performance.hierarchy_ui_service import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    SPECIAL_SINGLE_MANAGER_UNITS,
    SPECIAL_TOP_ROLES,
    build_assignment_rows,
    build_grouped_tree,
    display_name,
    filter_users,
    manager_map,
    row_for_user,
)


def _display_name(user: User | None) -> str:
    return display_name(user)


def _manager_map(users: list[User]) -> dict[str, User]:
    return cast("dict[str, User]", manager_map(users))


def _row_for_user(user: User, by_sicil: dict[str, User]) -> dict[str, object]:
    return row_for_user(
        user,
        by_sicil,
        special_single_manager_units=SPECIAL_SINGLE_MANAGER_UNITS,
        special_top_roles=SPECIAL_TOP_ROLES,
    )


@main_bp.route("/performance/hierarchy-tree-live", endpoint="performance_hierarchy_tree_live")
@login_required
@manager_required
@menu_key_required("performance_hierarchy_tree")
def performance_hierarchy_tree_live():
    try:
        sync_organization_units_from_users_if_stale(commit=True)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        safe_db_rollback()

    period_id = request.args.get("period_id", type=int)
    birim = (request.args.get("birim") or "").strip()
    q = (request.args.get("q") or "").strip()
    scope_ctx = _phase2_build_surface_scope_context_lazy(current_user, request.args.get("scope"))
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
    users = filter_users(all_users, q=q, birim=birim)
    tree_payload = build_grouped_tree(users)
    all_tree_payload = build_grouped_tree(all_users)

    return safe_render(
        "hierarchy_tree.html",
        "<h3>Hiyerarşi Ağacı</h3>",
        periods=periods,
        selected_period=selected_period,
        birimler=all_tree_payload["birimler"],
        selected_birim=birim,
        q=q,
        grouped_tree=tree_payload["grouped_tree"],
        total_user_count=tree_payload["total_user_count"],
        scope_total_user_count=len(all_users),
        parent_count=tree_payload["parent_count"],
        active_count=tree_payload["active_count"],
        passive_count=tree_payload["passive_count"],
        selected_scope=selected_scope,
        scope_options=scope_ctx.get("scope_options"),
        scope_option_pairs=scope_ctx.get("scope_option_pairs"),
        scope_label=scope_ctx.get("scope_label"),
        scope_role_title=scope_ctx.get("role_title"),
        scope_user_count=scope_ctx.get("scope_user_count", 0),
        scope_unit_count=scope_ctx.get("scope_unit_count", 0),
        ai_hierarchy_tree_panel=None,
    )


@main_bp.route("/performance/hierarchy-assignments-live", methods=["GET", "POST"], endpoint="performance_hierarchy_assignments_live")
@login_required
@admin_required
@menu_key_required("performance_hierarchy_assignments")
def performance_hierarchy_assignments_live():
    q = (request.values.get("q") or "").strip()
    birim = (request.values.get("birim") or "").strip()
    selected_user_id = request.values.get("user_id", type=int)

    all_users = User.query.filter(User.role != "admin").order_by(User.ad.asc(), User.soyad.asc()).all()
    assignment_payload = build_assignment_rows(all_users, q=q, birim=birim)

    if request.method == "POST" and selected_user_id:
        user = db.session.get(User, selected_user_id)
        if not user or getattr(user, "role", None) == "admin":
            flash("Personel kaydı bulunamadı.", "warning")
            return redirect(url_for("main.performance_hierarchy_assignments_live"))
        try:
            user.yonetici_sicil = (request.form.get("yonetici_sicil") or "").strip() or None
            user.ikinci_yonetici_sicil = (request.form.get("ikinci_yonetici_sicil") or "").strip() or None
            user.ucuncu_yonetici_sicil = (request.form.get("ucuncu_yonetici_sicil") or "").strip() or None
            db.session.commit()
            flash("Hiyerarşi ataması kaydedildi.", "success")
            return redirect(url_for("main.performance_hierarchy_assignments_live", user_id=user.id, q=q, birim=birim))
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            safe_db_rollback()
            flash("Hiyerarşi ataması kaydedilirken hata oluştu.", "danger")

    filtered = cast("list[User]", assignment_payload["filtered_users"])
    selected_user = None
    if selected_user_id:
        selected_user = db.session.get(User, selected_user_id)
        if selected_user and getattr(selected_user, "role", None) == "admin":
            selected_user = None
    if not selected_user and filtered:
        selected_user = filtered[0]

    return safe_render(
        "hierarchy_assignments.html",
        "<h3>Hiyerarşi Atamaları</h3>",
        all_users=assignment_payload["all_users"],
        birimler=assignment_payload["birimler"],
        q=q,
        selected_user=selected_user,
        incomplete_users=assignment_payload["incomplete_users"],
        stats=assignment_payload["stats"],
        personnel=filtered,
    )