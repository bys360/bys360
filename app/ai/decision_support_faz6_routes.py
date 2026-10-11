from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flask import jsonify
from flask_login import current_user, login_required

from app.extensions import db
from app.models import PerformanceEvaluation
from app.route_registry import main_bp
from app.route_support import safe_db_rollback
from app.services.ai_decision.low_performance_approval_integration import (
    build_low_performance_approval_payload,
    build_low_performance_bulk_summary,
)

if TYPE_CHECKING:
    from app.services.ai_decision.visibility_scope import AIDecisionVisibilityScope

logger = logging.getLogger(__name__)

"""BYS360 AI Karar Destek Faz 6 route ekleri.

Başkan/Üst Onay ve 70 altı düşük performans süreçlerini karar destek merkezi
üzerinden güvenli JSON çıktısı olarak sunar.

BYS360_AI_DECISION_FAZ6_ROUTES
"""

try:
    from app.services.ai_decision.permission_guard import (
        assert_center_access,
        assert_evaluation_access,
        assert_health_access,
    )
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz6_routes.py | line=29")

    # BYS360 DEFECT AR: bkz. decision_support_faz4_routes.py ayni not --
    # fail-open yerine fail-closed PermissionError firlatilir
    # (_run_faz6_json bunu yakalayip 403 donuyor).
    def assert_center_access(user: Any) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu sayfaya erişim yetkiniz bulunmamaktadır.")

    def assert_health_access(user: Any) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu sayfaya erişim yetkiniz bulunmamaktadır.")

    def assert_evaluation_access(
        user: Any, evaluation: Any, *, allow_own_published: bool = True
    ) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu performans karar destek kaydına erişim yetkiniz bulunmamaktadır.")

ResponseBuilder = Callable[..., dict[str, Any]]


def _run_faz6_json(builder: ResponseBuilder, *args: Any) -> tuple[Any, int]:
    try:
        payload = builder(*args)
        return jsonify(payload), 200
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
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz6_routes.py | line=52 | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Düşük performans karar destek kontrolünde beklenmeyen bir hata oluştu."}), 500


def _load_settings() -> dict[str, Any]:
    settings: dict[str, Any] = {}
    try:
        from sqlalchemy import text
        rows = db.session.execute(
            text(
                """
                SELECT module_key, setting_key, value_text
                  FROM module_settings
                 WHERE (module_key = 'performance' AND setting_key IN (
                    'low_score_limit', 'high_score_limit',
                    'require_general_comment_below_70'
                 )) OR (module_key = 'performance_flow' AND setting_key IN (
                    'low_score_requires_president_approval', 'low_score_publish_lock',
                    'low_score_direct_president_approval', 'require_general_comment_below_70'
                 )) OR (module_key = 'ai_decision' AND setting_key IN (
                    'faz6_low_score_limit', 'faz6_high_score_limit',
                    'faz6_direct_upper_approval', 'faz6_require_low_score_general_comment',
                    'faz6_publish_lock_until_upper_approval', 'faz6_create_first_low_warning',
                    'faz6_create_repeat_low_process', 'faz6_hr_admin_observer_mode'
                 ))
                """
            )
        ).mappings().all()
        for row in rows:
            settings[f"{row['module_key']}.{row['setting_key']}"] = row.get("value_text")
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz6_routes.py | line=83")
        return settings
    return settings


def _prior_low_count_same_year(evaluation: Any) -> int:
    try:
        getattr(evaluation, "final_score", None) or getattr(evaluation, "weighted_score", None) or getattr(evaluation, "score", None)
        user_id = getattr(evaluation, "user_id", None) or getattr(evaluation, "personnel_id", None)
        if user_id is None:
            return 0
        current_id = getattr(evaluation, "id", None)
        query = PerformanceEvaluation.query.filter(PerformanceEvaluation.id != current_id)
        if hasattr(PerformanceEvaluation, "user_id"):
            query = query.filter(PerformanceEvaluation.user_id == user_id)
        elif hasattr(PerformanceEvaluation, "personnel_id"):
            query = query.filter(PerformanceEvaluation.personnel_id == user_id)
        if hasattr(PerformanceEvaluation, "final_score"):
            query = query.filter(PerformanceEvaluation.final_score < 70)
        elif hasattr(PerformanceEvaluation, "score"):
            query = query.filter(PerformanceEvaluation.score < 70)
        else:
            return 0
        return int(query.count())
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz6_routes.py | line=108")
        return 0


@main_bp.route("/ai/decision-support/faz6/health")
@login_required
def ai_decision_faz6_health():
    def _health() -> dict[str, Any]:
        assert_health_access(current_user)
        return {
            "ok": True,
            "module": "AI Karar Destek - Başkan/Üst Onay ve Düşük Performans Süreci",
            "settings": _load_settings(),
            "process_principles": [
                "70 altı sonuçlar Başkan/Üst Onay tamamlanmadan personele açılmaz.",
                "İlk düşük performans kaydı uyarı süreciyle personel geçmişine bağlanır.",
                "Tekrarlayan düşük performans sistem tarafından idari süreç sinyali olarak işaretlenir.",
                "Sistem otomatik işten çıkarma yapmaz; yetkili onay akışını görünür kılar.",
            ],
            "marker": "BYS360_AI_DECISION_FAZ6_HEALTH_OK",
        }
    return _run_faz6_json(_health)


@main_bp.route("/ai/decision-support/performance/evaluation/<int:evaluation_id>/low-score-process")
@login_required
def ai_decision_evaluation_low_score_process(evaluation_id: int):
    def _payload(target_id: int) -> dict[str, Any]:
        evaluation = db.session.get(PerformanceEvaluation, int(target_id))
        if evaluation is None:
            raise LookupError("Performans değerlendirme kaydı bulunamadı.")
        assert_evaluation_access(current_user, evaluation)
        return build_low_performance_approval_payload(
            evaluation,
            prior_low_count_same_year=_prior_low_count_same_year(evaluation),
            settings=_load_settings(),
        )
    return _run_faz6_json(_payload, evaluation_id)


@main_bp.route("/ai/decision-support/performance/low-score-processes")
@login_required
def ai_decision_low_score_processes_summary():
    def _summary() -> dict[str, Any]:
        assert_center_access(current_user)
        query = PerformanceEvaluation.query.order_by(PerformanceEvaluation.id.desc()).limit(300)
        return build_low_performance_bulk_summary(query.all(), settings=_load_settings())
    return _run_faz6_json(_summary)
