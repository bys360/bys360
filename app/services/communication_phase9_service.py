from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models.communication_phase5_models import CommunicationAutomationLog
from app.services.communication_gate_status_labels import gate_status_label
from app.services.communication_phase5_service import (
    audit_logs_snapshot,
    automation_center_snapshot,
    escalation_snapshot,
    health_snapshot,
    log_action,
    retention_snapshot,
    safe_str,
    support_operations_snapshot,
)
from app.services.go_live_readiness_service import build_go_live_readiness_context

logger = logging.getLogger(__name__)


class CommunicationPhase9Error(RuntimeError):
    pass


def _now() -> datetime:
    return utc_now()


def _recent_phase9_logs(limit: int = 40) -> list[CommunicationAutomationLog]:
    return (
        CommunicationAutomationLog.query
        .filter(CommunicationAutomationLog.action_type.in_([
            'phase9_checkpoint',
            'phase9_decision',
            'phase8_checkpoint',
            'phase8_note',
        ]))
        .order_by(CommunicationAutomationLog.executed_at.desc())
        .limit(limit)
        .all()
    )


def _try_phase8_snapshot(*, viewer: Any) -> dict[str, Any]:
    try:
        from app.services.communication_phase8_service import (
            cutover_snapshot,
            pilot_readiness_snapshot,
        )
        return {
            'readiness': pilot_readiness_snapshot(viewer=viewer),
            'cutover': cutover_snapshot(viewer=viewer),
        }
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase9_service.py | line=54")
        return {
            'readiness': {'decision': 'Faz 8 verisi bulunamadı', 'counts': {'pass': 0, 'warn': 0, 'fail': 1}},
            'cutover': {'tasks': [], 'checkpoint_logs': []},
        }


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
    values = {'pass': 0, 'warn': 0, 'fail': 0}
    for row in rows:
        status = safe_str(row.get('status')).lower()
        if status in values:
            values[status] += 1
    return values


def _tone_from_counts(counts: dict[str, int]) -> tuple[str, str]:
    if counts.get('fail', 0) > 0:
        return 'danger', 'Blokajlı görünüm'
    if counts.get('warn', 0) > 0:
        return 'warning', 'Kontrollü canlı açılış'
    return 'success', 'Canlı açılışa hazır'


def _smoke_rows() -> list[dict[str, Any]]:
    return [
        {
            'label': 'İletişim operasyon merkezi',
            'path': '/communication/faz5',
            'expected': 'Kartlar, kuyruk ve operasyon özeti 200 döndürmeli.',
            'owner': 'BT',
        },
        {
            'label': 'Pilot cutover merkezi',
            'path': '/communication/faz8/cutover',
            'expected': 'Kontrol noktası ve pilot notu formu açılmalı.',
            'owner': 'BT / Proje',
        },
        {
            'label': 'Canlıya geçiş merkezi',
            'path': '/communication/faz9/release-center',
            'expected': 'Kapılar, karar formu ve son kayıtlar görünmeli.',
            'owner': 'BT / Yönetim',
        },
        {
            'label': 'Portal bildirim akışı',
            'path': '/portal/notifications',
            'expected': 'Bildirim sayfası kırık yönlendirme üretmemeli.',
            'owner': 'BT',
        },
        {
            'label': 'Feedback dashboard',
            'path': '/feedback',
            'expected': 'Nabız ve kampanya özet kartları açılmalı.',
            'owner': 'İK / Süreç Sahibi',
        },
        {
            'label': 'Yönetici go-live readiness',
            'path': '/admin/go-live-readiness',
            'expected': 'Hazırlık skoru ve güvenlik bulguları görünmeli.',
            'owner': 'BT / Yönetim',
        },
    ]


