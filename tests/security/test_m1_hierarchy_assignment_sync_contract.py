"""P0 / M-1: hiyerarşi ve personel yazımları aktif dönemin görevlerini dolaylı yoldan yeniden üretemez.

Proje sahibi kararı (M-1, b). Aktif dönem varken gerçek admin olmayan kullanıcının görev üretimini
etkileyen değişikliği bütün olarak reddedilir: 403, hiçbir kullanıcı/görev kaydı değişmez, red
denetim kaydına yazılır. Aktif dönem yoksa R05 hiyerarşi yetkileri aynen kalır. Gerçek admin için
kayıt ve görev senkronu tek işlemdir; senkron başarısızsa ikisi de geri alınır. Kilitli veya
yayımlanmış dönem bu yoldan değişmez (gerçek admin dahil).

Bilinçli R05 değişikliği: R05 sözleşmesi admin olmayan editörün sıradan hesaplarda amir zinciri,
kimlik/ad/e-posta/unvan/birim/kategori düzenlemesine, hesap oluşturmaya, Excel içe aktarmaya,
pasife/arşive almaya ve silmeye izin verir (ör. ``test_p5_non_admin_cannot_change_protected_chain_nor_add_itself``,
"Another evaluator for an ordinary account stays allowed"). Bu haklar aktif dönem yokken aynen
korunur (R05 testlerinin ortamında dönem yoktur). Aktif dönem varken, görev üretiminin okuduğu bir
alanı (aktif ve admin olmayan personelin parola/güvenlik/fotoğraf/zaman damgası dışındaki her alanı,
birim/üst birim/kategori adları dahil; e-posta ve ad da dönem kapsamı eşleştirmesinde okunur)
değiştiren bu işlemler admin olmayan için artık reddedilir. Görev üretiminin okumadığı değişiklik
(ör. pasif hesapta düzenleme, parola sıfırlama) etkilenmez.

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
        row = PerformancePeriod(title=title, period_type="6 Aylık", start_date=fields.pop("start_date", date(2026, 1, 1)),
                                end_date=fields.pop("end_date", date(2026, 6, 30)),
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

    response = dict(_change_requests(env))["bulk_assign"](_web(env, "mali_musavir"))

    assert response.status_code == 403
    assert _users(env) == users and _tasks(env) == tasks
    assert _audits(env, "critical_operation:assignment_generate")


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


# ---------------------------------------------------------------------------
# Bağımsız inceleme sonrası: aynı kural diğer yollarda (BLOCKER-1, MAJOR-2..4, MINOR-6/7)
# ---------------------------------------------------------------------------
def _set_chain_in_db(env, key, manager_sicil):
    """Senkronlanmamış bir zincir farkı: bir sonraki görev üretimi görevleri değiştirir."""
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[key])
        assert user is not None
        user.yonetici_sicil = manager_sicil
        db.session.commit()


@pytest.mark.parametrize("how", [None, "locked", "results_published"])
@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
def test_faz2_task_generation_is_real_admin_only(env, actor, how):
    period_id = _setup(env)
    if how:
        _freeze(env, period_id, how)
    _set_chain_in_db(env, "plain", SICIL["koordinator"])
    tasks = _tasks(env)

    response = _web(env, actor).post(f"/performance/v2/faz2?period_id={period_id}")

    assert response.status_code == 403, (actor, how)
    assert _tasks(env) == tasks, (actor, how)
    assert _audits(env, "critical_operation:assignment_generate"), (actor, how)


def test_faz2_real_admin_still_generates(env):
    period_id = _setup(env)
    _set_chain_in_db(env, "plain", SICIL["koordinator"])

    response = _web(env, "admin").post(f"/performance/v2/faz2?period_id={period_id}")

    assert response.status_code == 200
    assert (env.ids["koordinator"], 1) in _evaluators_of(env, "plain", period_id)


def _deactivation_requests(env):
    plain = env.ids["plain"]
    return {
        "admin_toggle": lambda c: c.post(f"/admin/users/{plain}/toggle-active", data={"target_state": "0"}),
        "personnel_toggle": lambda c: c.post(f"/personnel/{plain}/toggle-active"),
        "admin_archive": lambda c: c.post(f"/admin/users/{plain}/archive"),
        "bulk_passive": lambda c: c.post("/admin/users/bulk-passive", data={"user_ids": [str(plain)]}),
        "bulk_archive": lambda c: c.post("/admin/users/bulk-archive", data={"user_ids": [str(plain)]}),
    }


_DEACTIVATIONS = ["admin_toggle", "personnel_toggle", "admin_archive", "bulk_passive", "bulk_archive"]


def _is_active(env, key):
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[key])
        return None if user is None else bool(user.is_active)


@pytest.mark.parametrize("name", _DEACTIVATIONS)
@pytest.mark.parametrize("actor", ("grup_baskani", "mali_musavir"))
def test_non_admin_deactivation_with_an_active_period_is_refused(env, actor, name):
    _setup(env)
    users, tasks = _users(env), _tasks(env)

    response = _deactivation_requests(env)[name](_web(env, actor))

    assert response.status_code == 403, (actor, name)
    assert _is_active(env, "plain") is True, (actor, name)
    assert _users(env) == users and _tasks(env) == tasks, (actor, name)
    assert _audits(env, "critical_operation:assignment_generate"), (actor, name)


@pytest.mark.parametrize("name", _DEACTIVATIONS)
def test_real_admin_deactivation_is_saved_with_its_task_sync(env, name):
    period_id = _setup(env)
    before = _evaluators_of(env, "plain", period_id)

    response = _deactivation_requests(env)[name](_web(env, "admin"))

    assert response.status_code == 302, name
    assert _is_active(env, "plain") is False, name
    from app.extensions import db
    from app.models import EvaluationAssignment

    with env.app.app_context():
        statuses = {a.status for a in db.session.query(EvaluationAssignment).filter_by(period_id=period_id, employee_id=env.ids["plain"])}
    assert before and "bekliyor" not in statuses, (name, statuses)


@pytest.mark.parametrize("name", _DEACTIVATIONS)
def test_deactivation_without_an_active_period_keeps_r05_rights(env, name):
    _setup(env, active=False)

    response = _deactivation_requests(env)[name](_web(env, "grup_baskani"))

    assert response.status_code == 302, name
    assert _is_active(env, "plain") is False, name


def _deletion_requests(env):
    plain = env.ids["plain"]
    return {
        "admin_delete": lambda c: c.post(f"/admin/users/{plain}/delete"),
        "personnel_delete": lambda c: c.post(f"/personnel/{plain}/delete"),
        "bulk_delete": lambda c: c.post("/admin/users/bulk-delete", data={"user_ids": [str(plain)]}),
    }


_DELETIONS = ["admin_delete", "personnel_delete", "bulk_delete"]


@pytest.mark.parametrize("name", _DELETIONS)
@pytest.mark.parametrize("actor", ("grup_baskani", "mali_musavir"))
def test_non_admin_deletion_with_an_active_period_is_refused(env, actor, name):
    _setup(env)
    users, tasks = _users(env), _tasks(env)

    response = _deletion_requests(env)[name](_web(env, actor))

    assert response.status_code == 403, (actor, name)
    assert _users(env) == users and _tasks(env) == tasks, (actor, name)


@pytest.mark.parametrize("how", ["locked", "results_published", "evaluation_published", "past_locked"])
@pytest.mark.parametrize("name", _DELETIONS)
def test_a_user_with_rows_in_a_frozen_period_is_deleted_by_nobody(env, name, how):
    from app.extensions import db
    from app.models import PerformancePeriod

    period_id = _setup(env)
    if how == "past_locked":
        with env.app.app_context():
            period = db.session.get(PerformancePeriod, period_id)
            assert period is not None
            period.is_active = False
            period.is_locked = True
            db.session.commit()
    else:
        _freeze(env, period_id, how)
    users, tasks = _users(env), _tasks(env)

    response = _deletion_requests(env)[name](_web(env, "admin"))

    assert response.status_code == 302, (name, how)
    assert _users(env) == users and _tasks(env) == tasks, (name, how)
    assert _audits(env, "assignment_sync_frozen_period"), (name, how)


@pytest.mark.parametrize("name", _DELETIONS)
def test_real_admin_deletion_in_an_open_period_is_saved_with_its_task_sync(env, name):
    period_id = _setup(env)

    response = _deletion_requests(env)[name](_web(env, "admin"))

    assert response.status_code == 302, name
    assert _is_active(env, "plain") is None, name
    assert _evaluators_of(env, "plain", period_id) == [], name
    assert _tasks(env)[0], name  # diğer personelin görevleri yerinde


def test_non_admin_still_deletes_an_account_that_touches_no_period(env):
    from app.extensions import db
    from app.models import User

    _setup(env)
    with env.app.app_context():
        user = User(sicil_no="M1DEL1", email="m1del1@example.gov.tr", ad="Kisi", soyad="M1DEL1", role="personel",
                    birim="R05 Birim", is_active=False, must_change_password=False, must_set_security_question=False)
        user.set_password("M1-Sahte-Parola-9x!")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    tasks = _tasks(env)

    response = _web(env, "grup_baskani").post(f"/admin/users/{user_id}/delete")

    assert response.status_code == 302
    with env.app.app_context():
        assert db.session.get(User, user_id) is None
    assert _tasks(env) == tasks


def _linked_unit(env) -> int:
    from app.extensions import db
    from app.models import OrganizationUnit, User

    with env.app.app_context():
        unit = OrganizationUnit(name=M1_UNIT, unit_type="diger")
        db.session.add(unit)
        db.session.flush()
        plain = db.session.get(User, env.ids["plain"])
        assert plain is not None
        plain.organization_unit_id = unit.id
        db.session.commit()
        return unit.id


def _unit_edit_requests(env, unit_id):
    return {
        "admin_org_unit_edit": lambda c: c.post(f"/admin/org-units/{unit_id}/edit", data={
            "name": "M1 Yeni Birim", "unit_type": "diger", "parent_id": "", "sort_order": "0", "is_active": "on"}),
        "org_unit_edit": lambda c: c.post(f"/org-units/{unit_id}/edit", data={"name": "M1 Yeni Birim", "is_active": "on"}),
    }


def _unit_name(env, unit_id):
    from app.extensions import db
    from app.models import OrganizationUnit

    with env.app.app_context():
        unit = db.session.get(OrganizationUnit, unit_id)
        assert unit is not None
        return unit.name


@pytest.mark.parametrize("name", ["admin_org_unit_edit", "org_unit_edit"])
@pytest.mark.parametrize("actor", ("grup_baskani", "mali_musavir"))
def test_non_admin_unit_edit_that_changes_period_scope_is_refused(env, actor, name):
    _setup(env)
    unit_id = _linked_unit(env)
    users, tasks = _users(env), _tasks(env)

    response = _unit_edit_requests(env, unit_id)[name](_web(env, actor))

    assert response.status_code == 403, (actor, name)
    assert _unit_name(env, unit_id) == M1_UNIT, (actor, name)
    assert _users(env) == users and _tasks(env) == tasks, (actor, name)
    assert _audits(env, "critical_operation:assignment_generate"), (actor, name)


@pytest.mark.parametrize("name", ["admin_org_unit_edit", "org_unit_edit"])
def test_real_admin_unit_edit_is_saved(env, name):
    _setup(env)
    unit_id = _linked_unit(env)

    response = _unit_edit_requests(env, unit_id)[name](_web(env, "admin"))

    assert response.status_code == 302, name
    assert _unit_name(env, unit_id) == "M1 Yeni Birim", name


def _mobile_create(env, sicil):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        admin = db.session.get(User, env.ids["admin"])
        assert admin is not None
        token = _issue_token(admin)
    payload = {"sicil_no": sicil, "ad": "Yeni", "soyad": "Personel", "unvan": "Uzman", "birim": M1_UNIT,
               "ust_birim": "R05 Ust Birim", "yonetici_sicil": SICIL["plain2"], "role": "personel"}
    return env.app.test_client().post("/api/mobile/personnel/create", json=payload, headers={"Authorization": f"Bearer {token}"})


def test_mobile_create_never_changes_a_frozen_period(env):
    period_id = _setup(env)
    _freeze(env, period_id, "locked")
    users, tasks = _users(env), _tasks(env)

    response = _mobile_create(env, "M1MOB1")

    assert response.status_code == 409
    assert _users(env) == users and _tasks(env) == tasks
    assert _audits(env, "assignment_sync:frozen_period:mobile_actor_id=")


def test_mobile_create_by_the_real_admin_is_saved_with_its_task_sync(env):
    from app.extensions import db
    from app.models import PerformanceEvaluation, User

    period_id = _setup(env)

    response = _mobile_create(env, "M1MOB2")

    assert response.status_code == 201
    with env.app.app_context():
        user = User.query.filter_by(sicil_no="M1MOB2").one()
        assert db.session.query(PerformanceEvaluation).filter_by(period_id=period_id, employee_id=user.id).count() == 1


def test_no_sync_message_while_the_scoring_window_is_not_open(env):
    """Puanlama penceresi açılmadan senkron görev yazmaz; senkron yapılmış gibi gösterilmez."""
    _setup(env, active=False)
    _period(env, title="M1 Gelecek Dönem", start_date=date(2026, 7, 1), end_date=date(2026, 12, 31))
    client = _fresh_admin(env)

    response = dict(_change_requests(env))["bulk_assign"](client)

    assert response.status_code == 302
    assert _chain(env, "plain") == SICIL["koordinator"]
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert not any("senkronlandı" in message for _category, message in flashes), flashes


def test_a_real_admin_save_without_a_relevant_change_runs_no_sync(env, monkeypatch):
    from app.services.performance import hierarchy_assignment_sync_guard as guard

    _setup(env)
    admin = _web(env, "admin")
    form = _admin_edit_form(env, "plain", birim=M1_UNIT, yonetici_sicil=SICIL["plain2"])
    assert admin.post(f"/admin/users/{env.ids['plain']}/edit", data=form).status_code == 302
    tasks = _tasks(env)

    def _no_sync(**_kwargs):
        raise AssertionError("görev üretimini etkilemeyen kayıtta senkron çalışmamalı")

    monkeypatch.setattr(guard, "generate_assignments_for_active_period", _no_sync)

    response = admin.post(f"/admin/users/{env.ids['plain']}/edit", data=form)

    assert response.status_code == 302
    assert _tasks(env) == tasks


def _former_publisher(env, period_id, how) -> int:
    """Değerlendirme/görev satırı olmayan, dönemi yayımlamış ve yayın kaydı yazmış pasif eski personel."""
    from app.extensions import db
    from app.models import PerformancePeriod, PerformancePublishLog, User

    with env.app.app_context():
        user = User(sicil_no="M1PUB1", email="m1pub1@example.gov.tr", ad="Kisi", soyad="M1PUB1", role="personel",
                    birim="R05 Birim", is_active=False, must_change_password=False, must_set_security_question=False)
        user.set_password("M1-Sahte-Parola-9x!")
        db.session.add(user)
        db.session.flush()
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        period.published_by_id = user.id
        if how == "locked":
            period.is_locked = True
        else:
            period.results_published = True
        db.session.add(PerformancePublishLog(period_id=period_id, actor_user_id=user.id, action_type="publish"))
        db.session.commit()
        return user.id


def _publication_record(env, period_id):
    from app.extensions import db
    from app.models import PerformancePeriod, PerformancePublishLog

    with env.app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        return period.published_by_id, db.session.query(PerformancePublishLog).filter_by(period_id=period_id).count()


@pytest.mark.parametrize("how", ["locked", "results_published"])
@pytest.mark.parametrize("actor", ("admin", "grup_baskani"))
def test_deleting_a_former_publisher_never_changes_a_frozen_periods_publication_record(env, actor, how):
    from app.extensions import db
    from app.models import User

    period_id = _setup(env)
    user_id = _former_publisher(env, period_id, how)
    record = _publication_record(env, period_id)
    assert record == (user_id, 1)

    response = _web(env, actor).post(f"/admin/users/{user_id}/delete")

    assert response.status_code == 302, (actor, how)
    assert _publication_record(env, period_id) == record, (actor, how)
    with env.app.app_context():
        assert db.session.get(User, user_id) is not None, (actor, how)
    assert _audits(env, "assignment_sync_frozen_period"), (actor, how)


def test_a_bulk_delete_sync_failure_is_reported_as_a_sync_failure(env, monkeypatch):
    from app.services.performance import hierarchy_assignment_sync_guard as guard

    _setup(env)
    users, tasks = _users(env), _tasks(env)
    monkeypatch.setattr(guard, "generate_assignments_for_active_period", lambda **_kw: {"ok": False, "message": "Sahte senkron hatası"})
    client = _fresh_admin(env)

    response = _deletion_requests(env)["bulk_delete"](client)

    assert response.status_code == 302
    assert _users(env) == users and _tasks(env) == tasks
    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])
    assert any(category == "danger" and "görev senkronu tamamlanamadı" in message for category, message in flashes), flashes
    assert not any(category == "success" for category, _message in flashes), flashes


def test_an_unrelated_link_column_with_the_same_name_does_not_block_a_deletion(env):
    """survey_responses.assignment_id anket atamasına bağlıdır; aynı kimlikli kilitli dönem görevi silmeyi engellemez."""
    from app.extensions import db
    from app.models import EvaluationAssignment, Survey, SurveyAssignment, SurveyResponse, User

    period_id = _setup(env)
    _freeze(env, period_id, "locked")
    with env.app.app_context():
        task_id = db.session.query(EvaluationAssignment.id).filter_by(period_id=period_id).first()[0]
        former = User(sicil_no="M1SRV1", email="m1srv1@example.gov.tr", ad="Kisi", soyad="M1SRV1", role="personel",
                      birim="R05 Birim", is_active=False, must_change_password=False, must_set_security_question=False)
        former.set_password("M1-Sahte-Parola-9x!")
        db.session.add(former)
        survey = Survey(title="M1 Anket", created_by_user_id=env.ids["admin"])
        db.session.add(survey)
        db.session.flush()
        db.session.add(SurveyAssignment(id=task_id, survey_id=survey.id, target_type="all"))
        db.session.flush()
        db.session.add(SurveyResponse(survey_id=survey.id, user_id=former.id, assignment_id=task_id))
        db.session.commit()
        former_id = former.id
    tasks = _tasks(env)

    response = _web(env, "admin").post(f"/admin/users/{former_id}/delete")

    assert response.status_code == 302
    with env.app.app_context():
        assert db.session.get(User, former_id) is None
    assert _tasks(env) == tasks
    assert not _audits(env, "assignment_sync_frozen_period")


# ---------------------------------------------------------------------------
# Q3 (proje sahibi kararı): doğrudan görev üretimi/senkronu kilitli veya yayımlanmış dönemi
# değiştiremez; gerçek admin dahil. Yeniden açma yetkisi tanımlanmamıştır.
# ---------------------------------------------------------------------------
def _direct_generation_requests(period_id):
    return {
        "faz2": lambda c: c.post(f"/performance/v2/faz2?period_id={period_id}"),
        "task_management_generate": lambda c: c.post("/performance/task-management/generate",
                                                     data={"period_id": str(period_id), "force_generate": "1"}),
        "assignments_generate": lambda c: c.post("/performance/assignments/generate", data={"period_id": str(period_id)}),
    }


@pytest.mark.parametrize("how", ["locked", "results_published", "evaluation_published"])
@pytest.mark.parametrize("name", ["faz2", "task_management_generate", "assignments_generate"])
def test_direct_generation_never_changes_a_frozen_period_even_for_the_real_admin(env, name, how):
    period_id = _setup(env)
    _freeze(env, period_id, how)
    _set_chain_in_db(env, "plain", SICIL["koordinator"])  # bir sonraki üretim görevleri değiştirirdi
    tasks = _tasks(env)

    response = _direct_generation_requests(period_id)[name](_fresh_admin(env))

    assert response.status_code == 302, (name, how)
    assert _tasks(env) == tasks, (name, how)
    assert _audits(env, f"assignment_generate_frozen_period:{period_id}"), (name, how)


@pytest.mark.parametrize("how", ["locked", "results_published", "evaluation_published"])
def test_the_generator_itself_refuses_a_frozen_period(env, how):
    from app.services.performance.assignments import generate_assignments_for_active_period

    period_id = _setup(env)
    _freeze(env, period_id, how)
    _set_chain_in_db(env, "plain", SICIL["koordinator"])
    tasks = _tasks(env)

    with env.app.app_context():
        result = generate_assignments_for_active_period(period_id=period_id)

    assert result["ok"] is False and result.get("frozen") is True, how
    assert _tasks(env) == tasks, how


@pytest.mark.parametrize("name", ["faz2", "task_management_generate", "assignments_generate"])
def test_direct_generation_still_works_on_an_open_period(env, name):
    period_id = _setup(env)
    _set_chain_in_db(env, "plain", SICIL["koordinator"])

    response = _direct_generation_requests(period_id)[name](_fresh_admin(env))

    assert response.status_code in {200, 302}, name
    assert (env.ids["koordinator"], 1) in _evaluators_of(env, "plain", period_id), name


def test_period_center_launch_never_changes_a_frozen_period(env):
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance.assignments import generate_assignments_for_active_period
    from app.services.performance.v2_1_5_category_period_scope import (
        upsert_category_period_scope_plan,
    )
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )
    from app.services.performance.v2_1_8_period_center_assignment_launch import (
        build_assignment_launch_guard,
    )

    _setup(env, active=False)
    with env.app.app_context():
        plan_key = str(upsert_category_period_scope_plan("diger", "M1 Merkez Planı", "special", "2026-01-01", "2026-06-30", "m1")["plan_key"])
        db.session.commit()
        link = create_or_update_period_from_plan(plan_key)
        db.session.commit()
        period_id = int(link["period_id"])
        assert generate_assignments_for_active_period(period_id=period_id).get("ok")
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        period.is_locked = True
        db.session.commit()
    _set_chain_in_db(env, "plain", SICIL["koordinator"])
    tasks = _tasks(env)

    response = _fresh_admin(env).post("/performans/donem-yonetim-merkezi", data={"action": "launch_assignments", "plan_key": plan_key})

    assert response.status_code == 302
    assert _tasks(env) == tasks
    with env.app.app_context():
        guard = build_assignment_launch_guard(plan_key)
    assert guard["can_launch"] is False and guard["status"] == "donem_kilitli_veya_yayimlanmis"


# ---------------------------------------------------------------------------
# Q3-1 (M-2 sahip kararı): dondurulmuş dönemin görev ve değerlendirme kayıtları temizlenmez
# (gerçek admin dahil); açık ve yayımlanmamış dönemin yetkili temizliği değişmez
# ---------------------------------------------------------------------------
def _period_state(env, period_id):
    from app.extensions import db
    from app.models import AssignmentCoverageLog, PerformanceEvaluation, PerformancePeriod

    with env.app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        evaluations = sorted((e.id, bool(e.is_published_to_employee), e.published_to_employee_at)
                             for e in db.session.query(PerformanceEvaluation).filter_by(period_id=period_id).all())
        logs = db.session.query(AssignmentCoverageLog).filter_by(period_id=period_id).count()
        return (period.is_active, period.is_locked, period.results_published, period.published_at,
                period.published_by_id, evaluations, logs)


def _clear(client, period_id):
    return client.post(f"/performance/task-management/clear/{period_id}")


@pytest.mark.parametrize("how", ["locked", "results_published", "evaluation_published"])
def test_a_frozen_periods_tasks_and_evaluations_are_not_cleared_even_by_the_real_admin(env, how):
    period_id = _setup(env)
    _freeze(env, period_id, how)
    tasks, state = _tasks(env), _period_state(env, period_id)
    assert any(row[0] == period_id for row in tasks[0]) and any(row[0] == period_id for row in tasks[1])

    from app.services.performance.period_freeze import PROTECTED_PERIOD_DELETE_MESSAGE

    client = _fresh_admin(env)
    response = _clear(client, period_id)

    assert response.status_code == 302, how
    assert _tasks(env) == tasks, how
    assert _period_state(env, period_id) == state, how
    assert _audits(env, f"assignment_clear_frozen_period:{period_id}"), how
    with client.session_transaction() as session:
        messages = [message for _category, message in session.get("_flashes", [])]
    assert messages == [PROTECTED_PERIOD_DELETE_MESSAGE], (how, messages)  # a plain refusal, not an error path


def test_the_clear_service_refuses_a_frozen_period_for_any_caller(env):
    from app.extensions import db
    from app.services.performance.task_management_service import clear_period_task_records

    period_id = _setup(env)
    _freeze(env, period_id, "locked")
    tasks = _tasks(env)
    with env.app.app_context():
        with pytest.raises(PermissionError):
            clear_period_task_records(period_id)
        db.session.rollback()
    assert _tasks(env) == tasks


def test_the_real_admin_still_clears_an_open_unpublished_period(env):
    period_id = _setup(env)
    assert any(row[0] == period_id for row in _tasks(env)[0])

    response = _clear(_fresh_admin(env), period_id)

    assignments, evaluations = _tasks(env)
    assert response.status_code == 302
    assert not [row for row in assignments if row[0] == period_id]
    assert not [row for row in evaluations if row[0] == period_id]
    assert not _audits(env, "assignment_clear_frozen_period")


@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
def test_a_non_admin_still_cannot_clear_an_open_period(env, actor):
    period_id = _setup(env)
    tasks = _tasks(env)

    _clear(_web(env, actor), period_id)

    assert _tasks(env) == tasks
