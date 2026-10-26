"""P0: performans dönemi kritik işlemleri için sunucu tarafı yetki sözleşmesi.

Kök neden: dönem rotaları yalnız ``admin_required`` taşıyordu. Bu kapı ``ADMIN_FAMILY_ROLES``
üyeliğine bakar; grup başkanı ve Hukuk Müşaviri (``mali_musavir``) de bu ailededir. Kurumun
menü yetki tanımı (performance_periods, performance_publish) rotalarda uygulanmıyordu; aynı işlemi yapan başka URL'ler de (Faz 5 yayın,
dönem yayın/geri alma, v2.1.6 entegrasyon, v2.1.7 dönem merkezi) açıktı.

Proje sahibi politikası:
- Dönem oluşturma/düzenleme: admin, baskan, baskan_yardimcisi.
- Dönem sonuçlarını yayınlama ve geri alma: admin, baskan.
- Dönem silme: yalnız gerçek admin.
- /settings ve /admin/settings* bu dosyanın kapsamı dışında: önceki R05c kararlarıyla çelişki
  proje sahibi kararını bekliyor (sec/p0-period-settings-authority-2026-10 dalında yerel).
- Açık kurumsal tanımı olmayan kritik durum değişiklikleri (etkinleştirme, kilitleme, görev
  üretimi): varsayımla genişletilmez; yalnız gerçek admin (ayrı karar bulgusu).

Menü izni ve işlem bazındaki sabit rol sınırı birlikte uygulanır; menü izni sabit sınırın
üzerinde yetki vermez. Her negatif test 403 ile birlikte veritabanının değişmediğini doğrular.
Pozitif testler yalnız kaydın gerçekten oluştuğu/değiştiği durumda başarılı sayılır.
"""
from __future__ import annotations

import ast
import inspect
import logging
import os
import tempfile
import textwrap
import uuid
from datetime import date
from pathlib import Path

import pytest

PASSWORD = "P0YetkiSahte1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "p0_period" / "dbs"

ROLES = ["admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu", "personel"]
PERIOD_MANAGERS = {"admin", "baskan", "baskan_yardimcisi"}
PUBLISHERS = {"admin", "baskan"}
REAL_ADMIN = {"admin"}
VALID_PERIOD_FORM = {"title": "Sahte P0 Yeni Dönem", "period_type": "6 Aylık", "start_date": "2027-01-01", "end_date": "2027-06-30"}
EDIT_FORM = {"title": "Sahte P0 Düzenlenmiş Dönem", "period_type": "6 Aylık", "start_date": "2026-01-01", "end_date": "2026-06-30"}


# İsteğe bağlı PostgreSQL koşusu: yalnız localhost'taki geçici, sahte bir test veritabanı.
# Tanımlıysa her test o veritabanının public şemasını sıfırlar; SQLite yerine geçmez, atlanmaz.
PG_URL = os.environ.get("BYS360_P0_PG_URL", "").strip()


@pytest.fixture(autouse=True)
def _logging_enabled():
    """test_17 günlük metnini doğrular; önceki bir testin açık bıraktığı süreç geneli
    ``logging.disable()`` durumuna bağlı kalmaz (test_pr68_f2_upload_log_hygiene ile aynı desen)."""
    previous = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    yield
    logging.disable(previous)


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    if PG_URL:
        assert "@localhost" in PG_URL or "@127.0.0.1" in PG_URL, "BYS360_P0_PG_URL yalnız yerel geçici veritabanı olabilir"
        uri = PG_URL
    else:
        uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-p0-period", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "p0-period-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db

    with flask_app.app_context():
        if PG_URL:
            from sqlalchemy import text

            db.session.remove()
            with db.engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        db.create_all()
    yield flask_app
    if not PG_URL:
        with flask_app.app_context():
            db.session.remove()
            db.engine.dispose()
        Path(uri.removeprefix("sqlite:///")).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Sahte veri ve oturum yardımcıları
# ---------------------------------------------------------------------------
def _client_for(app, role: str, sicil: str | None = None):
    from app.extensions import db
    from app.models import User

    sicil = sicil or f"P0-{role[:12]}"
    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=role, role=role,
                    birim="Sahte Birim", is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302, response.status_code
    return client


