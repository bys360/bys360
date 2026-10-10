from __future__ import annotations

import logging

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_REQUIRED
# STATUS_SOURCE: app.communication.route_manifest REQUIRED_ROUTE_MODULES
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2, orphan-auth-key
# closure): this file's support-ticket routes used to be gated by the bare
# "support" menu key -- never declared anywhere in MENU_SECTIONS, meaning
# these live, registered routes 403'd for EVERY role
# including admin. Confirmed these routes operate on the exact same
# SupportTicket/SupportTicketMessage/SupportTicketStatusHistory models as
# the already-registered, already-working "support_all" menu key (see
# app/support/routes.py) -- a genuine duplicate capability, not a distinct
# one. Repointed the decorator to reuse that existing canonical key rather
# than inventing a new one, matching this same file's own established
# pattern of reusing "notifications" for its dashboard route.
from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.models import Notification
from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.communication_phase1_service import BULLETIN_PRIORITY_LABELS
from app.services.communication_phase3_service import (
    SUPPORT_STATUS_LABELS,
    CommunicationPhase3Error,
    add_support_message,
    assign_support_ticket,
    create_survey_reminders,
    get_survey_for_user,
    help_article_detail,
    help_center_snapshot,
    is_manager,
    mark_all_notifications_read,
    notification_center_snapshot,
    phase3_dashboard_snapshot,
    save_or_submit_survey,
    support_detail_payload,
    support_queue_snapshot,
    survey_center_for_user,
    update_support_status,
)
from app.services.support_ticket_access import can_view_all_support_tickets

logger = logging.getLogger(__name__)


@main_bp.route("/communication/faz3")
@login_required
@menu_key_required("notifications")
def communication_phase3_dashboard_view():
    payload = phase3_dashboard_snapshot(current_user)
    return safe_render("communication/phase3_dashboard.html", payload=payload)


@main_bp.route("/communication/faz3/notifications")
@login_required
@menu_key_required("notifications")
def communication_phase3_notifications():
    filter_name = (request.args.get("filter") or "all").strip().lower()
    payload = notification_center_snapshot(current_user, filter_name=filter_name)
    return safe_render("communication/phase3_notifications.html", payload=payload)


@main_bp.route("/communication/faz3/notifications/read-all", methods=["POST"])
@login_required
@menu_key_required("notifications")
def communication_phase3_notifications_read_all():
    count = mark_all_notifications_read(current_user.id)
    flash(f"{count} bildirim okundu olarak işaretlendi.", "success")
    return redirect(url_for("main.communication_phase3_notifications"))


