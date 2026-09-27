from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

def _phase2_publish_preflight_rules():
    """Publish preflight kurallarını uygulama açılışında değil, ihtiyaç anında yükler."""
    from app.services.performance import publish_preflight_rules as _rules
    return _rules


def is_evaluation_publishable_strict(period, evaluation):
    return _phase2_publish_preflight_rules().is_evaluation_publishable_strict(period, evaluation)


def is_president_exempt(evaluation):
    return _phase2_publish_preflight_rules().is_president_exempt(evaluation)


def validate_evaluation_for_publish(period, evaluation):
    return _phase2_publish_preflight_rules().validate_evaluation_for_publish(period, evaluation)


"""BYS360 performans görünürlük anayasası.

Bu dosya not karnesi, yayın durumu ve değerlendirme formunda önceki amir
puan/kanaati görünürlüğü için tek merkezdir. Amaç iki farklı görünürlüğü
kesin biçimde ayırmaktır:

1. Değerlendirici görünürlüğü: Amir, yetkili olduğu personel için önceki
   amir puan ve kanaatini görebilir; kör değerlendirme yoktur.
2. Kendi sonuç görünürlüğü: Personel ya da amir, kendi kişisel sonucunu
   İK/yayın kilidi açılmadan göremez.
"""

# Düşük performans yayın kilidi servisi yüklenemezse karne personele sessizce
# açılmaz (fail-closed): yedek fonksiyon aynı imzayla her değerlendirme için
# boş olmayan bir kilit nedeni döndürür; çağıranlar bunu kilit olarak okur.
LOW_SCORE_LOCK_UNAVAILABLE_REASON = (
    "70 altı yayın kilidi bilgisi bu anda okunamadı; görünürlük kilidi korunarak devam edildi."
)

try:
    from app.services.performance.low_score_process_service import (
        get_low_score_employee_publish_lock_reason,
    )
except Exception:  # pragma: no cover - startup güvenliği
    logger.exception(
        "BYS360_LOW_SCORE_VISIBILITY_FAIL_CLOSED | Düşük performans yayın kilidi servisi yüklenemedi; "
        "görünürlük fail-closed moda geçti: personel karne görünürlüğü güvenlik nedeniyle kilitli "
        "tutuluyor. Bu durum uygulama yeniden başlatılana kadar sürebilir."
    )
    def get_low_score_employee_publish_lock_reason(evaluation=None, *, ensure=False):
        return LOW_SCORE_LOCK_UNAVAILABLE_REASON


VISIBILITY_RULE_VERSION = "2026-04-18-scorecard-visibility-lock-v2"
PUBLISHABLE_FINAL_STATUSES = {"tamamlandi", "tamamlandı", "completed", "published"}
PRIVILEGED_SCORECARD_ROLES = {
    "admin",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "koordinator",
    "birim_sorumlusu",
}
BLIND_REVIEW_ALLOWED = False


def _normalize_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_status(value: Any) -> str:
    return _normalize_text(value).lower()


def _normalize_role(value: Any) -> str:
    return _normalize_text(value).lower()


def _viewer_id(viewer: Any | None) -> int | None:
    try:
        value = getattr(viewer, "id", None)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _employee_id(evaluation: Any | None) -> int | None:
    try:
        value = getattr(evaluation, "employee_id", None)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_id_set(values: Iterable[Any] | None) -> set[int]:
    result: set[int] = set()
    for item in values or []:
        try:
            if item is not None:
                result.add(int(item))
        except (TypeError, ValueError):
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/visibility_guard.py:90)")
            continue
    return result


def _is_authenticated(viewer: Any | None) -> bool:
    if not viewer:
        return False
    authenticated = getattr(viewer, "is_authenticated", True)
    try:
        return bool(authenticated() if callable(authenticated) else authenticated)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def is_privileged_scorecard_viewer(viewer: Any | None) -> bool:
    if not _is_authenticated(viewer):
        return False
    return _normalize_role(getattr(viewer, "role", "")) in PRIVILEGED_SCORECARD_ROLES


def is_evaluation_publish_exempt(evaluation: Any | None) -> bool:
    return is_president_exempt(evaluation)


