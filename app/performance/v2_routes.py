from __future__ import annotations

import logging
import time
from typing import Any, cast

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import EvaluationAssignment, PerformancePeriod, User
from app.route_registry import main_bp
from app.route_support import admin_required
from app.services.ai.dashboard_panels import (
    build_management_ai_panel,
    build_publish_ai_panel,
    build_scorecard_ai_panel,
)
from app.services.performance.interim_notes_runtime import build_interim_notes_context
from app.services.performance.low_score_process_service import (
    build_low_score_period_summary,
    ensure_low_score_processes_for_period,
)
from app.services.performance.publish_guard import (
    build_publish_preflight_report,
    build_scorecard_visibility_summary,
    publish_preflight_has_blockers,
)
from app.services.performance_v2 import (
    build_assignment_preview,
    build_assignment_previews_for_period,
    build_csv_export,
    build_excel_export,
    build_management_dashboard_context,
    build_manager_summary_context,
    build_period_scorecard_context,
    build_publish_workspace_context,
    build_workspace_context,
    default_policy_snapshot,
    ensure_assignments_for_period,
    publish_period_results,
    return_assignment_to_previous_level,
    save_assignment_draft,
    submit_assignment,
    unpublish_period_results,
    withdraw_assignment_submission,
)
from app.view_helpers import build_surface_scope_context

logger = logging.getLogger(__name__)

# BYS360_RUNTIME_LOGGEDIN_SLOW_PAGES_V3_SCORECARD_MEMORY_CACHE
_SCORECARD_CONTEXT_CACHE_TTL_SECONDS = 30
_SCORECARD_CONTEXT_CACHE: dict[str, tuple[float, Any]] = {}
_build_period_scorecard_context_uncached = build_period_scorecard_context


def _scorecard_cache_key(period, viewer=None, allowed_employee_ids=None, **kwargs):
    period_id = int(getattr(period, "id", 0) or 0)
    viewer_id = int(getattr(viewer, "id", 0) or getattr(current_user, "id", 0) or 0)
    role = str(getattr(viewer, "role", "") or getattr(current_user, "role", "") or "")
    try:
        allowed = tuple(sorted(int(x) for x in (allowed_employee_ids or []) if x))
    except (TypeError, ValueError):
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        allowed = tuple()
    allowed_token = hash(allowed)
    return f"scorecard:v3:period:{period_id}:viewer:{viewer_id}:role:{role}:allowed:{allowed_token}"


def _scorecard_cache_get(key: str):
    row = _SCORECARD_CONTEXT_CACHE.get(key)
    if not row:
        return None
    expires_at, value = row
    if expires_at < time.time():
        _SCORECARD_CONTEXT_CACHE.pop(key, None)
        return None
    return value


def _scorecard_cache_set(key: str, value):
    _SCORECARD_CONTEXT_CACHE[key] = (time.time() + _SCORECARD_CONTEXT_CACHE_TTL_SECONDS, value)
    return value


def build_period_scorecard_context(period, *args, **kwargs):  # type: ignore[no-redef]
    endpoint = str(getattr(request, "endpoint", "") or "")
    # Yayın, ön kontrol ve POST akışları her zaman taze çalışır; sadece okuma ekranları cache'lenir.
    if request.method != "GET" or endpoint.endswith("_publish") or endpoint.endswith("_publish_preflight"):
        return _build_period_scorecard_context_uncached(period, *args, **kwargs)
    if period is None:
        return _build_period_scorecard_context_uncached(period, *args, **kwargs)
    cache_key = _scorecard_cache_key(period, **kwargs)
    cached = _scorecard_cache_get(cache_key)
    if cached is not None:
        return cached
    return _scorecard_cache_set(cache_key, _build_period_scorecard_context_uncached(period, *args, **kwargs))

def _resolve_period(period_id: int | None = None):
    period = db.session.get(PerformancePeriod, period_id) if period_id else None
    if period is None:
        period = PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
    return period


