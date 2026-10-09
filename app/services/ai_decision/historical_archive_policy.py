
"""BYS360 AI Karar Destek Faz 7 geçmiş karne arşivi politikası.

Bu servis eski yıl karne/puan kayıtlarını karar destek merkezine güvenli,
kişi detayı korumalı ve kurumsal Türkçe çıktılarla bağlar. İdari karar
üretmez; geçmiş veriyi özet, eğilim ve dikkat alanı olarak sunar.

BYS360_AI_DECISION_FAZ7_HISTORICAL_ARCHIVE_POLICY
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def safe_attr(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).replace(",", ".")))
    except Exception:
        return default


def display_score(value: Any) -> str:
    numeric = to_float(value)
    if numeric is None:
        return "—"
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def score_band(score: Any, low_limit: float = 70.0, high_limit: float = 90.0) -> str:
    value = to_float(score)
    if value is None:
        return "score_missing"
    if value < low_limit:
        return "low"
    if value >= high_limit:
        return "high"
    return "standard"


def score_band_label(score: Any, low_limit: float = 70.0, high_limit: float = 90.0) -> str:
    return {
        "low": "Düşük performans geçmişi",
        "high": "Yüksek başarı geçmişi",
        "standard": "Standart performans geçmişi",
        "score_missing": "Puan bilgisi eksik",
    }[score_band(score, low_limit, high_limit)]


def trend_label(scores_desc: list[float]) -> str:
    """Yeni kayıttan eski kayda doğru sıralı puanlarla sade eğilim üretir."""
    if len(scores_desc) < 2:
        return "Eğilim için yeterli geçmiş kayıt yok"
    newest, previous = scores_desc[0], scores_desc[1]
    diff = newest - previous
    if diff >= 5:
        return "Son kayıtta belirgin yükseliş var"
    if diff <= -5:
        return "Son kayıtta belirgin düşüş var"
    return "Son kayıt önceki dönemle dengeli görünüyor"


def risk_level_from_history(scores_desc: list[float], low_limit: float = 70.0) -> str:
    if not scores_desc:
        return "Kayıt yok"
    low_count = sum(1 for score in scores_desc if score < low_limit)
    if low_count >= 2:
        return "Tekrarlayan düşük performans geçmişi izlenmeli"
    if scores_desc[0] < low_limit:
        return "Son geçmiş kayıtta düşük performans görülüyor"
    return "Geçmiş kayıtlarda kritik tekrar sinyali yok"


@dataclass(frozen=True)
class ArchivePolicy:
    low_score_limit: float = 70.0
    high_score_limit: float = 90.0
    detail_for_personnel_only: bool = True
    manager_summary_only: bool = True

    def band_label(self, score: Any) -> str:
        return score_band_label(score, self.low_score_limit, self.high_score_limit)

    def band(self, score: Any) -> str:
        return score_band(score, self.low_score_limit, self.high_score_limit)


def build_archive_policy(settings: Mapping[str, Any] | None = None) -> ArchivePolicy:
    settings = settings or {}
    return ArchivePolicy(
        low_score_limit=to_float(settings.get("faz7_low_score_limit"), 70.0) or 70.0,
        high_score_limit=to_float(settings.get("faz7_high_score_limit"), 90.0) or 90.0,
        detail_for_personnel_only=str(settings.get("faz7_detail_for_personnel_only", "true")).lower() not in {"0", "false", "hayir", "hayır", "no"},
        manager_summary_only=str(settings.get("faz7_manager_summary_only", "true")).lower() not in {"0", "false", "hayir", "hayır", "no"},
    )


# B1-F1 (approved least-privilege policy, 2026-10-09): performans_yetkilisi and the HR
# roles (ik, insan_kaynaklari) no longer read any user's archived result by role name, and
# (decision 2) neither do the technical sistem_yoneticisi roles. Like /performance/archive,
# everyone else sees only their own history here.
DETAIL_ALLOWED_ROLES = {
    "admin", "super_admin",
    "baskan", "başkan", "ust_yonetim", "üst yönetim",
}


def user_role_text(user: Any) -> str:
    role = safe_attr(user, "role", "role_name", "rol", default="")
    if not role:
        role_obj = safe_attr(user, "role_obj", "role_record", default=None)
        role = safe_attr(role_obj, "name", "role_name", default="")
    return str(role or "").strip().lower()


def can_view_archive_detail(user: Any, target_user_id: Any) -> bool:
    role = user_role_text(user)
    if role in DETAIL_ALLOWED_ROLES:
        return True
    current_id = safe_attr(user, "id", "user_id", default=None)
    return str(current_id) == str(target_user_id)


def can_view_archive_summary(user: Any) -> bool:
    # BYS360 DEFECT AQ: önceden burada SUMMARY_ALLOWED_ROLE_PARTS adlı ayrı
    # bir alt dize listesi vardı ("ik" gibi 2 karakterlik çıplak bir jeton
    # dahil) -- rol metninde bu jetonlardan biri GEÇİYORSA (tam eşleşme
    # olmasa bile) özet erişimi veriyordu. "İktisat Uzmanı" gibi sıradan bir
    # unvan "ik" alt dizesini içerdiği için (iktisat) ilgisiz bir uzmana
    # şirket geneli arşiv özeti açıyordu. Artık zaten var olan, kardeş
    # fonksiyon can_view_archive_detail'in kullandığı tam eşleşmeli
    # DETAIL_ALLOWED_ROLES kümesi yeniden kullanılıyor -- yeni bir liste
    # icat edilmedi.
    return user_role_text(user) in DETAIL_ALLOWED_ROLES
