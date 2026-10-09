from __future__ import annotations

import importlib
from typing import Any

from app.api.mobile import shared as _shared

# Domain modülleri side-effect olarak route decorator kayıtlarını yapar.
from app.api.mobile.domains import (
    assistant_chat as _assistant_chat,  # noqa: F401
    auth as _auth,  # noqa: F401
    communication_v1_write as _communication_v1_write,
    communication_v2_write as _communication_v2_write,
    dashboard as _dashboard,  # noqa: F401
    kpi_target_management as _kpi_target_management,  # noqa: F401
    notifications as _notifications,  # noqa: F401
    personnel_read as _personnel_read,  # noqa: F401
    personnel_write_all as _personnel_write_all,
    push_notifications as _push_notifications,  # noqa: F401
    support_survey_write as _support_survey_write,
)
from app.api.mobile.shared import (  # noqa: F401 - re-exported for sibling performance_*_helpers modules
    User,
    _as_int,
    _full_name,
    _has_global_scope,
    _item,
    _metric,
    _module_payload,
    _safe_count,
    jsonify,
    request,
    require_mobile_user,
)

"""BYS360 mobile API facade.

Bu dosya endpoint sözleşmesini taşımaz; mobil domain modüllerini ve düşük riskli
okuma köprülerini yükleyen ince facade olarak kalır. Contract gate kuralı:
- routes.py <= 300 satır
- routes.py içinde @mobile_api_bp route decorator bulunmaz
- temel mobil endpoint sözleşmesi app/api/mobile/domains altında yaşar
"""


def _mobile_route_registry_v1() -> dict[str, Any]:
    """Exec tabanlı eski okuma köprüleri için kontrollü registry üret."""
    registry: dict[str, Any] = dict(vars(_shared))
    registry.update(
        {
            "mobile_api_bp": _shared.mobile_api_bp,
            "mobile_bp": _shared.mobile_api_bp,
            "_b46_thread_row": getattr(_communication_v1_write, "_b46_thread_row", None),
            "_b46_txt": getattr(_communication_v1_write, "_b46_txt", None),
            "_b48_thread_row": getattr(_communication_v2_write, "_b48_thread_row", None),
            "_mobile_support_status_label": getattr(_support_survey_write, "_mobile_support_status_label", None),
            "_mobile_support_priority_label": getattr(_support_survey_write, "_mobile_support_priority_label", None),
        }
    )
    return registry


def _register_bridge_v1(module_name: str, registrar_name: str) -> None:
    module = importlib.import_module(module_name)
    registrar = getattr(module, registrar_name)
    registry = _mobile_route_registry_v1()
    try:
        registrar(_shared.mobile_api_bp, registry)
    except TypeError:
        registrar(registry)


for _module_name, _registrar_name in (
    ("app.api.mobile.utility_routes", "register_mobile_utility_routes_v1"),
    ("app.api.mobile.light_read_routes", "register_mobile_light_read_routes_v1"),
    ("app.api.mobile.detail_read_routes", "register_mobile_detail_read_routes_v1"),
    ("app.api.mobile.support_survey_read_routes", "register_mobile_support_survey_read_routes_v1"),
    ("app.api.mobile.communication_read_routes", "register_mobile_communication_read_routes_v1"),
    ("app.api.mobile.communication_v2_read_routes", "register_mobile_communication_v2_read_routes_v1"),
):
    _register_bridge_v1(_module_name, _registrar_name)


