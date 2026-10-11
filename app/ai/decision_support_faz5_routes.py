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
from app.services.ai_decision.scorecard_ui_integration import (
    build_scorecard_bulk_payload,
    build_scorecard_decision_panel,
)

if TYPE_CHECKING:
    from app.services.ai_decision.visibility_scope import AIDecisionVisibilityScope

logger = logging.getLogger(__name__)

"""BYS360 AI Karar Destek Faz 5 route ekleri.

Mevcut app.ai.routes dosyasını ezmeden ana blueprint üzerine Faz 5 uçlarını
kaydeder. Uçlar karne ve puanlama ekranları için temiz karar destek özeti
döndürür.

BYS360_AI_DECISION_FAZ5_ROUTES
"""

try:
    from app.services.ai_decision.permission_guard import (
        assert_center_access,
        assert_evaluation_access,
        assert_health_access,
    )
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz5_routes.py | line=30")

    # BYS360 DEFECT AR: bkz. decision_support_faz4_routes.py ayni not --
    # fail-open yerine fail-closed PermissionError firlatilir
    # (_run_faz5_json bunu yakalayip 403 donuyor).
    def assert_center_access(user: Any) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu sayfaya erişim yetkiniz bulunmamaktadır.")

    def assert_health_access(user: Any) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu sayfaya erişim yetkiniz bulunmamaktadır.")

    def assert_evaluation_access(
        user: Any, evaluation: Any, *, allow_own_published: bool = True
    ) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu performans karar destek kaydına erişim yetkiniz bulunmamaktadır.")

ResponseBuilder = Callable[..., dict[str, Any]]

def _run_faz5_json(builder: ResponseBuilder, *args: Any) -> tuple[Any, int]:
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
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz5_routes.py | line=52 | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Karne karar destek kontrolünde beklenmeyen bir hata oluştu."}), 500

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
                    'require_general_comment_below_70', 'require_general_comment_above_90'
                 )) OR (module_key = 'ai_decision' AND setting_key IN (
                    'faz5_low_score_limit', 'faz5_high_score_limit',
                    'faz5_show_technical_terms', 'faz5_require_low_score_explanation',
                    'faz5_require_high_score_explanation'
                 ))
                """
            )
        ).mappings().all()
        for row in rows:
            settings[f"{row['module_key']}.{row['setting_key']}"] = row.get("value_text")
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz5_routes.py | line=78")
        return settings
    return settings

@main_bp.route("/ai/decision-support/faz5/health")
@login_required
def ai_decision_faz5_health():
    def _health() -> dict[str, Any]:
        assert_health_access(current_user)
        return {
            "ok": True,
            "module": "AI Karar Destek - Karne ve Puanlama Ekranı",
            "settings": _load_settings(),
            "screen_principles": [
                "Karne ekranında teknik ifade gösterilmez.",
                "70 altı sonuçlarda üst onay ve yayın kilidi korunur.",
                "Amir görüşleri ve kriter puanları ayrı okunur kartlarda sunulur.",
                "Karar destek çıktısı nihai idari karar değildir.",
            ],
            "marker": "BYS360_AI_DECISION_FAZ5_HEALTH_OK",
        }
    return _run_faz5_json(_health)

@main_bp.route("/ai/decision-support/performance/evaluation/<int:evaluation_id>/scorecard-ui")
@login_required
def ai_decision_evaluation_scorecard_ui(evaluation_id: int):
    def _payload(target_id: int) -> dict[str, Any]:
        evaluation = db.session.get(PerformanceEvaluation, int(target_id))
        if evaluation is None:
            raise LookupError("Performans değerlendirme kaydı bulunamadı.")
        assert_evaluation_access(current_user, evaluation)
        return build_scorecard_decision_panel(evaluation, settings=_load_settings())
    return _run_faz5_json(_payload, evaluation_id)

@main_bp.route("/ai/decision-support/performance/scorecard-ui/summary")
@login_required
def ai_decision_scorecard_ui_summary():
    def _summary() -> dict[str, Any]:
        assert_center_access(current_user)
        query = PerformanceEvaluation.query.order_by(PerformanceEvaluation.id.desc()).limit(250)
        return build_scorecard_bulk_payload(query.all(), settings=_load_settings())
    return _run_faz5_json(_summary)
