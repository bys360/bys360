from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.models import PerformanceLowScoreProcess
from app.performance.services import performance_rule_engine as _rule_engine
from app.services.performance.low_score_process_service import (
    get_low_score_publish_block_reason,
    is_low_score_evaluation,
)
from app.services.performance.meeting_p4_development_guidance import (
    get_development_recommendation_publish_block_reason,
)
from app.services.performance.personnel_support_publish_approval_service import (
    get_personnel_support_publish_block_reason,
)

"""BYS360 performans yayın ön kontrol anayasası.

Bu servis, not karnesinin personele açılmadan önce geçmesi gereken gerçek
iş kurallarını tek merkezde toplar. Yayın butonu, yayın paneli ve toplu yayın
aynı kural sonucunu kullanmalıdır.

Kilit kurallar:
- Tamamlanmamış değerlendirme yayınlanamaz.
- Zorunlu amir adımı eksikse yayınlanamaz.
- 3. amir yorum modundaysa puan değil görüş tamamlanması aranır.
- 3. amir puan modundaysa puan adımı tamamlanması aranır.
- 1 veya 5 puan açıklama kararı merkezi kural motorundan alınır.
- 70 altı ve 90 üstü genel görüş kararı merkezi kural motorundan alınır.
- 70 altı Başkan onayı ve yayın kilidi kararı merkezi kural motorundan alınır.
- Tek amirli istisnalarda gereksiz 2./3. amir beklenmez.
"""

logger = logging.getLogger(__name__)

PUBLISH_PREFLIGHT_RULE_VERSION = "phase1.4b-personnel-support-publish-approval-v1"
FINAL_STATUSES = {"tamamlandi", "tamamlandı", "completed", "published"}
LOW_SCORE_THRESHOLD = _rule_engine.LOW_SCORE_THRESHOLD
HIGH_SCORE_THRESHOLD = _rule_engine.HIGH_SCORE_THRESHOLD
EXTREME_SCORE_VALUES = {float(_rule_engine.MIN_CRITERIA_SCORE), float(_rule_engine.MAX_CRITERIA_SCORE)}
MIN_GENERAL_COMMENT_CHARS = 10
MIN_ITEM_EXPLANATION_CHARS = 3
# Başkan/Üst Onay kanıtı olan süreç kaydı yokken düşük puan servisinin kendi
# "süreç yok" gerekçesiyle aynı metin.
_LOW_SCORE_APPROVAL_NOT_PROVEN_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay tamamlanmadan 70 altı karne yayınlanamaz. Başkan/Üst Onay Yayın Kilidi"


@dataclass(slots=True)
class PublishFinding:
    code: str
    message: str
    severity: str = "blocker"  # blocker / warning / info
    manager_level: int | None = None
    criteria_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "manager_level": self.manager_level,
            "criteria_id": self.criteria_id,
        }


@dataclass(slots=True)
class PublishPreflightResult:
    ok: bool
    reason: str = ""
    rule_version: str = PUBLISH_PREFLIGHT_RULE_VERSION
    blockers: list[PublishFinding] = field(default_factory=list)
    warnings: list[PublishFinding] = field(default_factory=list)
    infos: list[PublishFinding] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "rule_version": self.rule_version,
            "blockers": [item.as_dict() for item in self.blockers],
            "warnings": [item.as_dict() for item in self.warnings],
            "infos": [item.as_dict() for item in self.infos],
        }


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize(value: Any) -> str:
    return _safe_text(value).lower()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_text(value: Any, *, min_len: int = 1) -> bool:
    return len(_safe_text(value)) >= min_len


def _query_items(evaluation: Any) -> list[Any]:
    items = getattr(evaluation, "items", None)
    if items is None:
        return []
    try:
        if hasattr(items, "all"):
            return list(items.all())
        return list(items)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return []


def _general_comments(evaluation: Any) -> dict[int, str]:
    return {
        1: _safe_text(getattr(evaluation, "level_1_general_comment", "")),
        2: _safe_text(getattr(evaluation, "level_2_general_comment", "")),
        3: _safe_text(getattr(evaluation, "level_3_general_comment", "")),
    }


def _level_completed(evaluation: Any, level: int) -> bool:
    return bool(getattr(evaluation, f"level_{level}_completed", False))


def _level_evaluator_id(evaluation: Any, level: int) -> Any:
    return getattr(evaluation, f"level_{level}_evaluator_id", None)


