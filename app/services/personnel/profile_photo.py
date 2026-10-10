from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flask import has_app_context

from app.core.datetime_utils import utc_now
from app.security.private_uploads import locate_upload, private_upload_path

"""Personel profil fotoğrafı servis köprüsü.

Faz 4 kapsamı:
- Route içindeki profil fotoğrafı yükleme/silme kararını servis katmanına alır.
- Commit/rollback, flash/redirect ve kayıt akışı route tarafında kalır.
- Dosya silme sırasında yalnızca uygulamanın static kökü altındaki dosyalar hedeflenir.
"""

PhotoSaver = Callable[[Any, Any], Any]


@dataclass(frozen=True, slots=True)
class PersonnelProfilePhotoResult:
    phase: str
    action: str
    db_commit: bool
    db_rollback: bool
    route_contract: str
    file_deleted: bool = False
    file_uploaded: bool = False
    skipped: bool = False
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _set_photo_fields_empty(user: Any) -> None:
    if hasattr(user, "profile_photo_path"):
        user.profile_photo_path = None
    if hasattr(user, "profile_photo_updated_at"):
        user.profile_photo_updated_at = utc_now()


def _safe_static_file_path(*, app_root_path: str | Path, relative_path: str) -> tuple[Path | None, str]:
    """Return a safe absolute path under app/static or a warning string.

    The legacy value stored on the user is expected to be relative to static.
    Suspicious paths are not deleted, but the model field can still be cleared.
    """
    clean_relative = (relative_path or "").strip().replace("\\", "/")
    if not clean_relative:
        return None, "empty_profile_photo_path"

    static_root = (Path(app_root_path) / "static").resolve()
    candidate = (static_root / clean_relative).resolve()

    try:
        candidate.relative_to(static_root)
    except ValueError:
        return None, "profile_photo_path_outside_static_root"

    return candidate, ""


def _delete_private_profile_photo_copy(relative_path: str) -> bool:
    """B2-F06: yeni profil fotoğrafları static dışındaki özel depoda durur."""
    if not has_app_context():
        return False
    located = locate_upload(Path(relative_path.replace("\\", "/")).name, (private_upload_path("profile_photos"),))
    if located is None:
        return False
    try:
        (located[0] / located[1]).unlink()
    except OSError:
        return False
    return True


def delete_personnel_profile_photo(
    user: Any,
    *,
    app_root_path: str | Path,
    logger: Any | None = None,
) -> PersonnelProfilePhotoResult:
    """Delete an existing profile photo file if it safely resolves under static.

    This function does not commit and does not rollback. It mutates the user photo
    fields exactly like the legacy route helper did.
    """
    relative_path = (getattr(user, "profile_photo_path", None) or "").strip()
    file_deleted = False
    warning = ""

    safe_path, warning = _safe_static_file_path(app_root_path=app_root_path, relative_path=relative_path)
    if safe_path and safe_path.is_file():
        try:
            safe_path.unlink()
            file_deleted = True
        except OSError as exc:
            # B2-F06: dosya yolu ve adı (OSError metni dahil) uyarıya/günlüğe yazılmaz.
            warning = f"profile_photo_delete_failed:{type(exc).__name__}"
            if logger is not None:
                logger.warning("Profil fotoğrafı silinemedi (%s).", type(exc).__name__)
    elif not warning and _delete_private_profile_photo_copy(relative_path):
        file_deleted = True
    elif not warning and safe_path:
        warning = "profile_photo_file_not_found"

    if warning == "profile_photo_path_outside_static_root" and logger is not None:
        logger.warning("Profil fotoğrafı yolu static dışı göründüğü için silinmedi.")

    _set_photo_fields_empty(user)
    return PersonnelProfilePhotoResult(
        phase="personnel_service_faz4",
        action="delete",
        db_commit=False,
        db_rollback=False,
        route_contract="preserved",
        file_deleted=file_deleted,
        warning=warning,
    )


def upload_personnel_profile_photo(
    user: Any,
    *,
    photo_file: Any,
    save_photo_func: PhotoSaver,
) -> PersonnelProfilePhotoResult:
    """Upload a profile photo through the existing security helper.

    The existing helper remains the source of truth for extension/filename/storage
    behavior. This service only centralizes the route decision.
    """
    if not photo_file or not getattr(photo_file, "filename", ""):
        return PersonnelProfilePhotoResult(
            phase="personnel_service_faz4",
            action="skip",
            db_commit=False,
            db_rollback=False,
            route_contract="preserved",
            skipped=True,
            warning="empty_photo_file",
        )

    save_photo_func(photo_file, user)
    return PersonnelProfilePhotoResult(
        phase="personnel_service_faz4",
        action="upload",
        db_commit=False,
        db_rollback=False,
        route_contract="preserved",
        file_uploaded=True,
    )


def apply_personnel_profile_photo_action(
    user: Any,
    *,
    photo_file: Any | None = None,
    remove_photo: bool = False,
    app_root_path: str | Path,
    logger: Any | None = None,
    save_photo_func: PhotoSaver,
) -> PersonnelProfilePhotoResult:
    """Apply the profile photo form action without committing.

    Priority stays compatible with the legacy route: explicit remove wins over a
    newly uploaded file; otherwise a non-empty upload is saved; otherwise no-op.
    """
    if remove_photo:
        return delete_personnel_profile_photo(user, app_root_path=app_root_path, logger=logger)
    if photo_file and getattr(photo_file, "filename", ""):
        return upload_personnel_profile_photo(user, photo_file=photo_file, save_photo_func=save_photo_func)
    return PersonnelProfilePhotoResult(
        phase="personnel_service_faz4",
        action="skip",
        db_commit=False,
        db_rollback=False,
        route_contract="preserved",
        skipped=True,
        warning="no_profile_photo_action",
    )


def build_personnel_profile_photo_phase4_summary(*, action: str = "summary") -> dict[str, Any]:
    return PersonnelProfilePhotoResult(
        phase="personnel_service_faz4",
        action=action,
        db_commit=False,
        db_rollback=False,
        route_contract="preserved",
        skipped=True,
    ).to_dict()
