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
    datetime,
    db,
    jsonify,
    mobile_api_bp,
    request,
    require_mobile_user,
    timezone,
)


def _b46_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _b46_txt(value):
    text = str(value or "").strip()
    return "" if text.lower() == "none" else text


def _b46_user_label(user):
    return _full_name(user) if user else "BYS360 Kullanıcısı"


def _b46_thread_access(thread_id: int, user: User):
    participant = MessageThreadParticipant.query.filter_by(thread_id=thread_id, user_id=user.id).first()
    if participant:
        return participant
    return None


def _b46_participants(thread_id: int):
    rows = MessageThreadParticipant.query.filter_by(thread_id=thread_id).order_by(MessageThreadParticipant.id.asc()).all()
    result = []
    for p in rows:
        u = getattr(p, "user", None) or User.query.get(getattr(p, "user_id", None))
        result.append({
            "id": getattr(u, "id", None) or getattr(p, "user_id", None),
            "user_id": getattr(u, "id", None) or getattr(p, "user_id", None),
            "display_name": _b46_user_label(u),
            "name": _b46_user_label(u),
            "registry_no": "",  # R06: participants carry no sicil (key kept for client compatibility)
            "unit_name": _b46_txt(getattr(u, "birim", None) or getattr(u, "unit_name", None)),
            "is_muted": bool(getattr(p, "is_muted", False)),
            "is_pinned": bool(getattr(p, "is_pinned", False)),
        })
    return result


def _b46_thread_title(thread, user: User):
    subject = _b46_txt(getattr(thread, "subject", None))
    if subject:
        return subject
    participants = _b46_participants(thread.id)
    others = [p.get("display_name") for p in participants if str(p.get("id")) != str(user.id)]
    label = ", ".join([x for x in others if x][:3])
    return label or "Kurum içi konuşma"


def _b46_message_row(message, user: User):
    sender = getattr(message, "sender", None) or User.query.get(getattr(message, "sender_user_id", None))
    deleted = bool(getattr(message, "is_deleted", False))
    body = "Silinmiş mesaj" if deleted else _b46_txt(getattr(message, "body", ""))
    sent_at = getattr(message, "sent_at", None) or getattr(message, "created_at", None)
    return {
        "id": getattr(message, "id", None),
        "message_id": getattr(message, "id", None),
        "thread_id": getattr(message, "thread_id", None),
        "sender_user_id": getattr(message, "sender_user_id", None),
        "sender_name": _b46_user_label(sender),
        "body": body,
        "message_type": _b46_txt(getattr(message, "message_type", "text")) or "text",
        "sent_at": sent_at.isoformat() if sent_at else None,
        "sent_at_label": _dt_label(sent_at),
        "edited_at": edited_at.isoformat() if (edited_at := getattr(message, "edited_at", None)) else None,
        "is_deleted": deleted,
        "is_mine": getattr(message, "sender_user_id", None) == user.id,
    }


def _b46_thread_row(thread, user: User):
    from app.api.mobile.services.communication_service import _b46_thread_row_delegate
    return _b46_thread_row_delegate(thread, user)

def _bys360_legacy__b46_thread_row(thread, user: User):
    from app.models import Message
    participant = MessageThreadParticipant.query.filter_by(thread_id=thread.id, user_id=user.id).first()
    participants = _b46_participants(thread.id)
    last_message = Message.query.filter_by(thread_id=thread.id, is_deleted=False).order_by(Message.sent_at.desc(), Message.id.desc()).first()
    last_read_id = getattr(participant, "last_read_message_id", None) if participant else None
    unread_q = Message.query.filter_by(thread_id=thread.id, is_deleted=False).filter(Message.sender_user_id != user.id)
    if last_read_id:
        unread_q = unread_q.filter(Message.id > int(last_read_id))
    unread = _safe_count(unread_q)
    last_at = getattr(last_message, "sent_at", None) if last_message else getattr(thread, "last_message_at", None)
    title = _b46_thread_title(thread, user)
    participant_label = ", ".join([p.get("display_name", "") for p in participants if p.get("display_name")][:4])
    return {
        "id": thread.id,
        "thread_id": thread.id,
        "subject": title,
        "title": title,
        "subtitle": _b46_txt(getattr(thread, "badge_label", None) or getattr(thread, "thread_type", None)),
        "thread_type": _b46_txt(getattr(thread, "thread_type", None) or "direct"),
        "thread_type_label": "Duyuru" if _b46_txt(getattr(thread, "thread_type", "")).lower() == "announcement" else "Mesajlaşma",
        "participants": participants,
        "participants_label": participant_label,
        "participant_count": len(participants),
        "last_message_body": _b46_txt(getattr(last_message, "body", "")) if last_message else "",
        "last_message_at": last_at.isoformat() if last_at else None,
        "last_message_at_label": _dt_label(last_at),
        "unread_count": unread,
        "is_pinned": bool(getattr(participant, "is_pinned", False)) if participant else False,
        "is_muted": bool(getattr(participant, "is_muted", False)) if participant else False,
        "is_active": bool(getattr(thread, "is_active", True)),
    }


# BYS360 P11-B6: mobile_b46_communication_message_threads communication read route app/api/mobile/communication_read_routes.py modülüne taşındı.