def phase9_release_center_snapshot(*, viewer: Any) -> dict[str, Any]:
    """K5 F4: support figures count only the tickets inside ``viewer``'s scope."""
    go_live = build_go_live_readiness_context()
    health = health_snapshot(viewer=viewer)
    support_ops = support_operations_snapshot(150, viewer=viewer)
    automation = automation_center_snapshot(viewer=viewer)
    escalations = escalation_snapshot(viewer=viewer)
    retention = retention_snapshot(viewer=viewer)
    phase8 = _try_phase8_snapshot(viewer=viewer)
    recent_logs = [
        {
            'action_type': row.action_type,
            'status': row.status,
            'status_label': gate_status_label(row.status),
            'summary': row.summary,
            'executed_at': row.executed_at,
        }
        for row in _recent_phase9_logs(40)
    ]

    risk_score = int(health.get('summary', {}).get('risk_score', 0) or 0)
    blockers = len(go_live.get('blockers') or [])
    warnings = len(go_live.get('warnings') or [])
    recent_backups = len((go_live.get('backup_summary') or {}).get('recent_files') or [])
    recent_log_files = len((go_live.get('log_summary') or {}).get('recent_files') or [])
    open_support = int(support_ops.get('summary', {}).get('open_total', 0) or 0)
    stale_total = int(support_ops.get('summary', {}).get('stale_total', 0) or 0)
    unassigned_total = int(support_ops.get('summary', {}).get('unassigned_total', 0) or 0)
    failed_automation = int(automation.get('summary', {}).get('failed_log_count', 0) or 0)
    breach_count = int(escalations.get('summary', {}).get('breach_count', 0) or 0)
    retention_warnings = int(retention.get('summary', {}).get('warning_scope_count', 0) or 0)
    phase8_logs = len(phase8.get('cutover', {}).get('checkpoint_logs', []) or [])

    gates = [
        _gate(
            'phase9_9a',
            '9A | Kod ve konfigürasyon freeze',
            'pass' if blockers == 0 else 'warn',
            f'Canlıya hazırlık blokajı: {blockers} | Uyarı: {warnings}',
            'BT / Proje',
            'Blokaj kapanmadan yeni değişiklik açmayın.',
        ),
        _gate(
            'phase9_9b',
            '9B | Yedek, log ve rollback görünümü',
            'pass' if recent_backups >= 1 and recent_log_files >= 1 else 'fail',
            f'Son 14 gün yedek: {recent_backups} | Son 7 gün log: {recent_log_files}',
            'BT',
            'Yedek ve log kanıtı olmadan tam açılış yapmayın.',
        ),
        _gate(
            'phase9_9c',
            '9C | Pilot karar kaydı ve cutover izi',
            'pass' if phase8_logs >= 2 else 'warn',
            f'Faz 8 kontrol noktası/not kaydı: {phase8_logs}',
            'Proje / Yönetim',
            'Pilot kararı yazılı kayıt altına alınmalı.',
        ),
        _gate(
            'phase9_9d',
            '9D | İlk 72 saat destek kuyruğu',
            'pass' if open_support <= 20 and stale_total == 0 and unassigned_total == 0 else 'warn' if open_support <= 40 else 'fail',
            f'Açık destek: {open_support} | Duran: {stale_total} | Atanmamış: {unassigned_total}',
            'Destek Ekibi',
            'İlk gün kritik kuyruğu temizleyin.',
        ),
        _gate(
            'phase9_security',
            'Güvenlik ve operasyon riski',
            'pass' if risk_score <= 35 and failed_automation == 0 else 'warn' if risk_score <= 60 else 'fail',
            f'Risk skoru: {risk_score} | Başarısız otomasyon: {failed_automation} | SLA ihlali: {breach_count}',
            'BT / Operasyon',
            'CSRF, redirect ve export hatalarını ilk gün yakın izleyin.',
        ),
        _gate(
            'phase9_retention',
            'Saklama ve uyum görünümü',
            'pass' if retention_warnings == 0 else 'warn',
            f'Uyarı kapsamı: {retention_warnings}',
            'BT / KVKK',
            'Destek, mesaj ve anket saklama politikalarını son kez doğrulayın.',
        ),
    ]

    gate_counts = _counts(gates)
    tone, decision = _tone_from_counts(gate_counts)

    workstreams = [
        {
            'title': '9A | Yayın öncesi teknik kilit',
            'summary': 'Kod freeze, env doğrulama, servis başlangıç betikleri ve erişim sınırlarının sabitlenmesi.',
            'status': gates[0]['status'],
            'status_label': gates[0]['status_label'],
            'items': [
                'APP_ENV, cookie ve proxy ayarları üretim görünümünde olmalı.',
                'Kritik route yapısı değişmeden bırakılmalı.',
                'Yeni migration açılmayacaksa release etiketi netlenmeli.',
            ],
        },
        {
            'title': '9B | Veri ve güvenlik geçişi',
            'summary': 'Yedek, rollback, log, KVKK ve denetim izi doğrulaması.',
            'status': gates[1]['status'],
            'status_label': gates[1]['status_label'],
            'items': [
                'Son yedek dosyası fiziksel olarak doğrulansın.',
                'Rollback adımları yazılı ve uygulanabilir olsun.',
                'Sicil bazlı görünürlük ve export erişimleri tekrar test edilsin.',
            ],
        },
        {
            'title': '9C | Pilot canlı açılış',
            'summary': 'Kontrollü kullanıcı grubuyla ilk açılış, karar kaydı ve onay akışı.',
            'status': gates[2]['status'],
            'status_label': gates[2]['status_label'],
            'items': [
                'Pilot kullanıcı listesi sabitlensin.',
                'Destek kişisi ve geri bildirim kanalı tek adreste toplansın.',
                'Açılış kararı sistem içine işlenmiş olsun.',
            ],
        },
        {
            'title': '9D | İlk 72 saat stabilizasyon',
            'summary': 'CSRF, redirect, export ve destek kuyruğunun yakın izlenmesi.',
            'status': gates[3]['status'],
            'status_label': gates[3]['status_label'],
            'items': [
                'Operasyon sağlığı ekranı düzenli yenilensin.',
                'İhlal ve atanmamış talepler aynı gün kapatılsın.',
                'Hızlı hotfix kararı gerekiyorsa değişiklik penceresi dar tutulsun.',
            ],
        },
    ]

    highlights = [
        {'label': 'Hazırlık skoru', 'value': go_live.get('readiness_score', 0), 'suffix': '/100'},
        {'label': 'Kritik blokaj', 'value': blockers, 'suffix': ''},
        {'label': 'Operasyon riski', 'value': risk_score, 'suffix': '/100'},
        {'label': 'Canlı kayıt', 'value': len(recent_logs), 'suffix': ''},
    ]

    recommendations = [row for row in gates if row['status'] in {'fail', 'warn'}]

    return {
        'generated_at': _now(),
        'decision': decision,
        'tone': tone,
        'gate_counts': gate_counts,
        'gates': gates,
        'go_live': go_live,
        'phase8': phase8,
        'health': health,
        'support_ops': support_ops,
        'automation': automation,
        'escalations': escalations,
        'retention': retention,
        'recent_logs': recent_logs,
        'workstreams': workstreams,
        'summary_cards': highlights,
        'recommendations': recommendations,
    }


