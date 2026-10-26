"""P0 / M-1 Q4: izin, devamsızlık ve vekâlet kayıtları performans görevlerini yetki dışında değiştiremez.

Onaylı izin/devamsızlık "yönetici görevlerini engeller" ve aktif vekâlet, açık görevin değerlendiricisini
canlı kapsama yenilemesinde (``refresh_assignment_live_coverages``) vekile çevirir. Bu yenilemeyi,
herhangi bir görevi açan her oturum tetikler.

Ölçülen açık (düzeltmeden önce): birim sorumlusu (A birimi) kapsamı dışındaki B birimi amiri için
onaylı izin ve kendisine vekâlet oluşturabiliyordu; sıradan bir personel herhangi bir görevi açınca B
biriminin personelinin değerlendirme görevi A birimi sorumlusuna geçiyordu.

Kural: izin/devamsızlık/vekâlet oluşturma da durum/silme ile aynı kapsama tabidir (kayıttaki her kişi
çağıranın kapsamında; gerçek admin için tüm kurum). Kapsam içindeki normal izin kaydı engellenmez.
Kilitli/yayımlanmış dönemin görevleri ve tamamlanmış görevler vekâletle yeniden yönlendirilmez.
"""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from tests.security import test_hr_leave_attendance_object_scope_contract as _hr
from tests.security.test_hr_leave_attendance_object_scope_contract import _client

app = _hr.app  # HR kapsam ortamı: A/B birim sorumluları, personel, admin; geçici SQLite


def _ids(app):
    from app.models import User

    with app.app_context():
        return {u.sicil_no: u.id for u in User.query.all()}


def _period_with_tasks(app, **fields) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance.assignments import generate_assignments_for_active_period

    with app.app_context():
        period = PerformancePeriod(title="Q4 Dönem", period_type="6 Aylık", start_date=date(2026, 1, 1),
                                   end_date=date(2026, 6, 30), is_active=True, is_locked=False, results_published=False)
        db.session.add(period)
        db.session.commit()
        assert generate_assignments_for_active_period(period_id=period.id).get("ok")
        for name, value in fields.items():
            setattr(period, name, value)
        db.session.commit()
        return period.id


def _task_of(app, period_id, employee_id):
    from app.models import EvaluationAssignment

    with app.app_context():
        row = EvaluationAssignment.query.filter_by(period_id=period_id, employee_id=employee_id, manager_level=1).one()
        return row.id, row.evaluator_id, row.original_evaluator_id, row.assignment_source, row.delegation_id


def _hr_rows(app):
    from app.models import AttendanceException, DelegationAssignment, PersonnelLeave

    with app.app_context():
        return (
            sorted((r.user_id, r.status) for r in PersonnelLeave.query.all()),
            sorted((r.user_id, r.status) for r in AttendanceException.query.all()),
            sorted((r.delegator_user_id, r.delegate_user_id, r.status) for r in DelegationAssignment.query.all()),
        )


def _tokens(client, path):
    html = client.get(path).get_data(as_text=True)
    return re.findall(r'name="_form_token"\s+value="([^"]+)"', html) + re.findall(r'value="([^"]+)"\s+name="_form_token"', html)


def _create_leave(client, user_id, **extra):
    today = date.today().isoformat()
    data = {"action": "create_leave", "_form_token": _tokens(client, "/hr-management/leave")[0], "user_id": str(user_id),
            "start_date": today, "end_date": today, "status": "onaylandi", "blocks_manager_duties": "on", "leave_type": "yillik"}
    data.update(extra)
    return client.post("/hr-management/leave", data=data)


def _create_attendance(client, user_id, record_date=None):
    data = {"action": "create_attendance", "_form_token": _tokens(client, "/hr-management/attendance")[0], "user_id": str(user_id),
            "record_date": record_date or date.today().isoformat(), "status": "onaylandi", "blocks_manager_duties": "on",
            "exception_type": "devamsizlik"}
    return client.post("/hr-management/attendance", data=data)


def _create_delegation(client, delegator_id, delegate_id):
    today = date.today().isoformat()
    data = {"action": "create_delegation", "_form_token": _tokens(client, "/hr-management/attendance")[-1],
            "delegator_user_id": str(delegator_id), "delegate_user_id": str(delegate_id), "start_date": today, "end_date": today,
            "status": "aktif", "scope_type": "performance", "applies_level_1": "on"}
    return client.post("/hr-management/attendance", data=data)


def _refusal_audits(app, reason):
    from app.models import AuditLog

    with app.app_context():
        return [row for row in AuditLog.query.filter_by(action="account.change_refused").all() if reason in (row.summary or "")]


