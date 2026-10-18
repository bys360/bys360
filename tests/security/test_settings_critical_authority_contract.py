"""Kritik sistem yapılandırması yalnız gerçek admin'e ait; Başkan'ın R05c işlemleri korunur.

Kök neden (17 Ekim 2026): /settings ve /admin/settings* yalnız ``admin_required`` (yönetim
ailesi) ile korunuyor. ``save_system_foundation`` dalı hiçbir yetki kontrolü yapmadan bütün sistem
ayarlarını yazıyordu: güvenlik eşikleri, oturum süresi, bakım modu, denetim kaydı, yükleme
uzantıları ve kökü. Form eksiksiz yazıldığı için gönderilmeyen onay kutuları kapanır; bir alanı
değiştiren istek denetim kaydını da kapatıyordu. ``system_settings`` değişikliklerinin geri alınması
da yetki denetimsizdi. Bu davranışları sabitleyen bir test yoktu.

Proje sahibi kararı (17 Ekim 2026):
- Sistem güvenlik yapılandırması, bakım modu, denetim kaydı ve yükleme güvenliği: yalnız gerçek
  admin. Reddedilen istek 403 alır, ``account.change_refused`` olarak denetlenir, hiçbir şey yazılmaz.
- /admin/settings, /admin/settings/performance, /admin/settings/security: yalnız gerçek admin.
- /settings üzerindeki R05c işlemleri (Başkan: temel personel rol profili, sıradan hesap matrisi,
  yetki içermeyen modül ayarları, temel geri almalar, toplu profil) değişmez; mevcut sözleşmeler
  (R05b/R05c/R05d/K5q/B1F1) bunları korumaya devam eder.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "AyarYetkiTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "settings_critical" / "dbs"
ADMIN_FAMILY_NON_ADMIN = ["baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir"]
OUTSIDE_ADMIN_FAMILY = ["koordinator", "birim_sorumlusu", "personel"]
ALL_ROLES = ["admin", *ADMIN_FAMILY_NON_ADMIN, *OUTSIDE_ADMIN_FAMILY]
ADMIN_PATHS = ["/admin/settings", "/admin/settings/performance", "/admin/settings/security"]
WATCHED = ("security.failed_login_threshold", "attachments.allowed_extensions", "logs.enable_audit_log",
           "general.maintenance_mode")
# Gerçekçi saldırı formu: eşiği yükselt, .exe yüklemeye izin ver; denetim kaydı alanı gönderilmez.
SYSTEM_FORM = {
    "form_action": "save_system_foundation",
    "system__security__failed_login_threshold": "99",
    "system__attachments__allowed_extensions": "pdf,exe",
}


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-settings-critical", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "settings-critical-first-login",
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
    from app.services.settings_service import ensure_settings_phase1_seeded

    with flask_app.app_context():
        db.create_all()
        ensure_settings_phase1_seeded()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


def _client_for(app, role: str, sicil: str | None = None):
    from app.extensions import db
    from app.models import User

    sicil = sicil or f"AY-{role[:12]}"
    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=role, role=role,
                    is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD}).status_code == 302
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


def _refusals(app, reason: str) -> list[str]:
    from app.extensions import db
    from app.models import AuditLog

    with app.app_context():
        rows = db.session.query(AuditLog).filter_by(action="account.change_refused").all()
        return [f"{row.summary} {row.new_data_json}" for row in rows if reason in (row.summary or "")]


# ---------------------------------------------------------------------------
# 1. Sistem ayarı yazma (/settings üzerinden): yalnız gerçek admin
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ALL_ROLES)
def test_system_foundation_write_is_real_admin_only(app, role) -> None:
    client = _client_for(app, role)
    before, logs_before = _values(app), _system_change_logs(app)
    assert before["logs.enable_audit_log"] == "true"
    response = client.post("/settings", data=SYSTEM_FORM)
    after = _values(app)
    if role == "admin":
        assert response.status_code == 302
        assert after["security.failed_login_threshold"] == "99"
        assert _system_change_logs(app) == logs_before + 1
    else:
        assert response.status_code == 403, (role, response.status_code)
        assert after == before, role  # eşik, uzantılar, denetim kaydı ve bakım modu değişmedi
        assert _system_change_logs(app) == logs_before, role
        if role in ADMIN_FAMILY_NON_ADMIN:
            assert _refusals(app, "settings_system_foundation"), role


# ---------------------------------------------------------------------------
# 2. /admin/settings* adresleri: yalnız gerçek admin (GET ve POST)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ALL_ROLES)
def test_admin_settings_paths_are_real_admin_only(app, role) -> None:
    client = _client_for(app, role)
    before = _values(app)
    for path in ADMIN_PATHS:
        get_status = client.get(path).status_code
        post_status = client.post(path, data=SYSTEM_FORM).status_code
        if role == "admin":
            assert get_status == 200 and post_status == 302, (path, get_status, post_status)
        else:
            assert get_status == 403 and post_status == 403, (role, path, get_status, post_status)
    if role != "admin":
        assert _values(app) == before, role
    if role in ADMIN_FAMILY_NON_ADMIN:
        assert _refusals(app, "settings_admin_path"), role


def test_baskan_keeps_the_settings_page_and_r05c_operations(app) -> None:
    """R05c sürekliliği: Başkan /settings sayfasına girer ve temel personel rol profilini yönetir."""
    from app.extensions import db
    from app.models import User
    from app.services.settings_service import get_role_default_menu_keys

    _client_for(app, "personel", "AY-SIRADAN")  # R05c sözleşmesindeki gibi sıradan bir personel hesabı
    with app.app_context():
        plain_id = db.session.query(User).filter_by(sicil_no="AY-SIRADAN").one().id
    client = _client_for(app, "baskan")
    assert client.get("/settings").status_code == 200
    response = client.post("/settings", data={"form_action": "save_role_profile", "user_id": str(plain_id),
                                              "profile_role_target": "personel", "menu_dashboard": "on"})
    assert response.status_code == 302
    with app.app_context():
        assert set(get_role_default_menu_keys("personel")) == {"dashboard"}


# ---------------------------------------------------------------------------
# 3. Sistem ayarı geri alma: yalnız gerçek admin
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ADMIN_FAMILY_NON_ADMIN)
def test_system_settings_rollback_is_real_admin_only(app, role) -> None:
    from app.extensions import db
    from app.models import SettingsChangeLog

    admin = _client_for(app, "admin")
    original = _values(app)["security.failed_login_threshold"]
    assert admin.post("/settings", data=SYSTEM_FORM).status_code == 302
    changed = _values(app)
    with app.app_context():
        log_row = (db.session.query(SettingsChangeLog).filter_by(change_scope="system_settings", is_rollback=False)
                   .order_by(SettingsChangeLog.id.desc()).first())
        assert log_row is not None
        log_id = log_row.id
    client = _client_for(app, role)
    response = client.post("/settings", data={"form_action": "rollback_settings_change_entry", "change_log_id": str(log_id)})
    assert response.status_code == 403, (role, response.status_code)
    assert _values(app) == changed, role
    assert _refusals(app, "settings_system_foundation"), role
    # Gerçek admin aynı kaydı geri alabilir.
    assert admin.post("/settings", data={"form_action": "rollback_settings_change_entry",
                                         "change_log_id": str(log_id)}).status_code == 302
    assert _values(app)["security.failed_login_threshold"] == original


# ---------------------------------------------------------------------------
# 4. Oturumsuz istek ve denetim kaydında hassas değer olmaması
# ---------------------------------------------------------------------------
def test_anonymous_settings_requests_change_nothing(app) -> None:
    before = _values(app)
    client = app.test_client()
    for path in ["/settings", *ADMIN_PATHS]:
        response = client.post(path, data=SYSTEM_FORM)
        redirected = response.status_code in (301, 302) and "/login" in response.headers.get("Location", "")
        # /admin/* yolları için mevcut operasyonel yol koruması oturumsuz isteği 403 ile reddeder.
        assert redirected or response.status_code == 403, (path, response.status_code)
    assert _values(app) == before


def test_refusal_audit_contains_no_submitted_values(app) -> None:
    client = _client_for(app, "mali_musavir")
    secret = "GIZLI-TEST-AYAR-4419"
    form = {**SYSTEM_FORM, "system__general__version_note": secret, "password": secret}
    assert client.post("/settings?token=" + secret, data=form).status_code == 403
    assert client.post("/admin/settings/security?token=" + secret, data=form).status_code == 403
    stored = " ".join(_refusals(app, "settings_"))
    assert "settings_system_foundation" in stored and "settings_admin_path" in stored
    assert secret not in stored and PASSWORD not in stored and "exe" not in stored
