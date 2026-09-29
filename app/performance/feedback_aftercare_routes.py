from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app.route_registry import main_bp

# BYS360_STUB_AI_V60_AFTERCARE_IMPORT
from app.services.ai.stub_panel_bridge import attach_aftercare_ai_panel

# /BYS360_STUB_AI_V60_AFTERCARE_IMPORT
from app.services.performance.feedback_aftercare import (
    action_plan_meeting_id,
    add_action_plan,
    build_full_context,
    get_meeting_aftercare_detail,
    save_after_note,
    save_preparation,
    update_action_plan,
)

logger = logging.getLogger(__name__)


# BYS360_FEEDBACK_AFTERCARE_PHASE7_USABILITY_IMPORTS
build_phase7_context: Callable[..., dict[str, Any]] | None
create_meeting_from_feedback_request: Callable[..., int] | None
try:
    from app.services.performance.feedback_aftercare_phase7 import (
        build_phase7_context,
        create_meeting_from_feedback_request,
    )
except Exception as exc:
    logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_aftercare_routes.py | line=29 | exc=%s", exc)
    build_phase7_context = None
    create_meeting_from_feedback_request = None
# /BYS360_FEEDBACK_AFTERCARE_PHASE7_USABILITY_IMPORTS


# BYS360_FEEDBACK_AFTERCARE_PHASE7_1_PERSON_PERIOD_IMPORTS
build_phase7_1_context: Callable[..., dict[str, Any]] | None
create_person_period_meeting: Callable[..., int] | None
try:
    from app.services.performance.feedback_aftercare_phase7_person_period import (
        build_phase7_1_context,
        create_person_period_meeting,
    )
except Exception as exc:
    logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_aftercare_routes.py | line=41 | exc=%s", exc)
    build_phase7_1_context = None
    create_person_period_meeting = None
# /BYS360_FEEDBACK_AFTERCARE_PHASE7_1_PERSON_PERIOD_IMPORTS


def _user_role() -> str:
    return (getattr(current_user, "role", "") or "").strip().lower()


def _is_admin() -> bool:
    return bool(getattr(current_user, "is_admin", False) or _user_role() in {"admin", "super_admin", "system_admin", "sistem_yoneticisi"})


def _is_superuser() -> bool:
    return bool(getattr(current_user, "is_superuser", False))


def _context(selected_meeting_id: int | None = None):
    ctx = build_full_context(
        current_user_id=getattr(current_user, "id", None),
        current_user_role=_user_role(),
        is_admin=_is_admin(),
        is_superuser=_is_superuser(),
        selected_meeting_id=selected_meeting_id,
        query=(request.args.get("q") or "").strip(),
        status=(request.args.get("status") or "all").strip(),
    )
    # BYS360_FEEDBACK_AFTERCARE_PHASE7_USABILITY_CONTEXT
    if build_phase7_context:
        try:
            ctx.update(build_phase7_context(
                current_user_id=getattr(current_user, "id", None),
                current_user_role=_user_role(),
                is_admin=_is_admin(),
                is_superuser=_is_superuser(),
            ))
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_aftercare_routes.py | line=78 | exc=%s", exc)
            ctx.update({
                "phase7_usage_steps": [],
                "phase7_detail_map": [],
                "feedback_request_options": [],
                "meeting_type_options": [],
                "can_create_aftercare_meeting": False,
                "phase7_schema_ready": False,
            })
    # /BYS360_FEEDBACK_AFTERCARE_PHASE7_USABILITY_CONTEXT

    # BYS360_FEEDBACK_AFTERCARE_PHASE7_1_PERSON_PERIOD_CONTEXT
    if build_phase7_1_context:
        try:
            ctx.update(build_phase7_1_context(
                current_user_id=getattr(current_user, "id", None),
                current_user_role=_user_role(),
                is_admin=_is_admin(),
                is_superuser=_is_superuser(),
            ))
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_aftercare_routes.py | line=98 | exc=%s", exc)
            ctx.update({
                "person_options": [],
                "period_options": [],
                "can_create_person_period_meeting": False,
                "meeting_period_map": {},
                "active_create_tab": "person_period",
                "phase7_1_person_period_ready": False,
            })
    # /BYS360_FEEDBACK_AFTERCARE_PHASE7_1_PERSON_PERIOD_CONTEXT

    # BYS360_FEEDBACK_AFTERCARE_PHASE7_2_VISIBLE_NEW_RECORD_CONTEXT
    if build_phase7_1_context:
        try:
            ctx.update(build_phase7_1_context(
                current_user_id=getattr(current_user, "id", None),
                current_user_role=_user_role(),
                is_admin=_is_admin(),
                is_superuser=_is_superuser(),
            ))
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_aftercare_routes.py | line=118 | exc=%s", exc)
            ctx.update({
                "person_options": [],
                "period_options": [],
                "can_create_person_period_meeting": False,
                "meeting_period_map": {},
                "meeting_type_options": [],
                "active_create_tab": "person_period",
                "phase7_1_person_period_ready": False,
            })
    # /BYS360_FEEDBACK_AFTERCARE_PHASE7_2_VISIBLE_NEW_RECORD_CONTEXT

    # BYS360_STUB_AI_V60_AFTERCARE_CONTEXT_ATTACH
    ctx = attach_aftercare_ai_panel(ctx)
    # /BYS360_STUB_AI_V60_AFTERCARE_CONTEXT_ATTACH
    return ctx