def is_evaluation_completed(evaluation: Any | None) -> bool:
    if not evaluation:
        return False
    return _normalize_status(getattr(evaluation, "status", "")) in PUBLISHABLE_FINAL_STATUSES


def is_employee_published(evaluation: Any | None) -> bool:
    return bool(getattr(evaluation, "is_published_to_employee", False)) if evaluation else False


def is_period_published(evaluation: Any | None) -> bool:
    period = getattr(evaluation, "period", None) if evaluation else None
    return bool(getattr(period, "results_published", False))


def is_employee_visible(evaluation: Any | None) -> bool:
    """Personelin kendi sonucunu görmesi için tek geçerli kilit."""
    # BYS360_PHASE6_2_LOW_SCORE_EMPLOYEE_VISIBILITY_LOCK
    if not evaluation:
        return False
    if get_low_score_employee_publish_lock_reason(evaluation, ensure=False):
        return False
    return bool(
        evaluation
        and is_evaluation_completed(evaluation)
        and is_period_published(evaluation)
        and is_employee_published(evaluation)
    )


def is_evaluation_publishable(period: Any, evaluation: Any) -> tuple[bool, str]:
    """Yayın kararı Dalga 6 yayın ön kontrol motorundan geçer."""
    return is_evaluation_publishable_strict(period, evaluation)


# BYS360_PHASE6_2_VISIBILITY_STATE_CONTRACT_V2
def _safe_phase6_2_publishable_result(period: Any, evaluation: Any) -> tuple[bool, str]:
    """Yayın ön kontrol importu geç yüklenirken oluşabilecek döngüyü görünürlük ekranına taşımaz."""
    try:
        return is_evaluation_publishable(period, evaluation)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False, ""


def _safe_phase6_2_visibility_lock_hint(period: Any, evaluation: Any) -> tuple[str, str]:
    """Karne görünürlük state'i gate/runtime kontrolünde preflight importuna takılmasın."""
    try:
        return build_visibility_lock_hint(period, evaluation)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        if not bool(getattr(period, "results_published", False)):
            return "Dönem henüz toplu yayına açılmadığı için sonuç personele görünmez.", "period_publish_off"
        if not bool(getattr(evaluation, "is_published_to_employee", False)):
            return "İK yayın kilidi devam ediyor; sonuç henüz personele açılmadı.", "employee_publish_off"
        return "Bu karne henüz görüntülenebilir durumda değil.", "locked"


def _safe_phase6_2_publish_preflight_dict(period: Any, evaluation: Any) -> dict[str, Any]:
    """Preflight sözlüğünü güvenli üretir; görünürlük state'i hiçbir zaman import döngüsüyle patlamaz."""
    try:
        result = validate_evaluation_for_publish(period, evaluation)
        if hasattr(result, "as_dict"):
            return result.as_dict()
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return {
            "ok": False,
            "reason": "Yayın ön kontrol bilgisi bu anda okunamadı; görünürlük kilidi korunarak devam edildi.",
            "rule_version": VISIBILITY_RULE_VERSION,
            "blockers": [],
            "warnings": [{"code": "preflight_runtime_unavailable", "message": str(exc), "severity": "warning"}],
            "infos": [],
        }
    return {"ok": False, "reason": "Yayın ön kontrol sonucu okunamadı.", "rule_version": VISIBILITY_RULE_VERSION, "blockers": [], "warnings": [], "infos": []}


def build_visibility_lock_hint(period: Any, evaluation: Any) -> tuple[str, str]:
    publishable, publish_reason = is_evaluation_publishable(period, evaluation)
    if publish_reason:
        return publish_reason, "publish_guard"
    if not bool(getattr(period, "results_published", False)):
        return "Dönem henüz toplu yayına açılmadığı için sonuç personele görünmez.", "period_publish_off"
    if not bool(getattr(evaluation, "is_published_to_employee", False)):
        return "İK yayın kilidi devam ediyor; sonuç henüz personele açılmadı.", "employee_publish_off"
    if publishable:
        return "Sonuç henüz personele açılmadı.", "employee_publish_off"
    return "Bu karne henüz görüntülenebilir durumda değil.", "locked"


