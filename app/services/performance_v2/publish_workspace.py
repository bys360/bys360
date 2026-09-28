from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from app.extensions import db
from app.models import PerformanceEvaluation
from app.services.mail_service import send_published_evaluation_notifications
from app.services.performance.low_score_process_service import ensure_low_score_processes_for_period
from app.services.performance.period_state_guard import (
    validate_publish_window,
    validate_unpublish_allowed,
)
from app.services.performance_admin_service import create_publish_log
from app.services.publish_service import (
    publish_evaluation as core_publish_evaluation,
    publish_period_results as core_publish_period_results,
    summarize_skip_reasons,
    unpublish_evaluation as core_unpublish_evaluation,
    unpublish_period_results as core_unpublish_period_results,
)

logger = logging.getLogger(__name__)


def _record_publish_log(period, actor: Any, action_type: str, evaluation_ids: Iterable[Any], note: str) -> None:
    """v2 yayın durum değişikliklerini eski yayın rotalarıyla aynı yayın
    defterine (performance_publish_logs, create_publish_log) yazar: kim, ne
    yaptı, hangi değerlendirme/personel, ne zaman. Durum değişikliğiyle aynı
    işlemde (commit öncesi) eklenir; yayın sırası ve sonucu değişmez."""
    ids = [int(value) for value in evaluation_ids or [] if value]
    if not ids:
        return
    actor_id = getattr(actor, "id", None)
    if not actor_id:
        # performance_publish_logs.actor_user_id zorunludur; aktörsüz çağrıda
        # yayını bozmamak için kayıt atlanır ve operatöre iz bırakılır.
        logger.warning("BYS360 v2 yayın defteri kaydı aktör olmadığı için atlandı | action=%s | adet=%s", action_type, len(ids))
        return
    employee_by_evaluation = dict(
        db.session.query(PerformanceEvaluation.id, PerformanceEvaluation.employee_id)
        .filter(PerformanceEvaluation.id.in_(ids))
        .all()
    )
    for evaluation_id in ids:
        create_publish_log(period.id, actor_id, action_type, evaluation_id, employee_by_evaluation.get(evaluation_id), note)


def publish_period_results(period, actor: Any = None):
    if not period:
        return {
            "period_id": None,
            "published_count": 0,
            "skipped": [{"reason": "Dönem bulunamadı."}],
            "skip_reasons_summary": [("Dönem bulunamadı.", 1)],
            "published_evaluation_ids": [],
        }

    ok, message = validate_publish_window(period)
    if not ok:
        return {
            "period_id": getattr(period, "id", None),
            "published_count": 0,
            "skipped": [{"reason": message}],
            "skip_reasons_summary": [(message, 1)],
            "published_evaluation_ids": [],
        }

    # BYS360_PHASE6_1_LOW_SCORE_AUTO_ON_PUBLISH
    ensure_low_score_processes_for_period(period, actor_user_id=getattr(actor, "id", None))
    db.session.flush()
    result = core_publish_period_results(period=period, acted_by=actor)
    _record_publish_log(period, actor, "bulk_publish", result.get("published_evaluation_ids", []), "V2 toplu yayın işlemi ile personele açıldı.")
    db.session.commit()
    notification_result = send_published_evaluation_notifications(
        period,
        result.get("published_evaluation_ids", []),
        actor_user_id=getattr(actor, "id", None),
    )
    db.session.commit()
    result["period_id"] = period.id
    result["notification_result"] = notification_result
    result["skip_reasons_summary"] = summarize_skip_reasons(result.get("skipped"))
    return result


def unpublish_period_results(period, actor: Any = None):
    if not period:
        return {
            "period_id": None,
            "unpublished_count": 0,
            "unpublished_evaluation_ids": [],
        }

    ok, message = validate_unpublish_allowed(period)
    if not ok:
        return {
            "period_id": getattr(period, "id", None),
            "unpublished_count": 0,
            "unpublished_evaluation_ids": [],
            "message": message,
        }

    result = core_unpublish_period_results(period=period, acted_by=actor)
    _record_publish_log(period, actor, "bulk_unpublish", result.get("unpublished_evaluation_ids", []), "V2 toplu yayından kaldırma işlemi uygulandı.")
    db.session.commit()
    result["period_id"] = period.id
    return result

