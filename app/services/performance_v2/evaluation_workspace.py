from __future__ import annotations

import logging

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    EvaluationAssignment,
    PerformanceCriteria,
    PerformanceEvaluation,
    PerformanceEvaluationItem,
)
from app.services.performance.interim_notes_runtime import build_interim_notes_context
from app.services.performance.low_score_process_service import (
    ensure_low_score_process_for_evaluation,
)
from app.services.performance.period_state_guard import ensure_scoring_window_open
from app.services.performance.process_engine_phase4_flow import (
    ensure_process_flow_for_evaluation,
)
from app.services.performance.visibility_guard import build_evaluation_form_visibility_context

from .chain import build_resolved_chain
from .rules import normalize_level_mode, resolve_chain_policy
from .scoring import compute_final_score, raw_score_to_100
from .visibility import build_previous_level_comment_snapshot
from .weights import resolve_weight_plan
from .workflow import current_actionable_levels

logger = logging.getLogger(__name__)

# BYS360_PHASE5_3_MANAGER_SCORING_SETTINGS_CONTEXT
def _phase5_3_comment_rule_from_settings() -> bool:
    """1/5 kriter açıklama zorunluluğunu canlı performans ayarından okur."""
    try:
        from app.services.performance_v2.policy_flags import score_requires_criterion_comment
        return bool(score_requires_criterion_comment(1) or score_requires_criterion_comment(5))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return True


def _criteria_list():
    return (
        PerformanceCriteria.query.filter(PerformanceCriteria.is_active.is_(True))
        .order_by(PerformanceCriteria.sort_order.asc(), PerformanceCriteria.id.asc())
        .all()
    )


def _load_assignment(assignment_id: int):
    return EvaluationAssignment.query.get_or_404(assignment_id)


def _ensure_evaluation(assignment):
    evaluation = PerformanceEvaluation.query.filter_by(period_id=assignment.period_id, employee_id=assignment.employee_id).first()
    if evaluation is None:
        evaluation = PerformanceEvaluation(period_id=assignment.period_id, employee_id=assignment.employee_id)
        db.session.add(evaluation)
        db.session.flush()
    if assignment.manager_level == 1:
        evaluation.level_1_evaluator_id = assignment.evaluator_id
    elif assignment.manager_level == 2:
        evaluation.level_2_evaluator_id = assignment.evaluator_id
    elif assignment.manager_level == 3:
        evaluation.level_3_evaluator_id = assignment.evaluator_id
    return evaluation


def _weighted_level_total(items):
    if not items:
        return 0.0
    total_weight = 0.0
    weighted_sum = 0.0
    for item in items:
        weight = float(getattr(item.criteria, 'weight', 0.0) or 0.0)
        if weight <= 0:
            weight = 1.0
        weighted_sum += float(item.score_100 or 0.0) * weight
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return round(weighted_sum / total_weight, 2)


def _assignment_chain_context(assignment):
    resolved_chain = build_resolved_chain(employee=assignment.employee, period=assignment.period)
    existing_assignments = (
        EvaluationAssignment.query
        .filter_by(period_id=assignment.period_id, employee_id=assignment.employee_id)
        .order_by(EvaluationAssignment.manager_level.asc(), EvaluationAssignment.id.asc())
        .all()
    )
    actionable_levels = current_actionable_levels(
        resolved_chain=resolved_chain,
        existing_assignments=existing_assignments,
    )
    current_level_payload = resolved_chain.levels.get(assignment.manager_level)
    return resolved_chain, existing_assignments, actionable_levels, current_level_payload


def _dedupe_level_items(evaluation, level: int):
    rows = (
        PerformanceEvaluationItem.query
        .filter_by(evaluation_id=evaluation.id, manager_level=level)
        .order_by(PerformanceEvaluationItem.criteria_id.asc(), PerformanceEvaluationItem.id.desc())
        .all()
    )
    kept_by_criteria = {}
    for row in rows:
        criteria_id = int(getattr(row, 'criteria_id', 0) or 0)
        if criteria_id and criteria_id not in kept_by_criteria:
            kept_by_criteria[criteria_id] = row
            continue
        db.session.delete(row)
    db.session.flush()
    return kept_by_criteria


