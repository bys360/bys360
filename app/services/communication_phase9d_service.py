from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import Notification, SupportTicket, SurveyAssignment
from app.models.communication_phase5_models import CommunicationAutomationLog
from app.services.communication_gate_status_labels import gate_status_label
from app.services.communication_phase5_service import OPEN_TICKET_STATUSES, log_action, safe_str
from app.services.communication_phase9_service import (
    phase9_first72_snapshot,
    phase9_release_center_snapshot,
)

logger = logging.getLogger(__name__)


class CommunicationPhase9DError(RuntimeError):
    pass


SIGNAL_STATUS_LABELS = {
    'stable': 'Stabil',
    'watch': 'İzle',
    'risk': 'Risk',
    'critical': 'Kritik',
}

HOTFIX_SEVERITY_LABELS = {
    'low': 'Düşük',
    'medium': 'Orta',
    'high': 'Yüksek',
    'critical': 'Kritik',
}


def _now() -> datetime:
    return utc_now()


def _recent_phase9d_logs(limit: int = 60) -> list[CommunicationAutomationLog]:
    return (
        CommunicationAutomationLog.query
        .filter(CommunicationAutomationLog.action_type.in_(['phase9d_checkin', 'phase9d_hotfix', 'phase9d_signal']))
        .order_by(CommunicationAutomationLog.executed_at.desc())
        .limit(limit)
        .all()
    )


def _checkin_window_rows() -> list[dict[str, Any]]:
    return [
        {'key': '0_24', 'title': '0–24 Saat', 'focus': 'Kimlik doğrulama, CSRF, kritik yönlendirme ve ilk destek kuyruğu', 'owner': 'BT / Destek'},
        {'key': '24_48', 'title': '24–48 Saat', 'focus': 'Export, bildirim, kampanya geri bildirimleri ve hotfix penceresi', 'owner': 'BT / Süreç Sahipleri'},
        {'key': '48_72', 'title': '48–72 Saat', 'focus': 'Kapanış değerlendirmesi, kalıcı blokaj listesi ve sonraki sürüm kararı', 'owner': 'Yönetim / Proje'},
    ]


def _support_metrics(*, viewer: Any) -> dict[str, int]:
    """K5 F4: counts only the tickets inside ``viewer``'s scope."""
    from app.services.support_ticket_access import support_ticket_visibility_clause

    metrics = {'open_total': 0, 'unassigned_total': 0, 'stale_total': 0}
    try:
        if SupportTicket is None:
            return metrics
        base = SupportTicket.query.filter(support_ticket_visibility_clause(viewer))
        if hasattr(SupportTicket, 'status'):
            base = base.filter(SupportTicket.status.in_(list(OPEN_TICKET_STATUSES)))
        metrics['open_total'] = base.count()
        if hasattr(SupportTicket, 'assigned_to_id'):
            metrics['unassigned_total'] = base.filter(SupportTicket.assigned_to_id.is_(None)).count()
        if hasattr(SupportTicket, 'updated_at'):
            try:
                metrics['stale_total'] = base.filter(SupportTicket.updated_at <= _now() - timedelta(hours=12)).count()
            except Exception:
                logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase9d_service.py | line=71")
                metrics['stale_total'] = 0
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase9d_service.py | line=73")
        return metrics
    return metrics


def _feedback_metrics() -> dict[str, int]:
    rows = {'pending_assignments': 0, 'unread_notifications': 0}
    try:
        if SurveyAssignment is not None and hasattr(SurveyAssignment, 'status'):
            rows['pending_assignments'] = SurveyAssignment.query.filter(
                SurveyAssignment.status.in_(['assigned', 'atandi', 'started', 'basladi'])
            ).count()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/communication_phase9d_service.py")
    try:
        if Notification is not None and hasattr(Notification, 'is_read'):
            rows['unread_notifications'] = Notification.query.filter_by(is_read=False).count()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/communication_phase9d_service.py")
    return rows


def _hotfix_summary(logs: list[CommunicationAutomationLog]) -> dict[str, int]:
    rows = {'total': 0, 'critical': 0, 'high': 0}
    for row in logs:
        if row.action_type != 'phase9d_hotfix':
            continue
        rows['total'] += 1
        severity = safe_str((row.payload_json or {}).get('severity')).lower()
        if severity == 'critical':
            rows['critical'] += 1
        elif severity == 'high':
            rows['high'] += 1
    return rows


def _signal_summary(logs: list[CommunicationAutomationLog]) -> dict[str, int]:
    rows = {'stable': 0, 'watch': 0, 'risk': 0, 'critical': 0}
    for row in logs:
        if row.action_type != 'phase9d_signal':
            continue
        status = safe_str((row.payload_json or {}).get('status')).lower()
        if status in rows:
            rows[status] += 1
    return rows