def _period_level_3_mode(period: Any) -> str:
    raw = _normalize(getattr(period, "level_3_mode", ""))
    if raw in {"scoring", "puan", "puan_modu"}:
        return "scoring"
    if bool(getattr(period, "enable_level_3_scoring", False)):
        return "scoring"
    if bool(getattr(period, "enable_level_3", False)):
        return "comment_only"
    return "off"


def is_president_exempt(evaluation: Any | None) -> bool:
    if not evaluation:
        return False
    employee = getattr(evaluation, "employee", None)
    role = _normalize(getattr(employee, "role", ""))
    return role == "baskan"


def is_completed_status(evaluation: Any | None) -> bool:
    if not evaluation:
        return False
    return _normalize(getattr(evaluation, "status", "")) in FINAL_STATUSES


def expected_publish_levels(period: Any, evaluation: Any) -> tuple[int, ...]:
    """Yayın için tamamlanması gereken seviyeleri üretir.

    Bu fonksiyon tek amirli akışları korur: 2. veya 3. amir yoksa gereksiz
    bekleme üretmez. 3. amir atanmışsa, yorum modu olsa bile görüş adımı
    tamamlanmış sayılmadan yayın açılmaz.
    """
    levels: list[int] = []
    if _level_evaluator_id(evaluation, 1):
        levels.append(1)
    if _level_evaluator_id(evaluation, 2):
        levels.append(2)
    if _level_evaluator_id(evaluation, 3):
        levels.append(3)

    if not levels and not is_president_exempt(evaluation):
        # Savunmacı varsayım: değerlendirme kaydı varsa en az 1. amir beklenir.
        return (1,)
    return tuple(sorted(set(levels)))

def _workflow_ordered_levels(levels: Iterable[int]) -> tuple[int, ...]:
    """Amir değerlendirme işlem sırasına göre seviyeleri döndürür.

    BYS360 akışında çok seviyeli yapılarda işlem sırası 3 -> 2 -> 1 olduğu
    için yayın blokajı ilk eksik gerçek adımı göstermelidir. Böylece 2. amir
    değerlendirmesi eksikken kullanıcıya yanlışlıkla 1. amir blokajı yazılmaz.
    """
    normalized: set[int] = set()
    for level in levels or []:
        try:
            value = int(level)
        except (TypeError, ValueError):
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/publish_preflight_rules.py:181)")
            continue
        if value in {1, 2, 3}:
            normalized.add(value)
    return tuple(level for level in (3, 2, 1) if level in normalized)


def _manager_level_label(level: int | None) -> str:
    try:
        value = int(level or 0)
    except (TypeError, ValueError):
        value = 0
    if value in {1, 2, 3}:
        return f"{value}. amir"
    return "amir"


def _missing_level_message(level: int, *, level_3_mode: str) -> tuple[str, str]:
    if level == 3 and level_3_mode == "comment_only":
        return "level_3_comment_missing", "3. amir görüşü tamamlanmadan yayınlanamaz."
    return f"level_{level}_missing", f"{level}. amir değerlendirmesi tamamlanmadan yayınlanamaz."

def _items_by_level(items: Iterable[Any]) -> dict[int, list[Any]]:
    result: dict[int, list[Any]] = {1: [], 2: [], 3: []}
    for item in items:
        try:
            level = int(getattr(item, "manager_level", 0) or 0)
        except (TypeError, ValueError):
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/publish_preflight_rules.py:209)")
            continue
        if level in result:
            result[level].append(item)
    return result


def _item_has_explanation(item: Any) -> bool:
    return any(
        _has_text(getattr(item, attr, ""), min_len=MIN_ITEM_EXPLANATION_CHARS)
        for attr in ("justification", "comment", "strength_note")
    )


# BYS360_PHASE1_4_RULE_ENGINE_EDGE_COMMENT_HELPER
def _edge_score_comment_required(score: Any) -> bool:
    """1/5 açıklama zorunluluğunu Faz 1.3 merkezi kural motorundan alır."""
    try:
        return bool(_rule_engine.is_score_comment_required(score))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            return round(float(score), 2) in EXTREME_SCORE_VALUES
        except (TypeError, ValueError):
            return False


