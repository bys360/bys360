"""Menü matrisi yetki tavanı (P0, 17 Ekim 2026).

Kişi bazlı menü kaydı canlı menüde kurumsal rol-menü politikasının üstüne yazılır ve yalnız
``menu_key_required`` ile korunan rotalarda gerçek erişim verir. Bu yüzden gerçek admin dışındaki
herkes, bir hesaba (kişi matrisi, toplu profil, geri alma) veya bir rol varsayılanına yalnız o
rolün kurumsal tanımın izin verdiği anahtarları **yeni** açabilir:

- menü kaydı: ``admin_only`` ve ``required_roles`` (``_role_allowed_for_menu``);
- rol-menü politikası: birleştirilmiş ``PHASE3_PERFORMANCE_MENU_POLICY`` (anahtar politikada yoksa
  yalnız menü kaydı belirleyicidir).

Hesapta zaten görünen anahtarlar yeniden kaydedilebilir; daraltma her zaman serbesttir. Açık izinler
(``personnel_read_all``, ``support_all``) mevcut K5q/B1F1 kuralıyla ayrıca korunur. Tanınmayan
anahtar hiçbir role açılamaz (fail-closed).
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.route_support import normalize_role_name
from app.services.personnel_read_grant import EXPLICIT_GRANT_KEYS

GRANT_CEILING_REFUSAL = "settings_grant_ceiling"


def _menu_item(key: str) -> dict[str, Any] | None:
    from app.services.settings.effective_menu import _active_menu_items

    for item in _active_menu_items() or []:
        if str((item or {}).get("key") or "").strip() == key:
            return item
    return None


def role_may_hold_menu_key(role: Any, key: Any) -> bool:
    """Kurumsal tanım bu rolün bu menü anahtarına sahip olmasına izin veriyor mu?"""
    from app.services.settings.effective_menu import PHASE3_PERFORMANCE_MENU_POLICY
    from app.services.settings.effective_menu_parts.apply_context import _role_allowed_for_menu

    role_name = normalize_role_name(role)
    menu_key = str(key or "").strip()
    item = _menu_item(menu_key)
    if not item or not _role_allowed_for_menu(item, role_name):
        return False
    allowed = PHASE3_PERFORMANCE_MENU_POLICY.get(menu_key)
    return allowed is None or role_name in {normalize_role_name(value) for value in allowed}


def grant_ceiling_violations(role: Any, requested_keys: Iterable[Any], already_visible: Iterable[Any]) -> set[str]:
    """Yeni açılmak istenen ve rolün kurumsal tanımının üstünde kalan anahtarlar."""
    visible = {str(key).strip() for key in already_visible or ()}
    requested = {str(key).strip() for key in requested_keys or () if str(key).strip()}
    return {
        key
        for key in requested - visible
        if key not in EXPLICIT_GRANT_KEYS and not role_may_hold_menu_key(role, key)
    }
