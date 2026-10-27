from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from flask import url_for
from sqlalchemy import case, func, or_
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import (
    AssignmentCoverageLog,
    EvaluationAssignment,
    PerformanceEvaluation,
    PerformanceEvaluationItem,
    PerformancePeriod,
    User,
)
from app.route_support import safe_all
from app.services.ai.audit import (
    ensure_recommendation_rows,
    log_ai_request,
    upsert_ai_summary_cache,
)
from app.services.ai.dashboard_panels import (
    build_assignment_delegation_pressure_ai_panel,
    build_assignment_recommendation_center_ai_panel,
    build_task_generation_ai_panel,
    build_task_preflight_ai_panel,
)
from app.services.hierarchy_admin_service import get_manager_scope_users
from app.services.performance_service import (
    analyze_hierarchy_gaps,
    build_assignment_log_summary,
    build_assignment_unit_summary,
    get_latest_assignment_generation_logs,
    is_informational_special_case,
)
from app.view_helpers import build_scope_switch_context

TASK_MANAGEMENT_LIST_LIMIT = 500
TASK_MANAGEMENT_COVERAGE_LIMIT = 80
TASK_MANAGEMENT_VISIBLE_STATUSES = {"bekliyor", "kismen_tamamlandi", "tamamlandi"}


def _normal_scope_ids(scope_user_ids: set | list | tuple | None) -> list[int]:
    """Scope listesini SQL IN icin guvenli, tekillestirilmis int listeye indirger."""
    cleaned: list[int] = []
    seen: set[int] = set()
    for raw in scope_user_ids or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/performance/task_management_service.py:53)")
            continue
        if value > 0 and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return cleaned


def _apply_assignment_scope(query, scope_user_ids: set | list | tuple | None):
    scope_ids = _normal_scope_ids(scope_user_ids)
    if scope_user_ids is not None and not scope_ids:
        return query.filter(EvaluationAssignment.employee_id == -1)
    if scope_ids:
        return query.filter(EvaluationAssignment.employee_id.in_(scope_ids))
    return query


def _active_personnel_count(scope_user_ids: set | list | tuple | None = None) -> int:
    scope_ids = _normal_scope_ids(scope_user_ids)
    if scope_user_ids is not None and not scope_ids:
        return 0
    query = User.query.filter(User.is_active.is_(True), User.role != "admin")
    query = query.filter(~func.lower(func.coalesce(User.email, "")).like("admin@%"))
    query = query.filter(~func.lower(func.coalesce(User.email, "")).like("system@%"))
    query = query.filter(~func.lower(func.coalesce(User.email, "")).like("sysadmin@%"))
    query = query.filter(~func.lower(func.coalesce(User.sicil_no, "")).in_(["admin", "system", "sysadmin"]))
    query = query.filter(~func.lower(func.coalesce(User.birim, "")).in_(["bys360"]))
    query = query.filter(~func.lower(func.coalesce(User.ust_birim, "")).in_(["bys360"]))
    if scope_ids:
        query = query.filter(User.id.in_(scope_ids))
    return int(query.order_by(None).count() or 0)


def _assignment_base_query(period_id: int):
    employee_user = aliased(User)
    evaluator_user = aliased(User)
    query = (
        EvaluationAssignment.query
        .join(employee_user, EvaluationAssignment.employee_id == employee_user.id)
        .outerjoin(evaluator_user, EvaluationAssignment.evaluator_id == evaluator_user.id)
        .outerjoin(PerformancePeriod, EvaluationAssignment.period_id == PerformancePeriod.id)
        .filter(EvaluationAssignment.period_id == period_id)
    )
    return query, employee_user, evaluator_user


