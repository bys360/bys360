from __future__ import annotations

import logging

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_REQUIRED
# STATUS_SOURCE: app.communication.route_manifest REQUIRED_ROUTE_MODULES
from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.communication_phase1_models import (
    CommunicationBulletin,
    CommunicationBulletinAudience,
    CommunicationBulletinReceipt,
)
from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.communication_phase1_service import (
    BULLETIN_PRIORITY_LABELS,
    BULLETIN_STATUS_LABELS,
    CommunicationPhase1Error,
    bulletin_dashboard_snapshot,
    communication_phase1_dashboard,
    create_bulletin,
    is_manager,
    manager_filter_options,
    publish_bulletin,
    support_center_snapshot,
    survey_center_snapshot,
)
from app.services.communication_service import (
    CommunicationServiceError,
    acknowledge_bulletin_receipt,
    bulletin_receipt_summary,
    get_bulletin_receipt,
    mark_bulletin_read,
)

logger = logging.getLogger(__name__)


@main_bp.route("/communication/faz1")
@login_required
@menu_key_required("notifications")
def communication_phase1_dashboard_view():
    dashboard = communication_phase1_dashboard(current_user)
    return safe_render("communication/phase1_dashboard.html", dashboard=dashboard)


@main_bp.route("/communication/faz1/bulletins")
@login_required
@menu_key_required("announcements")
def communication_phase1_bulletins():
    payload = bulletin_dashboard_snapshot(limit=50)
    return safe_render(
        "communication/phase1_bulletins.html",
        rows=payload["rows"],
        counts=payload["counts"],
        priority_labels=BULLETIN_PRIORITY_LABELS,
        status_labels=BULLETIN_STATUS_LABELS,
        can_manage=is_manager(current_user),
    )


@main_bp.route("/communication/faz1/bulletins/new", methods=["GET", "POST"])
@login_required
@menu_key_required("announcements")
def communication_phase1_bulletin_new():
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase1_bulletins"))

    options = manager_filter_options()

    if request.method == "POST":
        try:
            bulletin = create_bulletin(
                title=request.form.get("title") or "",
                summary=request.form.get("summary") or "",
                content=request.form.get("content") or "",
                bulletin_type=request.form.get("bulletin_type") or "",
                priority=request.form.get("priority") or "",
                target_type=request.form.get("target_type") or "",
                target_values_text=request.form.get("target_values") or "",
                creator_user_id=current_user.id,
                is_pinned=bool(request.form.get("is_pinned")),
                require_ack=bool(request.form.get("require_ack")),
                publish_now=bool(request.form.get("publish_now")),
            )
            flash("Faz 1 duyuru kaydı oluşturuldu.", "success")
            return redirect(url_for("main.communication_phase1_bulletin_detail", bulletin_id=bulletin.id))
        except CommunicationPhase1Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:  # pragma: no cover
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase1_routes.py | line=90 | exc=%s", exc)
            flash("Duyuru oluşturulamadı.", "danger")

    return safe_render(
        "communication/phase1_bulletin_form.html",
        options=options,
        priority_labels=BULLETIN_PRIORITY_LABELS,
    )


@main_bp.route("/communication/faz1/bulletins/<int:bulletin_id>")
@login_required
@menu_key_required("announcements")
def communication_phase1_bulletin_detail(bulletin_id: int):
    bulletin = CommunicationBulletin.query.get_or_404(bulletin_id)
    audiences = bulletin.audiences.order_by(CommunicationBulletinAudience.id).all()

    my_receipt = None
    try:
        my_receipt = mark_bulletin_read(bulletin.id, current_user.id)
        if my_receipt is not None:
            db.session.add(my_receipt)
            db.session.commit()
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase1_routes.py | line=113 | exc=%s", exc)
        db.session.rollback()
        my_receipt = get_bulletin_receipt(bulletin.id, current_user.id, create_if_missing=False)

    receipts = bulletin.receipts.order_by(CommunicationBulletinReceipt.created_at.desc()).all()
    receipt_summary = bulletin_receipt_summary(bulletin)
    return safe_render(
        "communication/phase1_bulletin_detail.html",
        bulletin=bulletin,
        audiences=audiences,
        receipts=receipts,
        my_receipt=my_receipt,
        receipt_summary=receipt_summary,
        can_manage=is_manager(current_user),
        priority_labels=BULLETIN_PRIORITY_LABELS,
        status_labels=BULLETIN_STATUS_LABELS,
    )


@main_bp.route("/communication/faz1/bulletins/<int:bulletin_id>/publish", methods=["POST"])
@login_required
@menu_key_required("announcements")
def communication_phase1_bulletin_publish(bulletin_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase1_bulletins"))

    try:
        result = publish_bulletin(bulletin_id, actor_user_id=current_user.id)
        flash(
            f"Duyuru yayımlandı. Bildirim giden kullanıcı: {result['target_count']} | yeni teslim kaydı: {result['delivered_count']}",
            "success",
        )
    except CommunicationPhase1Error as exc:
        flash(str(exc), "warning")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase1_routes.py | line=148 | exc=%s", exc)
        flash("Duyuru yayımlanamadı.", "danger")

    return redirect(url_for("main.communication_phase1_bulletin_detail", bulletin_id=bulletin_id))


@main_bp.route("/communication/faz1/surveys")
@login_required
@menu_key_required("surveys")
def communication_phase1_survey_center():
    payload = survey_center_snapshot()
    return safe_render("communication/phase1_survey_center.html", payload=payload)


@main_bp.route("/communication/faz1/support")
@login_required
@menu_key_required("support_index")
def communication_phase1_support_center():
    payload = support_center_snapshot(current_user)  # K5: viewer-scoped rows
    return safe_render("communication/phase1_support_center.html", payload=payload)


@main_bp.route("/communication/faz1/bulletins/<int:bulletin_id>/acknowledge", methods=["POST"])
@login_required
@menu_key_required("announcements")
def communication_phase1_bulletin_acknowledge(bulletin_id: int):
    bulletin = CommunicationBulletin.query.get_or_404(bulletin_id)
    try:
        receipt = acknowledge_bulletin_receipt(bulletin.id, current_user.id)
        db.session.add(receipt)
        db.session.commit()
        flash("Duyuru alındı bilgisi kaydedildi.", "success")
    except CommunicationPhase1Error as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except CommunicationServiceError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase1_routes.py | line=186 | exc=%s", exc)
        db.session.rollback()
        flash("Duyuru onayı kaydedilemedi.", "danger")
    return redirect(url_for("main.communication_phase1_bulletin_detail", bulletin_id=bulletin_id))
