from __future__ import annotations

from typing import Any


def phase3c_mobile_performance_full_feature_summary_service(user: Any, deps: dict[str, Any]):
    PerformancePeriod = deps['PerformancePeriod']
    PerformancePresidentApproval = deps['PerformancePresidentApproval']
    _assignment_query_for = deps['_assignment_query_for']
    _has_global_scope = deps['_has_global_scope']
    _item = deps['_item']
    _low_score_count = deps['_low_score_count']
    _metric = deps['_metric']
    _mobile_perf_safe_count = deps['_mobile_perf_safe_count']
    _module_payload = deps['_module_payload']
    _safe_avg_score = deps['_safe_avg_score']
    _snapshot_query_for = deps['_snapshot_query_for']
    _v2852_pending_assignments = deps['_v2852_pending_assignments']

    # Kapsam yalnız yetki yardımcılarından gelir; hata kapsamsız sorguya düşmez.
    _assignment_query_for(user)
    snapshot_q = _snapshot_query_for(user)
    active_periods = _mobile_perf_safe_count(PerformancePeriod.query.filter_by(is_active=True)) if hasattr(PerformancePeriod, 'is_active') else _mobile_perf_safe_count(PerformancePeriod.query)
    pending = len(_v2852_pending_assignments(user, 1000))
    scorecards = _mobile_perf_safe_count(snapshot_q)
    avg_score = _safe_avg_score(snapshot_q) if '_safe_avg_score' in deps.get('__route_globals__', {}) else 0
    low_score = _low_score_count(snapshot_q) if '_low_score_count' in deps.get('__route_globals__', {}) else 0
    approvals = _mobile_perf_safe_count(PerformancePresidentApproval.query.filter_by(status='pending')) if _has_global_scope(user) and PerformancePresidentApproval is not None else 0
    items = [
        _item('periods', 'Dönem Yönetimi', 'Yıllık, 6 aylık, 3 aylık, aylık ve özel dönemler', 'Aktif' if active_periods else 'Kontrol', 'Kapsam: kurum, birim, kategori, seçili personel', str(active_periods), 100 if active_periods else 45),
        _item('tasks', 'Değerlendirme Görevleri', 'Puanlama, taslak, tamamlama, geri çekme ve iade', 'Bekleyen' if pending else 'Tamamlandı', 'Mobil puanlama formu', str(pending), 60 if pending else 100),
        _item('scorecards', 'Karne ve Arşiv', 'Yayınlanmış karneler ve geçmiş kayıtlar', 'Yetki Kontrollü', 'Personel yalnızca yayınlanan kendi sonucunu görür', str(scorecards), 85),
        _item('approvals', 'Başkan/Üst Onay ve Yayın Ön Onayı', '70 altı ve final yayın kontrol akışları', 'Onay Bekliyor' if approvals else 'Kontrollü', 'Yayın kilidi korunur', str(approvals), 55 if approvals else 100),
        _item('reports', 'Raporlar, Risk ve Gelişim', 'Kategori, dönem, amir, personel, risk, gelişim ve hatırlatma ekranları', 'Aktif', 'Web performans modülüyle aynı başlıklar', '', 100),
    ]
    return _module_payload([
        _metric('Aktif Dönem', active_periods, 'Açık veya hazırlıktaki performans dönemi', 'red', 'timeline'),
        _metric('Bekleyen Görev', pending, 'Puanlama veya takip bekleyen görev', 'red', 'assignment'),
        _metric('Karne', scorecards, 'Yetki kapsamındaki karne kayıtları', 'green', 'scorecard'),
        _metric('Ortalama', f'{avg_score}/100' if avg_score else '-', 'Yayınlanmış sonuç ortalaması', 'green', 'trending_up'),
        _metric('70 Altı', low_score, 'Düşük performans takibi', 'yellow', 'warning'),
        _metric('Üst Onay', approvals, 'Başkan/Üst Onay bekleyen kayıt', 'red', 'verified_user'),
    ], items)