def _visible_assignment_status_query(query):
    """Görev listesinde pasife alınmış / muaf kayıtları varsayılan görünümden çıkar.

    Zincir düzeltmelerinden sonra eski başkan / eski amir görevleri DB'de arşiv niteliğinde
    'pasif' veya 'muaf' statüsüne çekiliyor. Bunlar yöneticinin aktif görevlerinde
    görünmemeli; aksi halde görev var gibi görünür ama işlem akışı yanıltıcı olur.
    """
    return query.filter(~EvaluationAssignment.status.in_(['pasif', 'muaf']))


@main_bp.route('/performance/v2/faz1')
@main_bp.route('/performans/v2/faz1')
@login_required
@admin_required
def performance_v2_phase1_dashboard():
    period_id = request.args.get('period_id', type=int)
    employee_id = request.args.get('employee_id', type=int)
    period = _resolve_period(period_id)
    selected_employee = db.session.get(User, employee_id) if employee_id else None
    preview = build_assignment_preview(selected_employee, period) if (period and selected_employee) else None
    sample_previews = build_assignment_previews_for_period(period=period, limit=15) if period else []
    employee_options = (
        User.query.filter(User.is_active.is_(True), User.role != 'admin')
        .order_by(User.ad.asc(), User.soyad.asc())
        .limit(250)
        .all()
    )
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    return render_template(
        'performance_v2_phase1.html',
        period=period,
        periods=periods,
        selected_employee=selected_employee,
        employee_options=employee_options,
        preview=preview,
        sample_previews=sample_previews,
        policy_snapshot=default_policy_snapshot(),
    )


@main_bp.route('/performance/v2/faz1/preview/<int:employee_id>')
@main_bp.route('/performans/v2/faz1/preview/<int:employee_id>')
@login_required
@admin_required
def performance_v2_phase1_preview(employee_id: int):
    period_id = request.args.get('period_id', type=int)
    period = _resolve_period(period_id)
    employee = User.query.get_or_404(employee_id)
    if not period:
        return jsonify({'ok': False, 'message': 'Aktif dönem bulunamadı.'}), 404
    return jsonify({'ok': True, 'data': build_assignment_preview(employee=employee, period=period)})


@main_bp.route('/performance/v2/faz2', methods=['GET', 'POST'])
@main_bp.route('/performans/v2/faz2', methods=['GET', 'POST'])
@login_required
@admin_required
def performance_v2_phase2_dashboard():
    period = _resolve_period(request.values.get('period_id', type=int))
    result = None
    if request.method == 'POST' and period:
        employee_id = request.form.get('employee_id', type=int)
        result = ensure_assignments_for_period(period=period, employee_ids=[employee_id] if employee_id else None)
        flash('V2 görev senkronu tamamlandı.', 'success')
    employee_options = (
        User.query.filter(User.is_active.is_(True), User.role != 'admin')
        .order_by(User.ad.asc(), User.soyad.asc())
        .limit(250)
        .all()
    )
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    return render_template('performance_v2_phase2.html', period=period, periods=periods, employee_options=employee_options, result=result)


@main_bp.route('/performance/v2/faz3', endpoint='performance_v2_phase3_dashboard')
@main_bp.route('/performans/v2/faz3', endpoint='performance_v2_phase3_dashboard')
@main_bp.route('/performance/v2/faz3/board', endpoint='performance_v2_phase3_board')
@main_bp.route('/performans/v2/faz3/board', endpoint='performance_v2_phase3_board')
@login_required
def performance_v2_phase3_dashboard():
    period = _resolve_period(request.args.get('period_id', type=int))
    assignments = []
    if period:
        q = _visible_assignment_status_query(EvaluationAssignment.query.filter_by(period_id=period.id))
        if getattr(current_user, 'role', '') != 'admin':
            q = q.filter_by(evaluator_id=current_user.id)
        assignments = q.order_by(EvaluationAssignment.completed_at.asc().nullsfirst(), EvaluationAssignment.id.desc()).all()
    return render_template('performance_v2_phase3.html', period=period, assignments=assignments)


