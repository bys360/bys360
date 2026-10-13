"""BYS360 Settings Center V2 routes.

Every route here is guarded by the SAME fail-closed authorization mechanism
that drives sidebar visibility (app.route_support.menu_key_required, which
resolves via the existing build_menu_visibility_map -- see
app/services/settings/module_registry.py's module docstring for why this
project deliberately builds on top of that resolver rather than replacing
its internals). An unresolved/undefined menu_key is always denied, never
silently allowed.

Each module page renders REAL data: registry metadata plus a small set of
module-specific facts pulled from the actual models where a cheap, safe
query exists. Modules with no mutable settings yet get an explicit note
saying so, per BYS360 Settings Center V2's own rule against inventing fake
settings for modules that don't have any (see the project's Phase 8
instruction).
"""
from __future__ import annotations

from typing import Any

from flask import abort, current_app
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Notification, OrganizationUnit, PortalPost, User
from app.models.communication_models import Survey, SurveyAssignment
from app.models.support_models import SupportTicket
from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.settings.module_registry import (
    MODULE_TYPE_BUSINESS,
    MODULE_TYPE_CROSS_CUTTING,
    MODULE_TYPE_SYSTEM,
    ModuleRegistryEntry,
    find_duplicate_module_keys,
    find_orphan_settings_endpoints,
    get_module,
    get_module_registry,
    list_active_modules,
    list_modules_missing_settings_center,
)

_MODULE_TYPE_LABELS = {
    MODULE_TYPE_BUSINESS: "İş Modülü",
    MODULE_TYPE_SYSTEM: "Sistem Servisi",
    MODULE_TYPE_CROSS_CUTTING: "Ortak Servis",
}

_PERMISSION_CATEGORY_LABELS = {
    "standard": "Standart kullanıcı",
    "manager": "Yönetici kademesi",
    "admin_only": "Yalnız yönetici",
    "system_critical": "Sistem kritik (yalnız yönetici)",
}

_SECURITY_LEVEL_LABELS = {
    "public": "Genel",
    "internal": "Kurumsal",
    "sensitive": "Hassas",
    "critical": "Kritik (gizli)",
}

_SECURITY_BADGE_CLASS = {
    "public": "ok",
    "internal": "readonly",
    "sensitive": "warn",
    "critical": "secret",
}


def _module_to_view_dict(entry: ModuleRegistryEntry) -> dict[str, Any]:
    return {
        "module_key": entry.module_key,
        "display_name": entry.display_name,
        "description": entry.description,
        "icon": entry.icon,
        "module_type": entry.module_type,
        "module_type_label": _MODULE_TYPE_LABELS.get(entry.module_type, entry.module_type),
        "route_endpoint": entry.route_endpoint,
        "settings_endpoint": entry.settings_endpoint,
        "active": entry.active,
        "settings_available": entry.settings_available,
        "permission_category": entry.permission_category,
        "permission_category_label": _PERMISSION_CATEGORY_LABELS.get(entry.permission_category, entry.permission_category),
        "security_level": entry.security_level,
        "security_level_label": _SECURITY_LEVEL_LABELS.get(entry.security_level, entry.security_level),
        "security_badge_class": _SECURITY_BADGE_CLASS.get(entry.security_level, "readonly"),
        "anchor_menu_key": entry.anchor_menu_key,
        "evidence": entry.evidence,
    }


def _safe_count(query_fn) -> int | None:
    """Never let a status-page count crash the page; a missing table/column
    in an older DB snapshot degrades to None (rendered as '-'), not a 500."""
    try:
        return int(query_fn())
    except Exception:
        current_app.logger.exception("BYS360 Settings Center V2: durum sayacı okunamadı")
        db.session.rollback()
        return None


