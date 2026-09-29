from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from app.extensions import db
from app.route_registry import main_bp
from app.route_support import admin_required, menu_key_required, safe_db_rollback
from app.services.ai import (
    build_dashboard_brief_response,
    build_hr_leave_brief_response,
    build_performance_consistency_response,
    build_performance_summary_response,
    build_support_ticket_triage_response,
    log_ai_feedback,
    mark_recommendation,
)
from app.services.ai.client import get_provider_snapshot
from app.services.ai.guardrails import (
    AIAccessDenied,
    AIInputError,
    AIResourceNotFound,
    AIServiceDisabled,
)
from app.services.ai.recommendation_actions import (
    apply_recommendation,
    bulk_apply_recommendations,
    list_target_recommendation_payloads,
)

logger = logging.getLogger(__name__)

ResponseBuilder = Callable[..., dict[str, Any]]


def _request_value(name: str) -> str | None:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return payload.get(name)
    return request.form.get(name)


def _request_values(name: str) -> list[str]:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        values = payload.get(name) or []
        if isinstance(values, (list, tuple)):
            return [str(item) for item in values]
        return [str(values)] if values else []
    return request.form.getlist(name)


def _run_json_service(builder: ResponseBuilder, *args: Any, commit: bool = True) -> tuple[Any, int]:
    try:
        payload = builder(*args)
        if commit:
            db.session.commit()
        return jsonify(payload), 200
    except AIServiceDisabled as exc:
        safe_db_rollback()
        return jsonify({"ok": False, "error": str(exc)}), 503
    except AIAccessDenied as exc:
        safe_db_rollback()
        return jsonify({"ok": False, "error": str(exc)}), 403
    except PermissionError as exc:
        logger.exception("BYS360 AI: beklenmeyen PermissionError | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Bu işlem için yetkiniz bulunmamaktadır."}), 403
    except AIResourceNotFound as exc:
        safe_db_rollback()
        return jsonify({"ok": False, "error": str(exc)}), 404
    except (AIInputError, ValueError) as exc:
        if not isinstance(exc, AIInputError):
            logger.exception("BYS360 AI: beklenmeyen ValueError | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": str(exc) if isinstance(exc, AIInputError) else "Geçersiz istek parametresi."}), 400
    except LookupError as exc:
        logger.exception("BYS360 AI: beklenmeyen LookupError | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Kayıt bulunamadı."}), 404
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 AI işleminde beklenmeyen hata | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "AI işleminde beklenmeyen bir hata oluştu."}), 500


# Güncel canlı AI uçları: performans, dashboard/genel, personel izin-vekalet,
# yardım merkezi ve ortak öneri/geri bildirim akışı. Eğitim, Strateji, Depo ve
# Portal uçları canlı omurga dışında bırakılmıştır.

@main_bp.route("/ai/performance/evaluation/<int:evaluation_id>/summary")
@login_required
def ai_performance_evaluation_summary(evaluation_id: int):
    return _run_json_service(build_performance_summary_response, evaluation_id)


@main_bp.route("/ai/performance/evaluation/<int:evaluation_id>/consistency")
@login_required
def ai_performance_evaluation_consistency(evaluation_id: int):
    return _run_json_service(build_performance_consistency_response, evaluation_id)


@main_bp.route("/ai/dashboard/brief")
@login_required
def ai_dashboard_brief():
    return _run_json_service(build_dashboard_brief_response, commit=True)


@main_bp.route("/ai/hr/leave/brief")
@login_required
def ai_hr_leave_brief():
    return _run_json_service(build_hr_leave_brief_response, commit=True)


@main_bp.route("/ai/support/ticket/<int:ticket_id>/triage")
@login_required
def ai_support_ticket_triage(ticket_id: int):
    return _run_json_service(build_support_ticket_triage_response, ticket_id)


# Reviewing AI recommendations is an admin function (same gate as /admin/ai-recommendations).
@main_bp.route("/ai/recommendations/<int:recommendation_id>/status", methods=["POST"])
@login_required
@admin_required
@menu_key_required("ai_center")
def ai_recommendation_status(recommendation_id: int):
    def _update_status(rid: int) -> dict[str, Any]:
        status = (_request_value("status") or "").strip().lower()
        recommendation = mark_recommendation(
            rid,
            status=status,
            reviewed_by_user_id=getattr(current_user, "id", None),
        )
        return {"ok": True, "data": {"id": recommendation.id, "status": recommendation.status}}

    return _run_json_service(_update_status, recommendation_id)


