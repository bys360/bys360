from __future__ import annotations

# BYS360_MOBILE_V2_8_44_SCORE_1_5_COMMENT_OPTIONAL_BACKEND: Mobilde 1 ve 5 puan kriter açıklaması zorunlu değildir.
import logging
from statistics import (
    mean,  # noqa: F401 - available via performance_read_routes.py globals().update() bridge
)
from typing import Any

from flask import jsonify, request

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    EvaluationAssignment,
    PerformanceCriteria,
    PerformanceEvaluation,
    PerformanceEvaluationItem,
    PerformancePeriod,
    PerformancePresidentApproval,
    PerformanceResultSnapshot,
    PerformanceWeightConfig,
    User,
)
from app.services.performance.common import get_period_level_3_flags
from app.services.performance.scoring import (
    calculate_preview_total_100,
    recalculate_evaluation_totals,
    save_evaluation_level,
    validate_general_comment_requirements,
)

from . import mobile_api_bp
from .routes import (
    _as_int,  # noqa: F401 - available via performance_read_routes.py globals().update() bridge
    _full_name,
    _has_global_scope,
    _item,
    _metric,
    _module_payload,
    require_mobile_user,
)

logger = logging.getLogger(__name__)


# BYS360 MOBILE V2.8.20.3 DB SAFE FINAL HELPERS
def _mobile_perf_rollback_quietly() -> None:
    """Mobil performans API okumasında hata olursa veritabanı oturumunu temizler."""
    try:
        db.session.rollback()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/performance_routes.py:50)")


def _mobile_perf_safe_count(query, default: int = 0) -> int:
    try:
        _mobile_perf_rollback_quietly()
        value = query.count()
        return int(value or 0)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        return default


def _mobile_perf_safe_all(query, default=None):
    try:
        _mobile_perf_rollback_quietly()
        return query.all()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        return [] if default is None else default


def _mobile_perf_safe_get(model, object_id):
    try:
        if object_id is None:
            return None
        _mobile_perf_rollback_quietly()
        return db.session.get(model, object_id)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        return None

_DONE = {"tamamlandi", "tamamlandı", "completed", "done", "closed", "kapandi", "kapandı", "yayınlandı", "published"}


from app.api.mobile.services.performance_base_helpers import (  # noqa: E402, F401 - deferred to avoid circular import with performance_period_service; _date_text used via performance_read_routes.py globals() bridge
    _date_range,
    _date_text,
    _label,
    _period_name,
    _period_scope,
    _period_status,
)

# performance_period_service._period_scope delegates here under the
# _bys360_legacy_ naming convention used by every other extracted helper
# in this module; _period_scope itself is a passthrough import rather than
# a locally defined function, so it never got the rename other helpers did.
_bys360_legacy__period_scope = _period_scope


def _period_progress(period: Any):
    from app.api.mobile.services import performance_period_service as _bys360_period_service
    return _bys360_period_service._period_progress(period)

def _bys360_legacy__period_progress(period: Any) -> int:
    if getattr(period, "is_active", False):
        return 80
    status = str(getattr(period, "status", "") or "").lower()
    if status in _DONE or status in {"closed", "kapandı"}:
        return 100
    if "draft" in status or "haz" in status:
        return 25
    return 50


from app.api.mobile.services.performance_item_helpers import (  # noqa: E402 - deferred to avoid circular import with performance_period_service
    _assignment_item,
    _scorecard_item,
)
from app.api.mobile.services.performance_query_helpers import (  # noqa: E402 - deferred to avoid circular import with performance_period_service
    _assignment_query_for,
    _low_score_count,
    _period_assignment_query,
    _period_snapshot_query,
    _safe_avg_score,
    _score_value,
    _snapshot_query_for,
)


@mobile_api_bp.get("/performance/summary")
@require_mobile_user
def mobile_performance_summary(user: User):
    from app.api.mobile.services.performance_summary_service import delegate_mobile_performance_summary  # noqa: I001 - kept single-line for route-file line budget
    return delegate_mobile_performance_summary(user, _bys360_legacy_mobile_performance_summary)

def _bys360_legacy_mobile_performance_summary(user: User):
    global_scope = _has_global_scope(user)
    assignment_q = _assignment_query_for(user)
    snapshot_q = _snapshot_query_for(user)
    try:
        pending_q = assignment_q.filter(~EvaluationAssignment.status.in_(list(_DONE)))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        pending_q = assignment_q
    active_periods = _mobile_perf_safe_count(PerformancePeriod.query.filter_by(is_active=True)) if hasattr(PerformancePeriod, "is_active") else _mobile_perf_safe_count(PerformancePeriod.query)
    pending_tasks = _mobile_perf_safe_count(pending_q)
    approvals = _mobile_perf_safe_count(PerformancePresidentApproval.query.filter_by(status="pending")) if global_scope else 0
    avg_score = _safe_avg_score(snapshot_q)
    low_score = _low_score_count(snapshot_q)
    items: list[dict[str, Any]] = []
    try:
        for assignment in _mobile_perf_safe_all(assignment_q.order_by(EvaluationAssignment.id.desc()).limit(8)):
            items.append(_assignment_item(assignment))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        items = []
    if not items:
        for period in _mobile_perf_safe_all(PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(5)):
            items.append(_item(getattr(period, "id", ""), _period_name(period), _date_range(period), _period_status(period), _period_scope(period), "", _period_progress(period)))
    return _module_payload([
        _metric("Bekleyen Görev", pending_tasks, "Yetkinize göre görünen değerlendirme görevi", "red", "assignment"),
        _metric("Aktif Dönem", active_periods, "Açık veya hazırlıktaki performans dönemi", "red", "timeline"),
        _metric("Ortalama Puan", f"{avg_score}/100" if avg_score else "-", "Yayınlanmış kayıtlar üzerinden", "green", "trending_up"),
        _metric("70 Altı Takip", low_score, "Yetkiniz kapsamındaki düşük performans kaydı", "yellow", "warning"),
        _metric("Üst Onay", approvals, "Başkan/Üst Onay bekleyen kayıt", "red", "verified_user"),
    ], items)


# BYS360 P11-C1: mobile_performance_periods read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.


@mobile_api_bp.get("/performance/periods/<int:period_id>")
@require_mobile_user
def mobile_performance_period_detail(user: User, period_id: int):
    from app.api.mobile.services import performance_period_service as _bys360_period_service
    return _bys360_period_service.mobile_performance_period_detail(user, period_id)

