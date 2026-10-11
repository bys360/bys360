"""Contract R06: mobile messaging user pickers and participant lists expose no sicil or title.

Approved policy (HUMAN_POLICY_APPROVED, 2026-10-10): mobile user pickers must not show unnecessary
sicil (registry number) or unvan (title); least privilege; web, mobile and API follow the same rule.

Before: every logged-in mobile user could list up to 50 (v1) or 10 000 (v2) active users with
their ``sicil_no`` and ``unvan`` through the message recipient pickers
(GET /api/mobile/communication/messages/users and /communication/v2/users), and search them BY
sicil or title, which turned the picker into a sicil -> person lookup. Thread participant lists
(v1 and v2 thread detail) carried every participant's sicil (and title on v2).

Rule now: the pickers and participant lists carry what choosing a recipient needs, the id, the
name and the unit. The sicil and title keys stay in the payload for client compatibility but are
empty; search matches the name and the unit only.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "R06MobilePickerTest1!"
SICIL = "R6SICIL7788"
TITLE = "R6-UNVAN-MARKER"
UNIT = "R6 Birim Hedef"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "r06_mobile_picker" / "dbs"
SICIL_KEYS = ("registry_no", "sicil_no")
TITLE_KEYS = ("title_name", "unvan")


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-r06-mobile-picker", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "r06-mobile-picker-first-login",
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
    from app.models import MessageThread, MessageThreadParticipant, User

    with flask_app.app_context():
        db.create_all()
        viewer = User(sicil_no="R6VIEW", email="r6view@example.gov.tr", ad="Bakan", soyad="Kullanici", role="personel",
                      birim="R6 Birim Bakan", is_active=True, must_change_password=False, must_set_security_question=False)
        target = User(sicil_no=SICIL, email="r6target@example.gov.tr", ad="Hedefkisi", soyad="Rsix", role="personel",
                      birim=UNIT, unvan=TITLE, is_active=True, must_change_password=False,
                      must_set_security_question=False)
        for user in (viewer, target):
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.flush()
        thread = MessageThread(thread_type="direct", subject="R6 konusma", created_by_user_id=viewer.id, is_active=True)
        db.session.add(thread)
        db.session.flush()
        for user in (viewer, target):
            db.session.add(MessageThreadParticipant(thread_id=thread.id, user_id=user.id))
        db.session.commit()
        flask_app.config["_R06"] = {"viewer": viewer.id, "target": target.id, "thread": thread.id}
    return flask_app


def _headers(app):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, app.config["_R06"]["viewer"])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _get(app, path):
    response = app.test_client().get(path, headers=_headers(app))
    assert response.status_code == 200, (path, response.status_code)
    return response


def _target_rows(payload, target_id):
    rows = payload.get("users") or payload.get("participants") or []
    return [row for row in rows if int(row.get("id") or row.get("user_id") or 0) == target_id]


PICKERS = ["/api/mobile/communication/messages/users", "/api/mobile/communication/v2/users"]
THREADS = ["/api/mobile/communication/messages/threads/{thread}", "/api/mobile/communication/v2/threads/{thread}"]


@pytest.mark.parametrize("path", PICKERS)
def test_pickers_list_name_and_unit_without_sicil_or_title(app, path):
    response = _get(app, path)
    body = response.get_data(as_text=True)
    assert SICIL not in body and TITLE not in body
    rows = _target_rows(response.get_json(), app.config["_R06"]["target"])
    assert len(rows) == 1
    assert "Hedefkisi" in rows[0]["display_name"] and rows[0]["unit_name"] == UNIT
    for key in SICIL_KEYS + TITLE_KEYS:
        assert rows[0].get(key, "") == "", key


@pytest.mark.parametrize("path", PICKERS)
@pytest.mark.parametrize("query", [SICIL, SICIL[-4:], TITLE])
def test_pickers_cannot_be_searched_by_sicil_or_title(app, path, query):
    response = _get(app, f"{path}?q={query}")
    assert _target_rows(response.get_json(), app.config["_R06"]["target"]) == []
    assert SICIL not in response.get_data(as_text=True)


@pytest.mark.parametrize("path", PICKERS)
@pytest.mark.parametrize("query", ["hedefkisi", "r6 birim hedef"])
def test_pickers_still_find_people_by_name_and_unit(app, path, query):
    response = _get(app, f"{path}?q={query}")
    assert len(_target_rows(response.get_json(), app.config["_R06"]["target"])) == 1


@pytest.mark.parametrize("path", THREADS)
def test_thread_participants_carry_no_sicil_or_title(app, path):
    response = _get(app, path.format(thread=app.config["_R06"]["thread"]))
    body = response.get_data(as_text=True)
    assert SICIL not in body and TITLE not in body
    payload = response.get_json()
    thread = payload.get("thread") if isinstance(payload.get("thread"), dict) else payload
    participants = thread.get("participants") or payload.get("participants") or []
    assert any(int(p.get("id") or 0) == app.config["_R06"]["target"] for p in participants)