def _assignment_stats_for_period(period_id: int, scope_user_ids: set | list | tuple | None = None) -> dict[str, int]:
    query = db.session.query(
        func.count(EvaluationAssignment.id).label("total"),
        func.coalesce(func.sum(case((EvaluationAssignment.status == "bekliyor", 1), else_=0)), 0).label("pending"),
        func.coalesce(func.sum(case((EvaluationAssignment.status == "kismen_tamamlandi", 1), else_=0)), 0).label("partial"),
        func.coalesce(func.sum(case((EvaluationAssignment.status == "tamamlandi", 1), else_=0)), 0).label("completed"),
        func.coalesce(func.sum(case((EvaluationAssignment.manager_level == 1, 1), else_=0)), 0).label("level_1"),
        func.coalesce(func.sum(case((EvaluationAssignment.manager_level == 2, 1), else_=0)), 0).label("level_2"),
        func.coalesce(func.sum(case((EvaluationAssignment.manager_level == 3, 1), else_=0)), 0).label("level_3"),
    ).filter(EvaluationAssignment.period_id == period_id)
    query = _apply_assignment_scope(query, scope_user_ids)
    row = query.one()
    return {
        "total": int(row.total or 0),
        "pending": int(row.pending or 0),
        "partial": int(row.partial or 0),
        "completed": int(row.completed or 0),
        "level_1": int(row.level_1 or 0),
        "level_2": int(row.level_2 or 0),
        "level_3": int(row.level_3 or 0),
    }


def _assignment_source_summary_for_period(period_id: int, scope_user_ids: set | list | tuple | None = None) -> dict[str, int]:
    query = db.session.query(
        func.coalesce(EvaluationAssignment.assignment_source, "direct").label("source"),
        func.count(EvaluationAssignment.id).label("row_count"),
    ).filter(EvaluationAssignment.period_id == period_id)
    query = _apply_assignment_scope(query, scope_user_ids)
    rows = query.group_by(func.coalesce(EvaluationAssignment.assignment_source, "direct")).all()
    summary = {"direct": 0, "delegated": 0, "uncovered": 0}
    for source, row_count in rows:
        key = str(source or "direct").strip().lower() or "direct"
        if key in summary:
            summary[key] = int(row_count or 0)
    return summary


def _assignment_source_rows(period_id: int, source: str, scope_user_ids: set | list | tuple | None = None, *, limit: int = TASK_MANAGEMENT_COVERAGE_LIMIT):
    query, _employee_user, _evaluator_user = _assignment_base_query(period_id)
    query = _apply_assignment_scope(query, scope_user_ids)
    query = query.filter(EvaluationAssignment.assignment_source == source)
    return safe_all(
        query.order_by(EvaluationAssignment.employee_id.asc(), EvaluationAssignment.manager_level.asc(), EvaluationAssignment.id.desc()).limit(limit),
        label=f"task_management_{source}_assignments",
    )


def _filtered_assignment_query(period_id: int, *, q: str = "", status: str = "", manager_level: int | None = None, scope_user_ids: set | list | tuple | None = None):
    query, employee_user, evaluator_user = _assignment_base_query(period_id)
    query = _apply_assignment_scope(query, scope_user_ids)
    q = (q or "").strip()
    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                employee_user.full_name_cache.ilike(like_q),
                employee_user.ad.ilike(like_q),
                employee_user.soyad.ilike(like_q),
                employee_user.sicil_no.ilike(like_q),
                employee_user.birim.ilike(like_q),
                employee_user.ust_birim.ilike(like_q),
                evaluator_user.full_name_cache.ilike(like_q),
                evaluator_user.ad.ilike(like_q),
                evaluator_user.soyad.ilike(like_q),
                evaluator_user.sicil_no.ilike(like_q),
                PerformancePeriod.title.ilike(like_q),
            )
        )
    normalized_status = status if status in TASK_MANAGEMENT_VISIBLE_STATUSES else ""
    if normalized_status:
        query = query.filter(EvaluationAssignment.status == normalized_status)
    normalized_level = manager_level if manager_level in (1, 2, 3) else None
    if normalized_level is not None:
        query = query.filter(EvaluationAssignment.manager_level == normalized_level)
    return query, normalized_status, normalized_level