def _period(app, title="Sahte P0 Dönem", **fields) -> int:
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        row = PerformancePeriod(title=title, period_type="6 Aylık", start_date=fields.pop("start_date", date(2026, 1, 1)),
                                end_date=fields.pop("end_date", date(2026, 6, 30)), is_active=fields.pop("is_active", False),
                                is_locked=fields.pop("is_locked", False), results_published=fields.pop("results_published", False),
                                **fields)
        db.session.add(row)
        db.session.commit()
        return row.id


def _period_state(app, period_id: int) -> dict | None:
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        row = db.session.get(PerformancePeriod, period_id)
        if row is None:
            return None
        return {"title": row.title, "is_active": bool(row.is_active), "is_locked": bool(row.is_locked),
                "results_published": bool(row.results_published)}


def _state(app, period_id: int) -> dict:
    """Var olması beklenen dönemin durumu."""
    state = _period_state(app, period_id)
    assert state is not None, period_id
    return state


def _period_titles(app) -> list[str]:
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        return sorted(row.title for row in db.session.query(PerformancePeriod).all())


def _assignment_count(app) -> int:
    from app.extensions import db
    from app.models import EvaluationAssignment

    with app.app_context():
        return db.session.query(EvaluationAssignment).count()








def _grant_menu(app, sicil: str, menu_key: str, visible: bool) -> None:
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = db.session.query(User).filter_by(sicil_no=sicil).one()
        db.session.add(UserMenuPermission(user_id=user.id, menu_key=menu_key, is_visible=visible))
        db.session.commit()


def _grant_role_menu(app, role: str, menu_key: str) -> None:
    """Ayarlar > Rol Matrisi satırı: kişisel izinden farklı olarak menü tavanına takılmaz."""
    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault

    with app.app_context():
        db.session.add(RoleMenuDefault(role_name=role, menu_key=menu_key, is_visible=True))
        db.session.commit()


def _seed_publishable_evaluation(app, period_id: int) -> int:
    """Yayına uygun, tamamlanmış ve 70 üstü (üst onay gerektirmeyen) sahte değerlendirme."""
    from app.extensions import db
    from app.models import PerformanceEvaluation, User

    with app.app_context():
        employee = User(sicil_no=f"P0-EMP-{period_id}", email=f"p0-emp-{period_id}@example.gov.tr", ad="Sahte",
                        soyad="Personel", role="personel", birim="Sahte Birim", is_active=True,
                        must_change_password=False, must_set_security_question=False)
        employee.set_password(PASSWORD)
        db.session.add(employee)
        db.session.flush()
        evaluation = PerformanceEvaluation(
            period_id=period_id, employee_id=employee.id, level_1_total_100=85, level_2_total_100=85,
            level_3_total_100=85, final_total_100=85, level_1_completed=True, level_2_completed=True,
            level_3_completed=True, status="tamamlandi", workflow_status="completed", is_published_to_employee=False,
            feedback_request_allowed=False, evaluation_exempted=False, employee_leave_days_in_period=0,
            employee_absence_days_in_period=0, employee_available_days_in_period=180)
        db.session.add(evaluation)
        db.session.commit()
        return evaluation.id


def _evaluation_published(app, evaluation_id: int) -> bool:
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert evaluation is not None
        return bool(evaluation.is_published_to_employee)


def _denied(response) -> bool:
    return response.status_code == 403


# ---------------------------------------------------------------------------
# 1. Dönem oluşturma (geçerli sahte form; yalnız kaydın oluşması başarı sayılır)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ROLES)
def test_01_period_create_matrix(app, role) -> None:
    client = _client_for(app, role)
    before = _period_titles(app)
    response = client.post("/performance/periods/create", data=VALID_PERIOD_FORM)
    after = _period_titles(app)
    if role in PERIOD_MANAGERS:
        assert response.status_code == 302, role
        assert after == sorted([*before, VALID_PERIOD_FORM["title"]]), role
    else:
        assert _denied(response), (role, response.status_code)
        assert after == before, role
        assert client.get("/performance/periods/create").status_code == 403, role
        assert client.get("/performance/periods").status_code == 403, role


# ---------------------------------------------------------------------------
# 2. Dönem sonuçlarını yayınlama (dönem yönetimi ekranı)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ROLES)
def test_02_period_publish_toggle_matrix(app, role) -> None:
    period_id = _period(app)
    client = _client_for(app, role)
    response = client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"})
    state = _state(app, period_id)
    if role in PUBLISHERS:
        assert response.status_code == 302 and state["results_published"] is True, role
    else:
        assert _denied(response), (role, response.status_code)
        assert state["results_published"] is False, role


