"""P0 / D1 (sahip kararı): korunan dönem plan yeniden bağlamayla değişmez.

v2.1.6 (``/performance/v2-1-6-category-period-integration``) ve v2.1.7 (dönem yönetim merkezi:
``link_period``, ``prepare_and_link``, ``prepare_link_precheck``) mevcut dönemi plana yeniden bağlarken
başlık, tür, tarih ve kapsam alanlarını yeniden yazıyor, ``is_locked`` ve ``results_published``
alanlarını da sessizce False yapıyordu. Kanıt (``17f9cdb3``): gerçek admin kilitli ya da iz bırakmadan
yayımlanmış bir dönemi bu yoldan korumasız bırakıp değerlendirmeleriyle silebiliyordu; yeniden
bağlama dönemi görev üretimine de yeniden açıyordu. Başkan yayını aynı yoldan geri alabiliyordu.

Kural: kilitli, sonuçları yayımlanmış, personele yayımlanmış değerlendirmesi olan ya da yayın geçmişi
bulunan dönem kimse tarafından yeniden bağlanamaz (gerçek admin dahil). Ret açık mesaj ve denetim
kaydıyla, hiçbir kısmi değişiklik olmadan (plan kaydı dahil) yapılır. Yeniden bağlama kilit ve yayın
durumuna hiçbir zaman dokunmaz. F-A rol sınırları aynen kalır. Açık ve hiç yayımlanmamış dönemin
yetkili yeniden bağlanması çalışır.

Bu sözleşme, kalıcı geçmiş kaydı olmayan (izsiz) eski yayın ve kilit geçmişini çözmez; o konu A1/C1'de.

Gerçek HTTP isteği ve veritabanının tamamının önce/sonra karşılaştırmasıyla ölçülür (P0 ortamı).
"""
from __future__ import annotations

import pytest

from tests.security import test_p0_period_authority_contract as _p0
from tests.security.test_p0_period_authority_contract import (
    CENTER_URL,
    FA_PLAN,
    INTEGRATION_URL,
    _client_for,
    _grant_role_menu,
    _linked_plan_period,
    _relink_requests,
)

app = _p0.app  # P0 ortamı: geçici SQLite (veya yerel PostgreSQL), gerçek uygulama

PROTECTED_STATES = ["locked", "results_published", "evaluation_published", "publication_history"]
UNLOCKED_PROTECTED_STATES = ["results_published", "evaluation_published", "publication_history"]


# ---------------------------------------------------------------------------
# Ölçüm
# ---------------------------------------------------------------------------
def _database(app) -> dict:
    """Denetim kaydı dışındaki her tablonun tüm satırları (plan ve entegrasyon tabloları dahil)."""
    import sqlalchemy as sa

    from app.extensions import db

    with app.app_context():
        tables = sorted(sa.inspect(db.engine).get_table_names())
        dump = {}
        for name in tables:
            if name == "audit_logs":
                continue
            table = sa.Table(name, sa.MetaData(), autoload_with=db.engine)
            rows = db.session.execute(sa.select(table)).mappings().all()
            dump[name] = sorted(repr(sorted(dict(row).items())) for row in rows)
        return dump


def _diff(before: dict, after: dict) -> dict:
    return {name: (len(before.get(name, [])), len(after.get(name, [])))
            for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)}


def _audits(app, text: str) -> list:
    from app.models import AuditLog

    with app.app_context():
        return [row.id for row in AuditLog.query.filter_by(action="account.change_refused").all()
                if text in (row.new_data_json or "") + (row.summary or "")]


def _flashes(client) -> list[str]:
    with client.session_transaction() as session:
        return [message for _category, message in session.get("_flashes", [])]


def _fresh(app, role, sicil=None):
    client = _client_for(app, role, sicil)
    with client.session_transaction() as session:
        session.pop("_flashes", None)
    return client


def _period_fields(app, period_id: int) -> dict:
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None
        return {column.key: getattr(period, column.key) for column in PerformancePeriod.__table__.columns}


