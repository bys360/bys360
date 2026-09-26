from __future__ import annotations

from typing import Any, cast

from app.extensions import db
from app.models import (
    PerformanceCriteria,
    PerformanceEvaluation,
    PerformanceEvaluationItem,
    PerformancePeriod,
    User,
)
from app.services.performance_v2.policy_flags import score_requires_criterion_comment

from .assignments import _dedupe_item_rows, ensure_evaluation_record
from .common import (
    _safe_float,
    _safe_str,
    calculate_effective_weights,
    get_base_weight_map,
    get_period_level_3_flags,
    is_single_manager_case,
)
from .criteria import level_1_gave_any_three, score_to_100
from .policy_flags import is_level_2_comment_required_when_level_1_score_is_three


def calculate_preview_total_100(item_payloads: list[dict[str, Any]] | None, criteria_weight_map: dict[int, float]) -> float:
    total = 0.0
    for payload in item_payloads or []:
        try:
            criteria_id = int(payload.get("criteria_id"))  # type: ignore[arg-type]  # None/bad values raise below by design
        except (TypeError, ValueError):
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/scoring.py:19)")
            continue
        score_100 = score_to_100(_safe_float(payload.get("score"), 0.0))
        weight = _safe_float(criteria_weight_map.get(criteria_id), 0.0)
        total += score_100 * (weight / 100.0)
    return round(total, 2)


def requires_general_comment(level_total_100: float, raw_scores: list[float] | None = None) -> bool:
    raw_scores = raw_scores or []
    if level_total_100 < 70 or level_total_100 > 90:
        return True
    return any(score_requires_criterion_comment(_safe_float(score, 0.0)) for score in raw_scores)


def validate_score_value(score: Any) -> float:
    value = _safe_float(score, 0.0)
    if value < 1.0 or value > 5.0:
        raise ValueError("Puan 1 ile 5 arasında olmalıdır.")
    return value


def validate_general_comment_requirements(
    *,
    manager_level: int,
    general_comment: str,
    level_total_100: float,
    raw_scores: list[float] | None = None,
    requires_level_2_comment: bool = False,
) -> None:
    comment = _safe_str(general_comment)
    if (
        manager_level == 2
        and requires_level_2_comment
        and is_level_2_comment_required_when_level_1_score_is_three()
        and not comment
    ):
        raise ValueError("1. amirin 3 verdiği durumda 2. amir genel değerlendirme yazmalıdır.")
    if requires_general_comment(level_total_100, raw_scores) and not comment:
        raise ValueError("70 altı / 90 üstü sonuçlarda genel değerlendirme zorunludur. 1 ve 5 puan açıklaması sistem ayarından yönetilir.")


def validate_item_comment_requirements(item_payloads: list[dict[str, Any]] | None) -> None:
    for payload in item_payloads or []:
        score = validate_score_value(payload.get("score"))
        comment = _safe_str(payload.get("comment"))
        if score_requires_criterion_comment(score) and not comment:
            raise ValueError("Bu puan için sistem ayarında açıklama zorunluluğu aktiftir.")


def requires_level_2_comment_for_evaluation(evaluation_or_id: int | PerformanceEvaluation) -> bool:
    # Nihai kurum kuralı: 3 puan tek başına yorum zorunluluğu oluşturmaz.
    # Parametre geriye uyumluluk için korunur.
    _ = evaluation_or_id
    if not is_level_2_comment_required_when_level_1_score_is_three():
        return False
    return level_1_gave_any_three(evaluation_or_id)


def validate_weight_distribution(weights: dict[str, float], scoring_level_3: bool = False) -> bool:
    expected = (
        _safe_float(weights.get("evaluator_1_weight"), 0.0)
        + _safe_float(weights.get("evaluator_2_weight"), 0.0)
        + (_safe_float(weights.get("evaluator_3_weight"), 0.0) if scoring_level_3 else 0.0)
    )
    return round(expected, 2) == 100.0


def calculate_level_total_100(evaluation_id: int, manager_level: int) -> float:
    items = (
        PerformanceEvaluationItem.query.join(PerformanceCriteria, PerformanceCriteria.id == PerformanceEvaluationItem.criteria_id)
        .filter(
            PerformanceEvaluationItem.evaluation_id == evaluation_id,
            PerformanceEvaluationItem.manager_level == manager_level,
        )
        .all()
    )
    if not items:
        return 0.0

    total = 0.0
    for item in items:
        weight = _safe_float(getattr(item.criteria, "weight", 0), 0.0)
        raw_score = _safe_float(getattr(item, "score", None), 0.0)
        item.score_100 = score_to_100(raw_score)
        total += item.score_100 * (weight / 100.0)
    return round(total, 2)


