"""BYS360 Dosya Merkezi servisleri.

Dosya metadata, güvenli yükleme, misafir indirme/yükleme bağlantıları,
transfer paketleri ve denetim kayıtları için kullanılır.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shlex
import shutil
import subprocess
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from secrets import token_urlsafe

from flask import current_app, request
from flask_login import current_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models.file_center_models import (
    FileAccessLog,
    FileAuditLog,
    FileDownloadLog,
    FileQuotaPolicy,
    FileQuotaUsage,
    FileRequest,
    FileRequestUpload,
    FileSecurityScan,
    FileShareLink,
    FileStorageItem,
    FileTransfer,
    FileTransferItem,
    FileTransferRecipient,
    FileUploadChunk,
    FileUploadSession,
)

logger = logging.getLogger(__name__)

BLOCKED_DEFAULT = ".exe,.bat,.cmd,.ps1,.vbs,.scr,.dll,.msi,.js,.jar,.com,.pif"


# BYS360_FILE_CENTER_LIVE_HARDENING_V1L_BEGIN
def clamav_enabled() -> bool:
    return _db_bool("clamav_enabled", "FILE_CENTER_CLAMAV_ENABLED", False)


def clamav_command() -> str:
    return _db_str("clamav_command", "FILE_CENTER_CLAMAV_COMMAND", "clamscan --no-summary --infected")


def clamav_timeout_seconds() -> int:
    return max(5, _db_int("clamav_timeout_seconds", "FILE_CENTER_CLAMAV_TIMEOUT_SECONDS", 60))


def _run_clamav_scan(path: Path) -> tuple[str, str]:
    """Run clamscan/clamdscan when explicitly enabled.

    Return statuses: clean, infected, failed. Dependency-free on purpose; canlıda
    FILE_CENTER_CLAMAV_COMMAND ile `clamdscan --fdpass --no-summary` gibi bir
    komut verilebilir.
    """
    command = clamav_command().strip()
    if not command:
        return "failed", "ClamAV komutu tanımlı değil."
    args = shlex.split(command) + [str(path)]
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=clamav_timeout_seconds(),
            check=False,
        )
    except FileNotFoundError:
        return "failed", "ClamAV komutu sunucuda bulunamadı."
    except subprocess.TimeoutExpired:
        return "failed", "ClamAV taraması zaman aşımına uğradı."
    output = " ".join(x.strip() for x in [completed.stdout, completed.stderr] if x and x.strip())
    if completed.returncode == 0:
        return "clean", "ClamAV taraması temiz sonuçlandı."
    if completed.returncode == 1:
        return "infected", output or "ClamAV dosyada riskli içerik tespit etti."
    return "failed", output or f"ClamAV taraması tamamlanamadı. Kod: {completed.returncode}"
# BYS360_FILE_CENTER_LIVE_HARDENING_V1L_END


def _db_bool(key: str, env_key: str, default: bool = False) -> bool:
    try:
        from app.file_center.settings_service import get_bool_setting
        return get_bool_setting(key, env_bool(env_key, default))
    except Exception:
        return env_bool(env_key, default)


def _db_str(key: str, env_key: str, default: str = "") -> str:
    try:
        from app.file_center.settings_service import get_str_setting
        return get_str_setting(key, os.getenv(env_key) or str(current_app.config.get(env_key, default) or default))
    except Exception:
        return os.getenv(env_key) or str(current_app.config.get(env_key, default) or default)


def _db_int(key: str, env_key: str, default: int = 0) -> int:
    try:
        from app.file_center.settings_service import get_int_setting
        return get_int_setting(key, int(os.getenv(env_key) or current_app.config.get(env_key, default) or default))
    except Exception:
        return int(os.getenv(env_key) or current_app.config.get(env_key, default) or default)


def _db_float(key: str, env_key: str, default: float = 0.0) -> float:
    try:
        from app.file_center.settings_service import get_float_setting
        return get_float_setting(key, float(os.getenv(env_key) or current_app.config.get(env_key, default) or default))
    except Exception:
        return float(os.getenv(env_key) or current_app.config.get(env_key, default) or default)


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        value = str(current_app.config.get(key, ""))
    if value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "evet", "on", "açık", "acik"}


def file_center_enabled() -> bool:
    return _db_bool("file_center_enabled", "FILE_CENTER_ENABLED", False)


def guest_links_enabled() -> bool:
    return _db_bool("guest_links_enabled", "FILE_CENTER_GUEST_LINKS_ENABLED", False)


def guest_uploads_enabled() -> bool:
    return _db_bool("guest_uploads_enabled", "FILE_CENTER_GUEST_UPLOADS_ENABLED", True)


def _default_storage_root() -> Path:
    """Return a portable local fallback without hard-coding a Windows drive."""
    # Canlı ortamda FILE_CENTER_STORAGE_ROOT mutlaka verilmelidir. Yerel geliştirme
    # için instance klasörünün altında güvenli ve proje dışı bir alan kullanılır.
    instance_path = Path(getattr(current_app, "instance_path", "instance") or "instance")
    return instance_path / "file_center_storage"


def storage_root() -> Path:
    configured = os.getenv("FILE_CENTER_STORAGE_ROOT") or current_app.config.get("FILE_CENTER_STORAGE_ROOT")
    env_name = (os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or str(current_app.config.get("ENV", "")) or "").strip().lower()
    is_production = env_name in {"production", "prod", "canli", "live"} or bool(current_app.config.get("BYS360_PRODUCTION"))
    if not configured and is_production:
        raise RuntimeError("FILE_CENTER_STORAGE_ROOT canlı ortamda zorunludur.")
    path = Path(str(configured or _default_storage_root())).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    for child in ["uploads", "deleted", "quarantine", "temp"]:
        (path / child).mkdir(parents=True, exist_ok=True)
    return path


def upload_root_for_user(user_id: int) -> Path:
    root = storage_root() / "uploads" / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def blocked_extensions() -> set[str]:
    raw = _db_str("blocked_extensions", "FILE_CENTER_BLOCKED_EXTENSIONS", BLOCKED_DEFAULT) or BLOCKED_DEFAULT
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def max_file_bytes() -> int:
    gb = _db_float("max_file_gb", "FILE_CENTER_MAX_FILE_GB", 5.0)
    return int(gb * 1024 * 1024 * 1024)


def max_transfer_bytes() -> int:
    gb = _db_float("max_transfer_gb", "FILE_CENTER_MAX_TRANSFER_GB", 20.0)
    return int(gb * 1024 * 1024 * 1024)


def default_expiry_days() -> int:
    return _db_int("default_expiry_days", "FILE_CENTER_GUEST_DEFAULT_EXPIRES_DAYS", 7)


def default_download_limit() -> int:
    return _db_int("default_download_limit", "FILE_CENTER_DEFAULT_DOWNLOAD_LIMIT", 5)


# BYS360 DEFECT AQ: bu kümeler önceden "in" alt dize eşleştirmesi ile
# kullanılıyordu ("admin" in role, "yönetici" in label) -- ör. role_label
# "İnsan Kaynakları Yöneticisi" (sıradan bir birim yöneticisi, admin değil)
# "yönetici" alt dizesini içerdiği için Dosya Merkezi'nde tam admin yetkisi
# kazanıyordu. Artık role/role_label alanlarının KENDİSİ bu kümelerle TAM
# eşleştirilir; orijinal jetonlar (aynı anlamda) korunur, yalnızca
# eşleştirme yöntemi değişir.
#
# BYS360 DEFECT AR: AQ'nun exact-match duzeltmesi bu dosyadaki kopyayi
# duzeltti, ama permissions.py'deki KANONIK, DB rol-matrisi farkindaki
# tanimla uzlastirmadi -- orada "yonetici" (sirada bir birim yoneticisi)
# ADMIN_ROLE_HINTS'te DEGIL, ayri ve daha dusuk yetkili MANAGER_HINTS'te
# yer alir (permissions.is_file_center_manager, is_file_center_admin degil).
# Bu iki bagimsiz tanim arasindaki farkli, tam admin-esdegeri "Yonetici"
# rol_label'ina sahip herhangi bir kullanicinin baskasinin ozel dosyalarini
# indirip/silip misafir paylasim linki olusturabilmesine ve organizasyon
# capinda kota panosunu gorebilmesine izin veriyordu -- kanonik rol
# matrisinin ayni role verdiginden daha fazlasi. Artik dogrudan kanonik
# kaynaga yonlendirilir; DB rol-matrisi tablosu hazir degilse
# is_file_center_admin kendi guvenli varsayilanina (_admin_like_text,
# ayni ADMIN_ROLE_HINTS) duser.
def is_admin_like(user) -> bool:
    from app.file_center.permissions import is_file_center_admin

    return is_file_center_admin(user)


def format_bytes(size: int | None) -> str:
    value = float(size or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.1f} {units[idx]}"


def scan_label(status: str | None) -> str:
    mapping = {
        "pending": "Güvenlik taraması bekliyor",
        "clean": "Güvenli",
        "ready": "Hazır",
        "blocked": "Engellendi",
        "failed": "Tarama başarısız",
    }
    return mapping.get(str(status or "").lower(), "Kontrol bekliyor")


def download_status_label(status: str | None) -> str:
    mapping = {
        "success": "Başarılı",
        "wrong_password": "Şifre hatalı",
        "blocked_by_security": "Güvenlik tarafından engellendi",
    }
    return mapping.get(str(status or "").lower(), "Bilinmiyor")


def link_status_label(link: FileShareLink) -> str:
    if not link.is_active:
        return "İptal edildi"
    if link.download_count >= link.max_downloads:
        return "İndirme limiti doldu"
    if link.expires_at < utc_now():
        return "Süresi doldu"
    return "Aktif"


def request_status_label(row: FileRequest) -> str:
    if row.status == "closed":
        return "Kapatıldı"
    if row.status == "revoked":
        return "İptal edildi"
    if row.expires_at < utc_now():
        return "Süresi doldu"
    if row.upload_count > 0:
        return "Yüklendi"
    return "Bekliyor"


def _request_meta() -> tuple[str | None, str | None]:
    return request.headers.get("X-Forwarded-For", request.remote_addr), request.headers.get("User-Agent")


def log_audit(action: str, *, file_id: int | None = None, message: str | None = None, actor_user_id: int | None = None) -> None:
    ip, ua = _request_meta()
    actor_id = actor_user_id
    if actor_id is None and getattr(current_user, "is_authenticated", False):
        actor_id = int(current_user.id)
    db.session.add(FileAuditLog(actor_user_id=actor_id, file_id=file_id, action=action, message=message, ip_address=ip, user_agent=ua))


def log_access(action: str, *, file_id: int | None = None, detail: str | None = None, actor_user_id: int | None = None) -> None:
    ip, ua = _request_meta()
    actor_id = actor_user_id
    if actor_id is None and getattr(current_user, "is_authenticated", False):
        actor_id = int(current_user.id)
    db.session.add(FileAccessLog(file_id=file_id, actor_user_id=actor_id, action=action, detail=detail, ip_address=ip, user_agent=ua))


def update_quota_for_user(user_id: int) -> None:
    total = db.session.query(db.func.coalesce(db.func.sum(FileStorageItem.size_bytes), 0)).filter(
        FileStorageItem.owner_user_id == user_id,
        FileStorageItem.is_deleted.is_(False),
    ).scalar() or 0
    count = FileStorageItem.query.filter_by(owner_user_id=user_id, is_deleted=False).count()
    row = FileQuotaUsage.query.filter_by(user_id=user_id).one_or_none()
    if row is None:
        row = FileQuotaUsage(user_id=user_id)
        db.session.add(row)
    row.used_bytes = int(total)
    row.file_count = int(count)


def _extension_allowed_for_request(ext: str, allowed_extensions: str | None) -> bool:
    if not allowed_extensions:
        return True
    allowed = {x.strip().lower() for x in allowed_extensions.replace(";", ",").split(",") if x.strip()}
    if not allowed:
        return True
    normalized = ext.lower()
    if normalized and not normalized.startswith("."):
        normalized = "." + normalized
    return normalized in allowed or normalized.lstrip(".") in allowed


def validate_upload_request(file_storage, *, max_bytes: int | None = None, allowed_extensions: str | None = None) -> tuple[bool, str]:
    if not file_storage or not file_storage.filename:
        return False, "Dosya seçilmedi."
    original = file_storage.filename
    ext = Path(original).suffix.lower()
    if ext in blocked_extensions():
        return False, f"Bu dosya türü güvenlik nedeniyle yüklenemez: {ext}"
    global_allowed = allowed_extensions_global() if 'allowed_extensions_global' in globals() else set()
    if global_allowed and ext not in global_allowed:
        return False, f"Bu dosya türü kurumsal izin listesinde değil: {ext or 'uzantısız dosya'}"
    if not _extension_allowed_for_request(ext, allowed_extensions):
        return False, f"Bu dosya türü bu talep için kabul edilmiyor: {ext or 'uzantısız dosya'}"
    limit = max_bytes or max_file_bytes()
    content_length = request.content_length or 0
    if content_length and content_length > limit:
        return False, "Dosya boyutu izin verilen sınırı aşıyor."
    return True, "OK"


def save_uploaded_file(file_storage, owner_user_id: int, *, max_bytes: int | None = None) -> FileStorageItem:
    original_name = file_storage.filename or "dosya"
    safe_original = secure_filename(original_name) or "dosya"
    ext = Path(safe_original).suffix.lower()
    stored_name = f"{utc_now().strftime('%Y%m%d_%H%M%S')}_{token_urlsafe(12)}{ext}"
    target_dir = upload_root_for_user(owner_user_id)
    target_path = (target_dir / stored_name).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    limit = max_bytes or max_file_bytes()
    estimated_upload_size = int(getattr(file_storage, "content_length", 0) or request.content_length or 0)
    quota_ok, quota_message = check_user_quota_for_upload(owner_user_id, estimated_bytes=estimated_upload_size)
    if not quota_ok:
        raise ValueError(quota_message)
    sha = hashlib.sha256()
    size = 0
    with open(target_path, "wb") as out:
        while True:
            chunk = file_storage.stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                out.close()
                try:
                    target_path.unlink(missing_ok=True)
                except TypeError:
                    if target_path.exists():
                        target_path.unlink()
                raise ValueError("Dosya boyutu izin verilen sınırı aşıyor.")
            sha.update(chunk)
            out.write(chunk)

    item = FileStorageItem(
        owner_user_id=owner_user_id,
        original_filename=original_name,
        stored_filename=stored_name,
        storage_path=str(target_path),
        content_type=file_storage.mimetype,
        extension=ext,
        size_bytes=size,
        sha256_hash=sha.hexdigest(),
        status="ready",
        scan_status="pending",
    )
    db.session.add(item)
    db.session.flush()
    db.session.add(FileSecurityScan(file_id=item.id, status="pending", scanner="file_center_queue", result_message="Güvenlik taraması için kuyruğa alındı."))
    log_audit("file_uploaded", file_id=item.id, message=f"Dosya yüklendi: {original_name}", actor_user_id=owner_user_id)
    update_quota_for_user(owner_user_id)
    return item


def secure_file_path(item: FileStorageItem) -> Path:
    root = storage_root()
    candidate = Path(item.storage_path).resolve()
    candidate.relative_to(root)
    if not candidate.is_file():
        raise FileNotFoundError("Dosya fiziksel depoda bulunamadı.")
    return candidate


# -----------------------------------------------------------------------------
# V1H Güvenlik taraması, dosya türü denetimi ve karantina servisleri
# -----------------------------------------------------------------------------
RISK_MARKERS = {
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".dll", ".msi", ".js", ".jar", ".com", ".pif", ".hta", ".reg"
}
SUSPICIOUS_MIME_PREFIXES = (
    "application/x-msdownload",
    "application/x-dosexec",
    "application/x-msdos-program",
    "application/x-sh",
)


def security_scan_enabled() -> bool:
    return _db_bool("security_scan_enabled", "FILE_CENTER_SECURITY_SCAN_ENABLED", True)


def auto_scan_on_upload_enabled() -> bool:
    return _db_bool("auto_scan_on_upload_enabled", "FILE_CENTER_AUTO_SCAN_ON_UPLOAD", True)


def quarantine_enabled() -> bool:
    return _db_bool("quarantine_enabled", "FILE_CENTER_QUARANTINE_ENABLED", True)


def require_clean_before_download() -> bool:
    return _db_bool("require_clean_before_download", "FILE_CENTER_REQUIRE_CLEAN_BEFORE_DOWNLOAD", True)


def allowed_extensions_global() -> set[str]:
    raw = _db_str("allowed_extensions", "FILE_CENTER_ALLOWED_EXTENSIONS", "") or ""
    values = {x.strip().lower() for x in raw.replace(";", ",").split(",") if x.strip()}
    normalized = set()
    for value in values:
        normalized.add(value if value.startswith(".") else f".{value}")
    return normalized


def file_security_status_label(status: str | None) -> str:
    mapping = {
        "pending": "Güvenlik taraması bekliyor",
        "clean": "Güvenli",
        "ready": "Hazır",
        "quarantined": "Karantinada",
        "blocked": "Engellendi",
        "failed": "Tarama başarısız",
        "review": "İnceleme gerekli",
    }
    return mapping.get(str(status or "").lower(), "Kontrol bekliyor")


def _has_double_extension_risk(filename: str | None) -> bool:
    name = f".{(filename or '').lower().strip('.')}"
    return any(f"{marker}." in name for marker in RISK_MARKERS)


def _global_extension_allowed(ext: str | None) -> tuple[bool, str | None]:
    normalized = (ext or "").lower()
    if normalized and not normalized.startswith("."):
        normalized = f".{normalized}"
    if normalized in blocked_extensions():
        return False, f"Riskli dosya uzantısı engellendi: {normalized or 'uzantısız'}"
    allowed = allowed_extensions_global()
    if allowed and normalized not in allowed:
        return False, f"Bu dosya türü kurumsal izin listesinde değil: {normalized or 'uzantısız'}"
    return True, None


def _move_file_to_area(item: FileStorageItem, area: str) -> None:
    try:
        current = Path(item.storage_path).resolve()
        if not current.exists():
            return
        target_dir = storage_root() / area / str(item.owner_user_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / item.stored_filename
        if target.exists() and target.resolve() != current:
            target = target_dir / f"{utc_now().strftime('%Y%m%d_%H%M%S')}_{token_urlsafe(6)}_{item.stored_filename}"
        if current.resolve() != target.resolve():
            shutil.move(str(current), str(target))
            item.storage_path = str(target.resolve())
    except Exception:
        # Dosya taşıma hatası güvenlik statüsünü bozmasın; denetim kaydına düşsün.
        logger.exception("BYS360 Dosya Merkezi dosya taşıma hatası: file_id=%s", getattr(item, "id", None))
        log_audit("file_security_move_failed", file_id=item.id, message="Dosya taşıma sırasında bir hata oluştu.")


def _set_latest_scan(item: FileStorageItem, *, status: str, scanner: str, message: str) -> FileSecurityScan:
    item.scan_status = status
    if status == "clean":
        item.status = "ready"
    elif status in {"quarantined", "blocked", "failed"}:
        item.status = status
    scan = FileSecurityScan(
        file_id=item.id,
        status=status,
        scanner=scanner,
        result_message=message,
        scanned_at=utc_now(),
    )
    db.session.add(scan)
    return scan


def run_security_scan(item: FileStorageItem, *, actor_user_id: int | None = None, force: bool = False) -> FileSecurityScan:
    """Local V1H güvenlik taraması.

    Bu faz gerçek antivirüs motoru yerine kontrollü kurumsal ön tarama yapar:
    uzantı denetimi, global izin listesi, çift uzantı/riskli ad kontrolü,
    MIME ipucu kontrolü, fiziksel dosya varlığı, boş dosya ve hash kontrolü.
    """
    if item is None:
        raise ValueError("Taranacak dosya bulunamadı.")
    if not force and item.scan_status in {"clean", "quarantined", "blocked"}:
        return _set_latest_scan(item, status=item.scan_status, scanner="file_center_v1h", message="Dosya daha önce taranmış; mevcut durum korundu.")

    path = Path(item.storage_path).resolve() if item.storage_path else None
    if path is None or not path.exists():
        scan = _set_latest_scan(item, status="failed", scanner="file_center_v1h", message="Fiziksel dosya bulunamadı.")
        log_audit("file_security_scan_failed", file_id=item.id, message="Fiziksel dosya bulunamadı.", actor_user_id=actor_user_id)
        return scan

    ext_ok, ext_message = _global_extension_allowed(item.extension)
    if not ext_ok:
        if quarantine_enabled():
            _move_file_to_area(item, "quarantine")
        scan = _set_latest_scan(item, status="quarantined", scanner="file_center_v1h", message=ext_message or "Dosya türü güvenlik nedeniyle karantinaya alındı.")
        log_audit("file_quarantined", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
        return scan

    if _has_double_extension_risk(item.original_filename):
        if quarantine_enabled():
            _move_file_to_area(item, "quarantine")
        scan = _set_latest_scan(item, status="quarantined", scanner="file_center_v1h", message="Dosya adında çift uzantı/riskli uzantı izi bulundu.")
        log_audit("file_quarantined", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
        return scan

    mime = (item.content_type or "").lower()
    if mime and any(mime.startswith(prefix) for prefix in SUSPICIOUS_MIME_PREFIXES):
        if quarantine_enabled():
            _move_file_to_area(item, "quarantine")
        scan = _set_latest_scan(item, status="quarantined", scanner="file_center_v1h", message=f"Riskli içerik türü algılandı: {mime}")
        log_audit("file_quarantined", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
        return scan

    try:
        size = path.stat().st_size
    except OSError:
        size = item.size_bytes or 0
    if size <= 0:
        if quarantine_enabled():
            _move_file_to_area(item, "quarantine")
        scan = _set_latest_scan(item, status="quarantined", scanner="file_center_v1h", message="Boş dosya güvenlik incelemesine alındı.")
        log_audit("file_quarantined", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
        return scan

    # Hash eksikse yeniden hesapla.
    if not item.sha256_hash:
        sha = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
        item.sha256_hash = sha.hexdigest()

    if clamav_enabled():
        av_status, av_message = _run_clamav_scan(path)
        if av_status == "clean":
            scan = _set_latest_scan(item, status="clean", scanner="clamav", message=av_message)
            log_audit("file_security_scan_clean", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
            return scan
        if av_status == "infected":
            if quarantine_enabled():
                _move_file_to_area(item, "quarantine")
            scan = _set_latest_scan(item, status="quarantined", scanner="clamav", message=av_message)
            FileShareLink.query.filter_by(file_id=item.id, is_active=True).update({"is_active": False, "revoked_at": utc_now(), "revoked_by_user_id": actor_user_id})
            log_audit("file_quarantined", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
            return scan
        scan = _set_latest_scan(item, status="failed", scanner="clamav", message=av_message)
        log_audit("file_security_scan_failed", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
        return scan

    scan = _set_latest_scan(
        item,
        status="clean",
        scanner="file_center_heuristic_v1l",
        message="Temel dosya türü ve güvenlik ön kontrolü geçti. Gerçek antivirüs taraması etkin değil.",
    )
    log_audit("file_security_scan_clean", file_id=item.id, message=scan.result_message, actor_user_id=actor_user_id)
    return scan


def can_download_file(item: FileStorageItem) -> tuple[bool, str]:
    if item.is_deleted:
        return False, "Dosya silinmiş olduğu için indirilemez."
    if item.status in {"quarantined", "blocked"} or item.scan_status in {"quarantined", "blocked"}:
        return False, "Dosya güvenlik nedeniyle indirilemez."
    if item.scan_status == "failed":
        return False, "Dosyanın güvenlik taraması başarısız olduğu için indirilemez."
    if require_clean_before_download() and item.scan_status not in {"clean", "ready"}:
        return False, "Dosya güvenlik taraması tamamlanmadan indirilemez."
    return True, "OK"


def quarantine_file_item(item: FileStorageItem, *, actor_user_id: int | None = None, reason: str | None = None) -> None:
    if quarantine_enabled():
        _move_file_to_area(item, "quarantine")
    message = reason or "Dosya manuel olarak karantinaya alındı."
    _set_latest_scan(item, status="quarantined", scanner="file_center_manual", message=message)
    FileShareLink.query.filter_by(file_id=item.id, is_active=True).update({"is_active": False, "revoked_at": utc_now(), "revoked_by_user_id": actor_user_id})
    log_audit("file_quarantined", file_id=item.id, message=message, actor_user_id=actor_user_id)


def release_quarantined_file(item: FileStorageItem, *, actor_user_id: int | None = None, reason: str | None = None) -> None:
    # Dosyayı yeniden yükleme alanına al.
    try:
        current = Path(item.storage_path).resolve()
        target_dir = upload_root_for_user(int(item.owner_user_id))
        target = target_dir / item.stored_filename
        if current.exists() and current.resolve() != target.resolve():
            if target.exists():
                target = target_dir / f"{utc_now().strftime('%Y%m%d_%H%M%S')}_{token_urlsafe(6)}_{item.stored_filename}"
            shutil.move(str(current), str(target))
            item.storage_path = str(target.resolve())
    except Exception:
        logger.exception("BYS360 Dosya Merkezi karantinadan çıkarma taşıma hatası: file_id=%s", getattr(item, "id", None))
        log_audit("file_security_release_move_failed", file_id=item.id, message="Karantinadan çıkarma sırasında bir taşıma hatası oluştu.", actor_user_id=actor_user_id)
    message = reason or "Dosya manuel inceleme sonrası güvenli kabul edildi."
    _set_latest_scan(item, status="clean", scanner="file_center_manual", message=message)
    log_audit("file_released_from_quarantine", file_id=item.id, message=message, actor_user_id=actor_user_id)


def block_file_item(item: FileStorageItem, *, actor_user_id: int | None = None, reason: str | None = None) -> None:
    if quarantine_enabled():
        _move_file_to_area(item, "quarantine")
    message = reason or "Dosya manuel olarak engellendi."
    _set_latest_scan(item, status="blocked", scanner="file_center_manual", message=message)
    FileShareLink.query.filter_by(file_id=item.id, is_active=True).update({"is_active": False, "revoked_at": utc_now(), "revoked_by_user_id": actor_user_id})
    log_audit("file_blocked", file_id=item.id, message=message, actor_user_id=actor_user_id)


def scan_pending_files(*, limit: int = 100, actor_user_id: int | None = None) -> dict[str, int]:
    rows = (
        FileStorageItem.query.filter(
            FileStorageItem.is_deleted.is_(False),
            FileStorageItem.scan_status.in_(["pending", "failed", None]),
        )
        .order_by(FileStorageItem.created_at.asc())
        .limit(limit)
        .all()
    )
    result = {"total": 0, "clean": 0, "quarantined": 0, "blocked": 0, "failed": 0}
    for item in rows:
        result["total"] += 1
        scan = run_security_scan(item, actor_user_id=actor_user_id, force=True)
        if scan.status in result:
            result[scan.status] += 1
    return result


def security_summary() -> dict[str, int]:
    def count(status: str) -> int:
        return FileStorageItem.query.filter_by(is_deleted=False, scan_status=status).count()
    return {
        "total": FileStorageItem.query.filter_by(is_deleted=False).count(),
        "pending": count("pending"),
        "clean": count("clean"),
        "quarantined": count("quarantined"),
        "blocked": count("blocked"),
        "failed": count("failed"),
        "active_links": FileShareLink.query.filter_by(is_active=True).count(),
    }


def create_guest_link(file_item: FileStorageItem, password: str, *, days: int | None = None, max_downloads: int | None = None) -> tuple[FileShareLink, str]:
    token = token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    link = FileShareLink(
        file_id=file_item.id,
        token_hash=token_hash,
        public_token=token,
        password_hash=generate_password_hash(password),
        expires_at=utc_now() + timedelta(days=days or default_expiry_days()),
        max_downloads=max_downloads or default_download_limit(),
        created_by_user_id=int(current_user.id),
        is_active=True,
    )
    db.session.add(link)
    db.session.flush()
    log_audit("guest_link_created", file_id=file_item.id, message="Misafir indirme bağlantısı oluşturuldu.")
    return link, token


def find_share_link_by_token(token: str) -> FileShareLink | None:
    token_hash = hashlib.sha256((token or "").encode("utf-8")).hexdigest()
    return FileShareLink.query.filter_by(token_hash=token_hash).one_or_none()


def verify_share_password(link: FileShareLink, password: str) -> bool:
    if not link.password_hash:
        return True
    return check_password_hash(link.password_hash, password or "")


def record_guest_download(link: FileShareLink, status: str = "success") -> None:
    ip, ua = _request_meta()
    if status == "success":
        link.download_count += 1
        link.last_downloaded_at = utc_now()
    db.session.add(FileDownloadLog(
        file_id=link.file_id,
        share_link_id=link.id,
        guest_label="Misafir bağlantısı",
        ip_address=ip,
        user_agent=ua,
        status=status,
    ))
    log_audit("guest_file_download", file_id=link.file_id, message=f"Misafir indirme durumu: {status}", actor_user_id=None)


def soft_delete_file(item: FileStorageItem, actor_user_id: int) -> None:
    item.is_deleted = True
    item.deleted_at = utc_now()
    item.deleted_by_user_id = actor_user_id
    FileShareLink.query.filter_by(file_id=item.id, is_active=True).update({"is_active": False, "revoked_at": utc_now(), "revoked_by_user_id": actor_user_id})
    log_audit("file_deleted", file_id=item.id, message="Dosya silindi ve aktif misafir bağlantıları kapatıldı.", actor_user_id=actor_user_id)
    # F07b-Q2: admin başkasının dosyasını sildiğinde kota, işlemi yapanın değil dosya sahibinin kotasıdır.
    update_quota_for_user(int(item.owner_user_id or actor_user_id))


def create_transfer_package(*, owner_user_id: int, title: str, message: str | None, file_ids: Iterable[int], recipient_emails: str | None) -> FileTransfer:
    ids = [int(x) for x in file_ids if str(x).strip()]
    if not ids:
        raise ValueError("Transfer için en az bir dosya seçilmelidir.")
    files = FileStorageItem.query.filter(
        FileStorageItem.id.in_(ids),
        FileStorageItem.owner_user_id == owner_user_id,
        FileStorageItem.is_deleted.is_(False),
    ).all()
    if len(files) != len(set(ids)):
        raise ValueError("Seçilen dosyalardan bazılarına erişilemiyor.")
    total_size = sum(int(x.size_bytes or 0) for x in files)
    if total_size > max_transfer_bytes():
        raise ValueError("Transfer paketi izin verilen toplam boyutu aşıyor.")
    transfer = FileTransfer(
        owner_user_id=owner_user_id,
        title=title.strip() or "Dosya transferi",
        message=message,
        status="ready",
        expires_at=utc_now() + timedelta(days=default_expiry_days()),
    )
    db.session.add(transfer)
    db.session.flush()
    for item in files:
        db.session.add(FileTransferItem(transfer_id=transfer.id, file_id=item.id))
    emails = []
    for raw in (recipient_emails or "").replace(";", ",").split(","):
        email = raw.strip()
        if email:
            emails.append(email)
            db.session.add(FileTransferRecipient(transfer_id=transfer.id, recipient_email=email, status="pending"))
    log_audit("transfer_created", message=f"Transfer paketi oluşturuldu: {transfer.title} ({len(files)} dosya, {len(emails)} alıcı)", actor_user_id=owner_user_id)
    return transfer


def create_file_request(*, owner_user_id: int, title: str, description: str | None, recipient_name: str | None, recipient_email: str | None, password: str, days: int, max_file_gb: float, allowed_extensions: str | None) -> tuple[FileRequest, str]:
    token = token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = FileRequest(
        owner_user_id=owner_user_id,
        title=(title or "Dosya Talebi").strip(),
        description=description,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        token_hash=token_hash,
        public_token=token,
        password_hash=generate_password_hash(password),
        expires_at=utc_now() + timedelta(days=days or default_expiry_days()),
        max_file_gb=float(max_file_gb or 5),
        allowed_extensions=allowed_extensions,
        status="open",
    )
    db.session.add(row)
    db.session.flush()
    log_audit("file_request_created", message=f"Dosya talebi oluşturuldu: {row.title}", actor_user_id=owner_user_id)
    return row, token


def find_file_request_by_token(token: str) -> FileRequest | None:
    token_hash = hashlib.sha256((token or "").encode("utf-8")).hexdigest()
    return FileRequest.query.filter_by(token_hash=token_hash).one_or_none()


def verify_request_password(row: FileRequest, password: str) -> bool:
    if not row.password_hash:
        return True
    return check_password_hash(row.password_hash, password or "")


def request_max_bytes(row: FileRequest) -> int:
    gb = float(row.max_file_gb or 5)
    hard_limit = max_file_bytes()
    return min(int(gb * 1024 * 1024 * 1024), hard_limit)


def record_guest_request_upload(row: FileRequest, file_storage, *, password: str, guest_name: str | None, guest_email: str | None) -> FileStorageItem:
    if not verify_request_password(row, password):
        log_audit("file_request_wrong_password", message=f"Dosya talebi için hatalı şifre denemesi: {row.title}", actor_user_id=None)
        raise ValueError("Şifre hatalı.")
    if not row.is_available():
        raise ValueError("Bu dosya yükleme bağlantısı kapalı veya süresi dolmuş.")
    limit = request_max_bytes(row)
    ok, message = validate_upload_request(file_storage, max_bytes=limit, allowed_extensions=row.allowed_extensions)
    if not ok:
        raise ValueError(message)
    item = save_uploaded_file(file_storage, int(row.owner_user_id), max_bytes=limit)
    ip, ua = _request_meta()
    db.session.add(FileRequestUpload(
        request_id=row.id,
        file_id=item.id,
        guest_name=guest_name,
        guest_email=guest_email,
        ip_address=ip,
        user_agent=ua,
        status="uploaded",
    ))
    row.upload_count = int(row.upload_count or 0) + 1
    row.last_upload_at = utc_now()
    log_audit("file_request_upload", file_id=item.id, message=f"Dosya talebi üzerinden yükleme alındı: {row.title}", actor_user_id=None)
    return item


# -----------------------------------------------------------------------------
# V1I Kota politikası ve parçalı yükleme hazırlığı
# -----------------------------------------------------------------------------

def quota_policy_enabled() -> bool:
    return _db_bool("quota_policy_enabled", "FILE_CENTER_QUOTA_POLICY_ENABLED", True)


def chunk_upload_enabled() -> bool:
    return _db_bool("chunk_upload_enabled", "FILE_CENTER_CHUNK_UPLOAD_ENABLED", True)


def default_user_storage_gb() -> float:
    return _db_float("default_user_storage_gb", "FILE_CENTER_DEFAULT_USER_STORAGE_GB", 25.0)


def default_unit_storage_gb() -> float:
    return _db_float("default_unit_storage_gb", "FILE_CENTER_DEFAULT_UNIT_STORAGE_GB", 250.0)


def default_warning_threshold() -> int:
    return _db_int("quota_warning_percent", "FILE_CENTER_QUOTA_WARNING_PERCENT", 80)


def default_chunk_size_bytes() -> int:
    mb = _db_float("default_chunk_mb", "FILE_CENTER_DEFAULT_CHUNK_MB", 10.0)
    return int(mb * 1024 * 1024)


def quota_scope_label(scope_type: str | None, scope_value: str | None = None) -> str:
    scope = str(scope_type or "global").lower()
    value = str(scope_value or "").strip()
    mapping = {
        "global": "Genel politika",
        "user": "Kullanıcı politikası",
        "unit": "Birim politikası",
        "role": "Rol politikası",
    }
    base = mapping.get(scope, "Özel politika")
    return f"{base}: {value}" if value and scope != "global" else base


def quota_status_label(used_bytes: int, max_bytes: int, warning_percent: int = 80) -> tuple[str, str]:
    if max_bytes <= 0:
        return "limitsiz", "Limit tanımlı değil"
    percent = (float(used_bytes or 0) / float(max_bytes)) * 100
    if percent >= 100:
        return "danger", "Kota doldu"
    if percent >= warning_percent:
        return "warning", "Kota uyarısı"
    return "success", "Kullanım normal"


def _user_unit_value(user) -> str | None:
    for attr in ("organization_unit_id", "unit_id", "department_id"):
        value = getattr(user, attr, None)
        if value:
            return str(value)
    return None


def _user_role_value(user) -> str | None:
    return str(getattr(user, "role", "") or getattr(user, "role_label", "") or "").strip() or None


def _policy_query(scope_type: str, scope_value: str | None = None):
    q = FileQuotaPolicy.query.filter_by(scope_type=scope_type, is_active=True)
    if scope_value is None:
        q = q.filter(FileQuotaPolicy.scope_value.is_(None))
    else:
        q = q.filter_by(scope_value=str(scope_value))
    return q.order_by(FileQuotaPolicy.updated_at.desc(), FileQuotaPolicy.created_at.desc())


def default_quota_policy() -> dict:
    return {
        "source": "Sistem varsayılanı",
        "max_storage_gb": default_user_storage_gb(),
        "max_single_file_gb": max_file_bytes() / 1024 / 1024 / 1024,
        "max_transfer_gb": float(os.getenv("FILE_CENTER_MAX_TRANSFER_GB") or 20),
        "warning_threshold_percent": default_warning_threshold(),
        "hard_stop_enabled": False,
        "policy": None,
    }


def effective_quota_for_user(user) -> dict:
    base = default_quota_policy()
    if not quota_policy_enabled() or user is None:
        return base
    # Öncelik: kullanıcı > rol > birim > global > varsayılan
    candidates = []
    user_id = getattr(user, "id", None)
    if user_id:
        candidates.append(_policy_query("user", str(user_id)).first())
    role_value = _user_role_value(user)
    if role_value:
        candidates.append(_policy_query("role", role_value).first())
    unit_value = _user_unit_value(user)
    if unit_value:
        candidates.append(_policy_query("unit", unit_value).first())
    candidates.append(_policy_query("global", None).first())
    policy = next((p for p in candidates if p is not None), None)
    if not policy:
        return base
    return {
        "source": policy.label or quota_scope_label(policy.scope_type, policy.scope_value),
        "max_storage_gb": float(policy.max_storage_gb or base["max_storage_gb"]),
        "max_single_file_gb": float(policy.max_single_file_gb or base["max_single_file_gb"]),
        "max_transfer_gb": float(policy.max_transfer_gb or base["max_transfer_gb"]),
        "warning_threshold_percent": int(policy.warning_threshold_percent or base["warning_threshold_percent"]),
        "hard_stop_enabled": bool(policy.hard_stop_enabled),
        "policy": policy,
    }


def calculate_user_used_bytes(user_id: int) -> int:
    total = db.session.query(db.func.coalesce(db.func.sum(FileStorageItem.size_bytes), 0)).filter(
        FileStorageItem.owner_user_id == user_id,
        FileStorageItem.is_deleted.is_(False),
    ).scalar() or 0
    return int(total)


def user_quota_summary(user) -> dict:
    usage = FileQuotaUsage.query.filter_by(user_id=getattr(user, "id", None)).one_or_none() if user else None
    if user and usage is None:
        update_quota_for_user(int(user.id))
        usage = FileQuotaUsage.query.filter_by(user_id=int(user.id)).one_or_none()
    used_bytes = int(getattr(usage, "used_bytes", 0) or calculate_user_used_bytes(int(user.id))) if user else 0
    file_count = int(getattr(usage, "file_count", 0) or 0)
    policy = effective_quota_for_user(user)
    max_bytes = int(float(policy["max_storage_gb"]) * 1024 * 1024 * 1024)
    percent = round((used_bytes / max_bytes) * 100, 2) if max_bytes else 0
    level, label = quota_status_label(used_bytes, max_bytes, int(policy["warning_threshold_percent"]))
    return {
        "used_bytes": used_bytes,
        "file_count": file_count,
        "max_bytes": max_bytes,
        "percent": percent,
        "level": level,
        "label": label,
        "policy": policy,
    }


def check_user_quota_for_upload(user_id: int, *, estimated_bytes: int = 0) -> tuple[bool, str]:
    if not quota_policy_enabled():
        return True, "Kota politikası kapalı."
    from app.models import User  # geç import: proje kullanıcı modelini güvenli kullanır
    user = User.query.get(user_id)
    if user is None:
        return True, "Kullanıcı bulunamadı; kota kontrolü pas geçildi."
    summary = user_quota_summary(user)
    max_bytes = int(summary["max_bytes"] or 0)
    if max_bytes <= 0:
        return True, "Kota limiti tanımlı değil."
    estimated = int(estimated_bytes or 0)
    projected = int(summary["used_bytes"] or 0) + estimated
    if projected > max_bytes and summary["policy"].get("hard_stop_enabled"):
        return False, "Depolama kotası dolduğu için dosya yüklenemedi. Kota artırımı için sistem yöneticisine başvurun."
    return True, "Kota kontrolü uygun."


def quota_dashboard_summary() -> dict:
    policies = FileQuotaPolicy.query.order_by(FileQuotaPolicy.is_active.desc(), FileQuotaPolicy.updated_at.desc(), FileQuotaPolicy.created_at.desc()).all()
    top_usage = FileQuotaUsage.query.order_by(FileQuotaUsage.used_bytes.desc()).limit(20).all()
    sessions = FileUploadSession.query.order_by(FileUploadSession.created_at.desc()).limit(20).all()
    return {
        "policies": policies,
        "top_usage": top_usage,
        "sessions": sessions,
        "policy_count": len([p for p in policies if p.is_active]),
        "prepared_sessions": FileUploadSession.query.filter_by(status="prepared").count(),
    }


def create_or_update_quota_policy(*, scope_type: str, scope_value: str | None, label: str, max_storage_gb: float, max_single_file_gb: float, max_transfer_gb: float, warning_threshold_percent: int, hard_stop_enabled: bool, actor_user_id: int | None, notes: str | None = None) -> FileQuotaPolicy:
    scope = (scope_type or "global").strip().lower()
    value = (scope_value or "").strip() or None
    if scope == "global":
        value = None
    policy = FileQuotaPolicy.query.filter_by(scope_type=scope, scope_value=value, is_active=True).one_or_none()
    if policy is None:
        policy = FileQuotaPolicy(scope_type=scope, scope_value=value, created_by_user_id=actor_user_id)
        db.session.add(policy)
    policy.label = label or quota_scope_label(scope, value)
    policy.max_storage_gb = float(max_storage_gb or default_user_storage_gb())
    policy.max_single_file_gb = float(max_single_file_gb or max_file_bytes() / 1024 / 1024 / 1024)
    policy.max_transfer_gb = float(max_transfer_gb or 20)
    policy.warning_threshold_percent = int(warning_threshold_percent or default_warning_threshold())
    policy.hard_stop_enabled = bool(hard_stop_enabled)
    policy.notes = notes
    policy.is_active = True
    log_audit("quota_policy_saved", message=f"Kota politikası kaydedildi: {policy.label}", actor_user_id=actor_user_id)
    return policy


def deactivate_quota_policy(policy_id: int, actor_user_id: int | None = None) -> FileQuotaPolicy:
    policy = FileQuotaPolicy.query.get_or_404(policy_id)
    policy.is_active = False
    log_audit("quota_policy_deactivated", message=f"Kota politikası pasifleştirildi: {policy.label}", actor_user_id=actor_user_id)
    return policy


def chunk_session_status_label(status: str | None) -> str:
    mapping = {
        "prepared": "Hazırlandı",
        "uploading": "Yükleme devam ediyor",
        "completed": "Tamamlandı",
        "finalizing": "Birleştiriliyor",
        "verified": "Doğrulandı",
        "cancelled": "İptal edildi",
        "expired": "Süresi doldu",
        "failed": "Başarısız",
    }
    return mapping.get(str(status or "").lower(), "Hazırlık")


def create_chunk_upload_session(*, owner_user_id: int, original_filename: str, total_size_bytes: int, chunk_size_bytes: int | None = None, sha256_hash: str | None = None) -> tuple[FileUploadSession, str]:
    if not chunk_upload_enabled():
        raise ValueError("Parçalı yükleme hazırlığı şu anda kapalı.")
    total = int(total_size_bytes or 0)
    if total <= 0:
        raise ValueError("Toplam dosya boyutu belirtilmelidir.")
    ok, quota_message = check_user_quota_for_upload(owner_user_id, estimated_bytes=total)
    if not ok:
        raise ValueError(quota_message)
    chunk_size = int(chunk_size_bytes or default_chunk_size_bytes())
    if chunk_size <= 0:
        chunk_size = default_chunk_size_bytes()
    total_chunks = int((total + chunk_size - 1) // chunk_size)
    token = token_urlsafe(32)
    temp_dir = storage_root() / "temp" / "chunk_sessions" / str(owner_user_id) / token
    temp_dir.mkdir(parents=True, exist_ok=True)
    session = FileUploadSession(
        owner_user_id=owner_user_id,
        session_token=token,
        original_filename=original_filename or "büyük_dosya",
        total_size_bytes=total,
        chunk_size_bytes=chunk_size,
        total_chunks=total_chunks,
        received_chunks=0,
        received_bytes=0,
        sha256_hash=sha256_hash,
        status="prepared",
        temp_dir=str(temp_dir.resolve()),
        expires_at=utc_now() + timedelta(hours=24),
    )
    db.session.add(session)
    db.session.flush()
    log_audit("chunk_upload_session_created", message=f"Parçalı yükleme oturumu hazırlandı: {session.original_filename} ({total_chunks} parça)", actor_user_id=owner_user_id)
    return session, token


def cancel_chunk_upload_session(session_id: int, actor_user_id: int) -> FileUploadSession:
    session = FileUploadSession.query.get_or_404(session_id)
    if session.owner_user_id != actor_user_id:
        # admin benzeri kontrol route tarafında ayrıca yapılır; burada kayıt koruması var
        pass
    session.status = "cancelled"
    session.cancelled_at = utc_now()
    try:
        if session.temp_dir:
            shutil.rmtree(session.temp_dir, ignore_errors=True)
    except Exception:
        logger.exception("BYS360 Dosya Merkezi parçalı yükleme temp temizliği hatası: session_id=%s", session_id)
        log_audit("chunk_upload_cleanup_failed", message="Parçalı yükleme geçici dosyaları temizlenirken bir hata oluştu.", actor_user_id=actor_user_id)
    log_audit("chunk_upload_session_cancelled", message=f"Parçalı yükleme oturumu iptal edildi: {session.original_filename}", actor_user_id=actor_user_id)
    return session


def list_user_upload_sessions(user_id: int, *, limit: int = 20) -> list[FileUploadSession]:
    return FileUploadSession.query.filter_by(owner_user_id=user_id).order_by(FileUploadSession.created_at.desc()).limit(limit).all()


# -----------------------------------------------------------------------------
# V1J Gerçek parçalı yükleme, devam etme, birleştirme ve hash doğrulama
# -----------------------------------------------------------------------------

def chunk_upload_session_to_dict(session: FileUploadSession) -> dict:
    chunks = FileUploadChunk.query.filter_by(session_id=session.id, status="uploaded").all()
    received_indexes = sorted({int(row.chunk_index) for row in chunks})
    return {
        "id": session.id,
        "filename": session.original_filename,
        "status": session.status,
        "status_label": chunk_session_status_label(session.status),
        "total_size_bytes": int(session.total_size_bytes or 0),
        "chunk_size_bytes": int(session.chunk_size_bytes or 0),
        "total_chunks": int(session.total_chunks or 0),
        "received_chunks": len(received_indexes),
        "received_bytes": int(sum(int(row.size_bytes or 0) for row in chunks)),
        "received_indexes": received_indexes,
        "finalized_file_id": session.finalized_file_id,
    }


def _get_user_chunk_session(session_id: int, user_id: int, *, allow_admin: bool = False) -> FileUploadSession:
    session = FileUploadSession.query.get_or_404(session_id)
    if session.owner_user_id != user_id and not allow_admin:
        raise PermissionError("Bu yükleme oturumuna erişim yetkiniz bulunmamaktadır.")
    return session


def upload_chunk_part(*, session_id: int, owner_user_id: int, chunk_index: int, file_storage) -> FileUploadChunk:
    session = _get_user_chunk_session(session_id, owner_user_id)
    if session.status in {"cancelled", "completed", "verified", "expired"}:
        raise ValueError("Bu yükleme oturumu artık parça kabul etmiyor.")
    if session.expires_at and session.expires_at < utc_now():
        session.status = "expired"
        raise ValueError("Bu yükleme oturumunun süresi dolmuş.")
    if chunk_index < 0 or chunk_index >= int(session.total_chunks or 0):
        raise ValueError("Parça numarası geçersiz.")
    if not file_storage:
        raise ValueError("Yüklenecek parça bulunamadı.")

    temp_dir = Path(session.temp_dir or "").resolve()
    root = (storage_root() / "temp" / "chunk_sessions").resolve()
    temp_dir.relative_to(root)
    temp_dir.mkdir(parents=True, exist_ok=True)

    part_path = (temp_dir / f"{chunk_index:08d}.part").resolve()
    tmp_path = (temp_dir / f"{chunk_index:08d}.part.tmp").resolve()
    sha = hashlib.sha256()
    size = 0
    max_chunk = int(session.chunk_size_bytes or default_chunk_size_bytes())
    with open(tmp_path, "wb") as out:
        while True:
            data = file_storage.stream.read(1024 * 1024)
            if not data:
                break
            size += len(data)
            if size > max_chunk and chunk_index < int(session.total_chunks or 0) - 1:
                out.close()
                try:
                    tmp_path.unlink(missing_ok=True)
                except TypeError:
                    if tmp_path.exists():
                        tmp_path.unlink()
                raise ValueError("Yüklenen parça beklenen parça boyutunu aşıyor.")
            sha.update(data)
            out.write(data)
    tmp_path.replace(part_path)

    row = FileUploadChunk.query.filter_by(session_id=session.id, chunk_index=chunk_index).one_or_none()
    if row is None:
        row = FileUploadChunk(session_id=session.id, chunk_index=chunk_index)
        db.session.add(row)
    row.size_bytes = size
    row.sha256_hash = sha.hexdigest()
    row.storage_path = str(part_path)
    row.status = "uploaded"

    uploaded = FileUploadChunk.query.filter_by(session_id=session.id, status="uploaded").all()
    indexes = {int(x.chunk_index) for x in uploaded}
    indexes.add(int(chunk_index))
    session.received_chunks = len(indexes)
    session.received_bytes = int(sum(int(x.size_bytes or 0) for x in uploaded if int(x.chunk_index) != int(chunk_index)) + size)
    session.status = "uploading"
    log_audit("chunk_part_uploaded", message=f"Parça yüklendi: {session.original_filename} [{chunk_index + 1}/{session.total_chunks}]", actor_user_id=owner_user_id)
    return row


def finalize_chunk_upload_session(*, session_id: int, owner_user_id: int) -> FileStorageItem:
    session = _get_user_chunk_session(session_id, owner_user_id)
    if session.status in {"cancelled", "completed", "verified", "expired"}:
        if session.finalized_file_id:
            existing = FileStorageItem.query.get(session.finalized_file_id)
            if existing:
                return existing
        raise ValueError("Bu yükleme oturumu tamamlanamaz.")
    if session.expires_at and session.expires_at < utc_now():
        session.status = "expired"
        raise ValueError("Bu yükleme oturumunun süresi dolmuş.")

    parts = {int(row.chunk_index): row for row in FileUploadChunk.query.filter_by(session_id=session.id, status="uploaded").all()}
    missing = [idx for idx in range(int(session.total_chunks or 0)) if idx not in parts]
    if missing:
        raise ValueError("Eksik parçalar var: " + ", ".join(str(x + 1) for x in missing[:20]))

    ok, quota_message = check_user_quota_for_upload(owner_user_id, estimated_bytes=int(session.total_size_bytes or 0))
    if not ok:
        raise ValueError(quota_message)

    original_name = session.original_filename or "büyük_dosya"
    safe_original = secure_filename(original_name) or "buyuk_dosya"
    ext = Path(safe_original).suffix.lower()
    if ext in blocked_extensions():
        raise ValueError(f"Bu dosya türü güvenlik nedeniyle birleştirilemez: {ext}")

    target_dir = upload_root_for_user(owner_user_id)
    stored_name = f"{utc_now().strftime('%Y%m%d_%H%M%S')}_{token_urlsafe(12)}{ext}"
    target_path = (target_dir / stored_name).resolve()
    sha = hashlib.sha256()
    total = 0
    session.status = "finalizing"

    with open(target_path, "wb") as out:
        for idx in range(int(session.total_chunks or 0)):
            part = parts[idx]
            part_path = Path(part.storage_path or "").resolve()
            if not part_path.is_file():
                raise ValueError(f"{idx + 1}. parça fiziksel depoda bulunamadı.")
            with open(part_path, "rb") as inp:
                while True:
                    data = inp.read(1024 * 1024)
                    if not data:
                        break
                    sha.update(data)
                    total += len(data)
                    out.write(data)

    expected = int(session.total_size_bytes or 0)
    if expected and total != expected:
        session.status = "failed"
        try:
            target_path.unlink(missing_ok=True)
        except TypeError:
            if target_path.exists():
                target_path.unlink()
        raise ValueError(f"Dosya boyutu doğrulanamadı. Beklenen: {expected}, oluşan: {total}")

    final_hash = sha.hexdigest()
    expected_hash = (session.sha256_hash or "").strip().lower()
    if expected_hash and expected_hash != final_hash:
        session.status = "failed"
        try:
            target_path.unlink(missing_ok=True)
        except TypeError:
            if target_path.exists():
                target_path.unlink()
        raise ValueError("SHA256 doğrulaması başarısız. Dosya parçaları beklenen dosyayla eşleşmiyor.")

    item = FileStorageItem(
        owner_user_id=owner_user_id,
        original_filename=original_name,
        stored_filename=stored_name,
        storage_path=str(target_path),
        content_type=None,
        extension=ext,
        size_bytes=total,
        sha256_hash=final_hash,
        status="ready",
        scan_status="pending",
    )
    db.session.add(item)
    db.session.flush()
    db.session.add(FileSecurityScan(file_id=item.id, status="pending", scanner="file_center_chunk_queue", result_message="Parçalı yükleme sonrası güvenlik taraması için kuyruğa alındı."))
    session.status = "verified" if expected_hash else "completed"
    session.finalized_file_id = item.id
    session.received_chunks = int(session.total_chunks or 0)
    session.received_bytes = total
    update_quota_for_user(owner_user_id)
    log_audit("chunk_upload_finalized", file_id=item.id, message=f"Parçalı yükleme birleştirildi: {original_name}", actor_user_id=owner_user_id)
    try:
        if session.temp_dir:
            shutil.rmtree(session.temp_dir, ignore_errors=True)
    except Exception:
        logger.exception("BYS360 Dosya Merkezi parça klasörü temizleme hatası: file_id=%s", getattr(item, "id", None))
        log_audit("chunk_upload_cleanup_failed", file_id=item.id, message="Parça klasörü temizlenirken bir hata oluştu.", actor_user_id=owner_user_id)
    return item