@main_bp.get("/settings-center")
@login_required
@menu_key_required("settings_center_home")
def settings_center_home():
    modules = [_module_to_view_dict(e) for e in get_module_registry()]
    groups: list[dict[str, Any]] = []
    for module_type, label, icon in (
        (MODULE_TYPE_SYSTEM, "Sistem Servisleri", "fa-solid fa-server"),
        (MODULE_TYPE_BUSINESS, "İş Modülleri", "fa-solid fa-briefcase"),
        (MODULE_TYPE_CROSS_CUTTING, "Ortak Servisler", "fa-solid fa-diagram-project"),
    ):
        group_modules = [m for m in modules if m["module_type"] == module_type]
        if group_modules:
            groups.append({"label": label, "icon": icon, "modules": group_modules})

    active_modules = list_active_modules()
    missing = list_modules_missing_settings_center()
    return safe_render(
        "settings_center/home.html",
        page_title="Ayar Merkezi",
        page_subtitle="Tüm aktif modüllerin ayar ve durum merkezi.",
        breadcrumb_label=None,
        module=None,
        module_groups=groups,
        total_modules=len(active_modules),
        modules_with_settings=len(active_modules) - len(missing),
        modules_missing_settings=len(missing),
        duplicate_module_keys=find_duplicate_module_keys(),
        orphan_settings_endpoints=find_orphan_settings_endpoints(),
    )


def _render_module_page(
    module_key: str,
    *,
    kv_facts: list[dict[str, Any]] | None = None,
    related_links: list[dict[str, str]] | None = None,
    mutable_settings_note: str | None = None,
):
    entry = get_module(module_key)
    if entry is None:  # pragma: no cover - defensive, registry is static and covers every route below
        return safe_render("settings_center/home.html", page_title="Ayar Merkezi", page_subtitle="", module=None, module_groups=[], total_modules=0, modules_with_settings=0, modules_missing_settings=0, duplicate_module_keys=[], orphan_settings_endpoints=[])
    if not entry.active:
        # Fail-closed: menu_key_required already gates who can even reach
        # this far, but a module the registry marks inactive must not be
        # reachable via direct URL either, even by an admin with the menu
        # key still granted -- "disabled module resolves FALSE" (Phase 14
        # invariant F) applies at the route, not only at the sidebar.
        abort(404)
    module = _module_to_view_dict(entry)
    return safe_render(
        "settings_center/module.html",
        page_title=module["display_name"],
        page_subtitle=module["description"],
        breadcrumb_label=module["display_name"],
        module=module,
        kv_facts=kv_facts or [],
        related_links=related_links or [],
        mutable_settings_note=mutable_settings_note,
    )


@main_bp.get("/settings-center/personnel-hr")
@login_required
@menu_key_required("settings_center_personnel_hr")
def settings_center_personnel_hr():
    user_count = _safe_count(lambda: User.query.count())
    unit_count = _safe_count(lambda: OrganizationUnit.query.count())
    return _render_module_page(
        "personnel_hr",
        kv_facts=[
            {"label": "Toplam personel", "value": user_count if user_count is not None else "-"},
            {"label": "Birim/pozisyon sayısı", "value": unit_count if unit_count is not None else "-"},
        ],
        related_links=[
            {"label": "Personel Özlük Dosyaları", "description": "Personel listesi ve kayıtları", "url": "/admin/users"},
            {"label": "Birim ve Pozisyon Yönetimi", "description": "Organizasyon yapısı", "url": "/admin/org-units"},
        ],
        mutable_settings_note="Bu modülün davranış ayarları henüz merkezi ayar kataloğuna taşınmadı; erişim ve görünürlük Rol Matrisi üzerinden yönetilir.",
    )


@main_bp.get("/settings-center/portal")
@login_required
@menu_key_required("settings_center_portal")
def settings_center_portal():
    post_count = _safe_count(lambda: PortalPost.query.count())
    return _render_module_page(
        "portal",
        kv_facts=[
            {"label": "Toplam portal gönderisi", "value": post_count if post_count is not None else "-"},
        ],
        related_links=[
            {"label": "Portal Yönetimi", "description": "Moderasyon ve onay akışı", "url": "/portal/moderation"},
            {"label": "Basında Tarihi Alan", "description": "Basın/haber izleme (yönetici)", "url": "/portal/press-news"},
        ],
        mutable_settings_note="Portal içerik/moderasyon davranışı şu an kod içinde sabittir; yayına alma her zaman yetkili onayı gerektirir.",
    )


