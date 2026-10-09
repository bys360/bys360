from __future__ import annotations

import logging
from collections.abc import Iterable

# BYS360 SP-1D KPI/Hedef Kayıt ve Listeleme Servisi
from typing import Any

try:
    from sqlalchemy import text
except Exception:  # pragma: no cover
    text = None  # type: ignore[assignment]

try:
    from app import db
except Exception:  # pragma: no cover
    db = None  # type: ignore[assignment]


def _execute(statement: str, params: dict[str, Any] | None = None):
    if db is None:
        raise RuntimeError("Veritabanı bağlantısı kullanılamıyor.")
    if text:  # type: ignore[truthy-function]
        return db.session.execute(text(statement), params or {})
    return db.session.execute(statement, params or {})


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def _normalize_status_and_risk(completion_rate: float) -> tuple[str, str]:
    if completion_rate >= 90:
        return "tamamlandi", "dusuk"
    if completion_rate >= 70:
        return "devam_ediyor", "normal"
    if completion_rate >= 50:
        return "riskli", "riskli"
    return "kritik", "kritik"


def _current_user_id(current_user: Any) -> int | None:
    value = getattr(current_user, "id", None) or getattr(current_user, "user_id", None)
    try:
        return int(value) if value is not None else None
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _current_unit_id(current_user: Any) -> int | None:
    for attr in ["organization_unit_id", "unit_id", "org_unit_id"]:
        value = getattr(current_user, attr, None)
        try:
            if value is not None:
                return int(value)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/sp1d_target_management_service.py)")
    return None


def _role_name(current_user: Any) -> str:
    role = getattr(current_user, "role", None) or getattr(current_user, "role_name", None) or ""
    return str(role).lower()


# B1-F1 decision 2: technical administration roles do not see every KPI target by role.
_TECHNICAL_ADMIN_ROLES = {"sistem_yoneticisi", "sistem_yöneticisi", "system_admin", "admin_sistem_yoneticisi"}


def _is_global_role(current_user: Any) -> bool:
    role = _role_name(current_user)
    # B1-F1 (approved least-privilege policy, 2026-10-09): "performans", "ik" and "sistem"
    # removed; performans_yetkilisi, ik and the technical roles see/edit only their own or
    # their unit's KPI targets.
    if role in _TECHNICAL_ADMIN_ROLES:
        return False
    return any(item in role for item in ["admin", "başkan", "baskan"])


def _dict_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        try:
            output.append(dict(row))
        except Exception:
            output.append(dict(row._mapping))
    return output


def build_target_form_context(current_user: Any) -> dict[str, Any]:
    periods = []
    if db is not None:
        try:
            rows = _execute(
                """
                SELECT id, name
                FROM performance_target_periods
                ORDER BY start_date DESC, id DESC
                LIMIT 50
                """
            ).mappings().all()
            periods = _dict_rows(rows)
        except Exception:
            periods = []
    return {
        "periods": periods,
        "target_types": [
            ("kurumsal", "Kurumsal Hedef"),
            ("birim", "Birim Hedefi"),
            ("personel", "Personel Hedefi"),
        ],
        "categories": [
            ("kpi", "KPI"),
            ("stratejik", "Stratejik"),
            ("operasyon", "Operasyon"),
            ("gelisim", "Gelişim"),
        ],
    }


def list_targets_for_user(current_user: Any) -> list[dict[str, Any]]:
    if db is None:
        return []
    params: dict[str, Any] = {}
    where = "1=1"
    if not _is_global_role(current_user):
        where = "(owner_user_id = :user_id OR owner_unit_id = :unit_id)"
        params = {"user_id": _current_user_id(current_user), "unit_id": _current_unit_id(current_user)}
    try:
        rows = _execute(
            f"""
            SELECT
                id,
                target_code,
                target_name,
                target_type,
                category,
                weight,
                target_value,
                current_value,
                completion_rate,
                status,
                risk_level,
                start_date,
                end_date
            FROM performance_targets
            WHERE {where}
            ORDER BY id DESC
            LIMIT 100
            """,
            params,
        ).mappings().all()
        return _dict_rows(rows)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return []


