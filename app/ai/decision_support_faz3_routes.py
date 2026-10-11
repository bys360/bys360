from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from flask import jsonify
from flask_login import current_user, login_required

from app.extensions import db
from app.models import PerformanceEvaluation
from app.route_registry import main_bp
from app.route_support import safe_db_rollback
from app.services.ai_decision.category_visibility_integration import (
    build_visible_category_group_summary,
)
from app.services.ai_decision.permission_guard import (
    AIDecisionPermissionDenied,
    assert_center_access,
    assert_health_access,
    build_ai_decision_visibility_context,
    build_evaluation_visibility_payload,
)

logger = logging.getLogger(__name__)

"""BYS360 AI Karar Destek Faz 3 route ekleri.

Bu modül app.ai.routes içine tek satırlık kayıt importu ile bağlanır. Mevcut
routes.py dosyasını ezmeden Faz 3 uçlarını main_bp üzerine kaydeder.

BYS360_AI_DECISION_FAZ3_ROUTES
"""

ResponseBuilder = Callable[..., dict[str, Any]]


def _run_faz3_json(builder: ResponseBuilder, *args: Any, commit: bool = False) -> tuple[Any, int]:
    try:
        payload = builder(*args)
        if commit:
            db.session.commit()
        return jsonify(payload), 200
    except AIDecisionPermissionDenied as exc:
        safe_db_rollback()
        return jsonify({"ok": False, "error": exc.message}), 403
    except PermissionError as exc:
        safe_db_rollback()
        return jsonify({"ok": False, "error": str(exc) or "Bu sayfaya erişim yetkiniz bulunmamaktadır."}), 403
    except LookupError as exc:
        logger.exception("BYS360 AI karar destek: beklenmeyen LookupError | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Kayıt bulunamadı."}), 404
    except ValueError as exc:
        logger.exception("BYS360 AI karar destek: beklenmeyen ValueError | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Geçersiz istek parametresi."}), 400
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz3_routes.py | line=51 | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Karar destek görünürlük kontrolünde beklenmeyen bir hata oluştu."}), 500


@main_bp.route("/ai/decision-support/faz3/health")
@login_required
def ai_decision_faz3_health():
    def _health() -> dict[str, Any]:
        scope = assert_health_access(current_user)
        return {
            "ok": True,
            "phase": "Faz 3",
            "module": "AI Karar Destek - Görünürlük ve Yetki Sınırları",
            "marker": "BYS360_AI_DECISION_FAZ3_HEALTH_OK",
            "scope": scope.to_dict(),
        }

    return _run_faz3_json(_health)


@main_bp.route("/ai/decision-support/visibility/my-scope")
@login_required
def ai_decision_my_visibility_scope():
    return _run_faz3_json(build_ai_decision_visibility_context, current_user)


@main_bp.route("/ai/decision-support/performance/evaluation/<int:evaluation_id>/visibility-check")
@login_required
def ai_decision_evaluation_visibility_check(evaluation_id: int):
    def _check(target_id: int) -> dict[str, Any]:
        evaluation = db.session.get(PerformanceEvaluation, int(target_id))
        if evaluation is None:
            raise LookupError("Performans değerlendirme kaydı bulunamadı.")
        return build_evaluation_visibility_payload(current_user, evaluation)

    return _run_faz3_json(_check, evaluation_id)


@main_bp.route("/ai/decision-support/performance/visible-category-groups")
@login_required
def ai_decision_visible_category_groups():
    def _summary() -> dict[str, Any]:
        assert_center_access(current_user)
        return build_visible_category_group_summary(acting_user=current_user, period_id=None)

    return _run_faz3_json(_summary)


@main_bp.route("/ai/decision-support/performance/visible-category-groups/<int:period_id>")
@login_required
def ai_decision_visible_category_groups_by_period(period_id: int):
    def _summary(target_period_id: int) -> dict[str, Any]:
        assert_center_access(current_user)
        return build_visible_category_group_summary(acting_user=current_user, period_id=int(target_period_id))

    return _run_faz3_json(_summary, period_id)