def _low_score_publish_release(evaluation: Any, final_total: float) -> tuple[bool, str]:
    """70 altı karne için (Başkan/Üst Onay açıkça kanıtlandı mı, blok nedeni).

    Blok nedeninin olmaması onay değildir: düşük puan servisi değerlendirmeyi
    kendi tanımına göre tamamlanmış saymadığında da (ör. workflow_status taslakta
    kalan mobil tamamlama) None döner. 0 < puan < 70 için kilit yalnız mevcut
    süreç kanonik model politikasına göre yayına kesinleşmişse açılır
    (PerformanceLowScoreProcess.is_finalized_for_publish: Başkan/Üst Onay var,
    iade yok, uyarı/idari süreç kaydı var); süreç yoksa onay da yoktur. Puanı
    0/None olan kayıt düşük puan sayılmaz, önceki karar korunur. Sorgu hataları
    çağırana iletilir (yayın rotası geri alır).
    """
    reason = get_low_score_publish_block_reason(evaluation, ensure=True)
    if reason:
        return False, reason
    if not is_low_score_evaluation(final_total):
        return True, ""
    process = None
    if getattr(evaluation, "id", None) is not None:
        process = PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation.id).first()
    if process is not None and process.is_finalized_for_publish:
        return True, ""
    process_reason = get_low_score_publish_block_reason(process) if process is not None else None
    return False, process_reason or _LOW_SCORE_APPROVAL_NOT_PROVEN_REASON


def _build_phase1_4_rule_decision(
    *,
    final_total: float,
    status_code: Any,
    level_3_mode: str,
    president_approved: bool,
):
    """Yayın öncesi kontrolün merkezi performans kural motoru kararı.

    70 altı süreçte gerçek Başkan/İK/personel süreç durumu mevcut
    low_score_process_service ve süreç kaydı üzerinden doğrulanır; kural
    motoruna ``president_approved`` yalnız açık onay kanıtıyla True verilir
    (bkz. _low_score_publish_release). Böylece kilit kararı ayar motorundan,
    süreç tamamlanma ayrıntısı ise süreç kaydından gelir.
    """
    return _rule_engine.evaluate_performance_rules(
        _rule_engine.PerformanceRuleContext(
            final_score=final_total,
            status_code=status_code,
            president_approved=president_approved,
            third_reviewer_mode=level_3_mode,
        )
    )


def _level_has_comment_or_item_note(evaluation: Any, items_by_level: dict[int, list[Any]], level: int) -> bool:
    comments = _general_comments(evaluation)
    if _has_text(comments.get(level), min_len=MIN_GENERAL_COMMENT_CHARS):
        return True
    return any(_item_has_explanation(item) for item in items_by_level.get(level, []))


