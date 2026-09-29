from __future__ import annotations

# BYS360 V1E: emergency runtime recovery for the Phase2Y wildcard-import regression.
# This deliberately restores the shared mobile contract first; explicit imports can be
# reintroduced later only after a per-file F821 gate and smoke test.
from app.api.mobile.shared import (
    User,
    _as_int,
    _has_global_scope,
    _item,
    _metric,
    _module_payload,
    _safe_count,
    db,
    jsonify,
    mean,
    mobile_api_bp,
    request,
    require_mobile_user,
)


def _v2853_float(value, default=0.0):
    try:
        text_value = str(value if value is not None else '').replace(',', '.').replace('%', '').strip()
        if not text_value:
            return float(default)
        return float(text_value)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/kpi_target_management.py:18")
        return float(default)


def _v2853_completion(current_value, target_value):
    target = _v2853_float(target_value, 0.0)
    current = _v2853_float(current_value, 0.0)
    if target <= 0:
        return 0
    return max(0, min(100, int(round((current / target) * 100))))


def _v2853_risk(rate):
    rate = int(rate or 0)
    if rate >= 90:
        return 'low', 'success'
    if rate >= 70:
        return 'medium', 'warning'
    return 'high', 'danger'


def _v2853_status_label(value):
    raw = str(value or '').strip().lower()
    return {
        'active': 'Aktif',
        'ongoing': 'Devam Ediyor',
        'devam': 'Devam Ediyor',
        'devam_ediyor': 'Devam Ediyor',
        'completed': 'Tamamlandı',
        'done': 'Tamamlandı',
        'closed': 'Kapandı',
        'draft': 'Taslak',
    }.get(raw, str(value or 'Devam Ediyor'))


def _v2853_target_models():
    try:
        from app.modules.strategic_performance.models import (
            PerformanceTarget as _Target,
            PerformanceTargetPeriod as _TargetPeriod,
        )
        return _Target, _TargetPeriod
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/kpi_target_management.py:57")
        return None, None


def _v2853_target_code(user):
    import time
    return f'MOB-{int(time.time())}-{int(getattr(user, "id", 0) or 0)}'


@mobile_api_bp.get('/kpi/target-management')
@require_mobile_user
def mobile_kpi_target_management_v2853(*args, **kwargs):
    """P1.4C service delegate wrapper; URL/endpoint/decorator korunur."""
    from app.api.mobile.services.dashboard_service import (
        mobile_kpi_target_management_v2853_delegate,
    )
    return mobile_kpi_target_management_v2853_delegate(_bys360_legacy_mobile_kpi_target_management_v2853, *args, **kwargs)

def _bys360_legacy_mobile_kpi_target_management_v2853(user: User):
    Target, TargetPeriod = _v2853_target_models()
    if Target is None:
        return _module_payload([
            _metric('SP-1', 'Hazır Değil', 'KPI/Hedef modeli bu kurulumda bulunamadı', 'yellow', 'warning'),
            _metric('Mobil Ekran', 'Aktif', 'Model geldiğinde otomatik veri çeker', 'green', 'flag'),
        ], [])
    items = []
    total = 0
    active = 0
    risky = 0
    completed = 0
    avg_rate = 0
    try:
        q = Target.query
        if not _has_global_scope(user) and hasattr(Target, 'owner_user_id'):
            q = q.filter(Target.owner_user_id == int(getattr(user, 'id', 0) or 0))
        total = _safe_count(q)
        rows = q.order_by(Target.id.desc()).limit(250).all()
        rates = []
        for target in rows:
            rate = _as_int(getattr(target, 'completion_rate', None)) if getattr(target, 'completion_rate', None) is not None else _v2853_completion(getattr(target, 'current_value', None), getattr(target, 'target_value', None))
            rates.append(rate)
            risk_level = str(getattr(target, 'risk_level', '') or '').lower()
            risk, tone = _v2853_risk(rate)
            if risk_level in {'high', 'yuksek', 'yüksek'}:
                tone = 'danger'
                risky += 1
            elif risk == 'high':
                risky += 1
            status = str(getattr(target, 'status', '') or 'ongoing')
            if status.lower() in {'active', 'ongoing', 'devam', 'devam_ediyor'}:
                active += 1
            if rate >= 100 or status.lower() in {'completed', 'done', 'closed'}:
                completed += 1
            title = getattr(target, 'target_name', None) or getattr(target, 'name', None) or 'KPI hedefi'
            subtitle = getattr(target, 'description', None) or getattr(target, 'category', None) or getattr(target, 'target_type', None) or ''
            target_value = getattr(target, 'target_value', None)
            current_value = getattr(target, 'current_value', None)
            item = _item(getattr(target, 'id', ''), title, subtitle, _v2853_status_label(status), getattr(target, 'category', '') or getattr(target, 'target_type', '') or 'KPI', f'{current_value or 0}/{target_value or 0}', rate)
            item['icon'] = 'flag'
            item['tone'] = tone
            items.append(item)
        avg_rate = int(mean(rates)) if rates else 0
    except Exception:
        db.session.rollback()
        items = []
    return _module_payload([
        _metric('Hedef', total, 'Yetki kapsamındaki KPI/Hedef kartı', 'green', 'flag'),
        _metric('Aktif', active, 'Devam eden hedef', 'blue', 'target'),
        _metric('Ortalama', f'%{avg_rate}', 'Gerçekleşme ortalaması', 'green', 'trending_up'),
        _metric('Riskli', risky, 'Takip gerektiren hedef', 'yellow', 'warning'),
        _metric('Tamamlanan', completed, 'Hedefe ulaşan kayıt', 'green', 'check'),
    ], items)


