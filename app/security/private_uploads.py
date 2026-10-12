"""B2-F06: static klasörü dışında özel yükleme deposu ve ``/static`` koruması.

Kişisel veya kurumsal dosyalar (mesaj ekleri, destek talebi ekleri, portal
medyası, İK belgeleri, kurumsal yayınlar, profil fotoğrafları) yeni kayıtlarda
``PRIVATE_UPLOAD_FOLDER`` altında, uygulamanın static klasörünün dışında saklanır
ve yalnızca nesne bazlı yetki kontrolü yapan route'lardan sunulur.

Bu değişiklikten önce ``app/static/uploads`` altına (veya static içindeki bir
``UPLOAD_FOLDER`` altına) yazılmış eski dosyalar yerinde kalır; route'lar onları
okumaya devam eder (geri dönüş konumu), fakat Flask'ın ``static`` endpoint'i bu
alt ağaçlara yapılan doğrudan istekleri 404 ile yanıtlar. Önde /static'i doğrudan
sunan bir web sunucusu varsa bu koruma onu kapsamaz; eski dosyaların static
dışına taşınması operasyon adımıdır.
"""

from __future__ import annotations

import os
import posixpath
import stat
from collections.abc import Iterable
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, abort, current_app
from werkzeug.security import safe_join

# app/static/uploads altındaki her alt klasör kullanıcı yüklemesidir; kamuya açık
# tasarım varlıkları (css, js, img, pwa, templates) bu ağacın dışında durur.
PRIVATE_STATIC_TOP_LEVEL = "uploads"
PRIVATE_UPLOAD_DEFAULT_DIRNAME = "private_uploads"
_GUARD_EXTENSION_KEY = "bys360_private_static_guard"


class PrivateUploadError(RuntimeError):
    """Only a fixed diagnostic code; never retain an OS error or a storage path."""


def public_upload_roots() -> tuple[Path, ...]:
    configured = current_app.config.get("PUBLIC_UPLOAD_ROOTS", ())
    if isinstance(configured, str):
        configured = configured.split(os.pathsep)
    return (static_root(), *(Path(str(p)).expanduser() for p in configured if str(p).strip()))


def _normalized_segments(filename: str) -> list[str]:
    """Windows dosya sistemi eşdeğerliğini de hesaba katan küçük harfli yol parçaları.

    ``\\`` ayırıcıları, ``.``/``..`` parçaları, sondaki nokta/boşluklar ve NTFS akış
    sonekleri (``name::$DATA``) Windows'ta aynı klasöre çözüldüğü için temizlenir.
    """
    raw = str(filename or "").replace("\\", "/")
    normalized = posixpath.normpath("/" + raw)
    segments: list[str] = []
    for segment in normalized.split("/"):
        cleaned = segment.split(":", 1)[0].rstrip(" .").lower()
        if cleaned:
            segments.append(cleaned)
    return segments


def _real(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _is_within(path: str | Path, root: str | Path) -> bool:
    target = _real(path)
    base = _real(root)
    return target == base or target.startswith(base.rstrip(os.sep) + os.sep)


def _configured_upload_folder_in_static(upload_folder: str | None, static_folder: str) -> str | None:
    """Legacy root overlapping static; equality/ancestors block all static files."""
    configured = str(upload_folder or "").strip()
    if not configured:
        return None
    if not (_is_within(configured, static_folder) or _is_within(static_folder, configured)):
        return None
    return configured


def is_private_static_path(
    filename: str,
    static_folder: str | None,
    upload_folder: str | None = None,
) -> bool:
    """``/static/<filename>`` isteği özel yükleme ağacına mı gidiyor?

    Hem sözcüksel (normalize edilmiş ilk parça ``uploads``) hem de dosya sistemi
    (Flask'ın sunacağı gerçek yol ``static/uploads`` veya static içindeki bir
    ``UPLOAD_FOLDER`` altında; büyük/küçük harf ve Windows kısa adları dahil)
    kontrol edilir.
    """
    segments = _normalized_segments(filename)
    if segments and segments[0] == PRIVATE_STATIC_TOP_LEVEL:
        return True
    if not static_folder:
        return False
    joined = safe_join(static_folder, str(filename or ""))
    if joined is None:
        return False
    private_roots = [os.path.join(static_folder, PRIVATE_STATIC_TOP_LEVEL)]
    configured = _configured_upload_folder_in_static(upload_folder, static_folder)
    if configured is not None:
        private_roots.append(configured)
    return any(_is_within(joined, root) for root in private_roots)


def install_private_static_guard(app: Flask) -> None:
    """Flask ``static`` görünümünü özel yükleme alt yollarında 404 dönecek şekilde sarar."""
    with app.app_context():
        private_upload_root()  # Validate declared public aliases before starting.
    view = app.view_functions.get("static")
    if view is None or app.extensions.get(_GUARD_EXTENSION_KEY):
        return

    @wraps(view)
    def guarded_static(*args: Any, **kwargs: Any) -> Any:
        filename = str(kwargs.get("filename") or "")
        if "\x00" in filename:
            abort(404)  # Plain Flask answers 404; never a 500 with a traceback.
        try:
            private = is_private_static_path(filename, app.static_folder, app.config.get("UPLOAD_FOLDER"))
        except (OSError, ValueError):
            abort(404)  # An unresolvable path is refused, never served.
        if private:
            abort(404)
        return view(*args, **kwargs)

    app.view_functions["static"] = guarded_static
    app.extensions[_GUARD_EXTENSION_KEY] = True


def static_root() -> Path:
    folder = current_app.static_folder or os.path.join(current_app.root_path, "static")
    return Path(folder)


def _reject_reparse(path: Path) -> None:
    """Check lexical ancestors before resolution hides a symlink or junction."""
    try:
        for ancestor in (path, *path.parents):
            try:
                info = ancestor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) or 0) & 0x400:
                raise PrivateUploadError("PRIVATE_UPLOAD_REPARSE_POINT")
    except OSError:
        raise PrivateUploadError("PRIVATE_UPLOAD_PATH_CHECK_FAILED") from None


