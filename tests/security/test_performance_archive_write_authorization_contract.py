"""Contract: only archive managers can add or import historical performance scores.

/performans/gecmis-karne-arsivi/yeni (manual entry), /excel (Excel import) and
/excel-sablon (template) are gated by can_manage_archive (MANUAL_ENTRY_ROLES). They
write historical scores and had no authorization test; an employee or a unit manager
must be refused and must not be able to create a record.
"""
from __future__ import annotations

import io
import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "ArchiveWriteAuthTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "archive_write_auth" / "dbs"
_PAGES = ("/performans/gecmis-karne-arsivi/yeni", "/performans/gecmis-karne-arsivi/excel",
          "/performans/gecmis-karne-arsivi/excel-sablon")


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-archive-write-auth", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "archive-write-auth-first-login",
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
    from app.models import User

    with flask_app.app_context():
        db.create_all()
        for sicil, role in (("PAW01", "personel"), ("PAW02", "birim_sorumlusu"), ("PAW03", "admin")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Archive", soyad=sicil, role=role,
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()
        flask_app.config["_EMPLOYEE_ID"] = User.query.filter_by(sicil_no="PAW01").one().id
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _archived_count(app):
    from app.models import PerformanceArchivedResult

    with app.app_context():
        return PerformanceArchivedResult.query.count()


@pytest.mark.parametrize("sicil", ["PAW01", "PAW02"])
def test_non_archive_roles_are_refused(app, sicil):
    client = _client(app, sicil)
    for path in _PAGES:
        assert client.get(path).status_code == 403, path
    client.post(_PAGES[0], data={"employee_id": app.config["_EMPLOYEE_ID"], "result_year": "2024",
                                 "period_label": "2024", "score": "90"})
    client.post(_PAGES[1], data={"archive_excel": (io.BytesIO(b"not a workbook"), "arsiv.xlsx")},
                content_type="multipart/form-data")
    assert _archived_count(app) == 0


def test_admin_can_open_the_archive_write_pages(app):
    client = _client(app, "PAW03")
    for path in _PAGES:
        assert client.get(path).status_code == 200, path
