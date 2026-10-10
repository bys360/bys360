from __future__ import annotations

# BYS360 V1E: emergency runtime recovery for the Phase2Y wildcard-import regression.
# This deliberately restores the shared mobile contract first; explicit imports can be
# reintroduced later only after a per-file F821 gate and smoke test.
from app.api.mobile.shared import (
    MessageThread,
    MessageThreadParticipant,
    User,
    _dt_label,
    _full_name,
    _safe_count,
    current_app,
    datetime,
    db,
    jsonify,
    mobile_api_bp,
    request,
    require_mobile_user,
    timezone,
)


def _b48_txt(value):
    text = str(value or "").strip()
    return "" if text.lower() == "none" else text


def _b48_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _b48_user_row(u: User, current_user_id: int | None = None):
    # R06 (approved policy, 2026-10-10): the recipient picker and the participant lists carry the
    # name and the unit only. The sicil and title keys stay for client compatibility but are empty,
    # so they are neither shown nor searchable (the picker searches this row's values).
    full_name = _full_name(u)
    registry = ""
    unit = _b48_txt(getattr(u, "birim", None) or getattr(u, "unit_name", None) or getattr(u, "organization_unit_name", None))
    title = ""
    return {
        "id": getattr(u, "id", None),
        "user_id": getattr(u, "id", None),
        "display_name": full_name,
        "name": full_name,
        "full_name": full_name,
        "registry_no": registry,
        "sicil_no": registry,
        "unit_name": unit,
        "birim": unit,
        "title_name": title,
        "unvan": title,
        "subtitle": unit or (f"Sicil {registry}" if registry else title),
        "is_self": bool(current_user_id and getattr(u, "id", None) == current_user_id),
    }


def _b48_message_model():
    from app.models import Message
    return Message


def _b48_thread_access(thread_id: int, user: User):
    return MessageThreadParticipant.query.filter_by(thread_id=thread_id, user_id=user.id).first()


def _b48_participants(thread_id: int):
    rows = MessageThreadParticipant.query.filter_by(thread_id=thread_id).order_by(MessageThreadParticipant.id.asc()).all()
    result = []
    for p in rows:
        u = getattr(p, "user", None) or db.session.get(User, getattr(p, "user_id", None))
        if u:
            row = _b48_user_row(u)
        else:
            row = {"id": getattr(p, "user_id", None), "user_id": getattr(p, "user_id", None), "display_name": "BYS360 Kullanıcısı", "name": "BYS360 Kullanıcısı"}
        row.update({
            "is_muted": bool(getattr(p, "is_muted", False)),
            "is_pinned": bool(getattr(p, "is_pinned", False)),
        })
        result.append(row)
    return result


def _b48_message_row(message, user: User):
    sender = getattr(message, "sender", None) or db.session.get(User, getattr(message, "sender_user_id", None))
    deleted = bool(getattr(message, "is_deleted", False))
    body = "Silinmiş mesaj" if deleted else _b48_txt(getattr(message, "body", ""))
    sent_at = getattr(message, "sent_at", None) or getattr(message, "created_at", None)
    return {
        "id": getattr(message, "id", None),
        "message_id": getattr(message, "id", None),
        "thread_id": getattr(message, "thread_id", None),
        "sender_user_id": getattr(message, "sender_user_id", None),
        "sender_name": _full_name(sender),
        "body": body,
        "message_type": _b48_txt(getattr(message, "message_type", "text")) or "text",
        "sent_at": sent_at.isoformat() if sent_at else None,
        "sent_at_label": _dt_label(sent_at),
        "is_deleted": deleted,
        "is_mine": int(getattr(message, "sender_user_id", 0) or 0) == int(user.id),
    }


def _b48_thread_title(thread, user: User):
    subject = _b48_txt(getattr(thread, "subject", None))
    if subject:
        return subject
    others = []
    for p in _b48_participants(thread.id):
        if str(p.get("id") or p.get("user_id")) != str(user.id):
            label = _b48_txt(p.get("display_name") or p.get("name"))
            if label:
                others.append(label)
    return ", ".join(others[:3]) or "Kurum içi konuşma"


def _b48_thread_row(thread, user: User):
    from app.api.mobile.services.communication_service import _b48_thread_row_delegate
    return _b48_thread_row_delegate(thread, user)