def build_task_management_dashboard_payload(selected_period, *, q: str = "", status: str = "", manager_level: int | None = None, scope_user_ids: set | None = None, selected_scope: str = "") -> dict[str, Any]:
    hierarchy_alerts = analyze_hierarchy_gaps(selected_period.id if selected_period else None)
    hierarchy_alerts = [row for row in hierarchy_alerts if getattr(row.get("user"), "role", None) != "admin"]
    if scope_user_ids is not None:
        hierarchy_alerts = [row for row in hierarchy_alerts if getattr(row.get("user"), "id", None) in scope_user_ids]

    total_users = _active_personnel_count(scope_user_ids)

    alert_summary = {
        "total_users": total_users,
        "problematic_users": len(hierarchy_alerts),
        "ok_users": max(0, total_users - len(hierarchy_alerts)),
    }

    stats = {
        "total": 0,
        "pending": 0,
        "partial": 0,
        "completed": 0,
        "level_1": 0,
        "level_2": 0,
        "level_3": 0,
    }
    assignments = []
    filtered_count = 0
    coverage_summary = {"direct": 0, "delegated": 0, "uncovered": 0}
    delegated_assignments = []
    uncovered_assignments = []
    exempt_evaluations = []
    visible_assignment_logs = []
    special_case_logs = []
    latest_assignment_log_run_key = None
    latest_assignment_log_created_at = None
    latest_assignment_log_summary = build_assignment_log_summary([])

    if selected_period:
        stats.update(_assignment_stats_for_period(selected_period.id, scope_user_ids))
        coverage_summary.update(_assignment_source_summary_for_period(selected_period.id, scope_user_ids))

        delegated_assignments = _assignment_source_rows(
            selected_period.id,
            "delegated",
            scope_user_ids,
        )
        uncovered_assignments = _assignment_source_rows(
            selected_period.id,
            "uncovered",
            scope_user_ids,
        )

        exempt_query = PerformanceEvaluation.query.filter_by(period_id=selected_period.id, evaluation_exempted=True)
        if scope_user_ids is not None:
            exempt_query = exempt_query.filter(PerformanceEvaluation.employee_id.in_(_normal_scope_ids(scope_user_ids)))
        exempt_evaluations = safe_all(
            exempt_query.order_by(PerformanceEvaluation.updated_at.desc(), PerformanceEvaluation.id.desc()).limit(TASK_MANAGEMENT_COVERAGE_LIMIT),
            label="task_management_exempt_evaluations",
        )

        latest_log_payload = get_latest_assignment_generation_logs(
            selected_period.id,
            limit=250,
            employee_ids=_normal_scope_ids(scope_user_ids) if scope_user_ids is not None else None,
        )
        latest_assignment_logs = list(latest_log_payload.get("rows") or [])
        latest_assignment_log_run_key = latest_log_payload.get("run_key")
        latest_assignment_log_created_at = latest_log_payload.get("created_at")
        latest_assignment_log_summary = latest_log_payload.get("summary", build_assignment_log_summary([]))
        visible_assignment_logs = [
            row for row in latest_assignment_logs
            if not is_informational_special_case(getattr(row, "reason", None), getattr(row, "event_type", None))
        ]
        special_case_logs = [
            row for row in latest_assignment_logs
            if is_informational_special_case(getattr(row, "reason", None), getattr(row, "event_type", None))
        ]

        filtered_query, normalized_status, normalized_level = _filtered_assignment_query(
            selected_period.id,
            q=q,
            status=status,
            manager_level=manager_level,
            scope_user_ids=scope_user_ids,
        )
        filtered_count = int(filtered_query.order_by(None).count() or 0)
        assignments = safe_all(
            filtered_query.order_by(
                EvaluationAssignment.employee_id.asc(),
                EvaluationAssignment.manager_level.asc(),
                EvaluationAssignment.id.desc(),
            ).limit(TASK_MANAGEMENT_LIST_LIMIT),
            label="task_management_filtered_assignments",
        )
        status = normalized_status
        manager_level = normalized_level

    recommendation_payload = build_assignment_recommendation_payload(
        selected_period,
        selected_scope or "",
        scope_user_ids,
    )

    return {
        "hierarchy_alerts": hierarchy_alerts,
        "alert_summary": alert_summary,
        "stats": stats,
        "assignments": assignments,
        "filtered_count": filtered_count,
        "coverage_summary": coverage_summary,
        "delegated_assignments": delegated_assignments,
        "uncovered_assignments": uncovered_assignments,
        "exempt_evaluations": exempt_evaluations,
        "latest_assignment_logs": visible_assignment_logs,
        "special_case_logs": special_case_logs,
        "latest_assignment_log_run_key": latest_assignment_log_run_key,
        "latest_assignment_log_created_at": latest_assignment_log_created_at,
        "latest_assignment_log_summary": latest_assignment_log_summary,
        "selected_status": status,
        "selected_manager_level": manager_level,
        "ai_task_panel": build_task_generation_ai_panel(
            stats=stats,
            coverage_summary=coverage_summary,
            latest_log_summary=latest_assignment_log_summary,
            period=selected_period,
        ),
        "ai_preflight_panel": build_task_preflight_ai_panel(
            alert_summary=alert_summary,
            coverage_summary=coverage_summary,
            latest_log_summary=latest_assignment_log_summary,
            period=selected_period,
        ),
        "ai_audit_panel": recommendation_payload.get("ai_recommendation_panel"),
    }