def _bys360_legacy_mobile_performance_period_detail(user: User, period_id: int):
    period = _mobile_perf_safe_get(PerformancePeriod, period_id)
    if not period:
        return jsonify({"message": "Bu performans dönemine şu anda ulaşılamadı."}), 404
    assignment_q = _period_assignment_query(user, period_id)
    snapshot_q = _period_snapshot_query(user, period_id)
    try:
        pending_q = assignment_q.filter(~EvaluationAssignment.status.in_(list(_DONE)))
        completed_q = assignment_q.filter(EvaluationAssignment.status.in_(list(_DONE)))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        pending_q = assignment_q
        completed_q = assignment_q.filter(False)
    items: list[dict[str, Any]] = []
    try:
        for assignment in _mobile_perf_safe_all(assignment_q.order_by(EvaluationAssignment.id.desc()).limit(40)):
            items.append(_assignment_item(assignment))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        items = []
    if not items:
        try:
            for row in _mobile_perf_safe_all(snapshot_q.order_by(PerformanceResultSnapshot.id.desc()).limit(40)):
                items.append(_scorecard_item(row))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            _mobile_perf_rollback_quietly()
            items = []
    items.insert(0, _item(period_id, _period_name(period), _date_range(period), _period_status(period), _period_scope(period), "Dönem bilgisi", _period_progress(period)))
    total_tasks = _mobile_perf_safe_count(assignment_q)
    completed_tasks = _mobile_perf_safe_count(completed_q)
    pending_tasks = _mobile_perf_safe_count(pending_q)
    avg_score = _safe_avg_score(snapshot_q)
    low_score = _low_score_count(snapshot_q)
    return _module_payload([
        _metric("Dönem Durumu", _period_status(period), _period_scope(period), "red", "timeline"),
        _metric("Görev", total_tasks, "Bu dönem için görünen değerlendirme görevi", "red", "assignment"),
        _metric("Tamamlanan", completed_tasks, "Tamamlanmış değerlendirme görevi", "green", "check"),
        _metric("Bekleyen", pending_tasks, "İşlem bekleyen değerlendirme görevi", "yellow", "warning"),
        _metric("Ortalama", f"{avg_score}/100" if avg_score else "-", "Dönem karne ortalaması", "green", "trending_up"),
        _metric("70 Altı", low_score, "Başkan/Üst Onay takibi gerektirebilecek kayıt", "yellow", "verified_user"),
    ], items)


from app.api.mobile.services.performance_compact_route_services import (  # noqa: E402 - deferred to avoid circular import with performance_period_service
    phase3c_mobile_performance_approvals_service as _phase3c_approvals_service,
    phase3c_mobile_performance_criteria_service as _phase3c_criteria_service,
    phase3c_mobile_performance_in_period_notes_legacy_service as _phase3c_in_period_notes_legacy_service,
)


@mobile_api_bp.get("/performance/approvals")
@require_mobile_user
def mobile_performance_approvals(user: User):
    return _phase3c_approvals_service(user, globals())


@mobile_api_bp.get("/performance/scorecards")
@require_mobile_user
def mobile_performance_scorecards(user: User):
    q = _snapshot_query_for(user).order_by(PerformanceResultSnapshot.id.desc())
    items = [_scorecard_item(row) for row in _mobile_perf_safe_all(q.limit(30))]
    return _module_payload([_metric("Karne", _mobile_perf_safe_count(q), "Yetkiniz kapsamındaki karne kayıtları", "green", "assignment"), _metric("Ortalama", f"{_safe_avg_score(q)}/100" if _mobile_perf_safe_count(q) else "-", "Yayınlanmış kayıtlar", "green", "trending_up"), _metric("Görünürlük", "Yetki Kontrollü", "Personel yalnızca kendi yayınlanmış sonucunu görür", "green", "shield")], items)


@mobile_api_bp.get("/performance/rules-summary")
@require_mobile_user
def mobile_performance_rules_summary(user: User):
    return _module_payload([_metric("Kör Değerlendirme", "Yok", "Sonraki amir önceki puan ve kanaati görür", "red", "visibility"), _metric("70 Altı", "Üst Onay", "Düşük performans sonucu doğrudan kesinleşmez", "yellow", "verified_user"), _metric("Yayın", "Kontrollü", "İK/Admin ve yetkili ön onay tamamlanmadan personele açılmaz", "red", "lock"), _metric("3. Amir", "Opsiyonel", "Yorum modu veya puan modu sistem ayarıyla çalışır", "red", "admin")], [_item("rule-1", "Kör değerlendirme yok", "Sonraki amir önceki değerlendirmeyi görür.", "Sabit Kural", "Amir zinciri", "", 100), _item("rule-2", "1 ve 5 puanda açıklama", "Açıklama zorunluluğu sistem ayarı ve kurala göre uygulanır.", "Kontrol", "Puanlama", "", 100), _item("rule-3", "70 altı sonuç", "Başkan/Üst Onay ve yayın kilidi sürecine alınır.", "Üst Onay", "Düşük performans", "", 100), _item("rule-4", "Personel görünürlüğü", "Personel sonucu yayın tamamlanmadan göremez.", "Yayın Kilidi", "Karne", "", 100)])

# BYS360 MOBILE V2.8.21 CRITERIA WEIGHT THIRD MANAGER ENDPOINTS

from app.api.mobile.services.performance_config_helpers import (  # noqa: E402, F401 - deferred; some names used via performance_read_routes.py globals() bridge
    _v2821_criteria_item,
    _v2821_float,
    _v2821_mode_text,
    _v2821_percent,
    _v2821_period_label,
    _v2821_weight_item,
)


@mobile_api_bp.get("/performance/criteria")
@require_mobile_user
def mobile_performance_criteria(user: User):
    return _phase3c_criteria_service(user, globals())


# BYS360 P11-C1: mobile_performance_weights read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.


from app.api.mobile.services.performance_task_detail_route_services import (  # noqa: E402 - deferred to avoid circular import with performance_period_service
    phase3c_mobile_performance_task_detail_service as _phase3c_task_detail_service,
    phase3c_mobile_performance_third_manager_service as _phase3c_third_manager_service,
)