def _bys360_legacy__b48_thread_row(thread, user: User):
    Message = _b48_message_model()
    participant = MessageThreadParticipant.query.filter_by(thread_id=thread.id, user_id=user.id).first()
    participants = _b48_participants(thread.id)
    last_message = Message.query.filter_by(thread_id=thread.id, is_deleted=False).order_by(Message.sent_at.desc(), Message.id.desc()).first()
    last_read_id = getattr(participant, "last_read_message_id", None) if participant else None
    unread_q = Message.query.filter_by(thread_id=thread.id, is_deleted=False).filter(Message.sender_user_id != user.id)
    if last_read_id:
        try:
            unread_q = unread_q.filter(Message.id > int(last_read_id))
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:1918)")
    unread = _safe_count(unread_q)
    last_at = getattr(last_message, "sent_at", None) if last_message else getattr(thread, "last_message_at", None)
    participant_label = ", ".join([_b48_txt(p.get("display_name") or p.get("name")) for p in participants if _b48_txt(p.get("display_name") or p.get("name"))][:4])
    return {
        "id": thread.id,
        "thread_id": thread.id,
        "subject": _b48_thread_title(thread, user),
        "title": _b48_thread_title(thread, user),
        "subtitle": _b48_txt(getattr(thread, "badge_label", None) or getattr(thread, "thread_type", None)),
        "thread_type": _b48_txt(getattr(thread, "thread_type", None) or "direct"),
        "thread_type_label": "Duyuru" if _b48_txt(getattr(thread, "thread_type", "")).lower() == "announcement" else "Mesajlaşma",
        "participants": participants,
        "participants_label": participant_label,
        "participant_count": len(participants),
        "last_message_body": _b48_txt(getattr(last_message, "body", "")) if last_message else "",
        "last_message_at": last_at.isoformat() if last_at else None,
        "last_message_at_label": _dt_label(last_at),
        "unread_count": unread,
        "is_pinned": bool(getattr(participant, "is_pinned", False)) if participant else False,
        "is_muted": bool(getattr(participant, "is_muted", False)) if participant else False,
        "is_active": bool(getattr(thread, "is_active", True)),
    }


def _b48_thread_detail(thread_id: int, user: User):
    Message = _b48_message_model()
    thread = db.session.get(MessageThread, thread_id)
    if not thread:
        return None
    messages = Message.query.filter_by(thread_id=thread_id).order_by(Message.sent_at.asc(), Message.id.asc()).limit(500).all()
    return {
        "source": "real_message_thread_detail_v2",
        "thread": _b48_thread_row(thread, user),
        "participants": _b48_participants(thread_id),
        "messages": [_b48_message_row(m, user) for m in messages],
        "items": [_b48_message_row(m, user) for m in messages],
    }


# BYS360 P11-B7: mobile_b48_communication_v2_threads communication v2 read route app/api/mobile/communication_v2_read_routes.py modülüne taşındı.


@mobile_api_bp.get("/communication/v2/threads/<int:thread_id>")
@require_mobile_user
def mobile_b48_communication_v2_thread_detail(user: User, thread_id: int):
    from app.api.mobile.services.communication_service import (
        mobile_b48_communication_v2_thread_detail_delegate,
    )
    return mobile_b48_communication_v2_thread_detail_delegate(user, thread_id)

def _bys360_legacy_mobile_b48_communication_v2_thread_detail(user: User, thread_id: int):
    participant = _b48_thread_access(thread_id, user)
    if not participant:
        return jsonify({"message": "Bu konuşmayı görüntüleme yetkiniz bulunmamaktadır."}), 403
    detail = _b48_thread_detail(thread_id, user)
    if not detail:
        return jsonify({"message": "Konuşma bulunamadı."}), 404
    try:
        messages = detail.get("messages") or []
        if messages:
            participant.last_read_message_id = int(messages[-1].get("id") or messages[-1].get("message_id") or 0) or participant.last_read_message_id
            participant.last_read_at = _b48_now()
            db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify(detail)


@mobile_api_bp.post("/communication/v2/threads/<int:thread_id>/send")
@require_mobile_user
def mobile_b48_communication_v2_send(user: User, thread_id: int):
    from app.api.mobile.services.communication_service import (
        mobile_b48_communication_v2_send_delegate,
    )
    return mobile_b48_communication_v2_send_delegate(user, thread_id)

def _bys360_legacy_mobile_b48_communication_v2_send(user: User, thread_id: int):
    Message = _b48_message_model()
    participant = _b48_thread_access(thread_id, user)
    if not participant:
        return jsonify({"message": "Bu konuşmaya mesaj gönderme yetkiniz bulunmamaktadır."}), 403
    payload = request.get_json(silent=True) or {}
    body = _b48_txt(payload.get("body"))
    if not body:
        return jsonify({"message": "Mesaj metni boş olamaz."}), 400
    if len(body) > 4000:
        return jsonify({"message": "Mesaj metni çok uzun. Lütfen kısaltarak tekrar deneyin."}), 400
    thread = db.session.get(MessageThread, thread_id)
    if not thread:
        return jsonify({"message": "Konuşma bulunamadı."}), 404
    try:
        now = _b48_now()
        msg = Message(thread_id=thread_id, sender_user_id=user.id, body=body[:4000], message_type="text", sent_at=now, is_deleted=False)
        db.session.add(msg)
        thread.last_message_at = now
        db.session.flush()
        participant.last_read_message_id = msg.id
        participant.last_read_at = now
        try:
            participant.is_archived = False
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:2054)")
        db.session.commit()
        return jsonify({"message": "Mesajınız gönderildi.", "detail": _b48_thread_detail(thread_id, user) or {}})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("B48 mobile send message failed")
        return jsonify({"message": "Mesaj gönderilemedi. Lütfen tekrar deneyin."}), 500


