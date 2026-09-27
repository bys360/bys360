from __future__ import annotations

from typing import Any


def phase3c_mobile_performance_task_score_form_service(user: Any, assignment_id: int, deps: dict[str, Any]):
    EvaluationAssignment = deps['EvaluationAssignment']
    _mobile_perf_safe_get = deps['_mobile_perf_safe_get']
    _v2822_can_view_assignment = deps['_v2822_can_view_assignment']
    _v2835_json_error = deps['_v2835_json_error']
    _v2835_score_form_payload = deps['_v2835_score_form_payload']
    jsonify = deps['jsonify']

    assignment = _mobile_perf_safe_get(EvaluationAssignment, assignment_id)
    if not assignment or not _v2822_can_view_assignment(user, assignment):
        return _v2835_json_error('Bu değerlendirme görevine erişim yetkiniz bulunmamaktadır.', 403)
    return jsonify(_v2835_score_form_payload(assignment))


def phase3c_mobile_performance_task_score_submit_service(user: Any, assignment_id: int, deps: dict[str, Any]):
    EvaluationAssignment = deps['EvaluationAssignment']
    PerformanceEvaluation = deps['PerformanceEvaluation']
    PerformancePeriod = deps['PerformancePeriod']
    _label = deps['_label']
    _mobile_perf_safe_get = deps['_mobile_perf_safe_get']
    _v2822_can_view_assignment = deps['_v2822_can_view_assignment']
    _v2835_criteria_rows = deps['_v2835_criteria_rows']
    _v2835_json_error = deps['_v2835_json_error']
    _v2835_score_mode_for = deps['_v2835_score_mode_for']
    calculate_preview_total_100 = deps['calculate_preview_total_100']
    db = deps['db']
    jsonify = deps['jsonify']
    logger = deps['logger']
    request = deps['request']
    save_evaluation_level = deps['save_evaluation_level']
    utc_now = deps['utc_now']
    validate_general_comment_requirements = deps['validate_general_comment_requirements']

    assignment = _mobile_perf_safe_get(EvaluationAssignment, assignment_id)
    if not assignment or not _v2822_can_view_assignment(user, assignment):
        return _v2835_json_error('Bu değerlendirme görevine erişim yetkiniz bulunmamaktadır.', 403)

    body = request.get_json(silent=True) or {}
    completed = bool(body.get('completed'))
    general_comment = str(body.get('general_comment') or body.get('generalComment') or '').strip()
    raw_items = items if isinstance(items := body.get('items'), list) else []

    period = getattr(assignment, 'period', None) or _mobile_perf_safe_get(PerformancePeriod, getattr(assignment, 'period_id', None))
    level = int(getattr(assignment, 'manager_level', 0) or 0)
    score_mode = _v2835_score_mode_for(assignment, period)
    criteria_rows = _v2835_criteria_rows()
    criteria_by_id = {int(getattr(row, 'id', 0) or 0): row for row in criteria_rows}
    criteria_weight_map = {cid: float(getattr(row, 'weight', 0) or 0) for cid, row in criteria_by_id.items()}

    item_payloads: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            criteria_id = int(raw.get('criteria_id') or raw.get('id'))  # type: ignore[arg-type]
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/api/mobile/performance_routes.py:956)")
            continue
        if criteria_id not in criteria_by_id:
            continue
        raw_score = raw.get('score')
        if raw_score in (None, ''):
            continue
        try:
            score_value = float(str(raw_score).replace(',', '.'))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return _v2835_json_error('Puan 1 ile 5 arasında olmalıdır.', 400)
        item_payloads.append({
            'criteria_id': criteria_id,
            'score': score_value,
            'comment': str(raw.get('comment') or '').strip(),
            'strength_note': str(raw.get('strength_note') or '').strip(),
            'justification': str(raw.get('justification') or raw.get('comment') or '').strip(),
        })

    try:
        # Personele yayınlanmış değerlendirme mobilden değiştirilemez (mobil geri
        # çekme / iade ile aynı yayın kontrolü); karar hiçbir yazmadan önce verilir.
        existing_evaluation = PerformanceEvaluation.query.filter_by(
            period_id=getattr(assignment, 'period_id', None),
            employee_id=getattr(assignment, 'employee_id', None),
        ).first()
        if existing_evaluation is not None and bool(getattr(existing_evaluation, 'is_published_to_employee', False) or getattr(existing_evaluation, 'published_to_employee_at', None)):
            raise ValueError('Personele yayınlanmış değerlendirme mobil ekrandan değiştirilemez.')
        if score_mode:
            if completed and criteria_rows and len(item_payloads) < len(criteria_rows):
                return _v2835_json_error('Tamamlamak için tüm değerlendirme kriterlerine 1-5 arası puan girilmelidir.', 400)
            if not item_payloads and not general_comment:
                return _v2835_json_error('Kaydetmek için en az bir puan veya genel görüş girilmelidir.', 400)
            if completed:
                # Mobil uygulamada 1 ve 5 puan için kriter açıklaması zorunlu değildir.
                # 70 altı / 90 üstü genel görüş zorunluluğu aşağıda korunur.
                preview_total = calculate_preview_total_100(item_payloads, criteria_weight_map)
                raw_scores = [float(item.get('score') or 0) for item in item_payloads]
                validate_general_comment_requirements(
                    manager_level=level,
                    general_comment=general_comment,
                    level_total_100=preview_total,
                    raw_scores=raw_scores,
                    requires_level_2_comment=False,
                )
        else:
            if not general_comment:
                return _v2835_json_error('3. amir yorum/görüş modunda genel görüş zorunludur.', 400)
            item_payloads = []

        evaluation = save_evaluation_level(
            period_id=getattr(assignment, 'period_id', None),
            employee_id=getattr(assignment, 'employee_id', None),
            manager_level=level,
            evaluator_id=getattr(assignment, 'evaluator_id', None),
            item_payloads=item_payloads,
            general_comment=general_comment,
            completed=completed or not score_mode,
        )

        if completed or not score_mode:
            assignment.status = 'tamamlandi'
            assignment.completed_at = utc_now()
        else:
            assignment.status = 'kismen_tamamlandi'
            assignment.completed_at = None
        db.session.add(assignment)
        db.session.add(evaluation)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return _v2835_json_error(str(exc), 400)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        return _v2835_json_error('Puanlama kaydedilemedi. Lütfen bilgileri kontrol edip tekrar deneyin.', 500)

    level_total = float(getattr(evaluation, f'level_{level}_total_100', 0) or 0)
    return jsonify({
        'source': 'real_api',
        'message': 'Değerlendirme başarıyla tamamlandı.' if (completed or not score_mode) else 'Taslak başarıyla kaydedildi.',
        'assignment_id': str(getattr(assignment, 'id', '') or ''),
        'evaluation_id': str(getattr(evaluation, 'id', '') or ''),
        'status_label': _label(getattr(assignment, 'status', None), 'Kaydedildi'),
        'level_score_100': round(level_total, 2),
        'final_score_100': round(float(getattr(evaluation, 'final_total_100', 0) or 0), 2),
    })


