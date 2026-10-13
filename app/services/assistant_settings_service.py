from __future__ import annotations

import unicodedata
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

"""BYS360 Asistan ayar okuma servisi.

Bu servis, Asistan davranışını mevcut module_settings tablosundan okur.
Yeni tablo veya migrasyon gerektirmez. Ayar yoksa güvenli varsayılanlarla çalışır.
BYS360 Asistan idari karar üretmez; bu servis yalnızca görünürlük ve davranış bayraklarını yönetir.
"""

ASSISTANT_MODULE_KEY = "assistant"
ASSISTANT_SETTINGS_URL = "/settings#assistant-role-policy"

ASSISTANT_ALLOWED_ROLES = (
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "birim_sorumlusu",
    "koordinator",
)

ASSISTANT_MANAGER_ROLES = {
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
}

ASSISTANT_DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "summary_enabled": True,
    "actions_enabled": True,
    "topics_enabled": True,
    "safety_note_enabled": True,
    "count_summary_enabled": True,
    "safe_links_enabled": True,
    "visible_roles": ",".join(ASSISTANT_ALLOWED_ROLES),
}


def _normalize_role(value: Any) -> str:
    raw = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace(" ", "_").replace("-", "_")


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "on", "yes", "evet", "aktif", "enabled"}:
        return True
    if normalized in {"0", "false", "off", "no", "hayir", "hayır", "pasif", "disabled"}:
        return False
    return default


def _setting_rows() -> dict[str, str]:
    try:
        from app.models import ModuleSetting

        rows = ModuleSetting.query.filter_by(module_key=ASSISTANT_MODULE_KEY).all()
        return {str(row.setting_key): str(row.value_text or "") for row in rows}
    except (SQLAlchemyError, RuntimeError, AttributeError):
        try:
            db.session.rollback()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/assistant_settings_service.py")
        return {}


def _parse_roles(value: Any) -> set[str]:
    raw = str(value or "").replace("\n", ",").replace(";", ",")
    roles = {_normalize_role(item) for item in raw.split(",") if str(item).strip()}
    return {role for role in roles if role}


def visible_roles_for_value(value: Any) -> set[str]:
    """The roles a stored ``visible_roles`` value opens, read as get_assistant_settings reads it
    (blank means the allowed roles; ``__none__`` opens none). R05c compares these sets."""
    roles = _parse_roles(value) or set(ASSISTANT_ALLOWED_ROLES)
    return {role for role in roles if role != "__none__"}


def current_visible_roles() -> set[str]:
    return visible_roles_for_value(_setting_rows().get("visible_roles"))


def get_assistant_settings() -> dict[str, Any]:
    rows = _setting_rows()
    merged = dict(ASSISTANT_DEFAULT_SETTINGS)
    merged.update({key: value for key, value in rows.items() if key in ASSISTANT_DEFAULT_SETTINGS})

    return {
        "enabled": _bool_value(merged.get("enabled"), True),
        "summary_enabled": _bool_value(merged.get("summary_enabled"), True),
        "actions_enabled": _bool_value(merged.get("actions_enabled"), True),
        "topics_enabled": _bool_value(merged.get("topics_enabled"), True),
        "safety_note_enabled": _bool_value(merged.get("safety_note_enabled"), True),
        "count_summary_enabled": _bool_value(merged.get("count_summary_enabled"), True),
        "safe_links_enabled": _bool_value(merged.get("safe_links_enabled"), True),
        "visible_roles": ",".join(sorted(_parse_roles(merged.get("visible_roles")) or set(ASSISTANT_ALLOWED_ROLES))),
        "settings_source": "module_settings" if rows else "defaults",
    }


def can_manage_assistant_settings(user: Any) -> bool:
    role = _normalize_role(getattr(user, "role", ""))
    return role in ASSISTANT_MANAGER_ROLES


def is_assistant_visible_for_user(user: Any, settings: dict[str, Any] | None = None) -> bool:
    settings = settings or get_assistant_settings()
    if not _bool_value(settings.get("enabled"), True):
        return False
    allowed_roles = _parse_roles(settings.get("visible_roles")) or set(ASSISTANT_ALLOWED_ROLES)
    role = _normalize_role(getattr(user, "role", ""))
    return role in allowed_roles or can_manage_assistant_settings(user)


def build_assistant_runtime_for_user(user: Any) -> dict[str, Any]:
    settings = get_assistant_settings()
    visible = is_assistant_visible_for_user(user, settings)
    return {
        **settings,
        "visible_for_user": bool(visible),
        "can_manage": can_manage_assistant_settings(user),
        "settings_url": ASSISTANT_SETTINGS_URL,
        "mode_label": "Kurumsal rehberlik ve güvenli yönlendirme",
        "status_label": "Yetki kontrollü",
        "module_key": ASSISTANT_MODULE_KEY,
    }


def filter_topics_by_settings(topics: list[dict[str, str]], settings: dict[str, Any]) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for topic in topics or []:
        question = str(topic.get("question") or "").lower()
        label = str(topic.get("label") or "").lower()
        if not _bool_value(settings.get("summary_enabled"), True) and ("özet" in question or "ozet" in question or "özet" in label):
            continue
        if not _bool_value(settings.get("actions_enabled"), True) and ("önce" in question or "nereye" in question or "yönlendirme" in label):
            continue
        filtered.append(topic)
    return filtered


__all__ = [
    "ASSISTANT_MODULE_KEY",
    "ASSISTANT_SETTINGS_URL",
    "build_assistant_runtime_for_user",
    "can_manage_assistant_settings",
    "filter_topics_by_settings",
    "get_assistant_settings",
    "is_assistant_visible_for_user",
]