def _bys360_legacy_mobile_personnel_all(user: User):
    """Mobil /personnel/all davranışını koruyan kısa legacy facade."""
    from app.services.personnel_read_grant import has_personnel_read_all_grant

    # B1-F1: institution-wide only for the global roles or an explicit personnel_read_all grant.
    global_scope = _has_global_scope(user) or has_personnel_read_all_grant(user)

    def _arg_int(*names: str, default: int = 0) -> int:
        for name in names:
            raw = request.args.get(name)
            if raw is None or str(raw).strip() == "":
                continue
            try:
                return int(float(raw))
            except Exception:
                continue
        return default

    def _txt(value: Any) -> str:
        text = str(value or "").strip()
        return "" if text.lower() in {"none", "null"} else text

    def _uv(row: Any, *attrs: str) -> str:
        for attr in attrs:
            text = _txt(getattr(row, attr, None))
            if text:
                return text
        return ""

    def _row(row: User) -> dict[str, Any]:
        full_name = _full_name(row)
        unit_name = _uv(row, "birim", "unit_name", "organization_unit_name", "department")
        upper_unit = _uv(row, "ust_birim", "upper_unit_name", "parent_unit_name")
        registry = _uv(row, "sicil_no", "registry_no", "sicil", "employee_no")
        title = _uv(row, "unvan", "title", "title_name", "position_title", "job_title")
        duty = _uv(row, "gorev", "duty", "duty_name", "position", "role_name")
        category = _uv(row, "personnel_category", "category", "kategori") or "Diğer"
        active = bool(getattr(row, "is_active", False))
        return {
            "id": getattr(row, "id", None),
            "user_id": getattr(row, "id", None),
            "full_name": full_name,
            "display_name": full_name,
            "ad_soyad": full_name,
            "first_name": _uv(row, "ad", "first_name"),
            "last_name": _uv(row, "soyad", "last_name"),
            "registry_no": registry,
            "sicil_no": registry,
            "unit_name": unit_name,
            "birim": unit_name,
            "upper_unit_name": upper_unit,
            "ust_birim": upper_unit,
            "title_name": title,
            "unvan": title,
            "duty_name": duty,
            "gorev": duty,
            "manager_name": _uv(row, "manager_name", "yonetici", "supervisor_name", "first_manager_name", "amir"),
            "personnel_category": category,
            "category": category,
            "role_label": _uv(row, "role_label", "role"),
            "role": _uv(row, "role"),
            "status_label": "Aktif" if active else "Pasif",
            "status": "Aktif" if active else "Pasif",
            "is_active": active,
            "subtitle": f"{unit_name or upper_unit or 'Birim yok'} / Sicil {registry or '-'}",
            "meta": category or title,
        }

    requested_limit = _arg_int("limit", "length", "per_page", default=10000)
    limit = max(1, min(10000, requested_limit))
    page = max(1, _arg_int("page", default=1))
    offset = max(0, _arg_int("offset", "start", default=(page - 1) * limit))
    query_text = (request.args.get("q") or request.args.get("search") or request.args.get("query") or "").strip().lower()

    query = User.query.filter_by(is_active=True) if global_scope else User.query.filter_by(id=getattr(user, "id", None))
    total_before_search = _safe_count(query)
    try:
        records = query.order_by(User.ad.asc(), User.soyad.asc()).all()
    except Exception:
        records = query.all()

    rows = [_row(row) for row in records]
    if query_text:
        rows = [row for row in rows if query_text in " ".join(str(v or "") for v in row.values()).lower()]

    total = len(rows)
    selected = rows[offset : offset + limit]
    items = []
    for row in selected:
        item = _item(row.get("id"), row.get("full_name") or "Personel", row.get("subtitle") or "", row.get("status_label") or "", row.get("meta") or "", row.get("role_label") or "", 100 if row.get("is_active") else 0)
        item.update(row)
        items.append(item)

    return jsonify(
        {
            "source": "web_personnel_user_table_all",
            "can_create_personnel": _personnel_write_all._can_mobile_create_personnel(user),
            "scope": "Genel" if global_scope else "Kendi kaydım",
            "total": total,
            "total_count": total,
            "recordsTotal": total,
            "count": total,
            "all_active_count": total_before_search,
            "limit": limit,
            "offset": offset,
            "page": page,
            "has_more": offset + limit < total,
            "metrics": [
                _metric("Aktif Personel", total, "Yetkinize göre görünen tüm kayıt", "red", "people"),
                _metric("Kapsam", "Genel" if global_scope else "Kendi kaydım", "Rol ve menü görünürlüğüne bağlı", "red", "shield"),
                _metric("Mobil Liste", "Tümü", "50 kayıt sınırı kaldırıldı", "red", "all_inclusive"),
            ],
            "items": items,
            "rows": selected,
            "personnel": selected,
        }
    )