def phase3c_mobile_performance_task_score_action_service(user: Any, assignment_id: int, deps: dict[str, Any]):
    EvaluationAssignment = deps['EvaluationAssignment']
    _mobile_perf_safe_get = deps['_mobile_perf_safe_get']
    _v2822_can_view_assignment = deps['_v2822_can_view_assignment']
    _v2835_existing_evaluation = deps['_v2835_existing_evaluation']
    _v2835_json_error = deps['_v2835_json_error']
    _v2837_return_assignment = deps['_v2837_return_assignment']
    _v2837_withdraw_assignment = deps['_v2837_withdraw_assignment']
    db = deps['db']
    jsonify = deps['jsonify']
    logger = deps['logger']
    request = deps['request']

    assignment = _mobile_perf_safe_get(EvaluationAssignment, assignment_id)
    if not assignment or not _v2822_can_view_assignment(user, assignment):
        return _v2835_json_error('Bu değerlendirme görevine erişim yetkiniz bulunmamaktadır.', 403)
    body = request.get_json(silent=True) or {}
    action = str(body.get('action') or '').strip().lower()
    note = str(body.get('note') or '').strip()
    evaluation = _v2835_existing_evaluation(assignment)
    level = int(getattr(assignment, 'manager_level', 0) or 0)
    try:
        if action in {'withdraw', 'geri_cek', 'geri-cek'}:
            result = _v2837_withdraw_assignment(assignment, evaluation, level, user, note)
        elif action in {'return', 'iade', 'iade_et', 'iade-et'}:
            result = _v2837_return_assignment(assignment, evaluation, level, user, note)
        else:
            return _v2835_json_error('Bilinmeyen işlem seçildi.', 400)
    except ValueError as exc:
        db.session.rollback()
        return _v2835_json_error(str(exc), 400)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        return _v2835_json_error('İşlem tamamlanamadı. Lütfen tekrar deneyin.', 500)
    result.update({'source': 'real_api', 'assignment_id': str(getattr(assignment, 'id', '') or '')})
    return jsonify(result)
