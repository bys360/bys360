from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.extensions import db
from app.models import (
    AttendanceException,
    DelegationAssignment,
    EvaluationAssignment,
    PerformanceEvaluation,
    PerformancePeriod,
    PersonnelLeave,
    User,
)
from app.services.performance.period_freeze import period_is_frozen

APPROVED_STATUSES = {"onaylandi", "aktif", "tamamlandi", "kayit"}
PERFORMANCE_MODE_DEFAULT = "partial"
PERFORMANCE_MODE_ALLOWED = {"exclude", "partial", "informational"}


@dataclass
class PeriodAvailabilityImpact:
    employee_id: int
    work_days: float
    leave_days: float = 0.0
    absence_days: float = 0.0
    blocked_days: float = 0.0
    available_days: float = 0.0
    exempted: bool = False
    reason: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class DelegationResolution:
    original_manager_id: int | None
    acting_manager_id: int | None
    delegation_id: int | None = None
    source: str = "direct"
    note: str = ""


@dataclass
class AssignmentCoverageRefreshResult:
    updated_count: int = 0
    notes: list[str] = field(default_factory=list)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_status(value: str | None) -> str:
    return (value or "").strip().lower()


def _is_approved(value: str | None) -> bool:
    return _normalize_status(value) in APPROVED_STATUSES


def _normalize_performance_mode(row: Any, *, default_blocking: bool = True) -> str:
    explicit = _normalize_status(getattr(row, "performance_mode", None))
    if explicit in PERFORMANCE_MODE_ALLOWED:
        return explicit
    blocks = bool(getattr(row, "blocks_performance_evaluation", default_blocking))
    return PERFORMANCE_MODE_DEFAULT if blocks else "informational"


def get_assignment_reference_date(period: PerformancePeriod | None, on_date: date | None = None) -> date:
    candidate = on_date or date.today()
    if not period:
        return candidate
    if candidate < period.start_date:
        return period.start_date
    if candidate > period.end_date:
        return period.end_date
    return candidate