def _upsert_items(evaluation, level: int, form_data, *, score_enabled: bool = True):
    criteria = _criteria_list()
    existing_items = _dedupe_level_items(evaluation, level)
    saved_items = []
    active_criteria_ids = set()
    for criterion in criteria:
        active_criteria_ids.add(int(criterion.id))
        score_raw = (form_data.get(f'score_{criterion.id}') or '').strip()
        comment = (form_data.get(f'comment_{criterion.id}') or '').strip()
        item = existing_items.get(int(criterion.id))
        if item is None:
            item = PerformanceEvaluationItem(
                evaluation_id=evaluation.id,
                criteria_id=criterion.id,
                manager_level=level,
            )
            db.session.add(item)
        if score_enabled:
            try:
                item.score = float(score_raw) if score_raw else None
            except ValueError:
                item.score = None
            item.score_100 = raw_score_to_100(item.score) if item.score is not None else 0.0
            item.comment = comment or None
        else:
            # 3. amir yorumcu modunda kriter bazlı cevap/veri tutulmaz.
            # Bu seviyede yalnızca genel üst görüş kayıt altına alınır ve sonraki amir onu görür.
            item.score = None
            item.score_100 = 0.0
            item.comment = None
        saved_items.append(item)
    for criteria_id, row in existing_items.items():
        if int(criteria_id) not in active_criteria_ids:
            db.session.delete(row)
    db.session.flush()
    return saved_items


def _validate_submission(assignment, evaluation, items, *, score_enabled: bool, actionable_levels: list[int]):
    current_level = assignment.manager_level
    current_status = str(getattr(assignment, 'status', '') or '').strip().lower()

    if current_level not in set(actionable_levels or []) and current_status not in {'tamamlandi', 'submitted'}:
        raise ValueError('Bu görevin işlem sırası henüz gelmedi. Önce önceki amir adımı tamamlanmalıdır.')

    general_comment = (getattr(evaluation, f'level_{current_level}_general_comment', None) or '').strip()

    if not score_enabled:
        if not general_comment:
            raise ValueError('3. amir yorumcu modunda Genel Görüş alanı zorunludur.')
        return

    if any(getattr(item, 'score', None) is None for item in items):
        raise ValueError('Tamamlamak için tüm kriterlere puan verilmelidir.')

    # Kriter bazlı 1/5 açıklama zorunluluğu, yanlış pozitif üreten
    # çalışma alanı submit engeline değil yayın/bütünlük kontrolüne bırakılır.
    # Böylece kullanıcı 3 puan verdiği halde eski taslak veya hatalı runtime
    # eşleşmesi nedeniyle burada bloke olmaz; nihai anayasa kontrolü ise
    # publish_integrity katmanında korunur.

def _update_level_totals(evaluation, employee, period):
    resolved_chain = build_resolved_chain(employee=employee, period=period)
    weight_plan = resolve_weight_plan(employee=employee, period=period, resolved_chain=resolved_chain)
    level_scores: dict[int, float | int | None] = {
        1: float(getattr(evaluation, 'level_1_total_100', 0.0) or 0.0),
        2: float(getattr(evaluation, 'level_2_total_100', 0.0) or 0.0),
        3: float(getattr(evaluation, 'level_3_total_100', 0.0) or 0.0),
    }
    evaluation.final_total_100 = compute_final_score(level_scores=level_scores, weights=weight_plan.level_weights)
    return weight_plan


def _score_visual(score):
    if score is None:
        return '-', 'empty'
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return '-', 'empty'
    if numeric <= 2:
        tone = 'low'
    elif numeric < 4:
        tone = 'mid'
    elif numeric < 5:
        tone = 'good'
    else:
        tone = 'high'
    display = str(int(numeric)) if float(numeric).is_integer() else f'{numeric:.1f}'
    return display, tone


