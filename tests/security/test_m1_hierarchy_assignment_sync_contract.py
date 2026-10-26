"""P0 / M-1: hiyerarşi ve personel yazımları aktif dönemin görevlerini dolaylı yoldan yeniden üretemez.

Proje sahibi kararı (M-1, b). Aktif dönem varken gerçek admin olmayan kullanıcının görev üretimini
etkileyen değişikliği bütün olarak reddedilir: 403, hiçbir kullanıcı/görev kaydı değişmez, red
denetim kaydına yazılır. Aktif dönem yoksa R05 hiyerarşi yetkileri aynen kalır. Gerçek admin için
kayıt ve görev senkronu tek işlemdir; senkron başarısızsa ikisi de geri alınır. Kilitli veya
yayımlanmış dönem bu yoldan değişmez (gerçek admin dahil).

Bilinçli R05 değişikliği: R05 sözleşmesi admin olmayan editörün sıradan bir hesabın amir zincirini
değiştirmesine izin verir (``test_p5_non_admin_cannot_change_protected_chain_nor_add_itself``,
"Another evaluator for an ordinary account stays allowed"). Bu hak aktif dönem yokken aynen
korunur (R05 testlerinin ortamında dönem yoktur); aktif dönem varken artık reddedilir.

Gerçek HTTP isteği ve veritabanı önce/sonra karşılaştırmasıyla ölçülür (R05 ortamı: gerçek
formlar, gerçek Excel dosyaları, geçici SQLite).
"""
from __future__ import annotations

from datetime import date

import pytest

from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import (
    SICIL,
    _admin_edit_form,
    _new_user_form,
    _upload,
    _web,
    _xlsx_row,
)

env = _r05.env  # R05 ortamı: tohumlanmış hesaplar, geçici SQLite

NON_ADMIN_EDITORS = ("baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir")
M1_UNIT = "M1 Birim"
MENUS = ("admin_users", "performance_hierarchy_assignments")


# ---------------------------------------------------------------------------
# Ortam: aktif dönem, amir zinciri ve senkronlanmış görevler
# ---------------------------------------------------------------------------
def _period(env, title="M1 Dönem", **fields) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod

    with env.app.app_context():
        row = PerformancePeriod(title=title, period_type="6 Aylık", start_date=date(2026, 1, 1), end_date=date(2026, 6, 30),
                                is_active=fields.pop("is_active", True), is_locked=fields.pop("is_locked", False),
                                results_published=fields.pop("results_published", False), **fields)
        db.session.add(row)
        db.session.commit()
        return row.id


def _setup(env, *, active=True, **period_fields) -> int:
    """plain -> 1. amir plain2; plain kendi biriminde. Aktif dönemin görevleri senkronlanır."""
    from app.extensions import db
    from app.models import RoleMenuDefault, User
    from app.services.performance.assignments import generate_assignments_for_active_period
    from app.services.personnel.categories import assign_user_performance_category

    with env.app.app_context():
        for key in ("plain", "plain2"):
            user = db.session.get(User, env.ids[key])
            assign_user_performance_category(user, "Diğer", db_session=db.session)
        plain = db.session.get(User, env.ids["plain"])
        assert plain is not None
        plain.yonetici_sicil = SICIL["plain2"]
        plain.birim = M1_UNIT
        for role in NON_ADMIN_EDITORS:
            for menu_key in MENUS:
                db.session.add(RoleMenuDefault(role_name=role, menu_key=menu_key, is_visible=True))
        db.session.commit()
    period_id = _period(env, is_active=active, **period_fields)
    if active and not period_fields:
        with env.app.app_context():
            assert generate_assignments_for_active_period(period_id=period_id).get("ok")
    return period_id


def _users(env):
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        return sorted(
            (u.id, u.sicil_no, u.role, bool(u.is_active), u.birim, u.yonetici_sicil, u.ikinci_yonetici_sicil,
             u.ucuncu_yonetici_sicil, u.personnel_category)
            for u in db.session.query(User).all()
        )


def _tasks(env):
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation

    with env.app.app_context():
        assignments = sorted((a.period_id, a.employee_id, a.evaluator_id, a.manager_level, a.status)
                             for a in db.session.query(EvaluationAssignment).all())
        evaluations = sorted((e.period_id, e.employee_id) for e in db.session.query(PerformanceEvaluation).all())
        return assignments, evaluations


def _evaluators_of(env, key, period_id):
    from app.extensions import db
    from app.models import EvaluationAssignment

    with env.app.app_context():
        return sorted((a.evaluator_id, a.manager_level) for a in db.session.query(EvaluationAssignment)
                      .filter_by(period_id=period_id, employee_id=env.ids[key]).all())


