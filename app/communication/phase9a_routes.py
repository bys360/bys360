from __future__ import annotations

import logging

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_OPTIONAL
# STATUS_SOURCE: app.communication.route_manifest OPTIONAL_ROUTE_MODULES
from flask import Response, flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import consume_form_token, issue_form_token, menu_key_required, safe_render
from app.services.communication_phase9a_service import (
    build_phase9a_markdown,
    phase9a_backup_snapshot,
    phase9a_dashboard_snapshot,
    phase9a_preflight_snapshot,
    record_phase9a_freeze,
    record_phase9a_smoke,
)

logger = logging.getLogger(__name__)


@main_bp.route('/communication/faz9a')
@login_required
@menu_key_required('reports')
def communication_phase9a_dashboard():
    payload = phase9a_dashboard_snapshot(viewer=current_user)
    return safe_render('communication/phase9a_dashboard.html', payload=payload)


@main_bp.route('/communication/faz9a/preflight')
@login_required
@menu_key_required('settings')
def communication_phase9a_preflight_center():
    payload = phase9a_preflight_snapshot(viewer=current_user)
    freeze_token = issue_form_token('communication_phase9a_freeze', scope=str(current_user.id))
    smoke_token = issue_form_token('communication_phase9a_smoke', scope=str(current_user.id))
    return safe_render(
        'communication/phase9a_preflight_center.html',
        payload=payload,
        freeze_token=freeze_token,
        smoke_token=smoke_token,
    )


@main_bp.route('/communication/faz9a/backup')
@login_required
@menu_key_required('reports')
def communication_phase9a_backup_center():
    payload = phase9a_backup_snapshot(viewer=current_user)
    return safe_render('communication/phase9a_backup_center.html', payload=payload)


@main_bp.route('/communication/faz9a/freeze', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9a_freeze_create():
    submitted = request.form.get('freeze_token')
    if not consume_form_token('communication_phase9a_freeze', submitted, scope=str(current_user.id)):
        flash('Faz 9A teknik kilit formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9a_preflight_center'))

    status = (request.form.get('status') or 'pending').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9a_freeze(current_user, status, note)
        flash('Faz 9A teknik kilit kaydı oluşturuldu.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9a_routes.py | line=68 | exc=%s", exc)
        flash('Teknik kilit kaydı oluşturulamadı.', 'danger')
    return redirect(url_for('main.communication_phase9a_preflight_center'))


@main_bp.route('/communication/faz9a/smoke', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9a_smoke_create():
    submitted = request.form.get('smoke_token')
    if not consume_form_token('communication_phase9a_smoke', submitted, scope=str(current_user.id)):
        flash('Faz 9A smoke formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9a_preflight_center'))

    target = (request.form.get('target') or '').strip()
    status = (request.form.get('status') or 'pending').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9a_smoke(current_user, target, status, note)
        flash('Faz 9A smoke kaydı işlendi.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9a_routes.py | line=88 | exc=%s", exc)
        flash('Smoke kaydı işlenemedi.', 'danger')
    return redirect(url_for('main.communication_phase9a_preflight_center'))


@main_bp.route('/communication/faz9a/export/md')
@login_required
@menu_key_required('reports')
def communication_phase9a_export_md():
    return Response(
        build_phase9a_markdown(viewer=current_user),
        mimetype='text/markdown; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=communication_phase9a_teknik_kilit.md'},
    )
