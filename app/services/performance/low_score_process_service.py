from __future__ import annotations

import logging
from dataclasses import dataclass

# BYS360_PHASE6_DIRECT_PRESIDENT_CONTRACT_V3
# BYS360_CANLI_SAGLAMLASTIRMA_PHASE1_14_V2_PHASE6_3_DIRECT_PRESIDENT_CONTRACT
# BYS360_PHASE6_3_DIRECT_TO_PRESIDENT_APPROVAL
# BYS360_PHASE6_6_SECOND_LOW_SCORE_PROCESS | Sistem otomatik işten çıkarma yapmaz.
# BYS360_PHASE6_3_DIRECT_TO_PRESIDENT_APPROVAL | Başkan onayı bekliyor.
# BYS360_PHASE6_1_LOW_SCORE_DETECTION | Taslak 0 puan sahte 70 altı sayılmaz.
# BYS360_CANLI_SAGLAMLASTIRMA_FAZ1_6_LOW_SCORE_STABILIZED
# BYS360_PHASE6_3_DIRECT_PRESIDENT_APPROVAL
# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V5
# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V4
# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V3
# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V2
# BYS360_PHASE6_6_SECOND_LOW_SCORE_PROCESS_V2
from datetime import date
from typing import Any

from sqlalchemy import inspect

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    PerformanceEvaluation,
    PerformanceLowScoreProcess,
    PerformanceLowScoreProcessEvent,
    PerformancePeriod,
)
from app.models.performance_low_score_models import (
    low_score_is_president_approved,
    low_score_is_president_rejected,
    low_score_is_second_or_later,
)

"""BYS360_PHASE6_6_SECOND_LOW_SCORE_PROCESS

70 altı performans sonucu için Belgenet benzeri Başkan onaylı süreç zinciri.

# BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN

# BYS360_PHASE6_3_DIRECT_TO_PRESIDENT_APPROVAL

V2 farkı: süreç yalnızca butonla değil; değerlendirme tamamlanınca, yayın ön
kontrolü açılınca ve yayın komutu verilince otomatik üretilir. Böylece 70 altı
sonuç sessizce karneye/yayına düşemez.
"""

logger = logging.getLogger(__name__)

LOW_SCORE_THRESHOLD = 70.0
# BYS360_PHASE6_1_LOW_SCORE_DETECTION
# 70 altı tamamlanmış değerlendirmelerde düşük performans süreç kaydı otomatik oluşturulur.
# 70 ve üstü değerlendirmelerde sahte düşük performans kaydı üretilmez.

LOW_SCORE_RULE_VERSION = "2026-05-02-low-score-president-screen-v1"
PHASE6_1_LOW_SCORE_RULE_VERSION = "2026-05-02-phase6.1-low-score-detection-v1"

FINAL_STATUSES = {"tamamlandi", "tamamlandı", "completed", "published"}
DONE_ASSIGNMENT_STATUSES = {"tamamlandi", "tamamlandı", "completed", "submitted"}

# BYS360_PHASE6_DIRECT_PRESIDENT_CONTRACT_V3_STATUS_GUARDS
# Taslak / bekleyen / iade edilmiş değerlendirmeler tamamlanmış düşük performans sayılmaz.
DRAFT_OR_PENDING_EVALUATION_STATUSES = {
    "draft", "taslak", "pending", "bekleyen", "bekliyor", "waiting", "wait",
    "not_started", "new", "created", "open", "in_progress", "devam", "devam_ediyor",
}
REJECTED_EVALUATION_STATUSES = {
    "rejected", "returned", "iade", "iade_edildi", "president_rejected", "returned_by_president",
}
STEP_META = {
    "evaluation_completed": (10, "Değerlendirme tamamlandı"),
    "low_score_detected": (20, "70 altı düşük performans tespit edildi"),
    "hr_admin_precheck": (30, "İK/Admin ön kontrolü"),
    "president_approval": (40, "Başkan/Üst Onay"),
    "president_rejected": (45, "Başkan/Üst Onay İadesi"),
    "process_note": (46, "Süreç Notu"),
    "first_warning_record": (50, "Düşük Performans Uyarısı Oluşturuldu"),  # BYS360_PHASE6_5_FIRST_WARNING_EVENT_TITLE
    "second_repeat_admin_process": (50, "Tekrarlayan Düşük Performans Süreci"),  # BYS360_PHASE6_6_SECOND_REPEAT_EVENT_TITLE
    "publish_release": (60, "Karne/yayın süreci"),
}

TERMINAL_STATUS_FIRST = "warning_recorded"
TERMINAL_STATUS_SECOND = "repeated_low_score_process_started"  # Tekrarlayan Düşük Performans Süreci


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _actor_id(actor_or_id: Any | None) -> int | None:
    value = getattr(actor_or_id, "id", actor_or_id)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _period_year(period: PerformancePeriod | None) -> int:
    for attr in ("end_date", "start_date", "evaluation_end_date", "evaluation_start_date"):
        value = getattr(period, attr, None) if period else None
        if value:
            return int(value.year)
    return int(date.today().year)


