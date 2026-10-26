from __future__ import annotations

# BYS360_MAINTENANCE_ROADMAP_PHASE2_SECURITY_HARDENING_V1
import os
import re
import secrets
import zipfile
from pathlib import Path
from typing import IO

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

_MAGIC_SIGNATURES = [
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),  # docx/xlsx/pptx kapsayicisi
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
]

_DANGEROUS_EXTENSIONS = {
    "exe", "msi", "bat", "cmd", "ps1", "psm1", "sh", "com", "scr", "jar", "hta", "vbs", "js", "dll",
    "php", "asp", "aspx", "jsp", "py", "rb", "pl", "cgi", "reg", "lnk", "iso",
}

_ALLOWED_MIME_BY_EXTENSION = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "gif": {"image/gif"},
    "webp": {"image/webp"},
    "docx": {"application/zip", "application/octet-stream"},
    "xlsx": {"application/zip", "application/octet-stream"},
    "pptx": {"application/zip", "application/octet-stream"},
    "zip": {"application/zip", "application/octet-stream"},
    "csv": {"application/octet-stream", "text/plain", "text/csv"},
    "txt": {"application/octet-stream", "text/plain"},
}

_OOXML_REQUIRED_ROOT = {
    "docx": "word/",
    "xlsx": "xl/",
    "pptx": "ppt/",
}

_SUSPICIOUS_NAME_PATTERNS = [
    r"\.\.",
    r"[/\\]",
    r"\x00",
    r"\s{2,}",
]


class UploadValidationError(ValueError):
    pass


def _allowed_extensions() -> set[str]:
    raw = current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", "")
    if isinstance(raw, str):
        return {x.strip().lower().lstrip('.') for x in raw.split(",") if x.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(x).strip().lower().lstrip('.') for x in raw if str(x).strip()}
    return set()


def _max_size(max_size: int | None = None) -> int:
    # The upload request limit, not MAX_CONTENT_LENGTH (the smaller default for other requests, #105).
    config = current_app.config
    return int(max_size or config.get("UPLOAD_MAX_CONTENT_LENGTH") or config.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))


def _max_filename_length() -> int:
    try:
        return int(current_app.config.get("UPLOAD_MAX_FILENAME_LENGTH", 180) or 180)
    except (TypeError, ValueError):
        return 180


def sanitize_original_filename(original_name: str) -> str:
    raw = (original_name or "").strip()
    if not raw:
        raise UploadValidationError("Geçerli bir dosya adı bulunamadı.")
    if len(raw) > _max_filename_length():
        raise UploadValidationError("Dosya adı izin verilen uzunluğu aşıyor.")

    lowered = raw.lower()
    for pattern in _SUSPICIOUS_NAME_PATTERNS:
        if re.search(pattern, lowered):
            raise UploadValidationError("Dosya adı güvenlik nedeniyle kabul edilmedi.")

    cleaned = secure_filename(raw)
    if not cleaned:
        raise UploadValidationError("Dosya adı güvenli bir biçime dönüştürülemedi.")

    parts = [p for p in cleaned.lower().split('.') if p]
    if len(parts) >= 2 and any(part in _DANGEROUS_EXTENSIONS for part in parts[:-1]):
        raise UploadValidationError("Çift uzantılı veya riskli dosya adı kabul edilmedi.")

    ext = Path(cleaned).suffix.lower().lstrip('.')
    if ext in _DANGEROUS_EXTENSIONS:
        raise UploadValidationError(f"Riskli dosya uzantısı kabul edilmedi: .{ext}")

    return cleaned


def safe_store_filename(original_name: str) -> str:
    safe_name = sanitize_original_filename(original_name)
    suffix = Path(safe_name).suffix.lower()
    token = secrets.token_hex(16)
    return f"{token}{suffix}"


def detect_mime_from_stream(stream: IO[bytes]) -> str:
    pos = stream.tell()
    head = stream.read(32)
    stream.seek(pos)

    for signature, mime in _MAGIC_SIGNATURES:
        if head.startswith(signature):
            return mime

    return "application/octet-stream"


def _is_extension_allowed(extension: str, allowed_extensions: set[str]) -> bool:
    if extension in _DANGEROUS_EXTENSIONS:
        return False
    if not allowed_extensions:
        return extension in _ALLOWED_MIME_BY_EXTENSION
    return extension in allowed_extensions


def _archive_names(stream: IO[bytes]) -> list[str]:
    pos = stream.tell()
    try:
        with zipfile.ZipFile(stream) as archive:
            return archive.namelist()
    finally:
        stream.seek(pos)


def _validate_archive_container(stream: IO[bytes], extension: str) -> None:
    if extension not in {"zip", "docx", "xlsx", "pptx"}:
        return

    try:
        names = _archive_names(stream)
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("Sıkıştırılmış dosya yapısı geçerli değil.") from exc

    if not names:
        raise UploadValidationError("Sıkıştırılmış dosya boş görünüyor.")
    if len(names) > 2500:
        raise UploadValidationError("Sıkıştırılmış dosya içinde çok fazla kayıt var.")

    lowered_names = [name.replace("\\", "/").lower() for name in names]
    for name in lowered_names:
        if name.startswith("/") or "../" in name or name.startswith("../"):
            raise UploadValidationError("Dosya içeriğinde güvenli olmayan yol bilgisi bulundu.")
        suffix = Path(name).suffix.lower().lstrip('.')
        if suffix in _DANGEROUS_EXTENSIONS:
            raise UploadValidationError("Dosya içeriğinde riskli uzantı bulundu.")

    if extension in _OOXML_REQUIRED_ROOT:
        required_root = _OOXML_REQUIRED_ROOT[extension]
        if "[content_types].xml" not in lowered_names or not any(name.startswith(required_root) for name in lowered_names):
            raise UploadValidationError("Office dosyasının iç yapısı beklenen türle uyumlu değil.")


def validate_upload(file: FileStorage, allowed_extensions: set[str] | None = None, max_size: int | None = None) -> dict:
    if not file or not file.filename:
        raise UploadValidationError("Yüklenecek dosya bulunamadı.")

    filename = sanitize_original_filename(file.filename)
    extension = Path(filename).suffix.lower().lstrip('.')
    allowed = {x.lower().lstrip('.') for x in (allowed_extensions or _allowed_extensions())}

    if not _is_extension_allowed(extension, allowed):
        raise UploadValidationError(f"İzin verilmeyen dosya uzantısı: .{extension}")

    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)

    max_len = _max_size(max_size)
    if size <= 0:
        raise UploadValidationError("Boş dosya yüklenemez.")
    if size > max_len:
        raise UploadValidationError("Dosya boyutu izin verilen sınırı aşıyor.")

    detected = detect_mime_from_stream(file.stream)
    accepted_mimes = _ALLOWED_MIME_BY_EXTENSION.get(extension, {"application/octet-stream"})

    if detected not in accepted_mimes and not (
        detected == "application/octet-stream" and extension in {"csv", "txt"}
    ):
        raise UploadValidationError("Dosya içeriği beklenen tür ile uyuşmuyor.")

    _validate_archive_container(file.stream, extension)

    return {
        "original_filename": filename,
        "extension": extension,
        "size": size,
        "detected_mime": detected,
        "max_allowed_size": max_len,
    }
