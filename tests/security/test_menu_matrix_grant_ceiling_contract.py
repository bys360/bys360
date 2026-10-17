"""P0: menü matrisi üzerinden dolaylı yetki yükseltme kapatılır; meşru matris işlemleri korunur.

Kök neden (17 Ekim 2026, sahte uygulamada ölçüldü): yönetim ailesindeki admin olmayan bir rol
/settings üzerinden sıradan bir personel hesabının kişi matrisinde 92 menü anahtarından 90'ını
açabiliyordu. Rol değişmeden, yalnız ``menu_key_required`` ile korunan 62 rota 403'ten 200'e
dönüyordu (ör. /settings-center/security, /communication/faz5/audit-logs). Canlı menü haritasında
kişi bazlı kayıt kurumsal rol-menü politikasının ve ``admin_only`` filtresinin üstüne yazılır
(build_context.py V14 bloğu). Kişi matrisine yazan üç yolun (tekil kayıt, toplu profil, geri alma)
ve personel rol varsayılanlarının hiçbirinde "verilebilecek en üst yetki" sınırı yoktu.

Proje sahibi kararı (17 Ekim 2026): R05c, K5q ve B1F1'in koruduğu sıradan matris işlemleri
korunur; ancak bu işlemlerle kimseye kurumsal tanımın o rol için vermediği bir yetki açılamaz.

Kural (gerçek admin dışındaki herkes için): bir hesapta yalnız hedef rolün kurumsal tanımın
(menü kaydı ``admin_only``/``required_roles`` ve rol-menü politikası) izin verdiği anahtarlar
yeni açılabilir. Hesapta zaten görünen anahtarlar (ör. admin'in verdiği istisna) yeniden
kaydedilebilir; daraltma her zaman serbesttir. Açık izinler (personnel_read_all, support_all)
mevcut K5q/B1F1 kuralıyla ayrı korunur. Ret: 403, ``account.change_refused`` denetim kaydı,
hiçbir satır yazılmaz.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "MatrisTavanSahte1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "menu_grant_ceiling" / "dbs"
NON_ADMIN_MANAGERS = ["baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir"]
# Kurumsal tanımın personel rolüne vermediği, gerçek erişim açan anahtarlar ve açtıkları rotalar.
CRITICAL = {"settings_center_security": "/settings-center/security", "reports": "/communication/faz5/audit-logs"}
ALLOWED_FOR_PERSONEL = "dashboard"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-menu-ceiling", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "menu-ceiling-first-login",
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
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


def _user(app, sicil: str, role: str, birim: str = "Sahte Birim A") -> int:
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=sicil, role=role, birim=birim,
                    is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(app, sicil: str):
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD}).status_code == 302
    return client


def _rows(app, user_id: int) -> dict[str, bool]:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        return {r.menu_key: bool(r.is_visible) for r in db.session.query(UserMenuPermission).filter_by(user_id=user_id).all()}


def _visible(app, user_id: int) -> set[str]:
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.route_support import build_menu_visibility_map

    with app.app_context():
        user = db.session.get(User, user_id)
        with app.test_request_context("/"):
            login_user(user)
            return {key for key, value in build_menu_visibility_map(user).items() if value}


def _matrix_form(user_id: int, keys: set[str], action: str = "save_user_visibility") -> dict[str, str]:
    return {"form_action": action, "user_id": str(user_id), **{f"menu_{key}": "on" for key in keys}}


def _refused(app, reason: str) -> bool:
    from app.extensions import db
    from app.models import AuditLog

    with app.app_context():
        return any(reason in (row.summary or "") for row in db.session.query(AuditLog).filter_by(action="account.change_refused"))


def _route_status(app, sicil: str, path: str) -> int:
    return _login(app, sicil).get(path).status_code


# ---------------------------------------------------------------------------
# 1. Kritik anahtar verme: admin olmayan yönetim rolleri reddedilir; doğrudan URL kapalı kalır
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("actor_role", NON_ADMIN_MANAGERS)
@pytest.mark.parametrize("action", ["save_user_visibility", "save_personnel_feature_matrix_full"])
def test_manager_cannot_open_critical_keys_on_an_ordinary_account(app, actor_role, action) -> None:
    target = _user(app, "MT-HEDEF", "personel")
    _user(app, "MT-AKTOR", actor_role)
    actor = _login(app, "MT-AKTOR")
    before_rows, before_visible = _rows(app, target), _visible(app, target)
    assert not set(CRITICAL) & before_visible
    keys = (before_visible | set(CRITICAL)) - {"personnel_read_all", "support_all"}
    response = actor.post("/settings", data=_matrix_form(target, keys, action))
    assert response.status_code == 403, (actor_role, response.status_code)
    assert _rows(app, target) == before_rows
    assert _refused(app, "settings_grant_ceiling")
    for path in CRITICAL.values():
        assert _route_status(app, "MT-HEDEF", path) == 403, path


# ---------------------------------------------------------------------------
# 2. Meşru sıradan matris işlemi (R05c / K5q / B1F1) çalışmaya devam eder
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("actor_role", NON_ADMIN_MANAGERS)
def test_manager_still_edits_an_ordinary_account_within_the_role_definition(app, actor_role) -> None:
    target = _user(app, "MT-HEDEF", "personel")
    _user(app, "MT-AKTOR", actor_role)
    actor = _login(app, "MT-AKTOR")
    response = actor.post("/settings", data=_matrix_form(target, {ALLOWED_FOR_PERSONEL}))
    assert response.status_code == 302
    assert _rows(app, target).get(ALLOWED_FOR_PERSONEL) is True
    assert ALLOWED_FOR_PERSONEL in _visible(app, target)


# ---------------------------------------------------------------------------
# 3. Gerçek admin istisna verebilir; mevcut istisna admin olmayan kayıtta korunur, daraltılabilir
# ---------------------------------------------------------------------------
def test_real_admin_exception_is_kept_and_can_be_narrowed_by_a_manager(app) -> None:
    target = _user(app, "MT-HEDEF", "personel")
    _user(app, "MT-ADMIN", "admin")
    _user(app, "MT-GB", "grup_baskani")
    admin = _login(app, "MT-ADMIN")
    base = _visible(app, target) - {"personnel_read_all", "support_all"}
    assert admin.post("/settings", data=_matrix_form(target, base | {"settings_center_security"})).status_code == 302
    assert _route_status(app, "MT-HEDEF", "/settings-center/security") == 200
    manager = _login(app, "MT-GB")
    keep = (_visible(app, target) - {"personnel_read_all", "support_all"}) | {ALLOWED_FOR_PERSONEL}
    assert manager.post("/settings", data=_matrix_form(target, keep)).status_code == 302  # mevcut istisna yeniden kaydedilir
    assert _rows(app, target).get("settings_center_security") is True
    narrowed = keep - {"settings_center_security"}
    assert manager.post("/settings", data=_matrix_form(target, narrowed)).status_code == 302  # daraltma serbest
    assert _route_status(app, "MT-HEDEF", "/settings-center/security") == 403


# ---------------------------------------------------------------------------
# 4. Toplu profil: "tam erişim" yönetim rolüne reddedilir; rol varsayılanı profili çalışır (R05c F3)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("actor_role", ["baskan", "grup_baskani", "mali_musavir"])
def test_bulk_full_access_profile_is_refused_for_managers(app, actor_role) -> None:
    targets = [_user(app, f"MT-T{i}", "personel", "Sahte Toplu Birim") for i in range(2)]
    _user(app, "MT-AKTOR", actor_role)
    actor = _login(app, "MT-AKTOR")
    before = {t: _rows(app, t) for t in targets}
    response = actor.post("/settings", data={"form_action": "bulk_apply_profile", "bulk_profile_key": "static::full_access",
                                             "bulk_scope_type": "birim", "bulk_birim": "Sahte Toplu Birim"})
    assert response.status_code == 403
    assert {t: _rows(app, t) for t in targets} == before
    assert _route_status(app, "MT-T0", "/settings-center/security") == 403
    ok = actor.post("/settings", data={"form_action": "bulk_apply_profile", "bulk_profile_key": "dynamic::role_defaults",
                                       "bulk_scope_type": "birim", "bulk_birim": "Sahte Toplu Birim"})
    assert ok.status_code == 302


# ---------------------------------------------------------------------------
# 5. Personel rol varsayılanı: kritik anahtar eklenemez; izinli değişiklik yapılır (R05c)
# ---------------------------------------------------------------------------
def test_baseline_role_profile_cannot_gain_critical_keys(app) -> None:
    from app.services.settings_service import get_role_default_menu_keys

    plain = _user(app, "MT-HEDEF", "personel")
    _user(app, "MT-BASKAN", "baskan")
    baskan = _login(app, "MT-BASKAN")
    baskan.get("/settings")
    with app.app_context():
        before = set(get_role_default_menu_keys("personel"))
    response = baskan.post("/settings", data={"form_action": "save_role_profile", "user_id": str(plain),
                                              "profile_role_target": "personel", "menu_dashboard": "on",
                                              "menu_settings_center_security": "on"})
    assert response.status_code == 403
    with app.app_context():
        assert set(get_role_default_menu_keys("personel")) == before
    assert _route_status(app, "MT-HEDEF", "/settings-center/security") == 403
    ok = baskan.post("/settings", data={"form_action": "save_role_profile", "user_id": str(plain),
                                        "profile_role_target": "personel", "menu_dashboard": "on"})
    assert ok.status_code == 302
    with app.app_context():
        assert set(get_role_default_menu_keys("personel")) == {"dashboard"}


# ---------------------------------------------------------------------------
# 6. Geri alma ile kritik anahtar yeniden açılamaz (yalnız gerçek admin)
# ---------------------------------------------------------------------------
def test_rollback_cannot_restore_a_critical_key_for_a_manager(app) -> None:
    from app.extensions import db
    from app.models import SettingsChangeLog

    target = _user(app, "MT-HEDEF", "personel")
    _user(app, "MT-ADMIN", "admin")
    _user(app, "MT-GB", "grup_baskani")
    admin = _login(app, "MT-ADMIN")
    base = _visible(app, target) - {"personnel_read_all", "support_all"}
    admin.post("/settings", data=_matrix_form(target, base | {"settings_center_security"}))
    admin.post("/settings", data=_matrix_form(target, base))  # admin istisnayı kaldırır
    with app.app_context():
        log_id = (db.session.query(SettingsChangeLog).filter_by(change_scope="user_menu_overrides", target_user_id=target)
                  .order_by(SettingsChangeLog.id.desc()).first())
        assert log_id is not None
        log_id = log_id.id
    manager = _login(app, "MT-GB")
    before = _rows(app, target)
    response = manager.post("/settings", data={"form_action": "rollback_settings_change_entry", "change_log_id": str(log_id)})
    assert response.status_code == 403
    assert _rows(app, target) == before
    assert _route_status(app, "MT-HEDEF", "/settings-center/security") == 403


# ---------------------------------------------------------------------------
# 7. Kurumsal tanım kontrolü sözleşmesi: yardımcı fonksiyon fail-closed
# ---------------------------------------------------------------------------
def test_unknown_or_admin_only_keys_are_never_allowed_for_personel(app) -> None:
    from app.services.settings.menu_grant_ceiling import role_may_hold_menu_key

    with app.app_context():
        assert role_may_hold_menu_key("personel", "dashboard") is True
        assert role_may_hold_menu_key("personel", "settings_center_security") is False
        assert role_may_hold_menu_key("personel", "settings") is False
        assert role_may_hold_menu_key("personel", "boyle_bir_anahtar_yok") is False
        assert role_may_hold_menu_key("admin", "settings_center_security") is True


# ---------------------------------------------------------------------------
# 8. İstek anı (katman 2): veritabanında önceden yazılmış kişi bazlı kayıt, admin_only bir
#    yönetim anahtarını admin olmayana açmaz; GET ve yazma (POST) uçları kapalı kalır.
# ---------------------------------------------------------------------------
LEGACY_SETTINGS_ROUTES = ["/communication/faz5/retention", "/communication/faz8/cutover", "/communication/faz9/release-center",
                          "/communication/faz9a/preflight"]


def _legacy_override(app, user_id: int, key: str) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        db.session.add(UserMenuPermission(user_id=user_id, menu_key=key, is_visible=True, source_type="user_override"))
        db.session.commit()


def _retention_rows(app) -> int:
    from app.extensions import db
    from app.models.communication_phase5_models import CommunicationRetentionPolicy

    with app.app_context():
        return db.session.query(CommunicationRetentionPolicy).count()


@pytest.mark.parametrize("role", ["personel", "grup_baskani", "mali_musavir", "baskan"])
def test_legacy_override_of_an_admin_only_key_grants_nothing(app, role) -> None:
    user_id = _user(app, "MT-ESKI", role)
    _legacy_override(app, user_id, "settings")
    assert "settings" not in _visible(app, user_id)
    client = _login(app, "MT-ESKI")
    for path in LEGACY_SETTINGS_ROUTES:
        assert client.get(path).status_code == 403, (role, path)
    before = _retention_rows(app)
    response = client.post("/communication/faz5/retention/save", data={"data_scope": "notifications", "keep_days": "1",
                                                                       "purge_after_days": "1"})
    assert response.status_code == 403, (role, response.status_code)
    assert _retention_rows(app) == before


def test_real_admin_keeps_the_admin_only_management_screens(app) -> None:
    _user(app, "MT-ADMIN", "admin")
    client = _login(app, "MT-ADMIN")
    for path in LEGACY_SETTINGS_ROUTES:
        assert client.get(path).status_code == 200, path
    before = _retention_rows(app)
    assert client.post("/communication/faz5/retention/save", data={"data_scope": "notifications", "keep_days": "30"}).status_code == 302
    assert _retention_rows(app) == before + 1