@mobile_api_bp.get("/communication/v2/users")
@require_mobile_user
def mobile_b48_communication_v2_users(user: User):
    from app.api.mobile.services.communication_service import (
        mobile_b48_communication_v2_users_delegate,
    )
    return mobile_b48_communication_v2_users_delegate(user)

def _bys360_legacy_mobile_b48_communication_v2_users(user: User):
    query_text = _b48_txt(request.args.get("q") or request.args.get("search") or request.args.get("query")).lower()
    try:
        requested_limit = int(float(request.args.get("limit", 10000) or 10000))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/communication_v2_write.py:235")
        requested_limit = 10000
    limit = max(1, min(10000, requested_limit))
    try:
        records = User.query.filter_by(is_active=True).order_by(User.ad.asc(), User.soyad.asc()).limit(limit).all()
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/communication_v2_write.py:240")
        records = User.query.filter_by(is_active=True).limit(limit).all()
    rows = []
    for u in records:
        if int(getattr(u, "id", 0) or 0) == int(user.id):
            continue
        row = _b48_user_row(u, current_user_id=user.id)
        haystack = " ".join(str(v or "") for v in row.values()).lower()
        if query_text and query_text not in haystack:
            continue
        rows.append(row)
    return jsonify({
        "source": "real_active_users_for_messages_v2",
        "total": len(rows),
        "count": len(rows),
        "limit": limit,
        "users": rows,
        "items": rows,
        "rows": rows,
        "personnel": rows,
    })


@mobile_api_bp.post("/communication/v2/create-thread")
@require_mobile_user
def mobile_b48_communication_v2_create_thread(user: User):
    from app.api.mobile.services.communication_service import (
        mobile_b48_communication_v2_create_thread_delegate,
    )
    return mobile_b48_communication_v2_create_thread_delegate(user)

def _bys360_legacy_mobile_b48_communication_v2_create_thread(user: User):
    Message = _b48_message_model()
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("participant_user_ids") or payload.get("participants") or payload.get("recipient_ids") or payload.get("user_ids") or []
    if isinstance(raw_ids, (str, int)):
        raw_ids = [raw_ids]
    participant_ids = []
    for raw in raw_ids:
        try:
            value = int(raw)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/api/mobile/routes.py:2111)")
            continue
        if value != int(user.id) and value not in participant_ids and db.session.get(User, value):
            participant_ids.append(value)
    if not participant_ids:
        return jsonify({"message": "Konuşma başlatmak için en az bir alıcı seçilmelidir."}), 400
    body = _b48_txt(payload.get("body"))
    if not body:
        return jsonify({"message": "Konuşma başlatmak için ilk mesajı yazmanız gerekir."}), 400
    subject = _b48_txt(payload.get("subject"))
    now = _b48_now()
    first_recipient = db.session.get(User, participant_ids[0])
    try:
        thread = MessageThread(
            thread_type="direct" if len(participant_ids) == 1 else "group",
            subject=subject or (f"{_full_name(user)} - {_full_name(first_recipient)}" if first_recipient else "Kurum içi konuşma"),
            badge_label="Mobil mesajlaşma",
            created_by_user_id=user.id,
            is_active=True,
            last_message_at=now,
        )
        db.session.add(thread)
        db.session.flush()
        for uid in [user.id] + participant_ids:
            db.session.add(MessageThreadParticipant(thread_id=thread.id, user_id=uid, joined_at=now, is_archived=False))
        msg = Message(thread_id=thread.id, sender_user_id=user.id, body=body[:4000], message_type="text", sent_at=now, is_deleted=False)
        db.session.add(msg)
        db.session.flush()
        self_participant = MessageThreadParticipant.query.filter_by(thread_id=thread.id, user_id=user.id).first()
        if self_participant:
            self_participant.last_read_message_id = msg.id
            self_participant.last_read_at = now
        db.session.commit()
        return jsonify({"message": "Konuşma başlatıldı.", "thread": _b48_thread_row(thread, user), "thread_id": thread.id, "detail": _b48_thread_detail(thread.id, user) or {}})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("B48 mobile create thread failed")
        return jsonify({"message": "Konuşma başlatılamadı. Lütfen tekrar deneyin."}), 500

