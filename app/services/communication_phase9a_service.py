from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models.communication_phase5_models import CommunicationAutomationLog
from app.services.communication_gate_status_labels import gate_status_label
from app.services.communication_phase5_service import log_action, safe_str
from app.services.communication_phase9_service import (
    phase9_first72_snapshot,
    phase9_release_center_snapshot,
)


class CommunicationPhase9AError(RuntimeError):
    pass


def _now() -> datetime:
    return utc_now()


def _env_row(key: str, required: bool = True, expected: str = '', mask: bool = True) -> dict[str, Any]:
    value = os.getenv(key)
    exists = bool(value)
    status = 'pass' if exists else 'fail' if required else 'warn'
    shown = '***' if (exists and mask and key not in {'APP_ENV', 'APP_PORT', 'UPLOAD_FOLDER', 'REPORT_FOLDER', 'LOG_FOLDER'}) else (value or '-')
    detail = f'Beklenen: {expected}' if expected else ('Tanımlı' if exists else 'Tanımlı değil')
    return {
        'key': key,
        'status': status,
        'status_label': gate_status_label(status),
        'required': required,
        'value': shown,
        'detail': detail,
    }


def _path_row(label: str, path_value: str | None) -> dict[str, Any]:
    exists = path_value is not None and os.path.exists(path_value)
    path_status = 'pass' if exists else 'fail'
    return {
        'label': label,
        'path': path_value or '-',
        'status': path_status,
        'status_label': gate_status_label(path_status),
        'detail': 'Klasör mevcut' if exists else 'Klasör bulunamadı veya env eksik',
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out = {'pass': 0, 'warn': 0, 'fail': 0}
    for row in rows:
        status = safe_str(row.get('status')).lower()
        if status in out:
            out[status] += 1
    return out


def _recent_phase9a_logs(limit: int = 20) -> list[CommunicationAutomationLog]:
    return (
        CommunicationAutomationLog.query
        .filter(CommunicationAutomationLog.action_type.in_(['phase9a_freeze', 'phase9a_smoke']))
        .order_by(CommunicationAutomationLog.executed_at.desc())
        .limit(limit)
        .all()
    )


def phase9a_preflight_snapshot(*, viewer: Any) -> dict[str, Any]:
    release = phase9_release_center_snapshot(viewer=viewer)
    first72 = phase9_first72_snapshot(viewer=viewer)

    env_rows = [
        _env_row('APP_ENV', True, 'production', mask=False),
        _env_row('DATABASE_URL', True, 'PostgreSQL bağlantısı'),
        _env_row('SECRET_KEY', True, 'Uygulama gizli anahtarı'),
        _env_row('UPLOAD_FOLDER', True, 'Dosya yükleme klasörü', mask=False),
        _env_row('REPORT_FOLDER', True, 'Rapor klasörü', mask=False),
        _env_row('LOG_FOLDER', True, 'Log klasörü', mask=False),
        _env_row('SESSION_COOKIE_SECURE', False, 'true/false', mask=False),
        _env_row('REMEMBER_COOKIE_SECURE', False, 'true/false', mask=False),
        _env_row('SESSION_COOKIE_SAMESITE', False, 'Lax', mask=False),
    ]

    path_rows = [
        _path_row('Upload klasörü', os.getenv('UPLOAD_FOLDER')),
        _path_row('Rapor klasörü', os.getenv('REPORT_FOLDER')),
        _path_row('Log klasörü', os.getenv('LOG_FOLDER')),
    ]

    freeze_gates = [
        {
            'label': 'Kod freeze',
            'status': 'pass' if release.get('gate_counts', {}).get('fail', 0) == 0 else 'warn',
            'detail': 'Canlı açılış öncesi yeni feature değil sadece hotfix penceresi açık olmalı.',
            'owner': 'BT / Proje',
        },
        {
            'label': 'Production env',
            'status': 'pass' if _counts(env_rows).get('fail', 0) == 0 else 'fail',
            'detail': 'Zorunlu ortam değişkenleri eksiksiz doğrulanmalı.',
            'owner': 'BT',
        },
        {
            'label': 'Temel smoke matrisi',
            'status': 'pass' if len(first72.get('smoke_rows', [])) >= 5 else 'warn',
            'detail': 'Açılış öncesi temel ekran listesi sabitlenmiş olmalı.',
            'owner': 'BT / Süreç Sahibi',
        },
        {
            'label': 'Teknik kayıt izi',
            'status': 'pass' if len(_recent_phase9a_logs()) >= 1 else 'warn',
            'detail': 'Freeze ve smoke kararları sistem içine not düşülmeli.',
            'owner': 'BT / Yönetim',
        },
    ]
    for _row in freeze_gates:
        _row['status_label'] = gate_status_label(_row['status'])

    return {
        'generated_at': _now(),
        'release': release,
        'first72': first72,
        'env_rows': env_rows,
        'path_rows': path_rows,
        'freeze_gates': freeze_gates,
        'counts': {
            'env': _counts(env_rows),
            'paths': _counts(path_rows),
            'gates': _counts(freeze_gates),
        },
        'recent_logs': _recent_phase9a_logs(),
    }


def phase9a_backup_snapshot(*, viewer: Any) -> dict[str, Any]:
    release = phase9_release_center_snapshot(viewer=viewer)
    go_live = release.get('go_live', {}) or {}
    backup_summary = go_live.get('backup_summary', {}) or {}
    log_summary = go_live.get('log_summary', {}) or {}

    backup_checks = [
        {
            'label': 'Yedek kanıtı',
            'status': 'pass' if len(backup_summary.get('recent_files', []) or []) >= 1 else 'fail',
            'detail': 'Son yedek dosyasının fiziksel olarak görülmesi gerekir.',
        },
        {
            'label': 'Rollback notu',
            'status': 'warn',
            'detail': 'Rollback adımları yazılı, kısa ve tek sayfada tutulmalı.',
        },
        {
            'label': 'Log klasörü akışı',
            'status': 'pass' if len(log_summary.get('recent_files', []) or []) >= 1 else 'warn',
            'detail': 'İlk 72 saatte log klasörü günlük kontrol edilmeli.',
        },
    ]
    for _row in backup_checks:
        _row['status_label'] = gate_status_label(_row['status'])

    return {
        'generated_at': _now(),
        'release': release,
        'backup_summary': backup_summary,
        'log_summary': log_summary,
        'backup_checks': backup_checks,
        'recent_logs': _recent_phase9a_logs(),
    }


def phase9a_dashboard_snapshot(*, viewer: Any) -> dict[str, Any]:
    preflight = phase9a_preflight_snapshot(viewer=viewer)
    backup = phase9a_backup_snapshot(viewer=viewer)
    release = preflight['release']
    summary_cards = [
        {'label': 'Env blokajı', 'value': preflight['counts']['env'].get('fail', 0), 'suffix': ''},
        {'label': 'Klasör blokajı', 'value': preflight['counts']['paths'].get('fail', 0), 'suffix': ''},
        {'label': 'Yedek dosyası', 'value': len((backup.get('backup_summary') or {}).get('recent_files', []) or []), 'suffix': ''},
        {'label': 'Teknik kayıt', 'value': len(preflight.get('recent_logs', []) or []), 'suffix': ''},
    ]
    return {
        'generated_at': _now(),
        'release': release,
        'preflight': preflight,
        'backup': backup,
        'summary_cards': summary_cards,
    }


def build_phase9a_markdown(*, viewer: Any) -> str:
    payload = phase9a_dashboard_snapshot(viewer=viewer)
    lines = [
        '# BYS360 İletişim ve Anket | Faz 9A Teknik Kilit',
        '',
        f"- Üretim zamanı: {payload['generated_at']}",
        f"- Env blokajı: {payload['preflight']['counts']['env'].get('fail', 0)}",
        f"- Klasör blokajı: {payload['preflight']['counts']['paths'].get('fail', 0)}",
        f"- Yedek dosyası: {len((payload['backup'].get('backup_summary') or {}).get('recent_files', []) or [])}",
        '',
        '## Freeze kapıları',
        '',
    ]
    for row in payload['preflight']['freeze_gates']:
        lines.append(f"- [{row['status']}] {row['label']} — {row['detail']} ({row['owner']})")
    lines.extend(['', '## Env kontrolü', ''])
    for row in payload['preflight']['env_rows']:
        lines.append(f"- [{row['status']}] {row['key']} — {row['detail']}")
    lines.extend(['', '## Klasör kontrolü', ''])
    for row in payload['preflight']['path_rows']:
        lines.append(f"- [{row['status']}] {row['label']} — {row['path']} — {row['detail']}")
    lines.extend(['', '## Yedek ve rollback', ''])
    for row in payload['backup']['backup_checks']:
        lines.append(f"- [{row['status']}] {row['label']} — {row['detail']}")
    return "\n".join(lines).strip() + "\n"


def record_phase9a_freeze(actor: Any, status: str, note: str = '') -> CommunicationAutomationLog:
    status = safe_str(status).lower()[:20] or 'pending'
    note = safe_str(note)[:800]
    row = log_action(
        'phase9a_freeze',
        actor,
        'communication_phase9a',
        None,
        f'Faz 9A teknik kilit | {status}',
        {'status': status, 'note': note},
        status='success',
    )
    db.session.commit()
    return row


def record_phase9a_smoke(actor: Any, target: str, status: str, note: str = '') -> CommunicationAutomationLog:
    target = safe_str(target)[:160] or 'genel'
    status = safe_str(status).lower()[:20] or 'pending'
    note = safe_str(note)[:800]
    row = log_action(
        'phase9a_smoke',
        actor,
        'communication_phase9a',
        None,
        f'Faz 9A smoke | {target} | {status}',
        {'target': target, 'status': status, 'note': note},
        status='success',
    )
    db.session.commit()
    return row