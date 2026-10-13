from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
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

# Read compatibility for existing permission keys. All three consumers resolve these
# aliases identically; a manual alias must survive creation of a default seed row.
_ASSISTANT_FEATURE_ALIASES = {
    "assistant_module": frozenset({"assistant_module", "sanal_asistan", "sanal_asistan_modulu", "sanal_asistan_modülü", "assistant", "asistan", "ai_agent", "ai_agent_module", "virtual_assistant", "guvenli_sanal_asistan", "güvenli_sanal_asistan"}),
    "ai_agent_panel": frozenset({"ai_agent_panel", "assistant_panel", "asistan_paneli", "assistant_center"}),
    "ai_agent_knowledge": frozenset({"ai_agent_knowledge", "ai_teaching_center", "assistant_knowledge", "asistan_bilgi_bankasi", "asistan_bilgi_bankası"}),
    "ai_agent_teaching_center": frozenset({"ai_agent_teaching_center", "assistant_teaching_center", "asistan_ogretim_merkezi", "asistan_öğretim_merkezi"}),
}
_ASSISTANT_ALIAS_TARGETS = {alias: feature for feature, aliases in _ASSISTANT_FEATURE_ALIASES.items() for alias in aliases}
_ASSISTANT_KEY_PREFIXES = ("assistant.", "sanal_asistan.", "assistant_", "sanal_asistan_", "module_", "menu_", "role_matrix_")


def canonical_assistant_feature_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key in _ASSISTANT_ALIAS_TARGETS:
        return _ASSISTANT_ALIAS_TARGETS[key]
    for prefix in _ASSISTANT_KEY_PREFIXES:
        if key.startswith(prefix):
            tail = key[len(prefix):]
            if tail in _ASSISTANT_ALIAS_TARGETS or tail.startswith(("assistant_", "ai_agent_")):
                return _ASSISTANT_ALIAS_TARGETS.get(tail, tail)
    return key


@lru_cache(maxsize=128)
def assistant_feature_aliases(feature_key: str) -> frozenset[str]:
    feature = canonical_assistant_feature_key(feature_key)
    aliases = _ASSISTANT_FEATURE_ALIASES.get(feature, frozenset({feature}))
    return aliases | frozenset(prefix + alias for prefix in _ASSISTANT_KEY_PREFIXES for alias in aliases)


def assistant_feature_row_priority(key: Any, source_type: Any, feature_key: str) -> int:
    """Manual exact, manual alias, seed exact, seed alias. ID breaks ties newest first."""
    return (2 if source_type == "seed" else 0) + (0 if str(key or "").strip().lower() == feature_key else 1)

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


def assistant_enabled_for_value(value: Any) -> bool:
    """An explicit missing or malformed flag cannot enable assistant access."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "t", "on", "yes", "y", "evet", "aktif", "active",
        "enabled", "show", "visible", "izinli",
    }


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
    return visible_roles_for_value(value)


def visible_roles_for_value(value: Any) -> set[str]:
    """One parser for consumers and writers: missing uses install defaults; explicit empty,
    unknown or malformed configuration grants nothing. Comma, semicolon and line breaks
    are separators; whitespace inside a token never creates a role.
    """
    if value is None:
        return set(ASSISTANT_ALLOWED_ROLES)
    if not isinstance(value, str):
        return set()
    tokens = [item.strip().lower().replace("-", "_") for item in re.split(r"[,;\r\n]", value) if item.strip()]
    known = set(ASSISTANT_ALLOWED_ROLES) | {"personel", "kullanici"}
    if not tokens or any(token not in known for token in tokens):
        return set()
    return set(tokens)


def current_visible_roles() -> set[str]:
    return visible_roles_for_value(_setting_rows().get("visible_roles"))


def get_assistant_settings() -> dict[str, Any]:
    rows = _setting_rows()
    merged = dict(ASSISTANT_DEFAULT_SETTINGS)
    merged.update({key: value for key, value in rows.items() if key in ASSISTANT_DEFAULT_SETTINGS})

    return {
        "enabled": assistant_enabled_for_value(merged.get("enabled")),
        "summary_enabled": _bool_value(merged.get("summary_enabled"), True),
        "actions_enabled": _bool_value(merged.get("actions_enabled"), True),
        "topics_enabled": _bool_value(merged.get("topics_enabled"), True),
        "safety_note_enabled": _bool_value(merged.get("safety_note_enabled"), True),
        "count_summary_enabled": _bool_value(merged.get("count_summary_enabled"), True),
        "safe_links_enabled": _bool_value(merged.get("safe_links_enabled"), True),
        "visible_roles": ",".join(sorted(visible_roles_for_value(merged.get("visible_roles")))) or "__none__",
        "settings_source": "module_settings" if rows else "defaults",
    }


def can_manage_assistant_settings(user: Any) -> bool:
    role = _normalize_role(getattr(user, "role", ""))
    return role in ASSISTANT_MANAGER_ROLES


def is_assistant_visible_for_user(user: Any, settings: dict[str, Any] | None = None) -> bool:
    settings = settings or get_assistant_settings()
    if not assistant_enabled_for_value(settings.get("enabled", True)):
        return False
    allowed_roles = visible_roles_for_value(settings.get("visible_roles"))
    role = _normalize_role(getattr(user, "role", ""))
    return role in allowed_roles


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
