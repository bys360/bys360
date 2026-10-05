from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex

from flask import abort, current_app, flash, redirect, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, or_

from app.extensions import db
from app.models import (
    SupportCategory,
    SupportFeedbackRating,
    SupportHelpArticle,
    SupportTicket,
    SupportTicketAttachment,
    SupportTicketMessage,
    SupportTicketStatusHistory,
    User,
)
from app.route_registry import main_bp
from app.route_support import (
    admin_required,
    can_access_menu,
    is_manager_family_user,
    menu_key_required,
    safe_db_rollback,
    safe_render,
    sanitize_free_text,
)
from app.security.upload_security import UploadValidationError, safe_store_filename, validate_upload
from app.services.bys360_notification_bridge import (
    notify_support_ticket_assigned,
    notify_support_ticket_comment,
    notify_support_ticket_created,
    notify_support_ticket_rating,
    notify_support_ticket_status_changed,
)
from app.services.support_ticket_access import can_view_private_support_ticket
from app.support.help_center_content import (
    HELP_CATEGORIES,
    HELP_ROLES,
    build_home_context,
    default_help_articles_payload,
    get_article,
    get_category,
    get_role,
    search_articles,
)

logger = logging.getLogger(__name__)

SUPPORT_ALLOWED_TABLES = {
    "support_categories",
    "support_tickets",
    "support_ticket_messages",
    "support_ticket_attachments",
    "support_ticket_status_history",
    "support_feedback_ratings",
}

SUPPORT_HELP_ALLOWED_TABLES = {"support_help_articles"}

SUPPORT_TICKET_TYPES = [
    ("bug", "Hata Bildirimi"),
    ("enhancement", "Geliştirme Talebi"),
    ("usage", "Kullanım Desteği"),
    ("permission", "Yetki Talebi"),
    ("ui", "Tasarım / Arayüz Talebi"),
    ("training", "Eğitim Talebi"),
    ("other", "Diğer"),
]

SUPPORT_MODULE_CHOICES = [
    "Genel",
    "Giriş ve Hesap",
    "Personel Yönetimi",
    "Performans Yönetimi",
    "Ayarlar ve Yetkilendirme",
    "Destek ve Talep Yönetimi",
    "İletişim ve Anket",
    "BYS360 Asistanı",
    "KPI / Hedef Yönetimi",
    "Mobil Uygulama",
    "Raporlama ve Dashboard",
    "Diğer",
]

SUPPORT_PRIORITY_CHOICES = [
    ("low", "Düşük"),
    ("normal", "Normal"),
    ("high", "Yüksek"),
    ("critical", "Kritik"),
]

SUPPORT_STATUS_CHOICES = [
    ("open", "Açıldı"),
    ("reviewing", "İnceleniyor"),
    ("waiting_info", "Bilgi Bekleniyor"),
    ("assigned", "Atandı"),
    ("planned", "Geliştirme Planına Alındı"),
    ("resolved", "Çözüldü"),
    ("closed", "Kapatıldı"),
    ("rejected", "Reddedildi"),
]

DEFAULT_CATEGORY_ROWS = [
    ("Hata Bildirimi", "Uygulamada çalışan ama hatalı sonuç üreten alanlar", 10),
    ("Geliştirme Talebi", "Yeni ihtiyaçlar ve iyileştirme önerileri", 20),
    ("Kullanım Desteği", "Kullanıcı yönlendirmesi ve operasyon desteği", 30),
    ("Yetki Talebi", "Menü ve işlem erişimi talepleri", 40),
]

SUPPORT_LIST_LIMIT = 200
SUPPORT_HELP_ADMIN_LIMIT = 300
SUPPORT_CATEGORY_LIMIT = 100
SUPPORT_ASSIGNABLE_USER_LIMIT = 300


# BYS360_RUNTIME_SLOW_PAGES_V2_SUPPORT_READY_CACHE
_SUPPORT_READY_CACHE_TTL_SECONDS = 60
_SUPPORT_READY_CACHE = {
    "tables_checked_at": 0.0,
    "tables_ready": None,
    "help_checked_at": 0.0,
    "help_ready": None,
}


def _cached_ready_value(kind: str):
    checked_key = f"{kind}_checked_at"
    ready_key = f"{kind}_ready"
    now = time.time()
    ready = _SUPPORT_READY_CACHE.get(ready_key)
    checked_at = float(_SUPPORT_READY_CACHE.get(checked_key) or 0.0)
    if ready is not None and now - checked_at <= _SUPPORT_READY_CACHE_TTL_SECONDS:
        return bool(ready)
    return None


def _store_ready_value(kind: str, value: bool) -> bool:
    _SUPPORT_READY_CACHE[f"{kind}_checked_at"] = time.time()
    _SUPPORT_READY_CACHE[f"{kind}_ready"] = bool(value)
    return bool(value)


def _support_tables_ready() -> bool:
    cached = _cached_ready_value("tables")
    if cached is not None:
        return cached
    try:
        existing = set(inspect(db.engine).get_table_names())
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=133 | exc=%s", exc)
        safe_db_rollback()
        return _store_ready_value("tables", False)
    return _store_ready_value("tables", SUPPORT_ALLOWED_TABLES.issubset(existing))

def _support_help_tables_ready() -> bool:
    cached = _cached_ready_value("help")
    if cached is not None:
        return cached
    try:
        existing = set(inspect(db.engine).get_table_names())
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=146 | exc=%s", exc)
        safe_db_rollback()
        return _store_ready_value("help", False)
    return _store_ready_value("help", SUPPORT_HELP_ALLOWED_TABLES.issubset(existing))

def _forget_support_ready_cache() -> None:
    for kind in ("tables", "help"):
        _SUPPORT_READY_CACHE[f"{kind}_checked_at"] = 0.0
        _SUPPORT_READY_CACHE[f"{kind}_ready"] = None

