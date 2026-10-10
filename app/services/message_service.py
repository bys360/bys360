from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    Message,
    MessageAttachment,
    MessageThread,
    MessageThreadParticipant,
    Notification,
)
from app.security.private_uploads import (
    legacy_static_upload_path,
    private_upload_dir,
    private_upload_path,
)
from app.services.runtime_cache import (
    get_or_set as _cache_get_or_set,
    invalidate as _cache_invalidate,
)

logger = logging.getLogger(__name__)
ALLOWED_MESSAGE_FILE_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".txt",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic", ".heif",
    ".mp4", ".webm", ".mov", ".m4v",
    ".zip", ".rar", ".7z"
}
IMAGE_MESSAGE_FILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic", ".heif"}
VIDEO_MESSAGE_FILE_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
MAX_MESSAGE_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_MESSAGE_TOTAL_SIZE = 100 * 1024 * 1024  # 100 MB toplam mesaj yükü
MAX_MESSAGE_ATTACHMENTS = 5
_MESSAGE_PLACEHOLDER_BODIES = {"[Dosya Eki]", "[Ek]"}
_ALLOWED_ANNOUNCEMENT_ROLES = {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "koordinator", "mali_musavir"}

MESSAGE_THREAD_ICON_OPTIONS = [
    ("fa-solid fa-comments", "Sohbet"),
    ("fa-solid fa-paper-plane", "Hızlı Mesaj"),
    ("fa-solid fa-bell", "Bilgilendirme"),
    ("fa-solid fa-circle-info", "Bilgi Notu"),
    ("fa-solid fa-bolt", "Öncelikli"),
    ("fa-solid fa-people-arrows", "Koordinasyon"),
    ("fa-solid fa-handshake", "İş Birliği"),
    ("fa-solid fa-thumbtack", "Takip"),
    ("fa-solid fa-star", "Öne Çıkan"),
    ("fa-solid fa-shield-heart", "Kurumsal"),
]

MESSAGE_THREAD_COLOR_OPTIONS = [
    ("#8B0000", "Kurumsal Bordo"),
    ("#A31515", "Güçlü Kırmızı"),
    ("#B45309", "Kehribar"),
    ("#0F766E", "Teal"),
    ("#1D4ED8", "Mavi"),
    ("#6D28D9", "Mor"),
    ("#BE185D", "Fuşya"),
    ("#374151", "Antrasit"),
]

MESSAGE_THREAD_BADGE_OPTIONS = [
    "Kurumsal Mesaj",
    "Bilgi Notu",
    "Hızlı Dönüş",
    "Öncelikli",
    "Koordinasyon",
    "Takip",
    "Hatırlatma",
    "İş Birliği",
    "Kendime Not",
]

_DEFAULT_THREAD_ICON = "fa-solid fa-comments"
_DEFAULT_THREAD_COLOR = "#8B0000"
_SELF_THREAD_ICON = "fa-solid fa-note-sticky"
_SELF_THREAD_COLOR = "#374151"
_SELF_THREAD_BADGE = "Kendime Not"
_SELF_THREAD_SUBJECT = "Kendime Notlar"


def _normalize_hex_color(value: str | None, default: str = _DEFAULT_THREAD_COLOR) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if not raw.startswith("#"):
        raw = f"#{raw}"
    raw = raw[:7]
    if len(raw) != 7:
        return default
    try:
        int(raw[1:], 16)
    except ValueError:
        return default
    return raw.upper()


def _normalize_fa_solid_icon(value: str | None, default: str = _DEFAULT_THREAD_ICON) -> str | None:
    raw = " ".join((value or "").strip().split())
    if not raw:
        return None
    if not raw.startswith("fa-solid "):
        return default
    icon_token = raw.split(" ", 1)[1].strip()
    if not icon_token.startswith("fa-"):
        return default
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(ch.lower() not in allowed for ch in icon_token):
        return default
    return f"fa-solid {icon_token}"


def normalize_message_thread_style(*, badge_label: str = "", icon_name: str = "", accent_color: str = "") -> dict[str, str | None]:
    badge = (badge_label or "").strip()[:120] or None
    icon = _normalize_fa_solid_icon(icon_name, default=_DEFAULT_THREAD_ICON)
    color = _normalize_hex_color(accent_color, default=_DEFAULT_THREAD_COLOR)
    return {
        "badge_label": badge,
        "icon_name": icon,
        "accent_color": color,
    }