def _chain(env, key):
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[key])
        assert user is not None
        return user.yonetici_sicil


def _audits(env, text):
    from app.models import AuditLog

    with env.app.app_context():
        return [row for row in AuditLog.query.filter_by(action="account.change_refused").all() if text in (row.summary or "") + (row.new_data_json or "")]


def _fresh_admin(env):
    """Gerçek admin istemcisi; giriş mesajı oturumdan temizlenir (yalnız işlemin mesajları ölçülür)."""
    client = _web(env, "admin")
    with client.session_transaction() as session:
        session.pop("_flashes", None)
    return client


def _change_requests(env):
    """Görev üretimini etkileyen değişiklik yapan 12 HTTP isteği (11 rota + eski takma ad)."""
    koord = SICIL["koordinator"]
    plain = env.ids["plain"]
    return [
        ("bulk_assign", lambda c: c.post("/performance/hierarchy-settings/bulk-assign",
                                         data={"birim": M1_UNIT, "role": "personel", "bulk_yonetici_sicil": koord})),
        ("hierarchy_assignments", lambda c: c.post("/performance/hierarchy-assignments",
                                                   data={"user_id": plain, "manager_1_id": env.ids["koordinator"]})),
        ("hierarchy_assignments_legacy", lambda c: c.post("/performance/hierarchy-assignments-legacy",
                                                          data={"user_id": plain, "manager_1_id": env.ids["koordinator"]})),
        ("hierarchy_assignment_edit", lambda c: c.post(f"/performance/hierarchy-assignments/{plain}/edit",
                                                       data={"yonetici_sicil": koord})),
        ("hierarchy_assignments_live", lambda c: c.post(f"/performance/hierarchy-assignments-live?user_id={plain}",
                                                        data={"yonetici_sicil": koord})),
        ("hierarchy_auto_build", lambda c: c.post("/performance/hierarchy-settings", data={"action": "auto_build_chains"})),
        ("admin_user_edit", lambda c: c.post(f"/admin/users/{plain}/edit",
                                             data=_admin_edit_form(env, "plain", birim=M1_UNIT, yonetici_sicil=koord))),
        ("personnel_edit", lambda c: c.post(f"/personnel/{plain}/edit", data=_admin_edit_form(env, "plain", birim=M1_UNIT))),
        ("admin_user_create", lambda c: c.post("/admin/users/create", data=_new_user_form("M1NEW1", "personel"))),
        ("personnel_add", lambda c: c.post("/personnel/add", data=_new_user_form("M1NEW2", "personel"))),
        ("personnel_excel_upload", lambda c: _upload(c, "/personnel/excel-upload", [_xlsx_row("M1XL1", "personel")],
                                                     activate_new_users="on")),
        ("admin_user_import", lambda c: _upload(c, "/admin/users/import", [_xlsx_row("M1XL2", "personel")])),
    ]


_REQUEST_NAMES = [
    "bulk_assign", "hierarchy_assignments", "hierarchy_assignments_legacy", "hierarchy_assignment_edit",
    "hierarchy_assignments_live", "hierarchy_auto_build", "admin_user_edit", "personnel_edit", "admin_user_create",
    "personnel_add", "personnel_excel_upload", "admin_user_import",
]


def test_the_request_list_covers_every_named_path(env):
    assert [name for name, _request in _change_requests(env)] == _REQUEST_NAMES


# ---------------------------------------------------------------------------
# Kural 2: aktif dönem varken admin olmayanın değişikliği bütün olarak reddedilir
# ---------------------------------------------------------------------------
# Hiyerarşi ekranlarının menüsü (performance_hierarchy_assignments) sabit menü tavanıyla yalnız
# admine açıktır; rol matrisi satırı da açmaz. Admin olmayan için bu rotaları menü reddeder, M-1
# koruması ikinci katmandır. Toplu atama (menü anahtarı yok) ve admin_users menüsündeki personel
# yazımları admin olmayana açıktır; onları M-1 koruması reddeder.
MENU_CAPPED = {
    "hierarchy_assignments", "hierarchy_assignments_legacy", "hierarchy_assignment_edit",
    "hierarchy_assignments_live", "hierarchy_auto_build",
}


@pytest.mark.parametrize("name", _REQUEST_NAMES)
@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
def test_non_admin_change_with_an_active_period_is_refused_as_a_whole(env, actor, name):
    _setup(env)
    request = dict(_change_requests(env))[name]
    client = _web(env, actor)
    users, tasks = _users(env), _tasks(env)
    assert tasks[0], "senkronlanmış görev bulunmalı"

    response = request(client)

    assert response.status_code == 403, (actor, name, response.status_code)
    assert _users(env) == users, (actor, name)
    assert _tasks(env) == tasks, (actor, name)
    if name not in MENU_CAPPED:
        assert _audits(env, "critical_operation:assignment_generate"), (actor, name)