@main_bp.route("/ai/recommendations/<int:recommendation_id>/apply", methods=["POST"])
@login_required
@admin_required
@menu_key_required("ai_center")
def ai_recommendation_apply(recommendation_id: int):
    def _apply(rid: int) -> dict[str, Any]:
        return apply_recommendation(rid, acting_user=current_user)

    return _run_json_service(_apply, recommendation_id)


@main_bp.route("/ai/recommendations/bulk-apply", methods=["POST"])
@login_required
@admin_required
@menu_key_required("ai_center")
def ai_recommendation_bulk_apply():
    def _apply_bulk() -> dict[str, Any]:
        raw_ids = _request_values("recommendation_ids")
        ids = [int(item) for item in raw_ids if str(item).strip().isdigit()]
        if not ids:
            raise ValueError("Toplu AI uygulaması için en az bir öneri seçin.")
        return {"ok": True, "data": bulk_apply_recommendations(ids, acting_user=current_user)}

    return _run_json_service(_apply_bulk)


@main_bp.route("/ai/recommendations/list")
@login_required
@admin_required
@menu_key_required("ai_center")
def ai_recommendation_list():
    def _list() -> dict[str, Any]:
        module_type = (_request_value("module_type") or "").strip().lower()
        target_table = (_request_value("target_table") or "").strip()
        target_id = int(_request_value("target_id") or 0)
        if not module_type or not target_table or not target_id:
            raise ValueError("AI öneri listesi için module_type, target_table ve target_id zorunludur.")
        rows = list_target_recommendation_payloads(
            module_type=module_type,
            target_table=target_table,
            target_id=target_id,
            statuses=("open", "accepted", "rejected"),
        )
        return {"ok": True, "data": {"recommendations": rows, "recommendation_count": len(rows)}}

    return _run_json_service(_list, commit=False)


@main_bp.route("/ai/feedback/<int:ai_request_log_id>", methods=["POST"])
@login_required
def ai_feedback(ai_request_log_id: int):
    def _save_feedback(target_id: int) -> dict[str, Any]:
        feedback_type = (_request_value("feedback_type") or "").strip().lower()
        feedback_note = (_request_value("feedback_note") or "").strip() or None
        row = log_ai_feedback(
            ai_request_log_id=target_id,
            user_id=getattr(current_user, "id", None),
            feedback_type=feedback_type,
            feedback_note=feedback_note,
        )
        if row is None:
            raise AIServiceDisabled("AI şema hazır değil; geri bildirim kaydedilemedi.")
        return {"ok": True, "data": {"id": row.id, "feedback_type": row.feedback_type}}

    return _run_json_service(_save_feedback, ai_request_log_id)

# BYS360_AI_DECISION_FAZ1_ROUTES
@main_bp.route("/ai/decision-support/faz1/health")
@main_bp.route("/ai/decision-support/faz1/health.json")
@login_required
def ai_decision_faz1_health():
    """Karar Destek Merkezi giriş durumu - gerçek BYS360 layout ekranı."""
    from app.services.ai_decision.performance_integration import (
        build_ai_decision_faz1_health_payload,
    )

    accept_header = str(request.headers.get("Accept", "") or "").lower()
    wants_json = (
        request.args.get("format") == "json"
        or request.args.get("raw") == "1"
        or ("application/json" in accept_header and "text/html" not in accept_header)
    )
    try:
        payload = build_ai_decision_faz1_health_payload()
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:199")
        payload = {"ok": False, "policy": {}}
    provider_snapshot = get_provider_snapshot()
    if isinstance(payload, dict):
        payload["provider_status"] = provider_snapshot
    if wants_json:
        return jsonify(payload), 200
    policy = payload.get("policy") if isinstance(payload, dict) else {}
    if not isinstance(policy, dict):
        policy = {}
    def _is_enabled(*names: str) -> bool:
        for name in names:
            value = policy.get(name)
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "evet", "aktif"}:
                return True
        return False
    low_score_threshold = int(policy.get("low_score_threshold") or policy.get("low_threshold") or 70)
    high_score_threshold = int(policy.get("high_score_threshold") or policy.get("high_threshold") or 90)
    controls = [
        {"title": "Düşük performans üst onayı", "description": f"{low_score_threshold} puanın altındaki sonuçlar yayın öncesi üst onay kontrolüne alınır.", "active": _is_enabled("president_approval_required_below_low", "low_score_requires_president_approval", "low_score_approval_required")},
        {"title": "Yayın koruması", "description": "Gerekli onaylar tamamlanmadan sonuçların personele açılması engellenir.", "active": _is_enabled("publish_lock_for_low_score", "low_score_publish_lock", "publish_lock_enabled")},
        {"title": "Gerekçeli değerlendirme", "description": "1 ve 5 puanlarda açıklama gerekliliği sistem ayarlarına göre yönetilir.", "active": _is_enabled("require_comment_for_score_1", "require_comment_for_score_5", "score_1_comment_required", "score_5_comment_required")},
        {"title": "Eşik dışı sonuçlarda genel görüş", "description": "Düşük veya çok yüksek performans sonucunda ayrıntılı kanaat kontrolü desteklenir.", "active": _is_enabled("require_general_comment_below_low", "require_general_comment_above_high", "general_comment_required")},
    ]
    return render_template(
        "ai_decision/faz1_health_layout.html",
        ai_decision_payload=payload,
        ai_ready=bool(payload.get("ok")) if isinstance(payload, dict) else False,
        low_score_threshold=low_score_threshold,
        high_score_threshold=high_score_threshold,
        controls=controls,
        ai_provider_snapshot=provider_snapshot,
        ai_provider_visible_warning=(not bool(provider_snapshot.get("ready_for_live_provider")) and provider_snapshot.get("provider_mode") not in {"stub", "internal_stub"}),
    ), 200

