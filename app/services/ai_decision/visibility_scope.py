
"""BYS360 AI Karar Destek Faz 3 görünürlük ve kapsam sözleşmesi.

Bu dosya karar destek çıktılarının rol, birim, kategori ve kişi kapsamına göre
sınırlandırılması için tek merkezli, deterministik bir politika üretir. Kural
şudur: kullanıcı yalnızca görev/rol/yetki kapsamındaki karar destek özetini
alır; personel seviyesinde yetkisiz ayrıntı açılmaz.

BYS360_AI_DECISION_FAZ3_VISIBILITY_SCOPE
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

AI_DECISION_MENU_KEYS: tuple[str, ...] = (
    "ai_decision_center",
    "ai_decision.performance_scope",
    "ai_decision.visibility_scope",
    "performance.ai_decision",
    "decision_support",
)

# B1-F1 decision 2: sistem_yoneticisi / system_admin are technical roles; technical
# administration does not open institution-wide performance evaluations.
_FULL_SCOPE_ROLES = {
    "admin",
    "administrator",
    "super_admin",
    "baskan",
    "baskanlik",
    "ust_yonetim",
    "president",
}

# B1-F1 (approved least-privilege policy, 2026-10-09): ik, insan_kaynaklari and
# performans_yetkilisi get no institution-wide evaluation summary or person-level detail
# by role name; they fall to own_scope.
_HR_PERFORMANCE_SCOPE_ROLES = {
    "personel_destek",
    "personel_ve_destek_hizmetleri_grup_baskani",
    "performans_admin",
}

_MANAGER_SCOPE_ROLES = {
    "grup_baskani",
    "grup_baskanı",
    "koordinator",
    "koordinatör",
    "amir",
    "yonetici",
    "birim_amiri",
    "mudur",
    "müdür",
}

_PERSONNEL_ROLES = {
    "personel",
    "employee",
    "standart_kullanici",
    "standart_kullanıcı",
    "kullanici",
    "kullanıcı",
}

_TURKISH_TRANSLATION = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
)


def normalize_role_name(value: Any) -> str:
    """Rol metnini karşılaştırmaya uygun hale getirir."""
    text = str(value or "").strip().lower().translate(_TURKISH_TRANSLATION)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "personel"


def normalize_label(value: Any) -> str:
    """Birim/kategori etiketini sade karşılaştırma anahtarına dönüştürür."""
    text = str(value or "").strip().lower().translate(_TURKISH_TRANSLATION)
    text = re.sub(r"\s+", " ", text)
    return text


def _compact(values: Iterable[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue
        key = normalize_label(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class AIDecisionVisibilityScope:
    """Karar destek görünürlüğü için kullanıcı kapsamı."""

    user_id: int | None
    role: str
    role_group: str
    can_open_center: bool
    can_view_global_summary: bool
    can_view_person_level_detail: bool
    can_view_unit_scope: bool
    can_view_category_scope: bool
    can_view_own_summary: bool
    allowed_unit_names: tuple[str, ...] = field(default_factory=tuple)
    allowed_upper_unit_names: tuple[str, ...] = field(default_factory=tuple)
    allowed_category_labels: tuple[str, ...] = field(default_factory=tuple)
    denied_reason: str | None = None

    @property
    def is_global(self) -> bool:
        return bool(self.can_view_global_summary)

    @property
    def is_restricted(self) -> bool:
        return not self.is_global

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "role": self.role,
            "role_group": self.role_group,
            "can_open_center": self.can_open_center,
            "can_view_global_summary": self.can_view_global_summary,
            "can_view_person_level_detail": self.can_view_person_level_detail,
            "can_view_unit_scope": self.can_view_unit_scope,
            "can_view_category_scope": self.can_view_category_scope,
            "can_view_own_summary": self.can_view_own_summary,
            "allowed_unit_names": list(self.allowed_unit_names),
            "allowed_upper_unit_names": list(self.allowed_upper_unit_names),
            "allowed_category_labels": list(self.allowed_category_labels),
            "denied_reason": self.denied_reason,
            "corporate_notice": (
                "Karar Destek Merkezi yalnızca yetki kapsamındaki özetleri gösterir; "
                "idari karar üretmez ve yetkisiz personel ayrıntısı açmaz."
            ),
        }


def role_group_for(user_or_role: Any) -> str:
    # BYS360 DEFECT AQ: burada önceden bir "esnek eşleştirme" bloğu vardı --
    # rol metninde "admin", "baskan" (grup hariç) gibi alt dizeler geçiyorsa
    # tam rol kodu eşleşmese bile "global" (şirket geneli, kısıtlanmamış
    # performans değerlendirme görünürlüğü) veya "performance_authority"
    # kapsamı veriyordu. Bu, "Başkanlığı Uzmanı" gibi unvanı sadece "baskan"
    # alt dizesini İÇEREN sıradan bir uzmanı gerçek Başkan ile aynı
    # yetkiye taşıyordu (bkz. process_engine_phase6_president_approvals.py
    # is_president_user'ın kendi yorumu: "kurum adı veya 'Başkanlığı' metni
    # yetki vermez"). Kanonik rol kodu dışındaki her girdi artık güvenli
    # varsayılan olan "own_scope"a düşer -- yeni bir substring/allowlist
    # icat edilmedi, yalnızca zaten var olan tam-eşleşme kümeleri kullanılıyor.
    role = normalize_role_name(getattr(user_or_role, "role", user_or_role))
    if role in {normalize_role_name(item) for item in _FULL_SCOPE_ROLES}:
        return "global"
    if role in {normalize_role_name(item) for item in _HR_PERFORMANCE_SCOPE_ROLES}:
        return "performance_authority"
    if role in {normalize_role_name(item) for item in _MANAGER_SCOPE_ROLES}:
        return "manager_scope"
    return "own_scope"


def build_ai_decision_scope(user: Any) -> AIDecisionVisibilityScope:
    """Kullanıcıdan Faz 3 karar destek görünürlük kapsamı üretir."""
    if user is None or not getattr(user, "is_authenticated", True):
        return AIDecisionVisibilityScope(
            user_id=None,
            role="anonymous",
            role_group="denied",
            can_open_center=False,
            can_view_global_summary=False,
            can_view_person_level_detail=False,
            can_view_unit_scope=False,
            can_view_category_scope=False,
            can_view_own_summary=False,
            denied_reason="Oturum bilgisi bulunamadı.",
        )

    # B1-F1 decision 3: scope comes from the stored role only; role_label is display text.
    role = normalize_role_name(getattr(user, "role", None))
    group = role_group_for(role)
    user_id = getattr(user, "id", None)
    unit_names = _compact((getattr(user, "birim", None),))
    upper_unit_names = _compact((getattr(user, "ust_birim", None),))
    category_labels = _compact(
        (
            getattr(user, "personnel_category", None),
            getattr(getattr(user, "performance_category", None), "name", None),
        )
    )

    if group == "global":
        return AIDecisionVisibilityScope(
            user_id=user_id,
            role=role,
            role_group=group,
            can_open_center=True,
            can_view_global_summary=True,
            can_view_person_level_detail=True,
            can_view_unit_scope=True,
            can_view_category_scope=True,
            can_view_own_summary=True,
            allowed_unit_names=unit_names,
            allowed_upper_unit_names=upper_unit_names,
            allowed_category_labels=category_labels,
        )

    if group == "performance_authority":
        return AIDecisionVisibilityScope(
            user_id=user_id,
            role=role,
            role_group=group,
            can_open_center=True,
            can_view_global_summary=True,
            can_view_person_level_detail=True,
            can_view_unit_scope=True,
            can_view_category_scope=True,
            can_view_own_summary=True,
            allowed_unit_names=unit_names,
            allowed_upper_unit_names=upper_unit_names,
            allowed_category_labels=category_labels,
        )

    if group == "manager_scope":
        return AIDecisionVisibilityScope(
            user_id=user_id,
            role=role,
            role_group=group,
            can_open_center=True,
            can_view_global_summary=False,
            can_view_person_level_detail=True,
            can_view_unit_scope=True,
            can_view_category_scope=True,
            can_view_own_summary=True,
            allowed_unit_names=unit_names,
            allowed_upper_unit_names=upper_unit_names,
            allowed_category_labels=category_labels,
        )

    return AIDecisionVisibilityScope(
        user_id=user_id,
        role=role,
        role_group="own_scope",
        can_open_center=False,
        can_view_global_summary=False,
        can_view_person_level_detail=False,
        can_view_unit_scope=False,
        can_view_category_scope=True,
        can_view_own_summary=True,
        allowed_unit_names=unit_names,
        allowed_upper_unit_names=upper_unit_names,
        allowed_category_labels=category_labels,
        denied_reason="Karar Destek Merkezi yönetici ve yetkili kullanıcı görünürlüğündedir.",
    )


def same_scope_label(left: Any, right: Any) -> bool:
    return bool(normalize_label(left)) and normalize_label(left) == normalize_label(right)


def user_matches_scope(scope: AIDecisionVisibilityScope, target_user: Any) -> bool:
    """Hedef personelin kullanıcının yetkili kapsamına girip girmediğini kontrol eder."""
    if scope.can_view_global_summary:
        return True
    if scope.user_id and getattr(target_user, "id", None) == scope.user_id:
        return bool(scope.can_view_own_summary)

    target_unit = getattr(target_user, "birim", None)
    target_upper_unit = getattr(target_user, "ust_birim", None)
    target_category = getattr(target_user, "personnel_category", None) or getattr(
        getattr(target_user, "performance_category", None),
        "name",
        None,
    )

    if scope.can_view_unit_scope:
        if any(same_scope_label(item, target_unit) for item in scope.allowed_unit_names):
            return True
        if any(same_scope_label(item, target_upper_unit) for item in scope.allowed_upper_unit_names):
            return True
    return bool(scope.can_view_category_scope and any(same_scope_label(item, target_category) for item in scope.allowed_category_labels))


def build_safe_scope_payload(scope: AIDecisionVisibilityScope, *, include_menu_keys: bool = True) -> dict[str, Any]:
    payload = scope.to_dict()
    if include_menu_keys:
        payload["menu_keys"] = list(AI_DECISION_MENU_KEYS)
    payload["visibility_rules"] = [
        "Başkan, Admin ve performans yetkilileri genel karar destek özetini görebilir.",
        "Grup Başkanı, Koordinatör ve amirler yalnızca kendi yetki kapsamındaki veriyi görebilir.",
        "Personel için kişi detayı içeren karar destek ekranı açılmaz; yalnızca kendi yayınlanmış özeti ve kişi detayı içermeyen ortalama kullanılabilir.",
        "Doğrudan URL ile erişimde de aynı kapsam kontrolü uygulanır.",
    ]
    return payload
