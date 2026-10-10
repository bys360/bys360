from __future__ import annotations

# BYS360 V1E: emergency runtime recovery for the Phase2Y wildcard-import regression.
# This deliberately restores the shared mobile contract first; explicit imports can be
# reintroduced later only after a per-file F821 gate and smoke test.
from app.api.mobile.shared import (
    AIRecommendation,
    EvaluationAssignment,
    MessageThreadParticipant,
    Notification,
    PerformancePresidentApproval,
    PerformanceTarget,
    SupportTicket,
    User,
    _full_name,
    _has_global_scope,
    _mobile_survey_assignments_for_user,
    _mobile_survey_completed,
    _safe_count,
    _survey_is_active,
    db,
    jsonify,
    mean,
    mobile_api_bp,
    require_mobile_user,
)
from app.services.support_ticket_access import can_view_all_support_tickets


@mobile_api_bp.get("/dashboard/summary")
@require_mobile_user
def mobile_dashboard_summary(*args, **kwargs):
    """P1.4C service delegate wrapper; URL/endpoint/decorator korunur."""
    from app.api.mobile.services.dashboard_service import mobile_dashboard_summary_delegate
    return mobile_dashboard_summary_delegate(_bys360_legacy_mobile_dashboard_summary, *args, **kwargs)

def _bys360_legacy_mobile_dashboard_summary(user: User):
    global_scope = _has_global_scope(user)
    pending_assignments_q = EvaluationAssignment.query.filter(EvaluationAssignment.evaluator_id == user.id)
    try:
        pending_assignments_q = pending_assignments_q.filter(~EvaluationAssignment.status.in_(["tamamlandi", "tamamlandı", "completed", "done"]))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:687)")

    open_tickets_q = SupportTicket.query
    if not can_view_all_support_tickets(user):  # K5
        open_tickets_q = open_tickets_q.filter(SupportTicket.created_by_user_id == user.id)
    try:
        open_tickets_q = open_tickets_q.filter(~SupportTicket.status.in_(["closed", "kapali", "kapalı", "resolved"]))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:695)")

    unread_messages = 0
    try:
        unread_messages = MessageThreadParticipant.query.filter(
            MessageThreadParticipant.user_id == user.id,
            MessageThreadParticipant.left_at.is_(None),
        ).count()
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/dashboard.py:44")
        unread_messages = 0

    active_goals = 0
    kpi_success_rate = 0
    if PerformanceTarget is not None:
        try:
            target_q = PerformanceTarget.query
            active_goals = target_q.filter(PerformanceTarget.status.in_(["active", "ongoing", "devam", "devam_ediyor"])).count()
            rates = [float(x[0] or 0) for x in db.session.query(PerformanceTarget.completion_rate).filter(PerformanceTarget.completion_rate.isnot(None)).limit(200).all()]
            kpi_success_rate = int(mean(rates)) if rates else 0
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/dashboard.py:55")
            active_goals = 0
            kpi_success_rate = 0

    return jsonify({
        "user_name": _full_name(user),
        "pending_performance": _safe_count(pending_assignments_q),
        "unread_notifications": _safe_count(Notification.query.filter_by(user_id=user.id, is_read=False)),
        "open_tickets": _safe_count(open_tickets_q),
        "assigned_surveys": _survey_count_for_user(user),
        "kpi_success_rate": kpi_success_rate,
        "pending_approvals": _safe_count(PerformancePresidentApproval.query.filter_by(status="pending")) if global_scope else 0,
        "active_personnel": _safe_count(User.query.filter_by(is_active=True)) if global_scope else 1,
        "unread_messages": unread_messages,
        "ai_alerts": _safe_count(AIRecommendation.query.filter(AIRecommendation.status.in_(["open", "pending", "active"]))) if global_scope else 0,
        "active_goals": active_goals,
        "certificates": 0,
    })


def _survey_count_for_user(user: User) -> int:
    try:
        count = 0
        seen: set[int] = set()
        for assignment in _mobile_survey_assignments_for_user(user):
            survey = getattr(assignment, "survey", None)
            if not survey:
                continue
            sid = int(getattr(survey, "id", 0) or 0)
            if not sid or sid in seen:
                continue
            seen.add(sid)
            if _survey_is_active(survey) and (bool(getattr(survey, "allow_multiple_submissions", False)) or not _mobile_survey_completed(user, survey)):
                count += 1
        return count
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/dashboard.py:90")
        return 0

