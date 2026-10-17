"""BYS360 Portal Deneyimi V1B güvenli servis katmanı.

V1B amacı: Portal ana sayfası ilgi çekici kalsın; ancak local geliştirme,
eksik migrasyon veya eski SQLite kopyalarında tek bir eksik tablo yüzünden
anasayfa/portal beyaz ekrana düşmesin.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib import import_module
from typing import Any

try:
    from sqlalchemy import and_, inspect, or_
except Exception:
    and_ = None  # type: ignore[assignment]
    or_ = None  # type: ignore[assignment]
    inspect = None  # type: ignore[assignment]

try:
    from app.core.datetime_utils import utc_now as _app_utc_now
except Exception:
    _app_utc_now = None  # type: ignore[assignment]

try:
    from app.extensions import db
except Exception:
    db = None  # type: ignore[assignment]

try:
    from app.route_support import sanitize_free_text as _sanitize_free_text
except Exception:
    _sanitize_free_text = None  # type: ignore[assignment]

OPEN_SUPPORT_STATUSES = {"open", "reviewing", "waiting_info", "assigned", "planned", "in_progress", "pending", "waiting", "bekliyor", "inceleniyor"}
ACTIVE_SURVEY_STATUSES = {"published", "active", "yayinda", "aktif"}
PENDING_ASSIGNMENT_STATUSES = {"bekliyor", "kismen_tamamlandi", "pending", "in_progress"}


def utc_now() -> datetime:
    if _app_utc_now:  # type: ignore[truthy-function]
        try:
            return _app_utc_now()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
            pass
    return datetime.now(UTC)


def sanitize_free_text(value: Any, limit: int = 160) -> str:
    if _sanitize_free_text:  # type: ignore[truthy-function]
        try:
            return _sanitize_free_text(value, limit=limit)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
            pass
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit].rstrip() + "…" if len(text) > limit else text


@lru_cache(maxsize=1)
def _model_module() -> Any:
    try:
        return import_module("app.models")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _model(name: str) -> Any:
    module = _model_module()
    return getattr(module, name, None) if module is not None else None


@lru_cache(maxsize=8)
def _known_tables() -> frozenset[str]:
    if db is None or inspect is None:
        return frozenset()
    try:
        return frozenset(str(name) for name in inspect(db.engine).get_table_names())
    except Exception:
        return frozenset()


def _table_available(model: Any) -> bool:
    table_name = str(getattr(model, "__tablename__", "") or "") if model is not None else ""
    tables = _known_tables()
    return bool(table_name and tables and table_name in tables)


def _query(model: Any) -> Any:
    if not _table_available(model):
        return None
    try:
        return model.query
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _safe(factory: Callable[[], Any], default: Any = None) -> Any:
    try:
        return factory()
    except Exception:
        return default


def _safe_count(query_factory: Callable[[], Any]) -> int:
    value = _safe(lambda: query_factory().count(), 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _user_id(user: Any) -> int:
    try:
        return int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _role(user: Any) -> str:
    return str(getattr(user, "role", "") or "").strip().lower()


def _display_name(user: Any) -> str:
    full_name = sanitize_free_text(getattr(user, "full_name", ""), limit=160)
    if full_name:
        return full_name
    first = sanitize_free_text(getattr(user, "ad", ""), limit=80)
    last = sanitize_free_text(getattr(user, "soyad", ""), limit=80)
    email = sanitize_free_text(getattr(user, "email", ""), limit=160)
    return (first + " " + last).strip() or email or "BYS360 Kullanıcısı"


def _user_unit(user: Any) -> str:
    return sanitize_free_text(getattr(user, "birim", ""), limit=160)


def _user_upper_unit(user: Any) -> str:
    return sanitize_free_text(getattr(user, "ust_birim", ""), limit=160)


def _latest_notifications(uid: int, limit: int = 5) -> list[dict[str, str]]:
    Notification = _model("Notification")
    q = _query(Notification)
    if q is None:
        return []
    rows = _safe(lambda: q.filter_by(user_id=uid, is_read=False).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all(), []) or []
    return [{"title": sanitize_free_text(getattr(row, "title", ""), limit=120) or "Bildirim", "body": sanitize_free_text(getattr(row, "body", ""), limit=180) or "Yeni bildiriminiz var.", "priority": sanitize_free_text(getattr(row, "priority", ""), limit=30) or "normal", "link_url": sanitize_free_text(getattr(row, "link_url", ""), limit=300) or "/notifications"} for row in rows]


def _latest_support(uid: int, limit: int = 3) -> list[dict[str, str]]:
    SupportTicket = _model("SupportTicket")
    q = _query(SupportTicket)
    if q is None or or_ is None:
        return []
    rows = _safe(lambda: q.filter(or_(SupportTicket.created_by_user_id == uid, SupportTicket.assigned_to_user_id == uid), SupportTicket.status.in_(list(OPEN_SUPPORT_STATUSES))).order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).limit(limit).all(), []) or []
    return [{"title": sanitize_free_text(getattr(ticket, "title", ""), limit=120) or "Destek talebi", "status": sanitize_free_text(getattr(ticket, "status_label", ""), limit=60) or sanitize_free_text(getattr(ticket, "status", ""), limit=60) or "Açık", "priority": sanitize_free_text(getattr(ticket, "priority_label", ""), limit=60) or sanitize_free_text(getattr(ticket, "priority", ""), limit=60) or "Normal", "link_url": f"/support/{getattr(ticket, 'id', '')}"} for ticket in rows]


def _active_surveys_for_user(user: Any, limit: int = 3) -> list[dict[str, str]]:
    Survey = _model("Survey")
    SurveyAssignment = _model("SurveyAssignment")
    SurveyResponse = _model("SurveyResponse")
    q_survey = _query(Survey)
    if q_survey is None or or_ is None:
        return []
    uid = _user_id(user)
    now = utc_now()
    role = _role(user)
    unit = _user_unit(user)
    upper_unit = _user_upper_unit(user)
    assigned_survey_ids: set[int] = set()
    q_assignment = _query(SurveyAssignment)
    if q_assignment is not None and and_ is not None:
        assigned_survey_ids = set(_safe(lambda: [int(row.survey_id) for row in q_assignment.filter(or_(SurveyAssignment.target_type == "all", and_(SurveyAssignment.target_type == "user", SurveyAssignment.target_value == str(uid)), and_(SurveyAssignment.target_type == "role", SurveyAssignment.target_value == role), and_(SurveyAssignment.target_type == "unit", SurveyAssignment.target_value == unit), and_(SurveyAssignment.target_type == "upper_unit", SurveyAssignment.target_value == upper_unit))).all() if getattr(row, "survey_id", None) is not None], []) or [])
    completed_ids: set[int] = set()
    q_response = _query(SurveyResponse)
    if q_response is not None:
        completed_ids = set(_safe(lambda: [int(row.survey_id) for row in q_response.filter_by(user_id=uid, is_completed=True).all() if getattr(row, "survey_id", None) is not None], []) or [])
    if assigned_survey_ids:
        query = q_survey.filter(Survey.id.in_(list(assigned_survey_ids - completed_ids)), Survey.status.in_(list(ACTIVE_SURVEY_STATUSES)), or_(Survey.end_at.is_(None), Survey.end_at >= now))
    else:
        query = q_survey.filter(Survey.status.in_(list(ACTIVE_SURVEY_STATUSES)), or_(Survey.end_at.is_(None), Survey.end_at >= now))
    rows = _safe(lambda: query.order_by(Survey.created_at.desc(), Survey.id.desc()).limit(limit).all(), []) or []
    return [{"title": sanitize_free_text(getattr(survey, "title", ""), limit=140) or "Anket", "description": sanitize_free_text(getattr(survey, "description", ""), limit=160) or "Yanıt bekleyen anket.", "link_url": f"/surveys/{getattr(survey, 'id', '')}/take"} for survey in rows]


def _recent_recognition(limit: int = 4) -> list[dict[str, str]]:
    PortalPost = _model("PortalPost")
    q = _query(PortalPost)
    if q is None:
        return []
    since = utc_now() - timedelta(days=45)
    rows = _safe(lambda: q.filter(PortalPost.status == "published", PortalPost.post_type.in_(["thanks", "success", "best_practice"]), PortalPost.published_at >= since).order_by(PortalPost.published_at.desc(), PortalPost.id.desc()).limit(limit).all(), []) or []
    items: list[dict[str, str]] = []
    for row in rows:
        author = getattr(row, "author", None)
        items.append({"title": sanitize_free_text(getattr(row, "title", ""), limit=110) or "Teşekkür / başarı paylaşımı", "body": sanitize_free_text(getattr(row, "body", ""), limit=160) or "Kurumsal takdir paylaşımı.", "author": _display_name(author), "link_url": f"/portal#post-{getattr(row, 'id', '')}"})
    return items


def _base_experience(user: Any) -> dict[str, Any]:
    return {"display_name": _display_name(user), "unit_name": _user_unit(user) or _user_upper_unit(user) or "BYS360", "priority_label": "Gün Özeti", "priority_tone": "calm", "priority_note": "Bekleyen işleriniz ve kurumsal akışınız bu alanda özetlenir.", "my_day_cards": [{"key": "notifications", "label": "Bildirim", "value": 0, "note": "okunmamış", "href": "/notifications", "icon": "fa-regular fa-bell", "tone": "neutral"}, {"key": "performance", "label": "Performans", "value": 0, "note": "bekleyen görev", "href": "/performance/tasks", "icon": "fa-solid fa-chart-line", "tone": "neutral"}, {"key": "support", "label": "Destek", "value": 0, "note": "açık talep", "href": "/support/my-tickets", "icon": "fa-solid fa-life-ring", "tone": "neutral"}, {"key": "surveys", "label": "Anket", "value": 0, "note": "yanıt bekleyen", "href": "/surveys", "icon": "fa-solid fa-square-poll-vertical", "tone": "neutral"}, {"key": "messages", "label": "Mesaj", "value": 0, "note": "aktif konuşma", "href": "/messages", "icon": "fa-regular fa-comments", "tone": "neutral"}], "notifications": [], "support_items": [], "survey_items": [], "recognition_items": [], "culture_stats": {"recognitions": 0, "comments": 0, "reactions": 0}, "quick_actions": [{"label": "Duyuru paylaş", "href": "/portal", "icon": "fa-solid fa-bullhorn", "hint": "Kurumsal bilgilendirme oluştur"}, {"label": "Teşekkür / Takdir", "href": "/portal", "icon": "fa-solid fa-award", "hint": "Emeği görünür hale getir"}, {"label": "Destek talebi", "href": "/support/new", "icon": "fa-solid fa-circle-question", "hint": "Yardım talebi oluştur"}]}


def portal_experience_context(user: Any) -> dict[str, Any]:
    """Portal ve anasayfa için güvenli kişisel deneyim bağlamı üretir."""
    uid = _user_id(user)
    if uid <= 0:
        return {"portal_experience_enabled": False, "portal_experience": {}}
    try:
        px = _base_experience(user)
        EvaluationAssignment = _model("EvaluationAssignment")
        Notification = _model("Notification")
        MessageThreadParticipant = _model("MessageThreadParticipant")
        SupportTicket = _model("SupportTicket")
        PortalPost = _model("PortalPost")
        PortalPostComment = _model("PortalPostComment")
        PortalPostReaction = _model("PortalPostReaction")
        pending_performance = 0
        q_eval = _query(EvaluationAssignment)
        if q_eval is not None:
            pending_performance = _safe_count(lambda: q_eval.filter(EvaluationAssignment.evaluator_id == uid, EvaluationAssignment.status.in_(list(PENDING_ASSIGNMENT_STATUSES))))
        unread_notifications = 0
        q_notifications = _query(Notification)
        if q_notifications is not None:
            unread_notifications = _safe_count(lambda: q_notifications.filter_by(user_id=uid, is_read=False))
        active_messages = 0
        q_threads = _query(MessageThreadParticipant)
        if q_threads is not None:
            active_messages = _safe_count(lambda: q_threads.filter(MessageThreadParticipant.user_id == uid, MessageThreadParticipant.left_at.is_(None), MessageThreadParticipant.is_archived.is_(False)))
        open_support = 0
        q_support = _query(SupportTicket)
        if q_support is not None and or_ is not None:
            open_support = _safe_count(lambda: q_support.filter(or_(SupportTicket.created_by_user_id == uid, SupportTicket.assigned_to_user_id == uid), SupportTicket.status.in_(list(OPEN_SUPPORT_STATUSES))))
        survey_items = _active_surveys_for_user(user, limit=20)
        active_surveys = len(survey_items)
        unread_total = pending_performance + unread_notifications + open_support + active_surveys
        if unread_total >= 5:
            px.update(priority_label="Yoğun gün", priority_tone="danger", priority_note="Önce bildirim, görev ve açık talepleri kapatmanız önerilir.")
        elif unread_total >= 1:
            px.update(priority_label="Takip gereken gün", priority_tone="warning", priority_note="Birkaç işlem sizi bekliyor; hızlı kartlardan başlayabilirsiniz.")
        else:
            px.update(priority_label="Sakin gün", priority_tone="calm", priority_note="Bekleyen kritik işlem görünmüyor; portal akışını takip edebilirsiniz.")
        def tone(value: int) -> str:
            return "warning" if value else "neutral"
        px["my_day_cards"] = [{"key": "notifications", "label": "Bildirim", "value": unread_notifications, "note": "okunmamış", "href": "/notifications", "icon": "fa-regular fa-bell", "tone": tone(unread_notifications)}, {"key": "performance", "label": "Performans", "value": pending_performance, "note": "bekleyen görev", "href": "/performance/tasks", "icon": "fa-solid fa-chart-line", "tone": tone(pending_performance)}, {"key": "support", "label": "Destek", "value": open_support, "note": "açık talep", "href": "/support/my-tickets", "icon": "fa-solid fa-life-ring", "tone": tone(open_support)}, {"key": "surveys", "label": "Anket", "value": active_surveys, "note": "yanıt bekleyen", "href": "/surveys", "icon": "fa-solid fa-square-poll-vertical", "tone": tone(active_surveys)}, {"key": "messages", "label": "Mesaj", "value": active_messages, "note": "aktif konuşma", "href": "/messages", "icon": "fa-regular fa-comments", "tone": "primary" if active_messages else "neutral"}]
        px["notifications"] = _latest_notifications(uid)
        px["support_items"] = _latest_support(uid)
        px["survey_items"] = survey_items[:3]
        px["recognition_items"] = _recent_recognition()
        since = utc_now() - timedelta(days=30)
        q_posts = _query(PortalPost)
        q_comments = _query(PortalPostComment)
        q_reactions = _query(PortalPostReaction)
        px["culture_stats"] = {"recognitions": _safe_count(lambda: q_posts.filter(PortalPost.post_type.in_(["thanks", "success", "best_practice"]), PortalPost.created_at >= since)) if q_posts is not None else 0, "comments": _safe_count(lambda: q_comments.filter(PortalPostComment.created_at >= since)) if q_comments is not None else 0, "reactions": _safe_count(lambda: q_reactions.filter(PortalPostReaction.created_at >= since)) if q_reactions is not None else 0}
        return {"portal_experience_enabled": True, "portal_experience": px}
    except Exception:
        return {"portal_experience_enabled": True, "portal_experience": _base_experience(user)}