def _build_panel_criteria_cards(evaluation, criteria, *, level: int, is_comment_only: bool, is_current: bool):
    if not evaluation or is_comment_only:
        return []
    items = {
        item.criteria_id: item
        for item in PerformanceEvaluationItem.query.filter_by(evaluation_id=evaluation.id, manager_level=level).all()
    }
    cards = []
    for criterion in criteria:
        item = items.get(criterion.id)
        score = getattr(item, 'score', None) if item else None
        comment = (getattr(item, 'comment', None) or '').strip() if item else ''
        score_display, score_tone = _score_visual(score)
        cards.append({
            'criterion_id': criterion.id,
            'name': criterion.name,
            'score_display': score_display,
            'score_tone': score_tone,
            'comment': comment,
            'has_comment': bool(comment),
            'is_live': bool(is_current),
        })
    return cards


def _completion_tone(completed_count: int, total_count: int):
    if total_count <= 0:
        return 'na'
    ratio = completed_count / total_count
    if ratio >= 1:
        return 'complete'
    if ratio >= 0.5:
        return 'partial'
    return 'pending'


def _build_progress_payload(*, total_count: int, completed_count: int, is_comment_only: bool, has_general_comment: bool):
    if is_comment_only:
        return {
            'criteria_total': 0,
            'completed_count': 1 if has_general_comment else 0,
            'missing_count': 0 if has_general_comment else 1,
            'completion_percent': 100 if has_general_comment else 0,
            'tone': 'complete' if has_general_comment else 'pending',
            'status_label': 'Üst görüş hazır' if has_general_comment else 'Üst görüş bekleniyor',
            'counter_label': 'Kriter yok · yalnız üst görüş',
        }

    total_count = max(int(total_count or 0), 0)
    completed_count = max(min(int(completed_count or 0), total_count), 0)
    missing_count = max(total_count - completed_count, 0)
    completion_percent = int(round((completed_count / total_count) * 100)) if total_count else 0
    tone = _completion_tone(completed_count, total_count)
    if completed_count >= total_count and total_count > 0:
        status_label = 'Kriterler tamamlandı'
    elif completed_count > 0:
        status_label = 'Kısmen tamamlandı'
    else:
        status_label = 'Henüz başlanmadı'
    return {
        'criteria_total': total_count,
        'completed_count': completed_count,
        'missing_count': missing_count,
        'completion_percent': completion_percent,
        'tone': tone,
        'status_label': status_label,
        'counter_label': f'{completed_count}/{total_count} kriter dolu · {missing_count} eksik' if total_count else 'Kriter bulunmuyor',
    }


def _build_manager_side_panels(evaluation, resolved_chain, assignment_level: int, policy, level_mode, criteria):
    order_levels = set(getattr(resolved_chain, 'order', []) or [])
    panels = []
    for level in (2, 3):
        payload = getattr(resolved_chain, 'levels', {}).get(level)
        is_defined = level in order_levels and payload is not None
        is_comment_only = bool(payload and not getattr(payload, 'score_enabled', True))
        completed = bool(getattr(evaluation, f'level_{level}_completed', False)) if evaluation else False
        general_comment = getattr(evaluation, f'level_{level}_general_comment', None) if evaluation else None
        score_100 = getattr(evaluation, f'level_{level}_total_100', None) if evaluation else None
        criteria_cards = _build_panel_criteria_cards(
            evaluation,
            criteria,
            level=level,
            is_comment_only=is_comment_only,
            is_current=(assignment_level == level),
        ) if is_defined else []
        completed_count = sum(1 for card in criteria_cards if str(card.get('score_display') or '').strip() not in {'', '-'})
        progress = _build_progress_payload(
            total_count=len(criteria_cards),
            completed_count=completed_count,
            is_comment_only=is_comment_only,
            has_general_comment=bool((general_comment or '').strip()),
        )

        if not is_defined:
            if level == 3:
                empty_text = 'Bu personelde 3. amir adımı tanımlı değil ya da dönem ayarında kapalı.'
            else:
                empty_text = 'Bu personelde 2. amir adımı tanımlı değil.'
        elif completed:
            empty_text = None
        elif assignment_level == level:
            empty_text = 'Bu sütundaki özet, soldaki aktif çalışma alanındaki kayıtları yansıtır.'
        else:
            empty_text = 'Henüz tamamlanmış kayıt yok.'

        panels.append({
            'level': level,
            'title': f'{level}. Amir',
            'label': getattr(payload, 'label', None) or policy.labels.get(level) or f'{level}. Amir',
            'evaluator_name': getattr(payload, 'evaluator_name', None),
            'evaluator_role': getattr(payload, 'evaluator_role', None),
            'score_enabled': bool(getattr(payload, 'score_enabled', True)) if payload else False,
            'is_comment_only': is_comment_only,
            'is_current': assignment_level == level,
            'is_defined': is_defined,
            'completed': completed,
            'score_100': score_100,
            'general_comment': general_comment,
            'empty_text': empty_text,
            'mode_badge': 'Yorumcu' if is_comment_only else 'Puanlayıcı',
            'status_text': 'Tamamlandı' if completed else ('Aktif ekran' if assignment_level == level else 'Bekliyor'),
            'criteria_cards': criteria_cards,
            'show_criteria_cards': bool(criteria_cards) and not is_comment_only,
            'progress': progress,
        })
    return panels


