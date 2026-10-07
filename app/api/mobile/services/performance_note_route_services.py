from __future__ import annotations

from typing import Any

from sqlalchemy import inspect

from app.models import EvaluationAssignment


def phase3c_mobile_performance_in_period_notes_v2853_service(user: Any, deps: dict[str, Any]):
    PerformancePeriod = deps['PerformancePeriod']
    User = deps['User']
    _full_name = deps['_full_name']
    _has_global_scope = deps['_has_global_scope']
    _item = deps['_item']
    _metric = deps['_metric']
    _mobile_perf_safe_get = deps['_mobile_perf_safe_get']
    _module_payload = deps['_module_payload']
    _period_name = deps['_period_name']
    _v2853_ensure_interim_notes_table = deps['_v2853_ensure_interim_notes_table']
    _v2853_note_type_label = deps['_v2853_note_type_label']
    db = deps['db']
    logger = deps['logger']

    _v2853_ensure_interim_notes_table()
    from sqlalchemy import text as _sql_text
    where = ['COALESCE(is_active, TRUE) = TRUE']
    params = {'limit': 160}
    if not _has_global_scope(user):
        where.append('(employee_id = :uid OR employee_user_id = :uid OR manager_id = :uid OR created_by = :uid OR created_by_id = :uid)')
        params['uid'] = int(getattr(user, 'id', 0) or 0)
    sql = _sql_text(f'''
        SELECT id, period_id, employee_id, employee_user_id, manager_id, created_by, note_type,
               COALESCE(title, note_title, '') AS title,
               COALESCE(note, note_body, note_text, content, description, '') AS note_body,
               COALESCE(remind_during_scoring, remind_in_evaluation, TRUE) AS remind_during_scoring,
               COALESCE(include_in_scorecard, visible_on_scorecard, FALSE) AS include_in_scorecard,
               COALESCE(created_at, occurred_at, updated_at) AS created_at
        FROM performance_interim_notes
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(created_at, occurred_at, updated_at) DESC NULLS LAST, id DESC
        LIMIT :limit
    ''')
    try:
        rows = db.session.execute(sql, params).mappings().all()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        try:
            rows = db.session.execute(_sql_text(str(sql).replace(' DESC NULLS LAST', ' DESC')), params).mappings().all()
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            db.session.rollback()
            rows = []
    items = []
    for row in rows:
        employee = _mobile_perf_safe_get(User, row.get('employee_id') or row.get('employee_user_id'))
        period = _mobile_perf_safe_get(PerformancePeriod, row.get('period_id'))
        type_label = _v2853_note_type_label(row.get('note_type'))
        title = row.get('title') or type_label
        body = str(row.get('note_body') or '').strip()
        meta = []
        if period:
            meta.append(_period_name(period))
        if row.get('remind_during_scoring'):
            meta.append('Puanlamada Hatırlatılır')
        if row.get('include_in_scorecard'):
            meta.append('Karneye Açık')
        item = _item(row.get('id'), f'{_full_name(employee)} - {title}' if employee else title, body, type_label, ' / '.join(meta), '', 70)
        item['icon'] = 'note'
        item['tone'] = 'info'
        items.append(item)
    real_count = len(items)
    if not items:
        items = [_item('note-empty', 'Dönem içi not kaydı bulunmadı', 'Olumlu/olumsuz olay, başarı, gelişim ihtiyacı veya genel gözlem notu oluştuğunda burada görünür.', 'Bilgi', 'Puanı otomatik üretmez', '', 35)]
    return _module_payload([
        _metric('Not', real_count, 'Yetki kapsamındaki dönem içi not', 'blue', 'note'),
        _metric('Kural', 'Otomatik Puan Yok', 'Notlar puanı otomatik değiştirmez', 'green', 'shield'),
        _metric('Karne', 'Seçimli', 'Yalnız işaretlenen notlar karne detayına açılır', 'yellow', 'scorecard'),
    ], items)


