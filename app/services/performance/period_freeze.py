"""BYS360 P0: kilitli veya yayımlanmış dönem — görev kayıtları hiçbir yoldan değişmez.

Proje sahibi kararı (M-1 Q2/Q3): kilitli, sonuçları yayımlanmış veya personele yayımlanmış
değerlendirmesi olan dönemin görev ve değerlendirme kayıtları; hiyerarşi/personel yan etkileri,
doğrudan görev üretimi/senkronu ve personel silme dahil hiçbir yoldan değişmez (gerçek admin dahil).
Yetkili ve denetlenebilir bir yeniden açma süreci tanımlanana kadar bu kural için istisna yoktur.

Silme ve sıfırlama (Q3-1, sahip kararı a): dönemi silme, görev temizliği, personel silme ve tümünü
sıfırlama, dondurulmuş dönemin yanında yayını sonradan geri alınmış dönemi de değiştiremez. Yayını
geri almak geçmiş değerlendirmeleri silinebilir yapmaz. Yayın geçmişi şema değişikliği olmadan,
yayın/geri alma işlemlerinin kalıcı izlerinden okunur (``period_has_publication_history``).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_

from app.extensions import db
from app.models import (
    PerformanceEvaluation,
    PerformancePeriod,
    PerformancePublishLog,
    PerformanceResultSnapshot,
)

FROZEN_PERIOD_TASKS_MESSAGE = (
    "Dönem kilitli veya sonuçları yayımlanmış; görev kayıtları değiştirilemez. Hiçbir kayıt yazılmadı."
)
PROTECTED_PERIOD_DELETE_MESSAGE = (
    "Dönem kilitli, sonuçları yayımlanmış veya daha önce yayımlanmış; görev, değerlendirme ve yayın "
    "kayıtları silinemez. Hiçbir kayıt silinmedi."
)
PROTECTED_PERIOD_RELINK_MESSAGE = (
    "Dönem kilitli, sonuçları yayımlanmış veya daha önce yayımlanmış; plana yeniden bağlanamaz. Dönem, "
    "kilit, yayın, görev ve değerlendirme kayıtlarında hiçbir değişiklik yapılmadı."
)
RESET_ALL_PROTECTED_MESSAGE = (
    "Sistemde kilitli, sonuçları yayımlanmış veya daha önce yayımlanmış dönem var; tümünü sıfırlama "
    "yapılamaz. Hiçbir kayıt silinmedi."
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


class ProtectedPeriodRelinkError(PermissionError):
    """D1: korunan dönem plana yeniden bağlanamaz; ``period_id`` denetim kaydı içindir."""

    def __init__(self, period_id: int) -> None:
        super().__init__(PROTECTED_PERIOD_RELINK_MESSAGE)
        self.period_id = period_id


def period_has_publication_history(period: Any) -> bool:
    """Dönem bugün yayında olmasa da bir kez yayımlandıysa True.

    Yayın ve geri alma işlemleri iz bırakır: dönemin ``published_at``/``published_by_id`` alanı
    (geri alma yayımlayanı geri alanla değiştirir, boşaltmaz), değerlendirmenin
    ``published_to_employee_at``/``published_to_employee_by_id`` alanı, yayın defteri
    (``performance_publish_logs``) ve sonuç snapshot'ı. Aktörsüz servis çağrısı veya doğrudan SQL ile
    silinmiş iz görülemez.
    """
    if getattr(period, "published_at", None) is not None or getattr(period, "published_by_id", None) is not None:
        return True
    traced = (
        db.session.query(PerformanceEvaluation.id)
        .filter(
            PerformanceEvaluation.period_id == period.id,
            or_(
                PerformanceEvaluation.published_to_employee_at.isnot(None),
                PerformanceEvaluation.published_to_employee_by_id.isnot(None),
            ),
        )
        .first()
    )
    if traced is not None:
        return True
    for model in (PerformancePublishLog, PerformanceResultSnapshot):
        if db.session.query(model.id).filter(model.period_id == period.id).first() is not None:
            return True
    return False


def period_is_delete_protected(period: Any) -> bool:
    """Silme ve sıfırlama için: dondurulmuş veya yayın geçmişi olan dönem kimse tarafından silinmez."""
    return period_is_frozen(period) or period_has_publication_history(period)


def lock_period_for_deletion(period_id: int) -> PerformancePeriod | None:
    """Dönem satırını işlem sonuna kadar kilitler (PostgreSQL ``FOR UPDATE``) ve güncel halini okur.

    Her yayın dönem satırını yazar (``published_at``); kilitten sonra yapılan kontrol ile silme (ya da
    plan yeniden bağlama) arasında başka bir işlem dönemi yayımlayamaz veya kilitleyemez. ``of=`` yalnız dönem satırını kilitler: dönemin
    eager ilişkileri dış birleşim üretir ve PostgreSQL birleşimin boş olabilen tarafını kilitlemez.
    """
    return (
        db.session.query(PerformancePeriod)
        .filter(PerformancePeriod.id == period_id)
        .populate_existing()
        .with_for_update(of=PerformancePeriod)
        .first()
    )


def delete_protected_period_ids(*, lock: bool = False) -> list[int]:
    """Silinemeyecek dönemler; ``lock`` ile bütün dönem satırları işlem sonuna kadar kilitlenir."""
    query = db.session.query(PerformancePeriod).order_by(PerformancePeriod.id.asc())
    if lock:
        query = query.populate_existing().with_for_update(of=PerformancePeriod)
    return [int(period.id) for period in query.all() if period_is_delete_protected(period)]


__all__ = [
    "FROZEN_PERIOD_TASKS_MESSAGE",
    "PROTECTED_PERIOD_DELETE_MESSAGE",
    "PROTECTED_PERIOD_RELINK_MESSAGE",
    "ProtectedPeriodRelinkError",
    "RESET_ALL_PROTECTED_MESSAGE",
    "delete_protected_period_ids",
    "lock_period_for_deletion",
    "period_has_publication_history",
    "period_is_delete_protected",
    "period_is_frozen",
]
