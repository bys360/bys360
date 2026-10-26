from __future__ import annotations

import logging
from uuid import uuid4

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    AssignmentCoverageLog,
    EvaluationAssignment,
    Notification,
    PerformanceEvaluation,
    User,
)
from app.services.availability_service import (
    apply_availability_snapshot_to_evaluation,
    get_assignment_reference_date,
    get_period_employee_availability,
    resolve_effective_manager,
)
from app.services.hierarchy_rulebook_service import build_lookup
from app.services.performance.chain_rule_engine import resolve_authoritative_desired_chain
from app.services.performance.common import is_president
from app.services.performance.period_freeze import FROZEN_PERIOD_TASKS_MESSAGE, period_is_frozen

# BYS360_PHASE8_4_PERIOD_SCOPE_IMPORT_START
from app.services.performance.period_scope_assignment import (
    build_period_scope_generation_payload,
    deactivate_out_of_scope_assignments_for_period,
    filter_period_scope_employees,
)

# BYS360_PHASE8_4_PERIOD_SCOPE_IMPORT_END
from app.services.performance.scoring_window_policy import (
    apply_scoring_start_to_period,
    is_before_scoring_start,
    scoring_window_payload,
)
from app.services.performance.selected_scope_assessor_policy import (
    assessor_only_exclusion_note,
    split_scored_employees_from_assessor_only,
)

from .chain import build_resolved_chain
from .schedule import build_due_date_for_period
from .validators import validate_period_ready

logger = logging.getLogger(__name__)


def _normalize_text(value):
    return str(value).strip() if value is not None else ''


def _is_info_message(message: str) -> bool:
    folded = _normalize_text(message).lower()
    return any(token in folded for token in (
        'yorumcu modunda',
        'başkan performans değerlendirme zincirine dahil edilmez',
        'baskan performans degerlendirme zincirine dahil edilmez',
        'vekâlet nedeniyle',
        'vekalet nedeniyle',
        'tek amir kuralı uygulandı',
        'zinciri güncel kurala göre düzeltildi',
        'zinciri düzeltildi',
        'amir zinciri kurala göre onarıldı',
        'amir zinciri kurala gore onarildi',
        'birim amiri bulunamadı',
        '3. amir bulunamadı',
        'koordinatör zinciri anayasa matrisine göre 1=başkan yardımcısı, 2=grup başkanı olarak sabitlendi',
        'koordinator zinciri anayasa matrisine gore 1=baskan yardimcisi, 2=grup baskani olarak sabitlendi',
        'çalışma grubu personeli zinciri anayasa matrisine göre 1=grup başkanı, 2=koordinatör olarak sabitlendi',
        'calisma grubu personeli zinciri anayasa matrisine gore 1=grup baskani, 2=koordinator olarak sabitlendi',
        'çalışma grubu personeli zinciri faz 4 nihai matrise göre 1=grup başkanı, 2=koordinatör olarak sabitlendi',
        'calisma grubu personeli zinciri faz 4 nihai matrise gore 1=grup baskani, 2=koordinator olarak sabitlendi',
        'hukuk müşaviri için özel başkanlık istisnası uygulandı',
        'hukuk musaviri icin ozel baskanlik istisnasi uygulandi',
    ))