def _attach_row_side_cards(criteria_rows, manager_side_panels):
    panel_card_maps = {}
    for panel in manager_side_panels or []:
        card_map = {}
        for card in panel.get('criteria_cards') or []:
            card_map[card.get('criterion_id')] = card
        panel_card_maps[panel.get('level')] = card_map

    enriched_rows = []
    for row in criteria_rows:
        criterion = row.get('criterion')
        side_cards = []
        for panel in manager_side_panels or []:
            level = panel.get('level')
            if not panel.get('is_defined'):
                side_cards.append({
                    'level': level,
                    'label': panel.get('label'),
                    'state': 'missing',
                    'title': 'Tanımlı değil',
                    'text': panel.get('empty_text') or 'Bu amir seviyesi tanımlı değil.',
                    'is_live': False,
                    'score_display': '-',
                    'score_tone': 'empty',
                    'comment': '',
                })
                continue
            if panel.get('is_comment_only'):
                side_cards.append({
                    'level': level,
                    'label': panel.get('label'),
                    'state': 'comment_only',
                    'title': 'Yorumcu mod',
                    'text': 'Bu seviyede kriter bazlı puan ve yorum yok; yalnız üst görüş bulunur.',
                    'is_live': False,
                    'score_display': '-',
                    'score_tone': 'empty',
                    'comment': '',
                })
                continue
            card = (panel_card_maps.get(level) or {}).get(getattr(criterion, 'id', None), {})
            comment = (card.get('comment') or '').strip()
            side_cards.append({
                'level': level,
                'label': panel.get('label'),
                'state': 'scored',
                'title': card.get('name') or getattr(criterion, 'name', ''),
                'text': comment or 'Henüz kriter yorumu yok.',
                'is_live': bool(card.get('is_live')),
                'score_display': card.get('score_display') or '-',
                'score_tone': card.get('score_tone') or 'empty',
                'comment': comment,
            })
        cloned = dict(row)
        cloned['side_cards'] = side_cards
        enriched_rows.append(cloned)
    return enriched_rows