def _window_status(window_key: str, logs: list[CommunicationAutomationLog]) -> str:
    related = [row for row in logs if row.action_type == 'phase9d_checkin' and safe_str((row.payload_json or {}).get('window_key')) == window_key]
    if not related:
        return 'pending'
    statuses = {safe_str((row.payload_json or {}).get('status')).lower() for row in related}
    if 'critical' in statuses or 'fail' in statuses:
        return 'fail'
    if 'risk' in statuses or 'watch' in statuses or 'warn' in statuses:
        return 'warn'
    return 'pass'


def _gates(release: dict[str, Any], support: dict[str, int], feedback: dict[str, int], hotfix: dict[str, int], signal: dict[str, int]) -> list[dict[str, Any]]:
    blockers = int((release.get('gate_counts') or {}).get('fail', 0) or 0)
    warnings = int((release.get('gate_counts') or {}).get('warn', 0) or 0)
    rows = [
        {'label': 'İlk 72 saat yayın kapısı', 'status': 'pass' if blockers == 0 else 'warn' if warnings >= 0 else 'fail', 'owner': 'BT / Proje', 'detail': f'Canlı kapı blokajı: {blockers} | Uyarı: {warnings}', 'action': 'Blokajlı kapılar kapanmadan tam açılış genişletilmesin.'},
        {'label': 'Destek kuyruğu ve atama disiplini', 'status': 'pass' if support['open_total'] <= 15 and support['unassigned_total'] == 0 and support['stale_total'] == 0 else 'warn' if support['open_total'] <= 35 else 'fail', 'owner': 'Destek', 'detail': f"Açık: {support['open_total']} | Atanmamış: {support['unassigned_total']} | Duran: {support['stale_total']}", 'action': 'İlk gün atanmamış ve duran kayıt bırakılmamalı.'},
        {'label': 'Bildirim ve anket geri beslemesi', 'status': 'pass' if feedback['pending_assignments'] <= 20 and feedback['unread_notifications'] <= 100 else 'warn', 'owner': 'İK / Süreç Sahibi', 'detail': f"Bekleyen anket ataması: {feedback['pending_assignments']} | Okunmamış bildirim: {feedback['unread_notifications']}", 'action': 'İlk 72 saatte kullanıcı yanıtını geciktiren düğümler temizlensin.'},
        {'label': 'Hotfix baskısı', 'status': 'pass' if hotfix['critical'] == 0 and hotfix['high'] <= 1 else 'warn' if hotfix['critical'] == 0 else 'fail', 'owner': 'BT', 'detail': f"Toplam hotfix: {hotfix['total']} | High: {hotfix['high']} | Critical: {hotfix['critical']}", 'action': 'Kritik hotfix varsa değişiklik penceresi daraltılmalı.'},
        {'label': 'Saha izleme sinyalleri', 'status': 'pass' if signal['critical'] == 0 and signal['risk'] <= 1 else 'warn' if signal['critical'] == 0 else 'fail', 'owner': 'Proje / Yönetim', 'detail': f"Stabil: {signal['stable']} | İzle: {signal['watch']} | Risk: {signal['risk']} | Kritik: {signal['critical']}", 'action': 'Kritik sinyal kayıtlarında aynı vardiyada müdahale kararı alınmalı.'},
    ]
    for row in rows:
        row['status_label'] = gate_status_label(row['status'])
    return rows


def _counts(gates: list[dict[str, Any]]) -> dict[str, int]:
    rows = {'pass': 0, 'warn': 0, 'fail': 0}
    for row in gates:
        status = safe_str(row.get('status')).lower()
        if status in rows:
            rows[status] += 1
    return rows


def _tone_from_counts(counts: dict[str, int]) -> tuple[str, str]:
    if counts.get('fail', 0) > 0:
        return 'danger', 'İlk 72 saat kritik izleme'
    if counts.get('warn', 0) > 0:
        return 'warning', 'Yakın stabilizasyon takibi'
    return 'success', 'Stabil açılış görünümü'


def _summary_cards(release: dict[str, Any], support: dict[str, int], hotfix: dict[str, int], signals: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {'label': 'Canlı kapı fail', 'value': int((release.get('gate_counts') or {}).get('fail', 0) or 0), 'suffix': ''},
        {'label': 'Açık destek', 'value': support['open_total'], 'suffix': ''},
        {'label': 'Hotfix', 'value': hotfix['total'], 'suffix': ''},
        {'label': 'Risk + kritik sinyal', 'value': signals['risk'] + signals['critical'], 'suffix': ''},
    ]