# ---------------------------------------------------------------------------
# Ortam: plana bağlı dönem, görev ve değerlendirme, istenen koruma durumu
# ---------------------------------------------------------------------------
def _protected_linked_period(app, state: str) -> tuple[str, int]:
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod, User

    plan_key, period_id = _linked_plan_period(app, is_locked=state == "locked",
                                              results_published=state == "results_published")
    with app.app_context():
        employee = User(sicil_no="P0-D1-EMP", email="p0-d1-emp@example.gov.tr", ad="Sahte", soyad="Calisan",
                        role="personel", is_active=True)
        evaluator = User(sicil_no="P0-D1-MGR", email="p0-d1-mgr@example.gov.tr", ad="Sahte", soyad="Amir",
                         role="personel", is_active=True)
        for user in (employee, evaluator):
            user.set_password("Sahte-D1-Parola-1!")
        db.session.add_all([employee, evaluator])
        db.session.flush()
        evaluation = PerformanceEvaluation(period_id=period_id, employee_id=employee.id, final_total_100=82.5,
                                           level_1_completed=True, status="tamamlandi",
                                           is_published_to_employee=state == "evaluation_published")
        db.session.add(evaluation)
        db.session.add(EvaluationAssignment(period_id=period_id, employee_id=employee.id, evaluator_id=evaluator.id,
                                            manager_level=1, status="tamamlandi"))
        if state == "publication_history":
            period = db.session.get(PerformancePeriod, period_id)
            assert period is not None
            period.published_at = utc_now()  # yayımlanmış ve geri alınmış: bayraklar kapalı, iz var
            period.published_by_id = evaluator.id
        db.session.commit()
    return plan_key, period_id


def _relink(plan_key: str, kind: str) -> tuple[str, dict]:
    requests = dict((name, request) for name, request in zip(
        ["integration_link", "integration_default", "center_link", "center_prepare_and_link", "center_prepare_link_precheck"],
        _relink_requests(plan_key), strict=True))
    url, data = requests[kind]
    if kind.startswith("center_prepare"):
        data = {**data, "plan_name": "Sahte FA Planı (yeniden adlandırılmak istendi)", "activate_period": "1"}
    return url, data


RELINKS = ["integration_link", "integration_default", "center_link", "center_prepare_and_link", "center_prepare_link_precheck"]


def _assert_refused_and_unchanged(app, client, period_id: int, url: str, data: dict) -> None:
    before = _database(app)
    response = client.post(url, data=data)
    after = _database(app)

    assert response.status_code == 302, (url, data, response.status_code)
    assert _diff(before, after) == {}, (url, data)
    assert _audits(app, f"plan_relink_frozen_period:{period_id}"), (url, data)
    from app.services.performance.period_freeze import PROTECTED_PERIOD_RELINK_MESSAGE

    assert _flashes(client) == [PROTECTED_PERIOD_RELINK_MESSAGE], (url, data)


# ---------------------------------------------------------------------------
# Korunan dönem: gerçek admin ve Başkan
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", RELINKS)
@pytest.mark.parametrize("state", PROTECTED_STATES)
def test_the_real_admin_never_relinks_a_protected_period(app, state, kind):
    plan_key, period_id = _protected_linked_period(app, state)
    admin = _fresh(app, "admin")

    _assert_refused_and_unchanged(app, admin, period_id, *_relink(plan_key, kind))


@pytest.mark.parametrize("kind", ["integration_link", "integration_default"])
@pytest.mark.parametrize("state", UNLOCKED_PROTECTED_STATES)
def test_the_president_never_unpublishes_or_relinks_a_protected_period(app, state, kind):
    plan_key, period_id = _protected_linked_period(app, state)
    president = _fresh(app, "baskan")

    _assert_refused_and_unchanged(app, president, period_id, *_relink(plan_key, kind))


