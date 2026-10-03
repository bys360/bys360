from __future__ import annotations

import logging
from typing import Any

from app.api.mobile.services.performance_base_helpers import _period_name
from app.api.mobile.shared import _item
from app.extensions import db
from app.models import PerformancePeriod

logger = logging.getLogger(__name__)


def _safe_get_period(period_id: Any):
    try:
        if period_id is None:
            return None
        return db.session.get(PerformancePeriod, period_id)
    except Exception:
        logger.exception("BYS360 mobil performans ayar yardımcısında dönem okunamadı.")
        try:
            db.session.rollback()
        except Exception:
            logger.exception("BYS360 mobil performans ayar yardımcısında rollback tamamlanamadı.")
        return None


def _v2821_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def _v2821_percent(value) -> str:
    val = _v2821_float(value, 0.0)
    if val == int(val):
        return f"%{int(val)}"
    return f"%{val:.1f}".replace(".", ",")


def _v2821_active_text(value) -> str:
    return "Aktif" if bool(value) else "Pasif"


def _v2821_mode_text(value) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"comment_only", "comment", "yorum", "gorus", "görüş", "review_only"}:
        return "Yalnızca Görüş"
    if raw in {"score", "scored", "weighted", "puan", "puanli", "puanlı"}:
        return "Puan Katkılı"
    if not raw:
        return "Yalnızca Görüş"
    return str(value)


def _v2821_period_label(period_id) -> str:
    period = _safe_get_period(period_id)
    if period:
        return _period_name(period)
    return "Genel kural"


def _v2821_criteria_item(row) -> dict[str, Any]:
    weight = getattr(row, "weight", None)
    active = getattr(row, "is_active", True)
    code = getattr(row, "criteria_code", None) or getattr(row, "code", None) or ""
    description = str(getattr(row, "description", None) or "Kriter açıklaması bulunmuyor.")
    return _item(
        getattr(row, "id", ""),
        str(getattr(row, "name", None) or "Değerlendirme Kriteri"),
        description,
        _v2821_active_text(active),
        f"Ağırlık {_v2821_percent(weight)}" if weight is not None else "Ağırlık tanımlı değil",
        str(code),
        100 if active else 35,
    )


def _v2821_weight_item(row) -> dict[str, Any]:
    w1 = _v2821_float(getattr(row, "evaluator_1_weight", 0))
    w2 = _v2821_float(getattr(row, "evaluator_2_weight", 0))
    w3 = _v2821_float(getattr(row, "evaluator_3_weight", 0))
    total = w1 + w2 + w3
    level3 = bool(getattr(row, "level_3_enabled", False))
    mode = _v2821_mode_text(getattr(row, "level_3_mode", None))
    title = str(getattr(row, "name", None) or _v2821_period_label(getattr(row, "period_id", None)))
    status = "Dengeli" if int(round(total)) == 100 else "Kontrol Gerekir"
    subtitle = f"1. amir {_v2821_percent(w1)} · 2. amir {_v2821_percent(w2)} · 3. amir {_v2821_percent(w3)}"
    detail = f"3. amir {'Açık' if level3 else 'Kapalı'} · {mode}"
    return _item(
        getattr(row, "id", ""),
        title,
        subtitle,
        status,
        detail,
        f"Toplam {_v2821_percent(total)}",
        100 if status == "Dengeli" else 55,
    )
