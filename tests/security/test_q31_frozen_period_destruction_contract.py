"""P0 / Q3-1 (sahip kararı a): dondurulmuş dönem hiçbir normal silme veya sıfırlama ile değişmez.

Kilitli, sonuçları yayımlanmış veya personele yayımlanmış değerlendirmesi olan dönem; dönem silme
(``/performance/periods/<id>/delete``), görev temizliği, personel silme ve tümünü sıfırlama
(``/admin/users/reset-all``) ile gerçek admin dahil kimse tarafından değiştirilemez. Ret denetim
kaydına yazılır; görev, değerlendirme, yayın ve dönem kayıtları aynen kalır. Tümünü sıfırlama, tek
bir korunan dönem varken baştan ve bütün olarak reddedilir (kısmi silme yok).

Yayını geri almak korumayı kaldırmaz: yayın ve geri alma işlemleri kalıcı iz bırakır
(``period_has_publication_history``); her canlı geri alma rotasından sonra dönem dondurulmuş
sayılmasa da silinemez. Açık ve hiç yayımlanmamış dönemde mevcut yetkili silme ve sıfırlama aynen
çalışır; admin olmayan yine silemez.

Gerçek HTTP isteği ve veritabanı önce/sonra karşılaştırmasıyla ölçülür (M-1/R05 ortamı, geçici SQLite).
"""
from __future__ import annotations

import pytest

from tests.security import test_m1_hierarchy_assignment_sync_contract as m1
from tests.security.test_m1_hierarchy_assignment_sync_contract import (
    NON_ADMIN_EDITORS,
    _audits,
    _deletion_requests,
    _freeze,
    _fresh_admin,
    _period,
    _setup,
    _tasks,
    _users,
    _web,
)

env = m1.env  # R05 ortamı: tohumlanmış hesaplar, geçici SQLite

FROZEN = ["locked", "results_published", "evaluation_published"]
WITHDRAWALS = ["engagement_bulk", "engagement_single", "v2_bulk", "toggle"]
DESTRUCTIONS = ["period_delete", "assignment_clear", "reset_all", "user_delete"]


# ---------------------------------------------------------------------------
# Ölçüm
# ---------------------------------------------------------------------------
def _table_counts(env):
    """Denetim kaydı dışındaki her tablonun satır sayısı (kısmi silme ölçüsü)."""
    import sqlalchemy as sa

    from app.extensions import db

    counts = {}
    with env.app.app_context():
        for table in db.metadata.sorted_tables:
            if table.name == "audit_logs":
                continue
            try:
                counts[table.name] = db.session.execute(sa.select(sa.func.count()).select_from(table)).scalar()
            except Exception:  # bu ortamda oluşturulmamış tablo
                db.session.rollback()
                counts[table.name] = None
    return counts