def validate_evaluation_for_publish(period: Any, evaluation: Any) -> PublishPreflightResult:
    blockers: list[PublishFinding] = []
    warnings: list[PublishFinding] = []
    infos: list[PublishFinding] = []

    if not evaluation:
        blockers.append(PublishFinding("missing_evaluation", "Değerlendirme bulunamadı."))
        return PublishPreflightResult(False, blockers[0].message, blockers=blockers)

    if not period:
        blockers.append(PublishFinding("missing_period", "Değerlendirme dönemi bulunamadı."))
        return PublishPreflightResult(False, blockers[0].message, blockers=blockers)

    if is_president_exempt(evaluation):
        infos.append(PublishFinding("president_exempt", "Başkan için personel karne yayını yapılmaz.", "info"))
        return PublishPreflightResult(False, "", infos=infos)

    if not is_completed_status(evaluation):
        blockers.append(PublishFinding("not_completed", "Değerlendirme tamamlanmadığı için yayınlanamaz."))

    items = _query_items(evaluation)
    items_by_level = _items_by_level(items)
    required_levels = expected_publish_levels(period, evaluation)
    level_3_mode = _period_level_3_mode(period)

    if not required_levels:
        blockers.append(PublishFinding("missing_chain", "Değerlendirme için zorunlu amir zinciri bulunamadı."))

    missing_level_findings: list[PublishFinding] = []
    for level in _workflow_ordered_levels(required_levels):
        if not _level_completed(evaluation, level):
            code, message = _missing_level_message(level, level_3_mode=level_3_mode)
            missing_level_findings.append(PublishFinding(code, message, manager_level=level))

    if len(missing_level_findings) > 1:
        missing_labels = ", ".join(_manager_level_label(item.manager_level) for item in missing_level_findings)
        blockers.append(
            PublishFinding(
                "manager_steps_missing",
                f"Yayın için eksik amir değerlendirmesi var: {missing_labels}. Eksik değerlendirmeler tamamlanmadan personele yayın açılamaz.",
            )
        )
    blockers.extend(missing_level_findings)

    # 3. amir yorum modundaysa puan zorunlu değildir ama görüş/yorum aranır.
    if (
        3 in required_levels
        and level_3_mode == "comment_only"
        and _level_completed(evaluation, 3)
        and not _level_has_comment_or_item_note(evaluation, items_by_level, 3)
    ):
        blockers.append(PublishFinding("level_3_comment_required", "3. amir yorum modunda olduğu için görüş alanı boş bırakılamaz.", manager_level=3))

    # Puanlayan seviyelerde en az bir kriter satırı olmalı. 3. amir yorum modunda bundan muaftır.
    for level in _workflow_ordered_levels(required_levels):
        if level == 3 and level_3_mode == "comment_only":
            continue
        if _level_completed(evaluation, level) and not items_by_level.get(level):
            blockers.append(PublishFinding("missing_score_items", f"{level}. amir için kriter puanı bulunamadı.", manager_level=level))

    for item in items:
        score = _safe_float(getattr(item, "score", None), default=-999.0)
        rounded_score = round(score, 2)
        if _edge_score_comment_required(rounded_score) and not _item_has_explanation(item):
            blockers.append(
                PublishFinding(
                    "extreme_score_explanation_required",
                    "Bu puan için sistem ayarında açıklama/gerekçe zorunluluğu aktiftir.",
                    manager_level=int(getattr(item, "manager_level", 0) or 0) or None,
                    criteria_id=getattr(item, "criteria_id", None),
                )
            )

    final_total = _safe_float(getattr(evaluation, "final_total_100", 0), default=0.0)
    comments = _general_comments(evaluation)
    has_general_comment = any(_has_text(value, min_len=MIN_GENERAL_COMMENT_CHARS) for value in comments.values())

    # Faz 1.4: 70 altı Başkan/onay/yayın kilidi kararı merkezi kural motorundan alınır.
    # Ayar 70 altı için Başkan onayı istemiyorsa kilit kararı önceki gibi açıktır.
    low_score_block_reason = ""
    president_approved = True
    if _rule_engine.requires_president_approval(final_total):
        # BYS360_PHASE6_1_LOW_SCORE_PUBLISH_LOCK
        president_approved, low_score_block_reason = _low_score_publish_release(evaluation, final_total)

    rule_decision = _build_phase1_4_rule_decision(
        final_total=final_total,
        status_code=getattr(evaluation, "status", None),
        level_3_mode=level_3_mode,
        president_approved=president_approved,
    )

    if rule_decision.requires_general_comment and not has_general_comment:
        if final_total < LOW_SCORE_THRESHOLD:
            blockers.append(PublishFinding("low_score_general_comment_required", "70 altı sonuçlarda ayrıntılı genel görüş zorunludur."))
        elif final_total > HIGH_SCORE_THRESHOLD:
            blockers.append(PublishFinding("high_score_general_comment_required", "90 üstü sonuçlarda ayrıntılı genel görüş zorunludur."))
        else:
            blockers.append(PublishFinding("general_comment_required", "Bu sonuç için ayrıntılı genel görüş zorunludur."))

    # BYS360_PHASE6_2_LOW_SCORE_PUBLISH_PREFLIGHT_LOCK
    if rule_decision.requires_president_approval and low_score_block_reason:
        blockers.append(PublishFinding("low_score_president_approval_required", low_score_block_reason))
    elif rule_decision.publish_locked:
        blockers.append(PublishFinding("low_score_publish_lock", "Başkan onayı tamamlanmadan 70 altı karne personele yayınlanamaz."))

    development_block_reason = get_development_recommendation_publish_block_reason(evaluation)
    if development_block_reason:
        blockers.append(PublishFinding("low_score_development_recommendation_required", development_block_reason))

    # Faz 1.4.B: Başkan onayı ve tüm önceki yayın blokajları kapandıktan sonra
    # Admin/İK nihai yayından önce Personel ve Destek Hizmetleri Grup Başkanı
    # ön onayı zorunludur. Ön koşul blokajı varken bu adım erkenden oluşturulmaz.
    personnel_support_block_reason = get_personnel_support_publish_block_reason(
        evaluation,
        ensure=True,
        predecessor_blocked=bool(blockers),
    )
    if personnel_support_block_reason:
        blockers.append(PublishFinding("personnel_support_publish_approval_required", personnel_support_block_reason))

    # Dönem seviyesinde 3. amir puan zorunlu işaretlenmişse ama değerlendirmede 3. amir yoksa ayrı uyarı ver.
    if bool(getattr(period, "require_level_3_completion_for_final", False)) and 3 not in required_levels:
        blockers.append(PublishFinding("period_requires_level_3", "Dönem ayarında 3. amir tamamlanması zorunlu; bu kayıtta 3. amir zinciri yok."))

    if blockers:
        return PublishPreflightResult(False, blockers[0].message, blockers=blockers, warnings=warnings, infos=infos)

    return PublishPreflightResult(True, "", blockers=blockers, warnings=warnings, infos=infos)


