"""Phase 13B security closure -- CSRF negatives and object/unit-scope negatives.

Covers: missing/invalid CSRF on the assistant role-matrix write (CSRF is a
real, correctly-armed control in this app -- these tests lock that it stays
armed), the interim-notes cross-user/cross-unit scope fix (NEW-13B-01), and
the support-ticket private cross-unit scope fix (NEW-1).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

_PHASE13B_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "phase13b" / "test_dbs"


def _make_app(monkeypatch, **config_overrides):
    _PHASE13B_TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _PHASE13B_TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase13b-csrf-and-scope-negatives")
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
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    app.config.update(config_overrides)

    from app.extensions import db
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has

    return app


def _create_user(app, *, sicil_no, email, role="personel", birim=None, password="Phase13bTestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Phase13b",
            soyad="Test",
            role=role,
            birim=birim,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password="Phase13bTestKey1!"):
    payload = {"sicil_or_email": sicil_no, "password": password}
    if client.application.config.get("WTF_CSRF_ENABLED"):
        payload["csrf_token"] = _harvest_csrf_token(client)
    response = client.post("/login", data=payload, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _harvest_csrf_token(client) -> str:
    # /pwa/csrf-refresh issues a valid, session-bound CSRF token as JSON
    # regardless of authentication state (works for an already-logged-in
    # client, unlike /login which redirects away once authenticated).
    response = client.get("/pwa/csrf-refresh")
    assert response.status_code == 200
    token = response.get_json().get("csrf_token")
    assert token
    return token


def _role_matrix_value(app, *, role_name, menu_key):
    from app.extensions import db
    from app.models import RoleMenuDefault

    with app.app_context():
        row = (
            db.session.query(RoleMenuDefault)
            .filter_by(role_name=role_name, menu_key=menu_key)
            .order_by(RoleMenuDefault.id.desc())
            .first()
        )
        return None if row is None else bool(row.is_visible)


def _seed_role_matrix_row(app, *, role_name, menu_key, is_visible):
    from app.extensions import db
    from app.models import RoleMenuDefault

    with app.app_context():
        row = db.session.query(RoleMenuDefault).filter_by(role_name=role_name, menu_key=menu_key).first()
        if row is None:
            row = RoleMenuDefault(role_name=role_name, menu_key=menu_key, is_visible=is_visible, source_type="seed")
            db.session.add(row)
        else:
            row.is_visible = is_visible
        db.session.commit()


# --- #17/#18: CSRF negatives on the role-matrix write ---


def test_role_matrix_write_missing_csrf_denied(monkeypatch):
    app = _make_app(monkeypatch, WTF_CSRF_ENABLED=True)
    _create_user(app, sicil_no="13d001", email="p13b.csrfmissing@ktb.gov.tr", role="admin")
    _seed_role_matrix_row(app, role_name="kullanici", menu_key="assistant_module", is_visible=False)
    client = app.test_client()
    _login(client, "13d001")

    response = client.post(
        "/settings/assistant-role-matrix-v10/save",
        data={"assistant_matrix__assistant_module__kullanici": "on"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 400, 403)
    assert "/settings" not in response.headers.get("Location", "")
    assert _role_matrix_value(app, role_name="kullanici", menu_key="assistant_module") is False


def test_role_matrix_write_invalid_csrf_denied(monkeypatch):
    app = _make_app(monkeypatch, WTF_CSRF_ENABLED=True)
    _create_user(app, sicil_no="13d002", email="p13b.csrfinvalid@ktb.gov.tr", role="admin")
    _seed_role_matrix_row(app, role_name="kullanici", menu_key="assistant_settings", is_visible=False)
    client = app.test_client()
    _login(client, "13d002")

    response = client.post(
        "/settings/assistant-role-matrix-v10/save",
        data={
            "assistant_matrix__assistant_settings__kullanici": "on",
            "csrf_token": "garbage-token-not-a-real-csrf-value",
        },
        follow_redirects=False,
    )

    assert response.status_code in (302, 400, 403)
    assert "/settings" not in response.headers.get("Location", "")
    assert _role_matrix_value(app, role_name="kullanici", menu_key="assistant_settings") is False


def test_role_matrix_write_with_valid_csrf_still_succeeds(monkeypatch):
    # Positive control: CSRF enforcement must not collateral-damage a
    # legitimate authorized submission.
    app = _make_app(monkeypatch, WTF_CSRF_ENABLED=True)
    admin_id = _create_user(app, sicil_no="13d003", email="p13b.csrfvalid@ktb.gov.tr", role="admin")
    _seed_role_matrix_row(app, role_name="kullanici", menu_key="assistant_my_reminders", is_visible=False)
    # BYS360_P13B_TEST_ISOLATION: the *separate* assistant-module feature gate
    # (app/services/assistant_module_access.py, unrelated to the route under
    # test) consults a per-user override first. Other tests sharing this
    # process's cumulative DB may have left role-level defaults in a state
    # that would otherwise redirect this admin away before ever reaching the
    # view; an explicit per-user override sidesteps that unrelated gate
    # deterministically, regardless of prior test ordering.
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        db.session.add(UserMenuPermission(user_id=admin_id, menu_key="assistant_module", is_visible=True, source_type="seed"))
        db.session.commit()

    client = app.test_client()
    _login(client, "13d003")
    token = _harvest_csrf_token(client)

    response = client.post(
        "/settings/assistant-role-matrix-v10/save",
        data={"assistant_matrix__assistant_my_reminders__kullanici": "on", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert _role_matrix_value(app, role_name="kullanici", menu_key="assistant_my_reminders") is True


# --- #19: wrong-unit / cross-user object access denied ---


def test_interim_notes_wrong_scope_denied(monkeypatch):
    app = _make_app(monkeypatch)
    manager_id = _create_user(app, sicil_no="13d010", email="p13b.mgr@ktb.gov.tr", role="birim_sorumlusu", birim="Birim-A")
    victim_id = _create_user(app, sicil_no="13d011", email="p13b.notesvictim@ktb.gov.tr", role="personel", birim="Birim-A")
    # The "snoop" must itself pass the screen's own access gate (it is a
    # manager-family role, just from an unrelated unit with no reporting
    # relationship to the victim) -- otherwise this would only prove the
    # unrelated top-level role gate works, not the object/unit-scope fix.
    _create_user(app, sicil_no="13d012", email="p13b.snoop@ktb.gov.tr", role="koordinator", birim="Birim-B")

    from app.extensions import db
    from app.models import User

    with app.app_context():
        victim = db.session.get(User, victim_id)
        manager = db.session.get(User, manager_id)
        assert victim is not None
        assert manager is not None
        victim.yonetici_sicil = manager.sicil_no
        db.session.commit()

    manager_client = app.test_client()
    _login(manager_client, "13d010")
    create_response = manager_client.post(
        "/performance/interim-notes",
        data={
            "personnel_id": str(victim_id),
            "note_type": "olumsuz",
            "note": "BYS360-P13B-CONFIDENTIAL-NOTE-MARKER",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302

    snoop_client = app.test_client()
    _login(snoop_client, "13d012")
    snoop_view = snoop_client.get("/performance/interim-notes")
    assert b"BYS360-P13B-CONFIDENTIAL-NOTE-MARKER" not in snoop_view.data

    snoop_write = snoop_client.post(
        "/performance/interim-notes",
        data={
            "personnel_id": str(victim_id),
            "note_type": "olumsuz",
            "note": "INJECTED-BY-UNRELATED-PERSONEL",
        },
        follow_redirects=False,
    )
    assert snoop_write.status_code == 302

    from app.extensions import db as db2

    with app.app_context():
        rows = db2.session.execute(
            db2.text("SELECT note FROM performance_interim_notes_live WHERE personnel_id = :pid"),
            {"pid": victim_id},
        ).fetchall()
        notes = [r[0] for r in rows]
        assert "INJECTED-BY-UNRELATED-PERSONEL" not in notes


# --- bonus (NEW-1): support ticket private cross-unit access denied ---


def test_support_ticket_private_cross_unit_denied(monkeypatch):
    app = _make_app(monkeypatch)
    _create_user(app, sicil_no="13d020", email="p13b.ticketowner@ktb.gov.tr", role="personel", birim="Birim-A")
    _create_user(app, sicil_no="13d021", email="p13b.othermanager@ktb.gov.tr", role="birim_sorumlusu", birim="Birim-B")

    from app.extensions import db
    from app.models import SupportTicket, User

    with app.app_context():
        owner = db.session.query(User).filter_by(sicil_no="13d020").first()
        assert owner is not None
        ticket = SupportTicket(
            ticket_no="P13B-TEST-0001",
            title="Confidential ticket",
            description="BYS360-P13B-PRIVATE-TICKET-MARKER",
            ticket_type="other",
            module_name="test",
            created_by_user_id=owner.id,
            is_private=True,
            unit_name_snapshot="Birim-A",
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    other_manager_client = app.test_client()
    _login(other_manager_client, "13d021")

    response = other_manager_client.get(f"/support/{ticket_id}", follow_redirects=False)

    assert response.status_code in (302, 403, 404)
    assert b"BYS360-P13B-PRIVATE-TICKET-MARKER" not in response.data