def calculate_final_total(
    evaluation_or_period: PerformanceEvaluation | PerformancePeriod | Any,
    level_1_total: float | None = None,
    level_2_total: float | None = None,
    level_3_total: float = 0.0,
) -> float:
    if hasattr(evaluation_or_period, "employee_id") and hasattr(evaluation_or_period, "period_id"):
        evaluation = evaluation_or_period
        period = evaluation.period
        employee = evaluation.employee
        weights = calculate_effective_weights(
            period,
            employee,
            getattr(evaluation, "level_1_evaluator_id", None),
            getattr(evaluation, "level_2_evaluator_id", None),
            getattr(evaluation, "level_3_evaluator_id", None),
        )
        l1 = _safe_float(getattr(evaluation, "level_1_total_100", 0), 0)
        l2 = _safe_float(getattr(evaluation, "level_2_total_100", 0), 0)
        l3 = _safe_float(getattr(evaluation, "level_3_total_100", 0), 0)
    else:
        period = evaluation_or_period
        weights = get_base_weight_map(getattr(period, "id", None) if period else None)
        l1 = _safe_float(level_1_total, 0)
        l2 = _safe_float(level_2_total, 0)
        l3 = _safe_float(level_3_total, 0)

    # Eşit puanlı iki amirde 50/50 mantığı sonucu aynen korur.
    final_total = (
        l1 * (weights["evaluator_1_weight"] / 100.0)
        + l2 * (weights["evaluator_2_weight"] / 100.0)
        + l3 * (weights["evaluator_3_weight"] / 100.0)
    )
    return round(final_total, 2)


def _required_completion_levels(evaluation: PerformanceEvaluation) -> list[int]:
    levels: list[int] = []
    employee = cast("User | None", evaluation.employee)
    period = evaluation.period
    flags = get_period_level_3_flags(period)

    if getattr(evaluation, "level_3_evaluator_id", None) and flags["enabled"]:
        levels.append(3)
    if getattr(evaluation, "level_1_evaluator_id", None):
        levels.append(1)
    if getattr(evaluation, "level_2_evaluator_id", None) and not is_single_manager_case(employee):
        levels.append(2)
    return levels


def recalculate_evaluation_totals(evaluation: PerformanceEvaluation) -> PerformanceEvaluation:
    period = evaluation.period
    flags = get_period_level_3_flags(period)

    evaluation.level_1_total_100 = calculate_level_total_100(evaluation.id, 1)
    evaluation.level_2_total_100 = calculate_level_total_100(evaluation.id, 2)

    if flags["enabled"] and flags["scoring_enabled"] and getattr(evaluation, "level_3_evaluator_id", None):
        evaluation.level_3_total_100 = calculate_level_total_100(evaluation.id, 3)
    else:
        evaluation.level_3_total_100 = 0.0

    evaluation.final_total_100 = calculate_final_total(evaluation)

    required = _required_completion_levels(evaluation)
    completed_count = sum(1 for level in required if bool(getattr(evaluation, f"level_{level}_completed", False)))

    if completed_count == 0:
        evaluation.status = "bekliyor"
    elif completed_count < len(required):
        evaluation.status = "kismen_tamamlandi"
    else:
        evaluation.status = "tamamlandi"

    db.session.add(evaluation)
    return evaluation


def recalculate_all_evaluations(period_id: int | None = None, *, actor_user_id: int | None = None) -> int:
    from app.services.performance.low_score_process_service import (
        ensure_low_score_process_for_evaluation,
    )

    query = PerformanceEvaluation.query
    if period_id is not None:
        query = query.filter_by(period_id=period_id)
    rows = query.all()
    for row in rows:
        before = (row.final_total_100, row.status)
        recalculate_evaluation_totals(row)
        # Puanı/durumu bu hesaplamayla değişen ve nihai tamamlanmış değerlendirme için
        # 70 altı süreç zinciri aynı transaction'da kurulur (v2 web tamamlamasıyla aynı).
        if (row.final_total_100, row.status) != before and (row.status or "").strip().lower() in {"tamamlandi", "tamamlandı", "completed", "published"}:
            ensure_low_score_process_for_evaluation(row, actor_user_id=actor_user_id, flush=False)
    db.session.commit()
    return len(rows)


