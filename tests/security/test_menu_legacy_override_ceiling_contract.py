"""K2: kurumsal rol-menü politikasının dışındaki eski kişi kayıtları erişim anında yetki vermez.

Kök neden: kişi bazlı menü kaydı (``user_menu_permissions``) canlı menüde son karar katmanıdır
(``_apply_bys360_settings_live_authority_v1`` ve V14 bloğu). P0 menü düzeltmesi yalnız yeni yazmaları
sınırladı ve erişim anında yalnız ``admin_only`` anahtarları (91 anahtardan 2'si) kapattı. Rol
politikasının dışında kalan ama ``admin_only`` olmayan anahtarlar (``reports``,
``settings_center_security`` gibi 65 anahtar, ``personel`` için) eski bir kişi kaydıyla açılmaya ve
``menu_key_required`` rotalarında gerçek erişim vermeye devam ediyordu.

Proje sahibi kararı (18 Ekim 2026, K2): kurumsal politikanın dışındaki eski kişi kayıtları varsayılan
olarak erişim kazandırmaz; geçerli özel izinler yalnız kendi onaylı mekanizmasıyla tanınır:

- gerçek admin'in kişi matrisinden verdiği istisna (PS-MENÜ; kayıtta ``source_type="admin_exception"``);
- açık izinler (``personnel_read_all``, ``support_all``; K5q/B1F1, kendi denetimi).

Kural yalnız kişi kaydı olmadan zaten görünmeyecek anahtarlara uygulanır; rol varsayılanı, birim
profili ve portal/genel katmanlarının açtığı menüler değişmez. Kapatan kayıt her zaman uygulanır.
Erişim anındaki kontrol hiçbir satırı değiştirmez.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "EskiKayitTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "menu_legacy_override" / "dbs"
# Kurumsal tanımın personel ve koordinator rolüne vermediği, admin_only olmayan, gerçek erişim açan anahtarlar.
OUTSIDE_POLICY = {"settings_center_security": "/settings-center/security", "reports": "/communication/faz5/audit-logs"}
WITHIN_POLICY_HIDDEN_BY_DEFAULT = "performance_self_assessment"  # personel tutabilir, varsayılan kapalı


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-menu-legacy", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "menu-legacy-first-login-test",
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


def _user(app, sicil: str, role: str) -> int:
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=sicil, role=role,
                    birim="Sahte Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(app, sicil: str):
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD}).status_code == 302
    return client


def _legacy_rows(app, user_id: int, rows: dict[str, bool], source_type: str = "user_override") -> None:
    """Geçmişte yazılmış kişi kaydı (yazma yolu değil; erişim anındaki kural sınanır)."""
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        for key, visible in rows.items():
            db.session.add(UserMenuPermission(user_id=user_id, menu_key=key, is_visible=visible, source_type=source_type))
        db.session.commit()


def _rows(app, user_id: int) -> dict[str, tuple[bool, str]]:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        return {r.menu_key: (bool(r.is_visible), r.source_type) for r in db.session.query(UserMenuPermission).filter_by(user_id=user_id)}


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


def _matrix_form(user_id: int, keys: set[str]) -> dict[str, str]:
    return {"form_action": "save_user_visibility", "user_id": str(user_id), **{f"menu_{key}": "on" for key in keys}}


def _status(app, sicil: str, path: str) -> int:
    return _login(app, sicil).get(path).status_code


# ---------------------------------------------------------------------------
# 1. Politika dışı eski kişi kaydı erişim vermez (menü ve doğrudan URL); satır değişmez
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("target_role", ["personel", "koordinator"])
@pytest.mark.parametrize("key", sorted(OUTSIDE_POLICY))
@pytest.mark.parametrize("source_type", ["user_override", "rollback"])
def test_legacy_row_outside_role_policy_grants_nothing(app, target_role, key, source_type) -> None:
    target = _user(app, "EK-HEDEF", target_role)
    assert key not in _visible(app, target)
    _legacy_rows(app, target, {key: True}, source_type)
    before = _rows(app, target)
    assert key not in _visible(app, target), (target_role, key, source_type)
    assert _status(app, "EK-HEDEF", OUTSIDE_POLICY[key]) == 403, (target_role, key, source_type)
    assert _rows(app, target) == before  # erişim anındaki kontrol veri değiştirmez


def test_a_full_legacy_matrix_opens_no_key_outside_the_role_policy(app) -> None:
    """Eski yoklamadaki gibi bütün anahtarlar açık yazılmış bir personel kaydı (90/92 senaryosu)."""
    from app.services.settings.effective_menu import _active_menu_items
    from app.services.settings.menu_grant_ceiling import role_may_hold_menu_key

    target = _user(app, "EK-HEDEF", "personel")
    baseline = _visible(app, target)
    with app.app_context():
        keys = {str(item.get("key") or "").strip() for item in _active_menu_items() or []} - {""}
        outside = {key for key in keys if not role_may_hold_menu_key("personel", key)}
    _legacy_rows(app, target, {key: True for key in keys - {"personnel_read_all", "support_all"}})
    opened = (_visible(app, target) - baseline) & outside
    assert opened == set(), sorted(opened)


# ---------------------------------------------------------------------------
# 2. Meşru davranış korunur
# ---------------------------------------------------------------------------
def test_legacy_row_within_role_policy_still_opens(app) -> None:
    target = _user(app, "EK-HEDEF", "personel")
    assert WITHIN_POLICY_HIDDEN_BY_DEFAULT not in _visible(app, target)
    _legacy_rows(app, target, {WITHIN_POLICY_HIDDEN_BY_DEFAULT: True})
    assert WITHIN_POLICY_HIDDEN_BY_DEFAULT in _visible(app, target)


def test_legacy_row_still_closes_a_default_menu(app) -> None:
    target = _user(app, "EK-HEDEF", "personel")
    assert "messages" in _visible(app, target)
    _legacy_rows(app, target, {"messages": False})
    assert "messages" not in _visible(app, target)


def test_a_saved_matrix_keeps_every_default_menu(app) -> None:
    """Her kayıt bütün anahtarlara satır yazar; görünür varsayılan menüler (portal, genel) kaybolmaz."""
    target = _user(app, "EK-HEDEF", "personel")
    baseline = _visible(app, target)
    _legacy_rows(app, target, {key: True for key in baseline - {"personnel_read_all", "support_all"}})
    assert _visible(app, target) == baseline


def test_real_admin_exception_outside_policy_opens_access(app) -> None:
    target = _user(app, "EK-HEDEF", "personel")
    _user(app, "EK-ADMIN", "admin")
    admin = _login(app, "EK-ADMIN")
    base = _visible(app, target) - {"personnel_read_all", "support_all"}
    assert admin.post("/settings", data=_matrix_form(target, base | {"settings_center_security"})).status_code == 302
    assert _status(app, "EK-HEDEF", "/settings-center/security") == 200


def test_manager_resave_keeps_a_real_admin_exception_effective(app) -> None:
    target = _user(app, "EK-HEDEF", "personel")
    _user(app, "EK-ADMIN", "admin")
    _user(app, "EK-GB", "grup_baskani")
    admin = _login(app, "EK-ADMIN")
    base = _visible(app, target) - {"personnel_read_all", "support_all"}
    assert admin.post("/settings", data=_matrix_form(target, base | {"settings_center_security"})).status_code == 302
    manager = _login(app, "EK-GB")
    keep = _visible(app, target) - {"personnel_read_all", "support_all"}
    assert manager.post("/settings", data=_matrix_form(target, keep)).status_code == 302
    assert _status(app, "EK-HEDEF", "/settings-center/security") == 200


def test_manager_cannot_launder_a_legacy_row_by_resaving_it(app) -> None:
    target = _user(app, "EK-HEDEF", "personel")
    _user(app, "EK-GB", "grup_baskani")
    _legacy_rows(app, target, {"settings_center_security": True})
    manager = _login(app, "EK-GB")
    keys = (_visible(app, target) | {"settings_center_security"}) - {"personnel_read_all", "support_all"}
    before = _rows(app, target)
    assert manager.post("/settings", data=_matrix_form(target, keys)).status_code == 403
    assert _rows(app, target) == before
    assert _status(app, "EK-HEDEF", "/settings-center/security") == 403


def test_explicit_personnel_read_grant_by_admin_still_works(app) -> None:
    from app.extensions import db
    from app.models import User
    from app.services.personnel_read_grant import has_personnel_read_all_grant

    target = _user(app, "EK-HEDEF", "personel")
    _user(app, "EK-ADMIN", "admin")
    admin = _login(app, "EK-ADMIN")
    base = _visible(app, target) - {"personnel_read_all", "support_all"}
    assert admin.post("/settings", data=_matrix_form(target, base | {"personnel_read_all"})).status_code == 302
    with app.app_context():
        assert has_personnel_read_all_grant(db.session.get(User, target))


def test_real_admin_account_keeps_its_own_rows(app) -> None:
    admin = _user(app, "EK-ADMIN", "admin")
    baseline = _visible(app, admin)
    _legacy_rows(app, admin, {key: True for key in baseline - {"personnel_read_all", "support_all"}})
    assert _visible(app, admin) == baseline


# ---------------------------------------------------------------------------
# 3. Gerçek admin yalnız kayıtlı rolü "admin" olan hesaptır (K2/K3 kararı, 18 Ekim 2026)
# ---------------------------------------------------------------------------
ADMIN_ONLY_KEY, ADMIN_ONLY_ROUTE = "settings", "/communication/faz9/release-center"
REPORTS_ROUTE = "/communication/faz9/export/json"


def test_technical_role_legacy_rows_do_not_grant_real_admin_screens(app) -> None:
    target = _user(app, "EK-TEKNIK", "sistem_yoneticisi")
    _legacy_rows(app, target, {ADMIN_ONLY_KEY: True, "reports": True})
    visible = _visible(app, target)
    assert ADMIN_ONLY_KEY not in visible and "reports" not in visible
    assert _status(app, "EK-TEKNIK", ADMIN_ONLY_ROUTE) == 403
    assert _status(app, "EK-TEKNIK", REPORTS_ROUTE) == 403


@pytest.mark.parametrize("target_role", ["personel", "sistem_yoneticisi"])
def test_an_admin_exception_never_opens_an_admin_only_screen(app, target_role) -> None:
    target = _user(app, "EK-HEDEF", target_role)
    _legacy_rows(app, target, {ADMIN_ONLY_KEY: True}, "admin_exception")
    assert ADMIN_ONLY_KEY not in _visible(app, target)
    assert _status(app, "EK-HEDEF", ADMIN_ONLY_ROUTE) == 403


@pytest.mark.parametrize("target_role", ["personel", "sistem_yoneticisi"])
def test_reports_opens_only_through_a_real_admin_exception(app, target_role) -> None:
    plain = _user(app, "EK-DUZ", target_role)
    granted = _user(app, "EK-ISTISNA", target_role)
    _legacy_rows(app, plain, {"reports": True}, "user_override")
    _legacy_rows(app, granted, {"reports": True}, "admin_exception")
    assert _status(app, "EK-DUZ", REPORTS_ROUTE) == 403
    assert _status(app, "EK-ISTISNA", REPORTS_ROUTE) == 200


@pytest.mark.parametrize("actor_role", ["grup_baskani", "sistem_yoneticisi"])
def test_only_the_real_admin_records_an_exception(app, actor_role) -> None:
    target = _user(app, "EK-HEDEF", "personel")
    _user(app, "EK-ADMIN", "admin")
    _user(app, "EK-AKTOR", actor_role)
    base = _visible(app, target) - {"personnel_read_all", "support_all"}
    _login(app, "EK-AKTOR").post("/settings", data=_matrix_form(target, base | {"reports"}))
    assert _rows(app, target).get("reports", (False, ""))[1] != "admin_exception", actor_role
    assert _status(app, "EK-HEDEF", REPORTS_ROUTE) == 403
    assert _login(app, "EK-ADMIN").post("/settings", data=_matrix_form(target, base | {"reports"})).status_code == 302
    assert _rows(app, target)["reports"] == (True, "admin_exception")
    assert _status(app, "EK-HEDEF", REPORTS_ROUTE) == 200