def _records(env):
    """Dönemler, değerlendirmeler ve yayın defteri; yayın alanlarıyla birlikte."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod, PerformancePublishLog

    with env.app.app_context():
        periods = sorted((p.id, p.is_active, p.is_locked, p.results_published, p.published_at, p.published_by_id)
                         for p in db.session.query(PerformancePeriod).all())
        evaluations = sorted((e.id, e.period_id, e.employee_id, bool(e.is_published_to_employee),
                              e.published_to_employee_at, e.published_to_employee_by_id)
                             for e in db.session.query(PerformanceEvaluation).all())
        logs = sorted((log.id, log.period_id, log.evaluation_id, log.action_type)
                      for log in db.session.query(PerformancePublishLog).all())
        return periods, evaluations, logs


def _state(env):
    return _users(env), _tasks(env), _records(env), _table_counts(env)


def _flashes(client):
    with client.session_transaction() as session:
        return [message for _category, message in session.get("_flashes", [])]


def _period_flags(env, period_id):
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance.period_freeze import (
        period_has_publication_history,
        period_is_frozen,
    )

    with env.app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        return period_is_frozen(period), period_has_publication_history(period)


def _never_published(env, period_id) -> bool:
    """Hiç yayımlanmamış açık dönem: yayın alanları boş, yayın defteri ve snapshot yok."""
    _periods, evaluations, logs = _records(env)
    period = next(row for row in _periods if row[0] == period_id)
    return (period[2:] == (False, False, None, None) and not [row for row in logs if row[1] == period_id]
            and all(row[3:] == (False, None, None) for row in evaluations if row[1] == period_id))


# ---------------------------------------------------------------------------
# Yayın ve gerçek geri alma rotaları
# ---------------------------------------------------------------------------
def _publish_in_db(env, period_id) -> int:
    """Personele yayın: çekirdek ``publish_evaluation`` işleminin yazdığı alanlar.

    Yayın uygunluk kuralları (tamamlanma, düşük puan onayı) bu sözleşmenin konusu değildir; geri alma
    gerçek HTTP rotasından yapılır.
    """
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    with env.app.app_context():
        now = utc_now()
        period = db.session.get(PerformancePeriod, period_id)
        evaluation = db.session.query(PerformanceEvaluation).filter_by(period_id=period_id).first()
        assert period is not None and evaluation is not None
        evaluation.is_published_to_employee = True
        evaluation.published_to_employee_at = now
        evaluation.published_to_employee_by_id = env.ids["admin"]
        period.results_published = True
        period.published_at = now
        period.published_by_id = env.ids["admin"]
        db.session.commit()
        return evaluation.id


def _publish_and_withdraw(env, period_id, route) -> None:
    client = _fresh_admin(env)
    if route == "toggle":
        on = client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"})
        assert on.status_code == 302 and _period_flags(env, period_id)[0] is True, route
        off = client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "false"})
    else:
        evaluation_id = _publish_in_db(env, period_id)
        if route == "engagement_bulk":
            off = client.post(f"/performance/unpublish/period/{period_id}")
        elif route == "engagement_single":
            off = client.post(f"/performance/unpublish/evaluation/{evaluation_id}")
        else:
            off = client.post("/performance/v2/faz5/publish", data={"period_id": period_id, "publish_action": "unpublish"})
    assert off.status_code == 302, route
    # Geri alma gerçekten oldu: dönem artık dondurulmuş sayılmıyor, ama yayın geçmişi kalıcı.
    assert _period_flags(env, period_id) == (False, True), route


# ---------------------------------------------------------------------------
# Yıkıcı işlemler (gerçek admin)
# ---------------------------------------------------------------------------
def _destroy(client, env, operation, period_id):
    if operation == "period_delete":
        return client.post(f"/performance/periods/{period_id}/delete")
    if operation == "assignment_clear":
        return client.post(f"/performance/task-management/clear/{period_id}")
    if operation == "reset_all":
        return client.post("/admin/users/reset-all")
    return _deletion_requests(env)["admin_delete"](client)


def _expected_refusal(operation, period_id):
    from app.security.critical_operations import FROZEN_PERIOD_DELETE_MESSAGE
    from app.services.performance.period_freeze import (
        PROTECTED_PERIOD_DELETE_MESSAGE,
        RESET_ALL_PROTECTED_MESSAGE,
    )

    if operation == "reset_all":
        return f"reset_all_frozen_period:{period_id}", RESET_ALL_PROTECTED_MESSAGE
    if operation == "user_delete":
        return "assignment_sync_frozen_period", FROZEN_PERIOD_DELETE_MESSAGE
    return f"{operation}_frozen_period:{period_id}", PROTECTED_PERIOD_DELETE_MESSAGE


def _assert_refused_and_unchanged(env, operation, period_id):
    client = _fresh_admin(env)
    before = _state(env)

    response = _destroy(client, env, operation, period_id)

    audit, message = _expected_refusal(operation, period_id)
    assert response.status_code == 302, operation
    after = _state(env)
    assert after[0] == before[0], (operation, "personel")
    assert after[1] == before[1], (operation, "görev/değerlendirme")
    assert after[2] == before[2], (operation, "dönem/yayın")
    assert after[3] == before[3], (operation, "tablo sayıları")
    assert _audits(env, audit), (operation, audit)
    assert _flashes(client) == [message], operation


@pytest.mark.parametrize("operation", ["period_delete", "reset_all"])
@pytest.mark.parametrize("how", FROZEN)
def test_a_frozen_period_is_neither_deleted_nor_reset_even_by_the_real_admin(env, how, operation):
    period_id = _setup(env)
    _freeze(env, period_id, how)
    assert any(row[0] == period_id for row in _tasks(env)[0])

    _assert_refused_and_unchanged(env, operation, period_id)


@pytest.mark.parametrize("operation", DESTRUCTIONS)
@pytest.mark.parametrize("route", WITHDRAWALS)
def test_withdrawing_the_publication_does_not_make_the_period_deletable(env, route, operation):
    period_id = _setup(env)
    _publish_and_withdraw(env, period_id, route)

    _assert_refused_and_unchanged(env, operation, period_id)


def test_reset_all_is_refused_as_a_whole_even_when_other_periods_are_open(env):
    open_id = _setup(env)
    frozen_id = _period(env, title="Q3-1 Kilitli Dönem", is_active=False, is_locked=True)
    assert any(row[0] == open_id for row in _tasks(env)[0])

    _assert_refused_and_unchanged(env, "reset_all", frozen_id)


# ---------------------------------------------------------------------------
# Servis düzeyi ikinci kapı ve kontrol sonrası yayın
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("how", FROZEN + ["withdrawn"])
def test_the_delete_and_reset_services_refuse_for_any_caller(env, how):
    from app.extensions import db
    from app.services.hierarchy_admin_service import reset_all_personnel_and_related_data
    from app.services.performance.period_delete_service import (
        delete_performance_period_with_related_records,
    )
    from app.services.performance.task_management_service import clear_period_task_records

    period_id = _setup(env)
    if how == "withdrawn":
        _publish_and_withdraw(env, period_id, "engagement_bulk")
    else:
        _freeze(env, period_id, how)
    before = _state(env)

    with env.app.app_context():
        for call in (lambda: delete_performance_period_with_related_records(period_id),
                     lambda: clear_period_task_records(period_id),
                     reset_all_personnel_and_related_data):
            with pytest.raises(PermissionError):
                call()
            db.session.rollback()

    assert _state(env) == before, how


@pytest.mark.parametrize("operation", ["period_delete", "assignment_clear", "reset_all"])
def test_a_publication_after_the_route_check_is_refused_by_the_service(env, monkeypatch, operation):
    """Route kontrolünden sonra yayımlanan dönem: servis kilitli satırda yeniden kontrol eder."""
    import app.admin.ops_user_action_services as ops
    import app.performance.admin_core_routes as core
    import app.performance.task_routes as tasks

    period_id = _setup(env)
    _freeze(env, period_id, "results_published")
    monkeypatch.setattr(core, "protected_period_deletion_refusal", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks, "protected_period_deletion_refusal", lambda *args, **kwargs: None)
    real_ids = ops.delete_protected_period_ids
    calls: list[int] = []

    def route_check_passes_once(**kwargs):
        """Rota ön kontrolü dönemi korunmuyor görür; sonraki çağrılar gerçek kontrolü yapar."""
        calls.append(1)
        return [] if len(calls) == 1 else real_ids(**kwargs)

    monkeypatch.setattr(ops, "delete_protected_period_ids", route_check_passes_once)
    client = _fresh_admin(env)
    before = _state(env)

    response = _destroy(client, env, operation, period_id)

    audit, message = _expected_refusal(operation, period_id)
    assert response.status_code == 302, operation
    assert _state(env) == before, operation
    assert _audits(env, audit), operation
    assert _flashes(client) == [message], operation


# ---------------------------------------------------------------------------
# Korunan davranış: açık ve hiç yayımlanmamış dönem, yetki sınırı
# ---------------------------------------------------------------------------
def test_the_real_admin_still_deletes_an_open_never_published_period(env):
    period_id = _setup(env)
    assert _never_published(env, period_id)

    response = _destroy(_fresh_admin(env), env, "period_delete", period_id)

    assert response.status_code == 302
    periods, evaluations, _logs = _records(env)
    assignments, _ = _tasks(env)
    assert not [row for row in periods if row[0] == period_id]
    assert not [row for row in assignments if row[0] == period_id]
    assert not [row for row in evaluations if row[1] == period_id]
    assert not _audits(env, "period_delete_frozen_period")


def test_the_real_admin_still_resets_everything_without_a_protected_period(env):
    period_id = _setup(env)
    assert _never_published(env, period_id)
    users_before = len(_users(env))

    response = _destroy(_fresh_admin(env), env, "reset_all", period_id)

    assert response.status_code == 302
    assignments, evaluations = _tasks(env)
    assert assignments == [] and evaluations == []
    assert len(_users(env)) < users_before
    assert not _audits(env, "reset_all_frozen_period")


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
def test_a_non_admin_can_neither_delete_a_period_nor_reset_all(env, actor, frozen):
    period_id = _setup(env)
    if frozen:
        _freeze(env, period_id, "locked")
    client = _web(env, actor)
    before = _state(env)

    delete = client.post(f"/performance/periods/{period_id}/delete")
    client.post("/admin/users/reset-all")

    assert delete.status_code == 403, actor
    assert _state(env) == before, (actor, frozen)


def test_the_publish_toggle_leaves_the_same_trace_as_the_core_publish(env):
    from app.extensions import db
    from app.models import PerformancePeriod

    period_id = _setup(env)
    client = _fresh_admin(env)

    client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"})
    with env.app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        assert period.results_published is True and period.published_at is not None
        assert period.published_by_id == env.ids["admin"]
    client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "false"})
    with env.app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        assert period.results_published is False and period.published_at is None
        assert period.published_by_id == env.ids["admin"]
    assert _period_flags(env, period_id) == (False, True)


def _leave_only_a_legacy_trace(env, period_id, trace) -> None:
    """Önceki yayının tek izi: aktörsüz eski bir geri alma veya geçmiş aktarımı (dönem alanları boş)."""
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePublishLog, PerformanceResultSnapshot

    with env.app.app_context():
        evaluation = db.session.query(PerformanceEvaluation).filter_by(period_id=period_id).first()
        assert evaluation is not None
        if trace == "publish_log":
            db.session.add(PerformancePublishLog(period_id=period_id, evaluation_id=evaluation.id,
                                                 employee_id=evaluation.employee_id, actor_user_id=env.ids["admin"],
                                                 action_type="unpublish", note="Q3-1 eski geri alma izi"))
        elif trace == "snapshot":
            db.session.add(PerformanceResultSnapshot(period_id=period_id, evaluation_id=evaluation.id,
                                                     employee_id=evaluation.employee_id, employee_name_snapshot="Q3-1",
                                                     sicil_no_snapshot="Q31", published_at=utc_now()))
        else:  # değerlendirme izi: yayın bayrağı kalkmış, yayımlayan kalmış (ör. düşük puan onarımı)
            evaluation.published_to_employee_by_id = env.ids["admin"]
        db.session.commit()


@pytest.mark.parametrize("operation", ["period_delete", "assignment_clear", "reset_all"])
@pytest.mark.parametrize("trace", ["publish_log", "snapshot", "evaluation_trace"])
def test_a_period_whose_only_publication_trace_is_legacy_is_still_protected(env, trace, operation):
    period_id = _setup(env)
    _leave_only_a_legacy_trace(env, period_id, trace)
    assert _period_flags(env, period_id) == (False, True), trace

    _assert_refused_and_unchanged(env, operation, period_id)
