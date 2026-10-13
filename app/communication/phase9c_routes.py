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
from app.services.communication_phase9c_service import (
    build_phase9c_markdown,
    phase9c_payload,
    phase9c_pilot_opening_snapshot,
    record_phase9c_decision,
    record_phase9c_gate,
    record_phase9c_incident,
)

logger = logging.getLogger(__name__)


@main_bp.route('/communication/faz9c')
@login_required
@menu_key_required('reports')
def communication_phase9c_dashboard():
    payload = phase9c_pilot_opening_snapshot(viewer=current_user)
    gate_token = issue_form_token('communication_phase9c_gate', scope=str(current_user.id))
    decision_token = issue_form_token('communication_phase9c_decision', scope=str(current_user.id))
    incident_token = issue_form_token('communication_phase9c_incident', scope=str(current_user.id))
    return safe_render(
        'communication/phase9c_dashboard.html',
        payload=payload,
        gate_token=gate_token,
        decision_token=decision_token,
        incident_token=incident_token,
    )


@main_bp.route('/communication/faz9c/pilot-opening')
@login_required
@menu_key_required('settings')
def communication_phase9c_pilot_opening_center():
    payload = phase9c_pilot_opening_snapshot(viewer=current_user)
    gate_token = issue_form_token('communication_phase9c_gate', scope=str(current_user.id))
    decision_token = issue_form_token('communication_phase9c_decision', scope=str(current_user.id))
    incident_token = issue_form_token('communication_phase9c_incident', scope=str(current_user.id))
    return safe_render(
        'communication/phase9c_pilot_opening_center.html',
        payload=payload,
        gate_token=gate_token,
        decision_token=decision_token,
        incident_token=incident_token,
    )


@main_bp.route('/communication/faz9c/gate', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9c_gate_create():
    submitted = request.form.get('gate_token')
    if not consume_form_token('communication_phase9c_gate', submitted, scope=str(current_user.id)):
        flash('Faz 9C kapı formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9c_pilot_opening_center'))

    gate_key = (request.form.get('gate_key') or '').strip()
    status = (request.form.get('status') or 'pending').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9c_gate(current_user, gate_key, status, note)
        flash('Faz 9C kapı kaydı oluşturuldu.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9c_routes.py | line=75 | exc=%s", exc)
        flash('Kapı kaydı oluşturulamadı.', 'danger')
    return redirect(url_for('main.communication_phase9c_pilot_opening_center'))


@main_bp.route('/communication/faz9c/decision', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9c_decision_create():
    submitted = request.form.get('decision_token')
    if not consume_form_token('communication_phase9c_decision', submitted, scope=str(current_user.id)):
        flash('Faz 9C karar formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9c_pilot_opening_center'))

    decision = (request.form.get('decision') or '').strip()
    status = (request.form.get('status') or 'controlled').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9c_decision(current_user, decision, status, note)
        flash('Faz 9C karar kaydı oluşturuldu.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9c_routes.py | line=95 | exc=%s", exc)
        flash('Karar kaydı oluşturulamadı.', 'danger')
    return redirect(url_for('main.communication_phase9c_pilot_opening_center'))


@main_bp.route('/communication/faz9c/incident', methods=['POST'])
@login_required
@menu_key_required('settings')
def communication_phase9c_incident_create():
    submitted = request.form.get('incident_token')
    if not consume_form_token('communication_phase9c_incident', submitted, scope=str(current_user.id)):
        flash('Faz 9C olay formu geçersiz veya süresi dolmuş.', 'danger')
        return redirect(url_for('main.communication_phase9c_pilot_opening_center'))

    title = (request.form.get('title') or '').strip()
    severity = (request.form.get('severity') or 'medium').strip().lower()
    note = (request.form.get('note') or '').strip()
    try:
        record_phase9c_incident(current_user, title, severity, note)
        flash('Pilot olay kaydı oluşturuldu.', 'success')
    except Exception as exc:
        logger.exception("BYS360 V6C guarded exception | file=app/communication/phase9c_routes.py | line=115 | exc=%s", exc)
        flash('Olay kaydı oluşturulamadı.', 'danger')
    return redirect(url_for('main.communication_phase9c_pilot_opening_center'))


@main_bp.route('/communication/faz9c/export/md')
@login_required
@menu_key_required('reports')
def communication_phase9c_export_md():
    return Response(
        build_phase9c_markdown(viewer=current_user),
        mimetype='text/markdown; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=communication_phase9c_pilot_opening.md'},
    )


@main_bp.route('/communication/faz9c/export/json')
@login_required
@menu_key_required('reports')
def communication_phase9c_export_json():
    payload = json.dumps(phase9c_payload(viewer=current_user), ensure_ascii=False, indent=2, default=str)
    data = BytesIO(payload.encode('utf-8'))
    data.seek(0)
    return send_file(
        data,
        as_attachment=True,
        download_name='communication_phase9c_pilot_opening.json',
        mimetype='application/json',
    )
