from __future__ import annotations

import logging

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_REQUIRED
# STATUS_SOURCE: app.communication.route_manifest REQUIRED_ROUTE_MODULES
from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.models.communication_phase1_models import CommunicationBulletin
from app.models.communication_phase2_models import CommunicationSurveyTemplate
from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.communication_phase2_service import (
    BULLETIN_PRIORITY_LABELS,
    BULLETIN_STATUS_LABELS,
    SURVEY_QUESTION_TYPE_LABELS,
    SURVEY_STATUS_LABELS,
    CommunicationPhase2Error,
    archive_bulletin,
    archive_survey,
    bulletin_history_payload,
    close_survey,
    create_survey_from_template_or_builder,
    duplicate_survey,
    is_manager,
    manager_filter_options,
    phase2_dashboard_snapshot,
    publish_survey,
    reopen_survey,
    safe_str,
    survey_builder_payload,
    survey_detail_payload,
    survey_manager_snapshot,
    survey_results_snapshot,
    update_bulletin,
    update_survey_from_builder,
    upsert_survey_template,
)

logger = logging.getLogger(__name__)


def _parse_questions_from_request() -> list[dict]:
    question_texts = request.form.getlist("question_text")
    question_types = request.form.getlist("question_type")
    required_flags = request.form.getlist("question_required")
    options_blocks = request.form.getlist("question_options")

    questions = []
    for index, question_text in enumerate(question_texts):
        text = safe_str(question_text)
        if not text:
            continue
        question_type = safe_str(question_types[index] if index < len(question_types) else "single_choice") or "single_choice"
        required_raw = safe_str(required_flags[index] if index < len(required_flags) else "1")
        options_text = safe_str(options_blocks[index] if index < len(options_blocks) else "")
        options = [row.strip() for row in options_text.splitlines() if row and row.strip()]
        questions.append(
            {
                "question_text": text,
                "question_type": question_type,
                "is_required": required_raw not in {"0", "false", "hayir", "off"},
                "options": options,
                "options_text": "\n".join(options),
            }
        )
    return questions


def _survey_form_state_from_request() -> dict:
    questions = _parse_questions_from_request()
    return {
        "title": request.form.get("title", ""),
        "description": request.form.get("description", ""),
        "survey_type": request.form.get("survey_type", "kurum_ici"),
        "target_type": request.form.get("target_type", "all"),
        "target_values": request.form.get("target_values", ""),
        "is_anonymous": bool(request.form.get("is_anonymous")),
        "allow_multiple_submissions": bool(request.form.get("allow_multiple_submissions")),
        "publish_now": bool(request.form.get("publish_now")),
        "start_at": request.form.get("start_at", ""),
        "end_at": request.form.get("end_at", ""),
        "questions": questions or [{"question_text": "", "question_type": "single_choice", "is_required": True, "options_text": ""} for _ in range(4)],
    }


def _default_survey_form_state() -> dict:
    return {
        "title": "",
        "description": "",
        "survey_type": "kurum_ici",
        "target_type": "all",
        "target_values": "",
        "is_anonymous": False,
        "allow_multiple_submissions": False,
        "publish_now": False,
        "start_at": "",
        "end_at": "",
        "questions": [{"question_text": "", "question_type": "single_choice", "is_required": True, "options_text": ""} for _ in range(4)],
    }


@main_bp.route("/communication/faz2")
@login_required
@menu_key_required("notifications")
def communication_phase2_dashboard_view():
    payload = phase2_dashboard_snapshot()
    return safe_render("communication/phase2_dashboard.html", payload=payload)


