"""Menü matrisi yetki tavanı (P0, 17 Ekim 2026).

Kişi bazlı menü kaydı canlı menüde kurumsal rol-menü politikasının üstüne yazılır ve yalnız
``menu_key_required`` ile korunan rotalarda gerçek erişim verir. Bu yüzden gerçek admin dışındaki
herkes, bir hesaba (kişi matrisi, toplu profil, geri alma) veya bir rol varsayılanına yalnız o
rolün kurumsal tanımın izin verdiği anahtarları **yeni** açabilir:

- menü kaydı: ``admin_only`` ve ``required_roles`` (``_role_allowed_for_menu``);
- rol-menü politikası: birleştirilmiş ``PHASE3_PERFORMANCE_MENU_POLICY`` (anahtar politikada yoksa
  yalnız menü kaydı belirleyicidir).

Hesapta zaten görünen anahtarlar yeniden kaydedilebilir; daraltma her zaman serbesttir. Açık izinler
mevcut K5q/B1F1 kuralıyla ayrıca korunur; çağıran taraf onları ``exempt_keys`` ile geçirir (bu
modül, R07 sözleşmesi gereği açık izin sabitlerine doğrudan başvurmaz). Tanınmayan anahtar hiçbir
role açılamaz (fail-closed).

K2 (18 Ekim 2026): aynı tanım erişim anında da uygulanır. Kişi kaydı rol tanımının dışında bir anahtarı
yalnız onaylı mekanizmayla açar: gerçek admin'in verdiği istisna (``ADMIN_EXCEPTION_SOURCE``) ve
çağıranın ``exempt_keys`` ile geçirdiği açık izinler. Eski kayıtlar (``user_override``, ``rollback``)
rol tanımının dışında erişim vermez.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from app.route_support import normalize_role_name

logger = logging.getLogger(__name__)

GRANT_CEILING_REFUSAL = "settings_grant_ceiling"
# K2: gerçek admin'in kişi matrisinden rol tanımının dışında verdiği istisna (mevcut source_type sütunu).
ADMIN_EXCEPTION_SOURCE = "admin_exception"


def _menu_item(key: str) -> dict[str, Any] | None:
    from app.services.settings.effective_menu import _active_menu_items

    for item in _active_menu_items() or []:
        if str((item or {}).get("key") or "").strip() == key:
            return item
    return None


def _role_may_hold(role_name: str, menu_key: str, item: dict[str, Any] | None) -> bool:
    from app.services.settings.effective_menu import PHASE3_PERFORMANCE_MENU_POLICY
    from app.services.settings.effective_menu_parts.apply_context import _role_allowed_for_menu

    if not item or not _role_allowed_for_menu(item, role_name):
        return False
    allowed = PHASE3_PERFORMANCE_MENU_POLICY.get(menu_key)
    return allowed is None or role_name in {normalize_role_name(value) for value in allowed}


def role_may_hold_menu_key(role: Any, key: Any) -> bool:
    """Kurumsal tanım bu rolün bu menü anahtarına sahip olmasına izin veriyor mu?"""
    menu_key = str(key or "").strip()
    return _role_may_hold(normalize_role_name(role), menu_key, _menu_item(menu_key))


def grant_ceiling_violations(
    role: Any, requested_keys: Iterable[Any], already_visible: Iterable[Any], *, exempt_keys: Iterable[Any] = ()
) -> set[str]:
    """Yeni açılmak istenen ve rolün kurumsal tanımının üstünde kalan anahtarlar."""
    visible = {str(key).strip() for key in already_visible or ()}
    exempt = {str(key).strip() for key in exempt_keys or ()}
    requested = {str(key).strip() for key in requested_keys or () if str(key).strip()}
    return {key for key in requested - visible - exempt if not role_may_hold_menu_key(role, key)}


def apply_legacy_override_ceiling(
    visibility: dict[str, bool],
    user: Any,
    *,
    rebuild: Callable[[], dict[str, bool]],
    exempt_keys: Iterable[Any] = (),
) -> dict[str, bool]:
    """K2: kişi kaydının açtığı, rolün kurumsal tanımının dışındaki anahtarı erişim anında kapatır.

    Yalnız kişi kaydı olmadan görünmeyecek anahtarlar kapatılır (``rebuild`` haritayı kişi kayıtları
    okunmadan yeniden üretir; adayı olmayan hesapta hiç çağrılmaz). Onaylı istisnalar korunur: gerçek
    admin'in verdiği kayıt (``ADMIN_EXCEPTION_SOURCE``), ``exempt_keys`` (açık izinler, kendi denetimleri)
    ve gerçek admin hesabı. Satır okunamazsa kayıt kaynağı bilinmez; istisna tanınmaz (fail-closed).
    Hiçbir satır değiştirilmez.
    """
    from sqlalchemy.exc import SQLAlchemyError

    from app.services.account_change_guard import is_real_admin
    from app.services.settings.effective_menu import _active_menu_items
    from app.services.settings.effective_menu_parts.override_scope import (
        suppress_user_overrides,
        user_overrides_suppressed,
    )

    if user is None or getattr(user, "id", None) is None or user_overrides_suppressed() or is_real_admin(user):
        return visibility
    exempt = {str(key).strip() for key in exempt_keys or ()}
    try:
        from app.models import UserMenuPermission

        rows = UserMenuPermission.query.filter(
            UserMenuPermission.user_id == user.id, UserMenuPermission.is_visible.is_(True)
        ).all()
        opened = {str(row.menu_key or "").strip() for row in rows if (row.source_type or "") != ADMIN_EXCEPTION_SOURCE}
    except SQLAlchemyError:
        logger.exception("BYS360 K2 legacy override lookup failed; no per-user exception is recognised.")
        _safe_rollback()
        opened = {key for key, visible in visibility.items() if visible}
    items = {str((item or {}).get("key") or "").strip(): item for item in _active_menu_items() or []}
    role_name = normalize_role_name(getattr(user, "role", ""))
    candidates = {
        key for key in opened - exempt
        if visibility.get(key) and not _role_may_hold(role_name, key, items.get(key))
    }
    if not candidates:
        return visibility
    baseline = _request_baseline(user, rebuild, suppress_user_overrides)
    for key in candidates:
        if not baseline.get(key):
            visibility[key] = False
    return visibility


def _request_baseline(user: Any, rebuild: Callable[[], dict[str, bool]], suppress: Callable[[], Any]) -> dict[str, bool]:
    """Kişi kaydı olmayan temel harita; aynı istekte aynı hesap (rol, birim) için bir kez üretilir."""
    from flask import g, has_request_context

    cache_key = (getattr(user, "id", None), str(getattr(user, "role", "") or ""), str(getattr(user, "birim", "") or ""))
    cache = getattr(g, "_bys360_k2_baselines", None) if has_request_context() else None
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    with suppress():
        baseline = dict(rebuild() or {})
    if has_request_context():
        if cache is None:
            cache = {}
            g._bys360_k2_baselines = cache
        cache[cache_key] = baseline
    return baseline


def _safe_rollback() -> None:
    try:
        from app.extensions import db

        db.session.rollback()
    except Exception:  # pragma: no cover - geri alma da başarısızsa yapılacak bir şey yok
        logger.exception("BYS360 K2 rollback after lookup failure failed.")
