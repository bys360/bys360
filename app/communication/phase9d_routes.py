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
from app.services.communication_phase9d_service import (
    build_phase9d_markdown,
    phase9d_payload,
    phase9d_stabilization_snapshot,
    record_phase9d_checkin,
    record_phase9d_hotfix,
    record_phase9d_signal,
)

logger = logging.getLogger(__name__)


@main_bp.route('/communication/faz9d')
@login_required
@menu_key_required('reports')
def communication_phase9d_dashboard():
    payload = phase9d_stabilization_snapshot(viewer=current_user)
    checkin_token = issue_form_token('communication_phase9d_checkin', scope=str(current_user.id))
    hotfix_token = issue_form_token('communication_phase9d_hotfix', scope=str(current_user.id))
    signal_token = issue_form_token('communication_phase9d_signal', scope=str(current_user.id))
    return safe_render(
        'communication/phase9d_dashboard.html',
        payload=payload,
        checkin_token=checkin_token,
        hotfix_token=hotfix_token,
        signal_token=signal_token,
    )


@main_bp.route('/communication/faz9d/stabilization-center')
@login_required
@menu_key_required('settings')
def communication_phase9d_stabilization_center():
    payload = phase9d_stabilization_snapshot(viewer=current_user)
    checkin_token = issue_form_token('communication_phase9d_checkin', scope=str(current_user.id))
    hotfix_token = issue_form_token('communication_phase9d_hotfix', scope=str(current_user.id))
    signal_token = issue_form_token('communication_phase9d_signal', scope=str(current_user.id))
    return safe_render(
        'communication/phase9d_stabilization_center.html',
        payload=payload,
        checkin_token=checkin_token,
        hotfix_token=hotfix_token,
        signal_token=signal_token,
    )


@main_bp.route('/communication/faz9d/checkin', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9d_checkin_create():
    submitted = request.form.get('checkin_token')
    if not consume_form_token('communication_phase9d_checkin', submitted, scope=str(current_user.id)):
        flash('Faz 9D check-in formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9d_stabilization_center'))

    window_key = (request.form.get('window_key') or '').strip()
    status = (request.form.get('status') or 'watch').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9d_checkin(current_user, window_key, status, note)
        flash('Faz 9D check-in kaydedildi.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9d_routes.py | line=75 | exc=%s", exc)
        flash('Check-in kaydedilemedi.', 'danger')
    return redirect(url_for('main.communication_phase9d_stabilization_center'))


@main_bp.route('/communication/faz9d/hotfix', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9d_hotfix_create():
    submitted = request.form.get('hotfix_token')
    if not consume_form_token('communication_phase9d_hotfix', submitted, scope=str(current_user.id)):
        flash('Faz 9D hotfix formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9d_stabilization_center'))

    title = (request.form.get('title') or '').strip()
    severity = (request.form.get('severity') or 'medium').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9d_hotfix(current_user, title, severity, note)
        flash('Faz 9D hotfix kaydı oluşturuldu.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9d_routes.py | line=95 | exc=%s", exc)
        flash('Hotfix kaydı oluşturulamadı.', 'danger')
    return redirect(url_for('main.communication_phase9d_stabilization_center'))


@main_bp.route('/communication/faz9d/signal', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9d_signal_create():
    submitted = request.form.get('signal_token')
    if not consume_form_token('communication_phase9d_signal', submitted, scope=str(current_user.id)):
        flash('Faz 9D sinyal formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9d_stabilization_center'))

    signal_type = (request.form.get('signal_type') or '').strip()
    status = (request.form.get('status') or 'watch').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9d_signal(current_user, signal_type, status, note)
        flash('Faz 9D izleme sinyali kaydedildi.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9d_routes.py | line=115 | exc=%s", exc)
        flash('İzleme sinyali kaydedilemedi.', 'danger')
    return redirect(url_for('main.communication_phase9d_stabilization_center'))


@main_bp.route('/communication/faz9d/export/md')
@login_required
@menu_key_required('reports')
def communication_phase9d_export_md():
    return Response(
        build_phase9d_markdown(viewer=current_user),
        mimetype='text/markdown; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=communication_phase9d_stabilization.md'},
    )


@main_bp.route('/communication/faz9d/export/json')
@login_required
@menu_key_required('reports')
def communication_phase9d_export_json():
    payload = json.dumps(phase9d_payload(viewer=current_user), ensure_ascii=False, indent=2, default=str)
    data = BytesIO(payload.encode('utf-8'))
    data.seek(0)
    return send_file(
        data,
        as_attachment=True,
        download_name='communication_phase9d_stabilization.json',
        mimetype='application/json',
    )
