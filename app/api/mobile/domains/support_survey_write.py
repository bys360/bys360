from __future__ import annotations

# BYS360 V1E: emergency runtime recovery for the Phase2Y wildcard-import regression.
# This deliberately restores the shared mobile contract first; explicit imports can be
# reintroduced later only after a per-file F821 gate and smoke test.
from app.api.mobile.shared import (
    Any,
    SupportTicket,
    SupportTicketMessage,
    SupportTicketStatusHistory,
    Survey,
    SurveyAnswer,
    SurveyResponse,
    User,
    _can_mobile_reply_ticket,
    _clean_mobile_text,
    _full_name,
    _generate_mobile_ticket_no,
    _mobile_survey_anonymous_token,
    _mobile_survey_assignment_for_user,
    _mobile_survey_completed,
    _mobile_survey_detail_payload,
    _mobile_survey_questions,
    _mobile_survey_validate_answers,
    _survey_is_active,
    _ticket_detail_payload,
    _user_org_unit_id,
    _user_unit_name,
    datetime,
    db,
    jsonify,
    mobile_api_bp,
    notify_support_ticket_comment,
    notify_support_ticket_created,
    request,
    require_mobile_user,
    timezone,
)
from app.services.support_ticket_access import can_view_all_support_tickets

try:
    from app.api.mobile.services import (  # type: ignore[attr-defined]
        support_survey_service as _mobile_support_service,
    )
except Exception:  # pragma: no cover - compatibility fallback
    try:
        from app.api.mobile.services import (
            support_service as _mobile_support_service,
        )
    except Exception:  # pragma: no cover
        _mobile_support_service = None

def _mobile_support_status_label(value: Any) -> str:
    status = str(value or "open").strip().lower()
    mapping = {
        "open": "Açık",
        "reviewing": "İncelemede",
        "in_progress": "İşlemde",
        "waiting_info": "Bilgi Bekleniyor",
        "planned": "Planlandı",
        "resolved": "Çözüldü",
        "closed": "Kapalı",
        "kapali": "Kapalı",
        "kapalı": "Kapalı",
        "rejected": "Reddedildi",
    }
    return mapping.get(status, str(value or "Açık"))


def _mobile_support_priority_label(value: Any) -> str:
    priority = str(value or "normal").strip().lower()
    mapping = {"low": "Düşük", "normal": "Normal", "high": "Yüksek", "critical": "Kritik"}
    return mapping.get(priority, str(value or "Normal"))


# BYS360 P11-B5: mobile_support_tickets support/survey read route app/api/mobile/support_survey_read_routes.py modülüne taşındı.


@mobile_api_bp.post("/support/tickets")
@require_mobile_user
def mobile_support_ticket_create(user: User):
    if _mobile_support_service is not None:
        return _mobile_support_service.mobile_support_ticket_create(user, _bys360_legacy_mobile_support_ticket_create)
    return _bys360_legacy_mobile_support_ticket_create(user)

def _bys360_legacy_mobile_support_ticket_create(user: User):
    data = request.get_json(silent=True) or {}
    title = _clean_mobile_text(data.get("title"), limit=255)
    description = _clean_mobile_text(data.get("description"), limit=4000)
    module_name = _clean_mobile_text(data.get("module_name") or "Mobil Uygulama", limit=120)
    ticket_type = _clean_mobile_text(data.get("ticket_type") or "mobile_support", limit=100)
    priority = (_clean_mobile_text(data.get("priority") or "normal", limit=20) or "normal").lower()
    if priority not in {"low", "normal", "high", "critical"}:
        priority = "normal"

    if len(title) < 3:
        return jsonify({"message": "Destek talebi başlığı en az 3 karakter olmalıdır."}), 400
    if len(description) < 5:
        return jsonify({"message": "Destek talebi açıklaması en az 5 karakter olmalıdır."}), 400

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ticket = SupportTicket(
        ticket_no=_generate_mobile_ticket_no(user),
        title=title,
        description=description,
        ticket_type=ticket_type,
        module_name=module_name,
        priority=priority,
        status="open",
        created_by_user_id=user.id,
        organization_unit_id=_user_org_unit_id(user),
        sicil_no_snapshot=getattr(user, "sicil_no", "") or "-",
        full_name_snapshot=_full_name(user),
        unit_name_snapshot=_user_unit_name(user),
        is_private=False,
    )
    ticket.created_at = now
    ticket.updated_at = now
    db.session.add(ticket)
    db.session.flush()
    db.session.add(SupportTicketStatusHistory(ticket_id=ticket.id, old_status=None, new_status="open", changed_by_user_id=user.id, note="Destek talebi oluşturuldu."))
    db.session.add(SupportTicketMessage(ticket_id=ticket.id, user_id=user.id, message_type="comment", message=description, is_internal=False))
    notify_support_ticket_created(ticket, user)
    db.session.commit()
    return jsonify(_ticket_detail_payload(ticket, user)), 201