def build_task_scope_context(actor, selected_scope: str):
    scope = build_scope_switch_context(
        actor,
        selected_scope,
        managed_scope_users=get_manager_scope_users(actor),
        managed_scope_label=(getattr(actor, "birim", None) or getattr(actor, "ust_birim", None) or "Görev alanın"),
    )
    return scope, set(scope.get("scope_user_ids") or [])


def get_selected_period_from_args(source=None):
    getter = getattr(source, "get", None)
    selected_period_id = None
    if callable(getter):
        try:
            selected_period_id = getter("period_id", type=int)
        except TypeError:
            raw_value = getter("period_id")
            try:
                selected_period_id = int(raw_value) if raw_value not in (None, "") else None
            except (TypeError, ValueError):
                selected_period_id = None
    if not selected_period_id:
        active_period = PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
        selected_period_id = active_period.id if active_period else None
    return db.session.get(PerformancePeriod, selected_period_id) if selected_period_id else None


def matches_audit_query(row, q: str) -> bool:
    query = (q or "").strip().lower()
    if not query:
        return True
    employee = getattr(row, "employee", None)
    haystack = [
        getattr(employee, "ad", ""),
        getattr(employee, "soyad", ""),
        getattr(employee, "full_name", ""),
        getattr(employee, "sicil_no", ""),
        getattr(employee, "birim", ""),
        getattr(employee, "ust_birim", ""),
        getattr(row, "event_type", ""),
        getattr(row, "reason", ""),
        getattr(getattr(row, "acting_evaluator", None), "full_name", ""),
        getattr(getattr(row, "original_evaluator", None), "full_name", ""),
    ]
    blob = " | ".join(str(item or "") for item in haystack).lower()
    return query in blob


def build_audit_employee_options(scope_user_ids: set | None = None):
    query = User.query.filter(User.is_active.is_(True), User.role != "admin")
    if scope_user_ids is not None:
        query = query.filter(User.id.in_(list(scope_user_ids)))
    return query.order_by(User.ad.asc(), User.soyad.asc()).limit(500).all()


def filter_audit_rows(rows, *, severity: str = "", event_type: str = "", employee_id: int | None = None, q: str = ""):
    filtered = []
    severity_value = (severity or "").strip().lower()
    event_value = (event_type or "").strip().lower()
    for row in rows or []:
        row_severity = str(getattr(row, "severity", "") or "").strip().lower()
        row_event = str(getattr(row, "event_type", "") or "").strip().lower()
        if severity_value and row_severity != severity_value:
            continue
        if event_value and row_event != event_value:
            continue
        if employee_id and getattr(row, "employee_id", None) != employee_id:
            continue
        if q and not matches_audit_query(row, q):
            continue
        filtered.append(row)
    return filtered


def _assignment_shortcut_rows(selected_period, selected_scope: str, summary: dict | None = None):
    if not selected_period:
        return []
    summary = summary or {}
    return [
        {
            "label": "Açıkta kalan kayıtlar",
            "tone": "critical",
            "icon": "fa-user-slash",
            "count": int(summary.get("uncovered") or 0),
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="uncovered"),
        },
        {
            "label": "Zincir sorunu taşıyanlar",
            "tone": "critical",
            "icon": "fa-link-slash",
            "count": int(summary.get("chain_issue") or 0),
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="chain_issue"),
        },
        {
            "label": "Vekâletli görevler",
            "tone": "watch",
            "icon": "fa-people-arrows-left-right",
            "count": int(summary.get("delegated") or 0),
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="delegated"),
        },
        {
            "label": "Muaf kayıtlar",
            "tone": "watch",
            "icon": "fa-circle-minus",
            "count": int(summary.get("exempted") or 0),
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="exempted"),
        },
    ]


def _action_priority_score(row: dict[str, Any]) -> int:
    tone_weight = 200 if row.get("tone") == "critical" else 100 if row.get("tone") == "watch" else 0
    try:
        count_weight = int(float(row.get("count") or 0))
    except (TypeError, ValueError):
        count_weight = 0
    owner_weight = 15 if "İK" in str(row.get("owner") or "") else 0
    return tone_weight + count_weight + owner_weight