@main_bp.get("/settings-center/communication")
@login_required
@menu_key_required("settings_center_communication")
def settings_center_communication():
    notification_count = _safe_count(lambda: Notification.query.count())
    return _render_module_page(
        "communication",
        kv_facts=[
            {"label": "Toplam bildirim kaydı", "value": notification_count if notification_count is not None else "-"},
        ],
        related_links=[
            {"label": "Günlük Bilgilendirme E-postası", "description": "Otomasyon ve gönderim ayarları (fonksiyonel)", "url": "/executive-summary/daily-weather-mail"},
            {"label": "Duyurular", "description": "Duyuru yayınlama", "url": "/announcements"},
        ],
        mutable_settings_note="Yalnızca Günlük Bilgilendirme E-postası alt özelliğinin gerçek ayar sayfası var; duyuru/mesaj/geri bildirim davranışı henüz merkezi ayar kataloğunda değil.",
    )


@main_bp.get("/settings-center/surveys")
@login_required
@menu_key_required("settings_center_surveys")
def settings_center_surveys():
    survey_count = _safe_count(lambda: Survey.query.count())
    assignment_count = _safe_count(lambda: SurveyAssignment.query.count())
    return _render_module_page(
        "surveys",
        kv_facts=[
            {"label": "Toplam anket", "value": survey_count if survey_count is not None else "-"},
            {"label": "Toplam atama", "value": assignment_count if assignment_count is not None else "-"},
        ],
        related_links=[
            {"label": "Anket Yönetimi", "description": "Anket oluştur/düzenle", "url": "/survey-manage"},
            {"label": "Anket Sonuçları", "description": "Sonuç görünürlüğü", "url": "/survey-results"},
        ],
        mutable_settings_note="Anket davranış ayarları (atama kuralları, sonuç görünürlüğü) şu an anket bazında yönetilir; modül geneli bir ayar kataloğu henüz yok.",
    )


@main_bp.get("/settings-center/support")
@login_required
@menu_key_required("settings_center_support")
def settings_center_support():
    from app.services.support_ticket_access import support_ticket_visibility_clause

    # K5 F4: the count follows the ticket access rule; no role sees the institution-wide total.
    ticket_count = _safe_count(lambda: SupportTicket.query.filter(support_ticket_visibility_clause(current_user)).count())
    return _render_module_page(
        "support_help",
        kv_facts=[
            {"label": "Toplam destek talebi", "value": ticket_count if ticket_count is not None else "-"},
        ],
        related_links=[
            {"label": "Tüm Talepler", "description": "Destek talebi yönetimi", "url": "/support/all"},
            {"label": "Bana Atananlar", "description": "Atanan talepler", "url": "/support/assigned"},
        ],
        mutable_settings_note="Destek/Yardım Merkezi davranış ayarları henüz merkezi ayar kataloğuna taşınmadı.",
    )