def _b46_thread_detail_payload(thread_id: int, user: User):
    from app.models import Message
    thread = MessageThread.query.get(thread_id)
    if not thread:
        return None
    messages = Message.query.filter_by(thread_id=thread_id).order_by(Message.sent_at.asc(), Message.id.asc()).limit(300).all()
    return {
        "source": "real_message_thread_detail",
        "thread": _b46_thread_row(thread, user),
        "participants": _b46_participants(thread_id),
        "messages": [_b46_message_row(m, user) for m in messages],
    }


@mobile_api_bp.get("/communication/messages/threads/<int:thread_id>")
@require_mobile_user
def mobile_b46_communication_thread_detail(user: User, thread_id: int):
    from app.api.mobile.services.communication_service import (
        mobile_b46_communication_thread_detail_delegate,
    )
    return mobile_b46_communication_thread_detail_delegate(thread_id, user)

def _bys360_legacy_mobile_b46_communication_thread_detail(thread_id: int, user: User):
    from app.models import Message
    participant = _b46_thread_access(thread_id, user)
    if not participant:
        return jsonify({"message": "Bu konuşmayı görüntüleme yetkiniz bulunmamaktadır."}), 403
    detail = _b46_thread_detail_payload(thread_id, user)
    if not detail:
        return jsonify({"message": "Konuşma bulunamadı."}), 404
    messages = Message.query.filter_by(thread_id=thread_id).order_by(Message.sent_at.asc(), Message.id.asc()).limit(300).all()
    if messages:
        participant.last_read_message_id = messages[-1].id
        participant.last_read_at = _b46_now()
        db.session.commit()
    return jsonify(detail)


@mobile_api_bp.post("/communication/messages/threads/<int:thread_id>/send")
@require_mobile_user
def mobile_b46_communication_send_message(user: User, thread_id: int):
    from app.api.mobile.services.communication_service import (
        mobile_b46_communication_send_message_delegate,
    )
    return mobile_b46_communication_send_message_delegate(thread_id, user)

def _bys360_legacy_mobile_b46_communication_send_message(thread_id: int, user: User):
    from app.models import Message
    participant = _b46_thread_access(thread_id, user)
    if not participant:
        return jsonify({"message": "Bu konuşmaya mesaj gönderme yetkiniz bulunmamaktadır."}), 403
    payload = request.get_json(silent=True) or {}
    body = _b46_txt(payload.get("body"))
    if not body:
        return jsonify({"message": "Mesaj metni boş olamaz."}), 400
    if len(body) > 4000:
        return jsonify({"message": "Mesaj metni çok uzun. Lütfen kısaltarak tekrar deneyin."}), 400
    thread = MessageThread.query.get(thread_id)
    if not thread:
        return jsonify({"message": "Konuşma bulunamadı."}), 404
    now = _b46_now()
    msg = Message(thread_id=thread_id, sender_user_id=user.id, body=body, message_type="text", sent_at=now)
    db.session.add(msg)
    thread.last_message_at = now
    db.session.flush()
    participant.last_read_message_id = msg.id
    participant.last_read_at = now
    db.session.commit()
    return jsonify({"message": "Mesajınız gönderildi.", "detail": _b46_thread_detail_payload(thread_id, user) or {}})


# BYS360 P11-B6: mobile_b46_communication_users communication read route app/api/mobile/communication_read_routes.py modülüne taşındı.


@mobile_api_bp.post("/communication/messages/create-thread")
@require_mobile_user
def mobile_b46_communication_create_thread(user: User):
    from app.api.mobile.services.communication_service import (
        mobile_b46_communication_create_thread_delegate,
    )
    return mobile_b46_communication_create_thread_delegate(user)

def _bys360_legacy_mobile_b46_communication_create_thread(user: User):
    from app.models import Message
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("participant_user_ids") or payload.get("participants") or payload.get("recipient_ids") or []
    if isinstance(raw_ids, (str, int)):
        raw_ids = [raw_ids]
    participant_ids = []
    for raw in raw_ids:
        try:
            value = int(raw)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/api/mobile/routes.py:1782)")
            continue
        # Unknown user ids are dropped, as in the v2 create-thread (participant FK -> users.id).
        if value != user.id and value not in participant_ids and db.session.get(User, value):
            participant_ids.append(value)
    if not participant_ids:
        return jsonify({"message": "Konuşma başlatmak için en az bir alıcı seçilmelidir."}), 400
    body = _b46_txt(payload.get("body"))
    if not body:
        return jsonify({"message": "Konuşma başlatmak için ilk mesajı yazmanız gerekir."}), 400
    subject = _b46_txt(payload.get("subject"))
    first_recipient = User.query.get(participant_ids[0])
    now = _b46_now()
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
        db.session.add(MessageThreadParticipant(thread_id=thread.id, user_id=uid, joined_at=now))
    msg = Message(thread_id=thread.id, sender_user_id=user.id, body=body[:4000], message_type="text", sent_at=now)
    db.session.add(msg)
    db.session.flush()
    self_participant = MessageThreadParticipant.query.filter_by(thread_id=thread.id, user_id=user.id).first()
    if self_participant:
        self_participant.last_read_message_id = msg.id
        self_participant.last_read_at = now
    db.session.commit()
    return jsonify({"message": "Konuşma başlatıldı.", "thread": _b46_thread_row(thread, user), "thread_id": thread.id})