def test_out_of_scope_leave_and_self_delegation_cannot_take_over_another_units_task(app):
    ids = _ids(app)
    period_id = _period_with_tasks(app)
    before_task = _task_of(app, period_id, ids["HRS_EB"])
    assert before_task[1] == ids["HRS_MB"]
    hr_before = _hr_rows(app)
    manager_a = _client(app, "HRS_MA")

    leave = _create_leave(manager_a, ids["HRS_MB"])
    delegation = _create_delegation(manager_a, ids["HRS_MB"], ids["HRS_MA"])
    _client(app, "HRS_EA").get(f"/performance/evaluate/{before_task[0]}")  # canlı kapsama yenilemesini tetikler

    assert leave.status_code == 302 and delegation.status_code == 302
    assert _hr_rows(app) == hr_before
    assert _task_of(app, period_id, ids["HRS_EB"]) == before_task
    assert _refusal_audits(app, "hr_scope:leave_create") and _refusal_audits(app, "hr_scope:delegation_create")


def test_out_of_scope_attendance_is_refused(app):
    ids = _ids(app)
    hr_before = _hr_rows(app)

    response = _create_attendance(_client(app, "HRS_MA"), ids["HRS_MB"])

    assert response.status_code == 302
    assert _hr_rows(app) == hr_before
    assert _refusal_audits(app, "hr_scope:attendance_create")


@pytest.mark.parametrize("delegator, delegate", [("HRS_EA", "HRS_MB"), ("HRS_MB", "HRS_EA")])
def test_a_delegation_with_anyone_outside_the_callers_scope_is_refused(app, delegator, delegate):
    ids = _ids(app)
    hr_before = _hr_rows(app)

    response = _create_delegation(_client(app, "HRS_MA"), ids[delegator], ids[delegate])

    assert response.status_code == 302
    assert _hr_rows(app) == hr_before


def test_normal_leave_inside_the_callers_scope_is_not_blocked(app):
    ids = _ids(app)
    manager_a = _client(app, "HRS_MA")

    own_staff = _create_leave(manager_a, ids["HRS_EA"])
    own = _create_leave(manager_a, ids["HRS_MA"], start_date="2027-02-01", end_date="2027-02-02")
    attendance = _create_attendance(manager_a, ids["HRS_EA"], record_date="2027-03-01")  # izinle çakışmayan gün

    assert (own_staff.status_code, own.status_code, attendance.status_code) == (302, 302, 302)
    leaves, attendances, _delegations = _hr_rows(app)
    assert (ids["HRS_EA"], "onaylandi") in leaves and (ids["HRS_MA"], "onaylandi") in leaves
    assert (ids["HRS_EA"], "onaylandi") in attendances
    assert not _refusal_audits(app, "hr_scope:")


def test_the_real_admin_still_records_leave_and_delegation_and_the_delegate_takes_the_open_task(app):
    ids = _ids(app)
    period_id = _period_with_tasks(app)
    task_id = _task_of(app, period_id, ids["HRS_EB"])[0]
    admin = _client(app, "HRS_AD")

    assert _create_leave(admin, ids["HRS_MB"]).status_code == 302
    assert _create_delegation(admin, ids["HRS_MB"], ids["HRS_EB2"]).status_code == 302
    _client(app, "HRS_EA").get(f"/performance/evaluate/{task_id}")

    _task_id, evaluator, original, source, delegation_id = _task_of(app, period_id, ids["HRS_EB"])
    assert (evaluator, original, source) == (ids["HRS_EB2"], ids["HRS_MB"], "delegated") and delegation_id


@pytest.mark.parametrize("frozen", [{"is_locked": True}, {"results_published": True}])
def test_an_authorised_delegation_never_redirects_a_frozen_periods_tasks(app, frozen):
    ids = _ids(app)
    period_id = _period_with_tasks(app, **frozen)
    before_task = _task_of(app, period_id, ids["HRS_EB"])
    admin = _client(app, "HRS_AD")
    assert _create_leave(admin, ids["HRS_MB"]).status_code == 302
    assert _create_delegation(admin, ids["HRS_MB"], ids["HRS_EB2"]).status_code == 302

    admin.get(f"/performance/task-management?period_id={period_id}")
    _client(app, "HRS_EA").get(f"/performance/evaluate/{before_task[0]}")

    assert _task_of(app, period_id, ids["HRS_EB"]) == before_task


def test_an_authorised_delegation_never_redirects_a_completed_task(app):
    from app.extensions import db
    from app.models import EvaluationAssignment

    ids = _ids(app)
    period_id = _period_with_tasks(app)
    task_id = _task_of(app, period_id, ids["HRS_EB"])[0]
    with app.app_context():
        row = db.session.get(EvaluationAssignment, task_id)
        assert row is not None
        row.status = "tamamlandi"
        row.completed_at = datetime(2026, 7, 1, 10, 0)
        db.session.commit()
    before_task = _task_of(app, period_id, ids["HRS_EB"])
    admin = _client(app, "HRS_AD")
    assert _create_leave(admin, ids["HRS_MB"]).status_code == 302
    assert _create_delegation(admin, ids["HRS_MB"], ids["HRS_EB2"]).status_code == 302

    _client(app, "HRS_EA").get(f"/performance/evaluate/{task_id}")

    assert _task_of(app, period_id, ids["HRS_EB"]) == before_task
