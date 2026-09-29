from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import text

from app.extensions import db
from app.route_registry import main_bp
from app.route_support import safe_db_rollback
from app.services.ai_decision.period_scope_integration import (
    build_period_scope_summary_payload,
    build_single_period_payload,
)

logger = logging.getLogger(__name__)

"""BYS360 AI Karar Destek Faz 8 route ekleri.

Çoklu dönem, özel dönem, kategori/grup dönemi ve seçili personel kapsamını
karar destek merkezi üzerinden güvenli JSON çıktılarıyla sunar.

BYS360_AI_DECISION_FAZ8_ROUTES
"""

ResponseBuilder = Callable[..., dict[str, Any]]


def _run_faz8_json(builder: ResponseBuilder, *args: Any) -> tuple[Any, int]:
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
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz8_routes.py | line=43 | exc=%s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "error": "Dönem kapsam karar destek kontrolünde beklenmeyen bir hata oluştu."}), 500


def _load_settings() -> dict[str, Any]:
    rows = db.session.execute(
        text(
            """
            SELECT setting_key, value_text
              FROM module_settings
             WHERE module_key = 'ai_decision'
               AND setting_key IN (
                'faz8_allow_multiple_periods', 'faz8_allow_special_periods',
                'faz8_require_scope_for_special_period', 'faz8_overlap_warning_enabled',
                'faz8_selected_personnel_limit', 'faz8_low_assignment_warning_limit'
               )
            """
        )
    ).mappings().all()
    return {row["setting_key"]: row["value_text"] for row in rows}


def _limit(default: int = 250) -> int:
    try:
        value = int(request.args.get("limit", default))
        return max(1, min(value, 1000))
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/ai/decision_support_faz8_routes.py | line=70")
        return default


# Only columns of the canonical schema (ORM model, fresh migrations and the
# verified production database). The earlier SELECTs named period_name,
# scope_reference, category_id, unit_id and evaluated_user_id, none of which
# exist, so both Faz 8 endpoints failed on every request.
PERIOD_COLUMNS: tuple[str, ...] = (
    "id", "title", "name", "period_type", "scope_type",
    "scope_unit_label", "scope_category_label", "scope_personnel_filter",
    "start_date", "end_date", "is_active", "created_at",
)
# employee_id is the evaluated personnel (EvaluationAssignment.employee).
ASSIGNMENT_COLUMNS: tuple[str, ...] = ("id", "period_id", "evaluator_id", "employee_id", "status", "created_at")
_PERIOD_SELECT = ", ".join(PERIOD_COLUMNS)
_ASSIGNMENT_SELECT = ", ".join(ASSIGNMENT_COLUMNS)

_UNIT_SCOPES = frozenset({"unit", "upper_unit"})
_CATEGORY_SCOPES = frozenset({"category", "group"})
_PERSONNEL_SCOPES = frozenset({"selected_personnel", "personnel"})
SELECTED_PERSONNEL_REFERENCE = "selected_personnel"


def _with_scope_reference(row: Any) -> dict[str, Any]:
    """Return the period row with its scope target as ``scope_reference``.

    The target is the column period_forms requires for each scope type. A
    selected-personnel filter holds registry numbers, so only its presence is
    reported and the filter itself is dropped from the row.
    """
    period = dict(row)
    scope_type = str(period.get("scope_type") or "").strip()
    personnel_filter = str(period.pop("scope_personnel_filter", None) or "").strip()
    if scope_type in _UNIT_SCOPES:
        reference = str(period.get("scope_unit_label") or "").strip()
    elif scope_type in _CATEGORY_SCOPES:
        reference = str(period.get("scope_category_label") or "").strip()
    elif scope_type in _PERSONNEL_SCOPES:
        reference = SELECTED_PERSONNEL_REFERENCE if personnel_filter else ""
    else:
        reference = ""
    period["scope_reference"] = reference or None
    return period


def _periods(limit: int = 250) -> Sequence[Any]:
    rows = db.session.execute(
        text(
            f"""
            SELECT {_PERIOD_SELECT}
              FROM performance_periods
             ORDER BY COALESCE(start_date, created_at) DESC NULLS LAST, id DESC
             LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return [_with_scope_reference(row) for row in rows]


def _single_period(period_id: int) -> Any:
    row = db.session.execute(
        text(
            f"""
            SELECT {_PERIOD_SELECT}
              FROM performance_periods
             WHERE id = :period_id
            """
        ),
        {"period_id": period_id},
    ).mappings().first()
    if row is None:
        raise LookupError("Dönem kaydı bulunamadı.")
    return _with_scope_reference(row)


def _assignments(limit: int = 5000, period_id: int | None = None) -> Sequence[Any]:
    where = "WHERE period_id = :period_id" if period_id is not None else ""
    params = {"limit": limit}
    if period_id is not None:
        params["period_id"] = period_id
    return db.session.execute(
        text(
            f"""
            SELECT {_ASSIGNMENT_SELECT}
              FROM evaluation_assignments
              {where}
             ORDER BY id DESC
             LIMIT :limit
            """
        ),
        params,
    ).mappings().all()


@main_bp.route("/ai/decision-support/faz8/health")
@login_required
def ai_decision_faz8_health():
    return jsonify({
        "ok": True,
        "phase": "Faz 8",
        "module": "AI Karar Destek Merkezi",
        "scope": "Çoklu ve Özel Dönem Yönetimi",
        "marker": "BYS360_AI_DECISION_FAZ8_HEALTH_OK",
    })


@main_bp.route("/ai/decision-support/performance/periods/scope-summary")
@login_required
def ai_decision_faz8_period_scope_summary():
    settings = _load_settings()
    return _run_faz8_json(build_period_scope_summary_payload, _periods(_limit()), _assignments(), current_user, settings)


@main_bp.route("/ai/decision-support/performance/periods/<int:period_id>/scope-check")
@login_required
def ai_decision_faz8_single_period_scope_check(period_id: int):
    settings = _load_settings()

    def _build() -> dict[str, Any]:
        # Inside the runner, so a missing period maps to its LookupError -> 404 answer.
        period = _single_period(period_id)
        return build_single_period_payload(period, _periods(500), _assignments(period_id=period_id), settings)

    return _run_faz8_json(_build)