def get_evaluation_visibility_state(
    evaluation: Any | None,
    viewer: Any | None = None,
    allowed_employee_ids: set[int] | list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    if not evaluation:
        return {
            "rule_version": VISIBILITY_RULE_VERSION,
            "can_view": False,
            "can_view_unpublished": False,
            "employee_visible": False,
            "same_employee": False,
            "viewer_is_privileged": False,
            "completed": False,
            "period_published": False,
            "employee_published": False,
            "own_result_locked": False,
            "publish_state": "missing",
            "publish_label": "Kayıt Yok",
            "publish_badge_class": "locked",
            "reason": "Değerlendirme bulunamadı.",
            "reason_code": "missing_evaluation",
            "lock_reason": "Değerlendirme bulunamadı.",
            "next_action": "İlgili karne kaydını yeniden oluşturun ya da dönemi kontrol edin.",
            "publishable": False,
        }

    period = getattr(evaluation, "period", None)
    completed = is_evaluation_completed(evaluation)
    period_published = bool(getattr(period, "results_published", False))
    employee_published = is_employee_published(evaluation)
    # BYS360_PHASE6_2_LOW_SCORE_VISIBILITY_STATE_LOCK
    phase6_2_low_score_publish_lock_reason = get_low_score_employee_publish_lock_reason(evaluation, ensure=False)
    phase6_2_low_score_publish_locked = bool(phase6_2_low_score_publish_lock_reason)
    employee_visible = completed and period_published and employee_published and not phase6_2_low_score_publish_locked

    same_employee = bool(_viewer_id(viewer) is not None and _viewer_id(viewer) == _employee_id(evaluation))
    viewer_is_privileged = is_privileged_scorecard_viewer(viewer)
    normalized_allowed_ids = _coerce_id_set(allowed_employee_ids)
    eval_employee_id = _employee_id(evaluation)
    # BYS360_PHASE3_VISIBILITY_PERMISSION_SCOPE_GUARD
    # Boş kapsam listesi artık "herkesi gör" anlamına gelmez. Genel görünüm yalnızca
    # Başkan/Admin/Sistem Yöneticisi aileleri için açıktır; koordinatör ve grup başkanı
    # sadece allowed_employee_ids içinde kalan personeli görebilir.
    phase3_general_roles = {"admin", "sistem_yoneticisi", "system_admin", "super_admin", "baskan", "baskan_yardimcisi"}
    viewer_role = _normalize_role(getattr(viewer, "role", ""))
    phase3_general_scope = viewer_role in phase3_general_roles
    in_scope = bool(same_employee or phase3_general_scope or (eval_employee_id in normalized_allowed_ids))

    # Yönetici başkasının karnesini yetki alanında iç kullanım olarak görebilir.
    # Ancak hiçbir amir/admin kendi kişisel sonucunu yayın öncesi göremez.
    can_view_unpublished = bool(viewer_is_privileged and in_scope and completed and not same_employee)
    own_result_locked = bool(same_employee and not employee_visible)
    can_view = bool(employee_visible or can_view_unpublished)

    publishable, publish_reason = _safe_phase6_2_publishable_result(period, evaluation)
    lock_reason, lock_code = _safe_phase6_2_visibility_lock_hint(period, evaluation)

    if not completed:
        publish_state = "not_completed"
        publish_label = "Tamamlanmadı"
        publish_badge_class = "locked"
        reason = "Değerlendirme tamamlanmadığı için karne görünür değil."
        reason_code = "not_completed"
        next_action = "Önce eksik amir adımlarını tamamlayın."
    elif employee_visible:
        publish_state = "published"
        publish_label = "Personele Açık"
        publish_badge_class = "published"
        reason = ""
        reason_code = "published"
        next_action = "Karne görüntülenebilir durumda."
    elif can_view_unpublished:
        publish_state = "internal_preview"
        publish_label = "İç Kullanım"
        publish_badge_class = "internal"
        reason = publish_reason or "Bu karne henüz personele açılmadı; yalnızca yetkili görünümünde gösterilir."
        reason_code = lock_code if publish_reason else "internal_preview"
        next_action = "Yayın ön kontrol ekranında bloke nedeni kapanınca personele açılabilir."
    elif same_employee:
        if phase6_2_low_score_publish_locked:
            publish_state = "low_score_publish_locked"
            publish_label = "Başkan/Üst Onay Yayın Kilidi"
            publish_badge_class = "locked"
            reason = phase6_2_low_score_publish_lock_reason
            reason_code = "low_score_publish_lock"
            next_action = "İK/Admin ön kontrolü, Başkan/üst onayı ve personel süreç kaydı tamamlandıktan sonra karne personele açılır."
        else:
            publish_state = "employee_locked"
            publish_label = "İK Yayın Kilidi"
            publish_badge_class = "locked"
            reason = lock_reason
            reason_code = lock_code if lock_code != "locked" else "employee_locked"
            next_action = "İK yayın adımı tamamlandıktan sonra karne personele açılır."
    else:
        publish_state = "locked"
        publish_label = "Kapalı"
        publish_badge_class = "locked"
        reason = lock_reason
        reason_code = lock_code
        next_action = "Kapsam ve yayın kurallarını kontrol edin."

    return {
        "rule_version": VISIBILITY_RULE_VERSION,
        "can_view": can_view,
        "can_view_unpublished": can_view_unpublished,
        "employee_visible": employee_visible,
        "same_employee": same_employee,
        "viewer_is_privileged": viewer_is_privileged,
        "completed": completed,
        "period_published": period_published,
        "employee_published": employee_published,
        # BYS360_PHASE6_2_VISIBILITY_STATE_LOW_SCORE_LOCK_KEYS
        "low_score_publish_locked": phase6_2_low_score_publish_locked,
        "low_score_publish_lock_reason": phase6_2_low_score_publish_lock_reason,
        "phase6_2_low_score_publish_locked": phase6_2_low_score_publish_locked,
        "own_result_locked": own_result_locked,
        "publish_state": publish_state,
        "publish_label": publish_label,
        "publish_badge_class": publish_badge_class,
        "reason": reason,
        "reason_code": reason_code,
        "lock_reason": lock_reason,
        "next_action": next_action,
        "publishable": publishable,
        "publish_preflight": _safe_phase6_2_publish_preflight_dict(period, evaluation),
    }


def can_employee_view_evaluation(evaluation: Any | None, employee: Any) -> bool:
    if not evaluation or not employee:
        return False
    if _employee_id(evaluation) != _viewer_id(employee):
        return False
    visibility = get_evaluation_visibility_state(evaluation, employee, allowed_employee_ids={_viewer_id(employee) or 0})
    return bool(visibility.get("employee_visible", False))


def completed_previous_levels_for_form(evaluation: Any | None, current_level: int | None) -> list[int]:
    """Akış 3 -> 2 -> 1 olduğu için mevcut seviyeden önceki tamamlanmış adımlar."""
    try:
        level = int(current_level or 0)
    except (TypeError, ValueError):
        return []

    if level <= 0:
        return []
    previous_levels = [candidate for candidate in (3, 2, 1) if candidate > level]
    return [
        candidate
        for candidate in previous_levels
        if bool(getattr(evaluation, f"level_{candidate}_completed", False))
    ]


def build_evaluation_form_visibility_context(evaluation: Any | None, assignment: Any | None) -> dict[str, Any]:
    level = getattr(assignment, "manager_level", None) if assignment else None
    previous_levels = completed_previous_levels_for_form(evaluation, level)
    return {
        "rule_version": VISIBILITY_RULE_VERSION,
        "blind_review_allowed": BLIND_REVIEW_ALLOWED,
        "current_level": level,
        "visible_previous_levels": previous_levels,
        "can_see_previous_scores": bool(previous_levels) and not BLIND_REVIEW_ALLOWED,
        "previous_score_hint": "Kör değerlendirme yok; tamamlanmış önceki amir puan ve kanaatleri görünür." if previous_levels else "Önceki tamamlanmış amir kaydı yok.",
    }
