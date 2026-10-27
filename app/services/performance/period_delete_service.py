
"""BYS360 Performans dönemi silme servisi.

Bu servis, deneme veya hatalı açılmış performans dönemlerinin ilişkili
performans kayıtları nedeniyle silinememesi sorununu çözer. Seçili dönem
silinirken sadece o döneme bağlı performans artefaktları temizlenir; personel,
organizasyon ve genel kullanıcı kayıtlarına dokunulmaz.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy import inspect

from app.extensions import db
from app.models import AuditLog

logger = logging.getLogger(__name__)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PeriodDeleteResult:
    ok: bool
    period_id: int
    period_title: str = ""
    deleted: dict[str, int] = field(default_factory=dict)
    cleared: dict[str, int] = field(default_factory=dict)
    message: str = ""

    @property
    def total_deleted(self) -> int:
        return sum(int(value or 0) for value in self.deleted.values())

    @property
    def total_cleared(self) -> int:
        return sum(int(value or 0) for value in self.cleared.values())

    def short_summary(self) -> str:
        pieces: list[str] = []
        if self.total_deleted:
            pieces.append(f"{self.total_deleted} ilişkili kayıt silindi")
        if self.total_cleared:
            pieces.append(f"{self.total_cleared} kayıt dönem bağlantısından ayrıldı")
        return ", ".join(pieces) if pieces else "ilişkili kayıt bulunmadı"


def _bind():
    return db.session.get_bind()


def _has_table(table_name: str) -> bool:
    try:
        return bool(inspect(_bind()).has_table(table_name))
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        LOGGER.warning("BYS360 period_delete_service işleminde yakalanan hata loglandı: %r", exc)
        return False


def _table(table_name: str) -> sa.Table | None:
    if not _has_table(table_name):
        return None
    try:
        metadata = sa.MetaData()
        return sa.Table(table_name, metadata, autoload_with=_bind())
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        LOGGER.warning("BYS360 period_delete_service işleminde yakalanan hata loglandı: %r", exc)
        return None


def _has_column(table: sa.Table | None, column_name: str) -> bool:
    return bool(table is not None and column_name in table.c)


def _rowcount(result: Any) -> int:
    try:
        value = int(result.rowcount or 0)
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        LOGGER.warning("BYS360 period_delete_service işleminde yakalanan hata loglandı: %r", exc)
        value = 0
    return max(value, 0)


def _clean_ids(values: Iterable[Any]) -> list[int]:
    cleaned: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        try:
            item = int(value)
        except (TypeError, ValueError) as exc:
            LOGGER.warning("BYS360 period_delete_service işleminde yakalanan hata loglandı: %r", exc)
            continue
        if item in seen:
            continue
        cleaned.append(item)
        seen.add(item)
    return cleaned


def _select_ids(table_name: str, *conditions: Any) -> list[int]:
    table = _table(table_name)
    if table is None or "id" not in table.c:
        return []
    where_parts = [part for part in conditions if part is not None]
    if not where_parts:
        return []
    stmt = sa.select(table.c.id).where(sa.or_(*where_parts))
    return _clean_ids(db.session.execute(stmt).scalars().all())


def _select_ids_from_table(table: sa.Table | None, *conditions: Any) -> list[int]:
    """Ayni Table nesnesinden uretilen kosullarla id listesi toplar.

    Not: SQLAlchemy'de kosul farkli Table nesnesinden gelir, SELECT ise ayni
    tabloyu yeniden autoload ederse PostgreSQL DuplicateAlias hatasi uretebilir.
    Bu yardimci, SELECT ve WHERE tarafinda tek Table nesnesi kullanarak bu
    hatayi engeller.
    """
    if table is None or "id" not in table.c:
        return []
    where_parts = [part for part in conditions if part is not None]
    if not where_parts:
        return []
    stmt = sa.select(table.c.id).where(sa.or_(*where_parts))
    return _clean_ids(db.session.execute(stmt).scalars().all())


def _delete_from_table(table: sa.Table | None, *conditions: Any) -> int:
    """Ayni Table nesnesinden uretilen kosullarla guvenli DELETE yapar.

    SQLAlchemy, DELETE ifadesinde WHERE kosulu farkli bir Table nesnesinden
    gelirse PostgreSQL tarafinda `DELETE ... USING ayni_tablo` ureterek
    DuplicateAlias hatasina sebep olabilir. Bu yardimci, DELETE ve WHERE
    tarafinda tek Table nesnesini kullanir.
    """
    if table is None:
        return 0
    where_parts = [part for part in conditions if part is not None]
    if not where_parts:
        return 0
    return _rowcount(db.session.execute(table.delete().where(sa.or_(*where_parts))))


def _delete_by_ids(table_name: str, column_name: str, values: Iterable[Any]) -> int:
    ids = _clean_ids(values)
    if not ids:
        return 0
    table = _table(table_name)
    if table is None or not _has_column(table, column_name):
        return 0
    return _rowcount(db.session.execute(table.delete().where(table.c[column_name].in_(ids))))


def _delete_by_period(table_name: str, period_id: int, column_name: str = "period_id") -> int:
    table = _table(table_name)
    if table is None or not _has_column(table, column_name):
        return 0
    return _rowcount(db.session.execute(table.delete().where(table.c[column_name] == period_id)))


def _delete_by_period_or_evaluation(table_name: str, period_id: int, evaluation_ids: list[int]) -> int:
    table = _table(table_name)
    if table is None:
        return 0
    conditions: list[Any] = []
    if "period_id" in table.c:
        conditions.append(table.c.period_id == period_id)
    if evaluation_ids and "evaluation_id" in table.c:
        conditions.append(table.c.evaluation_id.in_(evaluation_ids))
    return _delete_from_table(table, *conditions)


def _clear_period_link(table_name: str, period_id: int, column_name: str = "period_id") -> int:
    table = _table(table_name)
    if table is None or not _has_column(table, column_name):
        return 0
    return _rowcount(
        db.session.execute(
            table.update()
            .where(table.c[column_name] == period_id)
            .values({column_name: None})
        )
    )


def _add_count(bucket: dict[str, int], table_name: str, value: int) -> None:
    if not value:
        return
    bucket[table_name] = int(bucket.get(table_name, 0) or 0) + int(value)


def _audit_period_delete(period_id: int, period_title: str, actor: Any, result: PeriodDeleteResult) -> None:
    try:
        db.session.add(
            AuditLog(
                user_id=getattr(actor, "id", None),
                action="performance_period_force_delete",
                entity_type="PerformancePeriod",
                entity_id=period_id,
                old_data_json=json.dumps(
                    {
                        "period_id": period_id,
                        "period_title": period_title,
                        "deleted": result.deleted,
                        "cleared": result.cleared,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                new_data_json=None,
                summary=f"Performans dönemi ilişkili kayıtlarıyla birlikte silindi: {period_title}",
                endpoint="performance_period_delete",
            )
        )
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        LOGGER.warning("BYS360 period_delete_service yardımcı işleminde bastırılan hata loglandı: %r", exc)
def delete_performance_period_with_related_records(period_id: int, actor: Any = None) -> PeriodDeleteResult:
    """Seçili performans dönemini bağlantılı performans kayıtlarıyla birlikte siler.

    Bilinçli kapsam:
    - Dönem görevleri, puanlama kayıtları, maddeler, yayın/snapshot kayıtları silinir.
    - Başkan/Üst Onay, düşük performans ve süreç motoru kayıtları silinir.
    - Dönem içi not, hatırlatma, aksatan amir, gelişim önerisi gibi dönem artefaktları silinir.
    - Personel/izin/devamsızlık gibi kurumsal ana kayıtlar silinmez; sadece dönem bağlantısı boşaltılır.
    """
    from app.services.performance.period_freeze import (
        PROTECTED_PERIOD_DELETE_MESSAGE,
        lock_period_for_deletion,
        period_is_delete_protected,
    )

    # P0 (Q3-1, sahip kararı a): dondurulmuş veya yayını geri alınmış dönem hiçbir çağrıdan silinmez.
    # Dönem satırı kilitlenir: kontrol ile silme arasında dönem yayımlanamaz.
    period = lock_period_for_deletion(period_id)
    if not period:
        return PeriodDeleteResult(False, period_id=period_id, message="Dönem bulunamadı.")
    if period_is_delete_protected(period):
        raise PermissionError(PROTECTED_PERIOD_DELETE_MESSAGE)

    period_title = str(getattr(period, "title", None) or getattr(period, "name", None) or f"#{period_id}")
    result = PeriodDeleteResult(True, period_id=period_id, period_title=period_title)

    evaluations = _table("performance_evaluations")
    evaluation_ids = _select_ids_from_table(evaluations, evaluations.c.period_id == period_id if evaluations is not None and "period_id" in evaluations.c else None)

    flows = _table("performance_process_flows")
    flow_conditions: list[Any] = []
    if flows is not None:
        if "period_id" in flows.c:
            flow_conditions.append(flows.c.period_id == period_id)
        if evaluation_ids and "evaluation_id" in flows.c:
            flow_conditions.append(flows.c.evaluation_id.in_(evaluation_ids))
    flow_ids = _select_ids_from_table(flows, *flow_conditions)

    low_processes = _table("performance_low_score_processes")
    low_conditions: list[Any] = []
    if low_processes is not None:
        if "period_id" in low_processes.c:
            low_conditions.append(low_processes.c.period_id == period_id)
        if evaluation_ids and "evaluation_id" in low_processes.c:
            low_conditions.append(low_processes.c.evaluation_id.in_(evaluation_ids))
    low_process_ids = _select_ids_from_table(low_processes, *low_conditions)

    feedback_requests = _table("feedback_requests")
    feedback_conditions: list[Any] = []
    if feedback_requests is not None:
        if "period_id" in feedback_requests.c:
            feedback_conditions.append(feedback_requests.c.period_id == period_id)
        if evaluation_ids and "evaluation_id" in feedback_requests.c:
            feedback_conditions.append(feedback_requests.c.evaluation_id.in_(evaluation_ids))
    feedback_request_ids = _select_ids_from_table(feedback_requests, *feedback_conditions)

    # FeedbackRequest ile FeedbackMeeting arasında bazı eski kurulumlarda çift yönlü
    # bağlantı oluşabildiği için önce toplantı referansını boşaltıyoruz.
    if feedback_request_ids:
        feedback_table = _table("feedback_requests")
        if feedback_table is not None and _has_column(feedback_table, "scheduled_meeting_id"):
            cleared_meetings = _rowcount(
                db.session.execute(
                    feedback_table.update()
                    .where(feedback_table.c.id.in_(feedback_request_ids))
                    .values({"scheduled_meeting_id": None})
                )
            )
            _add_count(result.cleared, "feedback_requests.scheduled_meeting_id", cleared_meetings)

    batches = _table("performance_import_batches")
    import_batch_ids = _select_ids_from_table(batches, batches.c.period_id == period_id if batches is not None and "period_id" in batches.c else None)

    feedback_flows = _table("performance_feedback_pipeline_flows")
    feedback_flow_ids = _select_ids_from_table(feedback_flows, feedback_flows.c.period_id == period_id if feedback_flows is not None and "period_id" in feedback_flows.c else None)

    # Çocuk tablolar: önce bağlı detay kayıtları temizlenir.
    for table_name, column_name, values in [
        ("performance_low_score_process_events", "process_id", low_process_ids),
        ("performance_process_flow_steps", "flow_id", flow_ids),
        ("performance_process_notifications", "flow_id", flow_ids),
        ("performance_president_approvals", "flow_id", flow_ids),
        ("performance_feedback_pipeline_steps", "flow_id", feedback_flow_ids),
        ("performance_import_batch_rows", "batch_id", import_batch_ids),
        ("feedback_meetings", "feedback_request_id", feedback_request_ids),
        ("mail_logs", "related_feedback_request_id", feedback_request_ids),
    ]:
        _add_count(result.deleted, table_name, _delete_by_ids(table_name, column_name, values))

    # Değerlendirme/dönem bağlantılı ayrıntı tabloları.
    for table_name in [
        "performance_evaluation_items",
        "performance_evaluation_history",
        "evaluation_publish_logs",
        "performance_scoring_history",
        "performance_president_approvals",
        "performance_process_notifications",
        "performance_result_snapshots",
        "performance_publish_logs",
        "feedback_requests",
        "performance_low_score_processes",
        "performance_process_flows",
        "performance_feedback_pipeline_flows",
        "performance_reminder_queue",
        "performance_overdue_manager_snapshots",
        "performance_scorecard_archive",
        "performance_interim_notes",
        "performance_interim_notes_live",
        "performance_period_targets",
        "performance_period_observation_notes",
        "performance_development_recommendations",
        "performance_process_report_snapshots",
        "performance_import_batches",
        "performance_weight_configs",
        "assignment_coverage_logs",
        "evaluation_assignments",
    ]:
        _add_count(result.deleted, table_name, _delete_by_period_or_evaluation(table_name, period_id, evaluation_ids))

    # İş kurumsal ana verisine dokunmadan sadece dönem bağlantısını boşalt.
    for table_name in ["personnel_leaves", "attendance_exceptions"]:
        _add_count(result.cleared, table_name, _clear_period_link(table_name, period_id))
    _add_count(result.deleted, "mail_logs", _delete_by_period("mail_logs", period_id, "related_period_id"))

    # En sonda değerlendirme ana kayıtları ve dönem silinir.
    _add_count(result.deleted, "performance_evaluations", _delete_by_period("performance_evaluations", period_id))
    db.session.delete(period)
    _audit_period_delete(period_id, period_title, actor, result)
    db.session.commit()

    result.message = f"Dönem silindi. {result.short_summary()}."
    return result
