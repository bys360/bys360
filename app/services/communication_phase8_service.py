from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import current_app

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import Survey, SurveyAssignment, SurveyResponse
from app.models.communication_phase5_models import CommunicationAutomationLog
from app.services.communication_gate_status_labels import gate_status_label
from app.services.communication_phase5_service import (
    automation_center_snapshot,
    escalation_snapshot,
    health_snapshot,
    log_action,
    retention_snapshot,
    safe_str,
)
from app.services.go_live_readiness_service import build_go_live_readiness_context

logger = logging.getLogger(__name__)


class CommunicationPhase8Error(RuntimeError):
    pass


def _now() -> datetime:
    return utc_now()


def _project_root() -> Path:
    try:
        return Path(current_app.root_path).parent
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/communication_phase8_service.py | line=39")
        return Path('.')


def _pilot_gate(label: str, status: str, detail: str, owner: str, action: str | None = None) -> dict[str, Any]:
    return {
        'label': label,
        'status': status,
        'status_label': gate_status_label(status),
        'detail': detail,
        'owner': owner,
        'action': action or '',
    }


def _count_phase8_logs(hours: int = 72) -> int:
    threshold = _now() - timedelta(hours=max(int(hours or 0), 1))
    return (
        CommunicationAutomationLog.query
        .filter(CommunicationAutomationLog.action_type.in_(['phase8_checkpoint', 'phase8_note']))
        .filter(CommunicationAutomationLog.executed_at >= threshold)
        .count()
    )