@main_bp.get("/settings-center/ai-agent")
# BYS360 SETTINGS CENTER V2: deliberately NOT "/settings-center/virtual-assistant"
# -- app.services.assistant_module_access.ASSISTANT_PATH_KEYWORDS includes the
# literal substring "/virtual-assistant" and its app-wide before_request gate
# would have redirected any personnel whose assistant module isn't enabled
# away from this settings page entirely, even though this page has nothing to
# do with that gate. The menu_key/endpoint name stays descriptive; only the
# URL path was changed to avoid the substring collision.
@login_required
@menu_key_required("settings_center_virtual_assistant")
def settings_center_virtual_assistant():
    kv_facts = [
        {"label": "Erişim kontrolü", "value": "Rol matrisi tabanlı", "sub": "app/services/assistant_role_matrix_v10.py"},
    ]
    try:
        # Defensive: a status-summary failure must not break the whole
        # Settings Center page (same failure-isolation stance as every
        # assistant_v2 read_adapter). get_assistant_v2_status_summary()
        # never returns secrets -- see its own module docstring.
        from app.services.assistant_v2.status_summary import get_assistant_v2_status_summary

        status = get_assistant_v2_status_summary()
        kv_facts.extend(
            [
                {
                    "label": "BYS360 AI Core",
                    "value": "Aktif" if status["bys360_ai_core_active"] else "Pasif",
                    "sub": "Harici yapay zekâ servisi veya üçüncü taraf dil modeli gerektirmez",
                },
                {
                    "label": "Yerli niyet motoru (Native Intent Engine)",
                    "value": status["native_intent_engine_status"],
                    "sub": "app/services/assistant_v2/intent_router.py + domain_vocabulary.py",
                },
                {
                    "label": "Yetenek kayıt defteri (Capability Registry)",
                    "value": f"{status['capability_count_total']} yetenek ({status['capability_count_read']} okuma / {status['capability_count_write']} yazma)",
                    "sub": "app/services/assistant_v2/capability_registry.py",
                },
                {
                    "label": "Kapsanan modüller",
                    "value": f"{status['module_count_with_coverage']}/{status['module_count_total']} modül",
                    "sub": f"kapsam dışı: {status['module_count_without_coverage']}",
                },
                {
                    "label": "Modüller arası zekâ (Cross-Module Intelligence)",
                    "value": f"{status['cross_module_intelligence_count']} birleşik yetenek",
                    "sub": "app/services/assistant_v2/cross_module_orchestrator.py",
                },
                {
                    "label": "Kullanım rehberleri (Procedural Guides)",
                    "value": f"{status['procedural_guide_count']} rehber",
                    "sub": "app/services/assistant_v2/procedural_guides.py",
                },
                {
                    "label": "Web arka ucu (Web Backend)",
                    "value": status["web_backend_status"],
                    "sub": "app/ai_agent/routes.py -- /ai-agent/api/ask",
                },
                {
                    "label": "Mobil arka uç (Mobile Backend)",
                    "value": status["mobile_backend_status"],
                    "sub": "app/api/mobile/services/assistant_service.py -- /api/mobile/assistant/v2/ask",
                },
                {
                    "label": "Tekil zekâ motoru (Single Intelligence Engine)",
                    "value": "Aktif" if status["single_intelligence_engine_active"] else "Pasif",
                    "sub": "Web ve mobil istemciler, sunucu erişilemediğinde yalnızca sabit bir bilgilendirme mesajı gösterir; iş sorusu yerel olarak cevaplanmaz",
                },
                {
                    "label": "Yetkilendirme uygulaması",
                    "value": status["authorization_enforcement_status"],
                    "sub": "app/services/assistant_v2/capability_dispatcher.py",
                },
                {
                    "label": "Kaynak atıfı (Source Attribution)",
                    "value": status["source_attribution_status"],
                },
                {
                    "label": "Denetim (Audit)",
                    "value": status["audit_status"],
                },
                {
                    "label": "Konuşma bağlamı (Conversation Context)",
                    "value": status["conversation_context_status"],
                },
                {
                    "label": "Ağdan bağımsızlık (Network Independence)",
                    "value": status["network_independence_status"],
                },
                {
                    "label": "Harici AI bağımlılığı (External AI Dependency)",
                    "value": str(status["external_ai_dependency_count"]),
                },
            ]
        )
    except Exception:
        current_app.logger.exception("BYS360 Settings Center V2: Assistant V2 durum özeti okunamadı")
    return _render_module_page(
        "virtual_assistant",
        kv_facts=kv_facts,
        related_links=[
            {"label": "Asistan Paneli", "description": "Sanal asistan ana ekranı", "url": "/ai-agent/panel"},
        ],
        mutable_settings_note="Asistan özellik görünürlüğü Ayarlar > Rol Matrisi'ndeki asistan rol politikasından yönetilir; ayrı bir davranış ayar sayfası henüz yok.",
    )