def apply_message_thread_style(thread: MessageThread, *, badge_label: str = "", icon_name: str = "", accent_color: str = "", overwrite: bool = False) -> MessageThread:
    payload = normalize_message_thread_style(
        badge_label=badge_label,
        icon_name=icon_name,
        accent_color=accent_color,
    )
    if overwrite:
        if payload["badge_label"]:
            thread.badge_label = payload["badge_label"]
        if payload["icon_name"]:
            thread.icon_name = payload["icon_name"]
        if payload["accent_color"]:
            thread.accent_color = payload["accent_color"]
        return thread

    if not getattr(thread, "badge_label", None) and payload["badge_label"]:
        thread.badge_label = payload["badge_label"]
    if not getattr(thread, "icon_name", None) and payload["icon_name"]:
        thread.icon_name = payload["icon_name"]
    if not getattr(thread, "accent_color", None) and payload["accent_color"]:
        thread.accent_color = payload["accent_color"]
    return thread


def thread_icon_name(thread: MessageThread | None) -> str:
    return (getattr(thread, "icon_name", None) or _DEFAULT_THREAD_ICON).strip() or _DEFAULT_THREAD_ICON


def thread_accent_color(thread: MessageThread | None) -> str:
    return (getattr(thread, "accent_color", None) or _DEFAULT_THREAD_COLOR).strip() or _DEFAULT_THREAD_COLOR

def _file_size(file_storage) -> int:
    current = None
    try:
        current = file_storage.stream.tell()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/message_service.py | line=164")
        current = None
    try:
        file_storage.stream.seek(0, 2)
        size = int(file_storage.stream.tell() or 0)
    finally:
        try:
            if current is None:
                file_storage.stream.seek(0)
            else:
                file_storage.stream.seek(current)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/message_service.py")
    return size


def _peek_bytes(file_storage, size: int = 32) -> bytes:
    current = None
    try:
        current = file_storage.stream.tell()
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/message_service.py | line=185")
        current = None
    try:
        file_storage.stream.seek(0)
        data = file_storage.stream.read(size) or b""
    finally:
        try:
            if current is None:
                file_storage.stream.seek(0)
            else:
                file_storage.stream.seek(current)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/message_service.py")
    return data