# G2: destek tablolarının tek sahibi Alembic a3d8f1c9b6e2 migration'ıdır. İstek kodu
# tablo oluşturmaz/değiştirmez; yalnız hazır olup olmadığını okur.
SUPPORT_SCHEMA_MIGRATION_REQUIRED_MESSAGE = (
    "Destek ve Talep Yönetimi veritabanı tabloları hazır değil. Uygulama ekranları tablo oluşturmaz; "
    "yetkili teknik ekip veritabanı migration/hazırlık işlemini (flask db upgrade) tamamlamalıdır."
)
SUPPORT_HELP_SCHEMA_MIGRATION_REQUIRED_MESSAGE = (
    "Yardım merkezi yönetim tablosu hazır değil. Uygulama ekranları tablo oluşturmaz; "
    "yetkili teknik ekip veritabanı migration/hazırlık işlemini (flask db upgrade) tamamlamalıdır."
)

def _seed_default_support_categories() -> None:
    """Mevcut şemaya eksik varsayılan kategorileri ekler (yalnız DML)."""
    for name, description, sort_order in DEFAULT_CATEGORY_ROWS:
        exists = SupportCategory.query.filter_by(name=name).first()
        if exists:
            continue
        db.session.add(SupportCategory(name=name, description=description, sort_order=sort_order, is_active=True))
    db.session.commit()

def _support_guard_or_redirect():
    if _support_tables_ready():
        return None
    flash("Destek ve Talep Yönetimi tabloları henüz kurulmamış. Yetkili kullanıcı kurulum ekranından modülü aktifleştirebilir.", "warning")
    return redirect(url_for("main.support_index"))

def _build_ticket_no() -> str:
    return f"DTY-{datetime.now(UTC).replace(tzinfo=None).strftime('%Y%m%d')}-{token_hex(3).upper()}"

def _ticket_type_map() -> dict[str, str]:
    return {key: label for key, label in SUPPORT_TICKET_TYPES}

def _priority_map() -> dict[str, str]:
    return {key: label for key, label in SUPPORT_PRIORITY_CHOICES}

def _default_support_category_id(ticket_type: str | None) -> int | None:
    """Yeni talep ekranında kategori alanı kullanıcıdan kaldırıldı.

    Kategori alanı veritabanında ve raporlama tarafında korunur; kullanıcıdan
    ikinci kez aynı seçim istenmez. Sistem, talep türüne göre iç kategori
    eşlemesini otomatik yapar.
    """

    ticket_type_key = (ticket_type or "").strip().lower()
    type_label = _ticket_type_map().get(ticket_type_key)
    if not type_label:
        type_label = "Diğer"
    category = SupportCategory.query.filter_by(name=type_label).first()
    if category:
        return int(category.id)
    fallback = SupportCategory.query.filter_by(name="Diğer").first()
    if fallback:
        return int(fallback.id)
    return None

def _status_map() -> dict[str, str]:
    return {key: label for key, label in SUPPORT_STATUS_CHOICES}

def _is_ticket_assignee(ticket: SupportTicket) -> bool:
    return int(getattr(ticket, "assigned_to_user_id", 0) or 0) == int(getattr(current_user, "id", 0) or 0)


def _can_use_assigned_support_view() -> bool:
    """Bana Atananlar ekranı kişi bazlı menü izniyle de açılabilir.

    Eski akışta menü görünürlüğü Ayarlar/Rol Matrisi tarafından açılmasına rağmen
    route içinde ikinci bir sabit yönetici rol kontrolü kaldığı için personel
    sekmeyi görüyor ama erişim engeline düşüyordu. Bu yardımcı, son kararı
    canlı menü haritasına bırakır; veri kapsamı yine yalnızca kullanıcının üzerine
    atanmış taleplerle sınırlıdır.
    """
    if not current_user.is_authenticated:
        return False
    return bool(is_manager_family_user(current_user) or can_access_menu(current_user, "support_assigned"))

def _can_use_all_support_view() -> bool:
    """Tüm Talepler ekranı kişi bazlı menü izniyle de açılabilir.

    Ayarlar/Rol Matrisi üzerinden bir personele support_all görünürlüğü verildiyse
    backend route da aynı kararı kabul eder. Bu izin verilmemişse normal personel
    kurum geneli talep verisini göremez.
    """
    if not current_user.is_authenticated:
        return False
    return bool(is_manager_family_user(current_user) or can_access_menu(current_user, "support_all"))


# BYS360_P13B_NEW1_FIX: _can_use_all_support_view() manager ailesine kurum
# geneli erisim veriyordu ve is_private hicbir yerde okunmuyordu (Phase 13B,
# confirmed - baska birimin yoneticisi, "sadece yetkili kullanicilar gorsun"
# etiketli gizli bir bileti okuyabiliyordu). Talep sahibi/atanan/admin ailesi
# disinda, gizli bir bilet artik yalnizca talebin birim anlik goruntusuyle
# ayni birimdeki yoneticilere acilir.
def _can_view_private_scope(ticket: SupportTicket) -> bool:
    return can_view_private_support_ticket(ticket, current_user)


def _can_view_ticket(ticket: SupportTicket) -> bool:
    if not current_user.is_authenticated:
        return False
    current_id = int(getattr(current_user, "id", 0) or 0)
    if int(ticket.created_by_user_id or 0) == current_id or _is_ticket_assignee(ticket):
        return True
    if not _can_use_all_support_view():
        return False
    return _can_view_private_scope(ticket)


def _can_operate_ticket(ticket: SupportTicket) -> bool:
    if not current_user.is_authenticated:
        return False
    current_id = int(getattr(current_user, "id", 0) or 0)
    if int(ticket.created_by_user_id or 0) == current_id or _is_ticket_assignee(ticket):
        return True
    if not _can_use_all_support_view():
        return False
    return _can_view_private_scope(ticket)