def _create_generation_log(
    *,
    period_id: int,
    employee_id: int,
    event_type: str,
    reason: str | None = None,
    manager_level: int | None = None,
    severity: str = 'warning',
    run_key: str | None = None,
    original_evaluator_id: int | None = None,
    acting_evaluator_id: int | None = None,
    delegation_id: int | None = None,
    created_by_user_id: int | None = None,
):
    row = AssignmentCoverageLog(
        period_id=period_id,
        employee_id=employee_id,
        manager_level=manager_level,
        event_scope='generation',
        event_type=event_type,
        severity=severity or 'warning',
        reason=reason or None,
        run_key=run_key or None,
        original_evaluator_id=original_evaluator_id,
        acting_evaluator_id=acting_evaluator_id,
        delegation_id=delegation_id,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(row)
    return row


def _log_issue_rows(*, period, employee, resolved_chain, run_key: str | None, actor_user_id: int | None):
    count = 0
    for chain_issue in getattr(resolved_chain, 'issues', []) or []:
        severity = _normalize_text(getattr(chain_issue, 'severity', 'warning')).lower() or 'warning'
        if severity not in {'info', 'warning', 'error'}:
            severity = 'warning'
        level = None
        details = getattr(chain_issue, 'details', None) or {}
        raw_level = details.get('level')
        try:
            level = int(raw_level) if raw_level is not None and raw_level != '' else None
        except (TypeError, ValueError):
            level = None
        _create_generation_log(
            period_id=period.id,
            employee_id=employee.id,
            event_type='chain_issue',
            reason=getattr(chain_issue, 'message', None),
            manager_level=level,
            severity=severity,
            run_key=run_key,
            created_by_user_id=actor_user_id,
        )
        count += 1
    return count


def _log_generation_event(*, period, employee, run_key: str | None, actor_user_id: int | None, reason: str | None = None):
    _create_generation_log(
        period_id=period.id,
        employee_id=employee.id,
        event_type='generated',
        reason=reason or 'Görev zinciri senkronlandı.',
        severity='info',
        run_key=run_key,
        created_by_user_id=actor_user_id,
    )


def _severity_summary(log_rows):
    summary = {'info': 0, 'warning': 0, 'error': 0}
    for row in log_rows or []:
        severity = _normalize_text(getattr(row, 'severity', 'warning')).lower() or 'warning'
        if severity not in summary:
            severity = 'warning'
        summary[severity] += 1
    return summary


def _summarize_breakdown(rows):
    breakdown = {
        'president_excluded': 0,
        'chain_issue': 0,
        'inactive_manager': 0,
        'exempted': 0,
        'uncovered': 0,
        'delegation_warning': 0,
    }
    for row in rows or []:
        availability = row.get('availability') or {}
        if availability.get('exempted'):
            breakdown['exempted'] += 1
        if not int(row.get('active_level_count') or 0) and not availability.get('exempted'):
            breakdown['chain_issue'] += 1
        for issue in row.get('issues') or []:
            lowered = _normalize_text(issue).lower()
            if 'seçilen dönem aktif değil' in lowered or 'secilen donem aktif degil' in lowered:
                continue
            if _is_info_message(issue):
                continue
            if 'geçerli değerlendirici bulunamadı' in lowered or 'gecerli degerlendirici bulunamadi' in lowered:
                breakdown['uncovered'] += 1
            elif 'pasif' in lowered or 'aktif değil' in lowered or 'aktif degil' in lowered:
                breakdown['inactive_manager'] += 1
            else:
                breakdown['chain_issue'] += 1
        for note in row.get('notes') or []:
            lowered = _normalize_text(note).lower()
            if 'seçilen dönem aktif değil' in lowered or 'secilen donem aktif degil' in lowered:
                continue
            if 'başkan performans değerlendirme zincirine dahil edilmez' in lowered or 'baskan performans degerlendirme zincirine dahil edilmez' in lowered:
                breakdown['president_excluded'] += 1
            if 'vekâlet' in lowered or 'vekalet' in lowered:
                breakdown['delegation_warning'] += 1
    return breakdown

def _canonical_manager_tuple(employee) -> tuple[str | None, str | None, str | None]:
    return (
        str(getattr(employee, 'yonetici_sicil', '') or '').strip() or None,
        str(getattr(employee, 'ikinci_yonetici_sicil', '') or '').strip() or None,
        str(getattr(employee, 'ucuncu_yonetici_sicil', '') or '').strip() or None,
    )


def _persist_canonical_manager_chain(employee, lookup) -> tuple[bool, tuple[str | None, str | None, str | None]]:
    """Kalıcı anayasa zincirini kullanıcı kartına da yazar.

    Böylece yalnızca runtime sırasında onaran bir katmanla yetinmeyiz;
    görev üretimi her çalıştığında ters slotlar tekrar canlanmaz.
    1. ve 2. amir slotları kural kitabından gelir, 3. amir ise geçerliyse korunur.
    """
    desired = resolve_authoritative_desired_chain(employee, lookup, preserve_explicit_level3=True)
    current_tuple = _canonical_manager_tuple(employee)
    desired_tuple = (desired.manager_1_sicil, desired.manager_2_sicil, desired.manager_3_sicil)
    if current_tuple == desired_tuple:
        return False, desired_tuple

    employee.yonetici_sicil = desired.manager_1_sicil
    employee.ikinci_yonetici_sicil = desired.manager_2_sicil
    employee.ucuncu_yonetici_sicil = desired.manager_3_sicil
    db.session.add(employee)
    db.session.flush()
    return True, desired_tuple

def _employee_query():
    return (
        User.query.filter(User.is_active.is_(True), User.role != 'admin')
        .order_by(User.ad.asc(), User.soyad.asc())
    )


def _get_or_create_evaluation(period, employee):
    evaluation = PerformanceEvaluation.query.filter_by(period_id=period.id, employee_id=employee.id).first()
    created = False
    if evaluation is None:
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=employee.id)
        db.session.add(evaluation)
        created = True
    return evaluation, created