def phase3c_mobile_performance_create_in_period_note_v2853_service(user: Any, deps: dict[str, Any]):
    _has_global_scope = deps['_has_global_scope']
    _v2853_ensure_interim_notes_table = deps['_v2853_ensure_interim_notes_table']
    _v2853_note_bool = deps['_v2853_note_bool']
    _v2853_note_type_label = deps['_v2853_note_type_label']
    db = deps['db']
    jsonify = deps['jsonify']
    logger = deps['logger']

    _v2853_ensure_interim_notes_table()
    from flask import request as _request
    from sqlalchemy import text as _sql_text
    payload = _request.get_json(silent=True) or {}
    note = str(payload.get('note') or payload.get('note_body') or '').strip()
    if not note:
        return jsonify({'message': 'Not metni boş bırakılamaz.'}), 400
    try:
        period_id = int(raw_period_id) if (raw_period_id := payload.get('period_id')) else None
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        period_id = None
    try:
        employee_id = int(raw_employee_id) if (raw_employee_id := payload.get('employee_id')) else None
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        employee_id = None
    requesting_user_id = int(getattr(user, 'id', 0) or 0)
    if not employee_id:
        employee_id = requesting_user_id
    # BYS360 SECURITY FIX (Defect N): a caller may only create an in-period
    # note about themselves (self-note, pre-existing default behavior),
    # about anyone if they hold global scope, or about an employee they are
    # a real EvaluationAssignment evaluator for. Any other target is denied
    # BEFORE the INSERT/commit -- fail closed on lookup errors.
    if employee_id != requesting_user_id and not _has_global_scope(user):
        try:
            has_relationship = EvaluationAssignment.query.filter_by(
                evaluator_id=requesting_user_id,
                employee_id=employee_id,
            ).first() is not None
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            has_relationship = False
        if not has_relationship:
            return jsonify({'message': 'Bu personel için not oluşturma yetkiniz bulunmamaktadır.'}), 403
    note_type = str(payload.get('note_type') or 'genel_gozlem').strip() or 'genel_gozlem'
    # Historical production keeps VARCHAR(40); canonical installs use VARCHAR(80).
    # Inspect only. Reject an oversized historical value before INSERT, preserving
    # both the submitted value and all existing data (no truncation/schema repair).
    try:
        note_type_column = next(
            (c for c in inspect(db.session.connection()).get_columns('performance_interim_notes')
             if c['name'] == 'note_type'), None
        )
        note_type_limit = getattr(note_type_column['type'], 'length', None) if note_type_column else None
        if note_type_limit not in {40, 80}:
            return jsonify({'message': 'Dönem içi not şeması hazır değil.'}), 503
        if note_type_limit == 40 and len(note_type) > note_type_limit:
            return jsonify({'message': 'Not türü en fazla 40 karakter olabilir.'}), 400
        note_type = note_type[:80]  # retain the existing canonical/mobile contract
        title = str(payload.get('title') or _v2853_note_type_label(note_type)).strip()[:255]
        remind = _v2853_note_bool(payload.get('remind_during_scoring'), True)
        include = _v2853_note_bool(payload.get('include_in_scorecard'), False)
        db.session.execute(_sql_text('''
            INSERT INTO performance_interim_notes
            (period_id, employee_id, employee_user_id, manager_id, created_by, created_by_id, note_type, title, note, note_body,
             visibility_level, visibility_scope, remind_during_scoring, remind_in_evaluation, include_in_scorecard, visible_on_scorecard,
             is_active, active, occurred_at, created_at, updated_at)
            VALUES
            (:period_id, :employee_id, :employee_id, :manager_id, :created_by, :created_by, :note_type, :title, :note, :note,
             'manager_scope', 'manager_scope', :remind, :remind, :include, :include,
             TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        '''), {
            'period_id': period_id,
            'employee_id': employee_id,
            'manager_id': int(getattr(user, 'id', 0) or 0),
            'created_by': int(getattr(user, 'id', 0) or 0),
            'note_type': note_type,
            'title': title,
            'note': note,
            'remind': remind,
            'include': include,
        })
        db.session.commit()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        return jsonify({'message': 'Dönem içi not kaydedilemedi. Lütfen tekrar deneyin.'}), 500
    return jsonify({'source': 'real_api', 'ok': True, 'message': 'Dönem içi not kaydedildi.'})