@main_bp.route("/communication/faz3/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
@menu_key_required("notifications")
def communication_phase3_notification_read(notification_id: int):
    row = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    row.is_read = True
    row.read_at = row.read_at or row.updated_at
    from app.extensions import db
    db.session.add(row)
    db.session.commit()
    return redirect(request.referrer or url_for("main.communication_phase3_notifications"))


@main_bp.route("/communication/faz3/surveys/my")
@login_required
@menu_key_required("surveys")
def communication_phase3_my_surveys():
    filter_name = (request.args.get("filter") or "all").strip().lower()
    payload = survey_center_for_user(current_user, filter_name=filter_name)
    return safe_render("communication/phase3_my_surveys.html", payload=payload)


@main_bp.route("/communication/faz3/surveys/<int:survey_id>/take", methods=["GET", "POST"])
@login_required
@menu_key_required("surveys")
def communication_phase3_survey_take(survey_id: int):
    if request.method == "POST":
        complete = bool(request.form.get("complete"))
        try:
            save_or_submit_survey(survey_id, current_user, request.form, complete=complete)
            flash("Anket yanıtı kaydedildi." if not complete else "Anket başarıyla tamamlandı.", "success")
            return redirect(url_for("main.communication_phase3_my_surveys"))
        except CommunicationPhase3Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:  # pragma: no cover
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase3_routes.py | line=95 | exc=%s", exc)
            flash("Anket kaydedilemedi.", "danger")

    try:
        payload = get_survey_for_user(survey_id, current_user)
    except CommunicationPhase3Error as exc:
        flash(str(exc), "warning")
        return redirect(url_for("main.communication_phase3_my_surveys"))

    return safe_render("communication/phase3_survey_take.html", payload=payload)


@main_bp.route("/communication/faz3/surveys/<int:survey_id>/remind", methods=["POST"])
@login_required
@menu_key_required("surveys")
def communication_phase3_survey_remind(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase3_my_surveys"))

    try:
        result = create_survey_reminders(survey_id, actor_user_id=current_user.id, note=request.form.get("note") or "")
        if result.get("skipped_recent"):
            flash(f"{result['created']} kullanıcıya hatırlatma gönderildi. {result['skipped_recent']} kullanıcı son 24 saatte zaten hatırlatıldığı için atlandı.", "success")
        else:
            flash(f"{result['created']} kullanıcıya anket hatırlatması gönderildi.", "success")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase3_routes.py | line=121 | exc=%s", exc)
        flash("Hatırlatma oluşturulamadı.", "danger")
    return redirect(request.referrer or url_for("main.communication_phase3_my_surveys"))


@main_bp.route("/communication/faz3/support/queue")
@login_required
@menu_key_required("support_all")
def communication_phase3_support_queue():
    filter_name = (request.args.get("filter") or "all").strip().lower()
    payload = support_queue_snapshot(current_user, filter_name=filter_name)
    return safe_render("communication/phase3_support_queue.html", payload=payload)


@main_bp.route("/communication/faz3/support/<int:ticket_id>", methods=["GET", "POST"])
@login_required
@menu_key_required("support_all")
def communication_phase3_support_detail(ticket_id: int):
    if request.method == "POST":
        try:
            add_support_message(
                ticket_id=ticket_id,
                actor_user=current_user,
                message=request.form.get("message") or "",
                is_internal=bool(request.form.get("is_internal")) and can_view_all_support_tickets(current_user),
            )
            flash("Talep mesajı kaydedildi.", "success")
            return redirect(url_for("main.communication_phase3_support_detail", ticket_id=ticket_id))
        except CommunicationPhase3Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:  # pragma: no cover
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase3_routes.py | line=151 | exc=%s", exc)
            flash("Talep mesajı kaydedilemedi.", "danger")

    try:
        payload = support_detail_payload(ticket_id, current_user)
    except CommunicationPhase3Error as exc:
        flash(str(exc), "warning")
        return redirect(url_for("main.communication_phase3_support_queue"))

    return safe_render(
        "communication/phase3_support_detail.html",
        payload=payload,
        status_labels=SUPPORT_STATUS_LABELS,
        priority_labels=BULLETIN_PRIORITY_LABELS,
    )


@main_bp.route("/communication/faz3/support/<int:ticket_id>/assign", methods=["POST"])
@login_required
@menu_key_required("support_all")
def communication_phase3_support_assign(ticket_id: int):
    # K5-Q3: the central support_all grant, not a manager role.
    if not can_view_all_support_tickets(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase3_support_detail", ticket_id=ticket_id))

    assignee_raw = (request.form.get("assigned_to_user_id") or "").strip()
    assignee_user_id = int(assignee_raw) if assignee_raw.isdigit() else None
    try:
        assign_support_ticket(
            ticket_id=ticket_id,
            assignee_user_id=assignee_user_id,
            actor_user_id=current_user.id,
            note=request.form.get("note") or "",
            actor_user=current_user,
        )
        flash("Talep ataması güncellendi.", "success")
    except CommunicationPhase3Error as exc:
        flash(str(exc), "warning")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase3_routes.py | line=183 | exc=%s", exc)
        flash("Atama yapılamadı.", "danger")
    return redirect(url_for("main.communication_phase3_support_detail", ticket_id=ticket_id))


@main_bp.route("/communication/faz3/support/<int:ticket_id>/status", methods=["POST"])
@login_required
@menu_key_required("support_all")
def communication_phase3_support_status(ticket_id: int):
    # K5-Q3: the central support_all grant, not a manager role.
    if not can_view_all_support_tickets(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase3_support_detail", ticket_id=ticket_id))

    try:
        update_support_status(
            ticket_id=ticket_id,
            new_status=request.form.get("status") or "open",
            actor_user_id=current_user.id,
            note=request.form.get("note") or "",
            actor_user=current_user,
        )
        flash("Talep durumu güncellendi.", "success")
    except CommunicationPhase3Error as exc:
        flash(str(exc), "warning")
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase3_routes.py | line=206 | exc=%s", exc)
        flash("Durum güncellenemedi.", "danger")
    return redirect(url_for("main.communication_phase3_support_detail", ticket_id=ticket_id))


@main_bp.route("/communication/faz3/help")
@login_required
@menu_key_required("support_all")
def communication_phase3_help_center():
    payload = help_center_snapshot(
        current_user,
        query_text=request.args.get("q") or "",
        category_slug=request.args.get("category") or "",
    )
    return safe_render("communication/phase3_help_center.html", payload=payload)


@main_bp.route("/communication/faz3/help/<slug>")
@login_required
@menu_key_required("support_all")
def communication_phase3_help_article(slug: str):
    try:
        payload = help_article_detail(slug, current_user, search_term=request.args.get("q") or "")
    except CommunicationPhase3Error as exc:
        flash(str(exc), "warning")
        return redirect(url_for("main.communication_phase3_help_center"))
    return safe_render("communication/phase3_help_article.html", payload=payload)
