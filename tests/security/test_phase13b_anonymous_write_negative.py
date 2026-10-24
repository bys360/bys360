"""Phase 13B security closure -- anonymous/unauthorized write and read negatives.

Real Flask ``test_client()`` against the real assistant-role-matrix and
executive-summary routes. These two route families were confirmed in the
Phase 13B brutal-audit follow-up to be reachable by anonymous requests with
no backend authorization at all (AUTH-001, AUTH-002) -- the fix adds the
canonical ``admin_required`` / ``menu_key_required`` backend gates used
elsewhere in the app; these tests lock the negative (denied) and positive
(still works for the correct role) contracts so the gap cannot silently
regress.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

# BYS360_P13B_TEST_DB: pytest'in varsayilan tmp_path fixture'i, bu makinede
# ASCII-disi kullanici adi yuzunden Windows PermissionError'a duser (bkz.
# audit calismasi notlari). Repository-disi, ASCII-only, disposable bir
# dizin kullanilir; canli DB veya gercek kullanici verisi icermez.
_PHASE13B_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "phase13b" / "test_dbs"


def _make_app(monkeypatch, **env_overrides):
    # BYS360_P13B_TEST_DB: sqlite:///:memory: bir SQLAlchemy connection-pool
    # checkout'undan digerine FARKLI, bos bir bellek-ici veritabani donebilir
    # (StaticPool zorlanmadan); bu da ayni test icinde bir istek tablo gorurken
    # bir sonraki istegin "no such table" almasina yol aciyordu. Disposable
    # dosya-tabanli sqlite, tum istekler boyunca tek ve tutarli bir DB saglar.
    _PHASE13B_TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _PHASE13B_TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase13b-security-negatives")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    from app import create_app
    from config import Config

    # BYS360_P13B_CONFIG_ISOLATION:
    # Config sinif alanlari modul importunda bir kez hesaplanir.
    # app.config degisikligi db.init_app sonrasinda yapilirsa SQLAlchemy
    # motorunu degistirmez. Test DB ayarlarini create_app oncesinde
    # dogrudan Config sinifina uygula.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(
        Config,
        "SQLALCHEMY_DATABASE_URI",
        "sqlite:///" + db_path.as_posix(),
    )
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, email, role="personel", password="Phase13bTestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Phase13b",
            soyad="Test",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password="Phase13bTestKey1!"):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return response


def _seed_role_matrix_row(app, *, role_name, menu_key, is_visible):
    # Upsert: some role/menu combinations are already auto-provisioned by
    # app-startup defaults, so a blind INSERT can hit the (role_name,
    # menu_key) unique constraint.
    from app.extensions import db
    from app.models import RoleMenuDefault

    with app.app_context():
        row = (
            db.session.query(RoleMenuDefault)
            .filter_by(role_name=role_name, menu_key=menu_key)
            .first()
        )
        if row is None:
            row = RoleMenuDefault(role_name=role_name, menu_key=menu_key, is_visible=is_visible, source_type="seed")
            db.session.add(row)
        else:
            row.is_visible = is_visible
        db.session.commit()


def _role_matrix_value(app, *, role_name, menu_key):
    from app.extensions import db
    from app.models import RoleMenuDefault

    with app.app_context():
        row = (
            db.session.query(RoleMenuDefault)
            .filter(RoleMenuDefault.role_name == role_name, RoleMenuDefault.menu_key == menu_key)
            .order_by(RoleMenuDefault.id.desc())
            .first()
        )
        return None if row is None else bool(row.is_visible)


# --- AUTH-001: assistant role-matrix write ---


def test_anonymous_role_matrix_write_denied(app, client):
    _seed_role_matrix_row(app, role_name="kullanici", menu_key="assistant_module", is_visible=False)

    response = client.post("/settings/assistant-role-matrix-v10/save", data={}, follow_redirects=False)

    assert response.status_code in (302, 401, 403)
    if response.status_code == 302:
        assert "/login" in response.headers.get("Location", "")
    assert _role_matrix_value(app, role_name="kullanici", menu_key="assistant_module") is False


def _assert_write_denied(response):
    # A denied request may be rejected either by admin_required (403 / redirect
    # to login) or -- earlier in the pipeline -- by the unrelated assistant
    # module feature gate (redirect to a safe, non-sensitive landing page).
    # Either is an acceptable secure outcome; a redirect to "/settings" (the
    # view's own post-save success target) would mean the write went through
    # and is NOT acceptable.
    if response.status_code == 302:
        assert "/settings" not in response.headers.get("Location", "")
    else:
        assert response.status_code in (401, 403)


def test_unauthorized_role_matrix_write_denied(app, client):
    _create_user(app, sicil_no="13b001", email="p13b.roleunauth@ktb.gov.tr", role="personel")
    _seed_role_matrix_row(app, role_name="kullanici", menu_key="assistant_module", is_visible=False)
    _login(client, "13b001")

    response = client.post(
        "/settings/assistant-role-matrix-v10/save",
        data={"assistant_matrix__assistant_module__kullanici": "on"},
        follow_redirects=False,
    )

    _assert_write_denied(response)
    assert _role_matrix_value(app, role_name="kullanici", menu_key="assistant_module") is False


def test_authorized_role_matrix_write_succeeds(app, client):
    admin_id = _create_user(app, sicil_no="13b002", email="p13b.roleadmin@ktb.gov.tr", role="admin")
    _seed_role_matrix_row(app, role_name="kullanici", menu_key="assistant_module", is_visible=False)
    # BYS360_P13B_TEST_ISOLATION: a separate, unrelated assistant-module
    # feature gate consults a per-user override first; pin it on so this
    # admin cannot be redirected away by that gate regardless of what any
    # other test in the full suite may have done to role-level defaults.
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        db.session.add(UserMenuPermission(user_id=admin_id, menu_key="assistant_module", is_visible=True, source_type="seed"))
        db.session.commit()
    _login(client, "13b002")

    response = client.post(
        "/settings/assistant-role-matrix-v10/save",
        data={"assistant_matrix__assistant_module__kullanici": "on"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert _role_matrix_value(app, role_name="kullanici", menu_key="assistant_module") is True


def test_failed_role_matrix_write_leaves_db_unchanged(app, client):
    _create_user(app, sicil_no="13b003", email="p13b.rolefail@ktb.gov.tr", role="birim_sorumlusu")
    seeds = [("admin", "assistant_module", True), ("kullanici", "assistant_module", False), ("personel", "assistant_settings", False)]
    for role_name, menu_key, is_visible in seeds:
        _seed_role_matrix_row(app, role_name=role_name, menu_key=menu_key, is_visible=is_visible)
    _login(client, "13b003")

    response = client.post("/settings/assistant-role-matrix-v10/save", data={}, follow_redirects=False)

    _assert_write_denied(response)
    for role_name, menu_key, expected in seeds:
        assert _role_matrix_value(app, role_name=role_name, menu_key=menu_key) is expected


# --- AUTH-002: executive summary sensitive data + test-mail ---


def test_anonymous_executive_summary_data_denied(app, client):
    response = client.get("/dashboard/yonetici-ozeti/data", follow_redirects=False)

    assert response.status_code in (302, 401, 403)
    assert response.content_type != "application/json"


def test_unauthorized_executive_summary_data_denied(app, client):
    _create_user(app, sicil_no="13b004", email="p13b.execunauth@ktb.gov.tr", role="personel")
    _login(client, "13b004")

    response = client.get("/dashboard/yonetici-ozeti/data", follow_redirects=False)

    assert response.status_code == 403


def test_anonymous_test_mail_denied(app, client):
    response = client.post("/dashboard/yonetici-ozeti/test-mail", data={}, follow_redirects=False)

    assert response.status_code in (302, 401, 403)


def test_unauthorized_test_mail_denied(app, client):
    _create_user(app, sicil_no="13b005", email="p13b.mailunauth@ktb.gov.tr", role="personel")
    _login(client, "13b005")

    response = client.post("/dashboard/yonetici-ozeti/test-mail", data={}, follow_redirects=False)

    assert response.status_code == 403