def _normalize_choice(value: str | None, allowed: set[str], default: str) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in allowed else default

def _apply_support_search_filter(query, search: str | None, *, include_requester: bool = False):
    """Destek talebi aramasını Python sonrası eleme yerine SQL WHERE tarafında kurar."""

    if not search:
        return query
    like = f"%{search}%"
    fields = [SupportTicket.title.ilike(like), SupportTicket.ticket_no.ilike(like), SupportTicket.module_name.ilike(like)]
    if include_requester:
        fields.append(SupportTicket.full_name_snapshot.ilike(like))
    return query.filter(or_(*fields))


def _support_list_rows(query, limit: int = SUPPORT_LIST_LIMIT) -> list[SupportTicket]:
    """Liste ekranlarında sınırsız all() yerine kontrollü SQL LIMIT uygular."""

    return (
        query
        .order_by(SupportTicket.updated_at.desc(), SupportTicket.created_at.desc())
        .limit(limit)
        .all()
    )


def _support_upload_root() -> Path:
    base_folder = current_app.config.get("UPLOAD_FOLDER") or "uploads"
    root = Path(base_folder) / "support_tickets"
    root.mkdir(parents=True, exist_ok=True)
    return root

def _store_ticket_attachment(ticket: SupportTicket, file_obj, attachment_type: str = "document") -> None:
    meta = validate_upload(
        file_obj,
        allowed_extensions={"png", "jpg", "jpeg", "pdf", "docx", "xlsx", "txt", "webp"},
        max_size=current_app.config.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024),
    )
    stored_name = safe_store_filename(file_obj.filename)
    root = _support_upload_root()
    ticket_folder = root / str(ticket.id)
    ticket_folder.mkdir(parents=True, exist_ok=True)
    file_obj.save(ticket_folder / stored_name)
    db.session.add(
        SupportTicketAttachment(
            ticket=ticket,
            uploaded_by_user_id=current_user.id,
            filename=meta["original_filename"],
            stored_name=stored_name,
            mime_type=meta.get("detected_mime"),
            file_size=int(meta.get("size") or 0),
            attachment_type=attachment_type,
        )
    )

def _build_help_center_context(search_query: str | None = None) -> dict:
    context = build_home_context()
    context["can_manage_help_content"] = bool(current_user.is_authenticated and getattr(current_user, "is_admin", False))
    context["editable_help_ready"] = _support_help_tables_ready()
    if search_query is not None:
        context["search_query"] = search_query
    return context

def _build_recent_support_streams(limit: int = 6) -> dict:
    manager_mode = _can_use_all_support_view()
    assigned_view = _can_use_assigned_support_view()
    base_order = (SupportTicket.updated_at.desc(), SupportTicket.created_at.desc())
    my_base = SupportTicket.query.filter_by(created_by_user_id=current_user.id)
    assigned_base = SupportTicket.query.filter_by(assigned_to_user_id=current_user.id)

    return {
        "my_recent_tickets": my_base.order_by(*base_order).limit(limit).all(),
        "assigned_recent_tickets": assigned_base.order_by(*base_order).limit(limit).all() if assigned_view else [],
        "all_recent_tickets": SupportTicket.query.order_by(*base_order).limit(limit).all() if manager_mode else [],
    }

def _build_dashboard_context() -> dict:
    open_statuses = {"open", "reviewing", "waiting_info", "assigned", "planned"}
    my_base = SupportTicket.query.filter_by(created_by_user_id=current_user.id)
    assigned_base = SupportTicket.query.filter_by(assigned_to_user_id=current_user.id)
    manager_mode = _can_use_all_support_view()
    assigned_view = _can_use_assigned_support_view()

    counts = {
        "my_total": my_base.count(),
        "my_open": my_base.filter(SupportTicket.status.in_(open_statuses)).count(),
        "assigned_total": assigned_base.count() if assigned_view else 0,
        "critical_open": SupportTicket.query.filter(SupportTicket.priority == "critical", SupportTicket.status.in_(open_statuses)).count() if manager_mode else my_base.filter(SupportTicket.priority == "critical", SupportTicket.status.in_(open_statuses)).count(),
        "resolved_total": SupportTicket.query.filter(SupportTicket.status == "resolved").count() if manager_mode else my_base.filter(SupportTicket.status == "resolved").count(),
        "all_total": SupportTicket.query.count() if manager_mode else my_base.count(),
    }

    streams = _build_recent_support_streams(limit=6)
    recent_tickets = streams["all_recent_tickets"] if manager_mode else streams["my_recent_tickets"]
    return {
        "counts": counts,
        "recent_tickets": recent_tickets,
        **streams,
        "status_labels": _status_map(),
        "priority_labels": _priority_map(),
        "is_support_ready": True,
    }

def _slugify(value: str | None) -> str:
    value = (value or "").strip().lower()
    replacements = {
        "ç": "c", "ğ": "g", "ı": "i", "i̇": "i", "ö": "o", "ş": "s", "ü": "u",
        "â": "a", "î": "i", "û": "u",
    }
    for src, target in replacements.items():
        value = value.replace(src, target)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or f"makale-{token_hex(4)}"

def _parse_csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item and item.strip()]

def _build_help_form_context(article: SupportHelpArticle | None = None) -> dict:
    return {
        "article": article,
        "help_categories": HELP_CATEGORIES,
        "help_roles": HELP_ROLES,
    }


@main_bp.route("/support")
@login_required
@menu_key_required("support_index")
def support_index():
    is_ready = _support_tables_ready()
    dashboard_context = {
        "counts": {"my_total": 0, "my_open": 0, "assigned_total": 0, "critical_open": 0, "resolved_total": 0, "all_total": 0},
        "recent_tickets": [],
        "status_labels": _status_map(),
        "priority_labels": _priority_map(),
        "is_support_ready": False,
    }
    if is_ready:
        dashboard_context = _build_dashboard_context()
    else:
        dashboard_context["status_labels"] = _status_map()
        dashboard_context["priority_labels"] = _priority_map()
    help_context = _build_help_center_context()
    return safe_render(
        "support/index.html",
        "<h3>Yardım merkezi ekranı yüklenemedi.</h3>",
        current_view_key="support_index",
        **help_context,
        **dashboard_context,
    )