def _dedupe_assignments(period_id: int, employee_id: int, level: int) -> int:
    rows = (
        EvaluationAssignment.query
        .filter_by(period_id=period_id, employee_id=employee_id, manager_level=level)
        .order_by(EvaluationAssignment.completed_at.desc().nullslast(), EvaluationAssignment.id.desc())
        .all()
    )
    if len(rows) <= 1:
        return 0
    removed = 0
    keep = rows[0]
    for row in rows[1:]:
        if row.id == keep.id:
            continue
        db.session.delete(row)
        removed += 1
    db.session.flush()
    return removed


def _upsert_assignment(
    period,
    employee,
    level: int,
    evaluator_id: int,
    due_date,
    *,
    source_field: str | None = None,
    original_evaluator_id: int | None = None,
    delegation_id: int | None = None,
    assignment_source: str = 'direct',
    coverage_note: str | None = None,
):
    deduped = _dedupe_assignments(period.id, employee.id, level)
    assignment = (
        EvaluationAssignment.query.filter_by(period_id=period.id, employee_id=employee.id, manager_level=level)
        .order_by(EvaluationAssignment.id.desc())
        .first()
    )
    created = False
    if assignment is None:
        assignment = EvaluationAssignment(
            period_id=period.id,
            employee_id=employee.id,
            evaluator_id=evaluator_id,
            original_evaluator_id=original_evaluator_id or evaluator_id,
            delegation_id=delegation_id,
            manager_level=level,
            assignment_source=assignment_source or 'direct',
            coverage_note=coverage_note or source_field,
            status='bekliyor',
            assigned_at=utc_now(),
        )
        db.session.add(assignment)
        created = True
    assignment.evaluator_id = evaluator_id
    assignment.original_evaluator_id = original_evaluator_id or evaluator_id
    assignment.delegation_id = delegation_id
    assignment.due_date = due_date
    assignment.assignment_source = assignment_source or 'direct'
    assignment.coverage_note = coverage_note or source_field or None
    if not assignment.completed_at and (assignment.status or '').strip().lower() not in {'tamamlandi', 'submitted'}:
        assignment.status = 'bekliyor'
    return assignment, created, deduped

def _period_display_name(period) -> str:
    return (
        _normalize_text(getattr(period, 'title', None))
        or _normalize_text(getattr(period, 'name', None))
        or 'Performans Dönemi'
    )