def pilot_readiness_snapshot(*, viewer: Any) -> dict[str, Any]:
    """K5 F4: support figures count only the tickets inside ``viewer``'s scope."""
    go_live = build_go_live_readiness_context()
    health = health_snapshot(viewer=viewer)
    automation = automation_center_snapshot()
    escalations = escalation_snapshot(viewer=viewer)
    retention = retention_snapshot(viewer=viewer)

    open_tickets = health['summary'].get('tickets_open', 0)
    failed_logs = health['summary'].get('failed_logs', 0)
    unread_total = health['summary'].get('unread_total', 0)
    active_rules = automation['summary'].get('active_rule_count', 0)
    retention_policies = len(retention.get('policies', []) or [])
    breach_count = escalations['summary'].get('breach_count', 0)
    recent_health = len(health.get('recent_checks', []) or [])
    recent_logs = _count_phase8_logs(72)
    pending_surveys = (
        SurveyAssignment.query
        .outerjoin(SurveyResponse, SurveyResponse.assignment_id == SurveyAssignment.id)
        .filter(db.or_(SurveyResponse.id.is_(None), SurveyResponse.is_completed.is_(False)))
        .count()
    )
    active_surveys = Survey.query.filter(Survey.status.in_(['published', 'active', 'yayinda'])).count()

    gates = [
        _pilot_gate(
            'Genel canlıya hazırlık skoru',
            'pass' if go_live['readiness_score'] >= 85 else 'warn' if go_live['readiness_score'] >= 70 else 'fail',
            f"Skor: {go_live['readiness_score']}/100",
            'BT / Proje',
            'Go-live readiness ekranındaki fail kayıtlarını kapatın.',
        ),
        _pilot_gate(
            'Açık kritik blokaj',
            'pass' if not go_live['blockers'] else 'fail',
            f"Kritik blokaj sayısı: {len(go_live['blockers'])}",
            'BT / Yönetim',
            'Blokaj kapanmadan pilot açılış yapmayın.',
        ),
        _pilot_gate(
            'Aktif escalation kuralı',
            'pass' if active_rules >= 1 else 'fail',
            f"Aktif kural: {active_rules}",
            'BT / Operasyon',
            'En az bir aktif escalation kuralı olmalı.',
        ),
        _pilot_gate(
            'Saklama politikaları',
            'pass' if retention_policies >= 3 else 'warn',
            f"Tanımlı politika: {retention_policies}",
            'BT / KVKK',
            'Bildirim, destek ve anket için politika tanımlayın.',
        ),
        _pilot_gate(
            'Son sağlık kontrolü',
            'pass' if recent_health >= 1 else 'warn',
            f"Son görünür sağlık kaydı: {recent_health}",
            'BT',
            'Pilot öncesi health refresh çalıştırın.',
        ),
        _pilot_gate(
            'Başarısız otomasyon kaydı',
            'pass' if failed_logs == 0 else 'warn',
            f"Başarısız otomasyon: {failed_logs}",
            'BT / Operasyon',
            'Başarısız otomasyonları inceleyip kapatın.',
        ),
        _pilot_gate(
            'SLA ihlal yükü',
            'pass' if breach_count == 0 else 'warn' if breach_count <= 5 else 'fail',
            f"Aktif SLA ihlali: {breach_count}",
            'Destek Ekibi',
            'Pilot öncesi kritik destek taleplerini temizleyin.',
        ),
        _pilot_gate(
            'Açık destek talebi hacmi',
            'pass' if open_tickets <= 25 else 'warn' if open_tickets <= 50 else 'fail',
            f"Açık destek talebi: {open_tickets}",
            'Destek Ekibi',
            'Kuyruğu azaltmadan pilot kullanıcı sayısını artırmayın.',
        ),
        _pilot_gate(
            'Bekleyen anket yükü',
            'pass' if pending_surveys <= 20 else 'warn',
            f"Bekleyen atama: {pending_surveys} | Aktif anket: {active_surveys}",
            'İK / Süreç Sahibi',
            'Pilot kullanıcı grubunda bekleyen anket yükünü sadeleştirin.',
        ),
        _pilot_gate(
            'Okunmamış bildirim hacmi',
            'pass' if unread_total <= 250 else 'warn',
            f"Okunmamış bildirim: {unread_total}",
            'Tüm Süreç Sahipleri',
            'Gürültüyü azaltın, sessiz saat ve özet kullanımını teşvik edin.',
        ),
        _pilot_gate(
            'Pilot kontrol noktası kaydı',
            'pass' if recent_logs >= 1 else 'warn',
            f"Son 72 saatte faz 8 kaydı: {recent_logs}",
            'Proje Ofisi',
            'Açılış öncesi en az bir kontrol noktası ve bir karar notu bırakın.',
        ),
    ]

    counts = {'pass': 0, 'warn': 0, 'fail': 0}
    for gate in gates:
        state = safe_str(gate.get('status')).lower()
        if state in counts:
            counts[state] += 1

    if counts['fail']:
        decision = 'Pilot açılış bloke'
        tone = 'danger'
    elif counts['warn']:
        decision = 'Kontrollü pilot açılış'
        tone = 'warning'
    else:
        decision = 'Pilot açılışa hazır'
        tone = 'success'

    recommendations = [gate for gate in gates if gate['status'] in {'fail', 'warn'}][:8]

    return {
        'generated_at': _now(),
        'decision': decision,
        'tone': tone,
        'counts': counts,
        'gates': gates,
        'recommendations': recommendations,
        'go_live': go_live,
        'health': health,
        'automation': automation,
        'escalation': escalations,
        'retention': retention,
    }