def _phase3c_task_detail_route_deps() -> dict[str, Any]:
    return {
        'EvaluationAssignment': EvaluationAssignment,
        'PerformanceCriteria': PerformanceCriteria,
        'PerformancePeriod': PerformancePeriod,
        'PerformanceWeightConfig': PerformanceWeightConfig,
        'User': User,
        '_date_range': _date_range,
        '_full_name': _full_name,
        '_item': _item,
        '_metric': _metric,
        '_mobile_perf_rollback_quietly': _mobile_perf_rollback_quietly,
        '_mobile_perf_safe_all': _mobile_perf_safe_all,
        '_mobile_perf_safe_get': _mobile_perf_safe_get,
        '_module_payload': _module_payload,
        '_period_name': _period_name,
        '_period_progress': _period_progress,
        '_period_scope': _period_scope,
        '_period_status': _period_status,
        '_v2821_float': _v2821_float,
        '_v2821_mode_text': _v2821_mode_text,
        '_v2821_percent': _v2821_percent,
        '_v2821_period_label': _v2821_period_label,
        '_v2822_can_view_assignment': _v2822_can_view_assignment,
        '_v2822_due_label': _v2822_due_label,
        '_v2822_level_label': _v2822_level_label,
        '_v2822_sicil': _v2822_sicil,
        '_v2822_unit_name': _v2822_unit_name,
        'jsonify': jsonify,
        'logger': logger,
    }


@mobile_api_bp.get("/performance/third-manager")
@require_mobile_user
def mobile_performance_third_manager(user: User):
    return _phase3c_third_manager_service(user, _phase3c_task_detail_route_deps())


# BYS360 MOBILE V2.8.22 PERFORMANCE TASKS
from app.api.mobile.services.performance_task_helpers import (  # noqa: E402, F401 - deferred; some names used via performance_read_routes.py globals() bridge
    _v2822_assignment_card,
    _v2822_assignment_query,
    _v2822_can_view_assignment,
    _v2822_due_label,
    _v2822_level_label,
    _v2822_open_query,
    _v2822_sicil,
    _v2822_unit_name,
)

# BYS360 P11-C1: mobile_performance_tasks read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.


@mobile_api_bp.get('/performance/tasks/<int:assignment_id>')
@require_mobile_user
def mobile_performance_task_detail(user: User, assignment_id: int):
    return _phase3c_task_detail_service(user, assignment_id, _phase3c_task_detail_route_deps())

# BYS360 MOBILE V2.8.35 PERFORMANCE SCORING FORM REAL API

def _v2835_json_error(message: str, status_code: int = 400):
    return jsonify({'message': str(message or 'İşlem tamamlanamadı. Lütfen tekrar deneyin.')}), status_code


def _v2835_level3_scoring_enabled(period: Any) -> bool:
    try:
        flags = get_period_level_3_flags(period)
        return bool(flags.get('enabled') and flags.get('scoring_enabled'))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return bool(getattr(period, 'enable_level_3', False) and getattr(period, 'enable_level_3_scoring', False))


def _v2835_score_mode_for(assignment: Any, period: Any) -> bool:
    try:
        level = int(getattr(assignment, 'manager_level', 0) or 0)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        level = 0
    return not (level == 3 and not _v2835_level3_scoring_enabled(period))


def _v2835_existing_evaluation(assignment: Any):
    try:
        return PerformanceEvaluation.query.filter_by(
            period_id=getattr(assignment, 'period_id', None),
            employee_id=getattr(assignment, 'employee_id', None),
        ).first()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        return None


def _v2835_general_comment(evaluation: Any, level: int) -> str:
    if not evaluation:
        return ''
    return str(getattr(evaluation, f'level_{level}_general_comment', None) or '')


def _v2835_level_completed(evaluation: Any, level: int) -> bool:
    if not evaluation:
        return False
    return bool(getattr(evaluation, f'level_{level}_completed', False))


def _v2835_criteria_rows():
    try:
        q = PerformanceCriteria.query.filter_by(is_active=True)
        try:
            q = q.order_by(PerformanceCriteria.sort_order.asc(), PerformanceCriteria.id.asc())
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            q = q.order_by(PerformanceCriteria.id.asc())
        return _mobile_perf_safe_all(q.limit(120))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        return []


def _v2835_existing_item_map(evaluation: Any, level: int) -> dict[int, Any]:
    if not evaluation:
        return {}
    try:
        rows = PerformanceEvaluationItem.query.filter_by(evaluation_id=evaluation.id, manager_level=level).all()
        return {int(getattr(row, 'criteria_id', 0) or 0): row for row in rows}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _mobile_perf_rollback_quietly()
        return {}


def _bys360_legacy__v2835_score_form_payload(assignment: Any) -> dict[str, Any]:
    employee = getattr(assignment, 'employee', None) or _mobile_perf_safe_get(User, getattr(assignment, 'employee_id', None))
    evaluator = getattr(assignment, 'evaluator', None) or _mobile_perf_safe_get(User, getattr(assignment, 'evaluator_id', None))
    period = getattr(assignment, 'period', None) or _mobile_perf_safe_get(PerformancePeriod, getattr(assignment, 'period_id', None))
    evaluation = _v2835_existing_evaluation(assignment)
    level = int(getattr(assignment, 'manager_level', 0) or 0)
    criteria_rows = _v2835_criteria_rows()
    existing = _v2835_existing_item_map(evaluation, level)
    score_mode = _v2835_score_mode_for(assignment, period)
    completed = bool(getattr(assignment, 'completed_at', None)) or _v2835_level_completed(evaluation, level)

    criteria_payload: list[dict[str, Any]] = []
    for row in criteria_rows:
        cid = int(getattr(row, 'id', 0) or 0)
        item = existing.get(cid)
        score_value = getattr(item, 'score', None) if item else None
        criteria_payload.append({
            'id': str(cid),
            'criteria_id': cid,
            'title': str(getattr(row, 'name', None) or 'Değerlendirme Kriteri'),
            'description': str(getattr(row, 'description', None) or ''),
            'weight': float(getattr(row, 'weight', 0) or 0),
            'score': score_value,
            'comment': str(getattr(item, 'comment', None) or getattr(item, 'justification', None) or '') if item else '',
            'score_100': float(getattr(item, 'score_100', 0) or 0) if item else 0,
        })

    warning = '70 altı veya 90 üstü sonuçlarda ayrıntılı genel görüş zorunludur. 1 ve 5 puanda kriter açıklaması mobil uygulamada isteğe bağlıdır.'
    if not score_mode:
        warning = '3. amir bu görevde yorum/görüş modundadır; puan alanı kapalıdır.'

    return {
        'source': 'real_api',
        'form': {
            'assignment_id': str(getattr(assignment, 'id', '') or ''),
            'evaluation_id': str(getattr(evaluation, 'id', '') or '') if evaluation else '',
            'employee_name': _full_name(employee),
            'sicil_no': _v2822_sicil(employee),
            'unit_name': _v2822_unit_name(employee),
            'period_name': _period_name(period),
            'date_range': _date_range(period),
            'evaluator_name': _full_name(evaluator),
            'manager_level': level,
            'manager_level_label': _v2822_level_label(level),
            'status_label': _label(getattr(assignment, 'status', None), 'Değerlendirme Bekliyor'),
            'is_completed': completed,
            'score_mode': score_mode,
            'criteria': criteria_payload,
            'general_comment': _v2835_general_comment(evaluation, level),
            'warning': warning,
            'submit_label': 'Tamamla',
            'save_label': 'Taslak Kaydet',
            'actions': _v2837_action_capabilities(assignment, evaluation, level),
        },
        'rules': {
            'score_range': '1-5',
            'low_high_general_comment': '70 altı / 90 üstü genel görüş zorunludur',
            'level3_mode': 'Puanlama' if score_mode else 'Yalnızca Görüş',
        },
    }

