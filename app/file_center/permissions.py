"""BYS360 Dosya Merkezi rol matrisi ve yetki yardımcıları.

V1K-D:
- Yetkiler veritabanındaki file_center_role_permissions tablosundan okunur.
- Tablo hazır değilse güvenli varsayılan/fallback kuralları kullanılır.
- Menü görünürlüğü tek başına güvenlik değildir; route seviyesinde de aynı kontroller çalışır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models.file_center_models import FileCenterRolePermission

PERMISSION_FIELDS: tuple[str, ...] = (
    "can_use",
    "can_upload_files",
    "can_download_files",
    "can_create_guest_links",
    "can_create_guest_upload_requests",
    "can_view_transfers",
    "can_view_requests",
    "can_use_chunk_upload",
    "can_view_logs",
    "can_manage_security",
    "can_manage_admin",
    "can_manage_maintenance",
    "can_manage_settings",
    "can_manage_quota_policy",
    "can_manage_role_matrix",
)


@dataclass(frozen=True)
class RolePermissionDefault:
    role_key: str
    role_label: str
    permissions: dict[str, bool]
    description: str = ""


def _perms(**kwargs: bool) -> dict[str, bool]:
    base = {field: False for field in PERMISSION_FIELDS}
    base.update(kwargs)
    return base


DEFAULT_ROLE_MATRIX: tuple[RolePermissionDefault, ...] = (
    RolePermissionDefault(
        "personel",
        "Personel",
        _perms(
            can_use=True,
            can_upload_files=True,
            can_download_files=True,
            can_create_guest_links=True,
            can_create_guest_upload_requests=True,
            can_view_transfers=True,
            can_view_requests=True,
            can_use_chunk_upload=True,
        ),
        "Kendi dosyalarını, kendi transferlerini ve kendi dosya isteklerini yönetir.",
    ),
    RolePermissionDefault(
        "yonetici",
        "Yönetici / Amir",
        _perms(
            can_use=True,
            can_upload_files=True,
            can_download_files=True,
            can_create_guest_links=True,
            can_create_guest_upload_requests=True,
            can_view_transfers=True,
            can_view_requests=True,
            can_use_chunk_upload=True,
            can_view_logs=True,
        ),
        "Birim yöneticisi düzeyinde takip ve kayıt görme yetkisi.",
    ),
    RolePermissionDefault(
        "dosya_merkezi_yetkilisi",
        "Dosya Merkezi Yetkilisi",
        _perms(
            can_use=True,
            can_upload_files=True,
            can_download_files=True,
            can_create_guest_links=True,
            can_create_guest_upload_requests=True,
            can_view_transfers=True,
            can_view_requests=True,
            can_use_chunk_upload=True,
            can_view_logs=True,
            can_manage_security=True,
            can_manage_admin=True,
            can_manage_quota_policy=True,
        ),
        "Dosya Merkezi operasyon, kota, güvenlik ve denetim süreçlerini yönetir.",
    ),
    RolePermissionDefault(
        "sistem_yoneticisi",
        "Sistem Yöneticisi",
        _perms(**{field: True for field in PERMISSION_FIELDS}),
        "Sistem ayarları, bakım ve rol matrisi dahil tam yetki.",
    ),
    RolePermissionDefault(
        "admin",
        "Admin",
        _perms(**{field: True for field in PERMISSION_FIELDS}),
        "Teknik/yönetim admin kullanıcısı için tam yetki.",
    ),
)

ADMIN_ROLE_HINTS = {
    "admin",
    "superadmin",
    "sistem_yoneticisi",
    "sistem yoneticisi",
    "sistem yöneticisi",
    "dosya_merkezi_yetkilisi",
    "dosya merkezi yetkilisi",
    "file_center_admin",
}
MANAGER_HINTS = {"baskan", "başkan", "grup_baskani", "grup başkanı", "koordinator", "koordinatör", "mudur", "müdür", "amir", "yonetici", "yönetici"}


def _normalize(value: Any) -> str:
    # BYS360 DEFECT AQ: 'İ'.lower() Python'da tek bir 'i' değil, 'i' +
    # COMBINING DOT ABOVE (U+0307) olmak üzere İKİ kod noktası üretir --
    # bu yüzden .lower() önce çalışırsa aşağıdaki table'daki 'İ' anahtarı
    # asla eşleşmez. 'İ' burada .lower() çağrılmadan ÖNCE, tek kod noktalı
    # haldeyken ayrı olarak 'i'ye çevrilir.
    text = str(value or "").strip().replace("İ", "i").lower()
    table = str.maketrans({
        "ı": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
        "ş": "s", "Ş": "s", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    })
    text = text.translate(table)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _user_text(user=None) -> str:
    user = user or current_user
    attrs = (
        "role", "role_key", "role_name", "role_label", "title", "position", "job_title",
        "username", "email", "department", "unit", "unit_name",
    )
    return " ".join(str(getattr(user, attr, "") or "") for attr in attrs)


def role_key(user=None) -> str:
    return _normalize(_user_text(user))


# BYS360 DEFECT AQ: _admin_like_text / _manager_like_text / _effective_role_key
# / _permission_from_matrix'in DB satırı bulunamadığında düştüğü fallback
# taraması önceden role_key(user)'ın (12 alanı -- username, email, department,
# unit dahil -- TEK bir metinde birleştiren) döndürdüğü metin üzerinde "in"
# alt dize eşleştirmesi yapıyordu. Bu, ör. email'i "office-admin@..." olan
# veya department'ı "Sistem Yönetimi Destek Birimi" olan sıradan bir
# "personel" kullanıcısına tam Dosya Merkezi admin yetkisi (rol matrisini
# DÜZENLEME dahil) veriyordu. Artık yalnızca gerçek rol/unvan alanları
# (username/email/department/unit HARİÇ) tek tek normalize edilip bu
# kümelerle TAM eşleştiriliyor.
#
# F07a / D3 (onaylı politika, 2026-10-09): role_label, title, position ve
# job_title görünen ad/unvan alanlarıdır; tek başına yetki veremez. Örn.
# role="personel" ve role_label="Sistem Yöneticisi" olan bir kullanıcı tam
# Dosya Merkezi admini (başkasının özel dosyasını indirme/silme/paylaşma)
# oluyordu. Rol kimliği artık yalnız saklanan rol alanlarıdır.
_ROLE_IDENTITY_ATTRS = ("role", "role_key", "role_name")


def _user_role_values(user=None) -> set[str]:
    user = user or current_user
    return {
        _normalize(getattr(user, attr, ""))
        for attr in _ROLE_IDENTITY_ATTRS
        if getattr(user, attr, "")
    }


def _table_ready() -> bool:
    try:
        FileCenterRolePermission.query.limit(1).all()
        return True
    except (SQLAlchemyError, RuntimeError):
        return False


_ADMIN_ROLE_HINT_VALUES = frozenset(_normalize(hint) for hint in ADMIN_ROLE_HINTS)
_MANAGER_HINT_VALUES = frozenset(_normalize(hint) for hint in MANAGER_HINTS)


def _admin_like_text(user=None) -> bool:
    return bool(_user_role_values(user) & _ADMIN_ROLE_HINT_VALUES)


def _manager_like_text(user=None) -> bool:
    return bool(_user_role_values(user) & _MANAGER_HINT_VALUES)


def _default_by_key(role_key_value: str) -> RolePermissionDefault | None:
    key = _normalize(role_key_value)
    return next((item for item in DEFAULT_ROLE_MATRIX if item.role_key == key), None)


def _effective_role_key(user=None) -> str:
    role_values = _user_role_values(user)
    # Önce daha özel roller.
    priority = ("admin", "sistem_yoneticisi", "dosya_merkezi_yetkilisi", "yonetici", "personel")
    for key in priority:
        if key in role_values:
            return key
    if _manager_like_text(user):
        return "yonetici"
    if _admin_like_text(user):
        return "admin"
    return "personel"


def _permission_from_matrix(user, field: str) -> bool | None:
    if field not in PERMISSION_FIELDS:
        return None
    if not getattr(user, "is_authenticated", False):
        return False
    try:
        if not _table_ready():
            return None
        key = _effective_role_key(user)
        row = FileCenterRolePermission.query.filter_by(role_key=key, is_active=True).one_or_none()
        if row is None:
            role_values = _user_role_values(user)
            rows = FileCenterRolePermission.query.filter_by(is_active=True).all()
            for candidate in rows:
                ckey = _normalize(candidate.role_key)
                clabel = _normalize(candidate.role_label)
                if (ckey and ckey in role_values) or (clabel and clabel in role_values):
                    row = candidate
                    break
        if row is None:
            return None
        return bool(getattr(row, field, False))
    except (SQLAlchemyError, RuntimeError):
        return None


def _permission(user=None, field: str = "can_use", default: bool = False) -> bool:
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return False
    value = _permission_from_matrix(user, field)
    if value is not None:
        return bool(value)
    if _admin_like_text(user):
        return True
    default_role = _default_by_key(_effective_role_key(user))
    if default_role is not None:
        return bool(default_role.permissions.get(field, default))
    return bool(default)


def ensure_file_center_role_matrix_defaults(actor_user_id: int | None = None) -> dict[str, int]:
    created = 0
    updated = 0
    for item in DEFAULT_ROLE_MATRIX:
        row = FileCenterRolePermission.query.filter_by(role_key=item.role_key).one_or_none()
        if row is None:
            db.session.add(FileCenterRolePermission(
                role_key=item.role_key,
                role_label=item.role_label,
                description=item.description,
                updated_by_user_id=actor_user_id,
                **item.permissions,
            ))
            created += 1
            continue
        changed = False
        if row.role_label != item.role_label:
            row.role_label = item.role_label
            changed = True
        if (row.description or "") != item.description:
            row.description = item.description
            changed = True
        for field, value in item.permissions.items():
            # Var olan satırda kullanıcı değişikliklerini ezmemek için sadece NULL/None durumda tamamla.
            if getattr(row, field, None) is None:
                setattr(row, field, bool(value))
                changed = True
        if changed:
            row.updated_by_user_id = actor_user_id
            row.updated_at = utc_now()
            updated += 1
    return {"created": created, "updated": updated}


def role_matrix_rows() -> list[FileCenterRolePermission]:
    return FileCenterRolePermission.query.order_by(FileCenterRolePermission.id.asc()).all()


def update_role_matrix_from_form(form, actor_user_id: int | None = None) -> int:
    ensure_file_center_role_matrix_defaults(actor_user_id=actor_user_id)
    changed = 0
    rows = FileCenterRolePermission.query.order_by(FileCenterRolePermission.id.asc()).all()
    for row in rows:
        prefix = f"role_{row.id}_"
        label = str(form.get(prefix + "role_label", row.role_label or "")).strip()
        description = str(form.get(prefix + "description", row.description or "")).strip()
        is_active = form.get(prefix + "is_active") in {"on", "true", "1", "yes"}
        if row.role_label != label:
            row.role_label = label
            changed += 1
        if (row.description or "") != description:
            row.description = description
            changed += 1
        if bool(row.is_active) != bool(is_active):
            row.is_active = bool(is_active)
            changed += 1
        for field in PERMISSION_FIELDS:
            new_value = form.get(prefix + field) in {"on", "true", "1", "yes"}
            if bool(getattr(row, field, False)) != bool(new_value):
                setattr(row, field, bool(new_value))
                changed += 1
        if changed:
            row.updated_by_user_id = actor_user_id
            row.updated_at = utc_now()

    new_role_key = _normalize(form.get("new_role_key"))
    new_role_label = str(form.get("new_role_label", "")).strip()
    if new_role_key and new_role_label:
        exists = FileCenterRolePermission.query.filter_by(role_key=new_role_key).one_or_none()
        if exists is None:
            db.session.add(FileCenterRolePermission(
                role_key=new_role_key,
                role_label=new_role_label,
                description=str(form.get("new_role_description", "")).strip(),
                can_use=True,
                can_upload_files=True,
                can_download_files=True,
                can_view_transfers=True,
                can_view_requests=True,
                updated_by_user_id=actor_user_id,
            ))
            changed += 1
    return changed


def is_file_center_admin(user=None) -> bool:
    return _permission(user, "can_manage_admin", default=_admin_like_text(user))


# F07b / D2 (onaylı politika, 2026-10-09): teknik roller (sistem_yoneticisi,
# system_admin) Dosya Merkezi'ni yönetir (panel, bakım, kota, güvenlik, ayarlar,
# rol matrisi, silme, bağlantı iptali) ama başka kullanıcının dosya içeriğini
# indiremez veya misafir bağlantısıyla dışarı paylaşamaz.
_TECHNICAL_ROLE_VALUES = frozenset(_normalize(role) for role in ("sistem_yoneticisi", "system_admin"))


def can_read_other_users_files(user=None) -> bool:
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return False
    if _user_role_values(user) & _TECHNICAL_ROLE_VALUES:
        return False
    return is_file_center_admin(user)


def is_file_center_manager(user=None) -> bool:
    user = user or current_user
    if is_file_center_admin(user):
        return True
    return _manager_like_text(user) or _permission(user, "can_view_logs", default=False)


def can_use_file_center(user=None) -> bool:
    return _permission(user, "can_use", default=True)


def can_upload_files(user=None) -> bool:
    return _permission(user, "can_upload_files", default=True)


def can_download_files(user=None) -> bool:
    return _permission(user, "can_download_files", default=True)


def can_create_guest_links(user=None) -> bool:
    return _permission(user, "can_create_guest_links", default=True)


def can_create_guest_upload_requests(user=None) -> bool:
    return _permission(user, "can_create_guest_upload_requests", default=True)


def can_view_transfers(user=None) -> bool:
    return _permission(user, "can_view_transfers", default=True)


def can_view_requests(user=None) -> bool:
    return _permission(user, "can_view_requests", default=True)


def can_use_chunk_upload(user=None) -> bool:
    return _permission(user, "can_use_chunk_upload", default=True)


def can_view_logs(user=None) -> bool:
    return _permission(user, "can_view_logs", default=False)


def can_manage_file_center_admin(user=None) -> bool:
    return _permission(user, "can_manage_admin", default=_admin_like_text(user))


def can_manage_file_center_settings(user=None) -> bool:
    return _permission(user, "can_manage_settings", default=_admin_like_text(user))


def can_manage_file_center_role_matrix(user=None) -> bool:
    return _permission(user, "can_manage_role_matrix", default=_admin_like_text(user))


def can_manage_file_center_security(user=None) -> bool:
    return _permission(user, "can_manage_security", default=_admin_like_text(user))


def can_manage_file_center_maintenance(user=None) -> bool:
    return _permission(user, "can_manage_maintenance", default=_admin_like_text(user))


def can_manage_file_center_quota_policy(user=None) -> bool:
    return _permission(user, "can_manage_quota_policy", default=_admin_like_text(user))


def menu_context(user=None) -> dict[str, bool]:
    user = user or current_user
    return {
        "can_use": can_use_file_center(user),
        "can_upload": can_upload_files(user),
        "can_download": can_download_files(user),
        "can_guest_links": can_create_guest_links(user),
        "can_guest_uploads": can_create_guest_upload_requests(user),
        "can_transfers": can_view_transfers(user),
        "can_requests": can_view_requests(user),
        "can_chunk_upload": can_use_chunk_upload(user),
        "can_logs": can_view_logs(user),
        "can_admin": can_manage_file_center_admin(user),
        "can_settings": can_manage_file_center_settings(user),
        "can_role_matrix": can_manage_file_center_role_matrix(user),
        "can_security": can_manage_file_center_security(user),
        "can_maintenance": can_manage_file_center_maintenance(user),
        "can_quota_policy": can_manage_file_center_quota_policy(user),
        "can_manager": is_file_center_manager(user),
    }
