from __future__ import annotations

import os
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from app.core.datetime_utils import utc_now
from app.security.private_uploads import locate_upload, private_upload_dir, private_upload_path

PROFILE_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def profile_photo_upload_dir() -> str:
    """Yeni profil fotoğrafları için yazma klasörü (B2-F06: static dışındaki özel depo)."""
    return str(private_upload_dir("profile_photos"))


def is_allowed_profile_photo(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower().strip()
    return ext in PROFILE_PHOTO_EXTENSIONS


def delete_profile_photo_file(relative_path: str | None) -> None:
    if not relative_path:
        return

    try:
        private_copy = locate_upload(os.path.basename(relative_path.replace("\\", "/")), (private_upload_path("profile_photos"),))
        if private_copy is not None:
            os.remove(os.path.join(private_copy[0], private_copy[1]))
        abs_path = os.path.join(current_app.root_path, "static", relative_path.replace("/", os.sep))
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except Exception as exc:
        # B2-F06: OSError metni dosya yolunu ve indirme anahtarı olan adı taşır; yalnız türü yazılır.
        current_app.logger.warning("Profil fotoğrafı silinirken hata oluştu (%s).", type(exc).__name__)


def save_profile_photo(file_storage, user) -> str:
    if not file_storage or not getattr(file_storage, "filename", ""):
        return user.profile_photo_path

    filename = secure_filename(file_storage.filename or "")
    if not is_allowed_profile_photo(filename):
        raise ValueError("Sadece PNG, JPG, JPEG veya WEBP dosyaları yükleyebilirsiniz.")

    ext = filename.rsplit(".", 1)[1].lower().strip()
    new_name = f"user_{user.id}_{uuid4().hex}.{ext}"

    upload_dir = profile_photo_upload_dir()
    abs_path = os.path.join(upload_dir, new_name)
    file_storage.save(abs_path)

    old_path = getattr(user, "profile_photo_path", None)
    new_relative_path = f"uploads/profile_photos/{new_name}"

    if old_path and old_path != new_relative_path:
        delete_profile_photo_file(old_path)

    user.profile_photo_path = new_relative_path
    user.profile_photo_updated_at = utc_now()
    return new_relative_path