@pytest.mark.parametrize("kind", ["center_link", "center_prepare_and_link"])
@pytest.mark.parametrize("role", ["baskan", "baskan_yardimcisi"])
def test_period_managers_never_relink_a_protected_period_from_the_center(app, role, kind):
    plan_key, period_id = _protected_linked_period(app, "results_published")
    for menu_key in ("performance_periods", "performance_publish", "performance_period_management_center"):
        _grant_role_menu(app, role, menu_key)
    client = _fresh(app, role)
    before = _database(app)
    url, data = _relink(plan_key, kind)

    response = client.post(url, data=data)

    assert _diff(before, _database(app)) == {}, (role, kind, response.status_code)
    assert response.status_code in {302, 403}, (role, kind, response.status_code)


def test_the_president_still_cannot_relink_a_locked_period(app):
    """F-A rol sınırı aynen kalır: kilit hakkı olmayan Başkan için 403."""
    plan_key, period_id = _protected_linked_period(app, "locked")
    president = _fresh(app, "baskan")
    before = _database(app)

    response = president.post(INTEGRATION_URL, data={"action": "link_period", "plan_key": plan_key})

    assert response.status_code == 403
    assert _diff(before, _database(app)) == {}


# ---------------------------------------------------------------------------
# Servis ikinci kapısı, kontrol sonrası değişiklik, görev üretimi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("state", PROTECTED_STATES)
def test_the_relink_service_refuses_a_protected_period_for_any_caller(app, state):
    from app.extensions import db
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    plan_key, period_id = _protected_linked_period(app, state)
    before = _database(app)

    with app.app_context():
        with pytest.raises(PermissionError):
            create_or_update_period_from_plan(plan_key, activate_period=True)
        db.session.rollback()

    assert _diff(before, _database(app)) == {}, state


@pytest.mark.parametrize("kind", ["center_prepare_and_link", "center_prepare_link_precheck"])
def test_the_plan_written_before_a_refused_link_is_rolled_back_with_it(app, monkeypatch, kind):
    """Merkez planı önce yazar, sonra bağlar: ret kilitli satırda verilir ve aynı işlemde yazılan plan
    kaydı da geri alınır. Arada hiçbir commit olmadığı ölçülür (kilit yazıma kadar tutulur)."""
    from app.extensions import db
    from app.services.performance import v2_1_6_category_period_integration as integration

    plan_key, period_id = _protected_linked_period(app, "locked")
    events: list[str] = []
    real_commit, real_check = db.session.commit, integration.ensure_plan_relink_allowed

    def check(key):
        events.append("check")
        return real_check(key)

    def commit():
        events.append("commit")
        return real_commit()

    admin = _fresh(app, "admin")
    monkeypatch.setattr(integration, "ensure_plan_relink_allowed", check)
    monkeypatch.setattr(db.session, "commit", commit)

    _assert_refused_and_unchanged(app, admin, period_id, *_relink(plan_key, kind))
    # Planın yazıldığı işlem ret anına kadar commit edilmedi; tek commit, rollback sonrası denetim kaydıdır.
    assert events.count("check") == 1 and events[events.index("check"):] == ["check", "commit"], events


@pytest.mark.parametrize("state", PROTECTED_STATES)
def test_a_refused_relink_keeps_every_protection_of_the_period(app, state):
    """Reddedilen yeniden bağlamadan sonra dönem korunmaya devam eder: silinemez; dondurulmuş dönem
    görev üretimine de kapalı kalır. (Yayını geri alınmış dönemde düzeltme için görev üretimi açık
    kalır; bu, onaylanmış mevcut davranıştır ve D1 bunu değiştirmez.)"""
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance.assignments import generate_assignments_for_active_period
    from app.services.performance.period_freeze import period_is_delete_protected, period_is_frozen

    plan_key, period_id = _protected_linked_period(app, state)
    admin = _fresh(app, "admin")
    admin.post(INTEGRATION_URL, data={"action": "link_period", "plan_key": plan_key})
    before = _database(app)

    with app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        assert period is not None and period_is_delete_protected(period), state
        frozen = period_is_frozen(period)
        if frozen:
            result = generate_assignments_for_active_period(period_id=period_id)
            assert not result.get("ok"), (state, result)
        db.session.rollback()

    assert frozen is (state != "publication_history"), state
    assert _diff(before, _database(app)) == {}, state
    assert admin.post(f"/performance/periods/{period_id}/delete").status_code == 302
    assert _diff(before, _database(app)) == {}, state