# BYS360 P11-B4: mobile_support_ticket_detail detail read route app/api/mobile/detail_read_routes.py modülüne taşındı.


@mobile_api_bp.post("/support/tickets/<int:ticket_id>/reply")
@require_mobile_user
def mobile_support_ticket_reply(user: User, ticket_id: int):
    if _mobile_support_service is not None:
        return _mobile_support_service.mobile_support_ticket_reply(user, ticket_id, _bys360_legacy_mobile_support_ticket_reply)
    return _bys360_legacy_mobile_support_ticket_reply(user, ticket_id)

def _bys360_legacy_mobile_support_ticket_reply(user: User, ticket_id: int):
    ticket = db.session.get(SupportTicket, ticket_id)
    if not ticket:
        return jsonify({"message": "Destek talebi bulunamadı."}), 404
    if not _can_mobile_reply_ticket(user, ticket):
        return jsonify({"message": "Bu destek talebine cevap yazma yetkiniz bulunmamaktadır."}), 403

    data = request.get_json(silent=True) or {}
    message = _clean_mobile_text(data.get("message"), limit=2000)
    if len(message) < 3:
        return jsonify({"message": "Cevap alanı boş bırakılamaz."}), 400

    can_manage = can_view_all_support_tickets(user)  # K5: internal notes and open -> reviewing, as on the web
    is_internal = bool(data.get("is_internal")) and can_manage
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add(SupportTicketMessage(ticket=ticket, user_id=user.id, message_type="internal_note" if is_internal else "comment", message=message, is_internal=is_internal))
    ticket.updated_at = now
    if (getattr(ticket, "status", "") or "").strip().lower() == "open" and can_manage:
        old_status = ticket.status
        ticket.status = "reviewing"
        db.session.add(SupportTicketStatusHistory(ticket=ticket, old_status=old_status, new_status="reviewing", changed_by_user_id=user.id, note="Destek talebi incelemeye alındı."))
    notify_support_ticket_comment(ticket, user, is_internal=is_internal)
    db.session.commit()
    return jsonify({"message": "Destek talebine cevap eklendi.", "ticket": _ticket_detail_payload(ticket, user)["ticket"]})

# BYS360 P11-B5: mobile_surveys support/survey read route app/api/mobile/support_survey_read_routes.py modülüne taşındı.


# BYS360 P11-B4: mobile_survey_detail detail read route app/api/mobile/detail_read_routes.py modülüne taşındı.


@mobile_api_bp.post("/surveys/<int:survey_id>/submit")
@require_mobile_user
def mobile_survey_submit(user: User, survey_id: int):
    survey = db.session.get(Survey, survey_id)
    if not survey:
        return jsonify({"message": "Anket bulunamadı."}), 404
    assignment = _mobile_survey_assignment_for_user(user, survey)
    # Web survey_submit rule (matching_assignment_for_user): every respondent, admin included, needs an assignment.
    if assignment is None:
        return jsonify({"message": "Bu ankete cevap verme yetkiniz bulunmamaktadır."}), 403
    if not _survey_is_active(survey):
        return jsonify({"message": "Bu anket şu anda cevaplamaya açık değildir."}), 400
    if not bool(getattr(survey, "allow_multiple_submissions", False)) and _mobile_survey_completed(user, survey):
        return jsonify({"message": "Bu anket için cevabınız daha önce kaydedilmiş."}), 409

    data = request.get_json(silent=True) or {}
    answers = data.get("answers") or {}
    if not isinstance(answers, dict):
        return jsonify({"message": "Anket cevapları beklenen formatta değil."}), 400

    questions = _mobile_survey_questions(survey)
    if not questions:
        return jsonify({"message": "Bu ankette cevaplanacak soru bulunmuyor."}), 400

    try:
        prepared = _mobile_survey_validate_answers(survey, questions, answers)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    response = SurveyResponse(
        survey_id=survey.id,
        user_id=None if getattr(survey, "is_anonymous", False) else user.id,
        assignment_id=getattr(assignment, "id", None),
        submitted_at=now,
        is_completed=True,
        anonymous_token=_mobile_survey_anonymous_token(user, survey) if getattr(survey, "is_anonymous", False) else None,
    )
    db.session.add(response)
    db.session.flush()
    for row in prepared:
        db.session.add(SurveyAnswer(
            response_id=response.id,
            question_id=row["question_id"],
            selected_option_id=row.get("selected_option_id"),
            answer_text=row.get("answer_text"),
            answer_number=row.get("answer_number"),
        ))
    db.session.commit()
    return jsonify({"message": "Anket cevabınız kaydedildi.", "detail": _mobile_survey_detail_payload(survey, user)})

# BYS360 P11-B4: mobile_communication_threads detail read route app/api/mobile/detail_read_routes.py modülüne taşındı.


# BYS360 P11-B3: mobile_settings_summary light read route app/api/mobile/light_read_routes.py modülüne taşındı.


# BYS360 P11-B9: mobile_reports performance read route app/api/mobile/performance_read_routes.py modülüne taşındı.