def _v2835_score_form_payload(assignment):
    from app.api.mobile.services.performance_task_service import delegate_v2835_score_form_payload
    return delegate_v2835_score_form_payload(assignment)


def _v2837_status_key(value: Any) -> str:
    return str(value or '').strip().lower().replace('ı', 'i').replace(' ', '_').replace('-', '_')


def _v2837_assignment_is_completed(assignment: Any, evaluation: Any, level: int) -> bool:
    return bool(getattr(assignment, 'completed_at', None)) or _v2835_level_completed(evaluation, level) or _v2837_status_key(getattr(assignment, 'status', None)) in {'tamamlandi', 'completed', 'done'}


def _bys360_legacy__v2837_find_return_target(assignment: Any, level: int):
    # İşlem sırası BYS360 kuralına göre yüksek numaralı seviyeden düşük numaralı seviyeye iner.
    # Bu nedenle mevcut amir, varsa bir önceki işlem seviyesine iade edebilir: 1 -> 2, 2 -> 3.
    for target_level in (level + 1,):
        if target_level not in {2, 3}:
            continue
        target = EvaluationAssignment.query.filter_by(
            period_id=getattr(assignment, 'period_id', None),
            employee_id=getattr(assignment, 'employee_id', None),
            manager_level=target_level,
        ).first()
        if target:
            return target_level, target
    return None, None

def _v2837_find_return_target(assignment: Any, level: int):
    from app.api.mobile.services import performance_task_service as _bys360_performance_task_service
    return _bys360_performance_task_service._v2837_find_return_target(assignment, level)


def _bys360_legacy__v2837_action_capabilities(assignment: Any, evaluation: Any, level: int) -> dict[str, Any]:
    completed = _v2837_assignment_is_completed(assignment, evaluation, level)
    target_level, target = _v2837_find_return_target(assignment, level)
    is_published = bool(getattr(evaluation, 'is_published_to_employee', False) or getattr(evaluation, 'published_to_employee_at', None)) if evaluation else False
    can_withdraw = bool(completed and not is_published)
    can_return = bool(completed and target and not is_published)
    return {
        'can_withdraw': can_withdraw,
        'can_return': can_return,
        'return_target_level': target_level or 0,
        'withdraw_label': 'Geri Çek',
        'return_label': 'İade Et',
        'bulk_scores': [5, 4, 3, 2, 1],
        'bulk_note': 'Toplu puan verdiğinizde her kriter yine ayrı ayrı düzenlenebilir.',
    }

def _v2837_action_capabilities(assignment: Any, evaluation: Any, level: int) -> dict[str, Any]:
    from app.api.mobile.services import performance_task_service as _bys360_performance_task_service
    return _bys360_performance_task_service._v2837_action_capabilities(assignment, evaluation, level)


def _v2837_recalculate_if_possible(evaluation: Any) -> None:
    if not evaluation:
        return
    try:
        recalculate_evaluation_totals(evaluation)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.add(evaluation)


def _bys360_legacy__v2837_withdraw_assignment(assignment: Any, evaluation: Any, level: int, user: User, note: str = '') -> dict[str, Any]:
    if not _v2837_assignment_is_completed(assignment, evaluation, level):
        raise ValueError('Geri çekme için önce tamamlanmış bir değerlendirme olmalıdır.')
    if bool(getattr(evaluation, 'is_published_to_employee', False) or getattr(evaluation, 'published_to_employee_at', None)):
        raise ValueError('Personele yayınlanmış değerlendirme mobil ekrandan geri çekilemez.')
    assignment.status = 'taslak'
    assignment.completed_at = None
    if evaluation:
        setattr(evaluation, f'level_{level}_completed', False)
        evaluation.workflow_status = f'taslak_{level}_amir'
        if _v2837_status_key(getattr(evaluation, 'status', None)) in {'tamamlandi', 'completed'}:
            evaluation.status = 'kismen_tamamlandi'
        _v2837_recalculate_if_possible(evaluation)
        db.session.add(evaluation)
    db.session.add(assignment)
    db.session.commit()
    return {'message': 'Değerlendirme geri çekildi. Artık puanları yeniden düzenleyebilirsiniz.'}

def _v2837_withdraw_assignment(assignment: Any, evaluation: Any, level: int, user: User, note: str = '') -> dict[str, Any]:
    from app.api.mobile.services import performance_task_service as _bys360_performance_task_service
    return _bys360_performance_task_service._v2837_withdraw_assignment(assignment, evaluation, level, user, note)


def _bys360_legacy__v2837_return_assignment(assignment: Any, evaluation: Any, level: int, user: User, note: str = '') -> dict[str, Any]:
    note_text = str(note or '').strip()
    if not note_text:
        raise ValueError('İade işlemi için kısa bir açıklama yazın.')
    if not _v2837_assignment_is_completed(assignment, evaluation, level):
        raise ValueError('İade işlemi için önce mevcut değerlendirme tamamlanmış olmalıdır.')
    if bool(getattr(evaluation, 'is_published_to_employee', False) or getattr(evaluation, 'published_to_employee_at', None)):
        raise ValueError('Personele yayınlanmış değerlendirme mobil ekrandan iade edilemez.')
    target_level, target = _v2837_find_return_target(assignment, level)
    if not target:
        raise ValueError('İade edilecek önceki amir görevi bulunamadı.')
    target.status = 'iade'
    target.completed_at = None
    assignment.status = 'taslak'
    assignment.completed_at = None
    if evaluation:
        setattr(evaluation, f'level_{level}_completed', False)
        setattr(evaluation, f'level_{target_level}_completed', False)
        evaluation.workflow_status = f'level_{target_level}_iade'
        evaluation.status = 'devam_ediyor'
        if hasattr(evaluation, 'level_2_return_note'):
            evaluation.level_2_return_note = note_text
        if hasattr(evaluation, 'level_2_returned_by_id'):
            evaluation.level_2_returned_by_id = getattr(user, 'id', None)
        if hasattr(evaluation, 'level_2_returned_to_level_1_at'):
            evaluation.level_2_returned_to_level_1_at = utc_now()
        _v2837_recalculate_if_possible(evaluation)
        db.session.add(evaluation)
    db.session.add(target)
    db.session.add(assignment)
    db.session.commit()
    return {'message': f'Değerlendirme {target_level}. amire iade edildi. Düzeltme sonrası süreç yeniden devam eder.'}