def _finalize_action_plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = []
    for row in rows or []:
        item = dict(row)
        item["priority_score"] = _action_priority_score(item)
        ordered.append(item)
    ordered.sort(key=lambda item: (-int(item.get("priority_score") or 0), str(item.get("title") or "").lower()))
    for index, row in enumerate(ordered, start=1):
        row["priority"] = index
    return ordered


def log_performance_recommendation_export(*, selected_period, selected_scope: str, export_format: str, payload: dict, actor_user_id: int | None = None) -> None:
    if not selected_period:
        return
    summary = payload.get("summary") or {}
    recommendation_rows = payload.get("recommendation_rows") or []
    action_plan_rows = payload.get("action_plan_rows") or []
    pressure_rows = payload.get("pressure_rows") or []
    period_label = getattr(selected_period, "title", None) or "aktif dönem"
    scope_label = selected_scope or "genel"
    summary_text = " | ".join(
        [
            f"Performans AI öneri merkezi export · dönem={period_label}",
            f"scope={scope_label}",
            f"format={export_format}",
            f"açıkta={int(summary.get('uncovered') or 0)}",
            f"zincir={int(summary.get('chain_issue') or 0)}",
            f"vekâlet={int(summary.get('delegated') or 0)}",
            f"muaf={int(summary.get('exempted') or 0)}",
            *[str(row.get('title') or '') for row in action_plan_rows[:5] if str(row.get('title') or '').strip()],
        ]
    )
    log_row = log_ai_request(
        module_type="performance",
        feature_type="task_recommendations_export",
        target_table="evaluation_assignments",
        target_id=int(getattr(selected_period, "id", 0) or 0),
        user_id=actor_user_id,
        request_text=f"scope={scope_label};format={export_format};period_id={getattr(selected_period, 'id', 0) or 0}",
        response_text=summary_text,
        provider_name="rule_engine",
        model_name="bys360-performance-ai-v1",
        prompt_version="performance_task_recommendations_v1",
        latency_ms=0,
        token_in=0,
        token_out=max(len(summary_text) // 4, 1),
        was_masked=True,
        was_user_visible=False,
        status="completed",
    )
    recommendation_titles = [str(row.get("title") or "").strip() for row in recommendation_rows[:6] if str(row.get("title") or "").strip()]
    if not recommendation_titles:
        recommendation_titles = [str(row.get("title") or "").strip() for row in action_plan_rows[:6] if str(row.get("title") or "").strip()]
    ensure_recommendation_rows(
        module_type="performance",
        target_table="evaluation_assignments",
        target_id=int(getattr(selected_period, "id", 0) or 0),
        recommendation_type="task_governance",
        titles=recommendation_titles,
        ai_request_log_id=getattr(log_row, "id", None),
        created_by_id=actor_user_id,
        severity="warning" if int(summary.get("uncovered") or 0) or int(summary.get("chain_issue") or 0) else "info",
    )
    upsert_ai_summary_cache(
        module_type="performance",
        target_table="evaluation_assignments",
        target_id=int(getattr(selected_period, "id", 0) or 0),
        summary_kind=f"task_recommendations_{scope_label}",
        summary_text=summary_text,
        source_hash=f"performance:{getattr(selected_period, 'id', 0) or 0}:{scope_label}:{len(action_plan_rows)}:{len(pressure_rows)}",
    )
    db.session.commit()


def build_assignment_recommendation_payload(selected_period, selected_scope: str, scope_user_ids: set | None = None, severity: str = "", event_type: str = ""):
    empty = {
        "summary": build_assignment_log_summary([]),
        "visible_rows": [],
        "reason_rows": [],
        "pressure_rows": [],
        "recommendation_rows": [],
        "action_plan_rows": [],
        "shortcut_rows": [],
        "ai_recommendation_panel": build_assignment_recommendation_center_ai_panel(summary={}, recommendation_rows=[], action_plan_rows=[], pressure_rows=[], period=selected_period, scope_label=selected_scope or "Genel görünüm"),
        "ai_pressure_panel": build_assignment_delegation_pressure_ai_panel(pressure_rows=[], shortcut_rows=[], scope_label=selected_scope or "Genel görünüm"),
    }
    if not selected_period:
        return empty

    employee_ids = list(scope_user_ids) if scope_user_ids is not None else None
    latest_bundle = get_latest_assignment_generation_logs(selected_period.id, limit=800, employee_ids=employee_ids)
    visible_rows = list(latest_bundle.get("rows") or [])
    if severity:
        visible_rows = [row for row in visible_rows if (getattr(row, "severity", "") or "").strip() == severity]
    if event_type:
        visible_rows = [row for row in visible_rows if (getattr(row, "event_type", "") or "").strip() == event_type]

    summary = build_assignment_log_summary(visible_rows)
    unit_rows = build_assignment_unit_summary(visible_rows, top_n=None)
    pressure_rows = []
    for row in unit_rows[:10]:
        risk_score = int(row.get("risk_score", 0) or 0)
        tone = "critical" if risk_score >= 6 or int(row.get("uncovered", 0)) or int(row.get("chain_issue", 0)) else "watch"
        detail_parts = []
        if int(row.get("uncovered", 0)):
            detail_parts.append(f"açıkta {row.get('uncovered')}")
        if int(row.get("chain_issue", 0)):
            detail_parts.append(f"zincir {row.get('chain_issue')}")
        if int(row.get("delegated", 0)):
            detail_parts.append(f"vekâlet {row.get('delegated')}")
        if int(row.get("exempted", 0)):
            detail_parts.append(f"muaf {row.get('exempted')}")
        pressure_rows.append({
            "unit_name": row.get("unit_name") or "Tanımsız",
            "risk_score": risk_score,
            "detail": ", ".join(detail_parts) or f"toplam {row.get('log_count', 0)} kayıt",
            "tone": tone,
            "log_count": int(row.get("log_count", 0) or 0),
        })

    reasons = Counter((getattr(row, "reason", None) or "Tanımsız neden").strip() for row in visible_rows)
    reason_rows = sorted(reasons.items(), key=lambda item: (-int(item[1]), item[0].lower()))

    recommendation_rows = []
    if int(summary.get("uncovered", 0) or 0):
        recommendation_rows.append({
            "title": "Açıkta kalan görevleri önce kapat",
            "detail": f"{summary.get('uncovered')} kayıt doğrudan kapsama bulamamış görünüyor. Önce açıkta kalan personel ve eksik amir eşleşmeleri temizlenmeli.",
            "count": int(summary.get("uncovered", 0) or 0),
            "tone": "critical",
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="uncovered"),
        })
    if int(summary.get("chain_issue", 0) or 0):
        recommendation_rows.append({
            "title": "Amir zinciri kırıklarını toplu düzelt",
            "detail": f"{summary.get('chain_issue')} kayıt zincir sorunu taşıyor. Hiyerarşi atamaları ekranında aynı kümeler birlikte ele alınmalı.",
            "count": int(summary.get("chain_issue", 0) or 0),
            "tone": "critical",
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="chain_issue"),
        })
    if int(summary.get("delegated", 0) or 0):
        recommendation_rows.append({
            "title": "Kalıcılaşan vekâlet yükünü azalt",
            "detail": f"{summary.get('delegated')} görev vekâletle akıyor. Aynı birimde tekrar eden devirler için izin-vekalet ve organizasyon yapısı birlikte gözden geçirilmeli.",
            "count": int(summary.get("delegated", 0) or 0),
            "tone": "watch",
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="delegated"),
        })
    if int(summary.get("exempted", 0) or 0):
        recommendation_rows.append({
            "title": "Muaf kayıtların gerekçesini toparla",
            "detail": f"{summary.get('exempted')} kayıt muaf akışta. Kısa ve net gerekçeler rapor okunabilirliğini güçlendirir.",
            "count": int(summary.get("exempted", 0) or 0),
            "tone": "watch",
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None, event_type="exempted"),
        })

    action_plan_rows = []
    for row in recommendation_rows:
        owner = "Performans yöneticisi"
        title = str(row.get("title") or "")
        if "zincir" in title.lower():
            owner = "İK + Hiyerarşi yöneticisi"
        elif "vekâlet" in title.lower() or "görev devri" in title.lower():
            owner = "İK + Birim yöneticisi"
        elif "muaf" in title.lower():
            owner = "İK"
        elif "açıkta" in title.lower():
            owner = "İK + Performans yöneticisi"
        action_plan_rows.append({
            "title": row["title"],
            "count": row["count"],
            "tone": row["tone"],
            "owner": owner,
            "next_step": row["detail"],
            "url": row["url"],
        })

    for unit in pressure_rows[:5]:
        action_plan_rows.append({
            "title": f"{unit['unit_name']} biriminde görev devri baskısı",
            "count": unit["risk_score"],
            "tone": unit["tone"],
            "owner": "İK + Birim yöneticisi",
            "next_step": f"{unit['detail']} görünümü üzerinden kalıcı görev devri baskısı incelenmeli.",
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None),
        })

    for reason, count in reason_rows[:3]:
        action_plan_rows.append({
            "title": f"Neden kümesi: {reason}",
            "count": int(count),
            "tone": "watch",
            "owner": "Süreç sahibi",
            "next_step": "Aynı kök neden tekrar ediyorsa toplu düzeltme kuralı hazırlanmalı.",
            "url": url_for("main.performance_task_management_audit_detail", period_id=selected_period.id, scope=selected_scope or None),
        })

    action_plan_rows = _finalize_action_plan_rows(action_plan_rows)
    shortcut_rows = _assignment_shortcut_rows(selected_period, selected_scope, summary)
    ai_recommendation_panel = build_assignment_recommendation_center_ai_panel(
        summary=summary,
        recommendation_rows=recommendation_rows,
        action_plan_rows=action_plan_rows,
        pressure_rows=pressure_rows,
        period=selected_period,
        scope_label=selected_scope or "Genel görünüm",
    )
    ai_pressure_panel = build_assignment_delegation_pressure_ai_panel(
        pressure_rows=pressure_rows,
        shortcut_rows=shortcut_rows,
        scope_label=selected_scope or "Genel görünüm",
    )

    return {
        "summary": summary,
        "visible_rows": visible_rows,
        "reason_rows": reason_rows,
        "pressure_rows": pressure_rows,
        "recommendation_rows": recommendation_rows,
        "action_plan_rows": action_plan_rows,
        "shortcut_rows": shortcut_rows,
        "ai_recommendation_panel": ai_recommendation_panel,
        "ai_pressure_panel": ai_pressure_panel,
    }


