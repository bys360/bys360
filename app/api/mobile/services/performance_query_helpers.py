from __future__ import annotations

import logging
from statistics import mean
from typing import Any

from app.api.mobile.routes import _as_int, _has_global_scope
from app.extensions import db
from app.models import EvaluationAssignment, PerformanceResultSnapshot, User

logger = logging.getLogger(__name__)


def _performance_query_rollback_quietly() -> None:
    try:
        db.session.rollback()
    except Exception:
        logger.exception("BYS360 mobil performans sorgu yardımcısında rollback tamamlanamadı.")


def _assignment_query_for(user: User):
    q = EvaluationAssignment.query
    if _has_global_scope(user):
        return q
    return q.filter(EvaluationAssignment.evaluator_id == user.id)


def _snapshot_query_for(user: User):
    # Her dönem/personel için yalnız güncel sürüm (web anlık görüntü ekranlarıyla
    # aynı); eski sürümler tarihçe olarak veritabanında kalır.
    q = PerformanceResultSnapshot.query.filter(PerformanceResultSnapshot.is_current.is_(True))
    if _has_global_scope(user):
        return q
    return q.filter(PerformanceResultSnapshot.employee_id == user.id)


def _period_assignment_query(user: User, period_id: int):
    q = _assignment_query_for(user)
    try:
        return q.filter(EvaluationAssignment.period_id == period_id)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _performance_query_rollback_quietly()
        return q


def _period_snapshot_query(user: User, period_id: int):
    q = _snapshot_query_for(user)
    try:
        return q.filter(PerformanceResultSnapshot.period_id == period_id)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _performance_query_rollback_quietly()
        return q


def _score_value(row: Any) -> int:
    for name in ("final_total_100", "final_score", "score", "total_score", "average_score"):
        if hasattr(row, name):
            return _as_int(getattr(row, name), 0)
    return 0


def _safe_avg_score(q) -> int:
    try:
        rows = q.limit(300).all()
        scores = [_score_value(row) for row in rows if _score_value(row) > 0]
        return int(mean(scores)) if scores else 0
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return 0


def _low_score_count(q) -> int:
    try:
        rows = q.limit(500).all()
        return sum(1 for row in rows if 0 < _score_value(row) < 70)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return 0