@main_bp.route('/performance/v2/faz3/assignment/<int:assignment_id>', methods=['GET', 'POST'])
@main_bp.route('/performans/v2/faz3/assignment/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
def performance_v2_phase3_assignment(assignment_id: int):
    context = build_workspace_context(assignment_id)
    assignment = context['assignment']
    if (getattr(assignment, 'status', '') or '').strip().lower() in {'pasif', 'muaf'}:
        flash('Bu görev pasife alındı veya muaf akışa geçtiği için artık işlem açılamaz.', 'warning')
        return redirect(url_for('main.performance_v2_phase3_dashboard'))
    if getattr(current_user, 'role', '') != 'admin' and assignment.evaluator_id != current_user.id:
        flash('Bu değerlendirme görevi size ait değil.', 'danger')
        return redirect(url_for('main.performance_v2_phase3_dashboard'))
    if request.method == 'POST':
        action = (request.form.get('action') or 'save').strip().lower()
        try:
            if action == 'save':  # BYS360_INTERIM_NOTES_ROUTE_ACTION_BINDING
                save_assignment_draft(assignment_id=assignment_id, form_data=request.form)
                db.session.commit()
                flash('Taslak kaydedildi.', 'success')
            elif action == 'submit':
                submit_assignment(assignment_id=assignment_id, form_data=request.form)
                db.session.commit()
                flash('Değerlendirme tamamlandı.', 'success')
            elif action == 'return':
                return_assignment_to_previous_level(assignment_id=assignment_id, note=request.form.get('return_note'))
                db.session.commit()
                flash('Kayıt 2. amire iade edildi.', 'warning')
            elif action == 'withdraw':
                withdraw_assignment_submission(assignment_id=assignment_id)
                db.session.commit()
                flash('Gönderim taslağa alındı.', 'info')
            else:
                flash('Bilinmeyen işlem.', 'warning')
        except ValueError as exc:
            if action == 'submit':
                try:
                    db.session.commit()
                    flash('Tamamlama uyarısı nedeniyle kayıt gönderilemedi; girdileriniz taslak olarak korundu.', 'warning')
                except Exception:
                    logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
                    db.session.rollback()
            else:
                db.session.rollback()
            flash(str(exc), 'danger')
        return redirect(url_for('main.performance_v2_phase3_assignment', assignment_id=assignment_id))
    if 'interim_notes_context' not in context or not context.get('interim_notes_context'):
        context['interim_notes_context'] = build_interim_notes_context(
            assignment=assignment,
            evaluation=context.get('evaluation'),
            viewer=current_user,
            surface='scoring',
        )

    # BYS360_INTERIM_NOTES_MANAGER_PAGE_SOURCE_CONTEXT
    context['interim_notes_context'] = build_interim_notes_context(
        assignment=assignment,
        evaluation=context.get('evaluation'),
        viewer=current_user,
        surface='scoring',
    )
    return render_template('performance_v2_phase3_assignment.html', **context)


@main_bp.route('/performance/v2/faz4')
@main_bp.route('/performans/v2/faz4')
@login_required
def performance_v2_phase4_dashboard():
    return redirect(url_for('main.performance_v2_phase3_dashboard', **cast("dict[str, Any]", request.args.to_dict())))


@main_bp.route('/performance/v2/faz4/board')
@main_bp.route('/performans/v2/faz4/board')
@login_required
def performance_v2_phase4_board():
    return redirect(url_for('main.performance_v2_phase4_dashboard', **cast("dict[str, Any]", request.args.to_dict())))


@main_bp.route('/performance/v2/faz4/assignment/<int:assignment_id>', methods=['GET', 'POST'])
@main_bp.route('/performans/v2/faz4/assignment/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
def performance_v2_phase4_assignment(assignment_id: int):
    return performance_v2_phase3_assignment(assignment_id)


@main_bp.route('/performance/v2/faz5')
@main_bp.route('/performans/v2/faz5')
@login_required
@admin_required
def performance_v2_phase5_dashboard():
    period = _resolve_period(request.args.get('period_id', type=int))
    # BYS360_PERF_SPEED: ensure_low_score GET'ten kaldirildi, sadece POST/publish'te tetiklenir
    scorecard = build_period_scorecard_context(period, viewer=current_user) if period else {'rows': [], 'count': 0, 'published_count': 0}
    manager_summary = build_manager_summary_context(period) if period else {'rows': []}
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    return render_template('performance_v2_phase5_dashboard.html', period=period, periods=periods, scorecard=scorecard, manager_summary=manager_summary)


@main_bp.route('/performance/v2/faz5/scorecard')
@main_bp.route('/performans/v2/faz5/scorecard')
@login_required
def performance_v2_phase5_scorecard():
    period = _resolve_period(request.args.get('period_id', type=int))
    # BYS360_PERF_SPEED: ensure_low_score GET'ten kaldirildi, sadece POST/publish'te tetiklenir
    scope_ctx = build_surface_scope_context(current_user, request.args.get('scope'))
    scorecard = build_period_scorecard_context(
        period,
        viewer=current_user,
        allowed_employee_ids=scope_ctx.get('employee_ids'),
    ) if period else {'rows': [], 'count': 0, 'published_count': 0}
    # BYS360_PHASE3_6_SCORECARD_PEER_PUBLISHED_DECORATOR
    try:
        from app.services.performance.peer_published_score_visibility import (
            decorate_scorecard_context_for_peer_published_scores,
        )
        scorecard = decorate_scorecard_context_for_peer_published_scores(
            scorecard,
            viewer=current_user,
            scope_ctx=scope_ctx,
        )
    except Exception as exc:
        current_app.logger.warning("Faz 3.6 aynı seviye puan görünürlüğü uygulanamadı: %s", exc)

    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    ai_scorecard_panel = build_scorecard_ai_panel(
        scorecard=scorecard,
        period=period,
        scope_label=scope_ctx.get('scope_label'),
    )
    scorecard_visibility_summary = build_scorecard_visibility_summary(scorecard)
    return render_template(
        'performance_v2_phase5_scorecard.html',
        period=period,
        periods=periods,
        scorecard=scorecard,
        selected_scope=scope_ctx.get('selected_scope'),
        scope_option_pairs=scope_ctx.get('scope_option_pairs'),
        scope_label=scope_ctx.get('scope_label'),
        scope_user_count=scope_ctx.get('scope_user_count', 0),
        ai_scorecard_panel=ai_scorecard_panel,
        scorecard_visibility_summary=scorecard_visibility_summary,
    )


@main_bp.route('/performance/v2/faz5/publish/preflight')
@main_bp.route('/performans/v2/faz5/publish/preflight')
@login_required
@admin_required
def performance_v2_phase5_publish_preflight():
    period = _resolve_period(request.args.get('period_id', type=int))
    # BYS360_PERF_SPEED: ensure_low_score GET'ten kaldirildi, sadece POST/publish'te tetiklenir
    scorecard = build_period_scorecard_context(period, viewer=current_user) if period else {'rows': [], 'count': 0, 'published_count': 0, 'completed_count': 0}
    publish_summary = build_publish_workspace_context(period, viewer=current_user) if period else {'blocked_reasons_summary': [], 'blocked_rows': [], 'ready_count': 0, 'blocked_count': 0, 'publish_rate': 0.0}
    publish_preflight = build_publish_preflight_report(period=period, scorecard=scorecard, publish_summary=publish_summary)
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    return render_template(
        'performance_publish_preflight.html',
        period=period,
        periods=periods,
        scorecard=scorecard,
        publish_summary=publish_summary,
        publish_preflight=publish_preflight,
        low_score_summary=build_low_score_period_summary(period) if period else {"total": 0, "pending_president": 0, "pending_hr": 0, "pending_warning": 0, "pending_admin_process": 0, "ready_for_publish": 0},
    )


@main_bp.route('/performance/v2/faz5/publish', methods=['GET', 'POST'])
@main_bp.route('/performans/v2/faz5/publish', methods=['GET', 'POST'])
@login_required
@admin_required
def performance_v2_phase5_publish():
    period = _resolve_period(request.values.get('period_id', type=int))
    if request.method == 'POST' and period:
        action = (request.form.get('publish_action') or '').strip().lower()
        force_publish = (request.form.get('force_publish') or '').strip() == '1'
        try:
            if action == 'publish':
                ensure_low_score_processes_for_period(period, actor_user_id=current_user.id)
                db.session.flush()
                scorecard_snapshot = build_period_scorecard_context(period, viewer=current_user)
                publish_summary_snapshot = build_publish_workspace_context(period, viewer=current_user)
                publish_preflight = build_publish_preflight_report(period=period, scorecard=scorecard_snapshot, publish_summary=publish_summary_snapshot)
                if publish_preflight_has_blockers(publish_preflight) and not force_publish:
                    flash('Yayın işlemi ön kontrolde durduruldu. Blokajlar çözülmeden toplu yayın başlatılmadı.', 'warning')
                    return redirect(url_for('main.performance_v2_phase5_publish_preflight', period_id=period.id))
                if force_publish and publish_preflight_has_blockers(publish_preflight):
                    flash('Blokaja rağmen yayın komutu verildi. Sistem yalnızca uygun kayıtları açacak, bloklu kayıtları atlayacaktır.', 'warning')
                result = publish_period_results(period=period, actor=current_user)
                published_count = int(result.get('published_count') or 0)
                notification_result = result.get('notification_result') or {}
                if published_count > 0:
                    flash(f'{published_count} sonuç personele açıldı.', 'success')
                    flash(
                        f"Bilgilendirme mailleri: başarılı {int(notification_result.get('success_count') or 0)}, başarısız {int(notification_result.get('failed_count') or 0)}, toplam alıcı {int(notification_result.get('recipient_count') or 0)}",
                        'success' if int(notification_result.get('failed_count') or 0) == 0 else 'warning',
                    )
                else:
                    flash('Yayımlanabilir tamamlanmış sonuç bulunamadı.', 'warning')

                for reason, count in (result.get('skip_reasons_summary') or [])[:3]:
                    flash(f'{count} kayıt atlandı: {reason}', 'warning')
            elif action == 'unpublish':
                result = unpublish_period_results(period=period, actor=current_user)
                flash(f"{int(result.get('unpublished_count') or 0)} kayıt personel görünümünden çıkarıldı.", 'warning')
            else:
                flash('Bilinmeyen yayın işlemi.', 'warning')
        except Exception as exc:
            current_app.logger.exception('V2 publish islemi basarisiz: %s', exc)
            db.session.rollback()
            flash('Yayın işlemi sırasında beklenmeyen bir hata oluştu.', 'danger')
        return redirect(url_for('main.performance_v2_phase5_publish', period_id=period.id))
    # BYS360_PERF_SPEED: ensure_low_score GET'ten kaldirildi, sadece POST/publish'te tetiklenir
    scorecard = build_period_scorecard_context(period, viewer=current_user) if period else {'rows': [], 'count': 0, 'published_count': 0}
    publish_summary = build_publish_workspace_context(period, viewer=current_user) if period else {'blocked_reasons_summary': [], 'blocked_rows': [], 'ready_count': 0, 'blocked_count': 0, 'publish_rate': 0.0}
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    ai_publish_panel = build_publish_ai_panel(scorecard=scorecard, publish_summary=publish_summary, period=period)
    publish_preflight = build_publish_preflight_report(period=period, scorecard=scorecard, publish_summary=publish_summary)
    return render_template(
        'performance_v2_phase5_publish.html',
        period=period,
        periods=periods,
        scorecard=scorecard,
        publish_summary=publish_summary,
        ai_publish_panel=ai_publish_panel,
        publish_preflight=publish_preflight,
        low_score_summary=build_low_score_period_summary(period) if period else {"total": 0, "pending_president": 0, "pending_hr": 0, "pending_warning": 0, "pending_admin_process": 0, "ready_for_publish": 0},
    )


@main_bp.route('/performance/v2/faz6')
@main_bp.route('/performans/v2/faz6')
@login_required
@admin_required
def performance_v2_phase6_dashboard():
    period = _resolve_period(request.args.get('period_id', type=int))
    periods = PerformancePeriod.query.order_by(PerformancePeriod.id.desc()).limit(50).all()
    dashboard = build_management_dashboard_context(period, viewer=current_user) if period else None
    publish_summary = build_publish_workspace_context(period, viewer=current_user) if period else None
    ai_management_panel = build_management_ai_panel(
        dashboard=dashboard,
        publish_summary=publish_summary,
        period=period,
    ) if period else None
    return render_template(
        'performance_v2_phase6_dashboard.html',
        period=period,
        periods=periods,
        dashboard=dashboard,
        publish_summary=publish_summary,
        ai_management_panel=ai_management_panel,
    )


@main_bp.route('/performance/v2/faz6/export/xlsx')
@main_bp.route('/performans/v2/faz6/export/xlsx')
@login_required
@admin_required
def performance_v2_phase6_export_xlsx():
    period = _resolve_period(request.args.get('period_id', type=int))
    if not period:
        flash('Dönem bulunamadı.', 'warning')
        return redirect(url_for('main.performance_v2_phase6_dashboard'))
    payload = build_excel_export(period, viewer=current_user)
    return send_file(
        payload,
        as_attachment=True,
        download_name=f'bys360_performance_v2_{period.id}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@main_bp.route('/performance/v2/faz6/export/csv')
@main_bp.route('/performans/v2/faz6/export/csv')
@login_required
@admin_required
def performance_v2_phase6_export_csv():
    period = _resolve_period(request.args.get('period_id', type=int))
    export_type = (request.args.get('type') or 'scorecard').strip().lower()
    if not period:
        flash('Dönem bulunamadı.', 'warning')
        return redirect(url_for('main.performance_v2_phase6_dashboard'))
    payload = build_csv_export(period, export_type=export_type, viewer=current_user)
    return send_file(
        payload,
        as_attachment=True,
        download_name=f'bys360_performance_v2_{export_type}_{period.id}.csv',
        mimetype='text/csv; charset=utf-8',
    )

@main_bp.route('/performance/v2/faz6/print')
@main_bp.route('/performans/v2/faz6/print')
@login_required
@admin_required
def performance_v2_phase6_print():
    period = _resolve_period(request.args.get('period_id', type=int))
    if not period:
        flash('Dönem bulunamadı.', 'warning')
        return redirect(url_for('main.performance_v2_phase6_dashboard'))
    dashboard = build_management_dashboard_context(period, viewer=current_user)
    publish_summary = build_publish_workspace_context(period, viewer=current_user)
    return render_template(
        'performance_v2_phase6_print.html',
        period=period,
        dashboard=dashboard,
        publish_summary=publish_summary,
    )

@main_bp.route('/performance/v2/faz8', endpoint='performance_v2_phase8_dashboard')
@main_bp.route('/performans/v2/faz8', endpoint='performance_v2_phase8_dashboard')
@login_required
def performance_v2_phase8_dashboard():
    """Canlı akışta Faz 8 adı geçen yönlendirmeleri güvenli alias ile karşıla."""
    return redirect(url_for('main.performance_v2_phase6_dashboard', **cast("dict[str, Any]", request.args.to_dict())))


@main_bp.route('/performance/v2/faz8/assignment/<int:assignment_id>', endpoint='performance_v2_phase8_assignment', methods=['GET', 'POST'])
@main_bp.route('/performans/v2/faz8/assignment/<int:assignment_id>', endpoint='performance_v2_phase8_assignment', methods=['GET', 'POST'])
@login_required
def performance_v2_phase8_assignment(assignment_id: int):
    """Eski/değişen ekran yönlendirmelerini mevcut değerlendirme çalışma alanına bağla."""
    return performance_v2_phase3_assignment(assignment_id)