@mobile_api_bp.post('/kpi/target-management')
@require_mobile_user
def mobile_kpi_target_create_v2853(*args, **kwargs):
    """P1.4C service delegate wrapper; URL/endpoint/decorator korunur."""
    from app.api.mobile.services.dashboard_service import mobile_kpi_target_create_v2853_delegate
    return mobile_kpi_target_create_v2853_delegate(_bys360_legacy_mobile_kpi_target_create_v2853, *args, **kwargs)

def _bys360_legacy_mobile_kpi_target_create_v2853(user: User):
    Target, TargetPeriod = _v2853_target_models()
    if Target is None:
        return jsonify({'message': 'KPI/Hedef modeli bu kurulumda bulunamadı.'}), 503
    payload = request.get_json(silent=True) or {}
    target_name = str(payload.get('target_name') or payload.get('name') or '').strip()
    if not target_name:
        return jsonify({'message': 'Hedef adı boş bırakılamaz.'}), 400
    target_value = _v2853_float(payload.get('target_value'), 0.0)
    current_value = _v2853_float(payload.get('current_value'), 0.0)
    rate = _v2853_completion(current_value, target_value)
    risk, _tone = _v2853_risk(rate)
    try:
        target = Target()
        if hasattr(target, 'target_code'):
            target.target_code = _v2853_target_code(user)
        if hasattr(target, 'target_name'):
            target.target_name = target_name
        elif hasattr(target, 'name'):
            target.name = target_name
        if hasattr(target, 'description'):
            target.description = str(payload.get('description') or '').strip()
        if hasattr(target, 'category'):
            target.category = str(payload.get('category') or 'KPI').strip() or 'KPI'
        if hasattr(target, 'target_type'):
            target.target_type = str(payload.get('target_type') or 'personnel').strip() or 'personnel'
        if hasattr(target, 'target_value'):
            target.target_value = target_value
        if hasattr(target, 'current_value'):
            target.current_value = current_value
        if hasattr(target, 'completion_rate'):
            target.completion_rate = rate
        if hasattr(target, 'risk_level'):
            target.risk_level = risk
        if hasattr(target, 'status'):
            target.status = 'completed' if rate >= 100 else 'ongoing'
        if hasattr(target, 'owner_user_id'):
            target.owner_user_id = int(getattr(user, 'id', 0) or 0)
        if hasattr(target, 'created_by'):
            target.created_by = int(getattr(user, 'id', 0) or 0)
        db.session.add(target)
        db.session.commit()
        return jsonify({'source': 'real_api', 'ok': True, 'message': 'KPI hedef kartı oluşturuldu.', 'id': getattr(target, 'id', None)})
    except Exception:
        db.session.rollback()
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: KPI hedef kartı oluşturma hatası (app/api/mobile/domains/kpi_target_management.py:196)")
        return jsonify({'message': 'KPI hedef kartı oluşturulamadı. Lütfen bilgileri kontrol edip tekrar deneyin.'}), 500


@mobile_api_bp.post('/kpi/target-management/<int:target_id>/progress')
@require_mobile_user
def mobile_kpi_target_progress_v2853(*args, **kwargs):
    """P1.4C service delegate wrapper; URL/endpoint/decorator korunur."""
    from app.api.mobile.services.dashboard_service import mobile_kpi_target_progress_v2853_delegate
    return mobile_kpi_target_progress_v2853_delegate(_bys360_legacy_mobile_kpi_target_progress_v2853, *args, **kwargs)

def _bys360_legacy_mobile_kpi_target_progress_v2853(user: User, target_id: int):
    Target, TargetPeriod = _v2853_target_models()
    if Target is None:
        return jsonify({'message': 'KPI/Hedef modeli bu kurulumda bulunamadı.'}), 503
    target = db.session.get(Target, int(target_id))
    if target is None:
        return jsonify({'message': 'KPI hedef kartı bulunamadı.'}), 404
    # Same owner scope as the mobile list (GET /kpi/target-management): an ownerless target is not the caller's.
    if not _has_global_scope(user) and hasattr(target, 'owner_user_id') and int(getattr(target, 'owner_user_id', 0) or 0) != int(getattr(user, 'id', 0) or 0):
        return jsonify({'message': 'Bu KPI hedef kartını güncelleme yetkiniz bulunmamaktadır.'}), 403
    payload = request.get_json(silent=True) or {}
    current_value = _v2853_float(payload.get('current_value'), 0.0)
    target_value = getattr(target, 'target_value', None)
    rate = _v2853_completion(current_value, target_value)
    risk, _tone = _v2853_risk(rate)
    try:
        if hasattr(target, 'current_value'):
            target.current_value = current_value
        if hasattr(target, 'completion_rate'):
            target.completion_rate = rate
        if hasattr(target, 'risk_level'):
            target.risk_level = risk
        if hasattr(target, 'status'):
            target.status = 'completed' if rate >= 100 else 'ongoing'
        db.session.commit()
        return jsonify({'source': 'real_api', 'ok': True, 'message': 'KPI gerçekleşme değeri güncellendi.', 'completion_rate': rate})
    except Exception:
        db.session.rollback()
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: KPI gerçekleşme değeri güncelleme hatası (app/api/mobile/domains/kpi_target_management.py:233)")
        return jsonify({'message': 'KPI gerçekleşme değeri güncellenemedi. Lütfen tekrar deneyin.'}), 500

