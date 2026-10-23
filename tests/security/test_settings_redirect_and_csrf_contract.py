"""PR #93 bağımsız inceleme bulgusu (BLOCKER-1): meşru /settings işlemi 403 ile bitmemeli.

Kök neden: ``settings_page`` dört adrese bağlı. Flask decorator'ları aşağıdan yukarı uyguladığı için
endpoint'in ilk kaydı ``/admin/settings/security`` oluyordu ve ``url_for("main.settings_page")`` bu
adresi üretiyordu. PR #93 ``/admin/settings*`` adreslerini yalnız gerçek admin'e kapatınca Başkan,
Başkan Yardımcısı, Grup Başkanı ve Mali Müşavir'in R05c / K5q / B1F1 işlemleri kaydediliyor, ardından
yönlendirme 403 veriyor ve her işlem yanlış bir ``settings_admin_path`` ret kaydı yazıyordu.
Mevcut süreklilik testi yalnız ``302`` kontrol ettiği için bu görünmüyordu.

Bu sözleşme:
1. Gerçek yönlendirme hedefini (``/settings``) ve takip edilen HTTP sonucunu (200) doğrular.
2. Meşru işlemin hiçbir ret kaydı (``account.change_refused``) üretmediğini doğrular.
3. CSRF açıkken: admin kaydı ve geri alması kabul edilir; token'sız istek hiçbir şey yazmaz; admin
   olmayan her rolün sistem ayarı kaydı, geri alması ve ``/admin/settings*`` isteği 403 alır ve
   veritabanı değişmez; Başkan'ın R05c işlemi çalışmaya devam eder.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

PASSWORD = "AyarYonlendirmeTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "settings_redirect_csrf" / "dbs"
NON_ADMIN_MANAGERS = ["baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir"]
OUTSIDE_ADMIN_FAMILY = ["koordinator", "birim_sorumlusu", "personel"]
ADMIN_PATHS = ["/admin/settings", "/admin/settings/performance", "/admin/settings/security"]
WATCHED = ("security.failed_login_threshold", "attachments.allowed_extensions", "logs.enable_audit_log",
           "general.maintenance_mode")
SYSTEM_FORM = {
    "form_action": "save_system_foundation",
    "system__security__failed_login_threshold": "99",
    "system__attachments__allowed_extensions": "pdf,exe",
}
_CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')


def _make_app(monkeypatch, *, csrf: bool):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-settings-redirect", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "true" if csrf else "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "settings-redirect-test-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=csrf, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.services.settings_service import ensure_settings_phase1_seeded

    with flask_app.app_context():
        db.create_all()
        ensure_settings_phase1_seeded()
    return flask_app, db_file


def _dispose(flask_app, db_file) -> None:
    from app.extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


@pytest.fixture
def app(monkeypatch):
    flask_app, db_file = _make_app(monkeypatch, csrf=False)
    yield flask_app
    _dispose(flask_app, db_file)


@pytest.fixture
def csrf_app(monkeypatch):
    flask_app, db_file = _make_app(monkeypatch, csrf=True)
    yield flask_app
    _dispose(flask_app, db_file)


def _user(app, sicil: str, role: str) -> int:
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=role, role=role,
                    is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _csrf_token(client, path: str) -> str:
    match = _CSRF_RE.search(client.get(path).get_data(as_text=True))
    assert match, path
    return match.group(1)


def _login(app, sicil: str, *, csrf: bool = False):
    client = app.test_client()
    data = {"sicil_or_email": sicil, "password": PASSWORD}
    if csrf:
        data["csrf_token"] = _csrf_token(client, "/login")
    assert client.post("/login", data=data).status_code == 302
    return client


def _values(app) -> dict[str, str | None]:
    from app.extensions import db
    from app.models import SystemSetting

    with app.app_context():
        rows = {row.setting_key: row.value_text for row in db.session.query(SystemSetting).all()}
    return {key: rows.get(key) for key in WATCHED}


def _system_change_logs(app) -> int:
    from app.extensions import db
    from app.models import SettingsChangeLog

    with app.app_context():
        return db.session.query(SettingsChangeLog).filter_by(change_scope="system_settings").count()


def _latest_system_log_id(app) -> int:
    from app.extensions import db
    from app.models import SettingsChangeLog

    with app.app_context():
        row = (db.session.query(SettingsChangeLog).filter_by(change_scope="system_settings", is_rollback=False)
               .order_by(SettingsChangeLog.id.desc()).first())
        assert row is not None
        return row.id


def _refusals(app) -> list[str]:
    from app.extensions import db
    from app.models import AuditLog

    with app.app_context():
        return [row.summary or "" for row in db.session.query(AuditLog).filter_by(action="account.change_refused")]


def _personel_role_keys(app) -> set[str]:
    from app.services.settings_service import get_role_default_menu_keys

    with app.app_context():
        return set(get_role_default_menu_keys("personel"))


def _user_rows(app, user_id: int) -> dict[str, bool]:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        return {row.menu_key: bool(row.is_visible) for row in db.session.query(UserMenuPermission).filter_by(user_id=user_id)}


def _assert_lands_on_settings(client, response) -> None:
    assert response.status_code == 302, response.status_code
    location = response.headers.get("Location", "")
    assert urlsplit(location).path == "/settings", location
    assert client.get(location).status_code == 200, location


# ---------------------------------------------------------------------------
# 1. /settings, endpoint'in varsayılan adresidir
# ---------------------------------------------------------------------------
def test_settings_page_endpoint_builds_the_settings_path(app) -> None:
    from flask import url_for

    with app.test_request_context():
        assert url_for("main.settings_page") == "/settings"
        assert urlsplit(url_for("main.settings_page", user_id=5)).path == "/settings"
    rules = {rule.rule for rule in app.url_map.iter_rules("main.settings_page")}
    assert rules == {"/settings", *ADMIN_PATHS}  # yönetim adresleri kaldırılmadı


# ---------------------------------------------------------------------------
# 2. Meşru işlemler: gerçek yönlendirme hedefi, takip edilen sonuç, ret kaydı yok
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", [*NON_ADMIN_MANAGERS, "admin"])
def test_legitimate_role_profile_save_lands_on_settings(app, role) -> None:
    """R05c: temel personel rol profili (tüm yönetim ailesi)."""
    plain_id = _user(app, "YD-SIRADAN", "personel")
    _user(app, "YD-AKTOR", role)
    client = _login(app, "YD-AKTOR")
    response = client.post("/settings", data={"form_action": "save_role_profile", "user_id": str(plain_id),
                                              "profile_role_target": "personel", "menu_dashboard": "on"})
    _assert_lands_on_settings(client, response)
    assert _personel_role_keys(app) == {"dashboard"}, role  # işlem gerçekten yazıldı
    assert _refusals(app) == [], role  # settings_admin_path dahil hiçbir yanlış ret kaydı yok


@pytest.mark.parametrize("role", [*NON_ADMIN_MANAGERS, "admin"])
def test_legitimate_ordinary_matrix_save_lands_on_settings(app, role) -> None:
    """R05c / K5q / B1F1: sıradan hesabın kişi bazlı matrisi, rol tanımı içinde."""
    plain_id = _user(app, "YD-SIRADAN", "personel")
    _user(app, "YD-AKTOR", role)
    client = _login(app, "YD-AKTOR")
    response = client.post("/settings", data={"form_action": "save_user_visibility", "user_id": str(plain_id),
                                              "menu_dashboard": "on"})
    _assert_lands_on_settings(client, response)
    assert _user_rows(app, plain_id).get("dashboard") is True, role
    assert _refusals(app) == [], role


# ---------------------------------------------------------------------------
# 3. CSRF açık: admin kabul edilir; token'sız istek hiçbir şey yazmaz
# ---------------------------------------------------------------------------
def test_csrf_on_real_admin_saves_and_rolls_back_system_settings(csrf_app) -> None:
    _user(csrf_app, "YD-ADMIN", "admin")
    admin = _login(csrf_app, "YD-ADMIN", csrf=True)
    original = _values(csrf_app)
    logs_before = _system_change_logs(csrf_app)
    response = admin.post("/settings", data={**SYSTEM_FORM, "csrf_token": _csrf_token(admin, "/settings")})
    _assert_lands_on_settings(admin, response)
    assert _values(csrf_app)["security.failed_login_threshold"] == "99"
    assert _values(csrf_app)["logs.enable_audit_log"] == original["logs.enable_audit_log"]  # kısmi istek kapatmadı
    assert _system_change_logs(csrf_app) == logs_before + 1
    response = admin.post("/settings", data={"form_action": "rollback_settings_change_entry",
                                             "change_log_id": str(_latest_system_log_id(csrf_app)),
                                             "csrf_token": _csrf_token(admin, "/settings")})
    _assert_lands_on_settings(admin, response)
    assert _values(csrf_app) == original
    for path in ADMIN_PATHS:
        assert admin.get(path).status_code == 200, path
    assert _refusals(csrf_app) == []


@pytest.mark.parametrize("path", ["/settings", *ADMIN_PATHS])
def test_csrf_on_request_without_token_writes_nothing(csrf_app, path) -> None:
    _user(csrf_app, "YD-ADMIN", "admin")
    admin = _login(csrf_app, "YD-ADMIN", csrf=True)
    before, logs_before = _values(csrf_app), _system_change_logs(csrf_app)
    response = admin.post(path, data=SYSTEM_FORM)
    assert response.status_code != 200, path
    assert _values(csrf_app) == before, path
    assert _system_change_logs(csrf_app) == logs_before, path


# ---------------------------------------------------------------------------
# 4. CSRF açık: admin olmayan yönetim rolleri geçerli token'la da reddedilir; R05c çalışır
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", NON_ADMIN_MANAGERS)
def test_csrf_on_manager_is_refused_for_system_settings_but_keeps_r05c(csrf_app, role) -> None:
    _user(csrf_app, "YD-ADMIN", "admin")
    plain_id = _user(csrf_app, "YD-SIRADAN", "personel")
    _user(csrf_app, "YD-AKTOR", role)
    admin = _login(csrf_app, "YD-ADMIN", csrf=True)
    assert admin.post("/settings", data={**SYSTEM_FORM, "csrf_token": _csrf_token(admin, "/settings")}).status_code == 302
    log_id = _latest_system_log_id(csrf_app)
    client = _login(csrf_app, "YD-AKTOR", csrf=True)
    before, logs_before = _values(csrf_app), _system_change_logs(csrf_app)

    attempts = {
        "save": ("/settings", {"form_action": "save_system_foundation",
                               "system__logs__enable_audit_log": "", "system_present__logs__enable_audit_log": "1",
                               "system__general__maintenance_mode": "on"}),
        "rollback": ("/settings", {"form_action": "rollback_settings_change_entry", "change_log_id": str(log_id)}),
        **{f"admin_path{path}": (path, SYSTEM_FORM) for path in ADMIN_PATHS},
    }
    for name, (path, form) in attempts.items():
        response = client.post(path, data={**form, "csrf_token": _csrf_token(client, "/settings")})
        assert response.status_code == 403, (role, name, response.status_code)
        assert _values(csrf_app) == before, (role, name)
        assert _system_change_logs(csrf_app) == logs_before, (role, name)
    for path in ADMIN_PATHS:
        assert client.get(path).status_code == 403, (role, path)
    refusals = " ".join(_refusals(csrf_app))
    assert "settings_system_foundation" in refusals and "settings_admin_path" in refusals, role

    refusal_count = len(_refusals(csrf_app))
    response = client.post("/settings", data={"form_action": "save_role_profile", "user_id": str(plain_id),
                                              "profile_role_target": "personel", "menu_dashboard": "on",
                                              "csrf_token": _csrf_token(client, "/settings")})
    _assert_lands_on_settings(client, response)
    assert _personel_role_keys(csrf_app) == {"dashboard"}, role
    assert len(_refusals(csrf_app)) == refusal_count, role  # meşru işlem yeni ret kaydı üretmedi


@pytest.mark.parametrize("role", OUTSIDE_ADMIN_FAMILY)
def test_csrf_on_roles_outside_admin_family_cannot_write_or_roll_back(csrf_app, role) -> None:
    _user(csrf_app, "YD-ADMIN", "admin")
    _user(csrf_app, "YD-AKTOR", role)
    admin = _login(csrf_app, "YD-ADMIN", csrf=True)
    assert admin.post("/settings", data={**SYSTEM_FORM, "csrf_token": _csrf_token(admin, "/settings")}).status_code == 302
    log_id = _latest_system_log_id(csrf_app)
    client = _login(csrf_app, "YD-AKTOR", csrf=True)
    token = _csrf_token(client, "/account")
    before, logs_before = _values(csrf_app), _system_change_logs(csrf_app)
    for path in ["/settings", *ADMIN_PATHS]:
        for form in (SYSTEM_FORM, {"form_action": "rollback_settings_change_entry", "change_log_id": str(log_id)}):
            response = client.post(path, data={**form, "csrf_token": token})
            assert response.status_code == 403, (role, path, form["form_action"], response.status_code)
    assert _values(csrf_app) == before, role
    assert _system_change_logs(csrf_app) == logs_before, role