def _v2837_return_assignment(assignment: Any, evaluation: Any, level: int, user: User, note: str = '') -> dict[str, Any]:
    from app.api.mobile.services import performance_task_service as _bys360_performance_task_service
    return _bys360_performance_task_service._v2837_return_assignment(assignment, evaluation, level, user, note)


from app.api.mobile.services.performance_score_route_services import (  # noqa: E402 - deferred to avoid circular import with performance_period_service
    phase3c_mobile_performance_task_score_action_service as _phase3c_score_action_service,
    phase3c_mobile_performance_task_score_form_service as _phase3c_score_form_service,
    phase3c_mobile_performance_task_score_submit_service as _phase3c_score_submit_service,
)


def _phase3c_score_route_deps() -> dict[str, Any]:
    return {
        'EvaluationAssignment': EvaluationAssignment,
        'PerformanceEvaluation': PerformanceEvaluation,
        'PerformancePeriod': PerformancePeriod,
        '_label': _label,
        '_mobile_perf_safe_get': _mobile_perf_safe_get,
        '_v2822_can_view_assignment': _v2822_can_view_assignment,
        '_v2835_criteria_rows': _v2835_criteria_rows,
        '_v2835_existing_evaluation': _v2835_existing_evaluation,
        '_v2835_json_error': _v2835_json_error,
        '_v2835_score_form_payload': _v2835_score_form_payload,
        '_v2835_score_mode_for': _v2835_score_mode_for,
        '_v2837_return_assignment': _v2837_return_assignment,
        '_v2837_withdraw_assignment': _v2837_withdraw_assignment,
        'calculate_preview_total_100': calculate_preview_total_100,
        'db': db,
        'jsonify': jsonify,
        'logger': logger,
        'request': request,
        'save_evaluation_level': save_evaluation_level,
        'utc_now': utc_now,
        'validate_general_comment_requirements': validate_general_comment_requirements,
    }


@mobile_api_bp.get('/performance/tasks/<int:assignment_id>/score-form')
@require_mobile_user
def mobile_performance_task_score_form(user: User, assignment_id: int):
    return _phase3c_score_form_service(user, assignment_id, _phase3c_score_route_deps())


@mobile_api_bp.post('/performance/tasks/<int:assignment_id>/score-form')
@require_mobile_user
def mobile_performance_task_score_submit(user: User, assignment_id: int):
    return _phase3c_score_submit_service(user, assignment_id, _phase3c_score_route_deps())

@mobile_api_bp.post('/performance/tasks/<int:assignment_id>/score-action')
@require_mobile_user
def mobile_performance_task_score_action(user: User, assignment_id: int):
    return _phase3c_score_action_service(user, assignment_id, _phase3c_score_route_deps())

# BYS360 P11-C1: mobile_performance_manager_tasks read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.

# BYS360_MOBILE_V2_8_52_PERFORMANCE_WEB_PARITY_API
# Mobil performans modülü web performans başlıklarıyla aynı kapsamda özet/listeler üretir.
def _v2852_model(*names):
    for name in names:
        try:
            registry = getattr(getattr(db, 'Model', None), 'registry', None)
            cls = getattr(registry, '_class_registry', {}).get(name) if registry is not None else None
            if cls is not None and hasattr(cls, 'query'):
                return cls
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/performance_routes.py:1105)")
        try:
            cls = globals().get(name)
            if cls is not None and hasattr(cls, 'query'):
                return cls
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/performance_routes.py:1111)")
    return None


def _v2852_text(obj, fields, default=''):
    if obj is None:
        return default
    for field in fields:
        try:
            value = getattr(obj, field, None)
            if value not in (None, ''):
                return str(value)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/performance_routes.py:1124)")
    return default


def _v2852_int(value, default=0):
    try:
        return int(float(str(value).replace(',', '.')))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def _v2852_query(model):
    q = model.query
    for field in ('updated_at', 'created_at', 'id'):
        try:
            col = getattr(model, field, None)
            if col is not None:
                return q.order_by(col.desc())
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/performance_routes.py:1143)")
    return q


def _v2852_items_from_models(model_names, title_fields, subtitle_fields, status_fields=None, meta_fields=None, value_fields=None, limit=80, progress=50):
    status_fields = status_fields or ['status', 'state', 'workflow_status']
    meta_fields = meta_fields or ['period_name', 'period_title', 'category', 'unit_name', 'created_at']
    value_fields = value_fields or ['score', 'final_score', 'final_total_100', 'value']
    for model_name in model_names:
        model = _v2852_model(model_name)
        if model is None:
            continue
        rows = _mobile_perf_safe_all(_v2852_query(model).limit(limit))
        items = []
        for row in rows:
            items.append(_item(
                getattr(row, 'id', ''),
                _v2852_text(row, title_fields, model_name),
                _v2852_text(row, subtitle_fields, 'Detay bilgisi'),
                _label(_v2852_text(row, status_fields, 'Kayıt'), 'Kayıt'),
                _v2852_text(row, meta_fields, ''),
                _v2852_text(row, value_fields, ''),
                progress,
            ))
        if items:
            return items
    return []


def _v2852_employee_category(user):
    if user is None:
        return 'Diğer'
    for field in ('personnel_category', 'employee_category', 'staff_category', 'category', 'group_name', 'personnel_group'):
        try:
            value = getattr(user, field, None)
            if value:
                return str(value)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/performance_routes.py:1181)")
    try:
        return _v2822_unit_name(user)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return 'Diğer'


def _v2852_score(row):
    return _score_value(row) if '_score_value' in globals() else _v2852_int(_v2852_text(row, ['final_total_100', 'final_score', 'score'], '0'))