@main_bp.route("/ai/decision-support/performance/evaluation/<int:evaluation_id>")
@login_required
def ai_decision_performance_evaluation(evaluation_id: int):
    """Performans değerlendirmesi için deterministik karar destek çıktısı üretir."""
    from app.services.ai_decision.performance_integration import (
        build_performance_decision_support_response,
    )

    create_recommendations = str(request.args.get("create_recommendations", "1")).strip().lower() not in {"0", "false", "no", "hayir", "hayır"}
    return _run_json_service(
        lambda target_id: build_performance_decision_support_response(
            target_id,
            create_recommendations=create_recommendations,
        ),
        evaluation_id,
        commit=True,
    )

# BYS360_AI_DECISION_FAZ2_ROUTES
@main_bp.route("/ai/decision-support/faz2/health")
@login_required
def ai_decision_faz2_health():
    """Karar Destek Merkezi Faz 2 kategori/grup servis sağlığı."""
    from app.services.ai_decision.category_group_integration import (
        build_ai_decision_faz2_health_payload,
    )

    return jsonify(build_ai_decision_faz2_health_payload()), 200


@main_bp.route("/ai/decision-support/performance/category-groups")
@login_required
def ai_decision_performance_category_groups():
    """Personel kategori ve grup kırılımı için toplu karar destek çıktısı üretir."""
    from app.services.ai_decision.category_group_integration import (
        build_category_group_decision_support_response,
    )

    raw_period_id = str(request.args.get("period_id", "") or "").strip()
    period_id = int(raw_period_id) if raw_period_id.isdigit() else None
    include_unpublished = str(request.args.get("include_unpublished", "1")).strip().lower() not in {"0", "false", "no", "hayir", "hayır"}
    create_recommendations = str(request.args.get("create_recommendations", "1")).strip().lower() not in {"0", "false", "no", "hayir", "hayır"}
    return _run_json_service(
        lambda: build_category_group_decision_support_response(
            period_id=period_id,
            include_unpublished=include_unpublished,
            create_recommendations=create_recommendations,
        ),
        commit=True,
    )


@main_bp.route("/ai/decision-support/performance/category-groups/<int:period_id>")
@login_required
def ai_decision_performance_category_groups_for_period(period_id: int):
    """Belirli performans dönemi için kategori/grup karar destek çıktısı üretir."""
    from app.services.ai_decision.category_group_integration import (
        build_category_group_decision_support_response,
    )

    include_unpublished = str(request.args.get("include_unpublished", "1")).strip().lower() not in {"0", "false", "no", "hayir", "hayır"}
    create_recommendations = str(request.args.get("create_recommendations", "1")).strip().lower() not in {"0", "false", "no", "hayir", "hayır"}
    return _run_json_service(
        lambda: build_category_group_decision_support_response(
            period_id=period_id,
            include_unpublished=include_unpublished,
            create_recommendations=create_recommendations,
        ),
        commit=True,
    )