@main_bp.route("/support/help/search")
@login_required
@menu_key_required("support_index")
def support_help_search():
    search_query = sanitize_free_text(request.args.get("q"), limit=120)
    return safe_render(
        "support/help_search.html",
        "<h3>Yardım merkezi arama ekranı yüklenemedi.</h3>",
        search_query=search_query,
        articles=search_articles(search_query),
        can_manage_help_content=bool(current_user.is_authenticated and getattr(current_user, "is_admin", False)),
    )


@main_bp.route("/support/help/category/<string:category_slug>")
@login_required
@menu_key_required("support_index")
def support_help_category(category_slug: str):
    category = get_category(category_slug)
    if not category:
        abort(404)
    return safe_render(
        "support/help_category.html",
        "<h3>Yardım kategorisi yüklenemedi.</h3>",
        category=category,
        can_manage_help_content=bool(current_user.is_authenticated and getattr(current_user, "is_admin", False)),
    )


@main_bp.route("/support/help/role/<string:role_slug>")
@login_required
@menu_key_required("support_index")
def support_help_role(role_slug: str):
    role = get_role(role_slug)
    if not role:
        abort(404)
    return safe_render(
        "support/help_role.html",
        "<h3>Rol rehberleri yüklenemedi.</h3>",
        role=role,
        can_manage_help_content=bool(current_user.is_authenticated and getattr(current_user, "is_admin", False)),
    )


@main_bp.route("/support/help/article/<string:article_slug>")
@login_required
@menu_key_required("support_index")
def support_help_article(article_slug: str):
    article = get_article(article_slug)
    if not article:
        abort(404)
    return safe_render(
        "support/help_article.html",
        "<h3>Yardım makalesi yüklenemedi.</h3>",
        article=article,
        can_manage_help_content=bool(current_user.is_authenticated and getattr(current_user, "is_admin", False)),
    )


@main_bp.route("/support/help-admin")
@login_required
@menu_key_required("support_index")
@admin_required
def support_help_admin():
    if not _support_help_tables_ready():
        flash(SUPPORT_HELP_SCHEMA_MIGRATION_REQUIRED_MESSAGE, "warning")
    search_query = sanitize_free_text(request.args.get("q"), limit=120)
    status_filter = (request.args.get("status") or "all").strip().lower()
    items: list[SupportHelpArticle] = []
    if _support_help_tables_ready():
        query = SupportHelpArticle.query.order_by(SupportHelpArticle.sort_order.asc(), SupportHelpArticle.title.asc())
        if search_query:
            like = f"%{search_query}%"
            query = query.filter(or_(SupportHelpArticle.title.ilike(like), SupportHelpArticle.slug.ilike(like), SupportHelpArticle.summary.ilike(like)))
        if status_filter == "published":
            query = query.filter(SupportHelpArticle.is_published.is_(True))
        elif status_filter == "draft":
            query = query.filter(SupportHelpArticle.is_published.is_(False))
        items = query.limit(SUPPORT_HELP_ADMIN_LIMIT).all()
    return safe_render(
        "support/help_admin_list.html",
        "<h3>Yardım merkezi yönetimi yüklenemedi.</h3>",
        articles=items,
        search_query=search_query,
        status_filter=status_filter,
        editable_help_ready=_support_help_tables_ready(),
    )