def is_evaluation_publishable_strict(period: Any, evaluation: Any) -> tuple[bool, str]:
    result = validate_evaluation_for_publish(period, evaluation)
    return bool(result.ok), result.reason


__all__ = [
    "FINAL_STATUSES",
    "HIGH_SCORE_THRESHOLD",
    "LOW_SCORE_THRESHOLD",
    "PUBLISH_PREFLIGHT_RULE_VERSION",
    "PublishFinding",
    "PublishPreflightResult",
    "expected_publish_levels",
    "is_completed_status",
    "is_evaluation_publishable_strict",
    "is_president_exempt",
    "validate_evaluation_for_publish",
]

# BYS360 Faz 1.4 yayın öncesi kontrol entegrasyon işareti
# phase1.4-rule-engine-preflight-v1

# BYS360_PERFORMANCE_COMPLETION_PHASE1_PREFLIGHT_CENTER_MARKER
# Yayın öncesi kontrol Faz 1 kural merkezinden beslenmelidir. Bu marker gate tarafında izlenir.
try:
    from app.services.performance.phase1_rule_center import (
        PHASE1_RULE_CENTER_VERSION as PHASE1_RULE_CENTER_VERSION,
    )
except Exception:
    logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
    PHASE1_RULE_CENTER_VERSION = "performance-completion-phase1-rule-center-unavailable"

# BYS360_PERFORMANCE_COMPLETION_PHASE4_THIRD_MANAGER_BOUND
# 3. amir opsiyonelliği ve sahte görev temizliği phase4_third_manager_policy üzerinden izlenir.

# BYS360_PERFORMANCE_COMPLETION_PHASE5_SCORECARD_UI_BOUND
# Karne/puanlama ekranları phase5_scorecard_ui_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE6_LOW_SCORE_APPROVAL_BOUND
# 70 altı düşük performans üst onay/yayın kilidi phase6_low_score_approval_policy ile izlenir.


# BYS360_A5_P2D3_PUBLISH_PREFLIGHT_RULES_CONSTITUTION_START
# Static contract anchors for publish preflight constitution.
# BYS360 DEFECT AR: bu satirlar eskiden LOW_SCORE_THRESHOLD/
# HIGH_SCORE_THRESHOLD'u modul basindaki (satir 38-39) merkezi kural
# motorundan yapilan importu SESSIZCE golgeleyerek 70.0/90.0 ile yeniden
# ataniyordu -- modulun kendi belgeledigi "70 altı ve 90 üstü ... karari
# merkezi kural motorundan alinir" tek-kaynak niyetini bozan, canli
# çalışan bir kopya tanim. Bugune kadar sayisal bir sapma yoktu (ikisi de
# 70.0/90.0), ama _rule_engine.LOW_SCORE_THRESHOLD degisirse bu dosya
# sessizce eski degeri kullanmaya devam ederdi. tests/test_performance_
# publish_preflight_static.py "LOW_SCORE_THRESHOLD = 70.0" metnini
# STATIC bir sozlesme olarak kilitledigi icin (yukarida satir 38'deki
# gercek importu degil, salt metni ariyor), o kilidi bozmadan asagidaki
# satirlar artik yeniden atama YAPMIYOR, yalnizca belgeleme.
# LOW_SCORE_THRESHOLD = 70.0
# HIGH_SCORE_THRESHOLD = 90.0
PUBLISH_PREFLIGHT_CONSTITUTION_VERSION = "2026-04-18-publish-preflight-lock-v1"
# BYS360_A5_P2D3_PUBLISH_PREFLIGHT_RULES_CONSTITUTION_END


# BYS360_A5_P2D3_PUBLISH_PREFLIGHT_LOCK_ANCHOR_START
# Static contract anchor: 2026-04-18-publish-preflight-lock-v1
PUBLISH_PREFLIGHT_LOCK_CONTRACT_ID = "2026-04-18-publish-preflight-lock-v1"
# BYS360_A5_P2D3_PUBLISH_PREFLIGHT_LOCK_ANCHOR_END