def _can_edit_meeting(meeting_id: int) -> bool:
    detail = get_meeting_aftercare_detail(
        meeting_id,
        current_user_id=getattr(current_user, "id", None),
        current_user_role=_user_role(),
        is_admin=_is_admin(),
        is_superuser=_is_superuser(),
    )
    return bool(detail.get("meeting") and detail.get("can_edit"))


@main_bp.route("/performance/feedback-aftercare", endpoint="performance_feedback_aftercare")
@main_bp.route("/performans/gorusme-sonrasi-notlar", endpoint="performance_feedback_aftercare_tr")
@login_required
def performance_feedback_aftercare():
    # Compatibility guard.
    try:
        return render_template("performance/feedback_aftercare.html", **_context())
    except SQLAlchemyError:
        return (
            "<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
            "<title>Geli?im ?zleme</title></head><body><main>"
            "<h1>Geli?im ?zleme</h1>"
            "<p>Veritaban? ba?lant?s? ge?ici olarak haz?rlan?yor. L?tfen daha sonra tekrar deneyiniz.</p>"
            "</main></body></html>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

# BYS360_FEEDBACK_AFTERCARE_PHASE7_USABILITY_CREATE_ROUTE
@main_bp.route("/performance/feedback-aftercare/create", methods=["POST"], endpoint="performance_feedback_aftercare_create")
@main_bp.route("/performans/gorusme-sonrasi-notlar/yeni", methods=["POST"], endpoint="performance_feedback_aftercare_create_tr")
@login_required
def performance_feedback_aftercare_create():
    if not create_meeting_from_feedback_request:
        flash("Yeni görüşme kaydı oluşturma servisi hazır değil.", "warning")
        return redirect(url_for("main.performance_feedback_aftercare"))
    try:
        meeting_id = create_meeting_from_feedback_request(
            current_user_id=getattr(current_user, "id", None),
            current_user_role=_user_role(),
            is_admin=_is_admin(),
            is_superuser=_is_superuser(),
            form=request.form,
        )
        flash("Görüşme kaydı oluşturuldu. Notlar bu görüşme detayının içine yazılabilir.", "success")
        return redirect(url_for("main.performance_feedback_aftercare_detail", meeting_id=meeting_id))
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_aftercare_routes.py | line=171 | exc=%s", exc)
        flash("Görüşme kaydı oluşturulamadı.", "warning")
        return redirect(url_for("main.performance_feedback_aftercare"))
# /BYS360_FEEDBACK_AFTERCARE_PHASE7_USABILITY_CREATE_ROUTE

# BYS360_FEEDBACK_AFTERCARE_PHASE7_1_PERSON_PERIOD_CREATE_ROUTE
@main_bp.route("/performance/feedback-aftercare/create-person-period", methods=["POST"], endpoint="performance_feedback_aftercare_create_person_period")
@main_bp.route("/performans/gorusme-sonrasi-notlar/personel-donem-yeni", methods=["POST"], endpoint="performance_feedback_aftercare_create_person_period_tr")
@login_required
def performance_feedback_aftercare_create_person_period():
    if not create_person_period_meeting:
        flash("Personel ve dönem görüşmesi oluşturma servisi hazır değil.", "warning")
        return redirect(url_for("main.performance_feedback_aftercare"))
    try:
        meeting_id = create_person_period_meeting(
            current_user_id=getattr(current_user, "id", None),
            current_user_role=_user_role(),
            is_admin=_is_admin(),
            is_superuser=_is_superuser(),
            form=request.form,
        )
        flash("Personel ve dönem görüşmesi oluşturuldu. Görüşme notları bu kaydın içine yazılabilir.", "success")
        return redirect(url_for("main.performance_feedback_aftercare_detail", meeting_id=meeting_id))
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_aftercare_routes.py | line=194 | exc=%s", exc)
        flash("Personel ve dönem görüşmesi oluşturulamadı.", "warning")
        return redirect(url_for("main.performance_feedback_aftercare"))
# /BYS360_FEEDBACK_AFTERCARE_PHASE7_1_PERSON_PERIOD_CREATE_ROUTE

# BYS360_FEEDBACK_AFTERCARE_PHASE7_2_VISIBLE_NEW_RECORD_NEW_PAGE_ROUTE
@main_bp.route("/performance/feedback-aftercare/new", endpoint="performance_feedback_aftercare_new")
@main_bp.route("/performans/gorusme-sonrasi-notlar/yeni", endpoint="performance_feedback_aftercare_new_tr")
@login_required
def performance_feedback_aftercare_new():
    ctx = _context()
    ctx["new_record_mode"] = True
    return render_template("performance/feedback_aftercare_new.html", **ctx)
# /BYS360_FEEDBACK_AFTERCARE_PHASE7_2_VISIBLE_NEW_RECORD_NEW_PAGE_ROUTE


@main_bp.route("/performance/feedback-aftercare/<int:meeting_id>", endpoint="performance_feedback_aftercare_detail")
@main_bp.route("/performans/gorusme-sonrasi-notlar/<int:meeting_id>", endpoint="performance_feedback_aftercare_detail_tr")
@login_required
def performance_feedback_aftercare_detail(meeting_id: int):
    ctx = _context(meeting_id)
    if not ctx.get("selected_meeting"):
        flash("Görüşme kaydı bulunamadı veya bu kayda erişim yetkiniz yok.", "warning")
        return redirect(url_for("main.performance_feedback_aftercare"))
    return render_template("performance/feedback_aftercare.html", **ctx)


@main_bp.route("/performance/feedback-aftercare/<int:meeting_id>/preparation", methods=["POST"], endpoint="performance_feedback_aftercare_save_preparation")
@login_required
def performance_feedback_aftercare_save_preparation(meeting_id: int):
    if not _can_edit_meeting(meeting_id):
        flash("Bu görüşme hazırlığını güncelleme yetkiniz yok.", "danger")
        return redirect(url_for("main.performance_feedback_aftercare"))
    save_preparation(meeting_id, getattr(current_user, "id", None), request.form)
    flash("Görüşme hazırlığı kaydedildi.", "success")
    return redirect(url_for("main.performance_feedback_aftercare_detail", meeting_id=meeting_id))


@main_bp.route("/performance/feedback-aftercare/<int:meeting_id>/after-note", methods=["POST"], endpoint="performance_feedback_aftercare_save_after_note")
@login_required
def performance_feedback_aftercare_save_after_note(meeting_id: int):
    if not _can_edit_meeting(meeting_id):
        flash("Görüşme sonrası notunu güncelleme yetkiniz yok.", "danger")
        return redirect(url_for("main.performance_feedback_aftercare"))
    save_after_note(meeting_id, getattr(current_user, "id", None), request.form)
    flash("Görüşme sonrası notlar kaydedildi.", "success")
    return redirect(url_for("main.performance_feedback_aftercare_detail", meeting_id=meeting_id))


@main_bp.route("/performance/feedback-aftercare/<int:meeting_id>/actions", methods=["POST"], endpoint="performance_feedback_aftercare_add_action")
@login_required
def performance_feedback_aftercare_add_action(meeting_id: int):
    detail = get_meeting_aftercare_detail(
        meeting_id,
        current_user_id=getattr(current_user, "id", None),
        current_user_role=_user_role(),
        is_admin=_is_admin(),
        is_superuser=_is_superuser(),
    )
    meeting = detail.get("meeting") or {}
    if not meeting or not detail.get("can_edit"):
        flash("Bu görüşme için eylem planı ekleme yetkiniz yok.", "danger")
        return redirect(url_for("main.performance_feedback_aftercare"))
    try:
        add_action_plan(meeting_id, meeting.get("employee_id"), getattr(current_user, "id", None), request.form)
        flash("Eylem planı eklendi.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("main.performance_feedback_aftercare_detail", meeting_id=meeting_id))


@main_bp.route("/performance/feedback-aftercare/actions/<int:action_id>/update", methods=["POST"], endpoint="performance_feedback_aftercare_update_action")
@login_required
def performance_feedback_aftercare_update_action(action_id: int):
    # Authorize before writing: the same _can_edit_meeting rule as the after-note and add-action routes.
    meeting_id = action_plan_meeting_id(action_id)
    if not meeting_id:
        flash("Eylem planı bulunamadı.", "warning")
        return redirect(url_for("main.performance_feedback_aftercare"))
    if not _can_edit_meeting(meeting_id):
        flash("Bu eylem planını güncelleme yetkiniz yok.", "danger")
        return redirect(url_for("main.performance_feedback_aftercare"))
    update_action_plan(action_id, request.form)
    flash("Eylem planı takip bilgisi güncellendi.", "success")
    return redirect(url_for("main.performance_feedback_aftercare_detail", meeting_id=meeting_id))