@main_bp.get("/settings-center/dashboard")
@login_required
@menu_key_required("settings_center_dashboard")
def settings_center_dashboard():
    return _render_module_page(
        "dashboard",
        kv_facts=[],
        related_links=[
            {"label": "Dashboard", "description": "Ana panel", "url": "/dashboard"},
        ],
        mutable_settings_note="Dashboard widget görünürlüğü şu an kod içinde role göre sabittir; ayrı bir ayar sayfası henüz yok.",
    )


@main_bp.get("/settings-center/notifications")
@login_required
@menu_key_required("settings_center_notifications")
def settings_center_notifications():
    notification_count = _safe_count(lambda: Notification.query.count())
    cache_ttl = current_app.config.get("NOTIFICATION_UNREAD_CACHE_TTL")
    return _render_module_page(
        "notifications",
        kv_facts=[
            {"label": "Toplam bildirim kaydı", "value": notification_count if notification_count is not None else "-"},
            {"label": "Okunmamış sayaç önbellek süresi", "value": f"{cache_ttl} sn" if cache_ttl is not None else "-", "sub": "NOTIFICATION_UNREAD_CACHE_TTL (ortam değişkeni)"},
        ],
        related_links=[
            {"label": "Bildirimler", "description": "Bildirim listesi", "url": "/notifications"},
        ],
        mutable_settings_note=None,
    )


@main_bp.get("/settings-center/scheduled-jobs")
@login_required
@menu_key_required("settings_center_scheduled_jobs")
def settings_center_scheduled_jobs():
    scheduler_enabled = current_app.config.get("SCHEDULER_ENABLED")
    followup_enabled_raw = current_app.config.get("BYS360_FEEDBACK_FOLLOWUP_SCHEDULER")
    return _render_module_page(
        "scheduled_jobs",
        kv_facts=[
            {"label": "Genel zamanlayıcı", "value": "Aktif" if scheduler_enabled else "Devre dışı", "sub": "SCHEDULER_ENABLED (ortam değişkeni)"},
            {"label": "Geri bildirim takip zamanlayıcısı", "value": "Aktif" if followup_enabled_raw else "Devre dışı", "sub": "BYS360_FEEDBACK_FOLLOWUP_SCHEDULER (ortam değişkeni)"},
        ],
        related_links=[],
        mutable_settings_note="Zamanlanmış işler ortam değişkenleriyle yönetilir; bu sayfa yalnızca durumu gösterir, canlıda değiştirilemez.",
    )


@main_bp.get("/settings-center/security")
@login_required
@menu_key_required("settings_center_security")
def settings_center_security():
    captcha_enabled = current_app.config.get("CAPTCHA_ENABLED", True)
    login_throttle = current_app.config.get("LOGIN_THROTTLE_ENABLED")
    captcha_threshold = current_app.config.get("LOGIN_CAPTCHA_THRESHOLD")
    return _render_module_page(
        "security_session",
        kv_facts=[
            {"label": "CAPTCHA", "value": "Aktif" if captcha_enabled else "Devre dışı", "sub": "CAPTCHA_ENABLED (ortam değişkeni)"},
            {"label": "Giriş kısıtlama (throttle)", "value": "Aktif" if login_throttle else "Devre dışı", "sub": "LOGIN_THROTTLE_ENABLED (ortam değişkeni)"},
            {"label": "CAPTCHA eşiği", "value": captcha_threshold if captcha_threshold is not None else "-", "sub": "LOGIN_CAPTCHA_THRESHOLD (ortam değişkeni)"},
        ],
        related_links=[],
        mutable_settings_note="Güvenlik/oturum/CAPTCHA davranışı yalnızca ortam değişkenleri ile yönetilir -- bu ekranda hiçbir gizli değer görüntülenmez veya değiştirilemez.",
    )
