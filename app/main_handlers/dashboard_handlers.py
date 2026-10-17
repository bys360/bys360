from __future__ import annotations

from flask import current_app, render_template, request
from flask_login import current_user

from app.route_support import ADMIN_FAMILY_ROLES, can_access_menu, safe_render, user_has_any_role
from app.services.ai.dashboard_panels import (
    build_dashboard_ai_operations_bridge,
    build_dashboard_ai_panel,
)
from app.services.dashboard_rebuild_service import (
    LEGAL_COUNSEL_ROLES,
    build_dashboard_rebuild_context,
)
from app.services.live_surface_service import build_live_dashboard_surface_context
from app.services.runtime_cache import get_or_set as cache_get_or_set
from app.view_helpers import build_dashboard_context, build_db_check_context

BYS360_DASHBOARD_REBUILD_HANDLER_OK = True


# BYS360_RUNTIME_LOGGEDIN_SLOW_PAGES_V3_DASHBOARD_REBUILD_CACHE
_build_dashboard_rebuild_context_uncached = build_dashboard_rebuild_context


def build_dashboard_rebuild_context(user):  # type: ignore[no-redef]
    cache_key = _dashboard_cache_key(user, "rebuild_context_v3")

    def _factory():
        return _build_dashboard_rebuild_context_uncached(user)

    try:
        return cache_get_or_set(cache_key, _factory, ttl_seconds=45)
    except Exception as exc:
        current_app.logger.warning("Dashboard rebuild kısa süreli cache güvenli fallback ile atlandı: %s", exc)
        return _factory()


def _normalize_dashboard_context(user, detail_level: str = "full") -> dict:
    context = dict(build_dashboard_context(user, detail_level=detail_level) or {})
    context.pop("completion_rate", None)
    total_evaluations = int(context.get("total_evaluations") or 0)
    completed_evaluations = int(context.get("completed_evaluations") or 0)
    context["completion_rate"] = round((completed_evaluations / total_evaluations) * 100, 2) if total_evaluations else 0
    return context


def _dashboard_cache_key(user, suffix: str) -> str:
    scope = (request.args.get("scope") or "").strip().lower() or "default"
    user_id = int(getattr(user, "id", 0) or 0)
    return f"dashboard:{suffix}:user:{user_id}:scope:{scope}"


def _build_dashboard_heavy_context(user) -> dict:
    context = _normalize_dashboard_context(user, detail_level="full")
    context["ai_dashboard_panel"] = build_dashboard_ai_panel(context)
    # Yapay zekâ yönetişim sayaçları (istek, açık öneri, olumsuz geri bildirim, maskelenmemiş
    # istek) /admin/ai-center ile aynı kurala bağlıdır: admin_required VE "ai_center" menü izni.
    # Kural sağlanmazsa veri hiç üretilmez; şablon korumalı mod metnini gösterir.
    # Hukuk Müşaviri (mali_musavir) yönetim ailesinde olsa da gösterge panelinde kurum geneli
    # veri almaz (proje sahibi kararı); bu iki kurum geneli panel ona da üretilmez.
    admin_family = user_has_any_role(user, ADMIN_FAMILY_ROLES) and not user_has_any_role(user, LEGAL_COUNSEL_ROLES)
    can_view_admin_ai = admin_family and can_access_menu(user, "ai_center")
    context["ai_operations_bridge"] = build_dashboard_ai_operations_bridge(can_view_admin_ai=True) if can_view_admin_ai else None
    context["can_view_admin_ai"] = can_view_admin_ai
    # Sistem olgunluk özeti için genel kullanıcı politikası yok: yalnız yönetim ailesine üretilir.
    context["live_dashboard_surface"] = build_live_dashboard_surface_context(context) if admin_family else {}
    return context


def dashboard_heavy_panels():
    cache_key = _dashboard_cache_key(current_user, "heavy_html")

    def _factory() -> str:
        context = _build_dashboard_heavy_context(current_user)
        return render_template("partials/dashboard_heavy_panels.html", **context)

    try:
        html = cache_get_or_set(cache_key, _factory, ttl_seconds=45)
    except Exception as exc:  # compatibility guard
        current_app.logger.exception("Dashboard ek panelleri güvenli fallback ile açıldı: %s", exc)
        html = (
            '<section class="dashboard-card" style="padding:16px;border-radius:18px;background:#fff;border-left:6px solid #8B0000;box-shadow:0 12px 30px rgba(0,0,0,.06);">'
            '<h3 style="margin:0 0 8px;color:#8B0000;">Dashboard ek panelleri güvenli modda</h3>'
            '<p style="margin:0;color:#5f5555;line-height:1.6;">Ana dashboard açık kalır. Ek analiz panelleri geçici güvenli görünümle sunulur; canlı veri doğrulaması tamamlandığında otomatik normal görünüm döner.</p>'
            '</section>'
        )
    return html, 200, {"Cache-Control": "no-store"}


def dashboard():
    # BYS360_DASHBOARD_REBUILD_V1_CONTEXT_ENTRY
    context = _normalize_dashboard_context(current_user, detail_level="core")
    dashboard_heavy_panels_url = request.path.rstrip("/") + "/heavy-panels"
    scope_value = (request.args.get("scope") or "").strip()
    if scope_value:
        dashboard_heavy_panels_url += f"?scope={scope_value}"
    context["dashboard_heavy_panels_url"] = dashboard_heavy_panels_url
    context["dashboard_rebuild"] = build_dashboard_rebuild_context(current_user)
    return safe_render(
        "dashboard.html",
        "<h3>BYS360 Dashboard</h3>",
        **context,
    )


def db_check():
    context = build_db_check_context(current_app.extensions.get("schema_check_errors", []))
    return safe_render(
        "db_check.html",
        f"<h3>DB Kontrol</h3><p>Sonuç: {context.get('db_result')}</p>",
        **context,
    )
