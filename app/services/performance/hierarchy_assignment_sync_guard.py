"""BYS360 P0 / M-1: hiyerarşi ve personel yazımlarının tetiklediği dönem geneli görev senkronu.

Amir zinciri, personel ekleme/düzenleme ve Excel içe aktarma kayıtları, dönem için görevleri
``generate_assignments_for_active_period`` ile yeniden üretir. Proje sahibi kararı (M-1, b):

- Gerçek admin olmayan kullanıcı için hedef dönem yalnız aktif dönemdir; istemcinin gönderdiği
  dönem senkronu yönlendirmez. Aktif dönem varken görev üretimini etkileyen bir değişiklik bütün
  olarak reddedilir (hiçbir kayıt yazılmaz). Aktif dönem yoksa R05 hiyerarşi yetkileri aynen kalır.
- Kilitli, sonuçları yayımlanmış veya yayımlanmış değerlendirmesi olan dönem bu dolaylı yoldan
  değişmez; gerçek admin dahil, böyle bir döneme dokunacak değişiklik reddedilir.
- Gerçek admin için hiyerarşi kaydı ve görev senkronu tek işlemdir: senkron başarısızsa ikisi de
  geri alınır ve başarı olarak gösterilmez.

Kullanım: ``plan = begin_hierarchy_change(...)`` değişiklikten önce; değişiklik oturuma
uygulandıktan sonra, kalıcı yan etkiden (dosya kaydı) ve commit'ten önce
``hierarchy_change_refusal(plan)``; izin verilirse ``commit_hierarchy_change(plan)``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models import PerformanceEvaluation, PerformancePeriod, User
from app.services.account_change_guard import is_real_admin
from app.services.performance.assignments import generate_assignments_for_active_period

logger = logging.getLogger(__name__)

# Görev üretimini etkilemeyen kullanıcı sütunları; listede olmayan (ileride eklenecekler dahil)
# her sütun görev üretimini etkiler sayılır.
ASSIGNMENT_NEUTRAL_USER_COLUMNS = frozenset({
    "password_hash",
    "profile_photo_path",
    "profile_photo_updated_at",
    "birth_date",
    "celebration_opt_out",
    "failed_login_attempts",
    "captcha_required",
    "must_change_password",
    "must_set_security_question",
    "security_question",
    "security_answer_hash",
    "is_first_login",
    "security_stamp",
    "created_at",
    "updated_at",
})

NON_ADMIN_PERIOD_SYNC = "non_admin_period_sync"
FROZEN_PERIOD = "frozen_period"


class AssignmentSyncFailed(RuntimeError):
    """Görev senkronu tamamlanamadı; hiyerarşi değişikliği de geri alındı."""


@dataclass
class HierarchyChangePlan:
    actor_is_real_admin: bool
    target: PerformancePeriod | None
    before: dict[int, tuple[Any, ...]] = field(default_factory=dict)


def _active_period() -> PerformancePeriod | None:
    return PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()


def assignment_relevant_user_state() -> dict[int, tuple[Any, ...]]:
    """Görev üretiminin okuduğu kullanıcılar ve alanları; oturumdaki yazılmamış değişiklikler dahil.

    Senkron yalnız aktif ve admin olmayan kullanıcıları okur (``performance_v2.sync_service``
    ``_employee_query``); bu kümeye giren veya kümeden çıkan kullanıcı da değişiklik sayılır.
    """
    columns = [column for column in User.__table__.columns if column.name not in ASSIGNMENT_NEUTRAL_USER_COLUMNS]
    query = select(*columns).where(User.is_active.is_(True), User.role != "admin").order_by(User.id)
    return {row[0]: tuple(row) for row in db.session.execute(query).all()}


def period_is_frozen(period: PerformancePeriod) -> bool:
    if bool(getattr(period, "is_locked", False)) or bool(getattr(period, "results_published", False)):
        return True
    published = (
        db.session.query(PerformanceEvaluation.id)
        .filter(PerformanceEvaluation.period_id == period.id, PerformanceEvaluation.is_published_to_employee.is_(True))
        .first()
    )
    return published is not None


def begin_hierarchy_change(explicit_period_id: int | None = None, *, actor: Any = None) -> HierarchyChangePlan:
    """Değişiklikten önce çağrılır: senkron hedefi ve görev üretimini etkileyen alanların ilk hali."""
    actor = current_user if actor is None else actor
    real_admin = is_real_admin(actor)
    target = None
    if real_admin and explicit_period_id:
        target = db.session.get(PerformancePeriod, explicit_period_id)
    if target is None:
        target = _active_period()
    plan = HierarchyChangePlan(actor_is_real_admin=real_admin, target=target)
    if target is not None:
        plan.before = assignment_relevant_user_state()
    return plan


def hierarchy_change_refusal(plan: HierarchyChangePlan) -> str | None:
    """Değişiklik oturuma uygulandıktan sonra, commit'ten önce: red nedeni veya None."""
    if plan.target is None or assignment_relevant_user_state() == plan.before:
        return None
    if not plan.actor_is_real_admin:
        return NON_ADMIN_PERIOD_SYNC
    if period_is_frozen(plan.target):
        return FROZEN_PERIOD
    return None


def commit_hierarchy_change(plan: HierarchyChangePlan, *, actor_user_id: int | None = None) -> dict[str, Any] | None:
    """Değişikliği yazar; gerçek admin ve açık hedef dönemde görev senkronuyla aynı işlemde.

    Senkronun döndürdüğü başarısızlık ``AssignmentSyncFailed`` olur; senkron sırasında çıkan
    hata olduğu gibi yükselir. İki durumda da hiçbir kayıt yazılmamıştır (senkron tek commit'ini
    en sonda yapar).
    """
    target = plan.target
    if target is None or not plan.actor_is_real_admin or period_is_frozen(target):
        # Gerçek admin olmayan için buraya yalnız görev üretimini etkilemeyen değişiklik gelir.
        db.session.commit()
        return None
    result = generate_assignments_for_active_period(period_id=target.id, actor_user_id=actor_user_id)
    if not result or not result.get("ok"):
        db.session.rollback()
        message = (result or {}).get("message") or "Görev senkronu tamamlanamadı."
        logger.warning("BYS360 M-1 görev senkronu başarısız; hiyerarşi değişikliği geri alındı | period_id=%s | message=%s", target.id, message)
        raise AssignmentSyncFailed(message)
    # Senkron puanlama penceresi açılmadan erken döndüğünde kendi commit'ini yapmaz.
    db.session.commit()
    return result


__all__ = [
    "ASSIGNMENT_NEUTRAL_USER_COLUMNS",
    "FROZEN_PERIOD",
    "NON_ADMIN_PERIOD_SYNC",
    "AssignmentSyncFailed",
    "HierarchyChangePlan",
    "assignment_relevant_user_state",
    "begin_hierarchy_change",
    "commit_hierarchy_change",
    "hierarchy_change_refusal",
    "period_is_frozen",
]