def create_or_update_item(
    evaluation_id: int,
    criteria_id: int,
    manager_level: int,
    score: float,
    comment: str = "",
    strength_note: str = "",
    justification: str = "",
) -> PerformanceEvaluationItem:
    _dedupe_item_rows(evaluation_id, criteria_id, manager_level)
    item = PerformanceEvaluationItem.query.filter_by(
        evaluation_id=evaluation_id,
        criteria_id=criteria_id,
        manager_level=manager_level,
    ).first()
    if not item:
        item = PerformanceEvaluationItem(
            evaluation_id=evaluation_id,
            criteria_id=criteria_id,
            manager_level=manager_level,
        )

    item.score = validate_score_value(score)
    item.score_100 = score_to_100(item.score)
    item.comment = comment or None
    item.strength_note = strength_note or None
    item.justification = justification or None
    db.session.add(item)
    db.session.flush()
    return item


def _delete_missing_level_items(evaluation_id: int, manager_level: int, keep_criteria_ids: list[int]) -> int:
    keep_ids = {int(criteria_id) for criteria_id in keep_criteria_ids if criteria_id is not None}
    rows = PerformanceEvaluationItem.query.filter_by(
        evaluation_id=evaluation_id,
        manager_level=manager_level,
    ).all()
    removed = 0
    for row in rows:
        if int(getattr(row, "criteria_id", 0) or 0) not in keep_ids:
            db.session.delete(row)
            removed += 1
    if removed:
        db.session.flush()
    return removed


def save_evaluation_level(
    *,
    period_id: int | None = None,
    employee_id: int | None = None,
    evaluation_id: int | None = None,
    manager_level: int,
    evaluator_id: int | None = None,
    item_payloads: list[dict[str, Any]] | None = None,
    general_comment: str = "",
    completed: bool = False,
    **_: Any,
) -> PerformanceEvaluation:
    """Persist one manager level of a performance evaluation.

    Bu fonksiyon eski `save_evaluation_level` çağrılarını doğrudan karşılar.
    Yeni mimaride route katmanı workflow geçişlerini ayrıca yönettiği için burada
    sadece kayıt, yorum, kriter satırları ve toplamlar güncellenir.
    """
    if manager_level not in {1, 2, 3}:
        raise ValueError("Geçersiz amir seviyesi.")

    evaluation: PerformanceEvaluation | None = None
    if evaluation_id:
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)

    if evaluation is None:
        if not period_id or not employee_id:
            raise ValueError("Değerlendirme kaydı için period_id ve employee_id gereklidir.")
        evaluation = ensure_evaluation_record(period_id=period_id, employee_id=employee_id)

    evaluator_field = f"level_{manager_level}_evaluator_id"
    if evaluator_id:
        setattr(evaluation, evaluator_field, evaluator_id)

    comment_field = f"level_{manager_level}_general_comment"
    setattr(evaluation, comment_field, _safe_str(general_comment) or None)

    completed_field = f"level_{manager_level}_completed"
    setattr(evaluation, completed_field, bool(completed))

    clean_payloads: list[dict[str, Any]] = []
    seen_criteria_ids = set()
    for payload in item_payloads or []:
        try:
            criteria_id = int(payload.get("criteria_id"))  # type: ignore[arg-type]  # None/bad values raise below by design
        except (TypeError, ValueError):
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/scoring.py:292)")
            continue
        if criteria_id in seen_criteria_ids:
            continue
        seen_criteria_ids.add(criteria_id)
        clean_payloads.append(payload)

    db.session.add(evaluation)
    db.session.flush()

    _delete_missing_level_items(evaluation.id, manager_level, list(seen_criteria_ids))

    for payload in clean_payloads:
        create_or_update_item(
            evaluation_id=evaluation.id,
            criteria_id=int(payload.get("criteria_id")),  # type: ignore[arg-type]  # already validated in clean_payloads above
            manager_level=manager_level,
            score=validate_score_value(payload.get("score")),
            comment=_safe_str(payload.get("comment")),
            strength_note=_safe_str(payload.get("strength_note")),
            justification=_safe_str(payload.get("justification")),
        )

    recalculate_evaluation_totals(evaluation)
    db.session.flush()
    return evaluation

