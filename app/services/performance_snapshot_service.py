from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, cast

from app import db
from app.core.datetime_utils import utc_now
from app.models import (
    EmployeeOrgAssignmentHistory,
    OrganizationUnit,
    PerformanceEvaluation,
    PerformanceEvaluationItem,
    PerformancePeriod,
    PerformanceResultSnapshot,
    User,
)

# --- BYS360 third-manager Excel import compatibility patch ---
THIRD_MANAGER_STANDARD_KEY = "ucuncu_yonetici_sicil"
THIRD_MANAGER_HEADER_ALIASES = [
    "ucuncu_yonetici_sicil",
    "üçüncü yönetici sicil",
    "ucuncu yonetici sicil",
    "3. amir sicil",
    "3 amir sicil",
    "new_y3",
]


def _full_name(user: User | None) -> str:
    if not user:
        return ""
    if getattr(user, "full_name", None):
        return (user.full_name or "").strip()
    return f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip()


def _manager_by_sicil(sicil_no: str | None) -> User | None:
    sicil_no = (sicil_no or "").strip()
    if not sicil_no:
        return None
    return User.query.filter_by(sicil_no=sicil_no).first()


def build_org_path(unit: OrganizationUnit | None) -> str:
    if not unit:
        return ""
    parts: list[str] = []
    current: OrganizationUnit | None = unit
    guard = 0
    while current is not None and guard < 50:
        name = (getattr(current, "name", "") or "").strip()
        if name:
            parts.append(name)
        current = getattr(current, "parent", None)
        guard += 1
    return " > ".join(reversed(parts))


def get_effective_assignment(employee_id: int, ref_date: date | None) -> EmployeeOrgAssignmentHistory | None:
    if not ref_date:
        ref_date = date.today()

    assignment = (
        EmployeeOrgAssignmentHistory.query
        .filter(
            EmployeeOrgAssignmentHistory.employee_id == employee_id,
            EmployeeOrgAssignmentHistory.start_date <= ref_date,
            db.or_(
                EmployeeOrgAssignmentHistory.end_date.is_(None),
                EmployeeOrgAssignmentHistory.end_date >= ref_date,
            ),
        )
        .order_by(EmployeeOrgAssignmentHistory.start_date.desc(), EmployeeOrgAssignmentHistory.id.desc())
        .first()
    )
    return assignment


def _visible_total_for_evaluation(evaluation: PerformanceEvaluation) -> float:
    if getattr(evaluation, "level_2_completed", False):
        return float(getattr(evaluation, "final_total_100", 0) or 0)
    return float(getattr(evaluation, "level_1_total_100", 0) or 0)


def build_snapshot_payload(evaluation: PerformanceEvaluation) -> dict[str, Any]:
    items = (
        PerformanceEvaluationItem.query
        .filter_by(evaluation_id=evaluation.id)
        .order_by(PerformanceEvaluationItem.criteria_id.asc(), PerformanceEvaluationItem.manager_level.asc())
        .all()
    )

    grouped: dict[int, dict[str, Any]] = {}
    for item in items:
        criteria = item.criteria
        if not criteria:
            continue
        row = grouped.setdefault(
            criteria.id,
            {
                "criteria_id": criteria.id,
                "criteria_code": getattr(criteria, "criteria_code", None),
                "name": getattr(criteria, "name", "") or "",
                "description": getattr(criteria, "description", None),
                "weight": float(getattr(criteria, "weight", 0) or 0),
                "sort_order": int(getattr(criteria, "sort_order", 0) or 0),
                "level_1_score": None,
                "level_2_score": None,
                "level_3_score": None,
                "visible_final_score": None,
            },
        )
        score_100 = float(getattr(item, "score_100", 0) or 0)
        if item.manager_level == 1:
            row["level_1_score"] = score_100
        elif item.manager_level == 2:
            row["level_2_score"] = score_100
        elif item.manager_level == 3:
            row["level_3_score"] = score_100

    for row in grouped.values():
        if row["level_2_score"] is not None:
            row["visible_final_score"] = row["level_2_score"]
        elif row["level_1_score"] is not None:
            row["visible_final_score"] = row["level_1_score"]
        elif row["level_3_score"] is not None:
            row["visible_final_score"] = row["level_3_score"]
        else:
            row["visible_final_score"] = 0

    criteria_rows = sorted(grouped.values(), key=lambda x: (x["sort_order"], x["criteria_id"]))

    return {
        "period_id": evaluation.period_id,
        "evaluation_id": evaluation.id,
        "status": getattr(evaluation, "status", None),
        "criteria": criteria_rows,
    }


def _period_ref_date(period: PerformancePeriod) -> date:
    return getattr(period, "end_date", None) or getattr(period, "start_date", None) or date.today()