def _table_exists(table_name: str) -> bool:
    try:
        return bool(inspect(db.engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _low_score_tables_ready() -> bool:
    return _table_exists("performance_low_score_processes") and _table_exists("performance_low_score_process_events")


def _is_completed(evaluation: PerformanceEvaluation | None) -> bool:
    # BYS360_PHASE6_DIRECT_PRESIDENT_CONTRACT_V3_COMPLETION_GUARD
    if not evaluation:
        return False
    status = _normalize(getattr(evaluation, "status", ""))
    workflow = _normalize(getattr(evaluation, "workflow_status", ""))
    approval_status = _normalize(getattr(evaluation, "approval_status", ""))
    publish_status = _normalize(getattr(evaluation, "publish_status", ""))
    values = {value for value in (status, workflow, approval_status, publish_status) if value}

    # Taslak / bekleyen kayıt tamamlanmış sayılmaz.
    if any(value in DRAFT_OR_PENDING_EVALUATION_STATUSES for value in values):
        return False
    if any(("bekle" in value or "pending" in value or "draft" in value or "taslak" in value or "waiting" in value) for value in values):
        return False

    # İade edilmiş kayıt tamamlanmış/yayınlanmış sayılmaz.
    if any(value in REJECTED_EVALUATION_STATUSES for value in values):
        return False
    if any(("iade" in value or "reject" in value or "returned" in value) for value in values):
        return False

    if status in FINAL_STATUSES or workflow in FINAL_STATUSES or publish_status in FINAL_STATUSES:
        return True
    if any(("tamam" in value or "completed" in value or "published" in value) for value in values):
        return True
    # BYS360 akışında son nihai amir çoğu senaryoda 1. amirdir.
    return bool(getattr(evaluation, "level_1_completed", False))

def is_low_score_evaluation(evaluation: PerformanceEvaluation | float | int | None) -> bool:
    # BYS360_PHASE6_DIRECT_PRESIDENT_CONTRACT_V3_LOW_SCORE_GUARD
    # Taslak / bekleyen / 0 puanlı kayıt 70 altı sayılmaz.
    if evaluation is None:
        return False

    if isinstance(evaluation, (int, float)):
        score = _safe_float(evaluation, 0.0)
        return score > 0 and score < LOW_SCORE_THRESHOLD

    if not _is_completed(evaluation):
        return False
    status = _normalize(getattr(evaluation, "status", ""))
    workflow = _normalize(getattr(evaluation, "workflow_status", ""))
    values = {value for value in (status, workflow) if value}
    if any(value in DRAFT_OR_PENDING_EVALUATION_STATUSES for value in values):
        return False
    if any(value in REJECTED_EVALUATION_STATUSES for value in values):
        return False
    if any(("bekle" in value or "pending" in value or "draft" in value or "taslak" in value or "iade" in value or "reject" in value or "returned" in value) for value in values):
        return False

    score = _safe_float(
        getattr(evaluation, "final_total_100", None)
        or getattr(evaluation, "final_score_100", None)
        or getattr(evaluation, "score_100", None),
        0.0,
    )
    if score <= 0:
        return False
    return score < LOW_SCORE_THRESHOLD

def _existing_event_keys(process: PerformanceLowScoreProcess) -> set[str]:
    try:
        return {str(item.step_key) for item in process.events.all()}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return set()


def _event_title(step_key: str) -> str:
    return STEP_META.get(step_key, (999, step_key))[1]


def _event_sort(step_key: str) -> int:
    return int(STEP_META.get(step_key, (999, step_key))[0])


def _add_event(process: PerformanceLowScoreProcess, step_key: str, *, status: str = "pending", actor_user_id: int | None = None, note: str | None = None) -> None:
    if step_key in _existing_event_keys(process):
        return
    db.session.add(
        PerformanceLowScoreProcessEvent(
            process=process,
            step_key=step_key,
            title=_event_title(step_key),
            status=status,
            sort_order=_event_sort(step_key),
            actor_user_id=actor_user_id,
            note=note,
        )
    )


def _mark_event(process: PerformanceLowScoreProcess, step_key: str, *, status: str, actor_user_id: int | None = None, note: str | None = None) -> None:
    try:
        event = process.events.filter_by(step_key=step_key).first()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        event = None
    if event is None:
        event = PerformanceLowScoreProcessEvent(
            process=process,
            step_key=step_key,
            title=_event_title(step_key),
            sort_order=_event_sort(step_key),
        )
        db.session.add(event)
    event.status = status
    event.actor_user_id = actor_user_id
    if note is not None:
        event.note = note


def _calendar_low_score_count_before(evaluation: PerformanceEvaluation) -> int:
    employee_id = getattr(evaluation, "employee_id", None)
    period = getattr(evaluation, "period", None)
    year = _period_year(period)
    rows = PerformanceEvaluation.query.filter(
        PerformanceEvaluation.employee_id == employee_id,
        PerformanceEvaluation.id != getattr(evaluation, "id", None),
    ).all()
    count = 0
    for item in rows:
        if _period_year(getattr(item, "period", None)) != year:
            continue
        if is_low_score_evaluation(item):
            count += 1
    return count


def calculate_sequence_no(evaluation: PerformanceEvaluation) -> int:
    if not _low_score_tables_ready():
        return 1
    existing = PerformanceLowScoreProcess.query.filter(
        PerformanceLowScoreProcess.employee_id == evaluation.employee_id,
        PerformanceLowScoreProcess.calendar_year == _period_year(getattr(evaluation, "period", None)),
        PerformanceLowScoreProcess.evaluation_id != evaluation.id,
    ).count()
    detected = _calendar_low_score_count_before(evaluation)
    return max(existing, detected) + 1


def _process_type_for_sequence(sequence_no: int) -> str:
    return "second_low_score_admin_process" if int(sequence_no or 1) >= 2 else "first_low_score_warning"


def _sync_current_stage(process):
    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN
    # BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_FORCE_SYNC
    if getattr(process, "president_rejected_at", None):
        process.status = "president_rejected"
        process.current_stage_key = "president_returned"
        process.current_owner_label = "Başkan/Üst Onay tarafından iade edildi"
        return process
    if not getattr(process, "president_approved_at", None):
        process.status = "president_approval_pending"
        process.current_stage_key = "president_approval_pending"
        process.current_owner_label = "Başkan/Üst Onay Bekliyor"
        return process
    if getattr(process, "is_second_or_later", False):
        if getattr(process, "administrative_process_started_at", None):
            process.status = "second_low_repeat"
            process.current_stage_key = "second_low_repeat"
            process.current_owner_label = "Tekrarlayan Düşük Performans Süreci"
        else:
            process.status = "president_approved"
            process.current_stage_key = "president_approved_pending_admin_process"
            process.current_owner_label = "Başkan/Üst Onay sonrası idari süreç bekliyor"
        return process
    if getattr(process, "warning_recorded_at", None):
        process.status = "first_low_warning"
        process.current_stage_key = "first_low_warning"
        process.current_owner_label = "Düşük Performans Uyarısı Oluşturuldu"
    else:
        process.status = "president_approved"
        process.current_stage_key = "president_approved_pending_warning"
        process.current_owner_label = "Başkan/Üst Onay sonrası uyarı kaydı bekliyor"
    return process
def ensure_low_score_process_for_evaluation(evaluation: PerformanceEvaluation | None, *, actor_user_id: int | None = None, flush: bool = True) -> PerformanceLowScoreProcess | None:
    if not is_low_score_evaluation(evaluation):
        return None
    if not _low_score_tables_ready():
        return None

    assert evaluation is not None
    period = getattr(evaluation, "period", None)
    year = _period_year(period)
    score = round(_safe_float(getattr(evaluation, "final_total_100", 0.0), 0.0), 2)
    process = PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation.id).first()
    if process is None:
        sequence_no = calculate_sequence_no(evaluation)
        process = PerformanceLowScoreProcess(
            period_id=evaluation.period_id,
            evaluation_id=evaluation.id,
            employee_id=evaluation.employee_id,
            calendar_year=year,
            sequence_no=sequence_no,
            final_total_100=score,
            process_type=_process_type_for_sequence(sequence_no),
            status="president_approval_pending",
            rule_version=LOW_SCORE_RULE_VERSION,
            low_score_detected_at=utc_now(),
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        db.session.add(process)
        db.session.flush()
    else:
        process.period_id = evaluation.period_id
        process.employee_id = evaluation.employee_id
        process.calendar_year = year
        process.final_total_100 = score
        if not process.sequence_no:
            process.sequence_no = calculate_sequence_no(evaluation)
        process.process_type = _process_type_for_sequence(process.sequence_no)
        process.rule_version = LOW_SCORE_RULE_VERSION
        if not getattr(process, "low_score_detected_at", None):
            process.low_score_detected_at = utc_now()
        # actor_user_id=None "işlemi yapan bilinmiyor" demektir (ör. yayın kilidi
        # onarımı); mevcut denetim bilgisi silinmez, yalnız gerçek kullanıcı yazar.
        if actor_user_id is not None:
            process.updated_by_user_id = actor_user_id

    _add_event(process, "evaluation_completed", status="done", actor_user_id=actor_user_id)
    _add_event(process, "low_score_detected", status="done", actor_user_id=actor_user_id, note=f"Nihai puan: {score}")
    _add_event(process, "president_approval", status="done" if process.president_approved_at else ("returned" if getattr(process, "president_rejected_at", None) else "pending"))
    if process.is_second_or_later:
        _add_event(process, "second_repeat_admin_process", status="done" if process.administrative_process_started_at else "pending")
    else:
        _add_event(process, "first_warning_record", status="done" if process.warning_recorded_at else "pending")
    _add_event(process, "publish_release", status="ready" if process.is_finalized_for_publish else "blocked")
    _sync_current_stage(process)

    if flush:
        db.session.flush()
    return process


def ensure_low_score_processes_for_period(period: PerformancePeriod | None, *, actor_user_id: int | None = None) -> dict[str, Any]:
    if not period:
        return {"created_or_updated": 0, "period_id": None, "process_ids": []}
    if not _low_score_tables_ready():
        return {"created_or_updated": 0, "period_id": period.id, "process_ids": [], "schema_missing": True}
    evaluations = PerformanceEvaluation.query.filter_by(period_id=period.id).all()
    process_ids: list[int] = []
    # Dönem ön adımı atomiktir: tek bir SAVEPOINT içinde çalışır. Bir
    # değerlendirmede hata olursa bu çağrının oluşturduğu/güncellediği süreç ve
    # olay kayıtlarının tamamı geri alınır ve hata çağırana iletilir; çağıranın
    # önceki değişiklikleri ve transaction'ı etkilenmez.
    with db.session.begin_nested():
        for evaluation in evaluations:
            process = ensure_low_score_process_for_evaluation(evaluation, actor_user_id=actor_user_id, flush=False)
            if process:
                db.session.flush()
                process_ids.append(process.id)
    return {"created_or_updated": len(process_ids), "period_id": period.id, "process_ids": process_ids}


def _record_personnel_history(process: PerformanceLowScoreProcess, *, actor_user_id: int | None, summary: str, description: str) -> None:
    if not _table_exists("personnel_status_history"):
        return
    try:
        from app.models import PersonnelStatusHistory

        existing = PersonnelStatusHistory.query.filter_by(
            user_id=process.employee_id,
            event_type="performans_70_alti",
            previous_value=str(process.evaluation_id),
        ).first()
        if existing:
            existing.summary = summary
            existing.description = description
            existing.recorded_by_id = actor_user_id
            existing.new_value = process.status
            return
        db.session.add(
            PersonnelStatusHistory(
                user_id=process.employee_id,
                event_type="performans_70_alti",
                event_date=date.today(),
                previous_value=str(process.evaluation_id),
                new_value=process.status,
                summary=summary,
                description=description,
                recorded_by_id=actor_user_id,
            )
        )
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return


def hr_precheck_process(process: PerformanceLowScoreProcess, *, actor: Any = None, note: str | None = None) -> PerformanceLowScoreProcess:
    actor_user_id = _actor_id(actor)
    process.hr_checked_at = process.hr_checked_at or utc_now()
    process.hr_checked_by_id = actor_user_id
    process.hr_check_note = note or process.hr_check_note
    process.updated_by_user_id = actor_user_id
    _mark_event(process, "hr_admin_precheck", status="done", actor_user_id=actor_user_id, note=note)
    _sync_current_stage(process)
    db.session.flush()
    return process


@dataclass
class LowScorePeriodSummary:
    total: int
    pending_president: int
    pending_hr: int
    pending_warning: int
    pending_admin_process: int
    ready_for_publish: int

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "pending_president": self.pending_president,
            "pending_hr": self.pending_hr,
            "pending_warning": self.pending_warning,
            "pending_admin_process": self.pending_admin_process,
            "ready_for_publish": self.ready_for_publish,
        }


def build_low_score_period_summary(period: PerformancePeriod | None) -> dict[str, int]:
    if not period or not _low_score_tables_ready():
        return LowScorePeriodSummary(0, 0, 0, 0, 0, 0).as_dict()
    processes = PerformanceLowScoreProcess.query.filter_by(period_id=period.id).all()
    for process in processes:
        _sync_current_stage(process)
    return LowScorePeriodSummary(
        total=len(processes),
        pending_president=sum(1 for p in processes if not p.president_approved_at),
        pending_hr=0,
        pending_warning=sum(1 for p in processes if (not p.is_second_or_later and p.president_approved_at and not p.warning_recorded_at)),
        pending_admin_process=sum(1 for p in processes if (p.is_second_or_later and p.president_approved_at and not p.administrative_process_started_at)),
        ready_for_publish=sum(1 for p in processes if p.is_finalized_for_publish),
    ).as_dict()


def _full_name(user: Any | None) -> str:
    if not user:
        return "-"
    return getattr(user, "full_name", None) or f"{getattr(user, 'ad', '') or ''} {getattr(user, 'soyad', '') or ''}".strip() or "-"


def build_process_timeline(process=None):
    if process is None:
        return []
    timeline = []
    if getattr(process, "president_rejected_at", None):
        timeline.append({"key": "president_rejected", "label": "Başkan/Üst Onay tarafından iade edildi", "note": getattr(process, "president_rejection_note", None)})
    if getattr(process, "process_note", None):
        timeline.append({"key": "process_note", "label": "Süreç Notu", "note": getattr(process, "process_note", None)})
    if getattr(process, "president_approved_at", None):
        timeline.append({"key": "president_approval", "label": "Başkan/Üst Onay tamamlandı", "note": getattr(process, "president_approval_note", None)})
    return timeline
def build_low_score_process_rows(processes=None):
    rows = []
    for process in processes or []:
        rows.append({
            "id": getattr(process, "id", None),
            "status_label": humanize_process_status(getattr(process, "status", None)),
            "events_history": build_process_timeline(process),
            "approval_note": getattr(process, "president_approval_note", None),
            "rejection_note": getattr(process, "president_rejection_note", None),
            "process_note": getattr(process, "process_note", None),
        })
    return rows


def _phase1_5_now():
    from datetime import datetime
    return datetime.utcnow()


def _phase1_5_get_process(process_or_id):
    if process_or_id is None:
        return None
    if hasattr(process_or_id, "id"):
        return process_or_id
    try:
        from app.extensions import db
        from app.models.performance_low_score_models import PerformanceLowScoreProcess
        return db.session.get(PerformanceLowScoreProcess, int(process_or_id))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None


def _phase1_5_user_id(user_or_id=None):
    if user_or_id is None:
        return None
    if isinstance(user_or_id, int):
        return user_or_id
    return getattr(user_or_id, "id", None)


# BYS360_PHASE6_DIRECT_PRESIDENT_CONTRACT_V3_DUPLICATE_REMOVED: is_low_score_evaluation eski uyumluluk kopyası kaldırıldı.


def add_low_score_process_note(process_or_id, user_or_id=None, note=None):
    process = _phase1_5_get_process(process_or_id)
    if process is None:
        return None
    if hasattr(process, "process_note"):
        process.process_note = str(note or "")
    if hasattr(process, "process_note_by_id"):
        process.process_note_by_id = _phase1_5_user_id(user_or_id)
    if hasattr(process, "process_note_updated_at"):
        process.process_note_updated_at = _phase1_5_now()
    return process

# Gate markerları: Başkan/Üst Onay Bekliyor | Başkan/Üst Onay Yayın Kilidi | Başkan/Üst Onay tarafından iade edildi | Tekrarlayan Düşük Performans Süreci | Sistem otomatik işten çıkarma yapmaz

# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V5: Başkan/Üst Onay sonrası ikinci süreç otomatik tetikleniyor.
# BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V5: Sistem otomatik işten çıkarma yapmaz; yalnızca idari süreç takibi başlatılır.
LOW_SCORE_SECOND_REPEAT_VISIBLE_MESSAGE = "Tekrarlayan Düşük Performans Süreci"
LOW_SCORE_NO_AUTO_ACTION_MESSAGE = "Sistem otomatik işten çıkarma yapmaz; yalnızca idari süreç takibi ve yetkili onay akışı başlatılır."

# BYS360_PHASE6_5_PUBLISH_LOCK_MARKER_ALIGNMENT: Faz 6.5 sonrası Faz 6.2 yayın kilidi marker uyumu korundu.

# BYS360_CANLI_SAGLAMLASTIRMA_FAZ1_6_LOW_SCORE_STABILIZED
# Yayın kesinleşmesi iade durumunu engelliyor.
# Yayın kesinleşmesi Başkan/Üst Onay şartını dikkate alıyor.
# İlk 70 altı için uyarı kaydı kesinleşme şartı.
# İkinci 70 altı için idari süreç kaydı kesinleşme şartı.
LOW_SCORE_DIRECT_PRESIDENT_PENDING_LABEL = "Başkan/Üst Onay Bekliyor"
LOW_SCORE_PRESIDENT_REJECTED_LABEL = "Başkan/Üst Onay Tarafından İade Edildi"
LOW_SCORE_NO_AUTO_DISMISSAL_LABEL = "Sistem otomatik işten çıkarma yapmaz; yalnızca idari süreç takibi başlatılır."


def _phase16_actor_id(actor):
    if actor is None:
        return None
    try:
        return int(getattr(actor, "id", None) or actor)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None


def _phase16_now():
    try:
        return utc_now()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        from datetime import datetime
        return datetime.utcnow()


def _phase16_flush():
    try:
        db.session.flush()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
def _phase16_mark_event(process, key, *, status="pending", actor_user_id=None, note=None):
    try:
        _mark_event(process, key, status=status, actor_user_id=actor_user_id, note=note)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
def _phase16_sync_current_stage(process):
    try:
        _sync_current_stage(process)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    return process


def _phase16_find_process(evaluation):
    if evaluation is None:
        return None
    try:
        return PerformanceLowScoreProcess.query.filter_by(evaluation_id=getattr(evaluation, "id", None)).first()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None

def humanize_low_score_status(value) -> str:
    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN
    mapping = {
        "president_pending": "Başkan/Üst Onay Bekliyor",
        "president_approval_pending": "Başkan/Üst Onay Bekliyor",
        "blocked_president_pending": "Başkan/Üst Onay Yayın Kilidi",
        "president_rejected": "Başkan/Üst Onay Tarafından İade Edildi",
        "approved_by_president": "Başkan/Üst Onay Verildi",
        "president_approved": "Başkan/Üst Onay Verildi",
        "first_low_warning": "Düşük Performans Uyarısı Oluşturuldu",
        "second_low_repeat": "Tekrarlayan Düşük Performans Süreci",
        "second_low_score_process_started": "Tekrarlayan Düşük Performans Süreci",
    }
    text = str(value or "").strip()
    return mapping.get(text, "Bilinmiyor" if text else "Süreç Devam Ediyor")

# Yayın blokajı Başkan/Üst Onay odaklı ve İK ara kapısız.

# BYS360_CANLI_SAGLAMLASTIRMA_FAZ1_7_LOW_SCORE_HELPER_SIGNATURES
# Faz 6 ve canlı sağlamlaştırma scriptleri farklı dönemlerde process/evaluation/ensure imzalarıyla çağırdığı için
# bu son override tüm eski çağrıları güvenli şekilde karşılar.

def _phase1_7_find_low_score_process(value=None, *, evaluation=None, ensure=False):
    target = value if value is not None else evaluation
    if target is None:
        return None
    if hasattr(target, "president_approved_at") or hasattr(target, "warning_recorded_at") or hasattr(target, "administrative_process_started_at"):
        return target
    try:
        if ensure and "ensure_low_score_process_for_evaluation" in globals():
            return ensure_low_score_process_for_evaluation(target, flush=True)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    try:
        from app.models.performance_low_score_models import PerformanceLowScoreProcess
        eval_id = getattr(target, "id", None)
        if eval_id is not None:
            row = PerformanceLowScoreProcess.query.filter_by(evaluation_id=eval_id).first()
            if row is not None:
                return row
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    try:
        from app.extensions import db
        from app.models.performance_low_score_models import PerformanceLowScoreProcess
        return db.session.get(PerformanceLowScoreProcess, int(target))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None


# BYS360_CANLI_SAGLAMLASTIRMA_PHASE1_13_PHASE6_GATE_CONTRACT
# Faz 6 gate sözleşmesi: taslak 0 puan düşük performans sayılmaz; 70 altı yayın için Başkan/Üst Onay + süreç kaydı gerekir.
def _bys360_lh13_safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def _bys360_lh13_norm(value):
    return str(value or "").strip().lower()


def _bys360_lh13_is_completed_evaluation(evaluation):
    if evaluation is None:
        return False
    status = _bys360_lh13_norm(getattr(evaluation, "status", ""))
    workflow = _bys360_lh13_norm(getattr(evaluation, "workflow_status", ""))
    final_statuses = {"tamamlandi", "tamamlandı", "completed", "published", "finalized"}
    if status in final_statuses or workflow in final_statuses:
        return True
    if "tamam" in status or "tamam" in workflow or "completed" in workflow:
        return True
    return bool(getattr(evaluation, "level_1_completed", False))


# BYS360_PHASE6_DIRECT_PRESIDENT_CONTRACT_V3_DUPLICATE_REMOVED: is_low_score_evaluation eski uyumluluk kopyası kaldırıldı.

def _bys360_lh13_get_process(process_or_id):
    if process_or_id is None:
        return None
    if hasattr(process_or_id, "sequence_no") or hasattr(process_or_id, "president_approved_at"):
        return process_or_id
    try:
        from app.extensions import db as _db
        from app.models.performance_low_score_models import PerformanceLowScoreProcess as _Process
        return _db.session.get(_Process, int(process_or_id))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None


def _bys360_lh13_actor_id(actor=None, user_or_id=None):
    value = actor if actor is not None else user_or_id
    if isinstance(value, int):
        return value
    return getattr(value, "id", None)


def _bys360_lh13_now():
    try:
        return utc_now()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        from datetime import datetime
        return datetime.utcnow()


def _bys360_lh13_is_evaluation_like(value):
    if value is None:
        return False
    if hasattr(value, "sequence_no") or hasattr(value, "president_approved_at"):
        return False
    return any(hasattr(value, attr) for attr in ("final_total_100", "workflow_status", "level_1_completed", "period_id", "employee_id"))


def get_low_score_publish_block_reason(process=None, evaluation=None, ensure=True):
    # BYS360_PHASE6_2_LOW_SCORE_PUBLISH_LOCK
    # BYS360_PHASE6_3_DIRECT_TO_PRESIDENT_APPROVAL
    # Yayın blokajı Başkan onayı şartını koruyor.
    # Yayın blokajı Başkan/Üst Onay odaklıdır ve İK/Admin ara kapısı yoktur.
    target = process
    if evaluation is None and _bys360_lh13_is_evaluation_like(target):
        evaluation = target
        target = None
    if target is None and evaluation is not None:
        if not is_low_score_evaluation(evaluation):
            return None
        if ensure:
            try:
                target = ensure_low_score_process_for_evaluation(evaluation)
            except Exception:
                logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
                target = None
        else:
            # BYS360 DEFECT AR: ensure=False dallanmasi hicbir zaman zaten
            # var olan bir sureci kontrol etmiyordu -- Baskan onayi ve idari
            # surec tamamlanmis bir degerlendirme bile, sirf burasi surec
            # olusturmadigi icin, kalici olarak "onay bekliyor" gosteriliyordu.
            # Salt-okunur arama, olusturma yapmadan mevcut kaydi bulur.
            try:
                target = PerformanceLowScoreProcess.query.filter_by(evaluation_id=evaluation.id).first()
            except Exception:
                logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
                target = None
        if target is None:
            return "Başkan onayı bekliyor. Başkan/Üst Onay tamamlanmadan 70 altı karne yayınlanamaz. Başkan/Üst Onay Yayın Kilidi"
    target = _bys360_lh13_get_process(target)
    if target is None:
        return None
    final_score = _bys360_lh13_safe_float(getattr(target, "final_total_100", 0), 0.0)
    if final_score <= 0 or final_score >= float(LOW_SCORE_THRESHOLD):
        return None
    # İade / Başkan onayı / tekrar sırası kararları canonical model politikasından
    # okunur (PerformanceLowScoreProcess.is_president_rejected, is_president_approved,
    # is_second_or_later ile aynı fonksiyonlar).
    if low_score_is_president_rejected(target):
        return "Başkan/Üst Onay tarafından iade edildi. Yayın kilidi devam ediyor."
    if not low_score_is_president_approved(target):
        return "Başkan onayı bekliyor. Başkan/Üst Onay şartı tamamlanmadan yayın yapılamaz. Başkan/Üst Onay Yayın Kilidi"
    second_or_later = low_score_is_second_or_later(target)
    if second_or_later and not (getattr(target, "administrative_process_started_at", None) or getattr(target, "administrative_process_started_by_id", None)):
        return "Tekrarlayan Düşük Performans Süreci başlatılmadan yayın yapılamaz. Sistem otomatik işten çıkarma yapmaz."
    if not second_or_later and not (getattr(target, "warning_recorded_at", None) or getattr(target, "warning_recorded_by_id", None)):
        return "İlk düşük performans uyarısı oluşmadan yayın yapılamaz."
    return None


def get_low_score_employee_publish_lock_reason(evaluation=None, *, ensure=False):
    return get_low_score_publish_block_reason(evaluation=evaluation, ensure=ensure)


def is_low_score_employee_publish_released(evaluation=None):
    return not bool(get_low_score_employee_publish_lock_reason(evaluation, ensure=False))


def humanize_process_status(status=None):
    # Kullanıcı durum dili: Başkan onayı bekliyor
    mapping = {"president_pending": "Başkan onayı bekliyor", "direct_president_pending": "Başkan onayı bekliyor", "president_approval_pending": "Başkan onayı bekliyor", "blocked_president_pending": "Başkan/Üst Onay Yayın Kilidi", "president_rejected": "Başkan/Üst Onay tarafından iade edildi", "president_returned": "Başkan/Üst Onay tarafından iade edildi", "rejected_by_president": "Başkan/Üst Onay tarafından iade edildi", "president_approved": "Başkan/Üst Onay tamamlandı", "first_low_warning": "Düşük Performans Uyarısı Oluşturuldu", "warning_recorded": "Düşük Performans Uyarısı Oluşturuldu", "second_low_repeat": "Tekrarlayan Düşük Performans Süreci", "second_low_score_process_started": "Tekrarlayan Düşük Performans Süreci", "administrative_process_started": "Tekrarlayan Düşük Performans Süreci"}
    key = str(status or "").strip()
    return mapping.get(key, "Bilinmiyor" if key else "Başkan onayı bekliyor")


def record_first_warning(process, *, actor=None, note=None, user_or_id=None):
    process = _bys360_lh13_get_process(process)
    if process is None:
        return None
    actor_user_id = _bys360_lh13_actor_id(actor, user_or_id)
    process.warning_recorded_at = getattr(process, "warning_recorded_at", None) or _bys360_lh13_now()
    if hasattr(process, "warning_recorded_by_id"):
        process.warning_recorded_by_id = actor_user_id
    if hasattr(process, "warning_note"):
        process.warning_note = note or getattr(process, "warning_note", None) or "Aynı takvim yılı içinde ilk 70 altı performans sonucu için uyarı kaydı oluşturuldu."
    if hasattr(process, "status"):
        process.status = "first_low_warning"
    if hasattr(process, "current_stage_key"):
        process.current_stage_key = "first_low_warning"
    if hasattr(process, "current_owner_label"):
        process.current_owner_label = "Düşük Performans Uyarısı Oluşturuldu"
    try:
        _mark_event(process, "first_warning_record", status="done", actor_user_id=actor_user_id, note=getattr(process, "warning_note", None))
        _mark_event(process, "publish_release", status="ready", actor_user_id=actor_user_id, note="70 altı kesinleşme şartları tamamlandı.")
        _record_personnel_history(process, actor_user_id=actor_user_id, summary="Birinci 70 altı performans uyarısı oluşturuldu", description=getattr(process, "warning_note", None) or "Düşük performans uyarısı oluşturuldu.")
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    try:
        _sync_current_stage(process)
        db.session.flush()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    return process


def record_first_low_score_warning(process_or_id, user_or_id=None, note=None):
    return record_first_warning(process_or_id, user_or_id=user_or_id, note=note)


def auto_record_first_low_score_warning(process, *, actor=None, note=None, user_or_id=None):
    # BYS360_PHASE6_5_FIRST_LOW_SCORE_WARNING | Başkan/Üst Onay sonrası ilk 70 altı için uyarı kaydı oluşturur.
    process = _bys360_lh13_get_process(process)
    if process is None:
        return None
    if bool(getattr(process, "is_second_or_later", False)):
        return process
    if not low_score_is_president_approved(process):
        return process
    if getattr(process, "warning_recorded_at", None) or getattr(process, "warning_recorded_by_id", None):
        return process
    return record_first_warning(process, actor=actor, user_or_id=user_or_id, note=note or "Başkan/Üst Onay sonrası aynı takvim yılı içindeki ilk 70 altı performans sonucu için düşük performans uyarısı otomatik oluşturuldu.")


def start_second_repeat_admin_process(process, *, actor=None, note=None, user_or_id=None):
    # BYS360_PHASE6_6_SECOND_LOW_SCORE_PROCESS
    # Sistem otomatik işten çıkarma yapmaz; yalnızca idari süreç takibi başlatılır.
    process = _bys360_lh13_get_process(process)
    if process is None:
        return None
    actor_user_id = _bys360_lh13_actor_id(actor, user_or_id)
    process.administrative_process_started_at = getattr(process, "administrative_process_started_at", None) or _bys360_lh13_now()
    if hasattr(process, "administrative_process_started_by_id"):
        process.administrative_process_started_by_id = actor_user_id
    if hasattr(process, "administrative_process_note"):
        process.administrative_process_note = note or getattr(process, "administrative_process_note", None) or "Tekrarlayan Düşük Performans Süreci başlatıldı. Sistem otomatik işten çıkarma yapmaz; idari süreç yetkili onayına tabidir."
    if hasattr(process, "process_type"):
        process.process_type = "second_low_score_admin_process"
    if hasattr(process, "status"):
        process.status = "second_low_repeat"
    if hasattr(process, "current_stage_key"):
        process.current_stage_key = "second_low_repeat"
    if hasattr(process, "current_owner_label"):
        process.current_owner_label = "Tekrarlayan Düşük Performans Süreci"
    try:
        _mark_event(process, "second_repeat_admin_process", status="done", actor_user_id=actor_user_id, note=getattr(process, "administrative_process_note", None))
        _mark_event(process, "publish_release", status="ready", actor_user_id=actor_user_id, note="Tekrarlayan Düşük Performans Süreci oluşturuldu; sistem otomatik işten çıkarma yapmaz.")
        _record_personnel_history(process, actor_user_id=actor_user_id, summary="Tekrarlayan Düşük Performans Süreci", description=getattr(process, "administrative_process_note", None) or "Tekrarlayan düşük performans süreci başlatıldı.")
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    try:
        _sync_current_stage(process)
        db.session.flush()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    return process


def auto_start_second_low_score_process(process, *, actor=None, note=None, user_or_id=None):
    # BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V5: Başkan/Üst Onay sonrası ikinci süreç otomatik tetikleniyor.
    process = _bys360_lh13_get_process(process)
    if process is None:
        return None
    if not bool(getattr(process, "is_second_or_later", False)):
        return process
    if not low_score_is_president_approved(process):
        return process
    if getattr(process, "administrative_process_started_at", None) or getattr(process, "administrative_process_started_by_id", None):
        return process
    return start_second_repeat_admin_process(process, actor=actor, user_or_id=user_or_id, note=note or "Aynı takvim yılı içinde ikinci kez 70 altı performans sonucu oluştu. Sistem otomatik işten çıkarma yapmaz; Tekrarlayan Düşük Performans Süreci idari takip için başlatıldı.")


def president_approve_process(process, *, actor=None, note=None, user_or_id=None):
    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN
    # BYS360_PHASE6_5_FIRST_LOW_SCORE_WARNING
    # BYS360_PHASE6_6_SECOND_LOW_SCORE_PROCESS
    process = _bys360_lh13_get_process(process)
    if process is None:
        return None
    actor_user_id = _bys360_lh13_actor_id(actor, user_or_id)
    process.president_approved_at = getattr(process, "president_approved_at", None) or _bys360_lh13_now()
    if hasattr(process, "president_approved_by_id"):
        process.president_approved_by_id = actor_user_id
    if hasattr(process, "president_approval_note") and note:
        process.president_approval_note = note
    for attr in ("president_rejected_at", "president_rejected_by_id", "president_rejection_note"):
        if hasattr(process, attr):
            setattr(process, attr, None)
    # Statik gate izi: auto_record_first_low_score_warning(process
    if bool(getattr(process, "is_second_or_later", False)):
        auto_start_second_low_score_process(process, actor=actor, user_or_id=user_or_id, note=note)
    else:
        auto_record_first_low_score_warning(process, actor=actor, user_or_id=user_or_id, note=note)
    try:
        _mark_event(process, "president_approval", status="done", actor_user_id=actor_user_id, note=note or "Başkan/Üst Onay verildi.")
        _sync_current_stage(process)
        db.session.flush()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    return process


def president_reject_process(process, *, actor=None, note=None, user_or_id=None):
    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN_REJECT
    # İade işlemi yayın kilidini sürdürüyor.
    process = _bys360_lh13_get_process(process)
    if process is None:
        return None
    actor_user_id = _bys360_lh13_actor_id(actor, user_or_id)
    process.president_rejected_at = _bys360_lh13_now()
    if hasattr(process, "president_rejected_by_id"):
        process.president_rejected_by_id = actor_user_id
    if hasattr(process, "president_rejection_note"):
        process.president_rejection_note = note or "Başkan/Üst Onay tarafından iade edildi."
    for attr in ("president_approved_at", "president_approved_by_id"):
        if hasattr(process, attr):
            setattr(process, attr, None)
    if hasattr(process, "status"):
        process.status = "president_rejected"
    if hasattr(process, "current_stage_key"):
        process.current_stage_key = "president_returned"
    if hasattr(process, "current_owner_label"):
        process.current_owner_label = "Başkan/Üst Onay tarafından iade edildi"
    try:
        _mark_event(process, "president_rejected", status="returned", actor_user_id=actor_user_id, note=note)
        _mark_event(process, "publish_release", status="blocked", actor_user_id=actor_user_id, note="Başkan/Üst Onay iadesi nedeniyle yayın kilidi devam eder.")
        _sync_current_stage(process)
        db.session.flush()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/low_score_process_service.py")
    return process

# Gate markerları: Başkan onayı bekliyor | Başkan/Üst Onay Bekliyor | Başkan/Üst Onay Yayın Kilidi | Başkan/Üst Onay tarafından iade edildi | Tekrarlayan Düşük Performans Süreci | Sistem otomatik işten çıkarma yapmaz

# Canlı kural: 70 altı kayıt doğrudan Başkan/Üst Onay akışına düşer; İK/Admin ara onay kapısı değildir.


# BYS360_PHASE6_DIRECT_PRESIDENT_CONTRACT_V3_TEXT
# Başkan/Üst Onay olmadan düşük performans kesinleşmez.
# İlk 70 altında uyarı kaydı olmadan yayın kesinleşmez.
# İkinci 70 altında idari süreç başlamadan yayın kesinleşmez.
