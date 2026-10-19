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
# K13: role_menu_defaults rows written by the automatic seeder (manual saves write "manual", rollbacks "rollback").
SEED_SOURCE = "seed"
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
        sources = {str(row.menu_key or "").strip(): (row.source_type or "") for row in rows}
    except SQLAlchemyError:
        logger.exception("BYS360 K2 legacy override lookup failed; no per-user exception is recognised.")
        _safe_rollback()
        sources = {key: "" for key, visible in visibility.items() if visible}
    items = {str((item or {}).get("key") or "").strip(): item for item in _active_menu_items() or []}
    role_name = normalize_role_name(getattr(user, "role", ""))
    candidates = {
        key for key, source in sources.items()
        if visibility.get(key) and not _row_grant_recognised(role_name, key, source, items, exempt)
    }
    if not candidates:
        return visibility
    baseline = _request_baseline(user, rebuild, suppress_user_overrides)
    for key in candidates:
        if not baseline.get(key):
            visibility[key] = False
    return visibility


def _row_grant_recognised(role_name: str, key: str, source: str, items: dict[str, Any], exempt: set[str]) -> bool:
    """May an opening per-user row for ``key`` grant it? (K2 rule, shared by every menu map.)

    F: a per-user row never opens an admin_only screen to anyone but the real admin, an admin
    exception included; other keys keep the real admin's exception.
    """
    item = items.get(key)
    if key in exempt:
        return True
    if source == ADMIN_EXCEPTION_SOURCE and not (item or {}).get("admin_only"):
        return True
    return _role_may_hold(role_name, key, item)


def unrecognised_user_row_grants(user: Any, rows: Iterable[tuple[Any, Any, Any]], *, exempt_keys: Iterable[Any] = ()) -> set[str]:
    """K2-b: keys of opening per-user rows ``(menu_key, is_visible, source_type)`` that grant nothing.

    For menu maps outside build_menu_visibility_map that read user_menu_permissions themselves (the
    assistant map): such a row is ignored there exactly as the main map's ceiling closes it. Role
    defaults are untouched, so a key the role already has stays open. Closing rows always apply.
    """
    from app.services.account_change_guard import is_real_admin
    from app.services.settings.effective_menu import _active_menu_items

    if user is None or getattr(user, "id", None) is None or is_real_admin(user):
        return set()
    exempt = {str(key).strip() for key in exempt_keys or ()}
    items = {str((item or {}).get("key") or "").strip(): item for item in _active_menu_items() or []}
    role_name = normalize_role_name(getattr(user, "role", ""))
    refused = set()
    for menu_key, is_visible, source_type in rows or ():
        key = str(menu_key or "").strip()
        if key and is_visible and not _row_grant_recognised(role_name, key, str(source_type or ""), items, exempt):
            refused.add(key)
    return refused


def stale_seed_grant_keys(role_name: Any, rows: Iterable[Any]) -> set[str]:
    """K13: keys of opening ``role_menu_defaults`` seed rows of one role that grant nothing.

    A seed row is the automatic copy of the static role default. One that opens a key today's static
    default no longer holds and the role definition does not allow (an old seed of a corrected
    default) is read as no record, so the static role gate decides again. Manual and rollback rows,
    closing rows and keys the role may hold are untouched; no row is changed (the explicit real-admin
    sync rewrites it).
    """
    from app.menu_registry import get_role_default_menu_keys

    role = normalize_role_name(role_name)
    static_default: set[str] | None = None
    stale: set[str] = set()
    for row in rows or ():
        if (getattr(row, "source_type", "") or "") != SEED_SOURCE or not getattr(row, "is_visible", False):
            continue
        key = str(getattr(row, "menu_key", "") or "").strip()
        if not key:
            continue
        if static_default is None:
            static_default = set(get_role_default_menu_keys(role))
        if key not in static_default and not role_may_hold_menu_key(role, key):
            stale.add(key)
    return stale


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
    from sqlalchemy.exc import SQLAlchemyError

    from app.extensions import db

    try:
        db.session.rollback()
    except SQLAlchemyError:  # pragma: no cover - geri alma da başarısızsa yapılacak bir şey yok
        logger.exception("BYS360 K2 rollback after lookup failure failed.")
