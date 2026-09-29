"""Build reports/quality/BYS360_AUTHORIZATION_MATRIX_V1.json from the registered Flask routes.

For every URL rule it records the view's decorators (from the source AST), the
authorization calls found in the view body, blueprint/app-level guards that apply,
object-id parameters and the test files that reference the URL. Classification is
evidence-based and conservative: a route is OBJECT_GATED only when its body shows a
scope/ownership check, and NEEDS_REVIEW means "a human or a test must confirm",
not "vulnerable".

usage: python scripts/quality/bys360_authorization_matrix.py [--out PATH]
Runs against an in-memory SQLite app; it never touches a real database.
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "reports" / "quality" / "BYS360_AUTHORIZATION_MATRIX_V1.json"

AUTH_DECORATORS = {"login_required", "require_mobile_user", "mobile_login_required", "api_login_required"}
# Role decorators in app/route_support.py that redirect anonymous users to login first.
AUTHENTICATING_ROLE_DECORATORS = {"menu_key_required", "_require_role_family", "admin_required", "manager_required"}
# Views whose first check is a helper that refuses anonymous users; read in the source
# (tests/security/test_anonymous_route_runtime_contract.py confirms it at runtime).
AUTHENTICATED_BY_HELPER = {
    "ai_agent.ag5_knowledge_toggle": "can_manage_ai_knowledge() returns False unless current_user.is_authenticated",
    "ai_agent.ag5_knowledge_delete": "can_manage_ai_knowledge() returns False unless current_user.is_authenticated",
}
_BODY_AUTH_CHECK = re.compile(r"current_user\.is_authenticated|current_user\s*,\s*['\"]is_authenticated['\"]")
ROLE_DECORATORS = re.compile(
    r"(admin_required|roles?_required|permission_required|menu_key_required|hr_required|president_required|"
    r"manager_required|superadmin_required|require_role|require_permission|require_admin|file_center_admin_required|"
    r"_required$)"
)
INLINE_ROLE = re.compile(
    r"(is_admin|is_super_admin|has_role|user_has_role|current_user\.role|role in|role not in|has_permission|"
    r"can_manage|can_access|require_admin|_guard\(|abort\(403\)|forbidden|menu_key|has_menu_access|is_hr|is_president|"
    r"is_manager\(|_manager_allowed\(|_can_use_all_[a-z_]+\(|_can_export_[a-z_]+\()"
)
INLINE_SCOPE = re.compile(
    r"(scope|can_view|can_edit|can_see|is_owner|owner_id|_owns|visible_to|allowed_employee|manager_of|"
    r"subordinate|\.filter_by\([^)]*(user_id|employee_id|owner|created_by)[^)]*current_user|"
    r"current_user\.id\s*[!=]=|!=\s*current_user\.id|==\s*current_user\.id|ensure_.*access|check_.*access|authorize|"
    r"_own_|_can_operate|_can_manage|is_group_member|participant|_thread_access|can_user_view_[a-z_]+\(|"
    r"can_manage_file_center_[a-z_]+\(|_for_user\()"
)
PUBLIC_ENDPOINT_HINTS = re.compile(
    r"(^static$|login|logout|healthz|readyz|versionz|password|forgot|reset|security_question|captcha|manifest|"
    r"service_worker|offline|robots|favicon|metrics|guest|share|public|mobile_health|auth_|\.index$|^main\.index$|"
    r"^health\.|^main\.kunye$|csrf_refresh|mobile_refresh|^main\.setup_admin$)",
    re.I,
)
PRIORITY_AREAS = {
    "personnel": re.compile(r"personnel|personel|hr_|/hr/|employee", re.I),
    "performance": re.compile(r"performance|performans|scorecard|karne|evaluation", re.I),
    "process_reports": re.compile(r"process|surec|report|rapor", re.I),
    "president_approvals": re.compile(r"president|baskan", re.I),
    "mobile_api": re.compile(r"^/api/mobile|mobile_api", re.I),
    "file_center": re.compile(r"file[-_]center|dosya", re.I),
    "survey": re.compile(r"survey|anket", re.I),
    "ai_knowledge": re.compile(r"ai[-_]agent|knowledge|assistant", re.I),
    "admin_settings": re.compile(r"^/admin|settings|ayarlar", re.I),
}


# Routes reviewed by hand (overnight 2026-09-28): the heuristic cannot see checks that live in
# service helpers. Each entry records the check that was read in the source, or the defect fixed.
_OG = "OBJECT_GATED"
MANUAL_REVIEW: dict[str, tuple[str, str]] = {
    "main.ai_performance_evaluation_summary": (_OG, "FIXED 2026-09-28: payload loader applies can_view_evaluation (was manager-role only)"),
    "main.ai_performance_evaluation_consistency": (_OG, "FIXED 2026-09-28: payload loader applies can_view_evaluation (was manager-role only)"),
    "main.ai_decision_performance_evaluation": (_OG, "payload loader applies can_view_evaluation; route answers 400: AI policy performance/decision_support is undefined"),
    "main.ai_recommendation_status": ("ROLE_GATED", "FIXED 2026-09-28: admin_required + menu_key_required('ai_center') (was login-only)"),
    "main.ai_recommendation_apply": ("ROLE_GATED", "FIXED 2026-09-28: admin_required + menu_key_required('ai_center'); service never applies"),
    "main.ai_decision_evaluation_low_score_process": (_OG, "assert_evaluation_access"),
    "main.ai_decision_evaluation_scorecard_ui": (_OG, "assert_evaluation_access"),
    "main.ai_decision_evaluation_third_supervisor_flow": (_OG, "assert_evaluation_access"),
    "main.ai_decision_evaluation_visibility_check": (_OG, "build_evaluation_visibility_payload -> can_view_evaluation"),
    "main.ai_decision_faz7_person_archive": (_OG, "build_person_archive_payload -> can_view_archive_detail"),
    "main.ai_decision_visible_category_groups_by_period": ("ROLE_GATED", "assert_center_access"),
    "main.ai_decision_performance_category_groups_for_period": ("NEEDS_REVIEW", "answers 400: AI policy performance/category_group_decision_support is undefined (functional defect)"),
    "main.ai_decision_faz8_single_period_scope_check": ("AUTHENTICATED_ONLY", "aggregate period metadata and counts, no person data; POLICY QUESTION: require AI decision center access like faz3?"),
    "main.ai_support_ticket_triage": (_OG, "get_support_ticket_payload: creator, assignee or manager family"),
    "main.ai_feedback": ("NEEDS_REVIEW", "POLICY QUESTION: any user can attach feedback to any AI request log id; returns only the new row id (low impact). 2026-09-29: a missing log now answers 404 and an oversized type 400 (were 500 / orphan row)"),
    "main.announcement_popup_acknowledge": (_OG, "records the current user's own acknowledgement"),
    "main.announcement_popup_dismiss": (_OG, "records the current user's own dismissal"),
    "main.bys360_feedback_success": (_OG, "ticket.created_by_user_id == current_user.id"),
    "main.file_center_chunk_upload_part": (_OG, "upload service scoped by owner_user_id=current_user.id"),
    "main.file_center_chunk_upload_finalize": (_OG, "upload service scoped by owner_user_id=current_user.id"),
    "main.hr_self_service_request_attachment_download": (_OG, "_attachment_in_own_request"),
    "main.performance_feedback_aftercare_detail": (_OG, "meeting access check in handler; edits use _can_edit_meeting"),
    "main.performance_feedback_aftercare_detail_tr": (_OG, "meeting access check in handler; edits use _can_edit_meeting"),
    "main.performance_v2_phase4_assignment": (_OG, "delegates to phase3 workspace: evaluator or admin"),
    "main.performance_v2_phase8_assignment": (_OG, "delegates to phase3 workspace: evaluator or admin"),
    "mobile_api.mobile_b46_communication_thread_detail": (_OG, "_b46_thread_access (participant)"),
    "mobile_api.mobile_b46_communication_send_message": (_OG, "_b46_thread_access (participant)"),
    "mobile_api.mobile_b48_communication_v2_thread_detail": (_OG, "_b48_thread_access (participant)"),
    "mobile_api.mobile_b48_communication_v2_send": (_OG, "_b48_thread_access (participant)"),
    "mobile_api.mobile_kpi_target_progress_v2853": (_OG, "owner_user_id or global scope"),
    "mobile_api.mobile_notification_mark_read_v2864": (_OG, "filter_by(id, user_id=user.id)"),
    "mobile_api.mobile_performance_period_detail": ("AUTHENTICATED_ONLY", "institution-wide period metadata, no person data"),
    "mobile_api.mobile_performance_task_detail": (_OG, "_v2822_can_view_assignment: evaluator or global scope"),
    "mobile_api.mobile_performance_task_score_form": (_OG, "_v2822_can_view_assignment: evaluator or global scope"),
    "mobile_api.mobile_performance_task_score_submit": (_OG, "_v2822_can_view_assignment: evaluator or global scope"),
    "mobile_api.mobile_performance_task_score_action": (_OG, "_v2822_can_view_assignment: evaluator or global scope"),
    "mobile_api.mobile_support_ticket_detail": (_OG, "_can_mobile_view_ticket"),
    "mobile_api.mobile_support_ticket_reply": (_OG, "_can_mobile_reply_ticket"),
    "mobile_api.mobile_survey_detail": (_OG, "survey access check in handler"),
    "main.ai_recommendation_list": ("ROLE_GATED", "FIXED 2026-09-28: admin_required + menu_key_required('ai_center') (was login-only)"),
    "main.ai_recommendation_bulk_apply": ("ROLE_GATED", "FIXED 2026-09-28: admin_required + menu_key_required('ai_center'); service never applies"),
    "health.health_deep": ("PUBLIC_INTENTIONAL", "FIXED 2026-09-28: no longer echoes dependency exception text"),
    "ai_agent.ai_agent_public_healthz": ("PUBLIC_INTENTIONAL", "anonymous smoke check: status, service, version, mode and bridge flags only; was misread as guarded by the ai_agent before_request"),
    "main.support_assign": (_OG, "FIXED 2026-09-29: _can_operate_ticket, i.e. the Phase 13B private-ticket unit scope (was the all-tickets permission only; self-assignment exposed private tickets)"),
    "main.communication_phase3_support_detail": (_OG, "FIXED 2026-09-29: _can_access_ticket on GET and POST: creator, assignee, or a manager within the private-ticket unit scope"),
    "main.communication_phase3_support_assign": (_OG, "FIXED 2026-09-29: is_manager + _can_access_ticket (private-ticket unit scope)"),
    "main.communication_phase3_support_status": (_OG, "FIXED 2026-09-29: is_manager + _can_access_ticket (private-ticket unit scope)"),
    "main.portal_press_news_publish": ("ROLE_GATED", "_portal_press_news_admin_only_allowed: admin roles only"),
    "main.portal_press_news_archive": ("ROLE_GATED", "_portal_press_news_admin_only_allowed: admin roles only"),
    "main.setup_admin": ("PUBLIC_INTENTIONAL", "404 unless explicitly permitted; redirects once any user exists"),
    "main.communication_phase2_surveys": ("ROLE_GATED", "FIXED 2026-09-28: is_manager() like the module's write actions (was menu 'surveys' only)"),
    "main.communication_phase2_survey_detail": ("ROLE_GATED", "FIXED 2026-09-28: is_manager() like the module's write actions (was menu 'surveys' only)"),
    "main.communication_phase2_survey_results": ("ROLE_GATED", "FIXED 2026-09-28: is_manager() like /survey-results (was menu 'surveys' only; exposed free-text answers)"),
    "main.communication_phase2_bulletin_history": ("NEEDS_REVIEW", "POLICY QUESTION: draft bulletin titles are visible to every 'announcements' menu holder here and in the faz1 bulletin list"),
    "main.communication_phase4_survey_analytics": ("NEEDS_REVIEW", "POLICY QUESTION: per-survey completion metrics (incl. drafts) under menu 'surveys', which employees hold"),
    "main.communication_phase3_survey_take": (_OG, "get_survey_for_user(survey_id, current_user)"),
    "main.communication_phase4_report_detail": ("ROLE_GATED", "menu 'reports' (manager reporting menu); module shows its dashboard to the same audience"),
    "main.file_center_download": (_OG, "_can_manage_file + can_download_file"),
    "main.file_center_delete": (_OG, "_can_manage_file"),
    "main.file_center_create_guest_link": (_OG, "can_create_guest_links + _can_manage_file"),
    "main.file_center_revoke_guest_link": (_OG, "_can_manage_file(link.file)"),
    "main.performance_evaluate": (_OG, "_can_access_assignment_for_actor"),
    "main.sp1_kpi_target_edit": (_OG, "_can_manage_targets + scoped lookup"),
    "ai_agent.ag5_knowledge_toggle": ("ROLE_GATED", "can_manage_ai_knowledge"),
    "ai_agent.ag5_knowledge_delete": ("ROLE_GATED", "can_manage_ai_knowledge"),
    "main.performance_feedback_followup_quick_update": (_OG, "scoped action lookup (is_admin / owner)"),
    "main.manager_feedback_request_schedule_preview": (_OG, "admin or allowed manager ids"),
    "main.survey_take": (_OG, "survey access check in handler"),
    "main.survey_edit": ("ROLE_GATED", "_survey_manager_allowed"),
    "main.survey_delete": ("ROLE_GATED", "_survey_manager_allowed"),
    "main.support_comment": (_OG, "_can_operate_ticket"),
    "main.support_status": (_OG, "FIXED 2026-09-29: _can_operate_ticket, i.e. the Phase 13B private-ticket unit scope (was _can_use_all_support_view only)"),
    "main.portal_post_delete": (_OG, "can_user_delete_post"),
    "main.portal_post_moderate": ("ROLE_GATED", "can_manage_portal"),
    "main.portal_group_detail": (_OG, "is_group_member or can_manage_portal"),
    "main.hr_leave_update_status": (_OG, "FIXED 2026-09-28: record person must be in build_user_scope_context(current_user, 'all') (was any record by id)"),
    "main.hr_leave_delete": (_OG, "FIXED 2026-09-28: record person must be in build_user_scope_context(current_user, 'all') (was any record by id)"),
    "main.hr_attendance_update_status": (_OG, "FIXED 2026-09-28: record person must be in build_user_scope_context(current_user, 'all') (was any record by id)"),
    "main.hr_attendance_delete": (_OG, "FIXED 2026-09-28: record person must be in build_user_scope_context(current_user, 'all') (was any record by id)"),
    "main.hr_delegation_update_status": (_OG, "FIXED 2026-09-28: record person must be in build_user_scope_context(current_user, 'all') (was any record by id)"),
    "main.hr_delegation_delete": (_OG, "FIXED 2026-09-28: record person must be in build_user_scope_context(current_user, 'all') (was any record by id)"),
    "main.announcement_popup_manage": ('NEEDS_REVIEW', "HIGH POLICY QUESTION: popup announcement management has no gate beyond menu 'announcements', which static defaults grant to 'personel'; bulletins (is_manager) and portal (can_publish_announcement) both exclude employees"),
    "main.announcement_popup_new": ('NEEDS_REVIEW', "HIGH POLICY QUESTION: popup announcement management has no gate beyond menu 'announcements', which static defaults grant to 'personel'; bulletins (is_manager) and portal (can_publish_announcement) both exclude employees"),
    "main.announcement_popup_edit": ('NEEDS_REVIEW', "HIGH POLICY QUESTION: popup announcement management has no gate beyond menu 'announcements', which static defaults grant to 'personel'; bulletins (is_manager) and portal (can_publish_announcement) both exclude employees"),
    "main.announcement_popup_toggle": ('NEEDS_REVIEW', "HIGH POLICY QUESTION: popup announcement management has no gate beyond menu 'announcements', which static defaults grant to 'personel'; bulletins (is_manager) and portal (can_publish_announcement) both exclude employees"),
    "main.announcement_popup_report": ('NEEDS_REVIEW', "HIGH POLICY QUESTION: popup announcement management has no gate beyond menu 'announcements', which static defaults grant to 'personel'; bulletins (is_manager) and portal (can_publish_announcement) both exclude employees"),
    "main.announcement_popup_report_csv": ('NEEDS_REVIEW', "HIGH POLICY QUESTION: popup announcement management has no gate beyond menu 'announcements', which static defaults grant to 'personel'; bulletins (is_manager) and portal (can_publish_announcement) both exclude employees"),
    "main.messages_thread": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_thread_activity": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_thread_live": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_thread_typing": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_react": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_comment": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_send": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_mark_read": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_toggle_mute": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_toggle_archive": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_toggle_pin": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_edit": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.messages_delete": (_OG, "participant of the thread (service participant_for_thread / MessageThreadParticipant, or *_for_user(current_user.id))"),
    "main.notifications_mark_read": (_OG, "filter_by(id, user_id=current_user.id)"),
    "main.notifications_mark_unread": (_OG, "filter_by(id, user_id=current_user.id)"),
    "main.communication_phase1_bulletin_acknowledge": (_OG, "records the current user's own acknowledgement"),
    "main.feedback_campaign_detail": (_OG, "submit: user_can_see_campaign; GET renders only the campaign questions (low)"),
    "main.feedback_campaign_status": ("ROLE_GATED", "manager_required + menu 'feedback_admin'; POLICY QUESTION: any manager can change any campaign"),
    "main.feedback_campaign_publish": ("ROLE_GATED", "manager_required + menu 'feedback_admin'; POLICY QUESTION: any manager can publish any campaign"),
    "main.announcement_popup_target_count": ("NEEDS_REVIEW", "part of the popup management surface (see announcement_popup_manage)"),
}

def _app():
    os.environ.update({
        "APP_ENV": "testing", "SECRET_KEY": "authorization-matrix-test-secret-0000",
        "DATABASE_URL": "sqlite:///:memory:", "SCHEDULER_ENABLED": "false", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
    })
    sys.path.insert(0, str(REPO))
    import logging

    logging.disable(logging.CRITICAL)
    from app import create_app

    return create_app()


_AST_CACHE: dict[str, ast.Module] = {}


def _function_node(func) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | None, str, int]:
    code = getattr(func, "__code__", None)
    if code is None:
        return None, "", 0
    path = code.co_filename
    if path not in _AST_CACHE:
        try:
            _AST_CACHE[path] = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, ValueError):
            return None, path, code.co_firstlineno
    for node in ast.walk(_AST_CACHE[path]):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == func.__name__:
            first = min([d.lineno for d in node.decorator_list] + [node.lineno])
            if code.co_firstlineno in (first, node.lineno):
                return node, path, node.lineno
    return None, path, code.co_firstlineno


def _wrapper_names(view) -> list[str]:
    """Names of the decorators/wrappers around a view, including ones applied via add_url_rule."""
    names = []
    func = view
    while func is not None and hasattr(func, "__wrapped__"):
        # functools.wraps copies __qualname__ from the view; the code object keeps the wrapper's own name.
        code = getattr(func, "__code__", None)
        qualname = getattr(code, "co_qualname", "") if code else ""
        names.append(qualname.split(".<locals>")[0].split(".")[-1])
        func = func.__wrapped__
    return names


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    text = ast.unparse(target)
    return text.split(".")[-1]


def _body_source(node) -> str:
    return "\n".join(ast.unparse(stmt) for stmt in node.body)


def _test_index() -> dict[str, str]:
    return {str(p.relative_to(REPO)).replace("\\", "/"): p.read_text(encoding="utf-8-sig", errors="ignore")
            for p in (REPO / "tests").rglob("*.py")}


def build(app) -> dict:
    tests = _test_index()
    admin_guard_paths = _admin_guard_predicate()
    rows = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        methods = sorted(m for m in (rule.methods or set()) if m not in {"HEAD", "OPTIONS"})
        view = app.view_functions.get(rule.endpoint)
        original = inspect.unwrap(view) if view else None
        node, path, line = _function_node(original) if original else (None, "", 0)
        decorators = [_decorator_name(d) for d in node.decorator_list] if node else []
        decorators = [d for d in decorators if d not in {"route", "get", "post", "put", "delete", "patch"}]
        decorators = list(dict.fromkeys(decorators + (_wrapper_names(view) if view else [])))
        body = _body_source(node) if node else ""
        blueprint = rule.endpoint.rsplit(".", 1)[0] if "." in rule.endpoint else "app"
        object_params = sorted(a for a in rule.arguments if a == "id" or a.endswith("_id") or a in {"token", "key", "uuid"})
        static_prefix = rule.rule.split("<", 1)[0].rstrip("/") or "/"
        test_files = sorted(f for f, text in tests.items()
                            if (len(static_prefix) > 3 and static_prefix in text) or f"'{rule.endpoint}'" in text
                            or f'"{rule.endpoint}"' in text)
        authn = sorted({d for d in decorators if d in AUTH_DECORATORS})
        role = sorted({d for d in decorators if (ROLE_DECORATORS.search(d) or d in AUTHENTICATING_ROLE_DECORATORS)
                       and d not in AUTH_DECORATORS})
        inline_role = sorted(set(INLINE_ROLE.findall(body))) if body else []
        inline_scope = sorted({m[0] if isinstance(m, tuple) else m for m in INLINE_SCOPE.findall(body)}) if body else []
        guards = []
        if admin_guard_paths(rule.rule):
            guards.append("app.admin_path_guard(authenticated + admin family role)")
        # The ai_agent blueprint's before_request hooks return early for anonymous users, so
        # they are not an authentication guard; hierarchy_governance's hook is @login_required.
        if blueprint in {"hierarchy_governance"}:
            guards.append("hierarchy_governance_bp.before_request")
        authenticated = (bool(authn) or bool(guards) or "require_mobile_user" in body
                         or bool(set(decorators) & AUTHENTICATING_ROLE_DECORATORS))
        if not authenticated and (_BODY_AUTH_CHECK.search(body) or rule.endpoint in AUTHENTICATED_BY_HELPER):
            authenticated = True
        public_hint = PUBLIC_ENDPOINT_HINTS.search(rule.endpoint) or PUBLIC_ENDPOINT_HINTS.search(rule.rule)
        if rule.endpoint == "static" or (not authenticated and public_hint):
            classification = "PUBLIC_INTENTIONAL"
        elif not authenticated:
            classification = "NEEDS_REVIEW"
        elif object_params and inline_scope:
            classification = "OBJECT_GATED"
        elif "admin_required" in decorators or any("admin" in g for g in guards):
            classification = "ROLE_GATED"  # admin family sees every record by policy
        elif role or inline_role:
            classification = "ROLE_GATED" if not object_params else "NEEDS_REVIEW"
        else:
            classification = "AUTHENTICATED_ONLY" if not object_params else "NEEDS_REVIEW"
        heuristic = classification
        review = MANUAL_REVIEW.get(rule.endpoint)
        if review:
            classification = review[0]
        areas = sorted(k for k, rx in PRIORITY_AREAS.items() if rx.search(rule.rule) or rx.search(rule.endpoint))
        rows.append({
            "blueprint": blueprint, "endpoint": rule.endpoint, "url": rule.rule, "methods": methods,
            "view": f"{str(Path(path).resolve().relative_to(REPO)).replace(chr(92), '/')}:{line}" if path and Path(path).resolve().is_relative_to(REPO) else path,
            "authenticated": authenticated, "decorators": decorators, "app_or_blueprint_guards": guards,
            "role_decorators": role, "inline_role_checks": inline_role, "object_params": object_params,
            "inline_scope_checks": inline_scope, "areas": areas, "test_files": len(test_files),
            "heuristic_classification": heuristic, "classification": classification,
            "manual_review": review[1] if review else None,
        })
    summary = {
        "routes": len(rows),
        "by_classification": dict(sorted(Counter(r["classification"] for r in rows).items())),
        "needs_review_by_area": dict(sorted(Counter(a for r in rows if r["classification"] == "NEEDS_REVIEW" for a in r["areas"] or ["other"]).items())),
        "manually_reviewed_routes": sum(1 for r in rows if r["manual_review"]),
        "fixed_2026_09_28": sorted(r["endpoint"] for r in rows if (r["manual_review"] or "").startswith("FIXED")),
        "routes_with_object_params": sum(1 for r in rows if r["object_params"]),
        "routes_without_test_reference": sum(1 for r in rows if not r["test_files"]),
        "method": "Flask url_map + source AST of each view (decorators, body calls); heuristic, conservative",
    }
    return {"matrix": "BYS360_AUTHORIZATION_MATRIX_V1", "summary": summary, "routes": rows}


def _admin_guard_predicate():
    from app.bootstrap import operational_guards

    return getattr(operational_guards, "_is_admin_path", lambda _p: False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    app = _app()
    with app.app_context():
        result = build(app)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result["summary"], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