def phase9_first72_snapshot(*, viewer: Any) -> dict[str, Any]:
    release = phase9_release_center_snapshot(viewer=viewer)
    health = release['health']
    support_ops = release['support_ops']
    escalation = release['escalations']
    audit = audit_logs_snapshot(40)

    watch_items = [
        {
            'title': 'CSRF ve oturum akışı',
            'metric': f"Risk skoru {health.get('summary', {}).get('risk_score', 0)}/100",
            'detail': 'Tarayıcı, intranet ve farklı cihazlarda oturum akışını ilk gün gözlemleyin.',
        },
        {
            'title': 'Destek kuyruğu',
            'metric': f"Açık {support_ops.get('summary', {}).get('open_total', 0)} | Duran {support_ops.get('summary', {}).get('stale_total', 0)}",
            'detail': 'Atanmamış talepleri aynı gün sorumluya verin.',
        },
        {
            'title': 'SLA ve escalation',
            'metric': f"İhlal {escalation.get('summary', {}).get('breach_count', 0)}",
            'detail': 'İlk 72 saatte kritik öncelikli talepler ayrı raporlansın.',
        },
        {
            'title': 'Bildirim ve otomasyon',
            'metric': f"Başarısız log {release['automation'].get('summary', {}).get('failed_log_count', 0)}",
            'detail': 'Sessiz saat ve özet job’ları beklenen şekilde çalışmalı.',
        },
    ]

    handoff_rows = [
        {'title': 'Tek destek kanalı', 'body': 'Pilot kullanıcıların geri bildirimleri tek ticket akışında toplansın.'},
        {'title': 'Günlük kapanış notu', 'body': 'Her gün sonunda canlı karar notu ve özet blokaj listesi bırakın.'},
        {'title': 'Rollback eşiği', 'body': 'Kritik auth, veri kaybı veya export bozulması halinde daraltılmış moda dönün.'},
        {'title': 'Yönetim bilgilendirmesi', 'body': 'İlk 72 saat sonunda kısa bir durum özeti paylaşın.'},
    ]

    return {
        'generated_at': _now(),
        'release': release,
        'watch_items': watch_items,
        'smoke_rows': _smoke_rows(),
        'recent_audit': audit.get('logs', [])[:20],
        'handoff_rows': handoff_rows,
    }


