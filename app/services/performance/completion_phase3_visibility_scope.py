from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

"""BYS360 Performans Tamamlama Faz 3 — Görünürlük ve yetki kapsam merkezi.

Bu servis Faz 3'ün ana sözleşmesidir:
- Personel yalnızca kendi karne/verisini görür.
- Personel kendi kategori/grup ortalamasını kişi detayı olmadan görebilir.
- Koordinatör yalnızca kendi çalışma grubu/kapsamındaki personeli görür.
- Grup Başkanı yalnızca kendi grup/üst birim kapsamını görür.
- Başkan ve Admin/Sistem Yöneticisi kurum geneli görünürlük alır.
- Menü görünürlüğü tek başına güvenlik değildir; backend route ve query kapsamı burada kilitlenir.
"""

logger = logging.getLogger(__name__)

try:  # Flask yoksa birim testleri yine çalışabilsin.
    from flask import render_template
except Exception:  # pragma: no cover
    logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
    render_template = None  # type: ignore

PHASE3_VISIBILITY_SCOPE_VERSION = "2026-05-04.performance-completion.phase3.visibility-scope.v1"
BYS360_PERFORMANCE_COMPLETION_PHASE3_VISIBILITY_SCOPE = True
BYS360_PERFORMANCE_COMPLETION_PHASE3_BACKEND_SCOPE_CENTER = True
BYS360_PERFORMANCE_COMPLETION_PHASE3_NO_PERSON_DETAIL_IN_CATEGORY_AVERAGE = True
BYS360_PERFORMANCE_COMPLETION_PHASE3_CORPORATE_ACCESS_DENIED = True

ACCESS_DENIED_MESSAGE = "Bu sayfaya erişim yetkiniz bulunmamaktadır."

ADMIN_ROLES = {
    "admin",
    "super_admin",
}
# F06d (D2, approved 2026-10-09/10): the technical roles keep their technical administration but get
# no automatic access to personnel or performance data, and the generic "yonetici" is a manager, not
# an administrator. Both were in ADMIN_ROLES (institution-wide view); they are now scope-limited
# like the other managers and their scope comes from the hierarchy helper.
SCOPED_MANAGER_ROLES = {
    "system_admin",
    "sistem_yoneticisi",
    "sistem_yöneticisi",
    "yonetici",
    "yönetici",
}
PRESIDENT_ROLES = {
    "baskan",
    "başkan",
    "president",
}
UPPER_MANAGEMENT_ROLES = {
    "baskan_yardimcisi",
    "başkan_yardımcısı",
    "baskan_yardımcısı",
    "başkan_yardimcisi",
}
GROUP_HEAD_ROLES = {
    "grup_baskani",
    "grup_başkanı",
    "grup_baskanı",
    "grup_başkankani",
    "mali_musavir",
    "mali_müşavir",
}
COORDINATOR_ROLES = {
    "koordinator",
    "koordinatör",
    "birim_sorumlusu",
    "birim_sorumlusu_yonetici",
}
PERSONNEL_SUPPORT_ROLES = {
    "personel_destek_grup_baskani",
    "personel_ve_destek_hizmetleri_grup_baskani",
    "personel_ve_destek_hizmetleri_grup_başkanı",
}
PERSONNEL_ROLES = {
    "personel",
    "employee",
    "calisan",
    "çalışan",
}

ROLE_LABELS = {
    "admin": "Admin / Sistem Yöneticisi",
    "baskan": "Başkan / Üst Yönetim",
    "baskan_yardimcisi": "Başkan Yardımcısı",
    "grup_baskani": "Grup Başkanı",
    "koordinator": "Koordinatör",
    "personel_destek": "Personel ve Destek Hizmetleri Grup Başkanı",
    "personel": "Personel",
}