# ---------------------------------------------------------------------------
# Korunan davranış: açık, hiç yayımlanmamış dönem
# ---------------------------------------------------------------------------
OPEN_RELINKERS = [("admin", "integration_link"), ("baskan", "integration_link"), ("baskan_yardimcisi", "integration_link"),
                  ("admin", "center_link"), ("admin", "center_prepare_and_link")]  # merkez: F-A gereği yalnız gerçek admin


@pytest.mark.parametrize(("role", "kind"), OPEN_RELINKERS)
def test_an_open_unpublished_period_is_still_relinked_by_its_managers(app, role, kind):
    plan_key, period_id = _linked_plan_period(app, is_locked=False, results_published=False)
    for menu_key in ("performance_periods", "performance_period_management_center"):
        _grant_role_menu(app, role, menu_key)
    client = _fresh(app, role)
    url, data = _relink(plan_key, kind)
    data = {key: value for key, value in data.items() if key != "activate_period"}

    response = client.post(url, data=data)

    fields = _period_fields(app, period_id)
    assert response.status_code == 302, (role, kind)
    assert (fields["is_locked"], fields["results_published"]) == (False, False)
    assert not _audits(app, "plan_relink_frozen_period")
    if kind == "center_prepare_and_link" and role == "admin":
        assert fields["title"] == "Sahte FA Planı (yeniden adlandırılmak istendi)"


def test_relinking_never_writes_lock_or_publish_even_for_an_open_period(app, monkeypatch):
    """Yeniden bağlama kilit/yayın alanlarına hiç yazmaz (eski sessiz sıfırlama kaldırıldı)."""
    from app.services.performance import v2_1_6_category_period_integration as integration

    plan_key, period_id = _linked_plan_period(app, is_locked=False, results_published=False)
    written: list[str] = []
    real_set = integration._set_if_has

    def tracking_set(obj, attr, value):
        written.append(attr)
        return real_set(obj, attr, value)

    monkeypatch.setattr(integration, "_set_if_has", tracking_set)
    admin = _fresh(app, "admin")

    assert admin.post(INTEGRATION_URL, data={"action": "link_period", "plan_key": plan_key}).status_code == 302
    assert "is_locked" not in written and "results_published" not in written, written
    assert FA_PLAN  # aynı plan


def test_a_prepared_plan_that_cannot_be_linked_is_still_saved(app):
    """Plan, dönem bağlamasıyla aynı işlemde yazılır; bağlama başarısız olursa (geçersiz tarih) plan
    önceki gibi kaydedilir, dönem oluşmaz."""
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.services.performance.v2_1_5_category_period_scope import resolve_plan_key
    from app.services.performance.v2_1_6_category_period_integration import get_scope_plan

    admin = _fresh(app, "admin")
    _linked_plan_period(app, is_locked=False, results_published=False)  # plan şemasını hazırlar
    data = {"action": "prepare_and_link", "plan_name": "Sahte Ters Tarihli Plan", "category_key": "diger",
            "period_type": "special", "start_date": "2027-06-30", "end_date": "2027-01-01"}
    with app.app_context():
        periods = db.session.query(PerformancePeriod).count()

    assert admin.post(CENTER_URL, data=data).status_code == 302

    with app.app_context():
        plan = get_scope_plan(resolve_plan_key("diger", "special", "2027-06-30", "2027-01-01"))
        assert plan is not None and plan["plan_name"] == "Sahte Ters Tarihli Plan"
        assert db.session.query(PerformancePeriod).count() == periods
