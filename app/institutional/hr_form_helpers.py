from __future__ import annotations

from app.institutional.hr_common import (
    Any,
    AttendanceException,
    DelegationAssignment,
    LeaveBalance,
    PersonnelLeave,
    _active_delegation_exists,
    _attendance_overlaps,
    _bool_from_form,
    _calculate_leave_day_count,
    _current_user_id,
    _leave_overlaps,
    _model_ready,
    _parse_date,
    _resolve_period_id_from_form,
    _safe_commit,
    _safe_float,
    _safe_int,
    _safe_text,
    consume_form_token,
    date,
    db,
    flash,
    redirect,
    request,
    url_for,
    utc_now,
)

HR_SCOPE_REFUSAL_MESSAGE = "Bu kayıt yetki kapsamınız dışındaki bir personeli içeriyor; kayıt oluşturulmadı."


def _people_outside_caller_scope(*user_ids: int | None) -> bool:
    """P0 (M-1 Q4): oluşturma da durum/silme ile aynı kapsam kuralına tabidir.

    Onaylı izin/devamsızlık ve vekâlet kayıtları performans görevlerinin değerlendiricisini
    değiştirir; kaydın içerdiği her kişi çağıranın en geniş kapsamında olmalıdır (çağıranın kendisi
    ve sorumlu olduğu personel; gerçek admin için tüm kurum).
    """
    from flask_login import current_user

    from app.services.ui_context.scope import build_user_scope_context

    scope_ids = set(build_user_scope_context(current_user, "all").get("scope_user_ids") or [])
    return any(user_id not in scope_ids for user_id in user_ids if user_id)


def _refuse_out_of_scope(reason: str, redirect_endpoint: str) -> Any:
    from app.services.account_change_guard import audit_refusal

    audit_refusal(None, f"hr_scope:{reason}")
    flash(HR_SCOPE_REFUSAL_MESSAGE, "danger")
    return redirect(url_for(redirect_endpoint, scope=request.form.get("scope") or "personal"))


def _create_delegation_from_form(*, delegator_user_id: int, start_date: date, end_date: date, source_leave_id: int | None = None, source_attendance_id: int | None = None) -> bool:
    delegate_user_id = _safe_int(request.form.get("delegate_user_id"))
    if not delegate_user_id:
        return False
    if not _model_ready(DelegationAssignment):
        flash("Vekâlet tablosu hazır olmadığı için vekâlet oluşturulamadı; ana kayıt kaydedildi.", "warning")
        return False
    if delegate_user_id == delegator_user_id:
        flash("Vekil personel, asıl amir/personel ile aynı olamaz. Ana kayıt kaydedildi, vekâlet oluşturulmadı.", "warning")
        return False
    delegation = DelegationAssignment(
        delegator_user_id=delegator_user_id,
        delegate_user_id=delegate_user_id,
        source_leave_id=source_leave_id,
        source_attendance_id=source_attendance_id,
        status="aktif",
        start_date=start_date,
        end_date=end_date,
        scope_type=_safe_text(request.form.get("delegation_scope_type") or request.form.get("scope_type"), "performance"),
        applies_level_1=_bool_from_form("delegation_applies_level_1", _bool_from_form("applies_level_1", True)),
        applies_level_2=_bool_from_form("delegation_applies_level_2", _bool_from_form("applies_level_2", True)),
        applies_level_3=_bool_from_form("delegation_applies_level_3", _bool_from_form("applies_level_3", False)),
        note=_safe_text(request.form.get("delegation_note") or request.form.get("note")) or None,
        approved_by_id=_current_user_id(),
        approved_at=utc_now(),
    )
    db.session.add(delegation)
    return True