def _next_snapshot_version(period_id: int, employee_id: int) -> int:
    last_row = (
        PerformanceResultSnapshot.query
        .filter_by(period_id=period_id, employee_id=employee_id)
        .order_by(PerformanceResultSnapshot.version_no.desc(), PerformanceResultSnapshot.id.desc())
        .first()
    )
    return (last_row.version_no + 1) if last_row else 1


def _deactivate_current_snapshots(period_id: int, employee_id: int) -> None:
    (
        PerformanceResultSnapshot.query
        .filter_by(period_id=period_id, employee_id=employee_id, is_current=True)
        .update({"is_current": False}, synchronize_session=False)
    )


def create_snapshot_for_evaluation(evaluation_id: int, actor_user_id: int | None = None) -> PerformanceResultSnapshot:
    evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
    if not evaluation:
        raise ValueError("Değerlendirme bulunamadı.")

    employee = cast(User, evaluation.employee)
    if not employee:
        raise ValueError("Değerlendirilen personel bulunamadı.")

    period = cast(PerformancePeriod, evaluation.period)
    if not period:
        raise ValueError("Dönem bulunamadı.")

    ref_date = _period_ref_date(period)
    current_unit = getattr(employee, "organization_unit", None)
    assignment = get_effective_assignment(employee.id, ref_date)

    unit_id_snapshot = None
    unit_code_snapshot = None
    birim_snapshot = (getattr(employee, "birim", None) or "").strip() or None
    ust_birim_snapshot = (getattr(employee, "ust_birim", None) or "").strip() or None
    org_path_snapshot = build_org_path(current_unit) if current_unit else None

    manager_1 = _manager_by_sicil(getattr(employee, "yonetici_sicil", None))
    manager_2 = _manager_by_sicil(getattr(employee, "ikinci_yonetici_sicil", None))
    manager_3 = _manager_by_sicil(getattr(employee, "ucuncu_yonetici_sicil", None))

    if assignment:
        unit_id_snapshot = assignment.organization_unit_id
        birim_snapshot = assignment.unit_name_snapshot or birim_snapshot
        ust_birim_snapshot = assignment.parent_unit_name_snapshot or ust_birim_snapshot
        org_path_snapshot = assignment.org_path_snapshot or org_path_snapshot

        if assignment.organization_unit_version and assignment.organization_unit_version.unit_code_snapshot:
            unit_code_snapshot = assignment.organization_unit_version.unit_code_snapshot
        elif assignment.organization_unit and getattr(assignment.organization_unit, "unit_code", None):
            unit_code_snapshot = assignment.organization_unit.unit_code

        manager_1 = cast("User | None", assignment.manager_1_user) or manager_1
        manager_2 = cast("User | None", assignment.manager_2_user) or manager_2
        manager_3 = cast("User | None", assignment.manager_3_user) or manager_3
    elif current_unit:
        unit_id_snapshot = current_unit.id
        unit_code_snapshot = getattr(current_unit, "unit_code", None)
        if not birim_snapshot:
            birim_snapshot = (getattr(current_unit, "name", None) or "").strip() or None
        if not ust_birim_snapshot:
            parent = getattr(current_unit, "parent", None)
            ust_birim_snapshot = (getattr(parent, "name", None) or "").strip() or None

    _deactivate_current_snapshots(period.id, employee.id)
    version_no = _next_snapshot_version(period.id, employee.id)

    snapshot = PerformanceResultSnapshot(
        period_id=period.id,
        evaluation_id=evaluation.id,
        employee_id=employee.id,
        employee_name_snapshot=_full_name(employee),
        sicil_no_snapshot=(getattr(employee, "sicil_no", None) or "").strip(),
        organization_unit_id_snapshot=unit_id_snapshot,
        organization_unit_code_snapshot=unit_code_snapshot,
        birim_snapshot=birim_snapshot,
        ust_birim_snapshot=ust_birim_snapshot,
        org_path_snapshot=org_path_snapshot,
        manager_1_user_id_snapshot=manager_1.id if manager_1 else None,
        manager_1_name_snapshot=_full_name(manager_1) or None,
        manager_1_sicil_snapshot=(getattr(manager_1, "sicil_no", None) if manager_1 else None),
        manager_2_user_id_snapshot=manager_2.id if manager_2 else None,
        manager_2_name_snapshot=_full_name(manager_2) or None,
        manager_2_sicil_snapshot=(getattr(manager_2, "sicil_no", None) if manager_2 else None),
        manager_3_user_id_snapshot=manager_3.id if manager_3 else None,
        manager_3_name_snapshot=_full_name(manager_3) or None,
        manager_3_sicil_snapshot=(getattr(manager_3, "sicil_no", None) if manager_3 else None),
        level_1_total_100=float(getattr(evaluation, "level_1_total_100", 0) or 0),
        level_2_total_100=float(getattr(evaluation, "level_2_total_100", 0) or 0),
        level_3_total_100=float(getattr(evaluation, "level_3_total_100", 0) or 0),
        final_total_100=_visible_total_for_evaluation(evaluation),
        evaluation_status_snapshot=getattr(evaluation, "status", None),
        level_1_general_comment=getattr(evaluation, "level_1_comment", None),
        level_2_general_comment=getattr(evaluation, "level_2_comment", None),
        level_3_general_comment=getattr(evaluation, "level_3_comment", None),
        published_at=utc_now(),
        published_by_user_id=actor_user_id,
        source_type="system_published",
        source_reference=f"evaluation:{evaluation.id}",
        version_no=version_no,
        is_current=True,
        payload_json=build_snapshot_payload(evaluation),
    )
    db.session.add(snapshot)
    return snapshot


