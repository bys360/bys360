from __future__ import annotations

# ruff: noqa: F821 - mobile bridge routes resolve legacy names from route_globals at registration time.

# BYS360 mobile performance read route bridge module.
# P11-C1 kapsamında küçük ve GET/read performans endpointleri ayrılmıştır.
# URL path, decorator ve JSON cevap davranışı değiştirilmemelidir.

def register_mobile_performance_read_routes_v1(route_globals) -> None:
    """Register selected read-only mobile performance routes in the original module context."""
    if route_globals.get("_BYS360_P11_C1_PERFORMANCE_READ_ROUTES_REGISTERED"):
        return

    globals().update(route_globals)

    @mobile_api_bp.get('/performance/manager-view')
    @require_mobile_user
    def mobile_performance_manager_view_v2852(user: User):
        if not _has_global_scope(user):
            return _module_payload([
                _metric('Görünürlük', 'Sınırlı', 'Bu alan yetkili yönetici kapsamına göre açılır', 'red', 'lock'),
                _metric('Veri Güvenliği', 'Aktif', 'Yetkisiz personel veya karne detayı gösterilmez', 'green', 'shield'),
            ], [])
        from app.api.mobile.performance_routes import _bys360_legacy_mobile_performance_reports
        return _bys360_legacy_mobile_performance_reports(user)

    @mobile_api_bp.get("/performance/periods")
    @require_mobile_user
    def mobile_performance_periods(user: User):
        q = PerformancePeriod.query.order_by(PerformancePeriod.id.desc())
        items: list[dict[str, Any]] = []
        for period in _mobile_perf_safe_all(q.limit(60)):
            period_id = getattr(period, "id", "")
            task_count = _mobile_perf_safe_count(_period_assignment_query(user, _as_int(period_id, 0))) if period_id else 0
            items.append(_item(period_id, _period_name(period), _date_range(period), _period_status(period), _period_scope(period), f"{task_count} görev" if task_count else "Dönem detayı", _period_progress(period)))
        active_count = _mobile_perf_safe_count(PerformancePeriod.query.filter_by(is_active=True)) if hasattr(PerformancePeriod, "is_active") else 0
        return _module_payload([
            _metric("Dönem", _mobile_perf_safe_count(q), "Toplam performans dönemi", "red", "timeline"),
            _metric("Aktif", active_count, "Açık dönem", "red", "check"),
            _metric("Kapsam", "Yetkili", "Dönem görünümü rol ve menü yetkisine bağlıdır", "red", "shield"),
        ], items)

    @mobile_api_bp.get("/performance/weights")
    @require_mobile_user
    def mobile_performance_weights(user: User):
        q = PerformanceWeightConfig.query.order_by(PerformanceWeightConfig.id.desc())
        rows = _mobile_perf_safe_all(q.limit(80))
        active_rows = [row for row in rows if bool(getattr(row, "is_active", True))]
        level3_rows = [row for row in rows if bool(getattr(row, "level_3_enabled", False))]
        unbalanced = []
        for row in rows:
            total = _v2821_float(getattr(row, "evaluator_1_weight", 0)) + _v2821_float(getattr(row, "evaluator_2_weight", 0)) + _v2821_float(getattr(row, "evaluator_3_weight", 0))
            if int(round(total)) != 100:
                unbalanced.append(row)
        items = [_v2821_weight_item(row) for row in rows]
        return _module_payload([
            _metric("Ağırlık Kuralı", len(rows), "Dönem veya genel ağırlık tanımı", "red", "scale"),
            _metric("Aktif", len(active_rows), "Kullanılabilir ağırlık kuralı", "green", "check"),
            _metric("3. Amir Açık", len(level3_rows), "3. amir modu açık olan yapı", "yellow", "admin"),
            _metric("Kontrol", len(unbalanced), "Toplamı %100 olmayan kural", "yellow", "warning"),
        ], items)

    @mobile_api_bp.get('/performance/tasks')
    @require_mobile_user
    def mobile_performance_tasks(user: User):
        q = _v2822_assignment_query(user).order_by(EvaluationAssignment.id.desc())
        open_q = _v2822_open_query(user)
        items = [_v2822_assignment_card(row) for row in _mobile_perf_safe_all(q.limit(80))]
        overdue = 0
        today = 0
        completed = 0
        for row in _mobile_perf_safe_all(_v2822_assignment_query(user).limit(500)):
            label, _, _ = _v2822_due_label(row)
            if label == 'Gecikti':
                overdue += 1
            elif label == 'Bugün Son Gün':
                today += 1
            if getattr(row, 'completed_at', None):
                completed += 1
        return _module_payload([
            _metric('Toplam Görev', _mobile_perf_safe_count(_v2822_assignment_query(user)), 'Yetkinize göre görünen görev', 'red', 'assignment'),
            _metric('Bekleyen', _mobile_perf_safe_count(open_q), 'İşlem bekleyen değerlendirme', 'red', 'assignment'),
            _metric('Bugün Son', today, 'Bugün tamamlanması gereken görev', 'yellow', 'today'),
            _metric('Geciken', overdue, 'Süresi geçen görev', 'yellow', 'warning'),
            _metric('Tamamlanan', completed, 'Tamamlanmış değerlendirme görevi', 'green', 'check'),
        ], items)

    @mobile_api_bp.get('/performance/manager-tasks')
    @require_mobile_user
    def mobile_performance_manager_tasks(user: User):
        if not _has_global_scope(user):
            return _module_payload([_metric('Görünürlük', 'Sınırlı', 'Bu ekran yalnızca yetkili roller için açılır', 'red', 'lock'), _metric('Veri Güvenliği', 'Aktif', 'Yetkisiz amir veya personel detayı gösterilmez', 'red', 'shield')], [])
        rows = _mobile_perf_safe_all(EvaluationAssignment.query.limit(1000))
        by_evaluator: dict[int, dict[str, Any]] = {}
        for row in rows:
            evaluator_id = int(getattr(row, 'evaluator_id', 0) or 0)
            if not evaluator_id:
                continue
            bucket = by_evaluator.setdefault(evaluator_id, {'user': getattr(row, 'evaluator', None), 'total': 0, 'pending': 0, 'overdue': 0, 'done': 0, 'last': None})
            bucket['total'] += 1
            label, _, _ = _v2822_due_label(row)
            if label == 'Tamamlandı':
                bucket['done'] += 1
            else:
                bucket['pending'] += 1
            if label == 'Gecikti':
                bucket['overdue'] += 1
            created = getattr(row, 'updated_at', None) or getattr(row, 'created_at', None)
            if created and (bucket['last'] is None or created > bucket['last']):
                bucket['last'] = created
        items: list[dict[str, Any]] = []
        for evaluator_id, data in sorted(by_evaluator.items(), key=lambda kv: (kv[1]['overdue'], kv[1]['pending']), reverse=True)[:80]:
            evaluator = data.get('user') or _mobile_perf_safe_get(User, evaluator_id)
            pending = int(data.get('pending', 0) or 0)
            overdue = int(data.get('overdue', 0) or 0)
            total = int(data.get('total', 0) or 0)
            status = 'Kritik' if overdue else ('Dikkat' if pending else 'Normal')
            progress = 100 if total == 0 else max(0, min(100, int((int(data.get('done', 0) or 0) / total) * 100)))
            items.append(_item(evaluator_id, _full_name(evaluator), f'Bekleyen {pending} / Geciken {overdue}', status, f'Toplam {total} görev', _date_text(data.get('last')) if data.get('last') else '', progress))
        overdue_total = sum(1 for row in rows if _v2822_due_label(row)[0] == 'Gecikti')
        pending_total = sum(1 for row in rows if _v2822_due_label(row)[0] != 'Tamamlandı')
        return _module_payload([_metric('Amir', len(by_evaluator), 'Görev atanmış değerlendirici', 'red', 'people'), _metric('Bekleyen', pending_total, 'Tamamlanmamış görev', 'red', 'assignment'), _metric('Geciken', overdue_total, 'Süresi geçen görev', 'yellow', 'warning'), _metric('Risk', 'Kritik' if overdue_total else ('Dikkat' if pending_total else 'Normal'), 'Yönetici takip göstergesi', 'yellow' if overdue_total else 'green', 'schedule')], items)

    @mobile_api_bp.get('/performance/categories')
    @require_mobile_user
    def mobile_performance_categories(user: User):
        rows = []
        try:
            if _has_global_scope(user):
                rows = _mobile_perf_safe_all(User.query.limit(10000))
            else:
                rows = [user]
        except Exception:
            rows = [user]
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            category = _v2852_employee_category(row) or 'Diğer'
            bucket = buckets.setdefault(category, {'total': 0, 'active': 0, 'sample': None})
            bucket['total'] += 1
            is_active = True
            try:
                is_active = bool(getattr(row, 'is_active', True))
            except Exception:
                is_active = True
            if is_active:
                bucket['active'] += 1
            if bucket['sample'] is None:
                bucket['sample'] = row
        defaults = ['Güvenlik', 'Temizlik', 'İdari Personel', 'Teknik Personel', 'Deneme Süreli Personel', 'Diğer']
        for name in defaults:
            buckets.setdefault(name, {'total': 0, 'active': 0, 'sample': None})
        items = []
        for category, data in sorted(buckets.items(), key=lambda kv: (-kv[1]['total'], kv[0])):
            total = int(data.get('total', 0) or 0)
            active_count = int(data.get('active', 0) or 0)
            status = 'Kayıt Var' if total else 'Tanımlı Kategori'
            items.append(_item(category, category, f'{active_count} aktif / {total} toplam personel', status, 'Kategori bazlı dönem ve rapor kapsamı', '', 100 if total else 35))
        return _module_payload([
            _metric('Kategori', len(buckets), 'Tanımlı kategori/grup başlığı', 'blue', 'people'),
            _metric('Personel', sum(int(v.get('total', 0) or 0) for v in buckets.values()), 'Yetki kapsamındaki personel', 'red', 'people'),
            _metric('Görünürlük', 'Yetkili', 'Kişi detayı rol kapsamına göre korunur', 'green', 'shield'),
        ], items)

    @mobile_api_bp.get('/performance/reminders')
    @require_mobile_user
    def mobile_performance_reminders(user: User):
        rows = _v2852_pending_assignments(user, 1000)
        items = []
        overdue = 0
        today = 0
        for row in rows[:120]:
            label, progress, tone = _v2852_due_label_safe(row)
            if label == 'Gecikti':
                overdue += 1
            if label == 'Bugün Son Gün':
                today += 1
            employee = getattr(row, 'employee', None) or _mobile_perf_safe_get(User, getattr(row, 'employee_id', None))
            period = getattr(row, 'period', None) or _mobile_perf_safe_get(PerformancePeriod, getattr(row, 'period_id', None))
            due = _date_text(getattr(row, 'due_date', None))
            items.append(_item(getattr(row, 'id', ''), _full_name(employee), _period_name(period), label, f'Son tarih {due}' if due else 'Hatırlatma bekliyor', '', progress))
        return _module_payload([
            _metric('Bekleyen', len(rows), 'Tamamlanmamış görev', 'red', 'assignment'),
            _metric('Bugün Son', today, 'Bugün tamamlanması gereken görev', 'yellow', 'schedule'),
            _metric('Geciken', overdue, 'Süresi geçen görev', 'yellow', 'warning'),
            _metric('Bildirim', 'Hazır', 'Hatırlatma ve aksatan amir raporuna veri sağlar', 'blue', 'reminder'),
        ], items)

    @mobile_api_bp.get('/performance/in-period-note-options')
    @require_mobile_user
    def mobile_performance_in_period_note_options_v2853(user: User):
        periods = []
        users = []
        try:
            for period in _mobile_perf_safe_all(PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(120)):
                periods.append({
                    'id': getattr(period, 'id', None),
                    'title': _period_name(period),
                    'subtitle': _date_range(period),
                    'status': _period_status(period),
                })
        except Exception:
            _mobile_perf_rollback_quietly()
            periods = []
        try:
            q = User.query.filter_by(is_active=True) if hasattr(User, 'is_active') else User.query
            if not _has_global_scope(user):
                # Mobilde güvenli varsayılan: global yetki yoksa en azından kendi kaydı gelir.
                q = User.query.filter(User.id == getattr(user, 'id', 0))
            for row in _mobile_perf_safe_all(q.order_by(User.id.asc()).limit(500)):
                users.append({
                    'id': getattr(row, 'id', None),
                    'name': _full_name(row),
                    'subtitle': getattr(row, 'sicil_no', '') or getattr(row, 'birim', '') or '',
                })
        except Exception:
            _mobile_perf_rollback_quietly()
            users = [{'id': getattr(user, 'id', None), 'name': _full_name(user), 'subtitle': getattr(user, 'sicil_no', '') or ''}]
        if not users:
            users = [{'id': getattr(user, 'id', None), 'name': _full_name(user), 'subtitle': getattr(user, 'sicil_no', '') or ''}]
        return jsonify({
            'source': 'real_api',
            'periods': periods,
            'users': users,
            'note_types': [
                {'value': 'olumlu_olay', 'label': 'Olumlu Olay'},
                {'value': 'olumsuz_olay', 'label': 'Olumsuz Olay'},
                {'value': 'basari', 'label': 'Başarı'},
                {'value': 'gelisim_ihtiyaci', 'label': 'Gelişim İhtiyacı'},
                {'value': 'genel_gozlem', 'label': 'Genel Gözlem'},
            ],
        })

    route_globals["_BYS360_P11_C1_PERFORMANCE_READ_ROUTES_REGISTERED"] = True
