"""BYS360 Dosya Merkezi ayar servisleri.

V1K amacı:
- Dosya Merkezi ayarlarını .env yerine veritabanı üzerinden yönetilebilir hale getirmek.
- Tablo yoksa veya migration henüz çalışmadıysa güvenli şekilde .env varsayılanlarına düşmek.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models.file_center_models import FileCenterSetting


@dataclass(frozen=True)
class FileCenterSettingDefinition:
    key: str
    label: str
    value: str
    value_type: str = "string"
    group_key: str = "general"
    description: str = ""


SETTING_DEFINITIONS: list[FileCenterSettingDefinition] = [
    FileCenterSettingDefinition("file_center_enabled", "Dosya Merkezi aktif", "true", "bool", "Genel", "Modülün kullanıcı arayüzünde ve route seviyesinde açık olup olmadığını belirler."),
    FileCenterSettingDefinition("guest_links_enabled", "Misafir indirme bağlantıları", "true", "bool", "Paylaşım", "BYS360 hesabı olmayan kişilere şifreli indirme bağlantısı oluşturulabilir."),
    FileCenterSettingDefinition("guest_uploads_enabled", "Misafir yükleme bağlantıları", "true", "bool", "Paylaşım", "BYS360 hesabı olmayan kişilerden şifreli yükleme bağlantısıyla dosya alınabilir."),
    FileCenterSettingDefinition("guest_password_required", "Misafir bağlantısında şifre zorunlu", "true", "bool", "Paylaşım", "Dış bağlantılarda şifre zorunluluğu."),
    FileCenterSettingDefinition("max_file_gb", "Tek dosya sınırı", "5", "float", "Limit", "Standart tek dosya yükleme sınırı, GB."),
    FileCenterSettingDefinition("max_transfer_gb", "Transfer paketi sınırı", "20", "float", "Limit", "Tek transfer paketindeki toplam dosya sınırı, GB."),
    FileCenterSettingDefinition("default_expiry_days", "Varsayılan bağlantı süresi", "7", "int", "Limit", "Misafir bağlantıları ve dosya istekleri için varsayılan gün sayısı."),
    FileCenterSettingDefinition("default_download_limit", "Varsayılan indirme limiti", "5", "int", "Limit", "Misafir indirme linki için varsayılan indirme sayısı."),
    FileCenterSettingDefinition("blocked_extensions", "Engellenen dosya türleri", ".exe,.bat,.cmd,.ps1,.vbs,.scr,.dll,.msi,.js,.jar,.com,.pif", "string", "Güvenlik", "Virüs veya zararlı kod riski nedeniyle yüklenmesi engellenen uzantılar."),
    FileCenterSettingDefinition("allowed_extensions", "İzin verilen dosya türleri", "", "string", "Güvenlik", "Boş bırakılırsa engellenenler dışındaki dosya türleri kabul edilir. Doluysa yalnızca listedekiler kabul edilir."),
    FileCenterSettingDefinition("security_scan_enabled", "Güvenlik taraması aktif", "true", "bool", "Güvenlik", "Dosyaların güvenlik kontrol sürecine alınmasını sağlar."),
    FileCenterSettingDefinition("auto_scan_on_upload_enabled", "Yükleme sonrası otomatik tarama", "true", "bool", "Güvenlik", "Dosya yüklenir yüklenmez güvenlik kontrolü çalışır."),
    FileCenterSettingDefinition("quarantine_enabled", "Karantina aktif", "true", "bool", "Güvenlik", "Riskli dosyalar karantina alanına alınır."),
    FileCenterSettingDefinition("require_clean_before_download", "İndirmeden önce temiz tarama zorunlu", "true", "bool", "Güvenlik", "Güvenlik taraması tamamlanmadan dosya indirilmesini engeller."),
    FileCenterSettingDefinition("quota_policy_enabled", "Kota politikası aktif", "true", "bool", "Kota", "Kullanıcı/birim/rol bazlı kota politikalarını etkinleştirir."),
    FileCenterSettingDefinition("default_user_storage_gb", "Varsayılan kullanıcı kotası", "25", "float", "Kota", "Kullanıcı başı varsayılan depolama alanı, GB."),
    FileCenterSettingDefinition("default_unit_storage_gb", "Varsayılan birim kotası", "250", "float", "Kota", "Birim başı varsayılan depolama alanı, GB."),
    FileCenterSettingDefinition("quota_warning_percent", "Kota uyarı eşiği", "80", "int", "Kota", "Kota kullanım uyarısı için yüzde eşiği."),
    FileCenterSettingDefinition("quota_hard_stop_enabled", "Kota dolunca yüklemeyi durdur", "false", "bool", "Kota", "Kota dolduğunda yeni yüklemeyi engeller."),
    FileCenterSettingDefinition("chunk_upload_enabled", "Parçalı yükleme aktif", "true", "bool", "Büyük Dosya", "Büyük dosyalar için parçalı yükleme altyapısını etkinleştirir."),
    FileCenterSettingDefinition("chunk_upload_real_enabled", "Gerçek parçalı yükleme aktif", "true", "bool", "Büyük Dosya", "Gerçek parça yükleme, devam etme ve birleştirme işlemlerini etkinleştirir."),
    FileCenterSettingDefinition("default_chunk_mb", "Varsayılan parça boyutu", "10", "float", "Büyük Dosya", "Parçalı yüklemede varsayılan parça boyutu, MB."),
    FileCenterSettingDefinition("chunk_min_mb", "En küçük parça boyutu", "1", "float", "Büyük Dosya", "Parçalı yüklemede kabul edilen en küçük parça, MB. Bundan küçük bir dosya tek parça olarak yüklenir."),
    FileCenterSettingDefinition("chunk_max_mb", "En büyük parça boyutu", "100", "float", "Büyük Dosya", "Parçalı yüklemede kabul edilen en büyük parça, MB. Yükleme isteği gövde sınırını (UPLOAD_MAX_CONTENT_LENGTH) aşamaz."),
    FileCenterSettingDefinition("chunk_max_parts", "En fazla parça sayısı", "10000", "int", "Büyük Dosya", "Bir parçalı yükleme oturumundaki en fazla parça sayısı."),
    FileCenterSettingDefinition("chunk_max_open_sessions", "Kullanıcı başına açık yükleme oturumu", "3", "int", "Büyük Dosya", "Bir kullanıcının aynı anda tamamlanmamış parçalı yükleme oturumu sayısı. Süresi dolan oturumlar sayılmaz, geçici dosyaları silinir. Toplam dosya boyutu Tek dosya sınırını aşamaz."),
    FileCenterSettingDefinition("mail_enabled", "E-posta gönderimi aktif", "false", "bool", "E-posta", "Dosya isteği e-posta gönderimini etkinleştirir."),
    FileCenterSettingDefinition("automatic_reminders_enabled", "Otomatik hatırlatma aktif", "false", "bool", "E-posta", "Son tarih yaklaşınca otomatik hatırlatma scriptinin çalışmasına izin verir."),
]


def _table_ready() -> bool:
    try:
        FileCenterSetting.query.limit(1).all()
        return True
    except (OperationalError, ProgrammingError):
        return False
    except Exception:
        return False


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "evet", "on", "açık", "acik"}


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "evet", "on", "açık", "acik"}


def _definition(key: str) -> FileCenterSettingDefinition | None:
    return next((item for item in SETTING_DEFINITIONS if item.key == key), None)


def ensure_file_center_settings_defaults(actor_user_id: int | None = None) -> dict[str, int]:
    created = 0
    updated = 0
    for item in SETTING_DEFINITIONS:
        row = FileCenterSetting.query.filter_by(key=item.key).one_or_none()
        if row is None:
            db.session.add(FileCenterSetting(
                key=item.key,
                value=item.value,
                value_type=item.value_type,
                group_key=item.group_key,
                label=item.label,
                description=item.description,
                updated_by_user_id=actor_user_id,
            ))
            created += 1
        else:
            changed = False
            for attr in ("label", "value_type", "group_key", "description"):
                new_value = getattr(item, attr)
                if getattr(row, attr) != new_value:
                    setattr(row, attr, new_value)
                    changed = True
            if changed:
                row.updated_by_user_id = actor_user_id
                updated += 1
    return {"created": created, "updated": updated}


def get_setting_raw(key: str, default: Any = None) -> Any:
    if not _table_ready():
        return default
    row = FileCenterSetting.query.filter_by(key=key, is_active=True).one_or_none()
    if row is None:
        return default
    return row.value


def get_str_setting(key: str, default: str = "") -> str:
    value = get_setting_raw(key, default)
    return str(value if value is not None else default)


def get_bool_setting(key: str, default: bool = False) -> bool:
    return parse_bool(get_setting_raw(key, default), default)


def get_int_setting(key: str, default: int = 0) -> int:
    try:
        return int(float(get_setting_raw(key, default)))
    except Exception:
        return int(default)


def get_float_setting(key: str, default: float = 0.0) -> float:
    try:
        return float(get_setting_raw(key, default))
    except Exception:
        return float(default)


def settings_grouped() -> dict[str, list[FileCenterSetting]]:
    ensure_file_center_settings_defaults()
    rows = FileCenterSetting.query.order_by(FileCenterSetting.group_key.asc(), FileCenterSetting.id.asc()).all()
    grouped: dict[str, list[FileCenterSetting]] = {}
    for row in rows:
        grouped.setdefault(row.group_key or "Genel", []).append(row)
    return grouped


def update_settings_from_form(form, actor_user_id: int | None = None) -> int:
    ensure_file_center_settings_defaults(actor_user_id=actor_user_id)
    changed = 0
    for item in SETTING_DEFINITIONS:
        row = FileCenterSetting.query.filter_by(key=item.key).one_or_none()
        if row is None:
            continue
        if row.value_type == "bool":
            new_value = "true" if form.get(item.key) in {"on", "true", "1", "yes"} else "false"
        else:
            new_value = str(form.get(item.key, row.value or item.value)).strip()
        if (row.value or "") != new_value:
            row.value = new_value
            row.updated_by_user_id = actor_user_id
            row.updated_at = utc_now()
            changed += 1
    return changed


def setting_to_display_value(row: FileCenterSetting) -> str:
    if row.value_type == "bool":
        return "Açık" if parse_bool(row.value) else "Kapalı"
    return row.value or ""