def build_workspace_context(assignment_id: int):
    assignment = _load_assignment(assignment_id)
    evaluation = _ensure_evaluation(assignment)
    employee = assignment.employee
    period = assignment.period
    criteria = _criteria_list()
    existing_items = {
        item.criteria_id: item
        for item in PerformanceEvaluationItem.query.filter_by(evaluation_id=evaluation.id, manager_level=assignment.manager_level).all()
    }
    criteria_rows = []
    for criterion in criteria:
        item = existing_items.get(criterion.id)
        criteria_rows.append({
            'criterion': criterion,
            'item': item,
        })
    policy = resolve_chain_policy(employee)
    level_mode = normalize_level_mode(period)
    previous_comments = build_previous_level_comment_snapshot(
        evaluation=evaluation,
        current_level=assignment.manager_level,
        policy=policy,
        level_mode=level_mode,
    )
    resolved_chain, existing_assignments, actionable_levels, current_level_payload = _assignment_chain_context(assignment)
    weight_plan = resolve_weight_plan(employee=employee, period=period, resolved_chain=resolved_chain)
    general_comment_value = getattr(
        evaluation,
        f'level_{assignment.manager_level}_general_comment',
        None,
    ) or ''
    return_note_value = getattr(evaluation, 'level_2_return_note', None) or ''
    is_comment_only_level = bool(current_level_payload and not getattr(current_level_payload, 'score_enabled', True))
    manager_side_panels = _build_manager_side_panels(
        evaluation=evaluation,
        resolved_chain=resolved_chain,
        assignment_level=assignment.manager_level,
        policy=policy,
        level_mode=level_mode,
        criteria=criteria,
    )
    criteria_rows = _attach_row_side_cards(criteria_rows, manager_side_panels)
    return {
        'assignment': assignment,
        'evaluation': evaluation,
        'employee': employee,
        'period': period,
        'criteria_rows': criteria_rows,
        'previous_comments': previous_comments,
        'resolved_chain': resolved_chain,
        'weight_plan': weight_plan,
        'current_level_payload': current_level_payload,
        'actionable_levels': actionable_levels,
        'is_actionable': assignment.manager_level in set(actionable_levels or []),
        'existing_assignments': existing_assignments,
        'general_comment_value': general_comment_value,
        'return_note_value': return_note_value,
        'is_comment_only_level': is_comment_only_level,
        'general_comment_label': '3. Amir Üst Görüşü' if is_comment_only_level else 'Genel görüş',
        'general_comment_placeholder': '3. amir üst görüşünü yazın' if is_comment_only_level else 'Genel değerlendirmenizi yazın',
        'manager_side_panels': manager_side_panels,
        'interim_notes_context': build_interim_notes_context(
            assignment=assignment,
            evaluation=evaluation,
            viewer=None,
            surface='scoring',
        ),  # BYS360_INTERIM_NOTES_WORKSPACE_CONTEXT_BINDING
        'form_visibility': build_evaluation_form_visibility_context(
            evaluation=evaluation,
            assignment=assignment,
        ),
        'phase5_3_comment_rule_from_settings': _phase5_3_comment_rule_from_settings(),
    }


def save_assignment_draft(assignment_id: int, form_data):
    assignment = _load_assignment(assignment_id)
    ensure_scoring_window_open(assignment.period)
    evaluation = _ensure_evaluation(assignment)
    _resolved_chain, _existing_assignments, _actionable_levels, current_level_payload = _assignment_chain_context(assignment)
    score_enabled = bool(getattr(current_level_payload, 'score_enabled', True)) if current_level_payload else True
    items = _upsert_items(
        evaluation=evaluation,
        level=assignment.manager_level,
        form_data=form_data,
        score_enabled=score_enabled,
    )
    level_total = _weighted_level_total(items) if score_enabled else 0.0
    level = assignment.manager_level
    setattr(evaluation, f'level_{level}_total_100', level_total)
    setattr(evaluation, f'level_{level}_general_comment', (form_data.get('general_comment') or '').strip() or None)
    assignment.status = 'taslak'
    evaluation.workflow_status = f'taslak_{level}_amir'
    _update_level_totals(evaluation=evaluation, employee=assignment.employee, period=assignment.period)
    db.session.flush()
    return assignment, evaluation