def phase3c_mobile_performance_publish_preapproval_service(user: Any, deps: dict[str, Any]):
    PerformancePeriod = deps['PerformancePeriod']
    PerformanceResultSnapshot = deps['PerformanceResultSnapshot']
    User = deps['User']
    _full_name = deps['_full_name']
    _has_global_scope = deps['_has_global_scope']
    _item = deps['_item']
    _metric = deps['_metric']
    _mobile_perf_safe_all = deps['_mobile_perf_safe_all']
    _mobile_perf_safe_get = deps['_mobile_perf_safe_get']
    _module_payload = deps['_module_payload']
    _period_name = deps['_period_name']
    _snapshot_query_for = deps['_snapshot_query_for']
    _v2852_items_from_models = deps['_v2852_items_from_models']
    _v2852_score = deps['_v2852_score']
    logger = deps['logger']

    # BYS360_SECURITY_FIX_DEFECT_O2: _v2852_items_from_models() runs a
    # zero-filter, organization-wide query across every model in its list.
    # That unscoped shortcut must only ever be reachable for
    # _has_global_scope() callers; non-global callers must go straight to
    # the already-correctly-scoped _snapshot_query_for(user) fallback below.
    items = _v2852_items_from_models(['PerformancePublishPreApproval', 'PerformancePublicationPreApproval', 'PerformancePublishApproval', 'PerformancePublishLog', 'PerformancePublicationApproval'], ['employee_name', 'title', 'name', 'period_name'], ['description', 'note', 'period_name', 'status_text'], ['status', 'approval_status', 'state'], ['period_name', 'created_at', 'approved_by_name'], ['final_score', 'score']) if _has_global_scope(user) else []
    if not items:
        pending = []
        try:
            q = _snapshot_query_for(user)
            if hasattr(PerformanceResultSnapshot, 'is_published'):
                q = q.filter(PerformanceResultSnapshot.is_published.is_(False))
            pending = _mobile_perf_safe_all(q.limit(60))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pending = []
        for row in pending:
            employee = getattr(row, 'employee', None) or _mobile_perf_safe_get(User, getattr(row, 'employee_id', None))
            period = getattr(row, 'period', None) or _mobile_perf_safe_get(PerformancePeriod, getattr(row, 'period_id', None))
            score = _v2852_score(row)
            items.append(_item(getattr(row, 'id', ''), _full_name(employee), _period_name(period), 'Yayın Ön Kontrol', 'Final yayın öncesi kontrol', f'{score}/100' if score else '', 55))
    return _module_payload([
        _metric('Ön Onay', len(items), 'Final yayın öncesi görünen kayıt', 'red', 'approval'),
        _metric('Yayın Kilidi', 'Aktif', 'Ön onay olmadan final yayın engellenir', 'yellow', 'lock'),
        _metric('Yetki', 'Rol Bazlı', 'Yayın işlemi yetkili kullanıcıyla sınırlıdır', 'green', 'shield'),
    ], items)


def phase3c_mobile_performance_risk_analysis_v2852_service(user: Any, deps: dict[str, Any]):
    PerformancePeriod = deps['PerformancePeriod']
    PerformanceResultSnapshot = deps['PerformanceResultSnapshot']
    User = deps['User']
    _full_name = deps['_full_name']
    _item = deps['_item']
    _metric = deps['_metric']
    _mobile_perf_safe_all = deps['_mobile_perf_safe_all']
    _mobile_perf_safe_get = deps['_mobile_perf_safe_get']
    _module_payload = deps['_module_payload']
    _period_name = deps['_period_name']
    _snapshot_query_for = deps['_snapshot_query_for']
    _v2852_score = deps['_v2852_score']
    logger = deps['logger']

    try:
        snapshot_q = _snapshot_query_for(user).order_by(PerformanceResultSnapshot.id.desc())
        rows = _mobile_perf_safe_all(snapshot_q.limit(200))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        rows = []
    low = [row for row in rows if 0 < _v2852_score(row) < 70]
    high = [row for row in rows if _v2852_score(row) >= 90]
    items = []
    for row in low[:80]:
        employee = getattr(row, 'employee', None) or _mobile_perf_safe_get(User, getattr(row, 'employee_id', None))
        period = getattr(row, 'period', None) or _mobile_perf_safe_get(PerformancePeriod, getattr(row, 'period_id', None))
        score = _v2852_score(row)
        items.append(_item(getattr(row, 'id', ''), _full_name(employee), _period_name(period), '70 Altı Risk', 'Başkan/Üst Onay ve gelişim takibi gerekebilir', f'{score}/100', 35))
    if not items:
        items = [_item('risk-empty', 'Riskli kayıt bulunmadı', 'Yetki kapsamınızda 70 altı performans sonucu görünmüyor.', 'Normal', 'Risk takibi aktif', '', 100)]
    return _module_payload([
        _metric('70 Altı', len(low), 'Düşük performans/risk kaydı', 'yellow', 'warning'),
        _metric('90 Üstü', len(high), 'Yüksek başarı takibi', 'green', 'trending_up'),
        _metric('Risk Takibi', 'Aktif', 'Başkan/Üst Onay ve gelişim süreciyle bağlantılıdır', 'red', 'risk'),
    ], items)
