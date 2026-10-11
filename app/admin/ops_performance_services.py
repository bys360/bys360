"""Operational admin performance services extracted from ops_routes.py.

Route decorators stay in ops_routes.py. This module contains implementation bodies.
"""
from __future__ import annotations

from flask import flash, redirect, request, url_for
from flask_login import current_user

from app.extensions import db
from app.models import PerformancePeriod, User
from app.services.account_change_guard import (
    MANAGER_CHAIN_REFUSAL_MESSAGE,
    audit_refusal,
    may_change_manager_chain,
)
from app.services.performance_service import generate_assignments_for_active_period


def performance_hierarchy_bulk_assign_impl():
    ust_birim = (request.form.get("ust_birim") or "").strip()
    birim = (request.form.get("birim") or "").strip()
    role = (request.form.get("role") or "").strip()

    yonetici_sicil = (request.form.get("bulk_yonetici_sicil") or "").strip() or None
    ikinci_yonetici_sicil = (request.form.get("bulk_ikinci_yonetici_sicil") or "").strip() or None
    ucuncu_yonetici_sicil = (request.form.get("bulk_ucuncu_yonetici_sicil") or "").strip() or None
    level_3_enabled = request.form.get("bulk_level_3_enabled") == "on"

    query = User.query.filter(User.role != "admin")
    if ust_birim:
        query = query.filter(User.ust_birim == ust_birim)
    if birim:
        query = query.filter(User.birim == birim)
    if role:
        query = query.filter(User.role == role)

    users = query.all()
    if not users:
        flash("Toplu atama için uygun personel bulunamadı.", "warning")
        return redirect(url_for("main.performance_hierarchy_settings"))

    # R05: a non-admin never changes a protected account's chain nor adds themselves to a
    # chain; one such row refuses the whole bulk assignment (nothing is written).
    new_chain = [yonetici_sicil, ikinci_yonetici_sicil, ucuncu_yonetici_sicil if level_3_enabled else None]
    refused = next((u for u in users if not may_change_manager_chain(current_user, u, new_chain)), None)
    if refused is not None:
        audit_refusal(refused, "bulk_manager_chain_change")
        flash(MANAGER_CHAIN_REFUSAL_MESSAGE + " Toplu atama yapılmadı.", "danger")
        return redirect(url_for("main.performance_hierarchy_settings"))

    updated_count = 0
    for user_obj in users:
        # Rol/ünvan anahtar kelimesine göre otomatik daraltma yapılmaz.
        # Tek amir istisnası yalnızca gerçekten başkana doğrudan bağlı ve
        # sadece başkanın puan verdiği personelde, alanlar o şekilde boş
        # bırakıldıysa oluşur.
        user_obj.yonetici_sicil = yonetici_sicil
        user_obj.ikinci_yonetici_sicil = ikinci_yonetici_sicil
        user_obj.ucuncu_yonetici_sicil = ucuncu_yonetici_sicil if level_3_enabled else None
        updated_count += 1

    db.session.commit()

    active_period = PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
    assignment_result = None
    if active_period:
        assignment_result = generate_assignments_for_active_period(period_id=active_period.id, actor_user_id=current_user.id)

    flash(f"Toplu hiyerarşi ataması tamamlandı. Güncellenen personel: {updated_count}", "success")
    if assignment_result and assignment_result.get("ok"):
        flash("Aktif dönem görevleri toplu hiyerarşi ataması sonrası yeniden senkronlandı.", "success")
    elif assignment_result and not assignment_result.get("ok"):
        flash(assignment_result.get("message", "Aktif dönem görevleri yeniden senkronlanamadı."), "warning")
    return redirect(url_for("main.performance_hierarchy_settings"))