def phase3c_mobile_performance_note_scorecard_v2863a_service(user: Any, deps: dict[str, Any]):
    PerformancePeriod = deps['PerformancePeriod']
    User = deps['User']
    _full_name = deps['_full_name']
    _has_global_scope = deps['_has_global_scope']
    _item = deps['_item']
    _metric = deps['_metric']
    _mobile_perf_safe_get = deps['_mobile_perf_safe_get']
    _module_payload = deps['_module_payload']
    _period_name = deps['_period_name']
    _v2853_ensure_interim_notes_table = deps['_v2853_ensure_interim_notes_table']
    _v2853_note_type_label = deps['_v2853_note_type_label']
    db = deps['db']
    logger = deps['logger']

    try:
        _v2853_ensure_interim_notes_table()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/performance_routes.py:1699)")
    from sqlalchemy import text as _sql_text
    # performance_interim_notes kolonları Alembic revision x1f3a9c5e7b2 ile sağlanır;
    # bu okuma yolu tabloya kolon eklemez.
    where = ['COALESCE(is_active, TRUE) = TRUE', 'COALESCE(include_in_scorecard, FALSE) = TRUE']
    params = {'limit': 160}
    if not _has_global_scope(user):
        where.append('(employee_id = :uid OR employee_user_id = :uid OR manager_id = :uid OR created_by = :uid OR created_by_id = :uid)')
        params['uid'] = int(getattr(user, 'id', 0) or 0)
    sql_text = "SELECT id, period_id, employee_id, employee_user_id, manager_id, created_by, note_type, title, note, note_body, created_at FROM performance_interim_notes WHERE " + ' AND '.join(where) + " ORDER BY COALESCE(created_at, CURRENT_TIMESTAMP) DESC, id DESC LIMIT :limit"
    try:
        rows = db.session.execute(_sql_text(sql_text), params).mappings().all()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        rows = []
    items = []
    for row in rows:
        employee = _mobile_perf_safe_get(User, row.get('employee_id') or row.get('employee_user_id'))
        period = _mobile_perf_safe_get(PerformancePeriod, row.get('period_id'))
        try:
            type_label = _v2853_note_type_label(row.get('note_type'))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            type_label = 'Not' if not row.get('note_type') else 'Bilinmiyor'
        title = str(row.get('title') or type_label or 'Karne Notu').strip()
        body = str(row.get('note') or row.get('note_body') or '').strip()
        meta = []
        if period:
            meta.append(_period_name(period))
        if type_label:
            meta.append(type_label)
        record_title = f'{_full_name(employee)} - {title}' if employee else title
        item = _item(row.get('id'), record_title, body, 'Karneye Açık', ' / '.join(meta), '', 80)
        item['icon'] = 'scorecard'
        item['tone'] = 'warning'
        items.append(item)
    real_count = len(items)
    if not items:
        items = [_item('note-scorecard-empty', 'Not karnesi kaydı bulunmadı', 'Dönem içi not eklerken “Karne detayında gösterilsin” işaretlenen kayıtlar burada görünür.', 'Bilgi', 'Puanı otomatik değiştirmez', '', 35)]
    return _module_payload([
        _metric('Karne Notu', real_count, 'Karne detayına açılan not', 'yellow', 'scorecard'),
        _metric('Görünürlük', 'Yetkili', 'Yalnız yetki kapsamındaki kayıtlar gösterilir', 'green', 'shield'),
        _metric('Puan Etkisi', 'Yok', 'Not karnesi puanı otomatik değiştirmez', 'blue', 'note'),
    ], items)