def _handle_leave_post() -> Any:
    action = _safe_text(request.form.get("action"), "create_leave")
    if action == "save_balance":
        return _handle_leave_balance_post()
    if action != "create_leave":
        flash("Bilinmeyen izin işlemi.", "warning")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or request.args.get("scope") or "personal"))

    if not consume_form_token("hr_management", request.form.get("_form_token"), scope="leave_create"):
        flash("Bu izin kaydı zaten gönderilmiş ya da oturum form anahtarı yenilenmiş. Sayfayı yenileyip tekrar deneyin.", "warning")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or request.args.get("scope") or "personal"))
    if not _model_ready(PersonnelLeave):
        flash("İzin tablosu hazır değil.", "warning")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal"))

    user_id = _safe_int(request.form.get("user_id"))
    start = _parse_date(request.form.get("start_date"))
    end = _parse_date(request.form.get("end_date"))
    if not user_id or not start or not end:
        flash("Personel, başlangıç ve bitiş tarihi zorunludur.", "danger")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal"))
    if end < start:
        flash("Bitiş tarihi başlangıç tarihinden önce olamaz.", "danger")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal"))
    if _people_outside_caller_scope(user_id):
        return _refuse_out_of_scope("leave_create", "main.hr_leave_management")
    if _leave_overlaps(user_id, start, end):
        flash("Bu personel için seçilen tarih aralığında zaten izin kaydı var. Mükerrer kayıt engellendi.", "warning")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal", user_id=user_id))

    leave = PersonnelLeave(
        user_id=user_id,
        period_id=_resolve_period_id_from_form(),
        leave_type=_safe_text(request.form.get("leave_type"), "diger"),
        status=_safe_text(request.form.get("status"), "onaylandi"),
        start_date=start,
        end_date=end,
        approved_day_count=_calculate_leave_day_count(start, end),
        start_half_day=_bool_from_form("start_half_day"),
        end_half_day=_bool_from_form("end_half_day"),
        blocks_performance_evaluation=_bool_from_form("blocks_performance_evaluation", True),
        performance_mode=_safe_text(request.form.get("performance_mode"), "partial"),
        blocks_manager_duties=_bool_from_form("blocks_manager_duties", True),
        description=_safe_text(request.form.get("description")) or None,
        approved_by_id=_current_user_id(),
        approved_at=utc_now(),
    )
    db.session.add(leave)
    db.session.flush()

    if leave.blocks_manager_duties and not _create_delegation_from_form(delegator_user_id=user_id, start_date=start, end_date=end, source_leave_id=leave.id) and not _active_delegation_exists(user_id, start, end):
        flash("Bu kayıt yönetici görevlerini blokluyor; aynı tarih aralığı için vekâlet tanımlamanız önerilir.", "warning")

    _safe_commit("İzin kaydı oluşturuldu.", danger_prefix="İzin kaydı oluşturulamadı")
    return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal", user_id=user_id))


def _handle_leave_balance_post() -> Any:
    if not consume_form_token("hr_management", request.form.get("_form_token"), scope="leave_balance"):
        flash("Bu bakiye formu zaten gönderilmiş ya da oturum form anahtarı yenilenmiş. Sayfayı yenileyip tekrar deneyin.", "warning")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal"))
    if not _model_ready(LeaveBalance):
        flash("İzin bakiyesi tablosu hazır değil.", "warning")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal"))
    user_id = _safe_int(request.form.get("user_id"))
    year = _safe_int(request.form.get("year"), date.today().year)
    leave_type = _safe_text(request.form.get("leave_type"), "yillik_izin")
    if not user_id or not year:
        flash("Personel ve yıl zorunludur.", "danger")
        return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal"))
    row = LeaveBalance.query.filter_by(user_id=user_id, leave_type=leave_type, year=year).first()
    if not row:
        row = LeaveBalance(user_id=user_id, leave_type=leave_type, year=year)
    row.total_days = _safe_float(request.form.get("total_days"), 0.0) or 0.0
    row.carried_over_days = _safe_float(request.form.get("carried_over_days"), 0.0) or 0.0
    row.used_days = _safe_float(request.form.get("used_days"), 0.0) or 0.0
    row.manual_override = True
    row.note = _safe_text(request.form.get("note")) or None
    db.session.add(row)
    _safe_commit("İzin bakiyesi kaydedildi.", danger_prefix="İzin bakiyesi kaydedilemedi")
    return redirect(url_for("main.hr_leave_management", scope=request.form.get("scope") or "personal", user_id=user_id))


