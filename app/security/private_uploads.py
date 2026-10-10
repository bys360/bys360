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
    """Static içinde (ama static'in kendisi değil) duran bir ``UPLOAD_FOLDER``; yoksa ``None``."""
    configured = str(upload_folder or "").strip()
    if not configured:
        return None
    if _real(configured) == _real(static_folder) or not _is_within(configured, static_folder):
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
    view = app.view_functions.get("static")
    if view is None or app.extensions.get(_GUARD_EXTENSION_KEY):
        return

    @wraps(view)
    def guarded_static(*args: Any, **kwargs: Any) -> Any:
        if is_private_static_path(
            str(kwargs.get("filename") or ""),
            app.static_folder,
            app.config.get("UPLOAD_FOLDER"),
        ):
            abort(404)
        return view(*args, **kwargs)

    app.view_functions["static"] = guarded_static
    app.extensions[_GUARD_EXTENSION_KEY] = True


def static_root() -> Path:
    folder = current_app.static_folder or os.path.join(current_app.root_path, "static")
    return Path(folder)


def private_upload_root() -> Path:
    """``PRIVATE_UPLOAD_FOLDER``; boşsa veya static içine işaret ediyorsa instance altındaki varsayılan."""
    default = Path(current_app.instance_path) / PRIVATE_UPLOAD_DEFAULT_DIRNAME
    configured = str(
        current_app.config.get("PRIVATE_UPLOAD_FOLDER") or os.getenv("PRIVATE_UPLOAD_FOLDER") or ""
    ).strip()
    root = Path(configured).expanduser() if configured else default
    if _is_within(root, static_root()):
        current_app.logger.warning(
            "PRIVATE_UPLOAD_FOLDER static klasörünün içinde; özel yüklemeler için varsayılan instance kökü kullanılıyor."
        )
        root = default
    return root


def private_upload_path(*parts: str) -> Path:
    """Okuma için özel depo yolu; klasör oluşturmaz."""
    return private_upload_root().joinpath(*parts)


def private_upload_dir(*parts: str) -> Path:
    """Yazma için özel depo klasörü; klasörü yalnızca burada oluşturur."""
    target = private_upload_path(*parts)
    target.mkdir(parents=True, exist_ok=True)
    return target


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
        if candidate is not None and os.path.isfile(candidate):
            return Path(directory), name
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