def test_the_hierarchy_menu_stays_admin_only_even_with_a_role_matrix_row(env):
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.route_support import can_access_menu

    _setup(env)  # rol matrisi satırlarını ekler
    for who, expected in (*((role, False) for role in NON_ADMIN_EDITORS), ("admin", True)):
        with env.app.test_request_context():
            user = db.session.get(User, env.ids[who])
            login_user(user)
            assert can_access_menu(user, "performance_hierarchy_assignments") is expected, who
            assert can_access_menu(user, "admin_users") is True, who


# ---------------------------------------------------------------------------
# Kural 1: aktif dönem yoksa R05 hiyerarşi yetkileri korunur (görev üretilmez)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
def test_without_an_active_period_r05_chain_rights_are_kept(env, actor):
    _setup(env, active=False)
    client = _web(env, actor)
    tasks = _tasks(env)

    bulk = client.post("/performance/hierarchy-settings/bulk-assign",
                       data={"birim": M1_UNIT, "role": "personel", "bulk_yonetici_sicil": SICIL["koordinator"]})
    edit = client.post(f"/admin/users/{env.ids['plain2']}/edit", data=_admin_edit_form(env, "plain2", yonetici_sicil=SICIL["koordinator"]))
    created = client.post("/admin/users/create", data=_new_user_form("M1NEW3", "personel"))

    assert (bulk.status_code, edit.status_code, created.status_code) == (302, 302, 302), actor
    assert _chain(env, "plain") == SICIL["koordinator"] and _chain(env, "plain2") == SICIL["koordinator"], actor
    assert any(row[1] == "M1NEW3" for row in _users(env)), actor
    assert _tasks(env) == tasks, actor
    assert not _audits(env, "critical_operation:assignment_generate"), actor


def test_a_client_supplied_period_never_steers_a_non_admin_sync():
    """Admin olmayan için senkron hedefi yalnız aktif dönemdir; istemcinin gönderdiği dönem yok sayılır."""
    from types import SimpleNamespace
    from unittest import mock

    from app.services.performance import hierarchy_assignment_sync_guard as guard

    actor = SimpleNamespace(id=7, role="grup_baskani", is_authenticated=True)
    with mock.patch.object(guard, "_active_period", return_value=None), \
            mock.patch.object(guard.db.session, "get", side_effect=AssertionError("client period read")):
        plan = guard.begin_hierarchy_change(99, actor=actor)
    assert plan.target is None and plan.actor_is_real_admin is False


def test_the_real_admin_keeps_syncing_an_explicitly_selected_period(env):
    """Gerçek admin için mevcut davranış: seçilen (aktif olmayan, açık) dönem senkronlanır."""
    from app.extensions import db
    from app.models import EvaluationAssignment

    selected = _setup(env, active=False)
    admin = _web(env, "admin")

    response = admin.post("/performance/hierarchy-assignments",
                          data={"user_id": env.ids["plain"], "manager_1_id": env.ids["koordinator"], "period_id": str(selected)})

    assert response.status_code == 302
    assert _chain(env, "plain") == SICIL["koordinator"]
    with env.app.app_context():
        assert db.session.query(EvaluationAssignment).filter_by(period_id=selected, employee_id=env.ids["plain"]).count() >= 1


@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
def test_a_non_admin_save_that_changes_nothing_relevant_is_allowed_without_a_sync(env, actor):
    _setup(env)
    admin = _web(env, "admin")
    form = _admin_edit_form(env, "plain", birim=M1_UNIT, yonetici_sicil=SICIL["plain2"])
    assert admin.post(f"/admin/users/{env.ids['plain']}/edit", data=form).status_code == 302  # alanları normalize eder
    users, tasks = _users(env), _tasks(env)

    response = _web(env, actor).post(f"/admin/users/{env.ids['plain']}/edit", data=form)

    assert response.status_code == 302, actor
    assert _users(env) == users and _tasks(env) == tasks, actor


# ---------------------------------------------------------------------------
# Kural 3: gerçek admin değişikliği yapar; kayıt ve görev senkronu birlikte yazılır
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", [
    "bulk_assign", "hierarchy_assignments", "hierarchy_assignment_edit", "hierarchy_assignments_live", "admin_user_edit",
])
def test_real_admin_chain_change_is_saved_with_its_task_sync(env, name):
    period_id = _setup(env)
    assert _evaluators_of(env, "plain", period_id) == [(env.ids["plain2"], 1)]

    response = dict(_change_requests(env))[name](_web(env, "admin"))

    assert response.status_code == 302, name
    assert _chain(env, "plain") == SICIL["koordinator"], name
    assert (env.ids["koordinator"], 1) in _evaluators_of(env, "plain", period_id), name
    assert (env.ids["plain2"], 1) not in _evaluators_of(env, "plain", period_id), name


