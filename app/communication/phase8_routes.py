from __future__ import annotations

import logging

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_OPTIONAL
# STATUS_SOURCE: app.communication.route_manifest OPTIONAL_ROUTE_MODULES
from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import consume_form_token, issue_form_token, menu_key_required, safe_render
from app.services.communication_phase8_service import (
    cutover_snapshot,
    phase8_dashboard_snapshot,
    pilot_readiness_snapshot,
    record_phase8_checkpoint,
    record_phase8_note,
)

logger = logging.getLogger(__name__)


@main_bp.route('/communication/faz8')
@login_required
@menu_key_required('reports')
def communication_phase8_dashboard():
    payload = phase8_dashboard_snapshot(viewer=current_user)  # K5 F4: viewer-scoped support figures
    return safe_render('communication/phase8_dashboard.html', payload=payload)


@main_bp.route('/communication/faz8/readiness')
@login_required
@menu_key_required('reports')
def communication_phase8_readiness():
    payload = pilot_readiness_snapshot(viewer=current_user)  # K5 F4: viewer-scoped support figures
    return safe_render('communication/phase8_readiness_center.html', payload=payload)


@main_bp.route('/communication/faz8/cutover')
@login_required
@menu_key_required('settings')
def communication_phase8_cutover():
    payload = cutover_snapshot(viewer=current_user)  # K5 F4: viewer-scoped support figures
    checkpoint_token = issue_form_token('communication_phase8_checkpoint', scope=str(current_user.id))
    note_token = issue_form_token('communication_phase8_note', scope=str(current_user.id))
    return safe_render(
        'communication/phase8_cutover_center.html',
        payload=payload,
        checkpoint_token=checkpoint_token,
        note_token=note_token,
    )


@main_bp.route('/communication/faz8/cutover/checkpoint', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase8_checkpoint_create():
    submitted = request.form.get('checkpoint_token')
    if not consume_form_token('communication_phase8_checkpoint', submitted, scope=str(current_user.id)):
        flash('Faz 8 kontrol noktası formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase8_cutover'))

    checkpoint_key = (request.form.get('checkpoint_key') or '').strip()
    status = (request.form.get('status') or 'pending').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase8_checkpoint(current_user, checkpoint_key, status, note)
        flash('Pilot kontrol noktası kaydedildi.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase8_routes.py | line=68 | exc=%s", exc)
        flash('Kontrol noktası kaydı oluşturulamadı.', 'danger')
    return redirect(url_for('main.communication_phase8_cutover'))


@main_bp.route('/communication/faz8/cutover/note', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase8_note_create():
    submitted = request.form.get('note_token')
    if not consume_form_token('communication_phase8_note', submitted, scope=str(current_user.id)):
        flash('Faz 8 not formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase8_cutover'))

    title = (request.form.get('title') or '').strip()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase8_note(current_user, title, note)
        flash('Pilot açılış notu kaydedildi.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase8_routes.py | line=87 | exc=%s", exc)
        flash('Pilot notu kaydedilemedi.', 'danger')
    return redirect(url_for('main.communication_phase8_cutover'))
