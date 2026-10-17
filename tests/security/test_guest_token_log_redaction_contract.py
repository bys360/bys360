"""Misafir dosya bağlantısı belirteci günlüklere açık metin olarak yazılmaz.

Kök neden: /guest/files/<token> ve /guest/upload/<token> yollarında belirteç, bağlantının tek
sırrıdır (veritabanında SHA-256 özetiyle aranır). İşlem erişim günlüğü (bys360.ops), yavaş
istek ve 5xx kayıtları, bakım modu reddi ve request_log_context yardımcıları ``request.path``
ve ``request.full_path`` değerini olduğu gibi yazıyordu; günlük dosyasını okuyabilen herkes
her misafir bağlantısını kullanabilirdi.

Düzeltme yol biçimini korur, yalnız belirteç bölümünü ``***`` ile maskeler; diğer yollar değişmez.
"""
from __future__ import annotations

import logging
import secrets
import tempfile
import uuid
from pathlib import Path

import pytest

_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "guest_token_log" / "dbs"


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-guest-token-log", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "guest-token-log-first-login",
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
    return flask_app


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def captured(app):
    handler = _Collect()
    loggers = [logging.getLogger("bys360.ops"), app.logger]
    for logger in loggers:
        logger.addHandler(handler)
    yield handler
    for logger in loggers:
        logger.removeHandler(handler)


@pytest.mark.parametrize("prefix", ["/guest/files/", "/guest/upload/"])
def test_access_and_slow_request_logs_do_not_contain_the_guest_token(app, captured, prefix) -> None:
    token = secrets.token_urlsafe(32)
    app.config["SLOW_REQUEST_THRESHOLD_MS"] = 0  # yavaş istek kaydını da tetikle
    client = app.test_client()
    client.get(prefix + token)
    client.post(prefix + token, data={"password": "yanlis-sahte"})
    assert captured.messages, "istek günlüğü üretilmedi"
    leaked = [m for m in captured.messages if token in m]
    assert leaked == [], leaked
    # İzlenebilirlik korunur: maskelenmiş yol günlükte görünür.
    assert any(prefix + "***" in m for m in captured.messages), captured.messages[:5]


@pytest.mark.parametrize("module", ["app.bootstrap.request_context", "app.error_handlers"])
def test_request_log_context_masks_the_guest_token(app, module) -> None:
    import importlib

    token = secrets.token_urlsafe(32)
    helper = importlib.import_module(module).request_log_context
    with app.test_request_context(f"/guest/files/{token}?download=1"):
        context = helper()
    assert token not in str(context)
    assert context["path"] == "/guest/files/***"
    assert context["full_path"] == "/guest/files/***?download=1"


def test_other_paths_are_logged_unchanged(app) -> None:
    from app.bootstrap.request_context import request_log_context

    with app.test_request_context("/support/my-tickets?status=open"):
        context = request_log_context()
    assert context["path"] == "/support/my-tickets"
    assert context["full_path"] == "/support/my-tickets?status=open"


def test_security_audit_records_mask_the_guest_token(app) -> None:
    """record_security_event isteğin yolunu audit_logs tablosuna kalıcı yazar."""
    import json

    from app.extensions import db
    from app.models import AuditLog
    from app.services.audit_event_service import record_security_event

    token = secrets.token_urlsafe(32)
    with app.test_request_context(f"/guest/files/{token}", method="POST"):
        record_security_event("guest_link_test_event", summary="sahte olay")
    with app.app_context():
        rows = db.session.query(AuditLog).filter_by(action="guest_link_test_event").all()
        stored = json.dumps([row.new_data_json or "" for row in rows], ensure_ascii=False)
    assert rows, "denetim kaydı oluşmadı"
    assert token not in stored
    assert "/guest/files/***" in stored
