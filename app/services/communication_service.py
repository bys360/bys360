from __future__ import annotations

import logging
from pathlib import Path

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import MessageAttachment, MessageThreadParticipant
from app.models.communication_phase1_models import (
    CommunicationBulletin,
    CommunicationBulletinReceipt,
)
from app.services.communication_phase1_service import resolve_bulletin_target_users
from app.services.message_service import message_attachment_search_dirs

logger = logging.getLogger(__name__)


class CommunicationServiceError(RuntimeError):
    """İletişim alanında kullanıcıya gösterilebilir iş hataları."""


_TRUE_VALUES = {"1", "true", "on", "yes", "pin", "sabit", "evet"}
_FALSE_VALUES = {"0", "false", "off", "no", "unpin", "hayir", "çıkar", "cikar"}


def _normalize_toggle_state(current_value: bool, requested_state: str | None) -> bool:
    raw = str(requested_state or "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return not bool(current_value)


def get_pinned_thread_ids(user_id: int | None) -> set[int]:
    if not user_id:
        return set()
    rows = (
        MessageThreadParticipant.query
        .filter_by(user_id=user_id, is_pinned=True)
        .filter(MessageThreadParticipant.left_at.is_(None))
        .all()
    )
    return {int(row.thread_id) for row in rows if getattr(row, "thread_id", None) is not None}


def set_message_thread_pin_state(participant: MessageThreadParticipant | None, requested_state: str | None = None) -> tuple[bool, str]:
    if not participant:
        raise CommunicationServiceError("Konuşma bulunamadı.")

    current_value = bool(getattr(participant, "is_pinned", False))
    target_value = _normalize_toggle_state(current_value, requested_state)
    participant.is_pinned = target_value
    participant.updated_at = utc_now()

    if target_value and not current_value:
        return True, "Sohbet sabitlendi."
    if not target_value and current_value:
        return False, "Sohbet sabitlemeden çıkarıldı."
    return target_value, "Sohbet sabit durumu korundu."


def touch_thread_read_state(participant: MessageThreadParticipant | None, message_id: int | None = None) -> None:
    if not participant:
        return
    if message_id:
        participant.last_read_message_id = message_id
    participant.last_read_at = utc_now()


def _can_user_receive_bulletin(bulletin: CommunicationBulletin | None, user_id: int | None) -> bool:
    if not bulletin or not user_id:
        return False
    try:
        target_ids = {int(row.id) for row in resolve_bulletin_target_users(bulletin) if getattr(row, "id", None) is not None}
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_service.py | line=73")
        return False
    return int(user_id) in target_ids


def get_bulletin_receipt(bulletin_id: int, user_id: int, create_if_missing: bool = False) -> CommunicationBulletinReceipt | None:
    bulletin = db.session.get(CommunicationBulletin, bulletin_id)
    if not bulletin:
        raise CommunicationServiceError("Duyuru kaydı bulunamadı.")

    receipt = CommunicationBulletinReceipt.query.filter_by(bulletin_id=bulletin_id, user_id=user_id).first()
    if receipt or not create_if_missing:
        return receipt

    if not _can_user_receive_bulletin(bulletin, user_id):
        return None

    receipt = CommunicationBulletinReceipt(
        bulletin_id=bulletin_id,
        user_id=user_id,
        delivered_at=utc_now(),
    )
    return receipt


def mark_bulletin_read(bulletin_id: int, user_id: int) -> CommunicationBulletinReceipt | None:
    receipt = get_bulletin_receipt(bulletin_id, user_id, create_if_missing=True)
    if not receipt:
        return None
    if not receipt.is_read:
        receipt.is_read = True
        receipt.read_at = utc_now()
    return receipt


def acknowledge_bulletin_receipt(bulletin_id: int, user_id: int) -> CommunicationBulletinReceipt:
    receipt = get_bulletin_receipt(bulletin_id, user_id, create_if_missing=True)
    if not receipt:
        raise CommunicationServiceError("Bu duyuru için teslim kaydı bulunamadı.")
    if not receipt.is_read:
        receipt.is_read = True
        receipt.read_at = utc_now()
    if not receipt.is_acknowledged:
        receipt.is_acknowledged = True
        receipt.acknowledged_at = utc_now()
    return receipt


def bulletin_receipt_summary(bulletin: CommunicationBulletin | None) -> dict[str, int]:
    if not bulletin:
        return {"targeted": 0, "delivered": 0, "read": 0, "acknowledged": 0}

    targeted = len(resolve_bulletin_target_users(bulletin)) if bulletin else 0
    receipts = bulletin.receipts.all() if hasattr(bulletin.receipts, "all") else list(bulletin.receipts or [])
    return {
        "targeted": int(targeted),
        "delivered": len(receipts),
        "read": sum(1 for row in receipts if bool(getattr(row, "is_read", False))),
        "acknowledged": sum(1 for row in receipts if bool(getattr(row, "is_acknowledged", False))),
    }


def resolve_message_attachment_download(attachment: MessageAttachment | None) -> tuple[Path, str]:
    if not attachment:
        raise CommunicationServiceError("Dosya kaydı bulunamadı.")

    stored_filename = str(getattr(attachment, "stored_filename", "") or "").strip()
    if not stored_filename:
        raise CommunicationServiceError("Dosya adı eksik görünüyor.")
    if Path(stored_filename).name != stored_filename or "/" in stored_filename or "\\" in stored_filename:
        raise CommunicationServiceError("Dosya adı güvenli değil.")

    for base in message_attachment_search_dirs():
        upload_dir = base.resolve()
        candidate = (upload_dir / stored_filename).resolve()
        if upload_dir in candidate.parents and candidate.is_file():
            return upload_dir, candidate.name
    raise CommunicationServiceError("Dosya sunucuda bulunamadı.")
