
"""Performans dönem kilidi, puanlama tarihi ve yayın sırası güvenlik kapısı."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from app.core.datetime_utils import utc_now

PROD_SAFE_STATUSES = {"tamamlandi", "tamamlandı", "completed", "final"}
BYS360_SCORING_AFTER_PERIOD_END_GUARD_MARKER = "BYS360_PERFORMANCE_SCORING_AFTER_PERIOD_END_GUARD_V1_2"


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return None


def _period_end_start_next_day(period: Any) -> datetime | None:
    end_date = getattr(period, "end_date", None)
    if isinstance(end_date, datetime):
        return datetime.combine(end_date.date() + timedelta(days=1), time.min)
    if isinstance(end_date, date):
        return datetime.combine(end_date + timedelta(days=1), time.min)
    return None


def _auto_scoring_start(period: Any) -> datetime | None:
    # BYS360_PERFORMANCE_SCORING_AFTER_PERIOD_END_GUARD_V1_2
    # Puanlama dönem içinde başlayamaz. Kayıtlı scoring_start_date eski/yanlış şekilde
    # dönem bitişine eşit veya daha önceyse yok sayılır ve dönem bitişinden sonraki gün kullanılır.
    default_start = _period_end_start_next_day(period)
    scoring_start = _as_datetime(getattr(period, "scoring_start_date", None))
    if scoring_start:
        if default_start and scoring_start < default_start:
            return default_start
        return scoring_start
    if bool(getattr(period, "scoring_auto_start_after_period", True)):
        return default_start
    return default_start


def _scoring_end(period: Any) -> datetime | None:
    return _as_datetime(getattr(period, "scoring_end_date", None))


def validate_period_scores_mutable(period: Any) -> tuple[bool, str]:
    """Sonuçları yayınlanmış veya kilitli dönemde puan değiştiren hiçbir işlem yapılamaz."""
    if bool(getattr(period, "results_published", False)):
        return False, "Bu dönem sonuçları yayınlandığı için puanlama değişikliği yapılamaz."
    if bool(getattr(period, "is_locked", False)):
        return False, "Bu dönem kilitli olduğu için puanlama değişikliği yapılamaz."
    return True, ""


def validate_scoring_window(period: Any, *, now: datetime | None = None) -> tuple[bool, str]:
    if period is None:
        return False, "Performans dönemi bulunamadı."
    mutable, message = validate_period_scores_mutable(period)
    if not mutable:
        return False, message
    current = now or utc_now()
    start_at = _auto_scoring_start(period)
    if start_at and current < start_at:
        return False, f"Puanlama dönemi henüz başlamadı. Puanlama başlangıcı: {start_at.strftime('%d.%m.%Y %H:%M')}"
    end_at = _scoring_end(period)
    if end_at and current > end_at:
        return False, f"Puanlama süresi sona erdi. Bitiş: {end_at.strftime('%d.%m.%Y %H:%M')}"
    return True, "Puanlama dönemi açık."


def ensure_scoring_window_open(period: Any) -> None:
    ok, message = validate_scoring_window(period)
    if not ok:
        raise ValueError(message)


def validate_publish_window(period: Any, *, now: datetime | None = None) -> tuple[bool, str]:
    if period is None:
        return False, "Dönem bulunamadı."
    if bool(getattr(period, "results_published", False)):
        return False, "Bu dönem daha önce yayınlanmış. Tekrar yayınlamak yerine önce yayından kaldırma/geri alma süreci kullanılmalıdır."
    current = now or utc_now()
    start_at = _auto_scoring_start(period)
    if start_at and current < start_at:
        return False, f"Puanlama başlamadan yayın yapılamaz. Puanlama başlangıcı: {start_at.strftime('%d.%m.%Y %H:%M')}"
    end_date = getattr(period, "end_date", None)
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    if isinstance(end_date, date) and current.date() <= end_date:
        return False, "Performans dönemi bitmeden sonuç yayını başlatılamaz."
    return True, "Yayın ön sıralama kontrolü geçti."


def validate_unpublish_allowed(period: Any) -> tuple[bool, str]:
    if period is None:
        return False, "Dönem bulunamadı."
    if not bool(getattr(period, "results_published", False)):
        return False, "Bu dönem zaten personel görünümünde yayınlanmış görünmüyor."
    return True, "Yayından kaldırma yapılabilir."
