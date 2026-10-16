"""Operational admin user action services extracted from ops_routes.py.

Route decorators stay in ops_routes.py. This module contains implementation bodies.
"""
from __future__ import annotations

import logging

from flask import flash, redirect, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import User
from app.route_support import ensure_boolean_toggle, normalize_int_list
from app.services.account_change_guard import (
    ADMIN_CONTINUITY_MESSAGE,
    REFUSAL_MESSAGE,
    admin_continuity_refusal,
    audit_account_change,
    audit_refusal,
    is_real_admin,
    may_change_account_state,
    record_account_changes,
    split_bulk_targets,
)
from app.services.hierarchy_admin_service import reset_all_personnel_and_related_data
from app.services.profile_photo_service import (
    delete_profile_photo_file as _delete_profile_photo_file,
    save_profile_photo as _save_profile_photo,
)
from app.services.safe_user_delete_service import safe_delete_user_by_id

logger = logging.getLogger(__name__)


def ensure_not_self_target(actor_id, target_id, entity_label="kayıt"):
    if actor_id is not None and target_id is not None and str(actor_id) == str(target_id):
        raise ValueError(f"Kendi {entity_label} kaydınız üzerinde bu işlem yapılamaz.")


def _audit_deletion(user) -> None:
    audit_account_change(
        "account.delete",
        user,
        old={"role": user.role, "is_active": bool(user.is_active), "sicil_no": user.sicil_no},
    )

BULK_PROTECTED_MESSAGE = (
    "korumalı hesap toplu işlemden çıkarıldı. Kendi hesabınız, personel dışındaki roller ve özel "
    "yetki sahipleri toplu işlemle silinemez veya arşivlenemez."
)


def _posted_bulk_user_ids() -> list[int]:
    """The selection of a bulk form: repeated ``user_ids`` fields (``/admin/users`` contract) or
    one comma-joined value (the personnel list script joins the ticked ids); ``selected_ids`` is
    that page's previous field name, still posted by a tab opened before the change. Blanks,
    non-numbers and repeats are dropped."""
    parts: list[str] = []
    for field in ("user_ids", "selected_ids"):
        for value in request.form.getlist(field):
            parts.extend(part for part in str(value).split(",") if part.strip())
    return normalize_int_list(parts)


def _split_bulk_selection(ids: list[int]) -> tuple[list[User], list[User], int]:
    """(allowed, protected, not_found) in the posted order. F3: a bulk change never touches a
    protected account, whoever runs it (own account, any role but ``personel``, explicit-grant
    holders); single-account edits stay the place for those."""
    found: list[User] = []
    missing = 0
    for user_id in ids:
        user = db.session.get(User, user_id)
        if user is None:
            missing += 1
        else:
            found.append(user)
    allowed, protected = split_bulk_targets(current_user, found)
    return allowed, protected, missing


def _report_bulk_selection(protected_count: int, missing: int) -> None:
    if protected_count:
        flash(f"{protected_count} {BULK_PROTECTED_MESSAGE}", "warning")
    if missing:
        flash(f"{missing} seçili kayıt bulunamadı ve işlem dışında kaldı.", "warning")


def admin_users_bulk_delete_impl():
    ids = _posted_bulk_user_ids()
    if not ids:
        flash("Lütfen en az bir personel seçin.", "warning")
        return redirect(url_for("main.admin_users"))

    allowed, protected, missing = _split_bulk_selection(ids)
    allowed_ids = [int(user.id) for user in allowed]
    # R05 / F3: every skipped account is audited, each in its own transaction, before any delete.
    for refused_user in protected:
        audit_refusal(refused_user, "bulk_delete")

    deleted_count = 0
    blocked_count = len(protected)

    for user_id in allowed_ids:
        user = db.session.get(User, user_id)
        if not user:
            continue
        # One account per transaction: a failure rolls back that account and its audit row only.
        try:
            _audit_deletion(user)
            safe_delete_user_by_id(user_id, commit=False)
            db.session.commit()
            deleted_count += 1
        except IntegrityError:
            db.session.rollback()
            logger.warning("BYS360 bulk delete: user %s kept (integrity error).", user_id)
            blocked_count += 1
        except Exception:
            db.session.rollback()
            logger.warning("BYS360 bulk delete: user %s kept (delete failed).", user_id, exc_info=True)
            blocked_count += 1

    _report_bulk_selection(len(protected), missing)

    if blocked_count > 0:
        flash(
            f"Toplu silme tamamlandı. Silinen: {deleted_count}, silinemeyen: {blocked_count}. "
            f"Silinemeyen kayıtlar ilişkili veri içeriyor olabilir.",
            "warning",
        )
    else:
        flash(f"Toplu silme tamamlandı. Silinen kayıt: {deleted_count}", "success")

    return redirect(url_for("main.admin_users"))

