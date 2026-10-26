"""BYS360 P0: kilitli veya yayımlanmış dönem — görev kayıtları hiçbir yoldan değişmez.

Proje sahibi kararı (M-1 Q2/Q3): kilitli, sonuçları yayımlanmış veya personele yayımlanmış
değerlendirmesi olan dönemin görev ve değerlendirme kayıtları; hiyerarşi/personel yan etkileri,
doğrudan görev üretimi/senkronu ve personel silme dahil hiçbir yoldan değişmez (gerçek admin dahil).
Yetkili ve denetlenebilir bir yeniden açma süreci tanımlanana kadar bu kural için istisna yoktur.
"""
from __future__ import annotations

from typing import Any

from app.extensions import db
from app.models import PerformanceEvaluation

FROZEN_PERIOD_TASKS_MESSAGE = (
    "Dönem kilitli veya sonuçları yayımlanmış; görev kayıtları değiştirilemez. Hiçbir kayıt yazılmadı."
)


def period_is_frozen(period: Any) -> bool:
    if bool(getattr(period, "is_locked", False)) or bool(getattr(period, "results_published", False)):
        return True
    published = (
        db.session.query(PerformanceEvaluation.id)
        .filter(PerformanceEvaluation.period_id == period.id, PerformanceEvaluation.is_published_to_employee.is_(True))
        .first()
    )
    return published is not None


__all__ = ["FROZEN_PERIOD_TASKS_MESSAGE", "period_is_frozen"]