@main_bp.route("/communication/faz2/bulletins/<int:bulletin_id>/edit", methods=["GET", "POST"])
@login_required
@menu_key_required("announcements")
def communication_phase2_bulletin_edit(bulletin_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase1_bulletins"))

    bulletin = CommunicationBulletin.query.get_or_404(bulletin_id)
    options = manager_filter_options()
    audiences = bulletin.audiences.order_by("id").all()
    default_target_type = audiences[0].target_type if audiences else "all"
    default_target_values = ", ".join([safe_str(row.target_value) for row in audiences if safe_str(row.target_value)])

    if request.method == "POST":
        try:
            update_bulletin(
                bulletin_id=bulletin.id,
                actor_user_id=current_user.id,
                title=request.form.get("title"),
                summary=request.form.get("summary"),
                content=request.form.get("content"),
                bulletin_type=request.form.get("bulletin_type"),
                priority=request.form.get("priority"),
                target_type=request.form.get("target_type"),
                target_values_text=request.form.get("target_values"),
                is_pinned=bool(request.form.get("is_pinned")),
                require_ack=bool(request.form.get("require_ack")),
                change_note=request.form.get("change_note"),
            )
            flash("Duyuru kaydı güncellendi.", "success")
            return redirect(url_for("main.communication_phase1_bulletin_detail", bulletin_id=bulletin.id))
        except CommunicationPhase2Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:  # pragma: no cover
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=146 | exc=%s", exc)
            flash("Duyuru güncellenemedi.", "danger")

    return safe_render(
        "communication/phase2_bulletin_edit.html",
        bulletin=bulletin,
        options=options,
        default_target_type=default_target_type,
        default_target_values=default_target_values,
        priority_labels=BULLETIN_PRIORITY_LABELS,
        status_labels=BULLETIN_STATUS_LABELS,
    )


@main_bp.route("/communication/faz2/bulletins/<int:bulletin_id>/history")
@login_required
@menu_key_required("announcements")
def communication_phase2_bulletin_history(bulletin_id: int):
    payload = bulletin_history_payload(bulletin_id)
    return safe_render(
        "communication/phase2_bulletin_history.html",
        payload=payload,
        priority_labels=BULLETIN_PRIORITY_LABELS,
        status_labels=BULLETIN_STATUS_LABELS,
    )


@main_bp.route("/communication/faz2/bulletins/<int:bulletin_id>/archive", methods=["POST"])
@login_required
@menu_key_required("announcements")
def communication_phase2_bulletin_archive(bulletin_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase1_bulletins"))
    try:
        archive_bulletin(bulletin_id, current_user.id, request.form.get("note"))
        flash("Duyuru arşive alındı.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=183 | exc=%s", exc)
        flash("Duyuru arşive alınamadı.", "danger")
    return redirect(url_for("main.communication_phase2_bulletin_history", bulletin_id=bulletin_id))


@main_bp.route("/communication/faz2/surveys")
@login_required
@menu_key_required("surveys")
def communication_phase2_surveys():
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.surveys_list"))
    payload = survey_manager_snapshot(limit=100)
    return safe_render(
        "communication/phase2_survey_manager.html",
        payload=payload,
        status_labels=SURVEY_STATUS_LABELS,
    )


@main_bp.route("/communication/faz2/surveys/new", methods=["GET", "POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_new():
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_surveys"))

    templates = CommunicationSurveyTemplate.query.filter_by(is_active=True).order_by(CommunicationSurveyTemplate.title.asc()).all()
    options = manager_filter_options()
    form_state = _survey_form_state_from_request() if request.method == "POST" else _default_survey_form_state()

    if request.method == "POST":
        try:
            template_id_raw = safe_str(request.form.get("template_id"))
            template_id = int(template_id_raw) if template_id_raw.isdigit() else None
            survey = create_survey_from_template_or_builder(
                actor_user_id=current_user.id,
                title=request.form.get("title"),
                description=request.form.get("description"),
                survey_type=request.form.get("survey_type"),
                is_anonymous=bool(request.form.get("is_anonymous")),
                allow_multiple_submissions=bool(request.form.get("allow_multiple_submissions")),
                target_type=request.form.get("target_type"),
                target_values_text=request.form.get("target_values"),
                publish_now=bool(request.form.get("publish_now")),
                start_at_raw=request.form.get("start_at"),
                end_at_raw=request.form.get("end_at"),
                template_id=template_id,
                questions_payload=None if template_id else _parse_questions_from_request(),
            )
            flash("Anket kaydı oluşturuldu.", "success")
            return redirect(url_for("main.communication_phase2_survey_detail", survey_id=survey.id))
        except CommunicationPhase2Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:  # pragma: no cover
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=235 | exc=%s", exc)
            flash("Anket oluşturulamadı.", "danger")

    return safe_render(
        "communication/phase2_survey_builder.html",
        templates=templates,
        options=options,
        question_type_labels=SURVEY_QUESTION_TYPE_LABELS,
        form_state=form_state,
        mode="create",
        action_url=url_for("main.communication_phase2_survey_new"),
        page_title="Anket Tasarım Stüdyosu",
        page_subtitle="Şablondan hızlı başla veya sıfırdan soru girerek kurum içi anketleri merkezi olarak oluştur.",
    )


@main_bp.route("/communication/faz2/surveys/<int:survey_id>/edit", methods=["GET", "POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_edit(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_surveys"))

    templates = CommunicationSurveyTemplate.query.filter_by(is_active=True).order_by(CommunicationSurveyTemplate.title.asc()).all()
    options = manager_filter_options()
    builder_payload = survey_builder_payload(survey_id)
    survey = builder_payload["survey"]
    form_state = _survey_form_state_from_request() if request.method == "POST" else builder_payload["form_state"]

    if request.method == "POST":
        try:
            survey = update_survey_from_builder(
                survey_id=survey.id,
                actor_user_id=current_user.id,
                title=request.form.get("title"),
                description=request.form.get("description"),
                survey_type=request.form.get("survey_type"),
                is_anonymous=bool(request.form.get("is_anonymous")),
                allow_multiple_submissions=bool(request.form.get("allow_multiple_submissions")),
                target_type=request.form.get("target_type"),
                target_values_text=request.form.get("target_values"),
                publish_now=bool(request.form.get("publish_now")),
                start_at_raw=request.form.get("start_at"),
                end_at_raw=request.form.get("end_at"),
                questions_payload=_parse_questions_from_request(),
            )
            flash("Anket taslağı güncellendi.", "success")
            return redirect(url_for("main.communication_phase2_survey_detail", survey_id=survey.id))
        except CommunicationPhase2Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:  # pragma: no cover
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=286 | exc=%s", exc)
            flash("Anket güncellenemedi.", "danger")

    return safe_render(
        "communication/phase2_survey_builder.html",
        templates=templates,
        options=options,
        question_type_labels=SURVEY_QUESTION_TYPE_LABELS,
        form_state=form_state,
        mode="edit",
        survey=survey,
        action_url=url_for("main.communication_phase2_survey_edit", survey_id=survey.id),
        page_title="Anketi Düzenle",
        page_subtitle="Yanıt almamış anketlerin soru yapısını, hedeflemesini ve zamanlamasını güncelleyin.",
    )


@main_bp.route("/communication/faz2/surveys/<int:survey_id>/duplicate", methods=["POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_duplicate(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_surveys"))
    try:
        survey = duplicate_survey(survey_id, current_user.id)
        flash("Anket kopyası taslak olarak oluşturuldu.", "success")
        return redirect(url_for("main.communication_phase2_survey_edit", survey_id=survey.id))
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=314 | exc=%s", exc)
        flash("Anket kopyalanamadı.", "danger")
        return redirect(url_for("main.communication_phase2_survey_detail", survey_id=survey_id))


@main_bp.route("/communication/faz2/surveys/<int:survey_id>/archive", methods=["POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_archive(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_surveys"))
    try:
        archive_survey(survey_id)
        flash("Anket arşive alındı.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=329 | exc=%s", exc)
        flash("Anket arşive alınamadı.", "danger")
    return redirect(url_for("main.communication_phase2_survey_detail", survey_id=survey_id))


@main_bp.route("/communication/faz2/surveys/<int:survey_id>/reopen", methods=["POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_reopen(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_surveys"))
    try:
        reopen_survey(survey_id)
        flash("Anket taslak durumuna geri alındı.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=344 | exc=%s", exc)
        flash("Anket geri alınamadı.", "danger")
    return redirect(url_for("main.communication_phase2_survey_detail", survey_id=survey_id))


@main_bp.route("/communication/faz2/surveys/<int:survey_id>")
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_detail(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.surveys_list"))
    payload = survey_detail_payload(survey_id)
    return safe_render(
        "communication/phase2_survey_detail.html",
        payload=payload,
        status_labels=SURVEY_STATUS_LABELS,
        question_type_labels=SURVEY_QUESTION_TYPE_LABELS,
    )


@main_bp.route("/communication/faz2/surveys/<int:survey_id>/publish", methods=["POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_publish(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_surveys"))
    try:
        publish_survey(survey_id, current_user.id)
        flash("Anket yayımlandı.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=372 | exc=%s", exc)
        flash("Anket yayımlanamadı.", "danger")
    return redirect(url_for("main.communication_phase2_survey_detail", survey_id=survey_id))


@main_bp.route("/communication/faz2/surveys/<int:survey_id>/close", methods=["POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_close(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_surveys"))
    try:
        close_survey(survey_id)
        flash("Anket kapatıldı.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=387 | exc=%s", exc)
        flash("Anket kapatılamadı.", "danger")
    return redirect(url_for("main.communication_phase2_survey_detail", survey_id=survey_id))


@main_bp.route("/communication/faz2/surveys/<int:survey_id>/results")
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_results(survey_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.surveys_list"))
    payload = survey_results_snapshot(survey_id)
    return safe_render(
        "communication/phase2_survey_results.html",
        payload=payload,
        question_type_labels=SURVEY_QUESTION_TYPE_LABELS,
        status_labels=SURVEY_STATUS_LABELS,
    )


@main_bp.route("/communication/faz2/templates")
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_templates():
    rows = CommunicationSurveyTemplate.query.order_by(CommunicationSurveyTemplate.updated_at.desc()).all()
    return safe_render("communication/phase2_survey_templates.html", rows=rows)


@main_bp.route("/communication/faz2/templates/new", methods=["GET", "POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_template_new():
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_survey_templates"))

    if request.method == "POST":
        try:
            template = upsert_survey_template(
                template_id=None,
                actor_user_id=current_user.id,
                title=request.form.get("title"),
                description=request.form.get("description"),
                survey_type=request.form.get("survey_type"),
                is_active=bool(request.form.get("is_active")),
                questions_payload=_parse_questions_from_request(),
            )
            flash("Anket şablonu oluşturuldu.", "success")
            return redirect(url_for("main.communication_phase2_survey_template_edit", template_id=template.id))
        except CommunicationPhase2Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=436 | exc=%s", exc)
            flash("Anket şablonu oluşturulamadı.", "danger")

    return safe_render(
        "communication/phase2_survey_template_form.html",
        template=None,
        question_type_labels=SURVEY_QUESTION_TYPE_LABELS,
    )


@main_bp.route("/communication/faz2/templates/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
@menu_key_required("surveys")
def communication_phase2_survey_template_edit(template_id: int):
    if not is_manager(current_user):
        flash("Bu işlem için yönetici yetkisi gerekir.", "warning")
        return redirect(url_for("main.communication_phase2_survey_templates"))

    template = CommunicationSurveyTemplate.query.get_or_404(template_id)

    if request.method == "POST":
        try:
            template = upsert_survey_template(
                template_id=template.id,
                actor_user_id=current_user.id,
                title=request.form.get("title"),
                description=request.form.get("description"),
                survey_type=request.form.get("survey_type"),
                is_active=bool(request.form.get("is_active")),
                questions_payload=_parse_questions_from_request(),
            )
            flash("Anket şablonu güncellendi.", "success")
            return redirect(url_for("main.communication_phase2_survey_template_edit", template_id=template.id))
        except CommunicationPhase2Error as exc:
            flash(str(exc), "warning")
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/communication/phase2_routes.py | line=471 | exc=%s", exc)
            flash("Anket şablonu güncellenemedi.", "danger")

    return safe_render(
        "communication/phase2_survey_template_form.html",
        template=template,
        question_type_labels=SURVEY_QUESTION_TYPE_LABELS,
    )
