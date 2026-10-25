"""Behavior contract for the BYS360 homepage (app/routes.py::home(), rendered
via app/templates/home.html).

BYS360_HOME_KARAR_DESTEK_KARTI_SUMMARY_REMOVED_CONTRACT

The homepage used to render a "Karar Destek Merkezi / Canlı Hazırlık ve
Kontrol Özeti" summary card at the bottom of the page (previously included
from app/templates/ai_decision/_final_gate_panel.html via
`home-faz1-ai-decision-wrap`). That card is intentionally no longer included
on the homepage -- this is a UI-only removal; the underlying panel partial,
its route targets, and its dedicated page
(app/templates/ai_decision/faz12_final_gate.html) are untouched and keep
rendering it elsewhere.

This test hits the real, authenticated /home route through a Flask test
client and asserts against the actual rendered response body -- not source
text or line positions -- so it fails if the block is ever reintroduced on
the homepage, and also fails (rather than false-passing) if the homepage
route starts swallowing a real template error into its safe_render()
fallback, by also requiring known-good homepage content to be present.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "home_page_summary_removed_tmp" / "test_dbs"
DEFAULT_PASSWORD = "HomePageSummaryTest1!"

_REMOVED_BLOCK_STRINGS = [
    "Canlı Hazırlık ve Kontrol Özeti",
    "Karar yerine destek üretir.",
    "Kontrol Kartını Aç",
    "Canlı Kontroller",
    "İnsan denetimli kontrol",
]


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-home-page-summary-removed-contract")
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

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
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


def _create_user(app, *, sicil_no, email, role="personel"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Home",
            soyad="Contract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": DEFAULT_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def test_home_page_no_longer_renders_decision_support_summary_block(app, client):
    _create_user(app, sicil_no="hp001", email="hp001@ktb.gov.tr")
    _login(client, "hp001")

    response = client.get("/home")

    assert response.status_code == 200
    body = response.get_data(as_text=True)

    # Proves this is a genuine successful render of home.html, not
    # safe_render()'s generic error fallback silently swallowing a break.
    assert "Gün Özeti" in body
    assert "Aktif dönem" in body

    for removed_text in _REMOVED_BLOCK_STRINGS:
        assert removed_text not in body, f"anasayfada kaldırılmış blok metni bulundu: {removed_text!r}"
