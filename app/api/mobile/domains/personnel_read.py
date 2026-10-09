from __future__ import annotations

# BYS360_P1C_MOBILE_ROUTES_DOMAIN_SPLIT
# Domain: personnel_read
# Bu modül mobil API endpoint sözleşmesini domain bazlı taşır.
# URL/endpoint isimleri korunur; ortak yardımcılar shared.py içinden gelir.
from app.api.mobile.shared import (
    User,
    _full_name,
    _has_global_scope,
    _item,
    _metric,
    _module_payload,
    _safe_count,
    mobile_api_bp,
    require_mobile_user,
)


@mobile_api_bp.get("/personnel/list")
@require_mobile_user
def mobile_personnel_list(user: User):
    from app.services.personnel_read_grant import has_personnel_read_all_grant

    # B1-F1: institution-wide only for the global roles or an explicit personnel_read_all grant.
    global_scope = _has_global_scope(user) or has_personnel_read_all_grant(user)
    q = User.query.filter_by(is_active=True) if global_scope else User.query.filter_by(id=user.id)
    total = _safe_count(q)
    items = []
    for u in q.order_by(User.ad.asc(), User.soyad.asc()).limit(10000).all():
        items.append(_item(
            u.id,
            _full_name(u),
            f"{getattr(u, 'birim', '') or getattr(u, 'ust_birim', '') or 'Birim yok'} / Sicil {getattr(u, 'sicil_no', '-')}",
            "Aktif" if getattr(u, "is_active", False) else "Pasif",
            getattr(u, "personnel_category", None) or getattr(u, "unvan", "") or "",
            getattr(u, "role_label", None) or getattr(u, "role", "") or "",
            100 if getattr(u, "is_active", False) else 0,
        ))
    return _module_payload([
        _metric("Aktif Personel", total, "Yetkinize göre görünen kayıt", "red", "people"),
        _metric("Kapsam", "Genel" if global_scope else "Kendi kaydım", "Rol ve menü görünürlüğüne bağlı", "red", "shield"),
        _metric("Kategori", "Gerçek", "Personel kategori alanından okunur", "red", "category"),
    ], items)


# BYS360 P11-B9: mobile_performance_tasks_legacy performance read route app/api/mobile/performance_read_routes.py modülüne taşındı.


# BYS360 P11-B2: mobile_kpi_goals utility route app/api/mobile/utility_routes.py modülüne taşındı.


# BYS360 P11-B3: mobile_ai_insights light read route app/api/mobile/light_read_routes.py modülüne taşındı.


# BYS360 P11-B3: mobile_assistant_suggestions light read route app/api/mobile/light_read_routes.py modülüne taşındı.


# BYS360 P11-B6: mobile_notifications communication read route app/api/mobile/communication_read_routes.py modülüne taşındı.

