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
from app.services.ai_decision.third_supervisor_integration import (
    build_third_supervisor_bulk_payload,
    build_third_supervisor_decision_payload,
)

if TYPE_CHECKING:
    from app.services.ai_decision.visibility_scope import AIDecisionVisibilityScope

logger = logging.getLogger(__name__)

"""BYS360 AI Karar Destek Faz 4 route ekleri.

Bu modül mevcut app.ai.routes dosyasını ezmeden main_bp üzerine Faz 4 uçlarını
kaydeder. Uçlar 3. amir opsiyonelliği ve akış temizliği için güvenli karar
destek çıktısı döndürür.

BYS360_AI_DECISION_FAZ4_ROUTES
"""

try:
    from app.services.ai_decision.permission_guard import (
        assert_center_access,
        assert_evaluation_access,
        assert_health_access,
    )
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz4_routes.py | line=30")

    # BYS360 DEFECT AR: bu yedek fonksiyonlar eskiden sessizce True donuyordu
    # (fail-open) -- permission_guard importu herhangi bir nedenle
    # basarisiz olursa (gelecekte dairesel import/sozdizimi hatasi vb.),
    # Faz 4 AI Karar Destek uclari HERHANGI bir dogrulanmis kullaniciya
    # AIDecisionVisibilityScope tabanli kapsamlama olmadan acik kalirdi.
    # Cagiranlarin hepsi zaten yalnizca yan etki (istisna firlatma) icin
    # cagiriyor, donus degerini kullanmiyor; fail-closed PermissionError
    # firlatmak dogru yedek davranistir (_run_faz4_json zaten PermissionError'i
    # yakalayip 403 donuyor).
    def assert_center_access(user: Any) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu sayfaya erişim yetkiniz bulunmamaktadır.")

    def assert_health_access(user: Any) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu sayfaya erişim yetkiniz bulunmamaktadır.")

    def assert_evaluation_access(
        user: Any, evaluation: Any, *, allow_own_published: bool = True
    ) -> AIDecisionVisibilityScope:
        raise PermissionError("Bu performans karar destek kaydına erişim yetkiniz bulunmamaktadır.")


ResponseBuilder = Callable[..., dict[str, Any]]


def _run_faz4_json(builder: ResponseBuilder, *args: Any) -> tuple[Any, int]:
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
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz4_routes.py | line=54 | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "3. amir karar destek kontrolünde beklenmeyen bir hata oluştu."}), 500


def _load_settings() -> dict[str, Any]:
    """Modül ayarlarını güvenli biçimde okur; tablo yapısı farklıysa varsayılan kullanılır."""
    settings: dict[str, Any] = {}
    try:
        from sqlalchemy import text
        rows = db.session.execute(
            text(
                """
                SELECT module_key, setting_key, value_text
                  FROM module_settings
                 WHERE (module_key = 'performance' AND setting_key IN (
                    'third_supervisor_enabled', 'third_supervisor_mode',
                    'third_supervisor_show_column', 'third_supervisor_weight_enabled',
                    'default_first_supervisor_weight', 'default_second_supervisor_weight',
                    'default_third_supervisor_weight'
                 )) OR (module_key = 'ai_decision' AND setting_key IN (
                    'faz4_synthetic_task_guard_enabled', 'faz4_empty_column_guard_enabled'
                 ))
                """
            )
        ).mappings().all()
        for row in rows:
            settings[f"{row['module_key']}.{row['setting_key']}"] = row.get("value_text")
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz4_routes.py | line=82")
        return settings
    return settings


@main_bp.route("/ai/decision-support/faz4/health")
@login_required
def ai_decision_faz4_health():
    def _health() -> dict[str, Any]:
        assert_health_access(current_user)
        return {
            "ok": True,
            "phase": "Faz 4",
            "module": "AI Karar Destek - 3. Amir Opsiyonelliği ve Akış Temizliği",
            "settings": _load_settings(),
            "marker": "BYS360_AI_DECISION_FAZ4_HEALTH_OK",
        }

    return _run_faz4_json(_health)


@main_bp.route("/ai/decision-support/performance/evaluation/<int:evaluation_id>/third-supervisor-flow")
@login_required
def ai_decision_evaluation_third_supervisor_flow(evaluation_id: int):
    def _payload(target_id: int) -> dict[str, Any]:
        evaluation = db.session.get(PerformanceEvaluation, int(target_id))
        if evaluation is None:
            raise LookupError("Performans değerlendirme kaydı bulunamadı.")
        assert_evaluation_access(current_user, evaluation)
        return build_third_supervisor_decision_payload(evaluation, settings=_load_settings())

    return _run_faz4_json(_payload, evaluation_id)


@main_bp.route("/ai/decision-support/performance/third-supervisor-flow/summary")
@login_required
def ai_decision_third_supervisor_flow_summary():
    def _summary() -> dict[str, Any]:
        assert_center_access(current_user)
        query = PerformanceEvaluation.query.order_by(PerformanceEvaluation.id.desc()).limit(250)
        return build_third_supervisor_bulk_payload(query.all(), settings=_load_settings())

    return _run_faz4_json(_summary)