# BYS360_AI_DECISION_FAZ3_ROUTE_REGISTRATION
try:
    from app.ai import decision_support_faz3_routes as _bys360_ai_decision_faz3_routes  # noqa: F401
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:302")
    _bys360_ai_decision_faz3_routes = None  # type: ignore[assignment]

# BYS360_AI_DECISION_FAZ4_ROUTE_REGISTRATION
try:
    from app.ai import decision_support_faz4_routes as _bys360_ai_decision_faz4_routes  # noqa: F401
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:308")
    _bys360_ai_decision_faz4_routes = None  # type: ignore[assignment]

# BYS360_AI_DECISION_FAZ5_ROUTE_REGISTRATION
try:
    from app.ai import decision_support_faz5_routes as _bys360_ai_decision_faz5_routes  # noqa: F401
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:314")
    _bys360_ai_decision_faz5_routes = None  # type: ignore[assignment]

# BYS360_AI_DECISION_FAZ6_ROUTE_REGISTRATION
try:
    from app.ai import decision_support_faz6_routes as _bys360_ai_decision_faz6_routes  # noqa: F401
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:320")
    _bys360_ai_decision_faz6_routes = None  # type: ignore[assignment]

# BYS360_AI_DECISION_FAZ7_ROUTE_REGISTRATION
try:
    from app.ai import decision_support_faz7_routes as _bys360_ai_decision_faz7_routes  # noqa: F401
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:326")
    _bys360_ai_decision_faz7_routes = None  # type: ignore[assignment]

# BYS360_AI_DECISION_FAZ8_ROUTE_REGISTRATION
try:
    from app.ai import decision_support_faz8_routes as _bys360_ai_decision_faz8_routes  # noqa: F401
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:332")
    _bys360_ai_decision_faz8_routes = None  # type: ignore[assignment]

# BYS360_AI_DECISION_FAZ9_ROUTE_REGISTRATION
try:
    from app.ai import decision_support_faz9_routes as _bys360_ai_decision_faz9_routes  # noqa: F401
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:338")
    _bys360_ai_decision_faz9_routes = None  # type: ignore[assignment]

# BYS360_AI_DECISION_FAZ10_ROUTE_REGISTERED
try:
    from app.ai.decision_support_faz10_routes import ai_decision_faz10_bp
    _bys360_parent_bp = globals().get("bp") or globals().get("ai_bp") or globals().get("ai")
    if _bys360_parent_bp is not None and hasattr(_bys360_parent_bp, "register_blueprint"):
        _bys360_parent_bp.register_blueprint(ai_decision_faz10_bp)
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/ai/routes.py)")
# BYS360_AI_DECISION_FAZ10_ROUTE_REGISTERED_END

# BYS360_AI_DECISION_FAZ11_ROUTE_REGISTERED
try:
    from app.ai.decision_support_faz11_routes import ai_decision_faz11_bp
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:354")
    ai_decision_faz11_bp = None  # type: ignore[assignment]

try:
    _bys360_parent_bp = globals().get("bp") or globals().get("ai_bp") or globals().get("ai")
    if (
        _bys360_parent_bp is not None
        and ai_decision_faz11_bp is not None
        and hasattr(_bys360_parent_bp, "register_blueprint")
    ):
        try:
            _bys360_parent_bp.register_blueprint(ai_decision_faz11_bp)
        except ValueError:
            # Blueprint daha önce kaydedildiyse canlı açılışı bozulmasın.
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/ai/routes.py:366)")
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/ai/routes.py)")
# BYS360_AI_DECISION_FAZ11_ROUTE_REGISTERED_END

# BYS360_AI_DECISION_FAZ12_ROUTE_REGISTERED
try:
    from app.ai.decision_support_faz12_routes import ai_decision_faz12_bp
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/ai/routes.py:376")
    ai_decision_faz12_bp = None  # type: ignore[assignment]

try:
    _bys360_parent_bp = globals().get("bp") or globals().get("ai_bp") or globals().get("ai")
    if (
        _bys360_parent_bp is not None
        and ai_decision_faz12_bp is not None
        and hasattr(_bys360_parent_bp, "register_blueprint")
    ):
        try:
            _bys360_parent_bp.register_blueprint(ai_decision_faz12_bp)
        except ValueError:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/ai/routes.py)")
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/ai/routes.py)")
# BYS360_AI_DECISION_FAZ12_ROUTE_REGISTERED_END