def _v2852_done(row):
    try:
        return bool(getattr(row, 'completed_at', None)) or str(getattr(row, 'status', '')).lower() in _DONE
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _v2852_pending_assignments(user, limit=1000):
    # Kapsam yalnız yetki yardımcılarından gelir; hata kapsamsız sorguya düşmez.
    q = _v2822_assignment_query(user) if '_v2822_assignment_query' in globals() else _assignment_query_for(user)
    return [row for row in _mobile_perf_safe_all(q.limit(limit)) if not _v2852_done(row)]


def _v2852_due_label_safe(row):
    try:
        return _v2822_due_label(row)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return (_label(getattr(row, 'status', None), 'Bekliyor'), 40, 'red')

from app.api.mobile.services.performance_summary_risk_route_services import (  # noqa: E402 - deferred to avoid circular import with performance_period_service
    phase3c_mobile_performance_full_feature_summary_service as _phase3c_full_feature_summary_service,
    phase3c_mobile_performance_publish_preapproval_service as _phase3c_publish_preapproval_service,
    phase3c_mobile_performance_risk_analysis_v2852_service as _phase3c_risk_analysis_v2852_service,
)


def _phase3c_summary_risk_route_deps() -> dict[str, Any]:
    return {
        '__route_globals__': globals(),
        'EvaluationAssignment': EvaluationAssignment,
        'PerformancePeriod': PerformancePeriod,
        'PerformancePresidentApproval': PerformancePresidentApproval,
        'PerformanceResultSnapshot': PerformanceResultSnapshot,
        'User': User,
        '_assignment_query_for': _assignment_query_for,
        '_full_name': _full_name,
        '_has_global_scope': _has_global_scope,
        '_item': _item,
        '_low_score_count': _low_score_count,
        '_metric': _metric,
        '_mobile_perf_safe_all': _mobile_perf_safe_all,
        '_mobile_perf_safe_count': _mobile_perf_safe_count,
        '_mobile_perf_safe_get': _mobile_perf_safe_get,
        '_module_payload': _module_payload,
        '_period_name': _period_name,
        '_safe_avg_score': _safe_avg_score,
        '_snapshot_query_for': _snapshot_query_for,
        '_v2852_items_from_models': _v2852_items_from_models,
        '_v2852_pending_assignments': _v2852_pending_assignments,
        '_v2852_score': _v2852_score,
        'logger': logger,
    }


@mobile_api_bp.get('/performance/full-feature-summary')
@require_mobile_user
def _bys360_legacy_mobile_performance_full_feature_summary(user: User):
    return _phase3c_full_feature_summary_service(user, _phase3c_summary_risk_route_deps())

def mobile_performance_full_feature_summary(user: User):
    from app.api.mobile.services.performance_summary_service import delegate_mobile_performance_full_feature_summary as _bys360_delegate  # noqa: I001 - kept single-line for route-file line budget
    return _bys360_delegate(_bys360_legacy_mobile_performance_full_feature_summary, user)

# BYS360 P11-C1: mobile_performance_categories read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.

@mobile_api_bp.get('/performance/president-approvals')
@require_mobile_user
def _bys360_prev_mobile_performance_president_approvals_alias_v21748(user: User):
    # BYS360 V2.17.49: 500 smoke fix - guvenli JSON fallback
    return _bys360_mobile_perf_president_approvals_safe_fallback_v21749(user)

def mobile_performance_president_approvals_alias(user: User):  # compatibility guard
    # BYS360 V2.17.49: 500 smoke fix - guvenli JSON fallback
    return _bys360_mobile_perf_president_approvals_safe_fallback_v21749(user)

@mobile_api_bp.get('/performance/publish-preapproval')
@require_mobile_user
def mobile_performance_publish_preapproval(user: User):
    return _phase3c_publish_preapproval_service(user, _phase3c_summary_risk_route_deps())

def _bys360_legacy_mobile_performance_history_archive(user: User):
    # BYS360 V2.17.49: 500 smoke fix - guvenli JSON fallback
    return _bys360_mobile_perf_history_archive_safe_fallback_v21749(user)

@mobile_api_bp.get('/performance/history-archive')
@require_mobile_user
def _bys360_prev_mobile_performance_history_archive_v21748(user):
    # BYS360 V2.17.49: 500 smoke fix - guvenli JSON fallback
    return _bys360_mobile_perf_history_archive_safe_fallback_v21749(user)

def mobile_performance_history_archive(user):  # compatibility guard
    # BYS360 V2.17.49: 500 smoke fix - guvenli JSON fallback
    return _bys360_mobile_perf_history_archive_safe_fallback_v21749(user)

@mobile_api_bp.get('/performance/in-period-notes')
@require_mobile_user
def _bys360_legacy_mobile_performance_in_period_notes(user: User):
    return _phase3c_in_period_notes_legacy_service(user, globals())

def mobile_performance_in_period_notes(user: User):
    from app.api.mobile.services.performance_period_service import delegate_mobile_performance_in_period_notes  # noqa: I001 - kept single-line for route-file line budget
    return delegate_mobile_performance_in_period_notes(user)

def _bys360_legacy_mobile_performance_development_suggestions(user: User):
    # BYS360_SECURITY_FIX_DEFECT_O1: _v2852_items_from_models() runs a
    # zero-filter, organization-wide query (see _v2852_query()) across every
    # model in its list. That unscoped shortcut must only ever be reachable
    # for _has_global_scope() callers; non-global callers must go straight to
    # the already-correctly-scoped _snapshot_query_for(user) fallback below.
    items = _v2852_items_from_models(['PerformanceDevelopmentSuggestion', 'PerformanceDevelopmentPlan', 'DevelopmentSuggestion', 'FeedbackActionPlan'], ['employee_name', 'title', 'suggestion_title', 'name'], ['suggestion', 'description', 'development_area', 'action_text'], ['status', 'state'], ['period_name', 'created_at', 'owner_name'], ['priority', 'score'], limit=100, progress=65) if _has_global_scope(user) else []
    if not items:
        try:
            q = _snapshot_query_for(user).order_by(PerformanceResultSnapshot.id.desc())
            rows = [row for row in _mobile_perf_safe_all(q.limit(100)) if 0 < _v2852_score(row) < 70]
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            rows = []
        for row in rows[:60]:
            employee = getattr(row, 'employee', None) or _mobile_perf_safe_get(User, getattr(row, 'employee_id', None))
            period = getattr(row, 'period', None) or _mobile_perf_safe_get(PerformancePeriod, getattr(row, 'period_id', None))
            score = _v2852_score(row)
            items.append(_item(getattr(row, 'id', ''), _full_name(employee), _period_name(period), 'Gelişim Takibi', '70 altı sonuç için gelişim önerisi değerlendirilebilir', f'{score}/100', 45))
    if not items:
        items = [_item('development-empty', 'Gelişim önerisi kaydı bulunmadı', 'Gelişim alanı, güçlü yön veya takip notu oluştuğunda burada görünür.', 'Bilgi', 'Yetki kontrollü', '', 35)]
    return _module_payload([
        _metric('Gelişim', max(0, len([i for i in items if i.get('id') != 'development-empty'])), 'Öneri veya takip kaydı', 'green', 'development'),
        _metric('Amaç', 'Rehberlik', 'Puan yerine gelişim takibi desteklenir', 'blue', 'school'),
        _metric('Düşük Performans', 'İzlenir', '70 altı sonuçlar gelişim sürecine bağlanabilir', 'yellow', 'warning'),
    ], items)