def _ensure_assignment_notifications_for_period(period) -> dict[str, int]:
    """Create or repair in-app notifications for evaluation assignments.

    Görev üretimi/senkronu tamamlandığında her aktif değerlendirme görevi için
    ilgili değerlendiriciye sistem içi bildirim oluşturulur. Aynı assignment için
    mükerrer bildirim bırakılmaz; değerlendirici değiştiyse mevcut bildirim yeni
    kullanıcıya taşınır. Böylece canlıda "görev var ama bildirim yok" durumu
    tekrar etmez.
    """
    if not period or not getattr(period, 'id', None):
        return {'created': 0, 'updated': 0, 'deduped': 0, 'total': 0}

    assignments = (
        EvaluationAssignment.query
        .filter(EvaluationAssignment.period_id == period.id)
        .filter(EvaluationAssignment.evaluator_id.isnot(None))
        .filter(~EvaluationAssignment.status.in_(['pasif', 'muaf']))
        .order_by(EvaluationAssignment.id.asc())
        .all()
    )
    assignment_ids = [int(item.id) for item in assignments if getattr(item, 'id', None) is not None]
    if not assignment_ids:
        return {'created': 0, 'updated': 0, 'deduped': 0, 'total': 0}

    existing_rows = (
        Notification.query
        .filter(Notification.notification_type == 'performance_assignment')
        .filter(Notification.source_type == 'evaluation_assignment')
        .filter(Notification.source_id.in_(assignment_ids))
        .order_by(Notification.id.asc())
        .all()
    )
    existing_by_source: dict[int, list[Notification]] = {}
    for row in existing_rows:
        if getattr(row, 'source_id', None) is None:
            continue
        existing_by_source.setdefault(int(row.source_id), []).append(row)

    period_name = _period_display_name(period)
    title = 'Yeni performans değerlendirme göreviniz oluşturuldu'
    body = f'{period_name} dönemi için performans değerlendirme göreviniz bulunmaktadır.'
    link_url = '/performance/tasks'

    created = 0
    updated = 0
    deduped = 0

    for assignment in assignments:
        rows = existing_by_source.get(int(assignment.id), [])
        if rows:
            keep = rows[0]
            changed = False
            desired_values = {
                'user_id': assignment.evaluator_id,
                'title': title,
                'body': body,
                'notification_type': 'performance_assignment',
                'source_type': 'evaluation_assignment',
                'source_id': assignment.id,
                'link_url': link_url,
                'priority': 'normal',
            }
            for attr, value in desired_values.items():
                if getattr(keep, attr, None) != value:
                    setattr(keep, attr, value)
                    changed = True
            if changed:
                keep.updated_at = utc_now()
                db.session.add(keep)
                updated += 1
            for duplicate in rows[1:]:
                db.session.delete(duplicate)
                deduped += 1
            continue

        db.session.add(Notification(
            user_id=assignment.evaluator_id,
            title=title,
            body=body,
            notification_type='performance_assignment',
            source_type='evaluation_assignment',
            source_id=assignment.id,
            link_url=link_url,
            priority='normal',
            is_read=False,
        ))
        created += 1

    db.session.flush()
    return {'created': created, 'updated': updated, 'deduped': deduped, 'total': len(assignments)}

def _resolved_payloads(period, resolved_chain):
    payloads = {}
    resolved_level_mode = str(getattr(resolved_chain, 'level_mode', '') or '').strip().lower()
    for level, payload in resolved_chain.levels.items():
        if level == 3:
            # BYS360_PHASE4_THIRD_SUPERVISOR_TASK_GUARD
            try:
                # BYS360_PHASE4_2_THIRD_SUPERVISOR_TASK_GUARD
                from app.services.performance.third_supervisor_policy import (
                    should_create_third_supervisor_task,
                )
                if not should_create_third_supervisor_task(period=period, payload=payload):
                    continue
            except Exception:
                logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
                import logging
                logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance_v2/sync_service.py")
            explicit_mode = str(getattr(period, 'level_3_mode', '') or '').strip().lower()
            enable_level_3 = bool(getattr(period, 'enable_level_3', False))
            enable_level_3_scoring = bool(getattr(period, 'enable_level_3_scoring', False))
            level_3_disabled = explicit_mode in {'off', 'disabled'}
            if explicit_mode == 'scoring' or explicit_mode in {'comment_only', 'yorumcu'} or resolved_level_mode in {'comment_only', 'yorumcu', 'scoring'} or enable_level_3 or enable_level_3_scoring:
                level_3_disabled = False
            if level_3_disabled:
                continue
        if not getattr(payload, 'evaluator_id', None):
            continue
        payloads[level] = {
            'evaluator_id': payload.evaluator_id,
            'source_field': payload.source_field,
            'label': payload.label,
        }
    return payloads


def _apply_evaluation_links(evaluation, payloads):
    for level, attr in {1: 'level_1_evaluator_id', 2: 'level_2_evaluator_id', 3: 'level_3_evaluator_id'}.items():
        payload = payloads.get(level)
        setattr(evaluation, attr, payload['evaluator_id'] if payload else None)
    db.session.add(evaluation)