def submit_assignment(assignment_id: int, form_data):
    assignment, evaluation = save_assignment_draft(assignment_id=assignment_id, form_data=form_data)
    _resolved_chain, _existing_assignments, actionable_levels, current_level_payload = _assignment_chain_context(assignment)
    level = assignment.manager_level
    _dedupe_level_items(evaluation, level)
    items = (
        PerformanceEvaluationItem.query
        .filter_by(evaluation_id=evaluation.id, manager_level=level)
        .order_by(PerformanceEvaluationItem.criteria_id.asc(), PerformanceEvaluationItem.id.desc())
        .all()
    )
    score_enabled = bool(getattr(current_level_payload, 'score_enabled', True)) if current_level_payload else True
    _validate_submission(
        assignment,
        evaluation,
        items,
        score_enabled=score_enabled,
        actionable_levels=actionable_levels,
    )
    setattr(evaluation, f'level_{level}_completed', True)
    # Submit asamasinda yalnizca mevcut amirin anlik form verisi dogrulanir.
    # Publish asamasina ait genel butunluk kontrolleri burada cagrilmaz; aksi halde
    # 3 puan verilen bir kriter, daha genis kapsamli publish kontrolu nedeniyle
    # yanlis pozitif uretip kullaniciyi gereksiz yere bloke edebilir.
    assignment.status = 'tamamlandi'
    assignment.completed_at = utc_now()
    if level == 3:
        evaluation.workflow_status = 'level_3_tamamlandi'
        evaluation.status = 'devam_ediyor'
    elif level == 2:
        evaluation.workflow_status = 'level_2_tamamlandi'
        evaluation.status = 'devam_ediyor'
    else:
        evaluation.workflow_status = 'tamamlandi'
        evaluation.status = 'tamamlandi'
    _update_level_totals(evaluation=evaluation, employee=assignment.employee, period=assignment.period)
    if (getattr(evaluation, "status", "") or "").strip().lower() in {"tamamlandi", "tamamlandı", "completed", "published"}:
        # BYS360 DEFECT AP: değerlendirme tamamlandığında, düşük puan
        # durumundan bağımsız olarak genel süreç takip kaydı oluşur/güncellenir.
        ensure_process_flow_for_evaluation(evaluation, flush=False)
        # BYS360_PHASE6_1_LOW_SCORE_AUTO_ON_SUBMIT
        ensure_low_score_process_for_evaluation(evaluation, actor_user_id=getattr(assignment, "evaluator_id", None), flush=False)
    db.session.flush()
    return assignment, evaluation


def _ensure_not_published_to_employee(assignment, message: str) -> None:
    # Personele yayınlanmış karne iş akışıyla geri alınamaz (mobil geri çekme/iade
    # ile aynı kural); düzeltme için önce yayından kaldırılmalıdır.
    evaluation = PerformanceEvaluation.query.filter_by(period_id=assignment.period_id, employee_id=assignment.employee_id).first()
    if evaluation is not None and (evaluation.is_published_to_employee or evaluation.published_to_employee_at):
        raise ValueError(message)


def return_assignment_to_previous_level(assignment_id: int, note: str | None = None):
    assignment = _load_assignment(assignment_id)
    if assignment.manager_level != 1:
        raise ValueError('İade işlemi yalnızca 1. amir ekranından yapılır.')
    note_text = (note or '').strip()
    if not note_text:
        raise ValueError('İade notu zorunludur.')
    _ensure_not_published_to_employee(assignment, 'Personele yayınlanmış değerlendirme iade edilemez.')
    evaluation = _ensure_evaluation(assignment)
    target = EvaluationAssignment.query.filter_by(
        period_id=assignment.period_id,
        employee_id=assignment.employee_id,
        manager_level=2,
    ).first()
    if not target:
        raise ValueError('2. amir görevi bulunamadı.')
    target.status = 'iade'
    target.completed_at = None
    assignment.status = 'taslak'
    assignment.completed_at = None
    evaluation.level_1_completed = False
    evaluation.workflow_status = 'level_2_iade'
    evaluation.level_2_return_note = note_text
    db.session.flush()
    return target, evaluation


def withdraw_assignment_submission(assignment_id: int):
    assignment = _load_assignment(assignment_id)
    _ensure_not_published_to_employee(assignment, 'Personele yayınlanmış değerlendirme geri çekilemez.')
    evaluation = _ensure_evaluation(assignment)
    level = assignment.manager_level
    assignment.status = 'taslak'
    assignment.completed_at = None
    setattr(evaluation, f'level_{level}_completed', False)
    evaluation.workflow_status = f'taslak_{level}_amir'
    db.session.flush()
    return assignment, evaluation