def _validate_message_attachment(file_storage, max_bytes: int = MAX_MESSAGE_FILE_SIZE):
    original_name = secure_filename(getattr(file_storage, "filename", "") or "")
    if not original_name:
        return False, "Dosya adı boş.", "", 0

    ext = Path(original_name).suffix.lower()
    if not ext or ext not in ALLOWED_MESSAGE_FILE_EXTENSIONS:
        allowed = ", ".join(sorted(x.lstrip(".") for x in ALLOWED_MESSAGE_FILE_EXTENSIONS))
        return False, f"Desteklenmeyen dosya türü. İzin verilenler: {allowed}", original_name, 0

    file_size = _file_size(file_storage)
    if max_bytes and file_size > max_bytes:
        return False, f"{original_name} dosyası {max_bytes // (1024 * 1024)} MB sınırını aşıyor.", original_name, file_size

    header = _peek_bytes(file_storage, 32)
    suspicious = False
    if ext == ".pdf" and header and not header.startswith(b"%PDF") or ext in {".doc", ".xls", ".ppt"} and header and not header.startswith(b"\xd0\xcf\x11\xe0") or ext in {".docx", ".xlsx", ".pptx", ".zip"} and header and not header.startswith(b"PK") or ext == ".png" and header and not header.startswith(b"\x89PNG\r\n\x1a\n") or ext in {".jpg", ".jpeg"} and header and not (header.startswith(b"\xff\xd8\xff")) or ext == ".webp" and header and not (len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP") or ext == ".gif" and header and not (header.startswith(b"GIF87a") or header.startswith(b"GIF89a")) or ext == ".bmp" and header and not header.startswith(b"BM") or ext == ".7z" and header and not header.startswith(b"7z\xbc\xaf'\x1c") or ext in {".mp4", ".mov", ".m4v"} and header and not (len(header) >= 12 and header[4:8] == b"ftyp") or ext == ".webm" and header and not header.startswith(b"\x1a\x45\xdf\xa3") or ext == ".rar" and header and not (header.startswith(b"Rar!\x1a\x07\x00") or header.startswith(b"Rar!\x1a\x07\x01\x00")):
        suspicious = True

    if suspicious:
        return False, "Dosya uzantısı ile içerik tipi uyuşmuyor gibi görünüyor.", original_name, file_size

    return True, "ok", original_name, file_size


def normalize_incoming_message_files(request_obj):
    files = []
    for key in ("attachments", "attachment"):
        try:
            incoming = request_obj.files.getlist(key)
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/message_service.py | line=254")
            incoming = []
        for file_storage in incoming or []:
            if file_storage and getattr(file_storage, "filename", ""):
                files.append(file_storage)
    if len(files) > MAX_MESSAGE_ATTACHMENTS:
        raise ValueError(f"Bir mesajda en fazla {MAX_MESSAGE_ATTACHMENTS} dosya gönderebilirsiniz.")
    total_size = 0
    for file_storage in files:
        total_size += _file_size(file_storage)
    if total_size > MAX_MESSAGE_TOTAL_SIZE:
        raise ValueError(f"Bir mesajdaki eklerin toplamı {MAX_MESSAGE_TOTAL_SIZE // (1024 * 1024)} MB sınırını aşıyor.")
    return files


def attachment_is_image(attachment) -> bool:
    ext = (getattr(attachment, "file_ext", "") or Path(getattr(attachment, "original_filename", "") or "").suffix).lower()
    mime = (getattr(attachment, "mime_type", "") or "").lower()
    return ext in IMAGE_MESSAGE_FILE_EXTENSIONS or mime.startswith("image/")


def attachment_is_video(attachment) -> bool:
    ext = (getattr(attachment, "file_ext", "") or Path(getattr(attachment, "original_filename", "") or "").suffix).lower()
    mime = (getattr(attachment, "mime_type", "") or "").lower()
    return ext in VIDEO_MESSAGE_FILE_EXTENSIONS or mime.startswith("video/")


def attachment_icon_class(attachment) -> str:
    ext = (getattr(attachment, "file_ext", "") or Path(getattr(attachment, "original_filename", "") or "").suffix).lower()
    if ext in IMAGE_MESSAGE_FILE_EXTENSIONS:
        return "fa-regular fa-image"
    if ext in VIDEO_MESSAGE_FILE_EXTENSIONS:
        return "fa-regular fa-file-video"
    if ext == ".pdf":
        return "fa-regular fa-file-pdf"
    if ext in {".ppt", ".pptx"}:
        return "fa-regular fa-file-powerpoint"
    if ext in {".doc", ".docx"}:
        return "fa-regular fa-file-word"
    if ext in {".xls", ".xlsx", ".csv"}:
        return "fa-regular fa-file-excel"
    if ext in {".zip", ".rar", ".7z"}:
        return "fa-regular fa-file-zipper"
    return "fa-regular fa-file-lines"


def format_attachment_file_size(size: int | None) -> str:
    try:
        value = float(size or 0)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/message_service.py | line=303")
        value = 0.0
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{int(value)} B"


def remove_message_attachment_file(stored_filename: str | None) -> None:
    if not stored_filename:
        return
    try:
        abs_path = resolve_message_attachment_abspath(stored_filename)
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/message_service.py | line=317")
        return
    try:
        abs_path.unlink(missing_ok=True)
    except Exception:
        # B2-F06: depolanan ad indirme adresinin anahtarıdır; günlüğe yazılmaz.
        current_app.logger.warning("Mesaj eki silinemedi.")


def message_placeholder_bodies() -> set[str]:
    return set(_MESSAGE_PLACEHOLDER_BODIES)


def message_upload_dir() -> Path:
    """Yeni mesaj ekleri için yazma klasörü (B2-F06: static dışındaki özel depo)."""
    return private_upload_dir("messages")


def message_attachment_search_dirs() -> tuple[Path, ...]:
    """Ek okuma sırası: özel depo, ardından bu değişiklikten önce kullanılan static konumu."""
    return (private_upload_path("messages"), legacy_static_upload_path("messages"))


def resolve_message_attachment_abspath(stored_filename: str | None) -> Path:
    filename = str(stored_filename or "").strip()
    if not filename:
        raise ValueError("Dosya adı boş.")
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise ValueError("Dosya adı güvenli değil.")

    for base in message_attachment_search_dirs():
        base_dir = base.resolve()
        candidate = (base_dir / filename).resolve()
        if base_dir in candidate.parents and candidate.is_file():
            return candidate
    raise ValueError("Dosya bulunamadı.")


def save_message_attachment(file_storage, message, uploaded_by_user_id):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    ok, validation_message, original_name, file_size = _validate_message_attachment(file_storage, MAX_MESSAGE_FILE_SIZE)
    if not ok:
        raise ValueError(validation_message)

    ext = Path(original_name).suffix.lower()
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = message_upload_dir()
    abs_path = upload_dir / stored_filename

    file_storage.stream.seek(0)
    file_storage.save(abs_path)

    attachment = MessageAttachment(
        message_id=message.id,
        original_filename=original_name,
        stored_filename=stored_filename,
        file_path=f"uploads/messages/{stored_filename}",
        file_ext=ext,
        mime_type=(getattr(file_storage, "mimetype", None) or mimetypes.guess_type(original_name)[0]),
        file_size=file_size,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.session.add(attachment)
    return attachment


def get_message_attachment_for_user(stored_filename: str, user_id: int) -> MessageAttachment | None:
    if not stored_filename:
        return None

    attachment = (
        MessageAttachment.query
        .join(Message, Message.id == MessageAttachment.message_id)
        .join(MessageThread, MessageThread.id == Message.thread_id)
        .join(MessageThreadParticipant, MessageThreadParticipant.thread_id == MessageThread.id)
        .filter(
            MessageAttachment.stored_filename == stored_filename,
            MessageThreadParticipant.user_id == user_id,
            MessageThreadParticipant.left_at.is_(None),
            MessageThread.is_active.is_(True),
        )
        .first()
    )
    return attachment


def get_unread_notification_count(user_id: int) -> int:
    cache_key = f"notification_unread_count:{int(user_id or 0)}"

    def _factory() -> int:
        try:
            return int(Notification.query.filter_by(user_id=user_id, is_read=False).count())
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/services/message_service.py | line=405")
            return 0

    return int(_cache_get_or_set(cache_key, _factory, ttl_seconds=20) or 0)


def can_use_announcement_tools(user) -> bool:
    return (getattr(user, "role", "") or "").lower() in _ALLOWED_ANNOUNCEMENT_ROLES


def get_direct_thread_between(user_a_id: int, user_b_id: int):
    if user_a_id == user_b_id:
        return (
            MessageThread.query
            .join(MessageThreadParticipant, MessageThreadParticipant.thread_id == MessageThread.id)
            .filter(
                MessageThread.thread_type == "self",
                MessageThreadParticipant.user_id == user_a_id,
                MessageThreadParticipant.left_at.is_(None),
                MessageThread.is_active.is_(True),
            )
            .order_by(MessageThread.last_message_at.desc().nullslast(), MessageThread.id.desc())
            .first()
        )

    thread_ids_a = db.session.query(MessageThreadParticipant.thread_id).filter(
        MessageThreadParticipant.user_id == user_a_id,
        MessageThreadParticipant.left_at.is_(None),
    )
    thread_ids_b = db.session.query(MessageThreadParticipant.thread_id).filter(
        MessageThreadParticipant.user_id == user_b_id,
        MessageThreadParticipant.left_at.is_(None),
    )

    return MessageThread.query.filter(
        MessageThread.thread_type == "direct",
        MessageThread.id.in_(thread_ids_a),
        MessageThread.id.in_(thread_ids_b),
        MessageThread.is_active.is_(True),
    ).order_by(MessageThread.last_message_at.desc().nullslast()).first()


def get_or_create_direct_thread(user_a_id: int, user_b_id: int, *, badge_label: str = "", icon_name: str = "", accent_color: str = ""):
    is_self_thread = user_a_id == user_b_id
    thread = get_direct_thread_between(user_a_id, user_b_id)
    if thread:
        if is_self_thread:
            apply_message_thread_style(
                thread,
                badge_label=badge_label or _SELF_THREAD_BADGE,
                icon_name=icon_name or _SELF_THREAD_ICON,
                accent_color=accent_color or _SELF_THREAD_COLOR,
                overwrite=True,
            )
            if not getattr(thread, "subject", None):
                thread.subject = _SELF_THREAD_SUBJECT
        else:
            apply_message_thread_style(
                thread,
                badge_label=badge_label,
                icon_name=icon_name,
                accent_color=accent_color,
                overwrite=True,
            )
        return thread

    thread = MessageThread(
        thread_type="self" if is_self_thread else "direct",
        subject=_SELF_THREAD_SUBJECT if is_self_thread else None,
        badge_label=None,
        icon_name=None,
        accent_color=None,
        created_by_user_id=user_a_id,
        is_active=True,
        last_message_at=utc_now(),
    )
    db.session.add(thread)
    db.session.flush()
    apply_message_thread_style(
        thread,
        badge_label=badge_label or (_SELF_THREAD_BADGE if is_self_thread else ""),
        icon_name=icon_name or (_SELF_THREAD_ICON if is_self_thread else ""),
        accent_color=accent_color or (_SELF_THREAD_COLOR if is_self_thread else ""),
        overwrite=True,
    )

    db.session.add(MessageThreadParticipant(
        thread_id=thread.id,
        user_id=user_a_id,
        joined_at=utc_now(),
    ))
    if not is_self_thread:
        db.session.add(MessageThreadParticipant(
            thread_id=thread.id,
            user_id=user_b_id,
            joined_at=utc_now(),
        ))
    db.session.flush()
    return thread


def find_or_create_direct_thread(user_a_id: int, user_b_id: int, *, badge_label: str = "", icon_name: str = "", accent_color: str = ""):
    return get_or_create_direct_thread(
        user_a_id,
        user_b_id,
        badge_label=badge_label,
        icon_name=icon_name,
        accent_color=accent_color,
    )


def notify_user(
    user_id: int,
    title: str,
    body: str = "",
    notification_type: str = "system",
    source_type: str | None = None,
    source_id: int | None = None,
    link_url: str | None = None,
    priority: str = "normal",
):
    notification = Notification(
        user_id=user_id,
        title=(title or "").strip()[:255] or "BYS360 Bildirimi",
        body=(body or "").strip() or None,
        notification_type=notification_type,
        source_type=source_type,
        source_id=source_id,
        link_url=link_url,
        priority=priority or "normal",
        is_read=False,
    )
    db.session.add(notification)
    _cache_invalidate(f"notification_unread_count:{int(user_id or 0)}")
    return notification


def survey_manager_allowed(user) -> bool:
    return can_use_announcement_tools(user)


def user_matches_assignment(assignment, user) -> bool:
    if not assignment:
        return False

    target_type = (assignment.target_type or "").strip().lower()
    target_value = (assignment.target_value or "").strip()

    if target_type == "all":
        return True
    if target_type == "user":
        return str(user.id) == target_value
    if target_type == "role":
        return ((getattr(user, "role", "") or "").strip().lower() == target_value.strip().lower())
    if target_type == "unit":
        return ((getattr(user, "birim", "") or "").strip().lower() == target_value.strip().lower())
    return False


def get_visible_surveys_for_user(user):
    now = utc_now()
    from app.services.surveys.targets import assigned_survey_assignment_rows_for_user

    visible = []
    seen_survey_ids: set[int] = set()
    for survey, _assignment in assigned_survey_assignment_rows_for_user(user, active_window=True, now=now):
        survey_id = int(getattr(survey, "id", 0) or 0)
        if not survey_id or survey_id in seen_survey_ids:
            continue
        seen_survey_ids.add(survey_id)
        visible.append(survey)
    return visible


def resolve_message_attachment_download(*args, **kwargs):
    """Message attachment download g?venlik s?zle?mesi.

    Bu fonksiyon, mevcut get_message_attachment_for_user ak???na uyumlu
    statik contract alias'?d?r.
    """
    if "get_message_attachment_for_user" in globals():
        return get_message_attachment_for_user(*args, **kwargs)
    return None

