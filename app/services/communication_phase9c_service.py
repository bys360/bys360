from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import Notification, SupportTicket, SurveyAssignment
from app.models.communication_phase5_models import CommunicationAutomationLog
from app.services.communication_gate_status_labels import gate_status_label
from app.services.communication_phase5_service import (
    OPEN_TICKET_STATUSES,
    log_action,
    safe_str,
)
from app.services.communication_phase8_service import cutover_snapshot, pilot_readiness_snapshot
from app.services.communication_phase9_service import (
    phase9_first72_snapshot,
    phase9_release_center_snapshot,
)

logger = logging.getLogger(__name__)


class CommunicationPhase9CError(RuntimeError):
    pass


INCIDENT_SEVERITY_LABELS = {
    'low': 'Düşük',
    'medium': 'Orta',
    'high': 'Yüksek',
    'critical': 'Kritik',
}


def _now() -> datetime:
    return utc_now()


def _gate(key: str, label: str, status: str, detail: str, owner: str, action: str = '') -> dict[str, Any]:
    return {
        'key': key,
        'label': label,
        'status': status,
        'status_label': gate_status_label(status),
        'detail': detail,
        'owner': owner,
        'action': action,
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {'pass': 0, 'warn': 0, 'fail': 0}
    for row in rows:
        state = safe_str(row.get('status')).lower()
        if state in counts:
            counts[state] += 1
    return counts


def _tone_from_counts(counts: dict[str, int]) -> tuple[str, str]:
    if counts.get('fail', 0) > 0:
        return 'danger', 'Pilot açılış bloke'
    if counts.get('warn', 0) > 0:
        return 'warning', 'Kontrollü pilot açılış'
    return 'success', 'Pilot açılışa hazır'


def _recent_phase9c_logs(limit: int = 40) -> list[CommunicationAutomationLog]:
    return (
        CommunicationAutomationLog.query
        .filter(CommunicationAutomationLog.action_type.in_(['phase9c_gate', 'phase9c_decision', 'phase9c_incident']))
        .order_by(CommunicationAutomationLog.executed_at.desc())
        .limit(limit)
        .all()
    )


def _support_summary(*, viewer: Any) -> dict[str, int]:
    """K5 F4: counts only the tickets inside ``viewer``'s scope."""
    from app.services.support_ticket_access import support_ticket_visibility_clause

    open_total = 0
    stale_total = 0
    unassigned_total = 0
    try:
        if SupportTicket is not None:
            base = SupportTicket.query.filter(support_ticket_visibility_clause(viewer))
            if hasattr(SupportTicket, 'status'):
                base = base.filter(SupportTicket.status.in_(list(OPEN_TICKET_STATUSES)))
            open_total = base.count()
            if hasattr(SupportTicket, 'assigned_to_id'):
                unassigned_total = base.filter(SupportTicket.assigned_to_id.is_(None)).count()
            if hasattr(SupportTicket, 'updated_at'):
                threshold = _now().replace(microsecond=0)
                # Savunmacı davran: updated_at tip farklarında patlamasın.
                try:
                    from datetime import timedelta
                    stale_total = base.filter(SupportTicket.updated_at <= threshold - timedelta(days=2)).count()
                except Exception:
                    logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase9c_service.py | line=93")
                    stale_total = 0
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/communication_phase9c_service.py")
    return {
        'open_total': open_total,
        'stale_total': stale_total,
        'unassigned_total': unassigned_total,
    }


def _pending_feedback_summary() -> dict[str, int]:
    assigned = 0
    notifications_unread = 0
    try:
        if SurveyAssignment is not None:
            assigned = SurveyAssignment.query.filter(SurveyAssignment.status.in_(['assigned', 'atandi', 'started', 'basladi'])).count()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/communication_phase9c_service.py")
    try:
        if Notification is not None and hasattr(Notification, 'is_read'):
            notifications_unread = Notification.query.filter_by(is_read=False).count()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/communication_phase9c_service.py")
    return {
        'pending_assignments': assigned,
        'unread_notifications': notifications_unread,
    }


def _pilot_wave_rows(release: dict[str, Any], support: dict[str, int], feedback: dict[str, int]) -> list[dict[str, Any]]:
    blockers = int((release.get('gate_counts') or {}).get('fail', 0) or 0)
    rows: list[dict[str, Any]] = [
        {
            'title': 'Dalga 1 | Çekirdek pilot grup',
            'status': 'ready' if blockers == 0 else 'hold',
            'scope': 'Performans, bildirim, yardım merkezi ve yönetici görünürlüğü',
            'owner': 'BT / İK / Süreç Sahipleri',
            'criteria': [
                'Kritik blokaj kalmamalı.',
                'Destek kanal sahibi belli olmalı.',
                'Rollback notu teyit edilmeli.',
            ],
        },
        {
            'title': 'Dalga 2 | Yönetici ve koordinatör genişlemesi',
            'status': 'ready' if support.get('open_total', 0) <= 20 else 'warn',
            'scope': 'Koordinatörler, grup başkanları ve operasyon sahipleri',
            'owner': 'Yönetim / Proje',
            'criteria': [
                f"Açık destek {support.get('open_total', 0)} alt seviyede kalmalı.",
                'İlk ekran geri bildirimleri toplanmış olmalı.',
                'Öncelikli hotfix penceresi tanımlı olmalı.',
            ],
        },
        {
            'title': 'Dalga 3 | Kontrollü kurum içi yaygınlaşma',
            'status': 'ready' if feedback.get('pending_assignments', 0) <= 25 else 'warn',
            'scope': 'Pilot sonrası modül bazlı genişletme',
            'owner': 'Yönetim / BT',
            'criteria': [
                'Pilot kullanıcı kabulü pozitif olmalı.',
                'Bekleyen atama yükü yönetilebilir kalmalı.',
                'İlk 72 saat raporu paylaşılmış olmalı.',
            ],
        },
    ]
    for row in rows:
        row['status_label'] = gate_status_label(row['status'])
    return rows


def phase9c_pilot_opening_snapshot(*, viewer: Any) -> dict[str, Any]:
    readiness = pilot_readiness_snapshot(viewer=viewer)
    cutover = cutover_snapshot(viewer=viewer)
    release = phase9_release_center_snapshot(viewer=viewer)
    first72 = phase9_first72_snapshot(viewer=viewer)
    support = _support_summary(viewer=viewer)
    feedback = _pending_feedback_summary()
    raw_recent_logs = _recent_phase9c_logs(40)

    recent_checkpoint_logs = len(cutover.get('checkpoint_logs', []) or [])
    release_blockers = int((release.get('gate_counts') or {}).get('fail', 0) or 0)
    release_warns = int((release.get('gate_counts') or {}).get('warn', 0) or 0)

    gates = [
        _gate(
            'pilot_decision',
            'Pilot açılış kararı ve kapsamı',
            'pass' if recent_checkpoint_logs >= 2 else 'warn',
            f'Faz 8 kontrol noktası/not kaydı: {recent_checkpoint_logs}',
            'Proje / Yönetim',
            'Pilot listesi ve açılış kararı yazılı kayıt altında olmalı.',
        ),
        _gate(
            'release_readiness',
            'Canlıya geçiş kapıları',
            'pass' if release_blockers == 0 and release_warns <= 2 else 'warn' if release_blockers == 0 else 'fail',
            f'Kritik kapı: {release_blockers} | Uyarı: {release_warns}',
            'BT',
            'Faz 9 ana blokajları kapanmadan yaygınlaştırma yapmayın.',
        ),
        _gate(
            'support_channel',
            'Pilot destek kanalı ve atama',
            'pass' if support['open_total'] <= 15 and support['unassigned_total'] == 0 else 'warn' if support['open_total'] <= 30 else 'fail',
            f"Açık destek: {support['open_total']} | Atanmamış: {support['unassigned_total']}",
            'Destek Ekibi',
            'Pilot kullanıcıdan gelen talepler aynı gün sınıflandırılmalı.',
        ),
        _gate(
            'feedback_noise',
            'Anket / bildirim gürültüsü',
            'pass' if feedback['pending_assignments'] <= 15 and feedback['unread_notifications'] <= 200 else 'warn',
            f"Bekleyen atama: {feedback['pending_assignments']} | Okunmamış bildirim: {feedback['unread_notifications']}",
            'İK / Süreç Sahipleri',
            'Pilot ilk gününde gereksiz bildirim yoğunluğunu düşük tutun.',
        ),
        _gate(
            'rollback_line',
            'Rollback ve daraltılmış moda dönüş',
            'pass' if len((release.get('go_live') or {}).get('backup_summary', {}).get('recent_files') or []) >= 1 else 'fail',
            'Son yedek görünmeli ve daraltılmış moda dönüş notu hazır olmalı.',
            'BT / Yönetim',
            'Kritik auth, export veya veri kaybında kontrollü geri dönüş uygulanmalı.',
        ),
        _gate(
            'first72_watch',
            'İlk 72 saat izleme planı',
            'pass' if len(first72.get('watch_items', []) or []) >= 4 else 'warn',
            f"İzleme başlığı: {len(first72.get('watch_items', []) or [])}",
            'BT / Operasyon',
            'CSRF, redirect, export ve destek kuyruğu yakın izlenmeli.',
        ),
    ]

    counts = _counts(gates)
    tone, decision = _tone_from_counts(counts)

    summary_cards = [
        {'label': 'Pilot kararı', 'value': 'Hazır' if counts['fail'] == 0 else 'Bloke', 'suffix': ''},
        {'label': 'Açık destek', 'value': support['open_total'], 'suffix': ''},
        {'label': 'Bekleyen atama', 'value': feedback['pending_assignments'], 'suffix': ''},
        {'label': 'Pilot kayıt', 'value': len(raw_recent_logs), 'suffix': ''},
    ]

    wave_rows = _pilot_wave_rows(release, support, feedback)
    incident_rows = []
    for row in raw_recent_logs:
        if row.action_type != 'phase9c_incident':
            continue
        raw_severity = safe_str((row.payload_json or {}).get('severity', row.status)).lower() or row.status
        incident_rows.append({
            'title': row.summary or row.action_type,
            'severity': raw_severity,
            'severity_label': INCIDENT_SEVERITY_LABELS.get(raw_severity, 'Bilinmiyor'),
            'note': safe_str((row.payload_json or {}).get('note', '')),
            'executed_at': row.executed_at,
        })
    incident_rows = incident_rows[:15]

    recent_logs = [
        {
            'action_type': row.action_type,
            'status': row.status,
            'status_label': gate_status_label(row.status),
            'summary': row.summary,
            'executed_at': row.executed_at,
        }
        for row in raw_recent_logs
    ]

    focus_rows = [
        {
            'title': 'Pilot kullanıcı grubu',
            'body': 'Önce çekirdek kullanıcılar: performans, bildirim ve destek süreç sahipleri.',
        },
        {
            'title': 'Tek geri bildirim kanalı',
            'body': 'Telefon, sözlü not ve ayrı mesaj yerine tek ticket akışı kullanılmalı.',
        },
        {
            'title': 'Açılış penceresi',
            'body': 'Pilot açılış saatini dar tutun; ilk 2 saat destek ekibi çevrim içi olsun.',
        },
        {
            'title': 'Genişleme kararı',
            'body': 'İlk gün stabilite sağlanmadan tüm kuruma açılış yapılmamalı.',
        },
    ]

    return {
        'generated_at': _now(),
        'decision': decision,
        'tone': tone,
        'counts': counts,
        'gates': gates,
        'summary_cards': summary_cards,
        'wave_rows': wave_rows,
        'focus_rows': focus_rows,
        'incident_rows': incident_rows,
        'recent_logs': recent_logs,
        'readiness': readiness,
        'cutover': cutover,
        'release': release,
        'first72': first72,
        'support': support,
        'feedback': feedback,
    }


def phase9c_payload(*, viewer: Any) -> dict[str, Any]:
    return phase9c_pilot_opening_snapshot(viewer=viewer)


def build_phase9c_markdown(*, viewer: Any) -> str:
    payload = phase9c_pilot_opening_snapshot(viewer=viewer)
    lines = [
        '# Faz 9C | Pilot Canlı Açılış',
        '',
        f"- Üretim zamanı: {payload['generated_at']}",
        f"- Karar: {payload['decision']}",
        '',
        '## Kapılar',
        '',
    ]
    for row in payload['gates']:
        lines.append(f"- [{row['status_label']}] {row['label']} — {row['detail']}")
    lines.extend([
        '',
        '## Açılış dalgaları',
        '',
    ])
    for row in payload['wave_rows']:
        lines.append(f"- [{row['status_label']}] {row['title']} — {row['scope']}")
    lines.extend([
        '',
        '## Son olay kayıtları',
        '',
    ])
    for row in payload['incident_rows'][:10]:
        lines.append(f"- {row['executed_at']} | {row['severity_label']} | {row['title']}")
    if not payload['incident_rows']:
        lines.append('- Henüz olay kaydı yok.')
    return '\n'.join(lines) + '\n'


def record_phase9c_gate(actor: Any, gate_key: str, status: str, note: str = '') -> CommunicationAutomationLog:
    gate_key = safe_str(gate_key)[:80] or 'genel'
    status = safe_str(status).lower()[:20] or 'pending'
    note = safe_str(note)[:600]
    summary = f'Faz 9C kapı | {gate_key} | {status}'
    row = log_action('phase9c_gate', actor, 'communication_phase9c', None, summary, {'gate_key': gate_key, 'status': status, 'note': note}, status='success')
    db.session.commit()
    return row


def record_phase9c_decision(actor: Any, decision: str, status: str = 'controlled', note: str = '') -> CommunicationAutomationLog:
    decision = safe_str(decision)[:120] or 'Pilot açılış kararı'
    status = safe_str(status).lower()[:20] or 'controlled'
    note = safe_str(note)[:800]
    summary = f'Faz 9C karar | {decision} | {status}'
    row = log_action('phase9c_decision', actor, 'communication_phase9c', None, summary, {'decision': decision, 'status': status, 'note': note}, status='success')
    db.session.commit()
    return row


def record_phase9c_incident(actor: Any, title: str, severity: str = 'medium', note: str = '') -> CommunicationAutomationLog:
    title = safe_str(title)[:120] or 'Pilot olay kaydı'
    severity = safe_str(severity).lower()[:20] or 'medium'
    if severity not in INCIDENT_SEVERITY_LABELS:
        severity = 'medium'
    note = safe_str(note)[:800]
    summary = f"Faz 9C olay | {INCIDENT_SEVERITY_LABELS.get(severity, severity)} | {title}"
    row = log_action('phase9c_incident', actor, 'communication_phase9c', None, summary, {'title': title, 'severity': severity, 'note': note}, status=severity)
    db.session.commit()
    return row