@pytest.mark.parametrize("name", ["admin_user_create", "personnel_add", "personnel_excel_upload", "admin_user_import"])
def test_real_admin_new_accounts_are_saved_with_their_task_sync(env, name):
    from app.extensions import db
    from app.models import PerformanceEvaluation, User

    period_id = _setup(env)
    sicil = {"admin_user_create": "M1NEW1", "personnel_add": "M1NEW2", "personnel_excel_upload": "M1XL1", "admin_user_import": "M1XL2"}[name]

    response = dict(_change_requests(env))[name](_web(env, "admin"))

    assert response.status_code == 302, name
    with env.app.app_context():
        user = User.query.filter_by(sicil_no=sicil).one()
        assert db.session.query(PerformanceEvaluation).filter_by(period_id=period_id, employee_id=user.id).count() == 1, name


# ---------------------------------------------------------------------------
# Kural 4: kilitli veya yayımlanmış dönem dolaylı yoldan değişmez (gerçek admin dahil)
# ---------------------------------------------------------------------------
def _freeze(env, period_id, how):
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    with env.app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        if how == "locked":
            period.is_locked = True
        elif how == "results_published":
            period.results_published = True
        else:
            evaluation = db.session.query(PerformanceEvaluation).filter_by(period_id=period_id).first()
            assert evaluation is not None
            evaluation.is_published_to_employee = True
        db.session.commit()


@pytest.mark.parametrize("how", ["locked", "results_published", "evaluation_published"])
@pytest.mark.parametrize("name", ["bulk_assign", "hierarchy_assignment_edit", "admin_user_edit", "admin_user_create"])
def test_a_frozen_period_is_not_changed_indirectly_even_by_the_real_admin(env, name, how):
    period_id = _setup(env)
    _freeze(env, period_id, how)
    users, tasks = _users(env), _tasks(env)

    response = dict(_change_requests(env))[name](_web(env, "admin"))

    assert response.status_code == 302, (name, how)
    assert _users(env) == users, (name, how)
    assert _tasks(env) == tasks, (name, how)
    assert _audits(env, "assignment_sync_frozen_period"), (name, how)


def test_a_frozen_period_refuses_a_non_admin_with_403(env):
    period_id = _setup(env)
    _freeze(env, period_id, "locked")
    users, tasks = _users(env), _tasks(env)

    response = dict(_change_requests(env))["hierarchy_assignment_edit"](_web(env, "mali_musavir"))

    assert response.status_code == 403
    assert _users(env) == users and _tasks(env) == tasks


# ---------------------------------------------------------------------------
# Kural 6: başarısız senkron hiçbir şeyi yazmaz ve başarı olarak gösterilmez
# ---------------------------------------------------------------------------
def test_a_sync_that_reports_failure_writes_nothing_and_is_not_shown_as_success(env, monkeypatch):
    from app.services.performance import hierarchy_assignment_sync_guard as guard

    _setup(env)
    users, tasks = _users(env), _tasks(env)
    monkeypatch.setattr(guard, "generate_assignments_for_active_period", lambda **_kw: {"ok": False, "message": "Sahte senkron hatası"})
    client = _fresh_admin(env)

    response = dict(_change_requests(env))["bulk_assign"](client)

    assert response.status_code == 302
    assert _users(env) == users and _tasks(env) == tasks
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert any(category == "danger" and "kaydedilmedi" in message for category, message in flashes), flashes
    assert not any(category == "success" for category, _message in flashes), flashes


@pytest.mark.parametrize("name", ["hierarchy_assignment_edit", "admin_user_edit", "personnel_excel_upload"])
def test_a_sync_that_fails_midway_rolls_back_tasks_and_hierarchy_together(env, monkeypatch, name):
    """Senkron bütün görev satırlarını yazdıktan sonra, son commit'ten hemen önce çöker."""
    from app.services.performance_v2 import sync_service

    _setup(env)
    users, tasks = _users(env), _tasks(env)

    def _boom(_period):
        raise RuntimeError("sahte senkron çöküşü")

    monkeypatch.setattr(sync_service, "_ensure_assignment_notifications_for_period", _boom)
    client = _fresh_admin(env)

    response = dict(_change_requests(env))[name](client)

    assert response.status_code in {200, 302}, name
    assert _users(env) == users, name
    assert _tasks(env) == tasks, name
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert not any(category == "success" for category, _message in flashes), (name, flashes)