def _window_rows(logs: list[CommunicationAutomationLog]) -> list[dict[str, Any]]:
    rows = []
    for item in _checkin_window_rows():
        status = _window_status(item['key'], logs)
        rows.append({**item, 'status': status, 'status_label': gate_status_label(status)})
    return rows


def _watch_items(release: dict[str, Any], support: dict[str, int], feedback: dict[str, int], hotfix: dict[str, int], signals: dict[str, int]) -> list[dict[str, Any]]:
    health = release.get('health', {})
    automation = release.get('automation', {})
    return [
        {'title': 'CSRF ve oturum akışı', 'metric': f"Risk skoru {health.get('summary', {}).get('risk_score', 0)}/100", 'detail': 'Telefon, intranet ve farklı tarayıcılarda oturum akışı yakın izlenmeli.'},
        {'title': 'Destek kuyruğu', 'metric': f"Açık {support['open_total']} | Atanmamış {support['unassigned_total']}", 'detail': 'Atanmamış veya duran talepler aynı vardiyada sahiplenilmeli.'},
        {'title': 'Bildirim ve geri dönüş', 'metric': f"Okunmamış {feedback['unread_notifications']} | Bekleyen atama {feedback['pending_assignments']}", 'detail': 'Kullanıcıya ulaşmayan bildirim zinciri pilot algısını bozar.'},
        {'title': 'Otomasyon ve hotfix', 'metric': f"Başarısız log {automation.get('summary', {}).get('failed_log_count', 0)} | Hotfix {hotfix['total']}", 'detail': 'Sık hotfix baskısı varsa yeni açılış dalgası geciktirilmeli.'},
        {'title': 'Saha sinyali', 'metric': f"İzle {signals['watch']} | Risk {signals['risk']} | Kritik {signals['critical']}", 'detail': 'Kritik sinyal kayıtlarında yönetici bilgilendirmesi gecikmemeli.'},
    ]


def _handoff_rows() -> list[dict[str, str]]:
    return [
        {'title': 'Tek iletişim kanalı', 'body': 'Pilot kullanıcılar destek taleplerini tek kanaldan iletmeli; alternatif notlar sonradan sisteme düşülmeli.'},
        {'title': 'Günlük sabah-akşam check-in', 'body': '0–24, 24–48 ve 48–72 saat pencereleri için kısa operasyon notu bırakılmalı.'},
        {'title': 'Dar hotfix penceresi', 'body': 'Hotfix yalnızca kritik kullanıcı etkisi varsa açılmalı; düşük öncelikli düzenlemeler bekletilmeli.'},
        {'title': 'Yönetim özeti', 'body': 'İlk 72 saatin sonunda karar özeti, açık risk listesi ve sonraki dalga önerisi paylaşılmalı.'},
    ]


def _hotfix_rows(logs: list[CommunicationAutomationLog]) -> list[dict[str, Any]]:
    rows = []
    for row in logs:
        if row.action_type != 'phase9d_hotfix':
            continue
        severity = safe_str((row.payload_json or {}).get('severity')).lower()
        rows.append({'title': row.summary or 'Hotfix kaydı', 'severity': HOTFIX_SEVERITY_LABELS.get(severity, 'Bilinmiyor') if severity else '-', 'note': safe_str((row.payload_json or {}).get('note')), 'executed_at': row.executed_at, 'status': row.status})
    return rows[:12]


def _signal_rows(logs: list[CommunicationAutomationLog]) -> list[dict[str, Any]]:
    rows = []
    for row in logs:
        if row.action_type != 'phase9d_signal':
            continue
        state = safe_str((row.payload_json or {}).get('status')).lower()
        rows.append({'title': row.summary or 'İzleme sinyali', 'status': SIGNAL_STATUS_LABELS.get(state, 'Bilinmiyor') if state else '-', 'note': safe_str((row.payload_json or {}).get('note')), 'executed_at': row.executed_at})
    return rows[:12]