def publish_single_evaluation(evaluation_id: int | None, period, actor: Any = None):
    """Seçili dönemde tek personel sonucunu personele açar.

    Toplu yayın akışını bozmadan, yalnızca seçilen değerlendirme kaydını yayınlar.
    70 altı Başkan onayı, yayın kilidi ve tamamlanma kontrolleri merkezi
    publish policy üzerinden korunur.
    """
    if not period:
        return {
            "ok": False,
            "period_id": None,
            "evaluation_id": evaluation_id,
            "published_count": 0,
            "message": "Dönem bulunamadı.",
            "notification_result": {},
        }

    if not evaluation_id:
        return {
            "ok": False,
            "period_id": period.id,
            "evaluation_id": None,
            "published_count": 0,
            "message": "Yayınlanacak personel kaydı seçilmedi.",
            "notification_result": {},
        }

    evaluation = db.session.get(PerformanceEvaluation, int(evaluation_id))
    if not evaluation or int(getattr(evaluation, "period_id", 0) or 0) != int(period.id):
        return {
            "ok": False,
            "period_id": period.id,
            "evaluation_id": evaluation_id,
            "published_count": 0,
            "message": "Seçilen değerlendirme bu döneme ait değil veya bulunamadı.",
            "notification_result": {},
        }

    ok, message = core_publish_evaluation(evaluation, acted_by=actor)
    if ok:
        _record_publish_log(period, actor, "publish", [evaluation.id], "V2 tekil yayın işlemi ile personele açıldı.")
    # Başarısız yayında bile düşük performans süreç kaydı / yayın kilidi gibi
    # kontrol kayıtları oluşmuş olabilir; bu izler kaybolmasın.
    db.session.commit()

    notification_result = {}
    if ok:
        notification_result = send_published_evaluation_notifications(
            period,
            [evaluation.id],
            actor_user_id=getattr(actor, "id", None),
        )
        db.session.commit()

    return {
        "ok": bool(ok),
        "period_id": period.id,
        "evaluation_id": evaluation.id,
        "employee_id": getattr(evaluation, "employee_id", None),
        "published_count": 1 if ok else 0,
        "message": message,
        "notification_result": notification_result,
    }


def unpublish_single_evaluation(evaluation_id: int | None, period, actor: Any = None):
    """Seçili dönemde tek personel sonucunu personel görünümünden kaldırır."""
    if not period:
        return {
            "ok": False,
            "period_id": None,
            "evaluation_id": evaluation_id,
            "unpublished_count": 0,
            "message": "Dönem bulunamadı.",
        }

    if not evaluation_id:
        return {
            "ok": False,
            "period_id": period.id,
            "evaluation_id": None,
            "unpublished_count": 0,
            "message": "Yayından kaldırılacak personel kaydı seçilmedi.",
        }

    evaluation = db.session.get(PerformanceEvaluation, int(evaluation_id))
    if not evaluation or int(getattr(evaluation, "period_id", 0) or 0) != int(period.id):
        return {
            "ok": False,
            "period_id": period.id,
            "evaluation_id": evaluation_id,
            "unpublished_count": 0,
            "message": "Seçilen değerlendirme bu döneme ait değil veya bulunamadı.",
        }

    was_published = bool(getattr(evaluation, "is_published_to_employee", False))
    ok, message = core_unpublish_evaluation(evaluation, acted_by=actor)
    if ok and was_published:
        _record_publish_log(period, actor, "unpublish", [evaluation.id], "V2 tekil yayından kaldırma işlemi uygulandı.")
    db.session.commit()
    return {
        "ok": bool(ok),
        "period_id": period.id,
        "evaluation_id": evaluation.id,
        "employee_id": getattr(evaluation, "employee_id", None),
        "unpublished_count": 1 if ok else 0,
        "message": message,
    }