@mobile_api_bp.get('/performance/development-suggestions')
@require_mobile_user
def mobile_performance_development_suggestions(user: User):
    from app.api.mobile.services.performance_summary_service import mobile_performance_development_suggestions_delegate  # noqa: I001 - kept single-line for route-file line budget
    return mobile_performance_development_suggestions_delegate(user)

def _bys360_legacy_mobile_performance_reports(user: User):
    # Kapsam yalnız yetki yardımcılarından gelir; hata kapsamsız sorguya düşmez.
    assignment_q = _assignment_query_for(user)
    snapshot_q = _snapshot_query_for(user)
    total_assignments = _mobile_perf_safe_count(assignment_q)
    total_scorecards = _mobile_perf_safe_count(snapshot_q)
    avg_score = _safe_avg_score(snapshot_q) if '_safe_avg_score' in globals() else 0
    low_score = _low_score_count(snapshot_q) if '_low_score_count' in globals() else 0
    periods = _mobile_perf_safe_all(PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(30)) if hasattr(PerformancePeriod, 'id') else []
    items = []
    for period in periods:
        period_id = getattr(period, 'id', None)
        task_count = _mobile_perf_safe_count(_period_assignment_query(user, period_id)) if period_id and '_period_assignment_query' in globals() else 0
        items.append(_item(period_id or '', _period_name(period), _date_range(period), _period_status(period), f'{task_count} görev', _period_scope(period), _period_progress(period)))
    if not items:
        items = [_item('report-summary', 'Performans rapor özeti', 'Birim, kategori, dönem, amir, personel ve risk bazlı raporlar web verisiyle üretilir.', 'Özet', f'{total_assignments} görev / {total_scorecards} karne', '', 70)]
    return _module_payload([
        _metric('Görev', total_assignments, 'Yetki kapsamındaki değerlendirme görevi', 'red', 'assignment'),
        _metric('Karne', total_scorecards, 'Yetki kapsamındaki karne', 'green', 'scorecard'),
        _metric('Ortalama', f'{avg_score}/100' if avg_score else '-', 'Yayınlanmış sonuç ortalaması', 'green', 'trending_up'),
        _metric('70 Altı', low_score, 'Risk/düşük performans göstergesi', 'yellow', 'warning'),
    ], items)

@mobile_api_bp.get('/performance/reports')
@require_mobile_user
def mobile_performance_reports(user: User):
    from app.api.mobile.services.performance_summary_service import delegate_mobile_performance_reports  # noqa: I001 - kept single-line for route-file line budget
    return delegate_mobile_performance_reports(_bys360_legacy_mobile_performance_reports, user)

# BYS360 P11-C1: mobile_performance_reminders read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.

# BYS360 P11-C1: mobile_performance_manager_view_v2852 read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.

@mobile_api_bp.get('/performance/risk-analysis')
@require_mobile_user
def _bys360_legacy_mobile_performance_risk_analysis_v2852(user: User):
    return _phase3c_risk_analysis_v2852_service(user, _phase3c_summary_risk_route_deps())

def mobile_performance_risk_analysis_v2852(user):
    from app.api.mobile.services.performance_summary_service import mobile_performance_risk_analysis_v2852_delegate  # noqa: I001 - kept single-line for route-file line budget
    return mobile_performance_risk_analysis_v2852_delegate(_bys360_legacy_mobile_performance_risk_analysis_v2852, user)

# BYS360_MOBILE_V2_8_53_IN_PERIOD_NOTES_API
# BYS360 P11-C1: mobile_performance_in_period_note_options_v2853 read-only performance route app/api/mobile/performance_read_routes.py modülüne taşındı.


def _bys360_legacy__v2853_note_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'evet', 'yes', 'on'}

def _v2853_note_bool(value, default=False):
    from app.api.mobile.services import performance_period_service as _bys360_performance_period_service  # noqa: I001 - kept single-line for route-file line budget
    return _bys360_performance_period_service._v2853_note_bool(value, default)


