"""Misafir dosya bağlantısı belirteci Referer başlığı üzerinden de günlüğe/audit'e açık yazılmaz.

Kök neden: PR #91 (4c77dff4) ``request.path`` ve ``request.full_path`` değerlerini maskeliyor, ancak
iki ortak günlük bağlamı (``app/bootstrap/request_context.py`` ve ``app/error_handlers.py``
içindeki ``request_log_context``) ``Referer`` başlığını ham yazıyordu. Misafir sayfasından gelen
bir sonraki istek (aynı site Referer'ı) veritabanı hatası, erişim reddi, 405 veya CSRF yenileme
kaydına düşerse belirteç günlükte açık kalıyordu.

Düzeltme tam Referer URL'sini ayrıştırır, belirteci yol bileşeninde ``***`` ile maskeler, sorgu
veya parça alanında belirteç yolu varsa o alanı çıkarır; ayrıştırılamayan başlığı ham yazmaz.
İlgisiz Referer değerleri aynen kalır. Global Referrer-Policy değiştirilmez.
"""
from __future__ import annotations

import json
import logging
import secrets
import tempfile
import uuid
from pathlib import Path

import pytest

_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "guest_token_referer_log" / "dbs"
HOST = "https://bys.example.gov.tr"
MODULES = ["app.bootstrap.request_context", "app.error_handlers"]


@pytest.fixture(autouse=True)
def _logging_enabled():
    """Günlük metni doğrulanır; önceki testin bıraktığı ``logging.disable()`` durumuna bağlı kalınmaz."""
    previous = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    yield
    logging.disable(previous)


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-guest-referer-log", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "guest-referer-log-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri, PROPAGATE_EXCEPTIONS=False)
    from app.extensions import db
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