# ---------------------------------------------------------------------------
# 3. Dönem silme: yalnız gerçek admin
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ROLES)
def test_03_period_delete_matrix(app, role) -> None:
    period_id = _period(app)
    client = _client_for(app, role)
    response = client.post(f"/performance/periods/{period_id}/delete")
    if role in REAL_ADMIN:
        assert response.status_code == 302 and _period_state(app, period_id) is None, role
    else:
        assert _denied(response), (role, response.status_code)
        assert _period_state(app, period_id) is not None, role


# ---------------------------------------------------------------------------
# 4. Düzenleme, etkinleştirme, kilitleme ve görev üretimi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ROLES)
def test_04_period_edit_activate_lock_generate_matrix(app, role) -> None:
    period_id = _period(app)
    client = _client_for(app, role)
    before = _state(app, period_id)

    edit = client.post(f"/performance/periods/{period_id}/edit", data=EDIT_FORM)
    if role in PERIOD_MANAGERS:
        assert edit.status_code == 302 and _state(app, period_id)["title"] == EDIT_FORM["title"], role
    else:
        assert _denied(edit) and _state(app, period_id)["title"] == before["title"], role

    # Açık kurumsal tanımı olmayan kritik durum değişiklikleri: yalnız gerçek admin.
    lock = client.post(f"/performance/periods/{period_id}/toggle-lock", data={"target_state": "true"})
    activate = client.post(f"/performance/periods/{period_id}/toggle-active", data={"target_state": "true"})
    assignments_before = _assignment_count(app)
    generate = client.post("/performance/assignments/generate", data={"period_id": str(period_id)})
    state = _state(app, period_id)
    if role in REAL_ADMIN:
        assert lock.status_code == 302 and state["is_locked"] is True, role
        assert activate.status_code == 302 and state["is_active"] is True, role
        assert generate.status_code == 302, role
    else:
        assert _denied(lock) and _denied(activate) and _denied(generate), role
        assert (state["is_locked"], state["is_active"]) == (before["is_locked"], before["is_active"]), role
        assert _assignment_count(app) == assignments_before, role
        assert client.get("/performance/assignments/generate").status_code == 403, role


