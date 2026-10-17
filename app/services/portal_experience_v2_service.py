"""BYS360 Portal Deneyimi V2 servis katmanı.

V2 hedefi: portalı sadece paylaşım listesi olmaktan çıkarıp kurumsal profil,
takdir kültürü, duyuru vitrini ve canlı katılım panosuna dönüştürmek.
Bu servis yeni tablo zorunluluğu getirmez; mevcut PortalPost, PortalProfile,
PortalPostComment, PortalPostReaction ve User modellerini güvenli şekilde okur.
Eksik tablo veya model durumunda güvenli varsayılan bağlam döndürür.

Görünürlük: bu bağlam ana sayfada ve portal V2 alanında her kullanıcıya ayrı
üretilir. Gönderiler portal akışıyla aynı kuraldan (portal_service.can_user_view_post)
geçer; kişi vitrini Personel Duvarları izniyle (portal_people) sınırlıdır. Kurala
uymayan kayıt sunucuda elenir, şablona hiç ulaşmaz.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import PortalPost, PortalPostComment, PortalPostReaction, PortalProfile, User
from app.route_support import sanitize_free_text
from app.services.portal_permission_matrix import portal_permission_allowed
from app.services.portal_service import can_user_view_post

RECOGNITION_TYPES = {"thanks", "success", "best_practice"}
ANNOUNCEMENT_TYPES = {"corporate_announcement", "event", "training"}
COMMUNITY_TYPES = RECOGNITION_TYPES | ANNOUNCEMENT_TYPES | {"normal", "daily_note"}
# Görünürlük süzgecinden önce okunan aday sayısı; portal_service.visible_posts_for_user ile aynı taban.
CANDIDATE_LIMIT = 120


def _safe(factory: Callable[[], Any], default: Any = None) -> Any:
    try:
        return factory()
    except Exception:
        return default


def _table_exists(table_name: str) -> bool:
    # BYS360 DEFECT AR: eskiden inspect() basarisiz olursa SQLite'a ozgu
    # ham sqlite_master sorgusuna dusuyordu -- bu, PostgreSQL'de her zaman
    # ayrica basarisiz olup ayni sonuca (False) varan, yalniz kafa
    # karistiran ve diger ~20 table_exists kopyasiyla tutarsiz gorunen bir
    # ikinci deneme katmaniydi. inspect() zaten her iki dialect'te de
    # calisir; tek denemeli guvenli-yakalama deseni yeterli.
    if not table_name:
        return False
    try:
        inspector = db.inspect(db.engine)
        return table_name in set(inspector.get_table_names())
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return False


def _portal_tables_ready() -> bool:
    return _table_exists("portal_posts") and _table_exists("users")


def _display_name(user: Any) -> str:
    full_name = sanitize_free_text(getattr(user, "full_name", ""), limit=180)
    if full_name:
        return full_name
    first = sanitize_free_text(getattr(user, "ad", ""), limit=90)
    last = sanitize_free_text(getattr(user, "soyad", ""), limit=90)
    email = sanitize_free_text(getattr(user, "email", ""), limit=180)
    return (first + " " + last).strip() or email or "BYS360 Kullanıcısı"


def _profile_photo(user: Any) -> str:
    return sanitize_free_text(getattr(user, "profile_photo_url", ""), limit=300)


def _safe_count(query_factory: Callable[[], Any]) -> int:
    try:
        return int(query_factory().count() or 0)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return 0


def _safe_len(value: Any) -> int:
    try:
        return len(value or [])
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return 0


def _post_link(post: Any) -> str:
    pid = getattr(post, "id", None)
    return f"/portal#post-{pid}" if pid else "/portal"


def _post_author(post: Any) -> str:
    return _display_name(getattr(post, "author", None))


def _post_body(post: Any, limit: int = 160) -> str:
    title = sanitize_free_text(getattr(post, "title", ""), limit=120)
    body = sanitize_free_text(getattr(post, "body", ""), limit=limit)
    return title or body or "Kurumsal portal paylaşımı"


def _profile_context(user: Any) -> dict[str, Any]:
    profile = None
    if _table_exists("portal_profiles"):
        profile = _safe(lambda: PortalProfile.query.filter_by(user_id=int(getattr(user, "id", 0) or 0)).first(), None)
    checks = [
        bool(sanitize_free_text(getattr(user, "unvan", ""), limit=80)),
        bool(sanitize_free_text(getattr(user, "birim", ""), limit=80)),
        bool(sanitize_free_text(getattr(user, "ust_birim", ""), limit=80)),
        bool(_profile_photo(user)),
        bool(sanitize_free_text(getattr(profile, "headline", ""), limit=80)) if profile else False,
        bool(sanitize_free_text(getattr(profile, "about_text", ""), limit=120)) if profile else False,
    ]
    score = int(round((sum(1 for item in checks if item) / max(len(checks), 1)) * 100))
    missing = []
    if not checks[0]:
        missing.append("unvan")
    if not checks[1]:
        missing.append("birim")
    if not checks[3]:
        missing.append("profil fotoğrafı")
    if not checks[5]:
        missing.append("profil açıklaması")
    return {
        "name": _display_name(user),
        "title": sanitize_free_text(getattr(user, "unvan", ""), limit=120) or "Kurumsal kullanıcı",
        "unit": sanitize_free_text(getattr(user, "birim", ""), limit=140) or "Birim bilgisi bekleniyor",
        "upper_unit": sanitize_free_text(getattr(user, "ust_birim", ""), limit=140) or "Üst birim bilgisi bekleniyor",
        "photo_url": _profile_photo(user),
        "completion": score,
        "missing": missing[:4],
        "profile_url": "/portal/profile/me",
    }


def _visible_to(user: Any, rows: list[Any], limit: int | None = None) -> list[Any]:
    """Yalnız kullanıcının portal akışında da görebileceği gönderileri bırakır (hata = görünmez)."""
    visible: list[Any] = []
    for row in rows:
        try:
            allowed = bool(can_user_view_post(user, row))
        except Exception:
            allowed = False
        if allowed:
            visible.append(row)
            if limit is not None and len(visible) >= limit:
                break
    return visible


def _recognition_highlights(user: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not _portal_tables_ready():
        return []
    rows = _safe(
        lambda: PortalPost.query.filter(
            PortalPost.status == "published",
            PortalPost.post_type.in_(list(RECOGNITION_TYPES)),
        ).order_by(PortalPost.published_at.desc(), PortalPost.id.desc()).limit(CANDIDATE_LIMIT).all(),
        [],
    ) or []
    rows = _visible_to(user, rows, limit)
    return [
        {
            "title": _post_body(row, limit=120),
            "body": sanitize_free_text(getattr(row, "body", ""), limit=180) or "Kurumsal takdir paylaşımı.",
            "author": _post_author(row),
            "type": sanitize_free_text(getattr(row, "post_type", ""), limit=40) or "thanks",
            "link_url": _post_link(row),
        }
        for row in rows
    ]


def _featured_announcements(user: Any, limit: int = 4) -> list[dict[str, Any]]:
    if not _portal_tables_ready():
        return []
    rows = _safe(
        lambda: PortalPost.query.filter(
            PortalPost.status == "published",
            PortalPost.post_type.in_(list(ANNOUNCEMENT_TYPES)),
        ).order_by(PortalPost.published_at.desc(), PortalPost.id.desc()).limit(CANDIDATE_LIMIT).all(),
        [],
    ) or []
    rows = _visible_to(user, rows, limit)
    return [
        {
            "title": sanitize_free_text(getattr(row, "title", ""), limit=130) or _post_body(row, limit=110),
            "body": sanitize_free_text(getattr(row, "body", ""), limit=150) or "Kurumsal duyuru paylaşımı.",
            "author": _post_author(row),
            "type": sanitize_free_text(getattr(row, "post_type", ""), limit=40) or "corporate_announcement",
            "link_url": _post_link(row),
        }
        for row in rows
    ]


def _community_pulse(user: Any) -> dict[str, Any]:
    if not _portal_tables_ready():
        return {"post_count": 0, "recognition_count": 0, "announcement_count": 0, "reaction_count": 0, "comment_count": 0, "top_type": "Henüz veri yok"}
    since = utc_now() - timedelta(days=30)
    posts = _safe(
        lambda: PortalPost.query.filter(
            PortalPost.status == "published",
            PortalPost.published_at >= since,
            PortalPost.post_type.in_(list(COMMUNITY_TYPES)),
        ).all(),
        [],
    ) or []
    posts = _visible_to(user, posts)
    post_ids = [getattr(row, "id", None) for row in posts if getattr(row, "id", None)]
    counter = Counter(str(getattr(row, "post_type", "normal") or "normal") for row in posts)
    top_type_key = counter.most_common(1)[0][0] if counter else "none"
    top_type_label = {
        "thanks": "Teşekkür / takdir",
        "success": "Başarı",
        "best_practice": "İyi uygulama",
        "corporate_announcement": "Duyuru",
        "event": "Etkinlik",
        "training": "Eğitim / toplantı",
        "daily_note": "Günlük not",
        "normal": "Genel paylaşım",
    }.get(top_type_key, "Genel paylaşım")
    reaction_count = 0
    comment_count = 0
    if post_ids and _table_exists("portal_post_reactions"):
        reaction_count = _safe_count(lambda: PortalPostReaction.query.filter(PortalPostReaction.post_id.in_(post_ids)))
    if post_ids and _table_exists("portal_post_comments"):
        comment_count = _safe_count(lambda: PortalPostComment.query.filter(PortalPostComment.post_id.in_(post_ids)))
    return {
        "post_count": len(posts),
        "recognition_count": sum(1 for row in posts if getattr(row, "post_type", "") in RECOGNITION_TYPES),
        "announcement_count": sum(1 for row in posts if getattr(row, "post_type", "") in ANNOUNCEMENT_TYPES),
        "reaction_count": reaction_count,
        "comment_count": comment_count,
        "top_type": top_type_label,
    }


def _people_spotlight(user: Any, limit: int = 4) -> list[dict[str, str]]:
    # Personel Duvarları (/portal/people) ile aynı izin ve aynı alanlar: ad, unvan, birim, fotoğraf.
    if not _table_exists("users") or not _safe(lambda: portal_permission_allowed(user, "portal_people"), False):
        return []
    rows = _safe(
        lambda: User.query.filter_by(is_active=True).order_by(User.updated_at.desc(), User.id.desc()).limit(limit).all(),
        [],
    ) or []
    return [
        {
            "name": _display_name(row),
            "title": sanitize_free_text(getattr(row, "unvan", ""), limit=90) or "BYS360 kullanıcısı",
            "unit": sanitize_free_text(getattr(row, "birim", ""), limit=100) or "Birim bilgisi yok",
            "photo_url": _profile_photo(row),
        }
        for row in rows
    ]


def portal_experience_v2_context(user: Any) -> dict[str, Any]:
    uid = int(getattr(user, "id", 0) or 0) if user else 0
    if uid <= 0:
        return {"portal_v2_enabled": False, "portal_v2": {}}
    pulse = _community_pulse(user)
    profile = _profile_context(user)
    quick_share_cards = [
        {"type": "thanks", "title": "Teşekkür / Takdir", "icon": "fa-solid fa-hands-clapping", "hint": "Emeği görünür kılın", "anchor": "#portal-body"},
        {"type": "best_practice", "title": "İyi Uygulama", "icon": "fa-solid fa-lightbulb", "hint": "Birimlerden iyi örnekleri paylaşın", "anchor": "#portal-body"},
        {"type": "daily_note", "title": "Günlük Not", "icon": "fa-regular fa-note-sticky", "hint": "Kısa kurumsal bilgilendirme yapın", "anchor": "#portal-body"},
    ]
    return {
        "portal_v2_enabled": True,
        "portal_v2": {
            "profile": profile,
            "pulse": pulse,
            "recognition_highlights": _recognition_highlights(user),
            "featured_announcements": _featured_announcements(user),
            "people_spotlight": _people_spotlight(user),
            "quick_share_cards": quick_share_cards,
            "safe_note": "Duyurular, bildirimler, destek talepleri, anketler ve kurumsal paylaşımlar bu alanda bir araya gelir.",
        },
    }