def _date_range(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _business_days_in_range(start_date: date, end_date: date) -> list[date]:
    return [day for day in _date_range(start_date, end_date) if day.weekday() < 5]


def _overlap_range(start_a: date, end_a: date, start_b: date, end_b: date) -> tuple[date, date] | None:
    start = max(start_a, start_b)
    end = min(end_a, end_b)
    if start > end:
        return None
    return start, end


def _leave_overlap_map(leave: PersonnelLeave, range_start: date, range_end: date) -> dict[date, float]:
    overlap = _overlap_range(leave.start_date, leave.end_date, range_start, range_end)
    if not overlap:
        return {}

    start, end = overlap
    business_days = _business_days_in_range(start, end)
    if not business_days:
        return {}

    fractions = {day: 1.0 for day in business_days}

    if start == end:
        if bool(getattr(leave, "start_half_day", False)) or bool(getattr(leave, "end_half_day", False)):
            fractions[start] = 0.5
    else:
        if bool(getattr(leave, "start_half_day", False)) and start in fractions:
            fractions[start] = 0.5
        if bool(getattr(leave, "end_half_day", False)) and end in fractions:
            fractions[end] = min(fractions.get(end, 1.0), 0.5)

    approved_day_count = getattr(leave, "approved_day_count", None)
    if approved_day_count not in (None, ""):
        approx_total = sum(fractions.values())
        approved = max(0.0, _safe_float(approved_day_count, approx_total))
        if approx_total > 0 and approved < approx_total:
            scale = approved / approx_total
            fractions = {day: round(value * scale, 2) for day, value in fractions.items()}

    return fractions


def _attendance_overlap_map(exception: AttendanceException, range_start: date, range_end: date) -> dict[date, float]:
    if exception.record_date < range_start or exception.record_date > range_end:
        return {}
    if exception.record_date.weekday() >= 5:
        return {}
    return {
        exception.record_date: max(0.0, min(1.0, _safe_float(exception.day_fraction, 1.0)))
    }


def get_period_employee_availability(employee: User, period: PerformancePeriod) -> PeriodAvailabilityImpact:
    work_days_list = _business_days_in_range(period.start_date, period.end_date)
    work_days = float(len(work_days_list))
    impact = PeriodAvailabilityImpact(
        employee_id=employee.id,
        work_days=work_days,
        available_days=work_days,
    )

    if not work_days_list:
        impact.exempted = True
        impact.reason = "Dönemde iş günü yok"
        impact.notes.append("Seçilen dönem hafta içi iş günü üretmediği için değerlendirme oluşturulmadı.")
        return impact

    blocked_map: dict[date, float] = {}
    leave_total = 0.0
    absence_total = 0.0
    forced_exclusion_reasons: list[str] = []

    leave_rows = (
        PersonnelLeave.query
        .filter(
            PersonnelLeave.user_id == employee.id,
            PersonnelLeave.start_date <= period.end_date,
            PersonnelLeave.end_date >= period.start_date,
        )
        .all()
    )
    for leave in leave_rows:
        if not _is_approved(getattr(leave, "status", None)):
            continue
        overlap = _leave_overlap_map(leave, period.start_date, period.end_date)
        if not overlap:
            continue
        overlap_days = round(sum(overlap.values()), 2)
        leave_total += overlap_days
        mode = _normalize_performance_mode(leave)

        if mode == "informational":
            impact.notes.append(f"İzin kaydı bilgi amaçlı işlendi: {overlap_days:g} gün")
            continue

        if bool(getattr(leave, "blocks_performance_evaluation", True)):
            for day, fraction in overlap.items():
                blocked_map[day] = max(blocked_map.get(day, 0.0), fraction)

        if mode == "exclude":
            forced_exclusion_reasons.append(f"İzin kaydı muafiyet modunda işlendi ({overlap_days:g} gün)")

    exception_rows = (
        AttendanceException.query
        .filter(
            AttendanceException.user_id == employee.id,
            AttendanceException.record_date >= period.start_date,
            AttendanceException.record_date <= period.end_date,
        )
        .all()
    )
    for row in exception_rows:
        if not _is_approved(getattr(row, "status", None)):
            continue
        overlap = _attendance_overlap_map(row, period.start_date, period.end_date)
        if not overlap:
            continue
        overlap_days = round(sum(overlap.values()), 2)
        absence_total += overlap_days
        mode = _normalize_performance_mode(row)

        if mode == "informational":
            impact.notes.append(f"Devamsızlık kaydı bilgi amaçlı işlendi: {overlap_days:g} gün")
            continue

        if bool(getattr(row, "blocks_performance_evaluation", True)):
            for day, fraction in overlap.items():
                blocked_map[day] = max(blocked_map.get(day, 0.0), fraction)

        if mode == "exclude":
            forced_exclusion_reasons.append(f"Devamsızlık kaydı muafiyet modunda işlendi ({overlap_days:g} gün)")

    blocked_days = round(sum(blocked_map.values()), 2)
    available_days = round(max(0.0, work_days - blocked_days), 2)

    impact.leave_days = round(leave_total, 2)
    impact.absence_days = round(absence_total, 2)
    impact.blocked_days = blocked_days
    impact.available_days = available_days

    min_presence = _safe_float(getattr(period, "minimum_presence_days_for_evaluation", 0.0), 0.0)
    leave_skip = getattr(period, "leave_skip_threshold_days", None)
    absence_skip = getattr(period, "absence_skip_threshold_days", None)
    auto_skip_full = bool(getattr(period, "auto_skip_if_fully_absent", True))

    reasons: list[str] = []
    exempted = False

    if forced_exclusion_reasons:
        exempted = True
        reasons.extend(forced_exclusion_reasons)

    if auto_skip_full and blocked_days >= work_days and work_days > 0:
        exempted = True
        reasons.append("Dönemin tamamında izin/devamsızlık kaydı var")

    if leave_skip not in (None, "") and impact.leave_days >= _safe_float(leave_skip, 0.0) > 0:
        exempted = True
        reasons.append(f"İzin günü eşiği aşıldı ({impact.leave_days:g})")

    if absence_skip not in (None, "") and impact.absence_days >= _safe_float(absence_skip, 0.0) > 0:
        exempted = True
        reasons.append(f"Devamsızlık günü eşiği aşıldı ({impact.absence_days:g})")

    if min_presence > 0 and available_days < min_presence:
        exempted = True
        reasons.append(f"Asgari fiili çalışma günü sağlanmadı ({available_days:g}/{min_presence:g})")

    if impact.leave_days > 0:
        impact.notes.append(f"Dönem içinde onaylı izin: {impact.leave_days:g} gün")
    if impact.absence_days > 0:
        impact.notes.append(f"Dönem içinde devamsızlık/istisna: {impact.absence_days:g} gün")
    if not exempted and blocked_days > 0:
        impact.notes.append(f"Değerlendirme devam eder; kullanılabilir fiili gün: {available_days:g}")

    impact.exempted = exempted
    impact.reason = "; ".join(dict.fromkeys(reasons))
    return impact


def is_user_currently_unavailable(user_id: int | None, on_date: date | None = None) -> tuple[bool, str]:
    if not user_id:
        return False, ""

    on_date = on_date or date.today()

    leave_rows = PersonnelLeave.query.filter(
        PersonnelLeave.user_id == user_id,
        PersonnelLeave.start_date <= on_date,
        PersonnelLeave.end_date >= on_date,
    ).all()
    for leave in leave_rows:
        if _is_approved(getattr(leave, "status", None)) and bool(getattr(leave, "blocks_manager_duties", True)):
            return True, f"Onaylı izin: {getattr(leave, 'leave_type', 'izin')}"

    exception_rows = AttendanceException.query.filter(
        AttendanceException.user_id == user_id,
        AttendanceException.record_date == on_date,
    ).all()
    for row in exception_rows:
        if _is_approved(getattr(row, "status", None)) and bool(getattr(row, "blocks_manager_duties", True)):
            return True, f"Devamsızlık/istisna: {getattr(row, 'exception_type', 'kayıt')}"

    return False, ""


def resolve_effective_manager(manager_id: int | None, manager_level: int, on_date: date | None = None) -> DelegationResolution:
    if not manager_id:
        return DelegationResolution(original_manager_id=None, acting_manager_id=None, source="missing")

    on_date = on_date or date.today()
    unavailable, reason = is_user_currently_unavailable(manager_id, on_date)
    if not unavailable:
        return DelegationResolution(
            original_manager_id=manager_id,
            acting_manager_id=manager_id,
            source="direct",
        )

    delegations = (
        DelegationAssignment.query
        .filter(
            DelegationAssignment.delegator_user_id == manager_id,
            DelegationAssignment.start_date <= on_date,
            DelegationAssignment.end_date >= on_date,
        )
        .order_by(DelegationAssignment.id.desc())
        .all()
    )

    for delegation in delegations:
        if not _is_approved(getattr(delegation, "status", None)):
            continue
        if getattr(delegation, "scope_type", "performance") not in {"performance", "full"}:
            continue
        if manager_level == 1 and not bool(getattr(delegation, "applies_level_1", True)):
            continue
        if manager_level == 2 and not bool(getattr(delegation, "applies_level_2", True)):
            continue
        if manager_level == 3 and not bool(getattr(delegation, "applies_level_3", True)):
            continue
        return DelegationResolution(
            original_manager_id=manager_id,
            acting_manager_id=getattr(delegation, "delegate_user_id", None),
            delegation_id=delegation.id,
            source="delegated",
            note=reason or "Aktif vekâlet devrede",
        )

    return DelegationResolution(
        original_manager_id=manager_id,
        acting_manager_id=None,
        source="uncovered",
        note=reason or "Asıl amir müsait değil ve aktif vekâlet bulunamadı.",
    )


def apply_availability_snapshot_to_evaluation(evaluation: PerformanceEvaluation, impact: PeriodAvailabilityImpact) -> None:
    evaluation.employee_leave_days_in_period = impact.leave_days
    evaluation.employee_absence_days_in_period = impact.absence_days
    evaluation.employee_available_days_in_period = impact.available_days
    evaluation.evaluation_exempted = bool(impact.exempted)
    evaluation.evaluation_exemption_reason = impact.reason or None
    if impact.exempted:
        evaluation.status = "muaf"
        evaluation.workflow_status = "muaf"
        evaluation.level_1_completed = False
        evaluation.level_2_completed = False
        evaluation.level_3_completed = False
        evaluation.level_1_total_100 = 0.0
        evaluation.level_2_total_100 = 0.0
        evaluation.level_3_total_100 = 0.0
        evaluation.final_total_100 = 0.0
    elif getattr(evaluation, "status", None) == "muaf":
        evaluation.status = "bekliyor"
        evaluation.workflow_status = "taslak_1_amir"

    db.session.add(evaluation)


def refresh_assignment_live_coverages(period_id: int | None = None, on_date: date | None = None) -> AssignmentCoverageRefreshResult:
    """Açık görevlerin etkin amir/vekil kapsamasını güncel tarihe göre yeniler.

    Her görev için orijinal değerlendirici, aktif vekâlet ve kullanılabilirlik
    durumu yeniden çözülür. Sonuçta evaluator_id, delegation_id, coverage_note ve
    assignment_source alanları canlı zincire uyarlanır; yapılan değişikliklerin
    özeti AssignmentCoverageRefreshResult içinde döner.
    """
    on_date = on_date or date.today()
    query = EvaluationAssignment.query
    if period_id is not None:
        query = query.filter(EvaluationAssignment.period_id == period_id)

    result = AssignmentCoverageRefreshResult()
    frozen_period_ids: dict[int, bool] = {}

    for assignment in query.all():
        # P0 (M-1 Q2/Q4): kilitli/yayımlanmış dönemin görevleri ve tamamlanmış görevler (görev
        # üreticisinin tanımı: completed_at veya tamamlandi/submitted) vekâletle yeniden yönlendirilmez.
        if assignment.period_id not in frozen_period_ids:
            period = db.session.get(PerformancePeriod, assignment.period_id)
            frozen_period_ids[assignment.period_id] = period is not None and period_is_frozen(period)
        if frozen_period_ids[assignment.period_id]:
            continue
        if getattr(assignment, "completed_at", None) or (getattr(assignment, "status", None) or "").strip().lower() in {"tamamlandi", "submitted"}:
            continue
        original_id = getattr(assignment, "original_evaluator_id", None) or getattr(assignment, "evaluator_id", None)
        resolution = resolve_effective_manager(original_id, assignment.manager_level, on_date)

        new_evaluator_id = resolution.acting_manager_id or original_id
        changed = False

        if getattr(assignment, "original_evaluator_id", None) != original_id:
            assignment.original_evaluator_id = original_id
            changed = True

        if getattr(assignment, "evaluator_id", None) != new_evaluator_id:
            assignment.evaluator_id = new_evaluator_id
            changed = True

        if getattr(assignment, "delegation_id", None) != resolution.delegation_id:
            assignment.delegation_id = resolution.delegation_id
            changed = True

        if getattr(assignment, "assignment_source", None) != resolution.source:
            assignment.assignment_source = resolution.source
            changed = True

        coverage_note = resolution.note or None
        if getattr(assignment, "coverage_note", None) != coverage_note:
            assignment.coverage_note = coverage_note
            changed = True

        if changed:
            db.session.add(assignment)
            result.updated_count += 1
            if coverage_note:
                employee_name = getattr(getattr(assignment, "employee", None), "full_name", None) or f"#{assignment.employee_id}"
                result.notes.append(f"{employee_name}: {coverage_note}")

    if result.updated_count:
        db.session.commit()

    return result