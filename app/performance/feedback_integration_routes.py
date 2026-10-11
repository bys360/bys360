from __future__ import annotations

import logging

from flask import render_template, request
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.services.performance.feedback_integration import build_integration_context

logger = logging.getLogger(__name__)


def _int_or_none(value):
    try:
        return int(value) if value not in (None, "", "None") else None
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/performance/feedback_integration_routes.py | line=16")
        return None


def _role() -> str:
    return (getattr(current_user, "role", "") or "").strip().lower()


def _is_admin() -> bool:
    # F06b (D2): the technical roles are not administrators of personal performance data.
    return bool(getattr(current_user, "is_admin", False) or _role() in {"admin", "super_admin"})


def _is_superuser() -> bool:
    return bool(getattr(current_user, "is_superuser", False))


@main_bp.route("/performance/feedback-integration", endpoint="performance_feedback_integration")
@main_bp.route("/performans/gorusme-entegrasyonu", endpoint="performance_feedback_integration_tr")
@login_required
def performance_feedback_integration():
    ctx = build_integration_context(
        current_user_id=getattr(current_user, "id", None),
        current_user_role=_role(),
        is_admin=_is_admin(),
        is_superuser=_is_superuser(),
        employee_id=_int_or_none(request.args.get("employee_id")),
        period_id=_int_or_none(request.args.get("period_id")),
    )
    status_code = 403 if ctx.get("access_denied") else 200
    return render_template("performance/feedback_integration_phase3.html", **ctx), status_code