def _resolved_private_path(path: Path) -> Path:
    if not path.is_absolute():
        raise PrivateUploadError("PRIVATE_UPLOAD_ABSOLUTE_ROOT_REQUIRED")
    _reject_reparse(path)
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        raise PrivateUploadError("PRIVATE_UPLOAD_PATH_CHECK_FAILED") from None


def _canonical_public_roots() -> tuple[Path, ...]:
    roots = public_upload_roots()
    if any(not root.is_absolute() for root in roots):
        raise PrivateUploadError("PRIVATE_UPLOAD_ABSOLUTE_ROOT_REQUIRED")
    try:
        return tuple(root.resolve() for root in roots)
    except (OSError, RuntimeError):
        raise PrivateUploadError("PRIVATE_UPLOAD_PATH_CHECK_FAILED") from None


def _overlaps_public(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_is_within(path, root) or _is_within(root, path) for root in roots)


def private_upload_root() -> Path:
    """``PRIVATE_UPLOAD_FOLDER``; boşsa veya static içine işaret ediyorsa instance altındaki varsayılan."""
    default = Path(current_app.instance_path) / PRIVATE_UPLOAD_DEFAULT_DIRNAME
    configured = str(
        current_app.config.get("PRIVATE_UPLOAD_FOLDER") or os.getenv("PRIVATE_UPLOAD_FOLDER") or ""
    ).strip()
    public_roots = _canonical_public_roots()
    root = _resolved_private_path(Path(configured).expanduser() if configured else default)
    if _overlaps_public(root, public_roots):
        current_app.logger.warning("PRIVATE_UPLOAD_SAFE_FALLBACK_REQUIRED")
        root = _resolved_private_path(default)
    if _overlaps_public(root, public_roots):
        raise PrivateUploadError("PRIVATE_UPLOAD_PUBLIC_ROOT")
    legacy = str(current_app.config.get("UPLOAD_FOLDER") or "").strip()
    if legacy and any(
        _is_within(legacy, public) or _is_within(public, legacy)
        for public in public_roots[1:]
    ):
        raise PrivateUploadError("PRIVATE_UPLOAD_LEGACY_PUBLIC_ROOT")
    return root


def private_upload_path(*parts: str) -> Path:
    """Okuma için özel depo yolu; klasör oluşturmaz."""
    root = private_upload_root()
    target = _resolved_private_path(root.joinpath(*parts))
    if not _is_within(target, root):
        raise PrivateUploadError("PRIVATE_UPLOAD_PATH_ESCAPE")
    return target


def private_upload_dir(*parts: str) -> Path:
    """Yazma için özel depo klasörü; klasörü yalnızca burada oluşturur."""
    target = private_upload_path(*parts)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise PrivateUploadError("PRIVATE_UPLOAD_WRITE_FAILED") from None
    # Validate again after creation, before returning a writable directory.
    return private_upload_path(*parts)


def store_private_upload(file_storage: Any, target: str | Path) -> None:
    """Prevent storage errors and their chains from reaching outer handler logs."""
    try:
        path = _resolved_private_path(Path(target))
        root = private_upload_root()
        if not _is_within(path, root) or _overlaps_public(path, _canonical_public_roots()):
            raise PrivateUploadError("PRIVATE_UPLOAD_PATH_ESCAPE")
        file_storage.save(path)
    except PrivateUploadError:
        raise
    except (OSError, RuntimeError, ValueError):
        # Disk, permission, reparse/loop and malformed-path errors; the chain is dropped so no
        # path or file name reaches a handler log.
        raise PrivateUploadError("PRIVATE_UPLOAD_WRITE_FAILED") from None


def legacy_static_upload_path(*parts: str) -> Path:
    """Bu değişiklikten önce yazılmış dosyaların static altındaki eski konumu (yalnızca okuma)."""
    return static_root().joinpath(PRIVATE_STATIC_TOP_LEVEL, *parts)


def locate_upload(filename: str, directories: Iterable[str | Path]) -> tuple[Path, str] | None:
    """Dosyayı sırayla verilen klasörlerde arar; bulunduğu klasörü ve güvenli adı döndürür."""
    name = str(filename or "").strip()
    if not name:
        return None
    for directory in directories:
        candidate = safe_join(str(directory), name)
        if candidate is not None:
            try:
                base = _resolved_private_path(Path(directory).absolute())
                target = _resolved_private_path(Path(candidate).absolute())
                if _is_within(target, base) and target.is_file():
                    return base, name
            except (OSError, PrivateUploadError):
                continue
    return None


__all__ = [
    "PRIVATE_STATIC_TOP_LEVEL",
    "install_private_static_guard",
    "is_private_static_path",
    "legacy_static_upload_path",
    "locate_upload",
    "private_upload_dir",
    "private_upload_path",
    "private_upload_root",
    "static_root",
]
