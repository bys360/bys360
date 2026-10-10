"""BYS360 support ticket status history -- raw DB status leak closure (H1D).

Root cause (found during the H1D repo-wide scan, same defect class as the
Phase 8 "checkpoint" action_type leak fixed in H1B): SupportTicket /
SupportTicketStatusHistory.status values are stored as raw English codes
("open", "reviewing", "resolved", ...) and were rendered VERBATIM in two
templates:

  - app/templates/support/detail.html (ticket status-history timeline)
  - app/templates/communication/phase5_support_operations.html
    ("Son hareketler" table)

even though a ready-made Turkish label mapping (SUPPORT_STATUS_CHOICES /
_status_map() in app/support/routes.py) already existed and was already used
elsewhere in the same file, just not passed into these two render calls.

Fix: both routes now pass status_labels (a dict built from the single
existing SUPPORT_STATUS_CHOICES source of truth) into their templates; the
templates do a display-only .get(value, value) lookup. The stored DB values
(SupportTicketStatusHistory.old_status/new_status) are completely
untouched -- this is presentation-only.

This file writes NOTHING to any production source file -- only to its own
isolated, temporary SQLite DB (same pattern established in
tests/communication/test_phase8_checkpoint_turkish_terminology_contract.py).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "support_status_turkish_tmp" / "test_dbs"
_PASSWORD = "SupportStatusTurkishTest1!"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-support-status-turkish-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "support-status-first-login-test-pw")
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
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD, menu_keys=("support_index", "support")):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="Support",
            soyad="StatusContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        for menu_key in menu_keys:
            db.session.add(UserMenuPermission(user_id=user.id, menu_key=menu_key, is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def test_ticket_detail_status_history_shows_turkish_labels_not_raw_english_codes(app, client) -> None:
    from app.extensions import db
    from app.models import SupportTicket, SupportTicketStatusHistory

    user_id = _create_user(app, sicil_no="sup_admin_detail")
    with app.app_context():
        ticket = SupportTicket(
            ticket_no="DTY-TEST-0001",
            title="H1D contract ticket",
            description="Test",
            ticket_type="bug",
            module_name="support",
            status="reviewing",
            created_by_user_id=user_id,
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(SupportTicketStatusHistory(ticket_id=ticket.id, old_status=None, new_status="open", changed_by_user_id=user_id))
        db.session.add(SupportTicketStatusHistory(ticket_id=ticket.id, old_status="open", new_status="reviewing", changed_by_user_id=user_id))
        db.session.commit()
        ticket_id = ticket.id

    _login(client, "sup_admin_detail")
    response = client.get(f"/support/{ticket_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "İlk kayıt" in body
    assert "Açıldı" in body
    assert "İnceleniyor" in body
    # The raw English DB codes must not leak into the rendered timeline text.
    assert "İlk kayıt → open" not in body
    assert "open → reviewing" not in body


def test_phase5_support_operations_recent_history_shows_turkish_labels(app, client) -> None:
    from app.extensions import db
    from app.models import SupportTicket, SupportTicketStatusHistory

    # K5-Q1: the Faz 5 support screens need the explicit per-person support_all grant.
    user_id = _create_user(app, sicil_no="sup_admin_ops", menu_keys=("support_index", "support", "support_all"))
    with app.app_context():
        ticket = SupportTicket(
            ticket_no="DTY-TEST-0002",
            title="H1D ops contract ticket",
            description="Test",
            ticket_type="bug",
            module_name="support",
            status="resolved",
            created_by_user_id=user_id,
        )
        db.session.add(ticket)
        db.session.commit()
        db.session.add(SupportTicketStatusHistory(ticket_id=ticket.id, old_status="assigned", new_status="resolved", changed_by_user_id=user_id))
        db.session.commit()

    _login(client, "sup_admin_ops")
    response = client.get("/communication/faz5/support-operations")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "Çözüldü" in body
    assert "<td>resolved</td>" not in body


def test_anonymous_user_still_redirected_on_both_routes(client) -> None:
    for path in ("/support/1", "/communication/faz5/support-operations"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, f"{path}: expected 302, got {response.status_code}"
        assert "/login" in (response.headers.get("Location") or "")