# ---------------------------------------------------------------------------
# 5. Başkan Yardımcısı: oluşturur ve düzenler, yayınlamaz ve silmez
# ---------------------------------------------------------------------------
def test_05_deputy_president_manages_but_does_not_publish_or_delete(app) -> None:
    period_id = _period(app)
    client = _client_for(app, "baskan_yardimcisi")
    assert _denied(client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"}))
    assert _denied(client.post(f"/performance/publish/period/{period_id}"))
    assert _denied(client.post(f"/performance/periods/{period_id}/delete"))
    assert _period_state(app, period_id) == {"title": "Sahte P0 Dönem", "is_active": False, "is_locked": False,
                                             "results_published": False}




# ---------------------------------------------------------------------------
# 8. Savunma derinliği: menü izni sabit rol sınırının üzerinde yetki vermez
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["baskan", "grup_baskani", "mali_musavir"])
def test_08_menu_grant_does_not_exceed_fixed_role_policy(app, role) -> None:
    period_id = _period(app)
    sicil = f"P0-GRANT-{role[:8]}"
    client = _client_for(app, role, sicil)
    for key in ("performance_periods", "performance_publish", "performance_task_management"):
        _grant_menu(app, sicil, key, True)
    assert _denied(client.post(f"/performance/periods/{period_id}/delete"))
    assert _denied(client.post(f"/performance/periods/{period_id}/toggle-lock", data={"target_state": "true"}))
    if role not in PUBLISHERS:
        assert _denied(client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"}))
    if role not in PERIOD_MANAGERS:
        assert _denied(client.post("/performance/periods/create", data=VALID_PERIOD_FORM))
        assert VALID_PERIOD_FORM["title"] not in _period_titles(app)
    state = _state(app, period_id)
    assert state == {"title": "Sahte P0 Dönem", "is_active": False, "is_locked": False, "results_published": False}


@pytest.mark.parametrize("role", ["baskan_yardimcisi", "grup_baskani", "mali_musavir"])
def test_08b_role_matrix_grant_does_not_exceed_fixed_role_policy(app, role) -> None:
    """F-01: Ayarlar > Rol Matrisi dönem ve yayın menülerini açsa da grup başkanı ve Hukuk Müşaviri dönem
    oluşturamaz, düzenleyemez, silemez; Başkan Yardımcısı yayınlayamaz ve silemez. Her red 403 ve veri aynı."""
    period_id = _period(app)
    for key in ("performance_periods", "performance_publish", "performance_task_management"):
        _grant_role_menu(app, role, key)
    client = _client_for(app, role, f"P0-RM-{role[:10]}")
    titles_before = _period_titles(app)
    assert _denied(client.post(f"/performance/periods/{period_id}/delete")), role
    assert _denied(client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"})), role
    assert _denied(client.post(f"/performance/periods/{period_id}/toggle-lock", data={"target_state": "true"})), role
    assert _denied(client.post(f"/performance/periods/{period_id}/toggle-active", data={"target_state": "true"})), role
    if role not in PERIOD_MANAGERS:
        assert _denied(client.post("/performance/periods/create", data=VALID_PERIOD_FORM)), role
        assert _denied(client.post(f"/performance/periods/{period_id}/edit", data=EDIT_FORM)), role
        assert _denied(client.get("/performance/periods")), role
        assert _period_titles(app) == titles_before, role
    assert _state(app, period_id) == {"title": "Sahte P0 Dönem", "is_active": False, "is_locked": False,
                                      "results_published": False}, role


# ---------------------------------------------------------------------------
# 9. Canlı kurum tanımı uygulanır: menü kapatılınca yetkili rol de giremez
# ---------------------------------------------------------------------------
def test_09_closing_the_menu_closes_the_route_for_an_authorised_role(app) -> None:
    period_id = _period(app)
    client = _client_for(app, "baskan", "P0-BASKAN-CLOSED")
    _grant_menu(app, "P0-BASKAN-CLOSED", "performance_periods", False)
    _grant_menu(app, "P0-BASKAN-CLOSED", "performance_publish", False)
    assert _denied(client.post("/performance/periods/create", data=VALID_PERIOD_FORM))
    assert VALID_PERIOD_FORM["title"] not in _period_titles(app)
    assert _denied(client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"}))
    assert _state(app, period_id)["results_published"] is False


# ---------------------------------------------------------------------------
# 10. Anonim kullanıcı: giriş sayfasına yönlenir, hiçbir şey değişmez
# ---------------------------------------------------------------------------
def test_10_anonymous_requests_are_redirected_and_change_nothing(app) -> None:
    period_id = _period(app)
    client = app.test_client()
    requests = [
        ("/performance/periods/create", VALID_PERIOD_FORM),
        (f"/performance/periods/{period_id}/toggle-publish", {"target_state": "true"}),
        (f"/performance/periods/{period_id}/delete", {}),
        (f"/performance/periods/{period_id}/toggle-lock", {"target_state": "true"}),
    ]
    for url, data in requests:
        response = client.post(url, data=data)
        redirected = response.status_code in (301, 302) and "/login" in response.headers.get("Location", "")
        assert redirected, (url, response.status_code)
    assert _state(app, period_id)["results_published"] is False
    assert VALID_PERIOD_FORM["title"] not in _period_titles(app)


# ---------------------------------------------------------------------------
# 11. Geçersiz kimlik: başka dönem etkilenmez; yetki kontrolü kayıt aramasından önce
# ---------------------------------------------------------------------------
def test_11_unknown_period_ids_change_no_other_period(app) -> None:
    period_id = _period(app)
    admin = _client_for(app, "admin")
    assert admin.post("/performance/periods/999999/delete").status_code == 302
    assert admin.post("/performance/periods/999999/toggle-publish", data={"target_state": "true"}).status_code == 302
    assert _period_state(app, period_id) == {"title": "Sahte P0 Dönem", "is_active": False, "is_locked": False,
                                             "results_published": False}
    counsel = _client_for(app, "mali_musavir")
    assert _denied(counsel.post("/performance/periods/999999/delete"))
    assert _denied(counsel.post("/performance/periods/999999/toggle-publish", data={"target_state": "true"}))


# ---------------------------------------------------------------------------
# 12-14. Meşru erişim korunur (gerçek kayıt değişikliğiyle)
# ---------------------------------------------------------------------------
def test_12_admin_full_flow_changes_real_records(app) -> None:
    client = _client_for(app, "admin")
    assert client.post("/performance/periods/create", data=VALID_PERIOD_FORM).status_code == 302
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        period_id = db.session.query(PerformancePeriod).filter_by(title=VALID_PERIOD_FORM["title"]).one().id
    assert client.post(f"/performance/periods/{period_id}/edit", data=EDIT_FORM).status_code == 302
    assert client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"}).status_code == 302
    assert _period_state(app, period_id) == {"title": EDIT_FORM["title"], "is_active": False, "is_locked": False,
                                             "results_published": True}
    assert client.post(f"/performance/periods/{period_id}/delete").status_code == 302
    assert _period_state(app, period_id) is None


def test_13_president_creates_edits_and_publishes_but_does_not_delete(app) -> None:
    client = _client_for(app, "baskan")
    assert client.post("/performance/periods/create", data=VALID_PERIOD_FORM).status_code == 302
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        period_id = db.session.query(PerformancePeriod).filter_by(title=VALID_PERIOD_FORM["title"]).one().id
    assert client.post(f"/performance/periods/{period_id}/edit", data=EDIT_FORM).status_code == 302
    assert client.post(f"/performance/periods/{period_id}/toggle-publish", data={"target_state": "true"}).status_code == 302
    assert _state(app, period_id)["results_published"] is True
    assert _denied(client.post(f"/performance/periods/{period_id}/delete"))
    assert _period_state(app, period_id) is not None


def test_14_deputy_president_creates_and_edits(app) -> None:
    client = _client_for(app, "baskan_yardimcisi")
    assert client.post("/performance/periods/create", data=VALID_PERIOD_FORM).status_code == 302
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        period_id = db.session.query(PerformancePeriod).filter_by(title=VALID_PERIOD_FORM["title"]).one().id
    assert client.post(f"/performance/periods/{period_id}/edit", data=EDIT_FORM).status_code == 302
    assert _state(app, period_id)["title"] == EDIT_FORM["title"]


# ---------------------------------------------------------------------------
# Aynı işlemi yapan diğer URL'ler (doğrudan URL denetimi)
# ---------------------------------------------------------------------------
def _publish_state(app, period_id: int, evaluation_id: int) -> tuple[bool, bool]:
    return _state(app, period_id)["results_published"], _evaluation_published(app, evaluation_id)


def _mark_published(app, period_id: int, evaluation_id: int) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    with app.app_context():
        period = db.session.get(PerformancePeriod, period_id)
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert period is not None and evaluation is not None
        period.results_published = True
        evaluation.is_published_to_employee = True
        db.session.commit()


@pytest.mark.parametrize("role", ROLES)
def test_alt_publish_routes_matrix(app, role) -> None:
    """Dönem yayın/geri alma ve Faz 5 toplu yayın: yalnız admin ve başkan.

    Sahte veride yayına uygun kriter puanı kurulamadığı için gerçek kayıt değişikliği yayından
    kaldırma yönünde ölçülür: önceden yayınlanmış dönem ve değerlendirme.
    """
    period_id = _period(app)
    evaluation_id = _seed_publishable_evaluation(app, period_id)
    _mark_published(app, period_id, evaluation_id)
    client = _client_for(app, role)
    if role in PUBLISHERS:
        assert client.post(f"/performance/unpublish/period/{period_id}").status_code == 302, role
        assert _publish_state(app, period_id, evaluation_id) == (False, False), role
        _mark_published(app, period_id, evaluation_id)
        faz5 = client.post("/performance/v2/faz5/publish", data={"period_id": str(period_id), "publish_action": "unpublish"})
        assert faz5.status_code == 302 and _publish_state(app, period_id, evaluation_id) == (False, False), role
    else:
        responses = [
            client.post(f"/performance/unpublish/period/{period_id}"),
            client.post("/performance/v2/faz5/publish", data={"period_id": str(period_id), "publish_action": "unpublish"}),
            client.post("/performance/v2/faz5/publish", data={"period_id": str(period_id), "publish_action": "publish",
                                                              "force_publish": "1"}),
            client.post(f"/performance/publish/period/{period_id}"),
        ]
        assert all(_denied(r) for r in responses), (role, [r.status_code for r in responses])
        assert _publish_state(app, period_id, evaluation_id) == (True, True), role


# Dönem merkezinin kendi operatör listesi grup başkanı ve Hukuk Müşavirini içeriyor; bu iki rol
# merkezde ve v2.1.6 entegrasyonunda dönem oluşturma/bağlama/etkinleştirme kapısından geçiyordu.
# Sahte SQLite veritabanında v2.1.x plan şeması kurulamadığı için bu yoldan gerçek dönem oluşumu
# uçtan uca üretilemiyor; bu testler yetki kapısını (403) ve dönem tablosunun değişmediğini ölçer.
@pytest.mark.parametrize("role", ["grup_baskani", "mali_musavir"])
def test_alt_period_center_and_integration_refuse_period_creation(app, role) -> None:
    client = _client_for(app, role)
    before = _period_titles(app)
    requests = [
        ("/performans/donem-yonetim-merkezi", {
            "action": "prepare_and_link", "category_key": "diger", "plan_name": "Sahte P0 Merkez Planı",
            "period_type": "special", "start_date": "2027-01-01", "end_date": "2027-06-30", "activate_period": "1"}),
        ("/performans/donem-yonetim-merkezi", {"action": "link_period", "plan_key": "sahte-plan", "activate_period": "1"}),
        ("/performans/donem-yonetim-merkezi", {"action": "launch_assignments", "plan_key": "sahte-plan"}),
        ("/performance/v2-1-6-category-period-integration", {"action": "link_period", "plan_key": "sahte-plan"}),
    ]
    for url, data in requests:
        response = client.post(url, data=data)
        assert _denied(response), (role, url, data["action"], response.status_code)
    assert _period_titles(app) == before, role
    assert _assignment_count(app) == 0, role


@pytest.mark.parametrize("role", ROLES)
def test_alt_task_management_generate_is_real_admin_only(app, role) -> None:
    """Görev yönetimi ekranındaki ikinci görev üretimi yolu (ön kontrol override dahil): yalnız gerçek admin.

    Kişi bazlı menü izni de verilir: menü izni sabit rol sınırının üzerinde yetki vermemeli."""
    period_id = _period(app, is_active=True)
    sicil = f"P0-GEN-{role[:10]}"
    client = _client_for(app, role, sicil)
    _grant_menu(app, sicil, "performance_task_management", True)
    _grant_role_menu(app, role, "performance_task_management")
    before = (_assignment_count(app), _state(app, period_id))
    plain = client.post("/performance/task-management/generate", data={"period_id": str(period_id)})
    forced = client.post("/performance/task-management/generate", data={"period_id": str(period_id), "force_generate": "1"})
    if role in REAL_ADMIN:
        assert plain.status_code == 302 and forced.status_code == 302, role
    else:
        assert _denied(plain) and _denied(forced), (role, plain.status_code, forced.status_code)
        assert (_assignment_count(app), _state(app, period_id)) == before, role


@pytest.mark.parametrize("role", ROLES)
def test_alt_single_evaluation_publish_matrix(app, role) -> None:
    """Tek değerlendirme sonucunu yayınlama ve yayından kaldırma: dönem yayınıyla aynı sınır (admin, başkan).

    Rol matrisinden ve kişi bazlı menü izni de verilir: menü izni sabit rol sınırının üzerinde
    yetki vermemeli (rol matrisi izni kişisel izinden farklı olarak menü tavanına takılmaz)."""
    period_id = _period(app)
    evaluation_id = _seed_publishable_evaluation(app, period_id)
    _mark_published(app, period_id, evaluation_id)
    sicil = f"P0-PUB1-{role[:10]}"
    client = _client_for(app, role, sicil)
    _grant_menu(app, sicil, "performance_publish", True)
    _grant_role_menu(app, role, "performance_publish")
    unpublish = client.post(f"/performance/unpublish/evaluation/{evaluation_id}")
    if role in PUBLISHERS:
        assert unpublish.status_code == 302 and _evaluation_published(app, evaluation_id) is False, role
    else:
        publish = client.post(f"/performance/publish/evaluation/{evaluation_id}")
        assert _denied(unpublish) and _denied(publish), (role, unpublish.status_code, publish.status_code)
        assert _publish_state(app, period_id, evaluation_id) == (True, True), role


# ---------------------------------------------------------------------------
# 15 ve 16. Statik sözleşmeler
# ---------------------------------------------------------------------------
def test_15_admin_required_and_admin_family_are_unchanged() -> None:
    from app import route_support

    expected = {"admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir"}
    assert expected == route_support.ADMIN_FAMILY_ROLES
    source = inspect.getsource(route_support)
    assert 'admin_required = _require_role_family(ADMIN_FAMILY_ROLES, "Bu sayfaya erişim yetkiniz bulunmamaktadır.")' in source


_GUARDED_VIEWS = {
    "app/performance/admin_core_routes.py": {
        "performance_periods": ("performance_periods", "period_manage"),
        "performance_period_create": ("performance_periods", "period_manage"),
        "performance_period_edit": ("performance_periods", "period_manage"),
        "performance_period_toggle_publish": ("performance_publish", "period_publish"),
        "performance_period_delete": ("performance_periods", "period_delete"),
        "performance_period_toggle_active": ("performance_periods", "period_activate"),
        "performance_period_toggle_lock": ("performance_periods", "period_lock"),
        "performance_generate_assignments": ("performance_task_management", "assignment_generate"),
    },
    "app/performance/engagement_publish_routes.py": {
        "performance_publish_period": ("performance_publish", "period_publish"),
        "performance_unpublish_period": ("performance_publish", "period_publish"),
        "performance_publish_evaluation": ("performance_publish", "period_publish"),
        "performance_unpublish_evaluation": ("performance_publish", "period_publish"),
    },
    "app/performance/task_routes.py": {
        "performance_task_management_generate": ("performance_task_management", "assignment_generate"),
    },
    "app/performance/v2_routes.py": {
        "performance_v2_phase5_publish": ("performance_publish", "period_publish"),
    },
}


def _decorators(path: str) -> dict[str, list[str]]:
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / path).read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            out[node.name] = [textwrap.dedent(ast.unparse(item)) for item in node.decorator_list]
    return out


@pytest.mark.parametrize("path", sorted(_GUARDED_VIEWS))
def test_16_every_critical_route_has_menu_and_fixed_role_guards(path) -> None:
    decorators = _decorators(path)
    for view, (menu_key, operation) in _GUARDED_VIEWS[path].items():
        found = decorators[view]
        assert "admin_required" in found, (path, view)
        assert f"menu_key_required('{menu_key}')" in found, (path, view, found)
        assert f"critical_operation_required('{operation}')" in found, (path, view, found)


# ---------------------------------------------------------------------------
# 17. Reddedilen kritik işlem denetim kaydına düşer; form değeri, parola veya oturum bilgisi düşmez
# ---------------------------------------------------------------------------
def test_17_refusals_are_audited_without_sensitive_values(app, caplog) -> None:
    import logging

    period_id = _period(app)
    client = _client_for(app, "mali_musavir", "P0-AUDIT-HM")
    secret = "GIZLI-TEST-DEGER-7731"
    with caplog.at_level(logging.WARNING, logger="app.security.critical_operations"):
        assert _denied(client.post(f"/performance/periods/{period_id}/toggle-publish?token=" + secret,
                                   data={"target_state": "true", "password": secret}))
        assert _denied(client.post(f"/performance/periods/{period_id}/delete", data={"note": secret}))
        assert _denied(client.post("/performance/periods/create", data={**VALID_PERIOD_FORM, "title": secret}))
    records = [r.getMessage() for r in caplog.records if r.name == "app.security.critical_operations"]
    assert len(records) == 3, records
    assert any("operation=period_publish" in m and f"path=/performance/periods/{period_id}/toggle-publish" in m
               for m in records), records
    assert any("operation=period_delete" in m for m in records), records
    assert any("operation=period_manage" in m and "role=mali_musavir" in m for m in records), records
    for message in records:
        assert secret not in message and PASSWORD not in message and "session" not in message.lower(), message
    # Kalıcı denetim kaydı: audit_logs (account.change_refused), hassas değer olmadan.
    from app.extensions import db
    from app.models import AuditLog

    with app.app_context():
        rows = db.session.query(AuditLog).filter_by(action="account.change_refused").all()
        stored = " ".join(f"{row.summary} {row.new_data_json}" for row in rows)
    for operation in ("period_publish", "period_delete", "period_manage"):
        assert f"critical_operation:{operation}" in stored, stored
    assert secret not in stored and PASSWORD not in stored