def _recalculate_period_rankings(period_id: int) -> None:
    current_rows = (
        PerformanceResultSnapshot.query
        .filter_by(period_id=period_id, is_current=True)
        .order_by(PerformanceResultSnapshot.final_total_100.desc(), PerformanceResultSnapshot.id.asc())
        .all()
    )

    unit_groups: dict[str, list[PerformanceResultSnapshot]] = defaultdict(list)
    for idx, row in enumerate(current_rows, start=1):
        row.ranking_in_scope = idx
        unit_key = (row.birim_snapshot or "__none__").strip().lower()
        unit_groups[unit_key].append(row)

    for rows in unit_groups.values():
        rows.sort(key=lambda x: (-(x.final_total_100 or 0), x.employee_name_snapshot or ""))
        for idx, row in enumerate(rows, start=1):
            row.ranking_in_unit = idx


def create_snapshots_for_period(period_id: int, evaluation_ids: list[int], actor_user_id: int | None = None) -> dict[str, int]:
    period = db.session.get(PerformancePeriod, period_id)
    if not period:
        raise ValueError("Dönem bulunamadı.")

    # Yalnız yayın kararının personele açtığı değerlendirmeler; yayınlanmayan
    # karne system_published anlık görüntüsü almaz.
    evaluations = (
        PerformanceEvaluation.query
        .filter_by(period_id=period_id)
        .filter(PerformanceEvaluation.id.in_(evaluation_ids))
        .filter(PerformanceEvaluation.status == "tamamlandi")
        .all()
    )

    created = 0
    for evaluation in evaluations:
        create_snapshot_for_evaluation(evaluation.id, actor_user_id=actor_user_id)
        created += 1

    _recalculate_period_rankings(period_id)

    period.snapshot_status = "completed"
    period.snapshot_generated_at = utc_now()
    period.snapshot_generated_by_id = actor_user_id

    return {"created": created}


def _has_current_system_snapshot(evaluation_id: int) -> bool:
    return (
        PerformanceResultSnapshot.query
        .filter_by(evaluation_id=evaluation_id, source_type="system_published", is_current=True)
        .first()
        is not None
    )


def backfill_snapshots_for_published_periods(actor_user_id: int | None = None) -> dict[str, int]:
    """Yalnız eksik yayın anlık görüntüsünü onarır; yeni yayın yapmaz.

    Sonuçları yayınlanmış dönemde, tamamlanmış ve personele yayınlanmış olup
    güncel system_published kaydı bulunmayan değerlendirmeler için kayıt açar.
    Commit çağıran rotaya aittir.
    """
    periods = (
        PerformancePeriod.query
        .filter(PerformancePeriod.results_published.is_(True))
        .order_by(PerformancePeriod.id.asc())
        .all()
    )

    created_total = 0
    skipped_total = 0

    for period in periods:
        evaluations = (
            PerformanceEvaluation.query
            .filter_by(period_id=period.id)
            .filter(PerformanceEvaluation.status == "tamamlandi")
            .filter(
                db.or_(
                    PerformanceEvaluation.is_published_to_employee.is_(True),
                    PerformanceEvaluation.published_to_employee_at.isnot(None),
                )
            )
            .order_by(PerformanceEvaluation.id.asc())
            .all()
        )

        created = 0
        for evaluation in evaluations:
            if _has_current_system_snapshot(evaluation.id):
                skipped_total += 1
                continue
            create_snapshot_for_evaluation(evaluation.id, actor_user_id=actor_user_id)
            created += 1

        if created:
            _recalculate_period_rankings(period.id)
            period.snapshot_status = "completed"
            period.snapshot_generated_at = utc_now()
            period.snapshot_generated_by_id = actor_user_id
            created_total += created

    return {
        "period_count": len(periods),
        "created": created_total,
        "skipped": skipped_total,
    }