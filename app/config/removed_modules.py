
"""Canlı öncesi kapsam dışı modül kararları.

Bu dosya Faz 1/2 overlay ile birlikte tek merkezli bir karar noktası sağlar.
Fiziksel söküm yapılmadan önce hangi modüllerin route, AI ve sayfa bağlamı
seviyesinde pasif kabul edildiği buradan okunur.
"""
from __future__ import annotations

REMOVED_MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "repository": ("repository", "belge_medya", "belge-medya", "belgemedya"),
    "education": ("education", "egitim", "eğitim", "egitim_isg", "eğitim_isg", "education_isg", "isg", "i̇sg", "isg_yonetimi"),
    "strategy": ("strategy", "strateji"),
    "portal": ("portal",),
}

REMOVED_MODULES: dict[str, bool] = {
    "repository": True,
    "education": True,
    "strategy": True,
    "portal": False,
}


def _normalize(name: str | None) -> str:
    return str(name or "").strip().lower().replace(" ", "_")


def _canonical_name(name: str | None) -> str:
    normalized = _normalize(name)
    for canonical, aliases in REMOVED_MODULE_ALIASES.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    return normalized


def is_module_removed(name: str | None) -> bool:
    canonical = _canonical_name(name)
    return bool(REMOVED_MODULES.get(canonical, False))


def is_removed(name: str | None) -> bool:
    return is_module_removed(name)


def get_removed_modules() -> dict[str, bool]:
    return dict(REMOVED_MODULES)