def _deactivate_stale_assignments(period, employee, active_levels: set[int], *, status: str = 'pasif') -> int:
    updated_count = 0
    stale_assignments = (
        EvaluationAssignment.query.filter_by(period_id=period.id, employee_id=employee.id)
        .filter(~EvaluationAssignment.manager_level.in_(list(active_levels or {0})))
        .all()
    )
    for item in stale_assignments:
        if item.completed_at:
            continue
        if item.status != status:
            item.status = status
            updated_count += 1
    return updated_count


def sync_employee_assignments(period, employee, *, run_key: str | None = None, actor_user_id: int | None = None, hierarchy_lookup=None):
    issues: list[str] = []
    notes: list[str] = []
    if hierarchy_lookup is not None:
        repaired, repaired_tuple = _persist_canonical_manager_chain(employee, hierarchy_lookup)
        if repaired:
            notes.append('Amir zinciri anayasa kuralına göre kalıcı olarak onarıldı.')
    resolved_chain = build_resolved_chain(employee=employee, period=period)
    due_date = build_due_date_for_period(period)
    evaluation, created_evaluation = _get_or_create_evaluation(period, employee)

    created_count = 1 if created_evaluation else 0
    updated_count = 0
    deduped_count = 0

    availability = get_period_employee_availability(employee, period)
    apply_availability_snapshot_to_evaluation(evaluation, availability)
    notes.extend(list(getattr(availability, 'notes', []) or []))
    if getattr(availability, 'reason', None):
        notes.append(availability.reason)

    for chain_issue in resolved_chain.issues:
        if getattr(chain_issue, 'severity', 'warning') in {'warning', 'error'}:
            issues.append(chain_issue.message)
        else:
            notes.append(chain_issue.message)
    _log_issue_rows(period=period, employee=employee, resolved_chain=resolved_chain, run_key=run_key, actor_user_id=actor_user_id)

    if availability.exempted:
        _apply_evaluation_links(evaluation, {})
        cleared_count = _deactivate_stale_assignments(period, employee, set(), status='muaf')
        updated_count += cleared_count
        _create_generation_log(
            period_id=period.id,
            employee_id=employee.id,
            event_type='exempted',
            reason=availability.reason or 'İzin/devamsızlık nedeniyle değerlendirmeden muaf tutuldu.',
            severity='warning',
            run_key=run_key,
            created_by_user_id=actor_user_id,
        )
        if cleared_count:
            _create_generation_log(
                period_id=period.id,
                employee_id=employee.id,
                event_type='cleared',
                reason=f'Muafiyet nedeniyle {cleared_count} görev pasife alındı.',
                severity='info',
                run_key=run_key,
                created_by_user_id=actor_user_id,
            )
        _log_generation_event(period=period, employee=employee, run_key=run_key, actor_user_id=actor_user_id, reason='Muafiyet kuralı uygulanarak görev senkronu tamamlandı.')
        return {
            'employee_id': employee.id,
            'employee_name': employee.full_name,
            'resolved_chain': resolved_chain.to_dict(),
            'created_count': created_count,
            'updated_count': updated_count,
            'deduped_count': deduped_count,
            'issues': issues,
            'notes': notes,
            'availability': {
                'exempted': True,
                'reason': availability.reason,
                'available_days': availability.available_days,
            },
            'active_level_count': 0,
        }

    desired_payloads = _resolved_payloads(period=period, resolved_chain=resolved_chain)
    effective_payloads = {}
    reference_date = get_assignment_reference_date(period)

    for level in sorted(desired_payloads):
        payload = desired_payloads[level]
        resolution = resolve_effective_manager(payload['evaluator_id'], level, reference_date)
        if not resolution.acting_manager_id:
            reason = f"{payload['label']} için geçerli değerlendirici bulunamadı."
            issues.append(reason)
            if resolution.note:
                notes.append(resolution.note)
            _create_generation_log(
                period_id=period.id,
                employee_id=employee.id,
                event_type='uncovered',
                reason=resolution.note or reason,
                manager_level=level,
                severity='error',
                run_key=run_key,
                original_evaluator_id=payload['evaluator_id'],
                acting_evaluator_id=None,
                created_by_user_id=actor_user_id,
            )
            continue
        effective_payloads[level] = {
            'evaluator_id': resolution.acting_manager_id,
            'original_evaluator_id': resolution.original_manager_id or payload['evaluator_id'],
            'delegation_id': resolution.delegation_id,
            'assignment_source': resolution.source or 'direct',
            'coverage_note': resolution.note or payload.get('source_field'),
            'source_field': payload.get('source_field'),
            'label': payload['label'],
        }
        if resolution.source == 'delegated' and resolution.note:
            notes.append(f"{payload['label']}: {resolution.note}")
        if resolution.source == 'delegated':
            _create_generation_log(
                period_id=period.id,
                employee_id=employee.id,
                event_type='delegated',
                reason=resolution.note or f"{payload['label']} görevi aynı seviyede vekile yönlendirildi.",
                manager_level=level,
                severity='info',
                run_key=run_key,
                original_evaluator_id=payload['evaluator_id'],
                acting_evaluator_id=resolution.acting_manager_id,
                delegation_id=resolution.delegation_id,
                created_by_user_id=actor_user_id,
            )

    _apply_evaluation_links(evaluation, effective_payloads)

    active_levels: set[int] = set()
    for level in sorted(effective_payloads):
        payload = effective_payloads[level]
        active_levels.add(level)
        _, created, deduped = _upsert_assignment(
            period=period,
            employee=employee,
            level=level,
            evaluator_id=payload['evaluator_id'],
            due_date=due_date,
            source_field=payload.get('source_field'),
            original_evaluator_id=payload.get('original_evaluator_id'),
            delegation_id=payload.get('delegation_id'),
            assignment_source=payload.get('assignment_source') or 'direct',
            coverage_note=payload.get('coverage_note'),
        )
        deduped_count += int(deduped or 0)
        if created:
            created_count += 1
        else:
            updated_count += 1

    cleared_count = _deactivate_stale_assignments(period, employee, active_levels, status='pasif')
    updated_count += cleared_count
    if cleared_count:
        _create_generation_log(
            period_id=period.id,
            employee_id=employee.id,
            event_type='cleared',
            reason=f'Pasifleşen {cleared_count} eski görev kaydı temizlendi.',
            severity='info',
            run_key=run_key,
            created_by_user_id=actor_user_id,
        )
    _log_generation_event(period=period, employee=employee, run_key=run_key, actor_user_id=actor_user_id)

    return {
        'employee_id': employee.id,
        'employee_name': employee.full_name,
        'resolved_chain': resolved_chain.to_dict(),
        'created_count': created_count,
        'updated_count': updated_count,
        'deduped_count': deduped_count,
        'issues': issues,
        'notes': notes,
        'availability': {
            'exempted': False,
            'reason': availability.reason,
            'available_days': availability.available_days,
        },
        'active_level_count': len(active_levels),
    }


