from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from flask import current_app
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app.core.datetime_utils import utc_now
from app.security.private_uploads import (
    locate_upload,
    private_upload_dir,
    private_upload_path,
    store_private_upload,
)

PROFILE_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def profile_photo_upload_dir() -> str:
    """Yeni profil fotoğrafları için yazma klasörü (B2-F06: static dışındaki özel depo)."""
    return str(private_upload_dir("profile_photos"))


def is_allowed_profile_photo(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower().strip()
    return ext in PROFILE_PHOTO_EXTENSIONS


def delete_profile_photo_copies(relative_path: str | None, *, owner_id: int | None = None) -> tuple[bool, bool]:
    """Clean every photo copy independently; preserve files referenced by others."""
    if not relative_path:
        return False, False
    clean = relative_path.strip().replace("\\", "/").lstrip("/")
    if clean.startswith("static/"):
        clean = clean[len("static/"):]
    name = clean.rsplit("/", 1)[-1]
    if not name or secure_filename(name) != name or clean not in {
        name, "profile_photos/" + name, "uploads/profile_photos/" + name,
    }:
        return False, True
    named_owner = re.match(r"user_(\d+)_", name, re.IGNORECASE)
    if owner_id is not None and named_owner and int(named_owner[1]) != owner_id:
        return False, True
    try:
        from app.extensions import db
        from app.models import User

        with db.session.no_autoflush:
            # Conservatively protect case aliases on Windows, even if the DB
            # collation treats the stored references as distinct strings.
            photo_path = func.lower(User.profile_photo_path)
            match_name = name.lower()
            query = User.query.filter(
                (photo_path == match_name) | photo_path.endswith("/" + match_name, autoescape=True)
                | photo_path.endswith("\\" + match_name, autoescape=True)
            )
            if owner_id is not None:
                query = query.filter(User.id != owner_id)
            if query.first() is not None:
                current_app.logger.warning("PRIVATE_UPLOAD_DELETE_SKIPPED_REFERENCED")
                return False, True
        roots = [private_upload_path("profile_photos"), Path(current_app.static_folder) / "uploads" / "profile_photos"]
        configured = current_app.config.get("UPLOAD_FOLDER") or os.getenv("UPLOAD_FOLDER")
        if configured:
            roots.extend([Path(configured) / "profile_photos", Path(configured) / "uploads" / "profile_photos"])
    except Exception:
        current_app.logger.warning("PRIVATE_UPLOAD_DELETE_FAILED")
        return False, True
    deleted = failed = False
    seen = set()
    for root in roots:
        try:
            located = locate_upload(name, (root,))
            if located is None:
                continue
            candidate = (located[0] / located[1]).resolve()
            candidate.relative_to(root.resolve())
            if candidate in seen:
                continue
            seen.add(candidate)
            candidate.unlink()
            deleted = True
        except (OSError, ValueError):
            failed = True
            current_app.logger.warning("PRIVATE_UPLOAD_DELETE_FAILED")
    return deleted, failed


def delete_profile_photo_file(relative_path: str | None, *, owner_id: int | None = None) -> None:
    delete_profile_photo_copies(relative_path, owner_id=owner_id)


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
    store_private_upload(file_storage, abs_path)

    old_path = getattr(user, "profile_photo_path", None)
    new_relative_path = f"uploads/profile_photos/{new_name}"

    if old_path and old_path != new_relative_path:
        delete_profile_photo_file(old_path, owner_id=user.id)

    user.profile_photo_path = new_relative_path
    user.profile_photo_updated_at = utc_now()
    return new_relative_path