def cutover_snapshot(*, viewer: Any) -> dict[str, Any]:
    readiness = pilot_readiness_snapshot(viewer=viewer)
    project_root = _project_root()
    checkpoint_logs = (
        CommunicationAutomationLog.query
        .filter(CommunicationAutomationLog.action_type.in_(['phase8_checkpoint', 'phase8_note']))
        .order_by(CommunicationAutomationLog.executed_at.desc())
        .limit(30)
        .all()
    )

    backup_root = project_root / 'data' / 'backups'
    log_root = Path(str(current_app.config.get('LOG_FOLDER') or project_root / 'logs'))
    report_root = Path(str(current_app.config.get('REPORT_FOLDER') or project_root / 'reports'))
    upload_root = Path(str(current_app.config.get('UPLOAD_FOLDER') or project_root / 'app' / 'static' / 'uploads'))

    tasks = [
        {
            'key': 'config_freeze',
            'label': 'Konfigürasyon dondurma',
            'owner': 'BT',
            'status': 'done' if readiness['go_live']['counts']['fail'] == 0 else 'pending',
            'detail': 'Üretim ortamı değişkenleri ve servis başlangıç ayarları kilitlensin.',
        },
        {
            'key': 'db_backup',
            'label': 'Veritabanı yedeği',
            'owner': 'BT',
            'status': 'done' if readiness['go_live']['backup_summary']['recent_files'] else 'pending',
            'detail': f'Yedek kökü: {backup_root}',
        },
        {
            'key': 'ops_logs',
            'label': 'Log ve izleme doğrulaması',
            'owner': 'BT / Operasyon',
            'status': 'done' if log_root.exists() else 'pending',
            'detail': f'Log kökü: {log_root}',
        },
        {
            'key': 'uploads_reports',
            'label': 'Yükleme ve rapor klasör izinleri',
            'owner': 'BT',
            'status': 'done' if upload_root.exists() and report_root.exists() else 'pending',
            'detail': f'Upload: {upload_root} | Report: {report_root}',
        },
        {
            'key': 'pilot_users',
            'label': 'Pilot kullanıcı listesi ve iletişim',
            'owner': 'Proje / İK',
            'status': 'done' if len(checkpoint_logs) >= 2 else 'pending',
            'detail': 'Pilot açılış notu, destek kişileri ve geri bildirim kanalı netleşsin.',
        },
        {
            'key': 'rollback_plan',
            'label': 'Rollback planı',
            'owner': 'BT / Yönetim',
            'status': 'done' if readiness['go_live']['backup_summary']['recent_files'] else 'pending',
            'detail': 'Veritabanı dönüş, config geri alma ve erişim daraltma adımları hazır olmalı.',
        },
    ]

    for _task in tasks:
        _task['status_label'] = gate_status_label(_task['status'])

    handoff_rows = [
        {'title': 'Pilot kapsamı', 'body': 'Önce performans, izin-vekalet, bildirim ve yönetici görünürlüğü alanlarını açın.'},
        {'title': 'İlk 72 saat', 'body': 'CSRF, yönlendirme, export ve destek kuyruğu hatalarını yakın izleyin.'},
        {'title': 'Geri bildirim kanalı', 'body': 'Pilot kullanıcılar için tek destek kanalı ve tek raporlama formatı kullanın.'},
        {'title': 'Karar eşiği', 'body': 'Kritik blokaj varsa geniş açılış yapmayın; kontrollü pilotta kalın.'},
    ]

    return {
        'generated_at': _now(),
        'readiness': readiness,
        'tasks': tasks,
        'checkpoint_logs': checkpoint_logs,
        'handoff_rows': handoff_rows,
    }


def phase8_dashboard_snapshot(*, viewer: Any) -> dict[str, Any]:
    readiness = pilot_readiness_snapshot(viewer=viewer)
    cutover = cutover_snapshot(viewer=viewer)
    return {
        'readiness': readiness,
        'cutover': cutover,
        'summary_cards': [
            {'label': 'Hazırlık skoru', 'value': readiness['go_live']['readiness_score'], 'suffix': '/100'},
            {'label': 'Kritik blokaj', 'value': len(readiness['go_live']['blockers']), 'suffix': ''},
            {'label': 'Uyarı', 'value': readiness['counts']['warn'], 'suffix': ''},
            {'label': 'Kontrol noktası kaydı', 'value': len(cutover['checkpoint_logs']), 'suffix': ''},
        ],
    }


def record_phase8_checkpoint(actor: Any, checkpoint_key: str, status: str, note: str = '') -> CommunicationAutomationLog:
    checkpoint_key = safe_str(checkpoint_key)[:80] or 'genel'
    status = safe_str(status).lower()[:20] or 'pending'
    note = safe_str(note)[:500]
    summary = f'Faz 8 kontrol noktası | {checkpoint_key} | {status}'
    payload = {'checkpoint_key': checkpoint_key, 'status': status, 'note': note}
    row = log_action('phase8_checkpoint', actor, 'communication_phase8', None, summary, payload, status='success')
    db.session.commit()
    return row


def record_phase8_note(actor: Any, title: str, note: str = '') -> CommunicationAutomationLog:
    title = safe_str(title)[:120] or 'Pilot notu'
    note = safe_str(note)[:800]
    row = log_action('phase8_note', actor, 'communication_phase8', None, title, {'note': note}, status='success')
    db.session.commit()
    return row