def ensure_assignments_for_period(period, employee_ids: list[int] | None = None, actor_user_id: int | None = None):
    # P0 (M-1 Q3): kilitli/yayımlanmış dönemin görevleri hiçbir yoldan yeniden üretilmez (gerçek admin
    # dahil); kontrol her yazımdan (puanlama penceresi alanı dahil) önce yapılır.
    if period_is_frozen(period):
        logger.warning("BYS360 P0 görev üretimi reddedildi: dönem kilitli/yayımlanmış | period_id=%s | actor=%s", period.id, actor_user_id)
        return {
            'ok': False,
            'frozen': True,
            'period_id': getattr(period, 'id', None),
            'created': 0,
            'updated': 0,
            'created_count': 0,
            'updated_count': 0,
            'warnings': [FROZEN_PERIOD_TASKS_MESSAGE],
            'message': FROZEN_PERIOD_TASKS_MESSAGE,
            'actor_user_id': actor_user_id,
        }
    issues = validate_period_ready(period)
    rows = []
    run_key = uuid4().hex
    query = _employee_query()
    if employee_ids:
        query = query.filter(User.id.in_(employee_ids))
    # Başkan değerlendirme öznesi olarak dışarıda kalır; ancak lookup havuzunda kalmalıdır.
    # Aksi halde Grup Başkanı / özel istisna zincirlerinde 1. Amir = Başkan çözülemez.
    lookup_pool = list(_employee_query().all())
    hierarchy_lookup = build_lookup(lookup_pool)
    # BYS360_PHASE8_4_PERIOD_SCOPE_EMPLOYEES_START
    phase8_scope_all_employees = [candidate for candidate in query.all() if not is_president(candidate)]
    # BYS360_SELECTED_SCOPE_ASSESSOR_FIX_APPLIED_START
    # BYS360_SCORING_AFTER_PERIOD_END_APPLIED_START
    apply_scoring_start_to_period(period)
    phase8_scoring_window_payload = scoring_window_payload(period)
    if is_before_scoring_start(period):
        # AssignmentCoverageLog.employee_id is NOT NULL; this event is period-wide
        # with no associated employee, so it cannot be recorded as a generation log
        # row (would stage an unflushable record). Logged directly instead.
        logger.info("BYS360 puanlama penceresi henüz başlamadı: period_id=%s", period.id)
        return {
            'ok': True,
            'created_count': 0,
            'updated_count': 0,
            'skipped_count': 0,
            'message': 'Puanlama dönem bitişinden sonra başlayacaktır.',
            'scoring_window': phase8_scoring_window_payload,
            'policy_marker': 'BYS360_SCORING_AFTER_PERIOD_END_APPLIED',
        }
    # BYS360_SCORING_AFTER_PERIOD_END_APPLIED_END
    phase8_scope_matched_employees = filter_period_scope_employees(phase8_scope_all_employees, period)
    employees, phase8_scope_assessor_only_excluded = split_scored_employees_from_assessor_only(
        period,
        phase8_scope_matched_employees,
    )
    phase8_scope_payload = build_period_scope_generation_payload(period, phase8_scope_all_employees, employees)
    phase8_scope_payload.update({
        'matched_before_assessor_split_count': len(phase8_scope_matched_employees),
        'assessor_only_excluded_count': len(phase8_scope_assessor_only_excluded),
        'assessor_only_excluded_employee_ids': [getattr(employee, 'id', None) for employee in phase8_scope_assessor_only_excluded],
        'scope_fix_marker': 'BYS360_SELECTED_SCOPE_ASSESSOR_FIX_APPLIED',
    })
    for excluded_employee in phase8_scope_assessor_only_excluded:
        _create_generation_log(
            period_id=period.id,
            employee_id=excluded_employee.id,
            event_type='assessor_only_excluded',
            reason=assessor_only_exclusion_note(excluded_employee),
            severity='info',
            run_key=run_key,
            created_by_user_id=actor_user_id,
        )
    phase8_scope_allowed_employee_ids = {int(employee.id) for employee in employees if getattr(employee, 'id', None) is not None}
    # BYS360_SELECTED_SCOPE_ASSESSOR_FIX_APPLIED_END
    phase8_scope_deactivated_count = deactivate_out_of_scope_assignments_for_period(
        period,
        phase8_scope_allowed_employee_ids,
        run_key=run_key,
        actor_user_id=actor_user_id,
    )
    # BYS360_PHASE8_4_PERIOD_SCOPE_EMPLOYEES_END
    total_created = 0
    total_updated = 0
    total_deduped = 0
    warnings: list[str] = []
    infos: list[str] = []
    skipped = 0
    for employee in employees:
        row = sync_employee_assignments(period=period, employee=employee, run_key=run_key, actor_user_id=actor_user_id, hierarchy_lookup=hierarchy_lookup)
        rows.append(row)
        total_created += int(row.get('created_count') or 0)
        total_updated += int(row.get('updated_count') or 0)
        total_deduped += int(row.get('deduped_count') or 0)
        employee_name = row.get('employee_name') or getattr(employee, 'full_name', None) or 'Personel'
        row_issues = row.get('issues') or []
        row_notes = row.get('notes') or []
        if row.get('availability', {}).get('exempted') or not int(row.get('active_level_count') or 0):
            skipped += 1
        for message in row_issues:
            lowered = _normalize_text(message).lower()
            if lowered in {'seçilen dönem aktif değil.', 'secilen donem aktif degil.'}:
                continue
            full = f'{employee_name}: {message}'
            if _is_info_message(message):
                infos.append(full)
            else:
                warnings.append(full)
        for message in row_notes:
            lowered = _normalize_text(message).lower()
            if lowered in {'seçilen dönem aktif değil.', 'secilen donem aktif degil.'}:
                continue
            full = f'{employee_name}: {message}'
            if _is_info_message(message):
                infos.append(full)
            else:
                warnings.append(full)
    breakdown = _summarize_breakdown(rows)
    latest_log_rows = (
        AssignmentCoverageLog.query
        .filter_by(period_id=period.id, event_scope='generation', run_key=run_key)
        .order_by(AssignmentCoverageLog.created_at.desc(), AssignmentCoverageLog.id.desc())
        .all()
    )
    severity_summary = _severity_summary(latest_log_rows)
    notification_summary = _ensure_assignment_notifications_for_period(period)
    db.session.commit()
    return {
        'period_id': getattr(period, 'id', None),
        'employee_count': len(employees),
        'created_count': total_created,
        'updated_count': total_updated,
        'deduped_count': total_deduped,
        'issues': issues,
        'rows': rows,
        'created': total_created,
        'updated': total_updated,
        'deduped': total_deduped,
        'skipped': skipped,
        'warnings': warnings,
        'infos': infos,
        'warning_count': len(warnings),
        'info_count': len(infos),
        'breakdown': breakdown,
        'severity_summary': severity_summary,
        'run_key': run_key,
        'period_scope': phase8_scope_payload,
        'scope_type': phase8_scope_payload.get('scope_type'),
        'scope_target_count': phase8_scope_payload.get('matched_count'),
        'out_of_scope_deactivated_count': phase8_scope_deactivated_count,
        'notification_created_count': notification_summary.get('created', 0),
        'notification_updated_count': notification_summary.get('updated', 0),
        'notification_deduped_count': notification_summary.get('deduped', 0),
        'notification_total_count': notification_summary.get('total', 0),
        'message': 'Görev senkronu tamamlandı.',
    }

