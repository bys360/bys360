from __future__ import annotations

# STATUS: ACTIVE
# BYS360_ROUTE_STATUS: ACTIVE_OPTIONAL
# STATUS_SOURCE: app.communication.route_manifest OPTIONAL_ROUTE_MODULES
import json
import logging
from io import BytesIO

from flask import Response, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required

from app.route_registry import main_bp
from app.route_support import consume_form_token, issue_form_token, menu_key_required, safe_render
from app.services.communication_phase9_service import (
    build_phase9_release_markdown,
    phase9_dashboard_snapshot,
    phase9_first72_snapshot,
    phase9_release_center_snapshot,
    phase9_release_payload,
    record_phase9_checkpoint,
    record_phase9_decision,
)

logger = logging.getLogger(__name__)


@main_bp.route('/communication/faz9')
@login_required
@menu_key_required('reports')
def communication_phase9_dashboard():
    payload = phase9_dashboard_snapshot(viewer=current_user)
    return safe_render('communication/phase9_dashboard.html', payload=payload)


@main_bp.route('/communication/faz9/release-center')
@login_required
@menu_key_required('settings')
def communication_phase9_release_center():
    payload = phase9_release_center_snapshot(viewer=current_user)
    checkpoint_token = issue_form_token('communication_phase9_checkpoint', scope=str(current_user.id))
    decision_token = issue_form_token('communication_phase9_decision', scope=str(current_user.id))
    return safe_render(
        'communication/phase9_release_center.html',
        payload=payload,
        checkpoint_token=checkpoint_token,
        decision_token=decision_token,
    )


@main_bp.route('/communication/faz9/first-72')
@login_required
@menu_key_required('reports')
def communication_phase9_first72():
    payload = phase9_first72_snapshot(viewer=current_user)
    return safe_render('communication/phase9_first72_center.html', payload=payload)


@main_bp.route('/communication/faz9/checkpoint', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9_checkpoint_create():
    submitted = request.form.get('checkpoint_token')
    if not consume_form_token('communication_phase9_checkpoint', submitted, scope=str(current_user.id)):
        flash('Faz 9 kontrol noktası formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9_release_center'))

    checkpoint_key = (request.form.get('checkpoint_key') or '').strip()
    status = (request.form.get('status') or 'pending').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9_checkpoint(current_user, checkpoint_key, status, note)
        flash('Faz 9 kontrol noktası kaydedildi.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9_routes.py | line=73 | exc=%s", exc)
        flash('Kontrol noktası kaydı oluşturulamadı.', 'danger')
    return redirect(url_for('main.communication_phase9_release_center'))


@main_bp.route('/communication/faz9/decision', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9_decision_create():
    submitted = request.form.get('decision_token')
    if not consume_form_token('communication_phase9_decision', submitted, scope=str(current_user.id)):
        flash('Faz 9 karar formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9_release_center'))

    decision = (request.form.get('decision') or '').strip()
    status = (request.form.get('status') or 'controlled').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9_decision(current_user, decision, status, note)
        flash('Canlıya geçiş kararı kaydedildi.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9_routes.py | line=93 | exc=%s", exc)
        flash('Karar kaydedilemedi.', 'danger')
    return redirect(url_for('main.communication_phase9_release_center'))


@main_bp.route('/communication/faz9/export/md')
@login_required
@menu_key_required('reports')
def communication_phase9_export_md():
    return Response(
        build_phase9_release_markdown(viewer=current_user),
        mimetype='text/markdown; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=communication_phase9_go_live.md'},
    )


@main_bp.route('/communication/faz9/export/json')
@login_required
@menu_key_required('reports')
def communication_phase9_export_json():
    payload = json.dumps(phase9_release_payload(viewer=current_user), ensure_ascii=False, default=str, indent=2)
    data = BytesIO(payload.encode('utf-8'))
    data.seek(0)
    return send_file(
        data,
        as_attachment=True,
        download_name='communication_phase9_go_live.json',
        mimetype='application/json',
    )