def phase9_dashboard_snapshot(*, viewer: Any) -> dict[str, Any]:
    release = phase9_release_center_snapshot(viewer=viewer)
    first72 = phase9_first72_snapshot(viewer=viewer)
    return {
        'generated_at': _now(),
        'release': release,
        'first72': first72,
        'summary_cards': release['summary_cards'],
    }


def phase9_release_payload(*, viewer: Any) -> dict[str, Any]:
    release = phase9_release_center_snapshot(viewer=viewer)
    first72 = phase9_first72_snapshot(viewer=viewer)
    return {
        'generated_at': release['generated_at'],
        'decision': release['decision'],
        'tone': release['tone'],
        'gate_counts': release['gate_counts'],
        'gates': release['gates'],
        'summary_cards': release['summary_cards'],
        'workstreams': release['workstreams'],
        'smoke_rows': first72['smoke_rows'],
        'handoff_rows': first72['handoff_rows'],
        'recent_logs': release['recent_logs'],
    }


def build_phase9_release_markdown(*, viewer: Any) -> str:
    payload = phase9_release_payload(viewer=viewer)
    lines = [
        '# BYS360 İletişim ve Anket | Faz 9 Canlıya Geçiş Paketi',
        '',
        f"- Üretim zamanı: {payload['generated_at']}",
        f"- Karar: {payload['decision']}",
        f"- Geçen kapı: {payload['gate_counts'].get('pass', 0)}",
        f"- Uyarı: {payload['gate_counts'].get('warn', 0)}",
        f"- Blokaj: {payload['gate_counts'].get('fail', 0)}",
        '',
        '## Canlıya geçiş kapıları',
        '',
    ]
    for row in payload['gates']:
        lines.append(f"- [{row['status_label']}] {row['label']} — {row['detail']} ({row['owner']})")
        if row.get('action'):
            lines.append(f"  - Aksiyon: {row['action']}")

    lines.extend(['', '## İş akışları', ''])
    for item in payload['workstreams']:
        lines.append(f"### {item['title']} [{item['status_label']}]")
        lines.append(item['summary'])
        for sub in item['items']:
            lines.append(f"- {sub}")
        lines.append('')

    lines.extend(['## İlk 72 saat smoke listesi', ''])
    for row in payload['smoke_rows']:
        lines.append(f"- {row['label']} — `{row['path']}` — {row['expected']}")

    lines.extend(['', '## Handoff notları', ''])
    for row in payload['handoff_rows']:
        lines.append(f"- **{row['title']}**: {row['body']}")

    lines.extend(['', '## Son canlı kayıtları', ''])
    for row in payload['recent_logs']:
        lines.append(f"- {row['executed_at']} | {row['action_type']} | {row['status_label']} | {row['summary']}")

    return "\n".join(lines).strip() + "\n"


def record_phase9_checkpoint(actor: Any, checkpoint_key: str, status: str, note: str = '') -> CommunicationAutomationLog:
    checkpoint_key = safe_str(checkpoint_key)[:80] or 'genel'
    status = safe_str(status).lower()[:20] or 'pending'
    note = safe_str(note)[:600]
    summary = f'Faz 9 kontrol noktası | {checkpoint_key} | {status}'
    row = log_action(
        'phase9_checkpoint',
        actor,
        'communication_phase9',
        None,
        summary,
        {'checkpoint_key': checkpoint_key, 'status': status, 'note': note},
        status='success',
    )
    db.session.commit()
    return row


def record_phase9_decision(actor: Any, decision: str, status: str = 'controlled', note: str = '') -> CommunicationAutomationLog:
    decision = safe_str(decision)[:120] or 'Canlıya geçiş kararı'
    status = safe_str(status).lower()[:20] or 'controlled'
    note = safe_str(note)[:800]
    row = log_action(
        'phase9_decision',
        actor,
        'communication_phase9',
        None,
        decision,
        {'status': status, 'note': note},
        status='success',
    )
    db.session.commit()
    return row
