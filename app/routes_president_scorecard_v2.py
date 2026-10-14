"""BYS360 Başkan Onayları Karne İncelemesi V2 compatibility routes."""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)
try:
    from app.extensions import db
except Exception:  # pragma: no cover - legacy fallback
    logger.exception("Performans modulu kritik isleminde hata olustu", exc_info=True)
    from app import db

president_scorecard_v2_bp = Blueprint("president_scorecard_v2", __name__)

STATUS_LABELS = {
    "president_pending": "Başkan onayı bekliyor",
    "blocked_president_pending": "Başkan onayı beklediği için yayın kilitli",
    "pending": "Bekliyor",
    "approved": "Onaylandı",
    "rejected": "Reddedildi",
    "published": "Yayınlandı",
    "draft": "Taslak",
    "completed": "Tamamlandı",
}


def _normalize_role_value(value) -> str:
    raw = str(value or "").strip().lower()
    tr_map = str.maketrans("çğıöşüâîûİ", "cgiosuaiui")
    return raw.translate(tr_map).replace(" ", "_").replace("-", "_")


def _is_admin_or_president() -> bool:
    if not getattr(current_user, "is_authenticated", False):
        return False
    if bool(getattr(current_user, "is_admin", False)) or bool(getattr(current_user, "is_superuser", False)):
        return True
    # D3/R05: the job title (unvan/title) never grants president approvals.
    role_values = {
        _normalize_role_value(getattr(current_user, attr, ""))
        for attr in ("role", "role_name", "user_type")
    }
    return bool(role_values & {"admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "president"})


def _access_denied_response():
    return render_template(
        "errors/403.html",
        title="Erişim Yetkiniz Bulunmamaktadır",
        message="Bu sayfa yalnızca Başkan ve yetkili sistem yöneticileri tarafından görüntülenebilir.",
        back_url="/",
    ), 403


def _require_access():
    if not _is_admin_or_president():
        return _access_denied_response()
    return None


def _insp():
    return inspect(db.engine)


def _tables() -> set[str]:
    try:
        return set(_insp().get_table_names())
    except Exception:
        logger.exception("Performans modulu kritik isleminde hata olustu", exc_info=True)
        return set()


def _has_table(table: str) -> bool:
    return table in _tables()


def _cols(table: str) -> set[str]:
    try:
        return {c["name"] for c in _insp().get_columns(table)}
    except Exception:
        logger.exception("Performans modulu kritik isleminde hata olustu", exc_info=True)
        return set()


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _row(table: str, where: str, params: dict):
    if not _has_table(table):
        return None
    try:
        return db.session.execute(text(f"SELECT * FROM {_qident(table)} WHERE {where} LIMIT 1"), params).mappings().first()
    except Exception:
        logger.exception("Performans modulu kritik isleminde hata olustu", exc_info=True)
        db.session.rollback()
        return None


def _rows(sql: str, params: dict | None = None) -> list[dict]:
    try:
        return [dict(r) for r in db.session.execute(text(sql), params or {}).mappings().all()]
    except Exception:
        logger.exception("Performans modulu kritik isleminde hata olustu", exc_info=True)
        db.session.rollback()
        return []


def _first(mapping, names, default=None):
    if not mapping:
        return default
    for name in names:
        if name in mapping and mapping[name] not in (None, ""):
            return mapping[name]
    return default


def _label(value, default="—") -> str:
    if value in (None, ""):
        return default
    raw = str(value)
    return STATUS_LABELS.get(raw, "Bilinmiyor")


def _score(value):
    try:
        if value is None or value == "":
            return None
        return round(float(value), 2)
    except Exception:
        logger.exception("Performans modulu kritik isleminde hata olustu", exc_info=True)
        return None


def _find_record(approval_id: int):
    candidates = (
        "performance_result_snapshots",
        "performance_publish_logs",
        "evaluation_publish_logs",
        "performance_evaluations",
        "evaluation_assignments",
    )
    for table in candidates:
        if not _has_table(table):
            continue
        cols = _cols(table)
        if "id" in cols:
            found = _row(table, "id = :id", {"id": approval_id})
            if found:
                return table, dict(found)
    return None, None


def _find_user(user_id):
    if not user_id or not _has_table("users"):
        return None
    cols = _cols("users")
    key = "id" if "id" in cols else None
    if not key:
        return None
    found = _row("users", f"{_qident(key)} = :id", {"id": user_id})
    return dict(found) if found else None


def _find_period(period_id):
    if not period_id or not _has_table("performance_periods"):
        return None
    cols = _cols("performance_periods")
    if "id" not in cols:
        return None
    found = _row("performance_periods", "id = :id", {"id": period_id})
    return dict(found) if found else None


def _name_from_user(user) -> str:
    if not user:
        return "—"
    full = _first(user, ["full_name", "name", "display_name", "ad_soyad", "adi_soyadi"])
    if full:
        return str(full)
    first = _first(user, ["first_name", "ad", "adi"], "") or ""
    last = _first(user, ["last_name", "soyad", "soyadi"], "") or ""
    combined = (str(first) + " " + str(last)).strip()
    return combined or str(_first(user, ["username", "email"], "—"))


def _period_name(period, record) -> str:
    if period:
        return str(_first(period, ["name", "title", "period_name", "label"], "—"))
    return str(_first(record, ["period_name", "period_title", "period"], "—"))


def _history_from_table(record, employee_id, period_id):
    if not _has_table("performance_evaluation_history"):
        return []
    cols = _cols("performance_evaluation_history")
    clauses = []
    params: dict[str, Any] = {}
    for key in ("evaluation_id", "assignment_id"):
        value = _first(record, [key])
        if key in cols and value:
            clauses.append(f"{_qident(key)} = :{key}")
            params[key] = value
    if "employee_id" in cols and employee_id:
        clauses.append("employee_id = :employee_id")
        params["employee_id"] = employee_id
    if not clauses:
        return []
    order_col = "created_at" if "created_at" in cols else ("id" if "id" in cols else None)
    order_sql = f" ORDER BY {_qident(order_col)} ASC" if order_col else ""
    sql = f"SELECT * FROM performance_evaluation_history WHERE {' OR '.join(clauses)}{order_sql} LIMIT 100"
    rows = _rows(sql, params)
    output = []
    for idx, r in enumerate(rows, 1):
        output.append({
            "stage": _label(_first(r, ["stage", "status", "action"], f"Kayıt {idx}")),
            "manager": str(_first(r, ["manager_name", "evaluator_name", "created_by_name", "user_name"], "—")),
            "score": _score(_first(r, ["score", "final_score", "weighted_score", "total_score"])),
            "comment": str(_first(r, ["comment", "note", "description", "general_comment"], "—")),
            "created_at": str(_first(r, ["created_at", "updated_at", "date"], "—")),
        })
    return output


def _history_from_evaluations(record, employee_id, period_id):
    """Puanlama geçmişi boşsa mevcut değerlendirme kayıtlarından güvenli özet üretir."""
    if not _has_table("performance_evaluations"):
        return []
    cols = _cols("performance_evaluations")
    clauses = []
    params = {}
    if "employee_id" in cols and employee_id:
        clauses.append("employee_id = :employee_id")
        params["employee_id"] = employee_id
    for alt in ("user_id", "evaluated_user_id", "personnel_id"):
        if alt in cols and employee_id:
            clauses.append(f"{_qident(alt)} = :employee_id")
    if "period_id" in cols and period_id:
        clauses.append("period_id = :period_id")
        params["period_id"] = period_id
    if not clauses:
        rec_id = _first(record, ["evaluation_id", "id"])
        if "id" in cols and rec_id:
            clauses.append("id = :rec_id")
            params["rec_id"] = rec_id
    if not clauses:
        return []
    order_col = "updated_at" if "updated_at" in cols else ("created_at" if "created_at" in cols else "id")
    sql = f"SELECT * FROM performance_evaluations WHERE {' AND '.join(clauses[:2])} ORDER BY {_qident(order_col)} ASC LIMIT 100"
    rows = _rows(sql, params)
    output = []
    for idx, r in enumerate(rows, 1):
        level = _first(r, ["manager_level", "evaluator_level", "level", "step"], idx)
        output.append({
            "stage": f"{level}. amir değerlendirme özeti" if str(level).isdigit() else str(level),
            "manager": str(_first(r, ["manager_name", "evaluator_name", "created_by_name"], "Sistem kaydı")),
            "score": _score(_first(r, ["final_score", "weighted_score", "total_score", "score", "average_score"])),
            "comment": str(_first(r, ["general_comment", "comment", "note", "description"], "Mevcut değerlendirme kayıtlarından güvenli özet üretildi.")),
            "created_at": str(_first(r, ["updated_at", "created_at", "completed_at"], "—")),
        })
    return output


def _build_data(approval_id: int) -> dict:
    table, record = _find_record(approval_id)
    record = record or {"id": approval_id, "status": "president_pending", "publish_lock_status": "blocked_president_pending"}

    employee_id = _first(record, ["employee_id", "user_id", "evaluated_user_id", "personnel_id", "subject_user_id"])
    period_id = _first(record, ["period_id", "performance_period_id"])
    user = _find_user(employee_id)
    period = _find_period(period_id)

    history = _history_from_table(record, employee_id, period_id)
    history_source = "Puanlama geçmişi kayıtları"
    if not history:
        history = _history_from_evaluations(record, employee_id, period_id)
        history_source = "Mevcut değerlendirme kayıtlarından güvenli özet"
    if not history:
        history = [{
            "stage": "Güvenli özet",
            "manager": "Sistem",
            "score": _score(_first(record, ["final_score", "score", "total_score", "weighted_score", "average_score"])),
            "comment": "Puanlama geçmişi tablosunda kayıt bulunamadı; karne özeti mevcut başkan onayı kaydından oluşturuldu.",
            "created_at": str(_first(record, ["updated_at", "created_at"], "—")),
        }]
        history_source = "Başkan onayı kaydından güvenli özet"

    final_score = _score(_first(record, ["final_score", "score", "total_score", "weighted_score", "average_score", "result_score"]))
    status_value = _first(record, ["status", "workflow_status", "approval_status"], "president_pending")
    lock_value = _first(record, ["publish_lock_status", "publish_lock", "publish_status", "lock_status"], "blocked_president_pending")
    if str(status_value) == "president_pending" and lock_value in (None, "", "draft", "pending"):
        lock_value = "blocked_president_pending"

    return {
        "id": approval_id,
        "source_table": table or "güvenli özet",
        "employee_name": _name_from_user(user) if user else str(_first(record, ["employee_name", "personnel_name", "full_name", "name"], "—")),
        "sicil_no": str(_first(user or {}, ["sicil_no", "registration_no", "employee_no", "sicil"], _first(record, ["sicil_no", "registration_no"], "—"))),
        "unit_name": str(_first(user or {}, ["unit_name", "department", "birim"], _first(record, ["unit_name", "department", "birim"], "—"))),
        "period_name": _period_name(period, record),
        "final_score": final_score,
        "status_label": _label(status_value),
        "publish_lock_label": _label(lock_value),
        "history": history,
        "history_source": history_source,
        "created_at": str(_first(record, ["created_at", "updated_at", "completed_at"], "—")),
        "process_flow": [
            "Değerlendirme tamamlandı",
            "Düşük performans ön kontrolü oluşturuldu",
            "İK/Admin kontrolü bekleniyor",
            "Başkan onayı bekliyor",
            "Başkan onayı beklediği için yayın kilitli",
        ],
    }


def _list_items():
    tables = ("performance_result_snapshots", "performance_publish_logs", "evaluation_publish_logs", "performance_evaluations")
    for table in tables:
        if not _has_table(table):
            continue
        cols = _cols(table)
        if "id" not in cols:
            continue
        score_col = next((c for c in ("final_score", "score", "total_score", "weighted_score", "average_score", "result_score") if c in cols), None)
        status_col = next((c for c in ("status", "workflow_status", "approval_status") if c in cols), None)
        where = []
        if status_col:
            where.append(f"CAST({_qident(status_col)} AS TEXT) = 'president_pending'")
        if score_col:
            where.append(f"CAST({_qident(score_col)} AS FLOAT) < 70")
        where_sql = " WHERE " + " OR ".join(where) if where else ""
        order_col = "updated_at" if "updated_at" in cols else ("created_at" if "created_at" in cols else "id")
        rows = _rows(f"SELECT * FROM {_qident(table)}{where_sql} ORDER BY {_qident(order_col)} DESC LIMIT 100")
        if rows:
            out = []
            for r in rows:
                data = _build_data(int(r.get("id") or 0))
                out.append(data)
            return out
    return []


@president_scorecard_v2_bp.route("/performans/baskan-onaylari")
@login_required
def president_approvals_tr_v2():
    denied = _require_access()
    if denied:
        return denied
    return render_template("performance/president_approvals_v2.html", items=_list_items())


@president_scorecard_v2_bp.route("/performance/president-approvals")
@login_required
def president_approvals_en_v2():
    denied = _require_access()
    if denied:
        return denied
    return render_template("performance/president_approvals_v2.html", items=_list_items())


@president_scorecard_v2_bp.route("/performance/president-approvals/<int:approval_id>/scorecard")
@president_scorecard_v2_bp.route("/performans/baskan-onaylari/<int:approval_id>/karne")
@login_required
def president_approval_scorecard_v2(approval_id: int):
    denied = _require_access()
    if denied:
        return denied
    data = _build_data(approval_id)
    return render_template("performance/president_approval_scorecard_v2.html", data=data)