def get_target_for_edit(target_id: int, current_user: Any) -> dict[str, Any] | None:
    if db is None:
        return None
    params: dict[str, Any] = {"id": target_id}
    where = "id = :id"
    if not _is_global_role(current_user):
        where += " AND (owner_user_id = :user_id OR owner_unit_id = :unit_id)"
        params.update({"user_id": _current_user_id(current_user), "unit_id": _current_unit_id(current_user)})
    try:
        row = _execute(
            f"""
            SELECT *
            FROM performance_targets
            WHERE {where}
            LIMIT 1
            """,
            params,
        ).mappings().first()
        return dict(row) if row else None
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _form_payload(form: Any, current_user: Any) -> dict[str, Any]:
    target_value = _to_float(form.get("target_value"))
    current_value = _to_float(form.get("current_value"))
    completion_rate = 0.0
    if target_value > 0:
        completion_rate = round(min((current_value / target_value) * 100, 999), 2)
    status, risk_level = _normalize_status_and_risk(completion_rate)
    return {
        "target_code": (form.get("target_code") or "").strip(),
        "target_name": (form.get("target_name") or "").strip(),
        "target_type": form.get("target_type") or "birim",
        "category": form.get("category") or "kpi",
        "owner_user_id": _current_user_id(current_user) if (form.get("target_type") == "personel") else None,
        "owner_unit_id": _current_unit_id(current_user),
        "weight": _to_float(form.get("weight")),
        "target_value": target_value,
        "current_value": current_value,
        "completion_rate": completion_rate,
        "status": status,
        "risk_level": risk_level,
        "start_date": form.get("start_date") or None,
        "end_date": form.get("end_date") or None,
        "period_id": int(form.get("period_id")) if str(form.get("period_id") or "").isdigit() else None,
    }


def _validate_payload(payload: dict[str, Any]) -> list[str]:
    errors = []
    if not payload["target_code"]:
        errors.append("Hedef kodu zorunludur.")
    if not payload["target_name"]:
        errors.append("Hedef adı zorunludur.")
    if payload["target_value"] <= 0:
        errors.append("Hedef değeri sıfırdan büyük olmalıdır.")
    if payload["weight"] < 0 or payload["weight"] > 100:
        errors.append("Ağırlık 0 ile 100 arasında olmalıdır.")
    return errors


def create_target_from_form(form: Any, current_user: Any) -> tuple[bool, str]:
    if db is None:
        return False, "Veritabanı bağlantısı kullanılamıyor."
    payload = _form_payload(form, current_user)
    errors = _validate_payload(payload)
    if errors:
        return False, " ".join(errors)
    try:
        _execute(
            """
            INSERT INTO performance_targets (
                target_code, target_name, target_type, category, owner_user_id, owner_unit_id,
                weight, target_value, current_value, completion_rate, status, risk_level,
                start_date, end_date, period_id
            ) VALUES (
                :target_code, :target_name, :target_type, :category, :owner_user_id, :owner_unit_id,
                :weight, :target_value, :current_value, :completion_rate, :status, :risk_level,
                :start_date, :end_date, :period_id
            )
            """,
            payload,
        )
        db.session.commit()
        return True, "KPI / hedef kaydı oluşturuldu."
    except Exception as exc:
        logging.getLogger(__name__).exception("BYS360 SP1D hedef kaydı oluşturulamadı | exc=%s", exc)
        db.session.rollback()
        return False, "Kayıt oluşturulamadı."


def update_target_from_form(target_id: int, form: Any, current_user: Any) -> tuple[bool, str]:
    if db is None:
        return False, "Veritabanı bağlantısı kullanılamıyor."
    existing = get_target_for_edit(target_id, current_user)
    if not existing:
        return False, "Hedef kaydı bulunamadı veya bu kayıt için yetkiniz yok."
    payload = _form_payload(form, current_user)
    payload["id"] = target_id
    errors = _validate_payload(payload)
    if errors:
        return False, " ".join(errors)
    try:
        _execute(
            """
            UPDATE performance_targets SET
                target_code = :target_code,
                target_name = :target_name,
                target_type = :target_type,
                category = :category,
                owner_user_id = :owner_user_id,
                owner_unit_id = :owner_unit_id,
                weight = :weight,
                target_value = :target_value,
                current_value = :current_value,
                completion_rate = :completion_rate,
                status = :status,
                risk_level = :risk_level,
                start_date = :start_date,
                end_date = :end_date,
                period_id = :period_id
            WHERE id = :id
            """,
            payload,
        )
        db.session.commit()
        return True, "KPI / hedef kaydı güncellendi."
    except Exception as exc:
        logging.getLogger(__name__).exception("BYS360 SP1D hedef güncellenemedi | exc=%s", exc)
        db.session.rollback()
        return False, "Güncelleme tamamlanamadı."
