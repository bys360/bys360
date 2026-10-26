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
from sqlalchemy import bindparam, inspect, select, text
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import (
    EvaluationAssignment,
    OrganizationUnit,
    PerformanceEvaluation,
    PerformancePeriod,
    PersonnelCategory,
    User,
)
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
    Dönem kapsamı kullanıcının birim, üst birim ve kategori adlarını da okur
    (``period_scope_assignment``); bunlar da karşılaştırılır.
    """
    columns = [column for column in User.__table__.columns if column.name not in ASSIGNMENT_NEUTRAL_USER_COLUMNS]
    unit = aliased(OrganizationUnit)
    parent = aliased(OrganizationUnit)
    query = (
        select(*columns, unit.name, unit.parent_id, parent.name, PersonnelCategory.name, PersonnelCategory.code)
        .outerjoin(unit, unit.id == User.organization_unit_id)
        .outerjoin(parent, parent.id == unit.parent_id)
        .outerjoin(PersonnelCategory, PersonnelCategory.id == User.performance_category_id)
        .where(User.is_active.is_(True), User.role != "admin")
        .order_by(User.id)
    )
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


# Dönem kaydına bağlantı: tablonun kendi dönem sütunu ya da bağlı olduğu değerlendirme/görev satırı.
# Yabancı anahtarı tanımlı sütunda gerçek hedef tablo kullanılır; tanımsız sütunda (eski ham SQL
# tabloları) ad kuralı geçerlidir.
_PERIOD_PARENT_TABLES = (PerformanceEvaluation.__tablename__, EvaluationAssignment.__tablename__)
_PERIOD_PARENT_LINKS = (
    ("evaluation_id", PerformanceEvaluation.__tablename__),
    ("performance_evaluation_id", PerformanceEvaluation.__tablename__),
    ("assignment_id", EvaluationAssignment.__tablename__),
    ("evaluation_assignment_id", EvaluationAssignment.__tablename__),
)


def _period_link(names: set[str], foreign_keys: dict[str, str]) -> tuple[str, str | None] | None:
    """(sütun, ara tablo) — ara tablo None ise sütun doğrudan dönem kimliğidir."""
    period_table = PerformancePeriod.__tablename__
    for column, target in foreign_keys.items():
        if target == period_table:
            return column, None
    if "period_id" in names and "period_id" not in foreign_keys:
        return "period_id", None
    for column, target in foreign_keys.items():
        if target in _PERIOD_PARENT_TABLES:
            return column, target
    for column, parent in _PERIOD_PARENT_LINKS:
        if column in names and column not in foreign_keys:
            return column, parent
    return None


def _users_period_ids(user_ids: list[int]) -> set[int]:
    """Silme işleminin dokunacağı dönemler.

    ``safe_delete_user_by_id`` kullanıcıya yabancı anahtarla bağlı her tablodaki satırı siler veya
    boşaltır (yayın kaydı, anlık görüntü, yayımlayan kişi dahil). Aynı tablo listesi
    veritabanından okunur; satır dönem kaydının kendisiyse, ``period_id`` taşıyorsa ya da bir
    değerlendirme/görev satırına bağlıysa o dönem dokunulmuş sayılır.
    """
    from app.services.safe_user_delete_service import _q, _user_fk_refs

    period_ids: set[int] = set()
    if not user_ids:
        return period_ids
    inspector = inspect(db.engine)
    links: dict[str, tuple[str, str | None] | None] = {}
    for ref in _user_fk_refs():
        table, column = ref["table"], ref["column"]
        if table not in links:
            names = {item["name"] for item in inspector.get_columns(table)}
            foreign_keys = {
                constrained: str(foreign_key.get("referred_table") or "")
                for foreign_key in inspector.get_foreign_keys(table)
                for constrained in foreign_key.get("constrained_columns") or []
            }
            links[table] = _period_link(names, foreign_keys)
        user_filter = f"t.{_q(column)} IN :user_ids"
        link = links[table]
        if table == PerformancePeriod.__tablename__:
            sql = f"SELECT t.id FROM {_q(table)} t WHERE {user_filter}"
        elif link is None:
            continue
        elif link[1] is None:
            sql = f"SELECT DISTINCT t.{_q(link[0])} FROM {_q(table)} t WHERE {user_filter}"
        else:
            sql = (
                f"SELECT DISTINCT p.period_id FROM {_q(table)} t JOIN {_q(link[1])} p ON p.id = t.{_q(link[0])} "
                f"WHERE {user_filter}"
            )
        query = text(sql).bindparams(bindparam("user_ids", expanding=True))
        period_ids |= {row[0] for row in db.session.execute(query, {"user_ids": list(user_ids)}).all() if row[0] is not None}
    return period_ids


def user_deletion_refusal(user_ids: list[int], plan: HierarchyChangePlan) -> str | None:
    """Silme bağlı satırları siler veya boşaltır: kilitli/yayımlanmış dönemde satırı olan kullanıcı
    kimse tarafından silinmez; aktif dönemi etkileyen silme gerçek admin dışında reddedilir."""
    touched = _users_period_ids(user_ids)
    for period_id in touched:
        period = db.session.get(PerformancePeriod, period_id)
        if period is not None and period_is_frozen(period):
            return FROZEN_PERIOD
    if plan.target is not None and not plan.actor_is_real_admin and user_deletion_requires_sync(user_ids, plan, touched):
        return NON_ADMIN_PERIOD_SYNC
    return None


def user_deletion_requires_sync(user_ids: list[int], plan: HierarchyChangePlan, touched: set[int] | None = None) -> bool:
    if plan.target is None:
        return False
    touched = _users_period_ids(user_ids) if touched is None else touched
    return plan.target.id in touched or any(user_id in plan.before for user_id in user_ids)


def commit_hierarchy_change(
    plan: HierarchyChangePlan, *, actor_user_id: int | None = None, force_sync: bool = False
) -> dict[str, Any] | None:
    """Değişikliği yazar; gerçek admin, açık hedef dönem ve görev üretimini etkileyen değişiklikte
    görev senkronuyla aynı işlemde.

    Senkronun döndürdüğü başarısızlık ``AssignmentSyncFailed`` olur; senkron sırasında çıkan
    hata olduğu gibi yükselir. İki durumda da hiçbir kayıt yazılmamıştır (senkron tek commit'ini
    en sonda yapar). Görev senkronu gerçekten çalıştıysa sonucunu, aksi halde None döndürür.
    """
    target = plan.target
    if (
        target is None
        or not plan.actor_is_real_admin
        or period_is_frozen(target)
        or not (force_sync or assignment_relevant_user_state() != plan.before)
    ):
        # Gerçek admin olmayan için buraya yalnız görev üretimini etkilemeyen değişiklik gelir.
        db.session.commit()
        return None
    result = generate_assignments_for_active_period(period_id=target.id, actor_user_id=actor_user_id)
    if not result or not result.get("ok"):
        db.session.rollback()
        message = (result or {}).get("message") or "Görev senkronu tamamlanamadı."
        logger.warning("BYS360 M-1 görev senkronu başarısız; hiyerarşi değişikliği geri alındı | period_id=%s | message=%s", target.id, message)
        raise AssignmentSyncFailed(message)
    # Senkron puanlama penceresi açılmadan erken döndüğünde kendi commit'ini yapmaz ve görev
    # yazmaz; bu durumda senkron yapılmış gibi gösterilmez.
    db.session.commit()
    return result if result.get("run_key") else None


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
    "user_deletion_refusal",
    "user_deletion_requires_sync",
]