def _handle_attendance_post() -> Any:
    action = _safe_text(request.form.get("action"), "create_attendance")
    if action == "create_delegation":
        return _handle_manual_delegation_post()
    if action != "create_attendance":
        flash("Bilinmeyen devamsızlık işlemi.", "warning")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    if not consume_form_token("hr_management", request.form.get("_form_token"), scope="attendance_create"):
        flash("Bu devamsızlık formu zaten gönderilmiş ya da oturum form anahtarı yenilenmiş. Sayfayı yenileyip tekrar deneyin.", "warning")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    if not _model_ready(AttendanceException):
        flash("Devamsızlık tablosu hazır değil.", "warning")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))

    user_id = _safe_int(request.form.get("user_id"))
    record_date = _parse_date(request.form.get("record_date"))
    if not user_id or not record_date:
        flash("Personel ve kayıt tarihi zorunludur.", "danger")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    if _people_outside_caller_scope(user_id):
        return _refuse_out_of_scope("attendance_create", "main.hr_attendance_management")
    if _attendance_overlaps(user_id, record_date):
        flash("Bu personel için aynı tarihte devamsızlık/istisna kaydı var. Mükerrer kayıt engellendi.", "warning")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal", user_id=user_id))
    if _leave_overlaps(user_id, record_date, record_date):
        flash("Bu tarihte izin kaydı bulundu. İzin ve devamsızlık çakışması engellendi.", "warning")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal", user_id=user_id))

    attendance = AttendanceException(
        user_id=user_id,
        period_id=_resolve_period_id_from_form(),
        record_date=record_date,
        exception_type=_safe_text(request.form.get("exception_type"), "devamsizlik"),
        status=_safe_text(request.form.get("status"), "onaylandi"),
        day_fraction=max(0.0, min(1.0, _safe_float(request.form.get("day_fraction"), 1.0) or 1.0)),
        blocks_performance_evaluation=_bool_from_form("blocks_performance_evaluation", True),
        performance_mode=_safe_text(request.form.get("performance_mode"), "partial"),
        blocks_manager_duties=_bool_from_form("blocks_manager_duties", True),
        description=_safe_text(request.form.get("description")) or None,
        approved_by_id=_current_user_id(),
        approved_at=utc_now(),
    )
    db.session.add(attendance)
    db.session.flush()
    if attendance.blocks_manager_duties and not _create_delegation_from_form(delegator_user_id=user_id, start_date=record_date, end_date=record_date, source_attendance_id=attendance.id) and not _active_delegation_exists(user_id, record_date, record_date):
        flash("Bu kayıt yönetici görevlerini blokluyor; aynı tarih için vekâlet tanımlamanız önerilir.", "warning")
    _safe_commit("Devamsızlık/istisna kaydı oluşturuldu.", danger_prefix="Devamsızlık kaydı oluşturulamadı")
    return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal", user_id=user_id))


def _handle_manual_delegation_post() -> Any:
    if not consume_form_token("hr_management", request.form.get("_form_token"), scope="delegation_create"):
        flash("Bu vekâlet formu zaten gönderilmiş ya da oturum form anahtarı yenilenmiş. Sayfayı yenileyip tekrar deneyin.", "warning")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    if not _model_ready(DelegationAssignment):
        flash("Vekâlet tablosu hazır değil.", "warning")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    delegator_user_id = _safe_int(request.form.get("delegator_user_id"))
    delegate_user_id = _safe_int(request.form.get("delegate_user_id"))
    source_leave_id = _safe_int(request.form.get("source_leave_id"))
    source_attendance_id = _safe_int(request.form.get("source_attendance_id"))
    start = _parse_date(request.form.get("start_date"))
    end = _parse_date(request.form.get("end_date"))
    if source_leave_id and _model_ready(PersonnelLeave):
        source = db.session.get(PersonnelLeave, source_leave_id)
        if source:
            delegator_user_id = delegator_user_id or int(source.user_id)
            start = start or source.start_date
            end = end or source.end_date
    if source_attendance_id and _model_ready(AttendanceException):
        source = db.session.get(AttendanceException, source_attendance_id)
        if source:
            delegator_user_id = delegator_user_id or int(source.user_id)
            start = start or source.record_date
            end = end or source.record_date
    if not delegator_user_id or not delegate_user_id or not start or not end:
        flash("Asıl amir/personel, vekil ve tarih aralığı zorunludur. Kaynak kayıt seçildiğinde tarih otomatik alınabilir.", "danger")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    if end < start:
        flash("Vekâlet bitiş tarihi başlangıçtan önce olamaz.", "danger")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    if delegate_user_id == delegator_user_id:
        flash("Vekil personel asıl kişiyle aynı olamaz.", "danger")
        return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))
    if _people_outside_caller_scope(delegator_user_id, delegate_user_id):
        return _refuse_out_of_scope("delegation_create", "main.hr_attendance_management")
    delegation = DelegationAssignment(
        delegator_user_id=delegator_user_id,
        delegate_user_id=delegate_user_id,
        source_leave_id=source_leave_id,
        source_attendance_id=source_attendance_id,
        status=_safe_text(request.form.get("status"), "aktif"),
        start_date=start,
        end_date=end,
        scope_type=_safe_text(request.form.get("scope_type"), "performance"),
        applies_level_1=_bool_from_form("applies_level_1", True),
        applies_level_2=_bool_from_form("applies_level_2", True),
        applies_level_3=_bool_from_form("applies_level_3", False),
        note=_safe_text(request.form.get("note")) or None,
        approved_by_id=_current_user_id(),
        approved_at=utc_now(),
    )
    db.session.add(delegation)
    _safe_commit("Vekâlet kaydı oluşturuldu.", danger_prefix="Vekâlet kaydı oluşturulamadı")
    return redirect(url_for("main.hr_attendance_management", scope=request.form.get("scope") or "personal"))

__all__ = [name for name in globals() if not name.startswith("__")]
