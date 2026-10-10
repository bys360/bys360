"""Contract F06a (D2 follow-up): the technical roles get no institution-wide interim (private) notes.

Approved decision D2 (HUMAN_POLICY_APPROVED, 2026-10-09): ``sistem_yoneticisi`` keeps its technical
administration functions but gets no automatic access to personnel data, performance data or
private notes.

``app/performance/interim_notes_manager_routes.py`` put ``sistem_yoneticisi`` and ``system_admin``
in ``ADMIN_ROLES``. ``_is_admin_like()`` then removed both filters of the manager screen
(``/performance/interim-notes``): the employee list (``_people``) and the notes list. A technical
administrator read every employee's in-period notes, negative incidents included, and could write
a note about anyone (``_allowed_employee``), through the screen and through
``/performance/interim-notes/create``.

Rule now: the technical roles are line managers like any other role in ``ALLOWED_ROLES``. They see
and write notes only for the people who report to them (``yonetici_sicil``). admin and başkan keep
the institution-wide view.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

PASSWORD = "F06aInterimNotesTest1!"
MARKER = "BYS360-F06A-PRIVATE-NOTE-MARKER"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "f06a_interim_notes" / "dbs"
TECHNICAL = ["sistem_yoneticisi", "system_admin"]


@pytest.fixture
def app(monkeypatch, install_interim_notes_schema):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-f06a-interim-notes", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "f06a-interim-notes-first-login",
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
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        install_interim_notes_schema(db.engine)
        users = {}
        for sicil, role, manager in (
            ("F6MGR", "birim_sorumlusu", None),   # the victim's real manager
            ("F6VIC", "personel", "F6MGR"),       # the person the notes are about
            ("F6TECH", "sistem_yoneticisi", None),
            ("F6SYS", "system_admin", None),
            ("F6TREP", "personel", "F6TECH"),     # reports to the technical administrator
            ("F6ADM", "admin", None),
            ("F6BSK", "baskan", None),
        ):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Not", soyad=sicil, role=role,
                        yonetici_sicil=manager, birim="Birim-A", is_active=True, must_change_password=False,
                        must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()
        flask_app.config["_IDS"] = {sicil: user.id for sicil, user in users.items()}
        db.session.commit()
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


def _write_live_note(app, author, about, note):
    return _client(app, author).post("/performance/interim-notes",
                                     data={"personnel_id": str(app.config["_IDS"][about]), "note_type": "olumsuz",
                                           "note": note})


def _live_notes(app, about):
    from app.extensions import db

    with app.app_context():
        rows = db.session.execute(text("SELECT note FROM performance_interim_notes_live WHERE personnel_id = :p"),
                                  {"p": app.config["_IDS"][about]}).fetchall()
        return [row[0] for row in rows]


def _canonical_notes(app, about):
    from app.extensions import db

    with app.app_context():
        rows = db.session.execute(text("SELECT note FROM performance_interim_notes WHERE employee_id = :p"),
                                  {"p": app.config["_IDS"][about]}).fetchall()
        return [row[0] for row in rows]


@pytest.mark.parametrize("role_sicil", ["F6TECH", "F6SYS"])
def test_technical_roles_cannot_read_other_managers_private_notes(app, role_sicil):
    assert _write_live_note(app, "F6MGR", "F6VIC", MARKER).status_code == 302
    assert MARKER in _live_notes(app, "F6VIC")
    page = _client(app, role_sicil).get("/performance/interim-notes")
    assert MARKER.encode() not in page.data


@pytest.mark.parametrize("role_sicil", ["F6TECH", "F6SYS"])
def test_technical_roles_cannot_write_notes_about_people_outside_their_reports(app, role_sicil):
    _write_live_note(app, role_sicil, "F6VIC", "F06A-INJECTED-LIVE")
    assert "F06A-INJECTED-LIVE" not in _live_notes(app, "F6VIC")
    _client(app, role_sicil).post("/performance/interim-notes/create",
                                  data={"employee_id": str(app.config["_IDS"]["F6VIC"]), "note_type": "genel_gozlem",
                                        "note": "F06A-INJECTED-CANONICAL"})
    assert "F06A-INJECTED-CANONICAL" not in _canonical_notes(app, "F6VIC")


def test_technical_role_lists_only_its_own_reports(app):
    page = _client(app, "F6TECH").get("/performance/interim-notes").get_data(as_text=True)
    assert "Not F6TREP" in page
    assert "Not F6VIC" not in page and "Not F6ADM" not in page


def test_technical_role_keeps_managing_notes_of_its_own_reports(app):
    assert _write_live_note(app, "F6TECH", "F6TREP", "F06A-OWN-REPORT-NOTE").status_code == 302
    assert "F06A-OWN-REPORT-NOTE" in _live_notes(app, "F6TREP")
    assert b"F06A-OWN-REPORT-NOTE" in _client(app, "F6TECH").get("/performance/interim-notes").data


@pytest.mark.parametrize("role_sicil", ["F6ADM", "F6BSK"])
def test_admin_and_baskan_keep_the_institution_wide_view(app, role_sicil):
    assert _write_live_note(app, "F6MGR", "F6VIC", MARKER).status_code == 302
    assert MARKER.encode() in _client(app, role_sicil).get("/performance/interim-notes").data


def test_the_real_manager_keeps_its_notes(app):
    assert _write_live_note(app, "F6MGR", "F6VIC", MARKER).status_code == 302
    assert MARKER.encode() in _client(app, "F6MGR").get("/performance/interim-notes").data