def phase9d_stabilization_snapshot(*, viewer: Any) -> dict[str, Any]:
    release = phase9_release_center_snapshot(viewer=viewer)
    first72 = phase9_first72_snapshot(viewer=viewer)
    logs = _recent_phase9d_logs(60)
    support = _support_metrics(viewer=viewer)
    feedback = _feedback_metrics()
    hotfix = _hotfix_summary(logs)
    signals = _signal_summary(logs)
    gates = _gates(release, support, feedback, hotfix, signals)
    gate_counts = _counts(gates)
    tone, decision = _tone_from_counts(gate_counts)
    return {
        'generated_at': _now(),
        'release': release,
        'first72': first72,
        'support': support,
        'feedback': feedback,
        'hotfix': hotfix,
        'signals': signals,
        'gates': gates,
        'gate_counts': gate_counts,
        'tone': tone,
        'decision': decision,
        'summary_cards': _summary_cards(release, support, hotfix, signals),
        'window_rows': _window_rows(logs),
        'watch_items': _watch_items(release, support, feedback, hotfix, signals),
        'handoff_rows': _handoff_rows(),
        'hotfix_rows': _hotfix_rows(logs),
        'signal_rows': _signal_rows(logs),
        'recent_logs': [
            {
                'action_type': row.action_type,
                'status': row.status,
                'status_label': gate_status_label(row.status),
                'summary': row.summary,
                'executed_at': row.executed_at,
                'payload_json': row.payload_json,
            }
            for row in logs
        ],
        'smoke_rows': first72.get('smoke_rows', []),
    }


def phase9d_payload(*, viewer: Any) -> dict[str, Any]:
    payload = phase9d_stabilization_snapshot(viewer=viewer)
    return {
        'generated_at': payload['generated_at'],
        'decision': payload['decision'],
        'tone': payload['tone'],
        'gate_counts': payload['gate_counts'],
        'gates': payload['gates'],
        'summary_cards': payload['summary_cards'],
        'window_rows': payload['window_rows'],
        'watch_items': payload['watch_items'],
        'handoff_rows': payload['handoff_rows'],
        'hotfix_rows': payload['hotfix_rows'],
        'signal_rows': payload['signal_rows'],
        'smoke_rows': payload['smoke_rows'],
        'recent_logs': payload['recent_logs'],
    }


def build_phase9d_markdown(*, viewer: Any) -> str:
    payload = phase9d_payload(viewer=viewer)
    lines = [
        '# Faz 9D | İlk 72 Saat Stabilizasyonu',
        '',
        f"- Üretim zamanı: {payload['generated_at']}",
        f"- Genel karar: {payload['decision']}",
        f"- Kapı dağılımı: pass={payload['gate_counts'].get('pass', 0)} | warn={payload['gate_counts'].get('warn', 0)} | fail={payload['gate_counts'].get('fail', 0)}",
        '',
        '## Stabilizasyon kapıları',
    ]
    for row in payload['gates']:
        lines.extend([
            f"- **{row['label']}** [{row['status_label']}]",
            f"  - Sahip: {row['owner']}",
            f"  - Detay: {row['detail']}",
            f"  - Aksiyon: {row['action']}",
        ])
    lines.extend(['', '## 72 saat pencereleri'])
    for row in payload['window_rows']:
        lines.append(f"- **{row['title']}** [{row['status_label']}] — {row['focus']}")
    lines.extend(['', '## Sıcak izleme başlıkları'])
    for row in payload['watch_items']:
        lines.append(f"- **{row['title']}** — {row['metric']} | {row['detail']}")
    lines.extend(['', '## Handoff notları'])
    for row in payload['handoff_rows']:
        lines.append(f"- **{row['title']}** — {row['body']}")
    return '\n'.join(lines)


def _record(action_type: str, actor: Any, summary: str, payload: dict[str, Any], status: str = 'success') -> CommunicationAutomationLog:
    row = log_action(action_type, actor, 'communication_phase9d', None, summary, payload, status=status)
    db.session.commit()
    return row


def record_phase9d_checkin(actor: Any, window_key: str, status: str, note: str) -> CommunicationAutomationLog:
    window_key = safe_str(window_key) or '0_24'
    status = safe_str(status).lower() or 'watch'
    note = safe_str(note)
    return _record('phase9d_checkin', actor, f'9D check-in | {window_key}', {'window_key': window_key, 'status': status, 'note': note}, status='success' if status in {'pass', 'stable'} else 'warning' if status in {'watch', 'warn'} else 'danger')


def record_phase9d_hotfix(actor: Any, title: str, severity: str, note: str) -> CommunicationAutomationLog:
    title = safe_str(title) or 'İsimsiz hotfix'
    severity = safe_str(severity).lower() or 'medium'
    note = safe_str(note)
    return _record('phase9d_hotfix', actor, title, {'severity': severity, 'note': note}, status='danger' if severity == 'critical' else 'warning' if severity in {'high', 'medium'} else 'success')


def record_phase9d_signal(actor: Any, signal_type: str, status: str, note: str) -> CommunicationAutomationLog:
    signal_type = safe_str(signal_type) or 'Genel saha sinyali'
    status = safe_str(status).lower() or 'watch'
    note = safe_str(note)
    return _record('phase9d_signal', actor, signal_type, {'status': status, 'note': note}, status='danger' if status == 'critical' else 'warning' if status in {'watch', 'risk'} else 'success')