def admin_user_change_photo_impl(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        flash("Kullanıcı bulunamadı.", "danger")
        return redirect(url_for("main.admin_users"))

    try:
        remove_photo = (request.form.get("remove_profile_photo") or "").strip().lower() in {"1", "true", "on", "evet", "yes"}

        if remove_photo:
            _delete_profile_photo_file(user.profile_photo_path)
            user.profile_photo_path = None
            user.profile_photo_updated_at = utc_now()
            db.session.commit()
            flash("Profil fotoğrafı kaldırıldı.", "success")
            return redirect(url_for("main.admin_user_edit", user_id=user.id))

        photo = request.files.get("profile_photo")
        if not photo or not getattr(photo, "filename", ""):
            flash("Lütfen bir fotoğraf seçin.", "warning")
            return redirect(url_for("main.admin_user_edit", user_id=user.id))

        _save_profile_photo(photo, user)
        db.session.commit()
        flash("Profil fotoğrafı güncellendi.", "success")
        return redirect(url_for("main.admin_user_edit", user_id=user.id))

    except ValueError as exc:
        db.session.rollback()
        flash(f"Profil fotoğrafı güncellenirken hata oluştu: {exc}", "danger")
        return redirect(url_for("main.admin_user_edit", user_id=user.id))
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Profil fotoğrafı güncellenirken hata oluştu.", "danger")
        return redirect(url_for("main.admin_user_edit", user_id=user.id))

def admin_user_archive_impl(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        flash("Kullanıcı bulunamadı.", "danger")
        return redirect(url_for("main.admin_users"))

    try:
        ensure_not_self_target(actor_id=current_user.id, target_id=user.id, entity_label="kullanıcı")
        if not may_change_account_state(current_user, user):
            audit_refusal(user, "archive")
            flash(REFUSAL_MESSAGE, "danger")
            return redirect(url_for("main.admin_users"))
        if bool(getattr(user, "is_archived", False)) and not bool(getattr(user, "is_active", True)):
            flash("Kullanıcı zaten arşivde.", "warning")
            return redirect(url_for("main.admin_users"))
        continuity_refusal = admin_continuity_refusal(current_user, user, new_role=user.role, new_active=False)
        if continuity_refusal:
            audit_refusal(user, continuity_refusal)
            flash(ADMIN_CONTINUITY_MESSAGE, "danger")
            return redirect(url_for("main.admin_users"))
        old_active = bool(user.is_active)
        user.is_active = False
        if hasattr(user, "is_archived"):
            user.is_archived = True
        if hasattr(user, "archived_at") and not getattr(user, "archived_at", None):
            user.archived_at = utc_now()
        record_account_changes(user, old_role=user.role, old_active=old_active)
        db.session.commit()
        flash("Kullanıcı arşive alındı.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Arşivleme sırasında hata oluştu.", "danger")
    return redirect(url_for("main.admin_users"))

def admin_users_bulk_archive_impl():
    ids = _posted_bulk_user_ids()
    if not ids:
        flash("Lütfen en az bir personel seçin.", "warning")
        return redirect(url_for("main.admin_users"))

    allowed, protected, missing = _split_bulk_selection(ids)
    # R05 / F3: protected accounts (own included) are skipped for every actor and audited below.
    refused = [int(user.id) for user in protected]
    updated = 0
    continuity_refused = []
    for user in allowed:
        if bool(getattr(user, "is_archived", False)) and not bool(getattr(user, "is_active", True)):
            continue
        if admin_continuity_refusal(current_user, user, new_role=user.role, new_active=False):
            continuity_refused.append(user.id)
            continue
        old_active = bool(user.is_active)
        user.is_active = False
        if hasattr(user, "is_archived"):
            user.is_archived = True
        if hasattr(user, "archived_at") and not getattr(user, "archived_at", None):
            user.archived_at = utc_now()
        record_account_changes(user, old_role=user.role, old_active=old_active)
        updated += 1

    db.session.commit()
    _audit_bulk_refusals(refused, "bulk_archive")
    _report_bulk_selection(len(refused), missing)
    _report_continuity_refusals(continuity_refused, "bulk_archive")
    flash(f"Toplu arşivleme tamamlandı. Güncellenen kayıt: {updated}", "success")
    return redirect(url_for("main.admin_users"))

def admin_user_delete_impl(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        flash("Kullanıcı bulunamadı.", "danger")
        return redirect(url_for("main.admin_users"))
    if user.id == current_user.id:
        flash("Kendi hesabınızı silemezsiniz.", "warning")
        return redirect(url_for("main.admin_users"))
    if not may_change_account_state(current_user, user):
        audit_refusal(user, "delete")
        flash(REFUSAL_MESSAGE, "danger")
        return redirect(url_for("main.admin_users"))

    try:
        _audit_deletion(user)
        safe_delete_user_by_id(getattr(user, "id", user), commit=False)
        db.session.commit()
        flash("Kullanıcı silindi.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Bu kullanıcı ilişkili kayıtlar nedeniyle silinemedi.", "danger")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Bu kullanıcı silinemedi.", "danger")
    return redirect(url_for("main.admin_users"))

def admin_users_bulk_passive_impl():
    ids = normalize_int_list(request.form.getlist("user_ids"))
    if not ids:
        flash("Lütfen en az bir personel seçin.", "warning")
        return redirect(url_for("main.admin_users"))

    updated = 0
    refused = []
    continuity_refused = []
    for user_id in ids:
        user = db.session.get(User, user_id)
        if not user or user.id == current_user.id:
            continue
        # R05: a non-admin editor never deactivates a protected account.
        if not may_change_account_state(current_user, user):
            refused.append(user.id)
            continue
        if not bool(getattr(user, "is_active", False)):
            continue
        if admin_continuity_refusal(current_user, user, new_role=user.role, new_active=False):
            continuity_refused.append(user.id)
            continue
        user.is_active = False
        record_account_changes(user, old_role=user.role, old_active=True)
        updated += 1

    db.session.commit()
    _report_bulk_refusals(refused, "bulk_passive")
    _report_continuity_refusals(continuity_refused, "bulk_passive")
    flash(f"Toplu pasif yapma tamamlandı. Güncellenen kayıt: {updated}", "success")
    return redirect(url_for("main.admin_users"))

def admin_user_toggle_active_impl(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        flash("Kullanıcı bulunamadı.", "danger")
        return redirect(url_for("main.admin_users"))
    try:
        ensure_not_self_target(actor_id=current_user.id, target_id=user.id, entity_label="kullanıcı")
        if not may_change_account_state(current_user, user):
            audit_refusal(user, "activation_change")
            flash(REFUSAL_MESSAGE, "danger")
            return redirect(url_for("main.admin_users"))
        old_active = bool(user.is_active)
        new_active = ensure_boolean_toggle(current_value=getattr(user, "is_active", False), entity_label="Kullanıcı", requested_state=request.form.get("target_state"))
        continuity_refusal = admin_continuity_refusal(current_user, user, new_role=user.role, new_active=new_active)
        if continuity_refusal:
            audit_refusal(user, continuity_refusal)
            flash(ADMIN_CONTINUITY_MESSAGE, "danger")
            return redirect(url_for("main.admin_users"))
        user.is_active = new_active
        record_account_changes(user, old_role=user.role, old_active=old_active)
        db.session.commit()
        flash("Kullanıcı durumu güncellendi.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Kullanıcı durumu güncellenirken hata oluştu.", "danger")
    return redirect(url_for("main.admin_users"))

def admin_users_reset_all_impl():
    # R05: deleting every non-admin account and its data is for a real admin only.
    if not is_real_admin(current_user):
        audit_refusal(None, "reset_all")
        flash(REFUSAL_MESSAGE, "danger")
        return redirect(url_for("main.admin_users"))
    try:
        audit_account_change("account.reset_all", None, summary="reset_all_personnel_and_related_data")
        reset_all_personnel_and_related_data()
        db.session.commit()
        flash("Personel, hiyerarşi ve ilişkili performans verileri tamamen sıfırlandı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("Sıfırlama işlemi sırasında hata oluştu.", "danger")

    return redirect(url_for("main.admin_users"))


def _report_continuity_refusals(refused_ids, reason: str) -> None:
    if not refused_ids:
        return
    audit_refusal(None, f"{reason}:last_active_admin:" + ",".join(str(user_id) for user_id in refused_ids[:50]))
    flash(f"{len(refused_ids)} admin hesabı işlem dışında bırakıldı. {ADMIN_CONTINUITY_MESSAGE}", "warning")


def _audit_bulk_refusals(refused_ids, reason: str) -> None:
    if refused_ids:
        audit_refusal(None, f"{reason}:" + ",".join(str(user_id) for user_id in refused_ids[:50]))


def _report_bulk_refusals(refused_ids, reason: str) -> None:
    if not refused_ids:
        return
    _audit_bulk_refusals(refused_ids, reason)
    flash(f"{len(refused_ids)} korumalı hesap işlem dışında bırakıldı. {REFUSAL_MESSAGE}", "warning")
