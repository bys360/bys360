"""K2-b: the assistant's own menu map follows the K2 ceiling for per-user rows.

Root cause: ``app/services/menu_visibility.py`` (``build_assistant_menu_visibility_map``) reads
``user_menu_permissions`` directly for the ``/ai-agent/*`` URL guards (``app/ai_agent/routes.py``)
and never went through the F/K2 ceiling of the main menu map. A legacy per-user row outside the role
definition (``ai_agent_teaching_center`` for personel) still opened ``/ai-agent/teaching-center``
although the main menu map closed the same key.

Rule (owner decision 2026-10-18, K2-b): a per-user row that the K2 ceiling would not recognise grants
nothing in the assistant map either; role defaults, closing rows, the real admin, a real admin's
exception and the explicit grants keep working. The knowledge base keeps its own role check.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "AsistanMenuTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "assistant_menu_legacy" / "dbs"
# Markers that only the page body renders (menu labels with the same names appear in every layout).
TEACHING = ("/ai-agent/teaching-center", 'data-bys360-screen="assistant-teaching-center"')
KNOWLEDGE = ("/ai-agent/knowledge", "Soru kalıbı ve cevap ekle")
OUTSIDE_PERSONEL = ["ai_agent_knowledge", "ai_teaching_center", "ai_agent_teaching_center"]


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-assistant-menu", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "assistant-menu-first-login-test",
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
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


def _user(app, sicil: str, role: str, rows: dict[str, tuple[bool, str]] | None = None) -> int:
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=sicil, role=role,
                    birim="Sahte Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        for key, (visible, source_type) in (rows or {}).items():
            db.session.add(UserMenuPermission(user_id=user.id, menu_key=key, is_visible=visible, source_type=source_type))
        db.session.commit()
        return user.id


def _maps(app, user_id: int, keys) -> tuple[dict[str, bool], dict[str, bool]]:
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.route_support import build_menu_visibility_map
    from app.services.menu_visibility import build_assistant_menu_visibility_map

    with app.app_context(), app.test_request_context("/"):
        user = db.session.get(User, user_id)
        login_user(user)
        main, assistant = build_menu_visibility_map(user), build_assistant_menu_visibility_map(user)
        return {k: bool(main.get(k)) for k in keys}, {k: bool(assistant.get(k)) for k in keys}


def _get(app, sicil: str, path: str):
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD}).status_code == 302
    return client.get(path)


def _opens(response, marker: str) -> bool:
    return response.status_code == 200 and marker in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 1. A legacy row outside the role definition opens nothing (assistant map = main map = HTTP)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", OUTSIDE_PERSONEL)
def test_legacy_row_outside_the_role_definition_opens_no_assistant_tab(app, key) -> None:
    uid = _user(app, "AS-ESKI", "personel", {key: (True, "user_override")})
    main, assistant = _maps(app, uid, [key])
    assert main == {key: False}
    assert assistant == {key: False}, key


def test_legacy_teaching_row_does_not_open_the_teaching_center(app) -> None:
    _user(app, "AS-ESKI", "personel", {"ai_agent_teaching_center": (True, "user_override")})
    response = _get(app, "AS-ESKI", TEACHING[0])
    assert response.status_code == 403
    assert TEACHING[1] not in response.get_data(as_text=True)


@pytest.mark.parametrize("key", ["ai_agent_knowledge", "ai_teaching_center"])
def test_legacy_knowledge_row_does_not_open_the_knowledge_base(app, key) -> None:
    _user(app, "AS-ESKI", "personel", {key: (True, "user_override")})
    response = _get(app, "AS-ESKI", KNOWLEDGE[0])
    assert response.status_code == 403
    assert KNOWLEDGE[1] not in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 2. Legitimate access keeps working
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["admin", "baskan"])
def test_role_defaults_still_open_both_tabs(app, role) -> None:
    _user(app, "AS-ROL", role)
    assert _opens(_get(app, "AS-ROL", TEACHING[0]), TEACHING[1]), role
    assert _opens(_get(app, "AS-ROL", KNOWLEDGE[0]), KNOWLEDGE[1]), role


def test_a_real_admin_exception_opens_the_teaching_center(app) -> None:
    _user(app, "AS-ISTISNA", "personel", {"ai_agent_teaching_center": (True, "admin_exception")})
    assert _opens(_get(app, "AS-ISTISNA", TEACHING[0]), TEACHING[1])


def test_the_knowledge_base_keeps_its_own_role_check(app) -> None:
    """Even a real admin's exception for the tab does not make personel a knowledge manager."""
    from app.extensions import db

    _user(app, "AS-ISTISNA", "personel", {"ai_agent_knowledge": (True, "admin_exception")})
    response = _get(app, "AS-ISTISNA", KNOWLEDGE[0])
    assert not _opens(response, KNOWLEDGE[1])
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": "AS-ISTISNA", "password": PASSWORD}).status_code == 302
    client.post(KNOWLEDGE[0], data={"title": "sahte", "question_patterns": "sahte soru", "answer": "sahte cevap"})
    with app.app_context():
        from sqlalchemy import inspect, text

        if "ai_agent_knowledge_entries" in inspect(db.engine).get_table_names():
            assert db.session.execute(text("SELECT COUNT(*) FROM ai_agent_knowledge_entries")).scalar() == 0


def test_a_closing_row_still_closes_a_role_default(app) -> None:
    _user(app, "AS-KAPALI", "baskan", {"ai_agent_teaching_center": (False, "user_override")})
    assert _get(app, "AS-KAPALI", TEACHING[0]).status_code == 403


def test_the_real_admin_keeps_its_own_rows(app) -> None:
    _user(app, "AS-ADMIN", "admin", {key: (True, "user_override") for key in OUTSIDE_PERSONEL})
    assert _opens(_get(app, "AS-ADMIN", TEACHING[0]), TEACHING[1])