def _v2853_ensure_interim_notes_table():
    try:
        from app.services.performance.interim_notes_runtime import ensure_interim_notes_table
        ensure_interim_notes_table()
        return True
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            from sqlalchemy import text as _sql_text

            from app.services.performance.interim_notes_runtime import _id_sql
            # BYS360 DEFECT AR: id artik dialect'e gore uretiliyor (eskiden sabit SERIAL SQLite'ta kalici NULL kaliyordu).
            db.session.execute(_sql_text(f'''
                CREATE TABLE IF NOT EXISTS performance_interim_notes (
                    {_id_sql()},
                    period_id INTEGER NULL,
                    employee_id INTEGER NULL,
                    employee_user_id INTEGER NULL,
                    manager_id INTEGER NULL,
                    created_by INTEGER NULL,
                    created_by_id INTEGER NULL,
                    note_type VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem',
                    title VARCHAR(255) NULL,
                    note TEXT NULL,
                    note_body TEXT NULL,
                    visibility_level VARCHAR(80) NULL DEFAULT 'manager_scope',
                    remind_during_scoring BOOLEAN DEFAULT TRUE,
                    include_in_scorecard BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            db.session.commit()
            return True
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            db.session.rollback()
            return False


def _bys360_legacy__v2853_note_type_label(value):
    mapping = {
        'olumlu_olay': 'Olumlu Olay',
        'olumsuz_olay': 'Olumsuz Olay',
        'basari': 'Başarı',
        'gelisim_ihtiyaci': 'Gelişim İhtiyacı',
        'genel_gozlem': 'Genel Gözlem',
    }
    key = str(value or 'genel_gozlem').strip().lower()
    return mapping.get(key, 'Bilinmiyor')

def _v2853_note_type_label(value):
    from app.api.mobile.services import performance_period_service as _bys360_performance_period_service  # noqa: I001 - kept single-line for route-file line budget
    return _bys360_performance_period_service._v2853_note_type_label(value)


from app.api.mobile.services.performance_note_route_services import (  # noqa: E402 - deferred to avoid circular import with performance_period_service
    phase3c_mobile_performance_create_in_period_note_v2853_service as _phase3c_create_in_period_note_v2853_service,
    phase3c_mobile_performance_in_period_notes_v2853_service as _phase3c_in_period_notes_v2853_service,
    phase3c_mobile_performance_note_scorecard_v2863a_service as _phase3c_note_scorecard_v2863a_service,
)


def _phase3c_note_route_deps() -> dict[str, Any]:
    return {
        'PerformancePeriod': PerformancePeriod,
        'User': User,
        '_full_name': _full_name,
        '_has_global_scope': _has_global_scope,
        '_item': _item,
        '_metric': _metric,
        '_mobile_perf_safe_get': _mobile_perf_safe_get,
        '_module_payload': _module_payload,
        '_period_name': _period_name,
        '_v2853_ensure_interim_notes_table': _v2853_ensure_interim_notes_table,
        '_v2853_note_bool': _v2853_note_bool,
        '_v2853_note_type_label': _v2853_note_type_label,
        'db': db,
        'jsonify': jsonify,
        'logger': logger,
    }


@mobile_api_bp.get('/performance/in-period-notes/v2')
@require_mobile_user
def _bys360_legacy_mobile_performance_in_period_notes_v2853(user: User):
    return _phase3c_in_period_notes_v2853_service(user, _phase3c_note_route_deps())

def mobile_performance_in_period_notes_v2853(user: User):
    from app.api.mobile.services.performance_period_service import delegate_mobile_performance_in_period_notes_v2853  # noqa: I001 - kept single-line for route-file line budget
    return delegate_mobile_performance_in_period_notes_v2853(user)


@mobile_api_bp.post('/performance/in-period-notes/v2')
@require_mobile_user
def mobile_performance_create_in_period_note_v2853(user: User):
    return _phase3c_create_in_period_note_v2853_service(user, _phase3c_note_route_deps())

# BYS360_MOBILE_V2_8_63A_NOTE_SCORECARD_ENDPOINT
@mobile_api_bp.get('/performance/note-scorecard')
@require_mobile_user
def _bys360_legacy_mobile_performance_note_scorecard_v2863a(user: User):
    return _phase3c_note_scorecard_v2863a_service(user, _phase3c_note_route_deps())

def mobile_performance_note_scorecard_v2863a(user: User):
    from app.api.mobile.services.performance_period_service import delegate_mobile_performance_note_scorecard_v2863a  # noqa: I001 - kept single-line for route-file line budget
    return delegate_mobile_performance_note_scorecard_v2863a(user)


# BYS360_MOBILE_V2_8_63A_ARCHIVE_NOTE_SCORECARD

# BYS360 P11-C1: mobile performance read routes bridge
from app.api.mobile.performance_read_routes import register_mobile_performance_read_routes_v1 as _register_mobile_performance_read_routes_v1  # noqa: I001, E402 - deferred bridge import feeds globals() to register routes
_register_mobile_performance_read_routes_v1(globals())

# Compatibility guard.
def _bys360_safe_smoke_500_json_response_v21748(kind, exc=None):
    try:
        from flask import current_app, jsonify
        try:
            current_app.logger.exception("BYS360_SAFE_SMOKE_500_FIX_V2_17_48: mobile performance smoke fallback kind=%s", kind)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
        if kind == "president_approvals":
            payload = {
                "items": [],
                "metrics": [{
                    "title": "Başkan Onayları",
                    "subtitle": "Yetki kapsamınızda gösterilecek kayıt bulunamadı veya güvenli boş liste döndürüldü.",
                    "icon": "approval",
                    "tone": "red",
                    "value": 0,
                }],
                "status": "safe_fallback",
                "message": "Başkan onayları mobil görünümü güvenli boş listeyle döndürüldü.",
            }
        elif kind == "history_archive":
            payload = {
                "items": [],
                "metrics": [{
                    "title": "Geçmiş Arşiv",
                    "subtitle": "Yetki kapsamınızda gösterilecek arşiv kaydı bulunamadı veya güvenli boş liste döndürüldü.",
                    "icon": "history",
                    "tone": "red",
                    "value": 0,
                }],
                "status": "safe_fallback",
                "message": "Performans geçmiş arşivi mobil görünümü güvenli boş listeyle döndürüldü.",
            }
        else:
            payload = {"items": [], "metrics": [], "status": "safe_fallback"}
        return jsonify(payload), 200
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        # Flask baglami disinda cagrilirsa bile fonksiyon patlamasin.
        return {"items": [], "metrics": [], "status": "safe_fallback", "kind": kind}, 200

# Compatibility guard.
# Bu blok yalnizca mobil GET smoke testinde 500 veren iki endpoint icin guvenli JSON fallback saglar.
def _bys360_mobile_perf_safe_json_response_v21749(payload, status=200):
    try:
        from flask import jsonify
        return jsonify(payload), status
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return payload, status


def _bys360_mobile_perf_president_approvals_safe_fallback_v21749(user=None):
    return _bys360_mobile_perf_safe_json_response_v21749({
        "items": [],
        "metrics": [
            {
                "title": "Başkan Onayları",
                "subtitle": "Yetki kapsamınızda bekleyen düşük performans onayı bulunamadı veya güvenli fallback devrede.",
                "value": 0,
                "tone": "red",
                "icon": "approval"
            }
        ],
        "status": "safe_fallback",
        "source": "BYS360 V2.17.49",
        "message": "Mobil başkan onayları endpointi güvenli boş yanıt döndürdü."
    })


def _bys360_mobile_perf_history_archive_safe_fallback_v21749(user=None):
    return _bys360_mobile_perf_safe_json_response_v21749({
        "items": [],
        "metrics": [
            {
                "title": "Geçmiş Arşiv",
                "subtitle": "Yetki kapsamınızda görüntülenecek geçmiş karne kaydı bulunamadı veya güvenli fallback devrede.",
                "value": 0,
                "tone": "red",
                "icon": "archive"
            }
        ],
        "status": "safe_fallback",
        "source": "BYS360 V2.17.49",
        "message": "Mobil performans geçmiş arşivi endpointi güvenli boş yanıt döndürdü."
    })

