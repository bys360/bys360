"""Sistem ayarları: kısmi istek güvenlik denetimini sessizce kapatmaz; tam formdaki kasıtlı seçim korunur.

Kök neden: ``save_system_settings_from_form_handler`` her kayıtta bütün tanımları yazar. Formda
olmayan onay kutusu "kapalı", formda olmayan metin/sayı alanı boş değer olarak kaydedilir. Arayüz
formu bütün alanları gönderdiği için olağan kullanımda sorun yoktu; fakat yalnız bir alanı içeren
istek (betik, eksik form) ``logs.enable_audit_log`` denetim kaydını kapatıyor, izin verilen
uzantıları ve diğer alanları boşaltıyordu.

Beklenen semantik:
- Arayüz formu her alan için ``system_present__<alan>`` işaretçisi gönderir; işaretçisi olan alan
  yazılır (işaretsiz onay kutusu = kasıtlı "kapalı").
- İsteğin içermediği ve işaretçisi de olmayan alan olduğu gibi kalır.
"""
from __future__ import annotations

import html
import re
import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "AyarFormSahte1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "settings_partial_form" / "dbs"
WATCHED = ("security.failed_login_threshold", "attachments.allowed_extensions", "logs.enable_audit_log",
           "general.maintenance_mode", "general.system_name")


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-settings-partial", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "settings-partial-first-login",
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


@pytest.fixture
def admin(app):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(sicil_no="AF-ADMIN", email="af-admin@example.gov.tr", ad="Sahte", soyad="Admin", role="admin",
                    is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": "AF-ADMIN", "password": PASSWORD}).status_code == 302
    return client


def _values(app) -> dict[str, str | None]:
    from app.extensions import db
    from app.models import SystemSetting

    with app.app_context():
        rows = {row.setting_key: row.value_text for row in db.session.query(SystemSetting).all()}
    return {key: rows.get(key) for key in WATCHED}


def _system_form_from_page(page: str) -> dict[str, str]:
    """Tarayıcının göndereceği tam form: save_system_foundation formundaki alanlar ve işaretli kutular."""
    marker = '<input type="hidden" name="form_action" value="save_system_foundation">'
    assert marker in page
    start = page.rfind("<form", 0, page.index(marker))
    body = page[start:page.index("</form>", start)]
    data: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", body):
        name = re.search(r'name="([^"]+)"', tag)
        if not name:
            continue
        kind = (re.search(r'type="([^"]+)"', tag) or [None, "text"])[1]
        if kind == "checkbox":
            if re.search(r"\bchecked\b", tag):
                data[name.group(1)] = "on"
            continue
        value = re.search(r'value="([^"]*)"', tag)
        data[name.group(1)] = html.unescape(value.group(1)) if value else ""
    for name, value in re.findall(r'<textarea[^>]*name="([^"]+)"[^>]*>(.*?)</textarea>', body, flags=re.S):
        data[name] = html.unescape(value)
    return data


def test_partial_request_keeps_audit_log_and_untouched_fields(app, admin) -> None:
    before = _values(app)
    assert before["logs.enable_audit_log"] == "true"
    response = admin.post("/settings", data={"form_action": "save_system_foundation",
                                             "system__security__failed_login_threshold": "7"})
    assert response.status_code == 302
    after = _values(app)
    assert after["security.failed_login_threshold"] == "7"
    for key in ("logs.enable_audit_log", "attachments.allowed_extensions", "general.maintenance_mode", "general.system_name"):
        assert after[key] == before[key], key


def test_partial_request_can_still_set_a_boolean_explicitly(app, admin) -> None:
    assert _values(app)["general.maintenance_mode"] == "false"
    admin.post("/settings", data={"form_action": "save_system_foundation", "system__general__maintenance_mode": "on"})
    assert _values(app)["general.maintenance_mode"] == "true"


def test_full_ui_form_unchecking_the_audit_log_is_an_intentional_change(app, admin) -> None:
    before = _values(app)
    form = _system_form_from_page(admin.get("/settings").get_data(as_text=True))
    assert form.pop("system__logs__enable_audit_log") == "on"  # kullanıcı kutunun işaretini kaldırır
    assert admin.post("/settings", data=form).status_code == 302
    after = _values(app)
    assert after["logs.enable_audit_log"] == "false"
    for key in ("security.failed_login_threshold", "attachments.allowed_extensions", "general.maintenance_mode",
                "general.system_name"):
        assert after[key] == before[key], key


def test_the_ui_form_carries_a_presence_marker_for_every_system_setting(app, admin) -> None:
    from app.services.settings.catalog import SYSTEM_SETTING_DEFINITIONS

    form = _system_form_from_page(admin.get("/settings").get_data(as_text=True))
    expected = {f"system_present__{d['setting_key'].replace('.', '__')}" for d in SYSTEM_SETTING_DEFINITIONS}
    assert expected <= set(form), sorted(expected - set(form))[:5]