@dataclass(frozen=True)
class VisibilityProfile:
    role_key: str
    role_label: str
    can_view_global: bool
    own_record_only: bool
    scope_limited: bool
    can_open_reports: bool
    can_view_person_detail: bool
    can_view_category_average: bool
    category_average_without_person_detail: bool
    can_manage_visibility: bool
    can_preapprove_publish: bool
    access_denied_message: str = ACCESS_DENIED_MESSAGE

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_key": self.role_key,
            "role_label": self.role_label,
            "can_view_global": self.can_view_global,
            "own_record_only": self.own_record_only,
            "scope_limited": self.scope_limited,
            "can_open_reports": self.can_open_reports,
            "can_view_person_detail": self.can_view_person_detail,
            "can_view_category_average": self.can_view_category_average,
            "category_average_without_person_detail": self.category_average_without_person_detail,
            "can_manage_visibility": self.can_manage_visibility,
            "can_preapprove_publish": self.can_preapprove_publish,
            "access_denied_message": self.access_denied_message,
        }


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    return (
        text.replace(" ", "_")
        .replace("-", "_")
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def _role_value(user_or_role: Any) -> str:
    if isinstance(user_or_role, str):
        return user_or_role
    # B1-F1 decision 3: role_label (display text) never decides visibility.
    for attr in ("role", "role_key", "role_name"):
        value = getattr(user_or_role, attr, None)
        if value:
            return str(value)
    return ""


def resolve_visibility_role_key(user_or_role: Any) -> str:
    """Kullanıcı/rol bilgisini Faz 3 görünürlük rol anahtarına çevirir."""
    role = _norm(_role_value(user_or_role))
    raw_role = str(_role_value(user_or_role) or "").strip().lower()

    if getattr(user_or_role, "is_admin", False) or getattr(user_or_role, "is_superuser", False):
        return "admin"
    if role in {_norm(item) for item in ADMIN_ROLES}:
        return "admin"
    if role in {_norm(item) for item in PRESIDENT_ROLES}:
        return "baskan"
    if role in {_norm(item) for item in UPPER_MANAGEMENT_ROLES}:
        return "baskan_yardimcisi"
    if role in {_norm(item) for item in PERSONNEL_SUPPORT_ROLES} or "personel_ve_destek" in role:
        return "personel_destek"
    if role in {_norm(item) for item in GROUP_HEAD_ROLES} or "grup_baskan" in role:
        return "grup_baskani"
    if role in {_norm(item) for item in COORDINATOR_ROLES} or "koordinator" in role:
        return "koordinator"
    if role in {_norm(item) for item in SCOPED_MANAGER_ROLES}:
        return "koordinator"
    if raw_role in PERSONNEL_ROLES or role in {_norm(item) for item in PERSONNEL_ROLES}:
        return "personel"
    return "personel"


def build_visibility_profile(user_or_role: Any) -> VisibilityProfile:
    role_key = resolve_visibility_role_key(user_or_role)
    global_roles = {"admin", "baskan"}
    # Başkan Yardımcısı sistemde üst onay ve amirlik görünümlerinde geniş kapsamlıdır; rapor açabilir ama nihai kurum geneli yetki Admin/Başkan kadar geniş tutulmaz.
    scope_roles = {"koordinator", "grup_baskani", "baskan_yardimcisi", "personel_destek"}
    own_record_only = role_key == "personel"
    can_view_global = role_key in global_roles
    scope_limited = role_key in scope_roles
    can_open_reports = role_key in global_roles | scope_roles
    can_view_person_detail = role_key in global_roles | scope_roles
    can_preapprove_publish = role_key in {"personel_destek", "admin", "baskan"}
    can_manage_visibility = role_key in {"admin"}
    return VisibilityProfile(
        role_key=role_key,
        role_label=ROLE_LABELS.get(role_key, "Personel"),
        can_view_global=can_view_global,
        own_record_only=own_record_only,
        scope_limited=scope_limited,
        can_open_reports=can_open_reports,
        can_view_person_detail=can_view_person_detail,
        can_view_category_average=True,
        category_average_without_person_detail=own_record_only,
        can_manage_visibility=can_manage_visibility,
        can_preapprove_publish=can_preapprove_publish,
    )


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_ids(values: Iterable[Any]) -> set[int]:
    ids: set[int] = set()
    for value in values or []:
        candidate = _safe_int(getattr(value, "id", value))
        if candidate is not None:
            ids.add(candidate)
    return ids


def _all_non_admin_user_ids() -> set[int]:
    try:
        from app.models import User

        rows = User.query.filter(User.role != "admin").with_entities(User.id).all()
        return _extract_ids(rows)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return set()


def _scope_context_employee_ids(user: Any) -> set[int]:
    """Mevcut BYS360 kapsam helper'ını kullanır; hata olursa güvenli daraltır."""
    try:
        from app.view_helpers import build_surface_scope_context

        ctx = build_surface_scope_context(user, None)
        ids = ctx.get("employee_ids") or ctx.get("visible_employee_ids") or []
        resolved = _extract_ids(ids)
        if resolved:
            return resolved
        scope_users = ctx.get("scope_users") or []
        resolved = _extract_ids(scope_users)
        if resolved:
            return resolved
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/completion_phase3_visibility_scope.py")
    user_id = _safe_int(getattr(user, "id", None))
    return {user_id} if user_id is not None else set()


def phase3_allowed_employee_ids(user: Any) -> set[int]:
    """Kullanıcının performans verisinde görebileceği personel id seti.

    Kritik güvenlik kuralı: boş set hiçbir zaman 'herkes' anlamına gelmez.
    """
    if not user or not getattr(user, "is_authenticated", True):
        return set()
    profile = build_visibility_profile(user)
    user_id = _safe_int(getattr(user, "id", None))
    if profile.can_view_global:
        resolved = _all_non_admin_user_ids()
        return resolved if resolved else ({user_id} if user_id is not None else set())
    if profile.own_record_only:
        return {user_id} if user_id is not None else set()
    if profile.scope_limited:
        return _scope_context_employee_ids(user)
    return {user_id} if user_id is not None else set()


def phase3_can_view_employee(user: Any, employee_id: Any) -> bool:
    candidate = _safe_int(employee_id)
    return bool(candidate is not None and candidate in phase3_allowed_employee_ids(user))


def phase3_can_view_evaluation(user: Any, evaluation: Any) -> bool:
    return bool(evaluation and phase3_can_view_employee(user, getattr(evaluation, "employee_id", None)))


def can_view_own_scorecard(user: Any, evaluation: Any) -> bool:
    user_id = _safe_int(getattr(user, "id", None))
    employee_id = _safe_int(getattr(evaluation, "employee_id", None))
    return bool(user_id is not None and user_id == employee_id)


def phase3_can_open_performance_reports(user: Any) -> bool:
    return build_visibility_profile(user).can_open_reports


def phase3_can_view_category_average(user: Any, *, include_person_details: bool = False) -> bool:
    profile = build_visibility_profile(user)
    if include_person_details and profile.category_average_without_person_detail:
        return False
    return profile.can_view_category_average


def category_average_visibility_payload(user: Any) -> dict[str, Any]:
    profile = build_visibility_profile(user)
    return {
        "can_view_average": profile.can_view_category_average,
        "can_view_person_details": profile.can_view_person_detail and not profile.category_average_without_person_detail,
        "privacy_note": "Kategori ortalaması kişi detayı göstermeden gösterilir." if profile.category_average_without_person_detail else "Yetkili kapsam içinde kişi detayı görüntülenebilir.",
        "role_key": profile.role_key,
    }


def filter_rows_by_visibility(rows: Sequence[Any], user: Any, *, employee_id_attr: str = "employee_id") -> list[Any]:
    allowed = phase3_allowed_employee_ids(user)
    if not allowed:
        return []
    visible: list[Any] = []
    for row in rows or []:
        employee_id = _safe_int(getattr(row, employee_id_attr, None))
        if employee_id is None and hasattr(row, "employee"):
            employee_id = _safe_int(getattr(getattr(row, "employee", None), "id", None))
        if employee_id in allowed:
            visible.append(row)
    return visible


def phase3_filter_evaluation_query(query: Any, user: Any) -> Any:
    from app.models import PerformanceEvaluation

    allowed = phase3_allowed_employee_ids(user)
    if not allowed:
        return query.filter(PerformanceEvaluation.id == -1)
    return query.filter(PerformanceEvaluation.employee_id.in_(allowed))


def phase3_filter_user_query(query: Any, user: Any) -> Any:
    from app.models import User

    allowed = phase3_allowed_employee_ids(user)
    if not allowed:
        return query.filter(User.id == -1)
    return query.filter(User.id.in_(allowed))


def access_denied_context(message: str | None = None) -> dict[str, Any]:
    return {
        "access_denied": True,
        "title": "Erişim Yetkisi Bulunmamaktadır",
        "message": (message or ACCESS_DENIED_MESSAGE).strip(),
        "phase3_visibility": True,
    }


def phase3_denied_response(message: str | None = None, *, status_code: int = 403):
    safe_message = (message or ACCESS_DENIED_MESSAGE).strip()
    if render_template is not None:
        try:
            return render_template("errors/403.html", **access_denied_context(safe_message)), status_code
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/completion_phase3_visibility_scope.py")
    return (
        f"""
        <html>
          <head><title>403 - Erişim Yetkisi Bulunmamaktadır</title></head>
          <body style="font-family:Arial,sans-serif;background:#f7f7f7;padding:40px;color:#222;">
            <main style="max-width:760px;margin:auto;background:#fff;border-radius:18px;padding:32px;box-shadow:0 12px 36px rgba(0,0,0,.08);">
              <h2 style="color:#8B0000;margin-top:0;">Erişim Yetkisi Bulunmamaktadır</h2>
              <p>{safe_message}</p>
            </main>
          </body>
        </html>
        """,
        status_code,
    )


def phase3_enforce_evaluation_access(user: Any, evaluation: Any):
    if phase3_can_view_evaluation(user, evaluation):
        return None
    return phase3_denied_response(ACCESS_DENIED_MESSAGE)


__all__ = [
    "PHASE3_VISIBILITY_SCOPE_VERSION",
    "BYS360_PERFORMANCE_COMPLETION_PHASE3_VISIBILITY_SCOPE",
    "VisibilityProfile",
    "resolve_visibility_role_key",
    "build_visibility_profile",
    "phase3_allowed_employee_ids",
    "phase3_can_view_employee",
    "phase3_can_view_evaluation",
    "phase3_enforce_evaluation_access",
    "phase3_filter_evaluation_query",
    "phase3_filter_user_query",
    "phase3_can_open_performance_reports",
    "phase3_can_view_category_average",
    "category_average_visibility_payload",
    "filter_rows_by_visibility",
    "access_denied_context",
    "phase3_denied_response",
]