def sync_assignments_v2_for_period(period_id=None, actor_user_id=None):
    from app.models import PerformancePeriod

    period = None
    if period_id:
        period = db.session.get(PerformancePeriod, period_id)
    if period is None:
        period = (
            PerformancePeriod.query.filter_by(is_active=True)
            .order_by(PerformancePeriod.id.desc())
            .first()
        )
    if period is None:
        return {
            'ok': False,
            'period_id': None,
            'employee_count': 0,
            'created_count': 0,
            'updated_count': 0,
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'deduped': 0,
            'issues': ['Aktif dönem bulunamadı.'],
            'warnings': ['Aktif dönem bulunamadı.'],
            'infos': [],
            'warning_count': 1,
            'info_count': 0,
            'breakdown': {},
            'rows': [],
            'message': 'Aktif dönem bulunamadı.',
            'actor_user_id': actor_user_id,
        }
    payload = ensure_assignments_for_period(period=period, actor_user_id=actor_user_id)
    payload.setdefault('ok', True)
    payload['actor_user_id'] = actor_user_id
    return payload


def sync_employee_assignments_v2(period, employee=None, employee_id=None):
    target = employee
    if target is None and employee_id is not None:
        target = db.session.get(User, employee_id)
    if target is None:
        raise ValueError('Çalışan bulunamadı.')
    return sync_employee_assignments(period=period, employee=target)

# BYS360_PERFORMANCE_COMPLETION_PHASE4_THIRD_MANAGER_BOUND
# 3. amir opsiyonelliği ve sahte görev temizliği phase4_third_manager_policy üzerinden izlenir.

# BYS360_PERFORMANCE_COMPLETION_PHASE8_PERIOD_SCOPE_BOUND
# Çoklu dönem ve kapsamlı görev üretimi phase8_period_scope_policy sözleşmesini kullanır.

# BYS360_PERFORMANCE_COMPLETION_PHASE9_REMINDER_BOUND
# Otomatik hatırlatma ve aksatan amir bildirimi phase9_reminder_policy sözleşmesini kullanır.