class _Collect(logging.Handler):
    """Mesajı ve istisna metnini birlikte toplar (biçimlendirilmiş kayıt)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


@pytest.fixture
def captured(app):
    handler = _Collect()
    loggers = [logging.getLogger(), logging.getLogger("bys360.ops"), app.logger]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    yield handler
    for logger, level in zip(loggers, levels, strict=True):
        logger.removeHandler(handler)
        logger.setLevel(level)


def _audit_text(app) -> str:
    from sqlalchemy import text

    from app.extensions import db

    with app.app_context():
        rows = db.session.execute(text("SELECT action, summary, old_data_json, new_data_json FROM audit_logs")).fetchall()
    return json.dumps([[str(value) for value in row] for row in rows], ensure_ascii=False)


def _token() -> str:
    return "SAHTE" + secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# 1. Ortak günlük bağlamları: Referer biçimleri
# ---------------------------------------------------------------------------
PATH_FORMS = {
    "ayni_site_tam_url": "http://localhost/guest/files/{t}",
    "kurumsal_alan_adi": HOST + "/guest/files/{t}",
    "mount_prefix": HOST + "/bys/guest/files/{t}",
    "yukleme_baglantisi": HOST + "/guest/upload/{t}?step=1",
    "goreli_yol": "/guest/files/{t}",
    "kodlanmis_bolu": HOST + "/guest%2Ffiles/{t}",
    "port_ve_alt_yol": "http://bys.example.gov.tr:8080/bys/guest/upload/{t}",
}
FIELD_FORMS = {
    "sorgu_next": HOST + "/login?next=/guest/files/{t}",
    "sorgu_kodlanmis": HOST + "/login?next=%2Fguest%2Ffiles%2F{t}",
    "parca": HOST + "/home#/guest/upload/{t}",
}


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("form", sorted(PATH_FORMS))
def test_request_log_context_masks_the_guest_token_in_the_referer_path(app, module, form) -> None:
    import importlib

    token = _token()
    helper = importlib.import_module(module).request_log_context
    with app.test_request_context("/support/my-tickets", headers={"Referer": PATH_FORMS[form].format(t=token)}):
        context = helper()
    assert token not in str(context), form
    referer = context["referer"]
    assert "/guest/files/***" in referer or "/guest/upload/***" in referer, referer  # izlenebilirlik korunur


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("form", sorted(FIELD_FORMS))
def test_request_log_context_drops_a_guest_token_carried_in_the_referer_query_or_fragment(app, module, form) -> None:
    import importlib

    token = _token()
    helper = importlib.import_module(module).request_log_context
    with app.test_request_context("/support/my-tickets", headers={"Referer": FIELD_FORMS[form].format(t=token)}):
        context = helper()
    assert token not in str(context), form
    assert context["referer"].startswith(HOST + "/"), context["referer"]


UNRELATED = [
    HOST + "/support/my-tickets?status=open",
    HOST + "/bys/performance/self-assessment",
    HOST + "/guest/help",
    HOST + "/file-center/files/42?tab=share",
    "https://other.example.org/files/abc?token=xyz",
    "/home",
]


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("referer", UNRELATED)
def test_unrelated_referers_are_logged_unchanged(app, module, referer) -> None:
    import importlib

    helper = importlib.import_module(module).request_log_context
    with app.test_request_context("/home", headers={"Referer": referer}):
        assert helper()["referer"] == referer


@pytest.mark.parametrize("module", MODULES)
def test_a_missing_referer_is_logged_as_dash(app, module) -> None:
    import importlib

    helper = importlib.import_module(module).request_log_context
    with app.test_request_context("/home"):
        assert helper()["referer"] == "-"


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("raw", ["http://[bys.example.gov.tr/guest/files/{t}", "http://[::1/home"])
def test_an_unparseable_referer_is_never_logged_raw(app, module, raw) -> None:
    import importlib

    token = _token()
    value = raw.format(t=token)
    helper = importlib.import_module(module).request_log_context
    with app.test_request_context("/home", headers={"Referer": value}):
        context = helper()
    assert token not in str(context)
    assert context["referer"] != value
    assert context["path"] == "/home"  # bağlamın geri kalanı üretilmeye devam eder


# ---------------------------------------------------------------------------
# 2. Uçtan uca: misafir indirmesinde sahte veritabanı hatası
# ---------------------------------------------------------------------------
def _break_guest_lookup(monkeypatch):
    from sqlalchemy.exc import OperationalError

    import app.file_center.routes as file_routes

    def _fail(_token_value):
        raise OperationalError("SELECT 1", {}, Exception("sahte veritabani hatasi"))

    monkeypatch.setattr(file_routes, "guest_links_enabled", lambda: True)
    monkeypatch.setattr(file_routes, "find_share_link_by_token", _fail)


@pytest.mark.parametrize("variant", ["referer_yok", "ayni_site_referer", "mount_prefix"])
def test_guest_download_database_error_leaves_no_token_in_logs_or_audit(app, captured, monkeypatch, variant) -> None:
    _break_guest_lookup(monkeypatch)
    token = _token()
    app.config["SLOW_REQUEST_THRESHOLD_MS"] = 0
    client = app.test_client()
    if variant == "mount_prefix":
        response = client.get(f"/guest/files/{token}", base_url="http://localhost/bys",
                              headers={"Referer": f"http://localhost/bys/guest/files/{token}"})
    else:
        headers = {"Referer": f"http://localhost/guest/files/{token}"} if variant == "ayni_site_referer" else {}
        response = client.get(f"/guest/files/{token}", headers=headers)
    assert response.status_code == 500  # mevcut hata davranışı korunur
    assert token not in response.get_data(as_text=True)
    assert any("Veritabanı hatası yakalandı" in m for m in captured.messages), captured.messages[:5]
    leaked = [m for m in captured.messages if token in m]
    assert leaked == [], [m.replace(token, "<SAHTE>")[:200] for m in leaked]
    assert any("/guest/files/***" in m for m in captured.messages)
    assert token not in _audit_text(app)


def test_guest_download_without_a_link_still_renders_the_guest_page(app, captured, monkeypatch) -> None:
    import app.file_center.routes as file_routes

    monkeypatch.setattr(file_routes, "guest_links_enabled", lambda: True)
    token = _token()
    response = app.test_client().get(f"/guest/files/{token}", headers={"Referer": f"{HOST}/guest/files/{token}"})
    assert response.status_code == 200
    assert "Bağlantı geçersiz" in response.get_data(as_text=True)
    assert not [m for m in captured.messages if token in m]


# ---------------------------------------------------------------------------
# 3. Erişim reddi, hata işleyicileri ve audit yolları (misafir sayfasından gelen istek)
# ---------------------------------------------------------------------------
def test_admin_access_denial_logs_and_audit_carry_no_token_from_the_referer(app, captured) -> None:
    token = _token()
    response = app.test_client().get("/admin/users", headers={"Referer": f"{HOST}/guest/files/{token}"})
    assert response.status_code == 403
    assert any("Admin alani oturumsuz erisim reddedildi" in m for m in captured.messages), captured.messages[:5]
    assert not [m for m in captured.messages if token in m]
    audit = _audit_text(app)
    assert "admin_access_denied_unauthenticated" in audit
    assert token not in audit


def test_method_not_allowed_log_carries_no_token_from_the_referer(app, captured) -> None:
    token = _token()
    response = app.test_client().delete("/login", headers={"Referer": f"{HOST}/guest/upload/{token}"})
    assert response.status_code == 405
    assert any("405 Method Not Allowed" in m for m in captured.messages), captured.messages[:5]
    assert not [m for m in captured.messages if token in m]
    assert any("/guest/upload/***" in m for m in captured.messages)


def test_expired_csrf_logs_carry_no_token_but_the_user_returns_to_the_guest_page(app, captured) -> None:
    """Etkin CSRF işleyicisi (app/__init__.py) Referer'a güvenli geri dönüş yapar; günlükte belirteç yok."""
    app.config["WTF_CSRF_ENABLED"] = True
    token = _token()
    referer = f"http://localhost/guest/files/{token}"
    response = app.test_client().post("/login", data={"sicil_or_email": "x", "password": "y"}, headers={"Referer": referer})
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/guest/files/{token}")  # geri dönüş davranışı değişmez
    assert any("CSRF token is missing" in m for m in captured.messages), captured.messages[:5]
    assert not [m for m in captured.messages if token in m]