@main_bp.route("/support/help-admin/seed", methods=["POST"])
@login_required
@menu_key_required("support_index")
@admin_required
def support_help_admin_seed():
    if not _support_help_tables_ready():
        flash(SUPPORT_HELP_SCHEMA_MIGRATION_REQUIRED_MESSAGE, "warning")
        return redirect(url_for("main.support_help_admin"))
    try:
        inserted = 0
        for payload in default_help_articles_payload():
            exists = SupportHelpArticle.query.filter_by(slug=payload["slug"]).first()
            if exists:
                continue
            article = SupportHelpArticle(
                slug=payload["slug"],
                title=payload["title"],
                summary=payload["summary"],
                category_slug=payload["category_slug"],
                content_text=payload["content_text"],
                steps_text=payload["steps_text"],
                notes_text=payload["notes_text"],
                is_published=True,
                is_featured=payload["slug"] in {"sisteme-ilk-giris", "performans-donemi-nasil-acilir", "izin-talebi-nasil-olusturulur", "not-karnesi-ne-zaman-gorunur"},
                source_type="seeded",
                created_by_user_id=current_user.id,
                updated_by_user_id=current_user.id,
            )
            article.set_role_slugs(payload.get("role_slugs", []))
            article.set_tags(payload.get("tags", []))
            article.set_related_slugs(payload.get("related_slugs", []))
            db.session.add(article)
            inserted += 1
        db.session.commit()
        flash(f"Hazır yardım makaleleri veritabanına aktarıldı. Yeni eklenen kayıt: {inserted}", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=575 | exc=%s", exc)
        safe_db_rollback()
        flash("Hazır makaleler aktarılırken hata oluştu.", "danger")
    return redirect(url_for("main.support_help_admin"))


@main_bp.route("/support/help-admin/new", methods=["GET", "POST"])
@login_required
@menu_key_required("support_index")
@admin_required
def support_help_admin_new():
    if not _support_help_tables_ready():
        flash(SUPPORT_HELP_SCHEMA_MIGRATION_REQUIRED_MESSAGE, "warning")
        return redirect(url_for("main.support_help_admin"))

    if request.method == "POST":
        try:
            title = sanitize_free_text(request.form.get("title"), limit=255)
            summary = sanitize_free_text(request.form.get("summary"), limit=500)
            slug = _slugify(request.form.get("slug") or title)
            category_slug = sanitize_free_text(request.form.get("category_slug"), limit=80) or "baslarken"
            role_slugs = request.form.getlist("role_slugs") or _parse_csv(request.form.get("role_slugs_text"))
            tags = _parse_csv(request.form.get("tags_text"))
            related = _parse_csv(request.form.get("related_slugs_text"))
            content_text = sanitize_free_text(request.form.get("content_text"), limit=12000)
            steps_text = sanitize_free_text(request.form.get("steps_text"), limit=12000)
            notes_text = sanitize_free_text(request.form.get("notes_text"), limit=12000)
            sort_order = request.form.get("sort_order", type=int) or 0
            if not title:
                raise ValueError("Makale başlığı zorunludur.")
            if SupportHelpArticle.query.filter_by(slug=slug).first():
                raise ValueError("Aynı slug ile kayıt zaten var. Farklı bir kısa bağlantı adı girin.")
            article = SupportHelpArticle(
                slug=slug,
                title=title,
                summary=summary,
                category_slug=category_slug,
                content_text=content_text,
                steps_text=steps_text,
                notes_text=notes_text,
                sort_order=sort_order,
                is_published=bool(request.form.get("is_published")),
                is_featured=bool(request.form.get("is_featured")),
                source_type="manual",
                created_by_user_id=current_user.id,
                updated_by_user_id=current_user.id,
            )
            article.set_role_slugs(role_slugs)
            article.set_tags(tags)
            article.set_related_slugs(related)
            db.session.add(article)
            db.session.commit()
            flash("Yardım makalesi oluşturuldu.", "success")
            return redirect(url_for("main.support_help_admin"))
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=633 | exc=%s", exc)
            safe_db_rollback()
            flash("Makale oluşturulamadı.", "danger")

    return safe_render(
        "support/help_admin_form.html",
        "<h3>Makale formu yüklenemedi.</h3>",
        form_mode="new",
        **_build_help_form_context(),
    )


@main_bp.route("/support/help-admin/<int:article_id>/edit", methods=["GET", "POST"])
@login_required
@menu_key_required("support_index")
@admin_required
def support_help_admin_edit(article_id: int):
    if not _support_help_tables_ready():
        flash(SUPPORT_HELP_SCHEMA_MIGRATION_REQUIRED_MESSAGE, "warning")
        return redirect(url_for("main.support_help_admin"))
    article = SupportHelpArticle.query.get_or_404(article_id)
    if request.method == "POST":
        try:
            title = sanitize_free_text(request.form.get("title"), limit=255)
            summary = sanitize_free_text(request.form.get("summary"), limit=500)
            slug = _slugify(request.form.get("slug") or title)
            category_slug = sanitize_free_text(request.form.get("category_slug"), limit=80) or article.category_slug
            role_slugs = request.form.getlist("role_slugs") or _parse_csv(request.form.get("role_slugs_text"))
            tags = _parse_csv(request.form.get("tags_text"))
            related = _parse_csv(request.form.get("related_slugs_text"))
            if not title:
                raise ValueError("Makale başlığı zorunludur.")
            duplicate = SupportHelpArticle.query.filter(SupportHelpArticle.slug == slug, SupportHelpArticle.id != article.id).first()
            if duplicate:
                raise ValueError("Bu kısa bağlantı adı başka bir makalede kullanılıyor.")
            article.slug = slug
            article.title = title
            article.summary = summary
            article.category_slug = category_slug
            article.content_text = sanitize_free_text(request.form.get("content_text"), limit=12000)
            article.steps_text = sanitize_free_text(request.form.get("steps_text"), limit=12000)
            article.notes_text = sanitize_free_text(request.form.get("notes_text"), limit=12000)
            article.sort_order = request.form.get("sort_order", type=int) or 0
            article.is_published = bool(request.form.get("is_published"))
            article.is_featured = bool(request.form.get("is_featured"))
            article.updated_by_user_id = current_user.id
            article.set_role_slugs(role_slugs)
            article.set_tags(tags)
            article.set_related_slugs(related)
            db.session.commit()
            flash("Makale güncellendi.", "success")
            return redirect(url_for("main.support_help_admin"))
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=689 | exc=%s", exc)
            safe_db_rollback()
            flash("Makale güncellenemedi.", "danger")
    return safe_render(
        "support/help_admin_form.html",
        "<h3>Makale düzenleme formu yüklenemedi.</h3>",
        form_mode="edit",
        **_build_help_form_context(article),
    )


@main_bp.route("/support/help-admin/<int:article_id>/toggle-publish", methods=["POST"])
@login_required
@menu_key_required("support_index")
@admin_required
def support_help_admin_toggle_publish(article_id: int):
    if not _support_help_tables_ready():
        return redirect(url_for("main.support_help_admin"))
    article = SupportHelpArticle.query.get_or_404(article_id)
    try:
        article.is_published = not bool(article.is_published)
        article.updated_by_user_id = current_user.id
        db.session.commit()
        flash("Makale yayın durumu güncellendi.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=713 | exc=%s", exc)
        safe_db_rollback()
        flash("Makale yayın durumu güncellenemedi.", "danger")
    return redirect(url_for("main.support_help_admin"))


@main_bp.route("/support/help-admin/<int:article_id>/delete", methods=["POST"])
@login_required
@menu_key_required("support_index")
@admin_required
def support_help_admin_delete(article_id: int):
    if not _support_help_tables_ready():
        return redirect(url_for("main.support_help_admin"))
    article = SupportHelpArticle.query.get_or_404(article_id)
    try:
        db.session.delete(article)
        db.session.commit()
        flash("Makale silindi.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=731 | exc=%s", exc)
        safe_db_rollback()
        flash("Makale silinemedi.", "danger")
    return redirect(url_for("main.support_help_admin"))


@main_bp.route("/support/setup", methods=["GET", "POST"])
@login_required
@menu_key_required("support_index")
@admin_required
def support_setup():
    if request.method == "POST":
        _forget_support_ready_cache()
    is_ready = _support_tables_ready()
    if request.method == "POST":
        if not (is_ready and _support_help_tables_ready()):
            flash(SUPPORT_SCHEMA_MIGRATION_REQUIRED_MESSAGE, "warning")
        else:
            try:
                _seed_default_support_categories()
                flash("Destek ve Talep Yönetimi tabloları hazır; temel kategoriler kontrol edildi.", "success")
                return redirect(url_for("main.support_index"))
            except Exception as exc:
                logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=749 | exc=%s", exc)
                safe_db_rollback()
                flash("Destek modülü kurulamadı.", "danger")
    return safe_render(
        "support/setup.html",
        "<h3>Destek modülü kurulum ekranı yüklenemedi.</h3>",
        is_support_ready=is_ready,
        required_tables=sorted(SUPPORT_ALLOWED_TABLES | SUPPORT_HELP_ALLOWED_TABLES),
    )


@main_bp.route("/support/new", methods=["GET", "POST"])
@login_required
@menu_key_required("support_new")
def support_new():
    if request.method == "POST":
        if not _support_tables_ready():
            return _support_guard_or_redirect()
        try:
            title = sanitize_free_text(request.form.get("title"), limit=255)
            description = sanitize_free_text(request.form.get("description"), limit=4000)
            module_name = sanitize_free_text(request.form.get("module_name"), limit=120) or "Genel"
            ticket_type = _normalize_choice(request.form.get("ticket_type"), set(_ticket_type_map().keys()), "other")
            priority = _normalize_choice(request.form.get("priority"), set(_priority_map().keys()), "normal")
            page_url = sanitize_free_text(request.form.get("page_url"), limit=255)
            category_id = request.form.get("category_id", type=int)
            if not category_id:
                category_id = _default_support_category_id(ticket_type)

            if not title or not description:
                raise ValueError("Konu ve açıklama alanları zorunludur.")

            ticket = SupportTicket(
                ticket_no=_build_ticket_no(),
                title=title,
                description=description,
                ticket_type=ticket_type,
                module_name=module_name,
                page_url=page_url or None,
                priority=priority,
                status="open",
                category_id=category_id,
                created_by_user_id=current_user.id,
                organization_unit_id=getattr(current_user, "organization_unit_id", None),
                sicil_no_snapshot=getattr(current_user, "sicil_no", None),
                full_name_snapshot=getattr(current_user, "full_name", None),
                unit_name_snapshot=(getattr(current_user, "birim", None) or getattr(current_user, "ust_birim", None)),
                is_private=bool(request.form.get("is_private")),
            )
            db.session.add(ticket)
            db.session.flush()

            db.session.add(
                SupportTicketStatusHistory(
                    ticket=ticket,
                    old_status=None,
                    new_status="open",
                    changed_by_user_id=current_user.id,
                    note="Talep oluşturuldu.",
                )
            )
            db.session.add(
                SupportTicketMessage(
                    ticket=ticket,
                    user_id=current_user.id,
                    message_type="comment",
                    message=description,
                    is_internal=False,
                )
            )

            upload = request.files.get("attachment")
            if upload and upload.filename:
                _store_ticket_attachment(ticket, upload, attachment_type="document")

            notify_support_ticket_created(ticket, current_user)
            db.session.commit()
            flash("Talebiniz kaydedildi.", "success")
            return redirect(url_for("main.support_detail", ticket_id=ticket.id))
        except UploadValidationError as exc:
            safe_db_rollback()
            flash(str(exc), "danger")
        except Exception as exc:
            logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=832 | exc=%s", exc)
            safe_db_rollback()
            flash("Talep oluşturulamadı.", "danger")

    categories = SupportCategory.query.filter_by(is_active=True).order_by(SupportCategory.sort_order.asc(), SupportCategory.name.asc()).limit(SUPPORT_CATEGORY_LIMIT).all() if _support_tables_ready() else []
    return safe_render(
        "support/new.html",
        "<h3>Yeni talep ekranı yüklenemedi.</h3>",
        categories=categories,
        ticket_types=SUPPORT_TICKET_TYPES,
        modules=SUPPORT_MODULE_CHOICES,
        priorities=SUPPORT_PRIORITY_CHOICES,
        is_support_ready=_support_tables_ready(),
    )


@main_bp.route("/support/my-tickets")
@login_required
@menu_key_required("support_my_tickets")
def support_my_tickets():
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    search = sanitize_free_text(request.args.get("q"), limit=120)
    query = SupportTicket.query.filter_by(created_by_user_id=current_user.id)
    query = _apply_support_search_filter(query, search)
    tickets = _support_list_rows(query)
    list_context = _build_recent_support_streams(limit=5)
    return safe_render(
        "support/list.html",
        "<h3>Talep listesi yüklenemedi.</h3>",
        tickets=tickets,
        page_heading="Taleplerim",
        page_text="Açtığınız tüm destek ve geliştirme taleplerini durumlarıyla birlikte izleyin.",
        current_view_key="support_my_tickets",
        search_query=search,
        is_manager_view=False,
        show_all_stream=False,
        **list_context,
    )


@main_bp.route("/support/assigned")
@login_required
@menu_key_required("support_assigned")
def support_assigned():
    if not _can_use_assigned_support_view():
        abort(403)
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    search = sanitize_free_text(request.args.get("q"), limit=120)
    query = SupportTicket.query.filter_by(assigned_to_user_id=current_user.id)
    query = _apply_support_search_filter(query, search, include_requester=True)
    tickets = _support_list_rows(query)
    list_context = _build_recent_support_streams(limit=5)
    return safe_render(
        "support/list.html",
        "<h3>Atanan talepler listesi yüklenemedi.</h3>",
        tickets=tickets,
        page_heading="Bana Atananlar",
        page_text="Üzerinizde işlem bekleyen kayıtları bu listeden yönetin.",
        current_view_key="support_assigned",
        search_query=search,
        is_manager_view=is_manager_family_user(current_user),
        can_assigned_view=True,
        show_all_stream=False,
        **list_context,
    )


@main_bp.route("/support/all")
@login_required
@menu_key_required("support_all")
def support_all():
    if not _can_use_all_support_view():
        abort(403)
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    search = sanitize_free_text(request.args.get("q"), limit=120)
    status_filter = _normalize_choice(request.args.get("status"), set(_status_map().keys()), "")
    query = SupportTicket.query
    query = _apply_support_search_filter(query, search, include_requester=True)
    if status_filter:
        query = query.filter(SupportTicket.status == status_filter)
    tickets = _support_list_rows(query)
    list_context = _build_recent_support_streams(limit=5)
    return safe_render(
        "support/list.html",
        "<h3>Tüm talepler listesi yüklenemedi.</h3>",
        tickets=tickets,
        page_heading="Tüm Talepler",
        page_text="Kurum genelinde açılan kayıtları filtreleyip atama ve durum yönetimi yapın.",
        current_view_key="support_all",
        search_query=search,
        status_filter=status_filter,
        status_choices=SUPPORT_STATUS_CHOICES,
        is_manager_view=_can_use_all_support_view(),
        show_all_stream=True,
        **list_context,
    )


@main_bp.route("/support/<int:ticket_id>")
@login_required
@menu_key_required("support_index")
def support_detail(ticket_id: int):
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if not _can_view_ticket(ticket):
        abort(403)
    assignable_users = User.query.filter(User.is_active.is_(True)).order_by(User.ad.asc(), User.soyad.asc()).limit(SUPPORT_ASSIGNABLE_USER_LIMIT).all() if _can_use_all_support_view() else []
    categories = SupportCategory.query.filter_by(is_active=True).order_by(SupportCategory.sort_order.asc(), SupportCategory.name.asc()).limit(SUPPORT_CATEGORY_LIMIT).all()
    return safe_render(
        "support/detail.html",
        "<h3>Talep detayı yüklenemedi.</h3>",
        ticket=ticket,
        categories=categories,
        status_choices=SUPPORT_STATUS_CHOICES,
        status_labels=_status_map(),
        assignable_users=assignable_users,
        can_manage=_can_use_all_support_view(),
    )


@main_bp.route("/support/<int:ticket_id>/comment", methods=["POST"])
@login_required
@menu_key_required("support_index")
def support_comment(ticket_id: int):
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if not _can_operate_ticket(ticket):
        abort(403)
    try:
        message = sanitize_free_text(request.form.get("message"), limit=2000)
        if not message:
            raise ValueError("Yorum alanı boş bırakılamaz.")
        is_internal = bool(request.form.get("is_internal")) and _can_use_all_support_view()
        db.session.add(
            SupportTicketMessage(
                ticket=ticket,
                user_id=current_user.id,
                message_type="internal_note" if is_internal else "comment",
                message=message,
                is_internal=is_internal,
            )
        )
        upload = request.files.get("attachment")
        if upload and upload.filename:
            _store_ticket_attachment(ticket, upload, attachment_type="document")
        ticket.updated_at = datetime.now(UTC).replace(tzinfo=None)
        notify_support_ticket_comment(ticket, current_user, is_internal=is_internal)
        db.session.commit()
        flash("Talep notu kaydedildi.", "success")
    except UploadValidationError as exc:
        safe_db_rollback()
        flash(str(exc), "danger")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=993 | exc=%s", exc)
        safe_db_rollback()
        flash("Yorum kaydedilemedi.", "danger")
    return redirect(url_for("main.support_detail", ticket_id=ticket.id))


@main_bp.route("/support/<int:ticket_id>/status", methods=["POST"])
@login_required
@menu_key_required("support_all")
def support_status(ticket_id: int):
    if not _can_use_all_support_view():
        abort(403)
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if not _can_operate_ticket(ticket):
        abort(403)
    try:
        new_status = _normalize_choice(request.form.get("status"), set(_status_map().keys()), ticket.status)
        note = sanitize_free_text(request.form.get("status_note"), limit=500)
        old_status = ticket.status
        ticket.status = new_status
        ticket.updated_at = datetime.now(UTC).replace(tzinfo=None)
        if new_status in {"resolved", "closed", "rejected"}:
            ticket.closed_at = datetime.now(UTC).replace(tzinfo=None)
        elif new_status:
            ticket.closed_at = None
        db.session.add(
            SupportTicketStatusHistory(
                ticket=ticket,
                old_status=old_status,
                new_status=new_status,
                changed_by_user_id=current_user.id,
                note=note or None,
            )
        )
        if note:
            db.session.add(
                SupportTicketMessage(
                    ticket=ticket,
                    user_id=current_user.id,
                    message_type="status_note",
                    message=note,
                    is_internal=False,
                )
            )
        notify_support_ticket_status_changed(ticket, current_user, old_status=old_status, new_status=new_status, note=note)
        db.session.commit()
        flash("Talep durumu güncellendi.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=1041 | exc=%s", exc)
        safe_db_rollback()
        flash("Durum güncellenemedi.", "danger")
    return redirect(url_for("main.support_detail", ticket_id=ticket.id))


@main_bp.route("/support/<int:ticket_id>/assign", methods=["POST"])
@login_required
@menu_key_required("support_all")
def support_assign(ticket_id: int):
    if not _can_use_all_support_view():
        abort(403)
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if not _can_operate_ticket(ticket):
        abort(403)
    try:
        assignee_id = request.form.get("assigned_to_user_id", type=int)
        assignee = User.query.get(assignee_id) if assignee_id else None
        ticket.assigned_to_user_id = assignee.id if assignee else None
        if ticket.status in {"open", "reviewing", "waiting_info"} and assignee:
            old_status = ticket.status
            ticket.status = "assigned"
            db.session.add(
                SupportTicketStatusHistory(
                    ticket=ticket,
                    old_status=old_status,
                    new_status="assigned",
                    changed_by_user_id=current_user.id,
                    note=f"Talep {(assignee.full_name if assignee else 'atanmamış')} olarak güncellendi.",
                )
            )
        ticket.updated_at = datetime.now(UTC).replace(tzinfo=None)
        notify_support_ticket_assigned(ticket, current_user, assignee=assignee)
        db.session.commit()
        flash("Talep ataması güncellendi.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=1077 | exc=%s", exc)
        safe_db_rollback()
        flash("Atama güncellenemedi.", "danger")
    return redirect(url_for("main.support_detail", ticket_id=ticket.id))


@main_bp.route("/support/<int:ticket_id>/rate", methods=["POST"])
@login_required
@menu_key_required("support_my_tickets")
def support_rate(ticket_id: int):
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if int(ticket.created_by_user_id or 0) != int(current_user.id or 0):
        abort(403)
    try:
        rating = max(1, min(int(request.form.get("rating") or 0), 5))
        note = sanitize_free_text(request.form.get("feedback_note"), limit=500)
        exists = SupportFeedbackRating.query.filter_by(ticket_id=ticket.id, created_by_user_id=current_user.id).first()
        if exists:
            exists.rating = rating
            exists.feedback_note = note or None
        else:
            db.session.add(
                SupportFeedbackRating(
                    ticket=ticket,
                    rating=rating,
                    feedback_note=note or None,
                    created_by_user_id=current_user.id,
                )
            )
        notify_support_ticket_rating(ticket, current_user, rating=rating, note=note)
        db.session.commit()
        flash("Destek değerlendirme notunuz kaydedildi.", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=1112 | exc=%s", exc)
        safe_db_rollback()
        flash("Değerlendirme kaydedilemedi.", "danger")
    return redirect(url_for("main.support_detail", ticket_id=ticket.id))


@main_bp.route("/support/<int:ticket_id>/attachments/<int:attachment_id>")
@login_required
@menu_key_required("support_index")
def support_attachment_download(ticket_id: int, attachment_id: int):
    guard = None if _support_tables_ready() else _support_guard_or_redirect()
    if guard is not None:
        return guard
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if not _can_view_ticket(ticket):
        abort(403)
    attachment = SupportTicketAttachment.query.filter_by(id=attachment_id, ticket_id=ticket.id).first_or_404()
    folder = _support_upload_root() / str(ticket.id)
    return send_from_directory(folder, attachment.stored_name, as_attachment=True, download_name=attachment.filename)

def _sync_seeded_help_articles(*, update_existing: bool = False) -> tuple[int, int, int]:
    inserted = 0
    updated = 0
    skipped = 0
    for payload in default_help_articles_payload():
        existing = SupportHelpArticle.query.filter_by(slug=payload["slug"]).first()
        if not existing:
            article = SupportHelpArticle(
                slug=payload["slug"],
                title=payload["title"],
                summary=payload["summary"],
                category_slug=payload["category_slug"],
                content_text=payload["content_text"],
                steps_text=payload["steps_text"],
                notes_text=payload["notes_text"],
                is_published=True,
                is_featured=payload["slug"] in {"sisteme-ilk-giris-ve-gunluk-kontrol", "yardim-merkezi-nasil-kullanilir", "performans-donemi-nasil-acilir", "izin-talebi-nasil-olusturulur", "not-karnesi-ne-zaman-gorunur", "destek-talebi-nasil-acilir"},
                source_type="seeded",
                created_by_user_id=current_user.id,
                updated_by_user_id=current_user.id,
            )
            article.set_role_slugs(payload.get("role_slugs", []))
            article.set_tags(payload.get("tags", []))
            article.set_related_slugs(payload.get("related_slugs", []))
            db.session.add(article)
            inserted += 1
            continue
        if not update_existing or (existing.source_type or "manual") == "manual":
            skipped += 1
            continue
        existing.title = payload["title"]
        existing.summary = payload["summary"]
        existing.category_slug = payload["category_slug"]
        existing.content_text = payload["content_text"]
        existing.steps_text = payload["steps_text"]
        existing.notes_text = payload["notes_text"]
        existing.is_published = True
        existing.updated_by_user_id = current_user.id
        existing.set_role_slugs(payload.get("role_slugs", []))
        existing.set_tags(payload.get("tags", []))
        existing.set_related_slugs(payload.get("related_slugs", []))
        updated += 1
    return inserted, updated, skipped


@main_bp.route("/support/help-admin/sync", methods=["POST"])
@login_required
@menu_key_required("support_index")
@admin_required
def support_help_admin_sync():
    if not _support_help_tables_ready():
        flash(SUPPORT_HELP_SCHEMA_MIGRATION_REQUIRED_MESSAGE, "warning")
        return redirect(url_for("main.support_help_admin"))
    try:
        inserted, updated, skipped = _sync_seeded_help_articles(update_existing=True)
        db.session.commit()
        flash(f"Hazır rehberler eşitlendi. Yeni: {inserted} | Güncellenen: {updated} | Atlanan(manuel): {skipped}", "success")
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/support/routes.py | line=1190 | exc=%s", exc)
        safe_db_rollback()
        flash("Hazır rehberler güncellenemedi.", "danger")
    return redirect(url_for("main.support_help_admin"))
# BYS360_SUPPORT_NEW_REQUEST_TAXONOMY_V1: Yeni talep ekranında kategori kullanıcıdan kaldırıldı; iç kategori talep türünden otomatik eşlenir.
