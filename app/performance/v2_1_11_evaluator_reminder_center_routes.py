from __future__ import annotations

import csv
import io
import logging
from functools import wraps
from typing import Any

from flask import Response, request
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import menu_key_required, safe_render
from app.services.performance.v2_1_11_evaluator_reminder_center import (
    build_evaluator_reminder_center_state,
    run_v2_1_11_evaluator_reminder_center_gate,
)

logger = logging.getLogger(__name__)

try:
    from app.services.performance.v2_1_6a_category_ui_cleanup import corporate_gate_label
except Exception:  # pragma: no cover - eski kopya uyumu
    logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=20")
    def corporate_gate_label(value: Any) -> str:
        return str(value or "Kontrol")


def _period_id_from_request() -> int | None:
    raw = request.args.get("period_id") or request.args.get("period") or ""
    try:
        return int(raw) if raw else None
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=29")
        return None


def _due_days_from_request() -> int:
    try:
        value = int(request.args.get("due_days") or 2)
        return max(1, min(30, value))
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=37")
        return 2


# BYS360_PERFORMANCE_V2_1_22A_PERIOD_CENTER_ADMIN_ACCESS_BEGIN
_PERIOD_CENTER_MENU_KEY_V222A = "performance_period_management_center"
_PERIOD_CENTER_MENU_DECORATOR_V222A = menu_key_required(_PERIOD_CENTER_MENU_KEY_V222A)
_PERIOD_CENTER_ADMIN_TERMS_V222A = {
    "admin", "administrator", "super_admin", "system_admin", "sistem_yoneticisi",
    "sistem yoneticisi", "sistem_yöneticisi", "yonetici", "yönetici",
}


def _period_center_norm_v222a(value):
    text = str(value or "").strip().lower()
    return (text
            .replace("İ", "i").replace("ı", "i")
            .replace("ğ", "g").replace("ü", "u").replace("ş", "s")
            .replace("ö", "o").replace("ç", "c")
            .replace("-", "_").replace("/", "_").replace(".", "_").strip())


def _period_center_collect_terms_v222a(user):
    terms: set[str] = set()
    if not user:
        return terms
    # R05/R1: the stored role only; title, unvan, position, gorev or username never create authority.
    for attr in ("role", "role_name", "user_role", "authority_level"):
        try:
            terms.add(_period_center_norm_v222a(getattr(user, attr, "")))
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=68")
            pass
    for rel in ("roles", "user_roles"):
        try:
            values = getattr(user, rel, None)
            if values:
                for item in values:
                    terms.add(_period_center_norm_v222a(getattr(item, "name", item)))
                    terms.add(_period_center_norm_v222a(getattr(item, "role_name", "")))
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=77")
            pass
    try:
        role_obj = getattr(user, "role", None)
        terms.add(_period_center_norm_v222a(getattr(role_obj, "name", "")))
        terms.add(_period_center_norm_v222a(getattr(role_obj, "role_name", "")))
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=83")
        pass
    return {t for t in terms if t}


def _period_center_is_admin_user_v222a(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    for attr in ("is_admin", "is_superuser", "is_system_admin", "is_sistem_yoneticisi"):
        try:
            if bool(getattr(user, attr, False)):
                return True
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=95")
            pass
    try:
        has_role = getattr(user, "has_role", None)
        if callable(has_role) and any(has_role(role) for role in ("admin", "Admin", "Sistem Yöneticisi", "sistem_yoneticisi")):
            return True
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/performance/v2_1_11_evaluator_reminder_center_routes.py | line=101")
        pass
    return bool(_period_center_collect_terms_v222a(user) & _PERIOD_CENTER_ADMIN_TERMS_V222A)


def period_center_menu_or_admin_required(view_func):
    menu_protected = _PERIOD_CENTER_MENU_DECORATOR_V222A(view_func)

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if _period_center_is_admin_user_v222a(current_user):
            return view_func(*args, **kwargs)
        return menu_protected(*args, **kwargs)

    return wrapper

def evaluator_reminder_menu_or_admin_required(view_func):
    menu_protected = menu_key_required("performance_evaluator_reminder_center")(view_func)

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if _period_center_is_admin_user_v222a(current_user):
            return view_func(*args, **kwargs)
        return menu_protected(*args, **kwargs)

    return wrapper

# BYS360_PERFORMANCE_V2_1_22A_PERIOD_CENTER_ADMIN_ACCESS_END

@main_bp.route("/performance/v2-1-11-evaluator-reminder-center", methods=["GET"])
@main_bp.route("/performans/amir-hatirlatma-merkezi", methods=["GET"])
@login_required
@evaluator_reminder_menu_or_admin_required
def performance_v2_1_11_evaluator_reminder_center():
    state = build_evaluator_reminder_center_state(
        period_id=_period_id_from_request(),
        risk_filter=request.args.get("risk_filter") or "all",
        manager_level=request.args.get("manager_level") or "",
        q=request.args.get("q") or "",
        due_days=_due_days_from_request(),
        include_rows=True,
    )
    return safe_render(
        "performance/v2_1_11_evaluator_reminder_center.html",
        page_title="Amir Hatırlatma Merkezi",
        state=state,
        gate=run_v2_1_11_evaluator_reminder_center_gate(),
        corporate_gate_label=corporate_gate_label,
    )


@main_bp.route("/performance/v2-1-11-evaluator-reminder-center/export.csv", methods=["GET"])
@login_required
@evaluator_reminder_menu_or_admin_required
def performance_v2_1_11_evaluator_reminder_center_export_csv():
    state = build_evaluator_reminder_center_state(
        period_id=_period_id_from_request(),
        risk_filter=request.args.get("risk_filter") or "all",
        manager_level=request.args.get("manager_level") or "",
        q=request.args.get("q") or "",
        due_days=_due_days_from_request(),
        include_rows=True,
    )
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Amir", "E-posta", "Unvan", "Toplam Görev", "Tamamlanan", "Bekleyen", "Geciken", "Son Tarihi Yaklaşan", "Hatırlatma Türü", "Konu"])
    for item in state.get("evaluators") or []:
        writer.writerow([
            item.get("evaluator_name") or "",
            item.get("evaluator_email") or "",
            item.get("evaluator_title") or "",
            item.get("total") or 0,
            item.get("completed") or 0,
            item.get("pending") or 0,
            item.get("overdue") or 0,
            item.get("due_soon") or 0,
            item.get("reminder_type") or "",
            item.get("preview_subject") or "",
        ])
    filename = "bys360_amir_hatirlatma_hazirligi_v2_1_11.csv"
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