def build_task_health_csv_text(health_report: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Bölüm", "Ad Soyad", "Birim", "Seviye", "Detay", "Ek Bilgi"])

    for row in health_report.get("duplicate_rows") or []:
        writer.writerow([
            "Mükerrer görev",
            row.get("employee_name"),
            row.get("employee_unit"),
            row.get("manager_level"),
            ", ".join(row.get("evaluators") or []),
            f"Satır: {row.get('row_count')} | Kaynak: {', '.join(row.get('source_labels') or [])}",
        ])

    for row in health_report.get("mismatch_rows") or []:
        writer.writerow([
            "Amir eşleşme farkı",
            row.get("employee_name"),
            row.get("employee_unit"),
            row.get("manager_level"),
            row.get("reason"),
            f"Beklenen: {row.get('expected_manager_name') or '-'} | Gerçek: {', '.join(row.get('actual_manager_names') or [])}",
        ])

    for row in health_report.get("orphan_evaluations") or []:
        writer.writerow([
            "Görevsiz değerlendirme",
            row.get("employee_name"),
            row.get("employee_unit"),
            "-",
            row.get("workflow_status"),
            f"Muaf: {'Evet' if row.get('exempted') else 'Hayır'}",
        ])

    for row in health_report.get("orphan_assignments") or []:
        writer.writerow([
            "Değerlendirmesiz görev",
            row.get("employee_name"),
            row.get("employee_unit"),
            ", ".join(str(value) for value in (row.get("manager_levels") or [])),
            ", ".join(row.get("sources") or []),
            ", ".join(str(value) for value in (row.get("assignment_ids") or [])),
        ])

    for row in health_report.get("health_rows") or []:
        user = row.get("user")
        user_name = getattr(user, "full_name", None) or f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip() or row.get("manager_1_name")
        user_unit = getattr(user, "birim", None) or getattr(user, "ust_birim", None) or "-"
        for issue in (row.get("issues") or []):
            writer.writerow([
                "Zincir sorunu",
                user_name,
                user_unit,
                "-",
                issue,
                row.get("status_label"),
            ])

    csv_text = output.getvalue()
    return csv_text if csv_text.startswith("﻿") else "﻿" + csv_text


def build_task_audit_csv_text(visible_rows) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Personel", "Sicil No", "Birim", "Üst Birim", "Seviye", "Olay", "Önem", "Gerekçe", "Asıl Amir", "İşleyen Amir"])
    for row in visible_rows:
        employee = getattr(row, "employee", None)
        original_evaluator = getattr(row, "original_evaluator", None)
        acting_evaluator = getattr(row, "acting_evaluator", None)
        writer.writerow([
            getattr(employee, "full_name", None) or f"{getattr(employee, 'ad', '')} {getattr(employee, 'soyad', '')}".strip(),
            getattr(employee, "sicil_no", None) or "",
            getattr(employee, "birim", None) or "",
            getattr(employee, "ust_birim", None) or "",
            getattr(row, "manager_level", None) or "",
            getattr(row, "event_type", None) or "",
            getattr(row, "severity", None) or "",
            getattr(row, "reason", None) or "",
            getattr(original_evaluator, "full_name", None) or f"{getattr(original_evaluator, 'ad', '')} {getattr(original_evaluator, 'soyad', '')}".strip(),
            getattr(acting_evaluator, "full_name", None) or f"{getattr(acting_evaluator, 'ad', '')} {getattr(acting_evaluator, 'soyad', '')}".strip(),
        ])
    csv_text = output.getvalue()
    return csv_text if csv_text.startswith("﻿") else "﻿" + csv_text


def build_task_recommendation_export_response(action_plan_rows, *, export_format: str = "csv"):
    export_format = (export_format or "csv").strip().lower()
    if export_format == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Aksiyon Planı"
        sheet.append(["Öncelik", "Başlık", "Adet/Skor", "Ton", "Sahip", "Sonraki Adım", "Filtre URL"])
        for row in action_plan_rows or []:
            sheet.append([
                row.get("priority"),
                row.get("title"),
                row.get("count"),
                row.get("tone"),
                row.get("owner"),
                row.get("next_step"),
                row.get("url"),
            ])
        binary = io.BytesIO()
        workbook.save(binary)
        binary.seek(0)
        return {
            "content": binary.getvalue(),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "extension": "xlsx",
        }

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Öncelik", "Başlık", "Adet/Skor", "Ton", "Sahip", "Sonraki Adım", "Filtre URL"])
    for row in action_plan_rows or []:
        writer.writerow([
            row.get("priority"),
            row.get("title"),
            row.get("count"),
            row.get("tone"),
            row.get("owner"),
            row.get("next_step"),
            row.get("url"),
        ])
    csv_text = output.getvalue()
    csv_text = csv_text if csv_text.startswith("﻿") else "﻿" + csv_text
    return {
        "content": csv_text,
        "mimetype": "text/csv; charset=utf-8",
        "extension": "csv",
    }


def clear_period_task_records(period_id: int) -> dict[str, int]:
    from app.services.performance.period_freeze import FROZEN_PERIOD_TASKS_MESSAGE, period_is_frozen

    # P0 (Q3-1, M-2 sahip kararı): dondurulmuş dönemin kayıtları hiçbir çağrıdan temizlenmez
    # (gerçek admin dahil); rota denetim kaydıyla önce reddeder, bu kontrol servis düzeyinde ikinci kapı.
    period = db.session.get(PerformancePeriod, period_id)
    if period is not None and period_is_frozen(period):
        raise PermissionError(FROZEN_PERIOD_TASKS_MESSAGE)
    evaluation_ids = [row.id for row in PerformanceEvaluation.query.filter_by(period_id=period_id).all()]
    item_count = 0
    if evaluation_ids:
        item_count = PerformanceEvaluationItem.query.filter(PerformanceEvaluationItem.evaluation_id.in_(evaluation_ids)).delete(synchronize_session=False)
    assignment_count = EvaluationAssignment.query.filter_by(period_id=period_id).delete(synchronize_session=False)
    evaluation_count = PerformanceEvaluation.query.filter_by(period_id=period_id).delete(synchronize_session=False)
    log_count = AssignmentCoverageLog.query.filter_by(period_id=period_id).delete(synchronize_session=False)
    return {
        "evaluation_item_count": int(item_count or 0),
        "assignment_count": int(assignment_count or 0),
        "evaluation_count": int(evaluation_count or 0),
        "log_count": int(log_count or 0),
    }