"""Final pre-live audit P3 hygiene contract (safe, deterministic subset).

- the two fixed-message HR fallback pages require login like the rest of the
  institutional HR area;
- the AI action-queue API never returns raw exception text;
- user-facing error pages use formal wording;
- no tracked text file carries stray control bytes (a Windows path written
  through an unescaped "\\b" / "\\r" / "\\a" / "\\f"), except the two quality
  gate scripts whose regex byte is a separate review item;
- no personal Windows account name in test/script comments.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
HR_FALLBACKS = ("/institutional/hr/career-planning", "/institutional/hr/reward-discipline")
# The regex byte in these gate scripts changes gate matching if "fixed"; review separately.
CONTROL_BYTE_REVIEW_ITEMS = {
    "scripts/quality/bys360_score100_quality_gate_v1.py",
    "scripts/archive/pre_handover_20260708/quality/bys360_score100_quality_gate_v1.py",
}


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        db_path = os.path.join(str(tmp_path_factory.mktemp("p3")), f"p3_{uuid.uuid4().hex}.sqlite3")
        db_uri = "sqlite:///" + db_path.replace("\\", "/")
        for key, value in {
            "APP_ENV": "testing",
            "SECRET_KEY": "test-secret-key-for-final-audit-p3-hygiene",
            "DEFAULT_FIRST_LOGIN_PASSWORD": "p3-first-login-test-pw",
            "FLASK_SKIP_SCHEMA_VALIDATION": "1",
            "AUTO_REPAIR_SCHEMA": "false",
            "STRICT_SCHEMA_CHECK": "false",
            "REQUIRE_DOTENV_FILE": "false",
            "STRICT_ENV_VALIDATION": "false",
            "WTF_CSRF_ENABLED": "false",
            "SCHEDULER_ENABLED": "false",
            "MAIL_SUPPRESS_SEND": "true",
            "DATABASE_URL": db_uri,
        }.items():
            monkeypatch.setenv(key, value)

        from app import create_app
        from config import Config

        monkeypatch.setattr(Config, "APP_ENV", "testing")
        monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
        monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
        flask_app = create_app()
        flask_app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI=db_uri,
            SQLALCHEMY_ENGINE_OPTIONS={"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
        )
        with flask_app.app_context():
            from app.extensions import db
            from app.models import User

            db.create_all()
            user = User(sicil_no="P3HYG01", email="p3.hygiene@example.gov.tr", ad="Hijyen", soyad="Personel", role="personel", is_active=True)
            user.set_password("TestP3Hygiene-2026!x")
            for flag in ("must_change_password", "must_set_security_question", "is_first_login"):
                if hasattr(user, flag):
                    setattr(user, flag, False)
            db.session.add(user)
            db.session.commit()
            flask_app.config["_P3_TEST_USER_SID"] = user.get_id()
        yield flask_app


@pytest.mark.parametrize("path", HR_FALLBACKS)
def test_hr_fallback_pages_require_login(app, path) -> None:
    if path not in {str(rule.rule) for rule in app.url_map.iter_rules()}:
        pytest.skip(f"{path} is served by a real endpoint in this build")
    response = app.test_client().get(path, follow_redirects=False)

    assert response.status_code in (302, 401)
    assert "login" in (response.headers.get("Location") or "").lower() or response.status_code == 401


@pytest.mark.parametrize("path", HR_FALLBACKS)
def test_hr_fallback_pages_still_render_for_signed_in_users(app, path) -> None:
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = app.config["_P3_TEST_USER_SID"]
        sess["_fresh"] = True

    assert client.get(path).status_code == 200


def test_ai_action_queue_error_never_returns_raw_exception_text(app, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.services.ai_agent import action_queue_bridge as bridge

    def _boom(*_args, **_kwargs):
        raise RuntimeError("SELECT secret FROM ai_agent_action_queue -- internal detail")

    template_key = next(iter(bridge._TEMPLATE_BY_KEY))
    monkeypatch.setattr(bridge, "table_exists", lambda _name: True)
    with app.app_context():
        monkeypatch.setattr(bridge.db.session, "execute", _boom)
        result = bridge.create_controlled_action_queue_suggestion(SimpleNamespace(id=1), template_key)

    assert result["ok"] is False and result["status"] == "failed"
    assert "internal detail" not in result["error"]
    assert "SELECT" not in result["error"]


def test_error_handler_wording_is_formal() -> None:
    source = (ROOT / "app" / "error_handlers.py").read_text(encoding="utf-8")
    for informal in ("orada kestim", "homurdandı", "Bir işlem koyup"):
        assert informal not in source


def _tracked_text_files() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [name for name in listed.decode("utf-8").split("\0") if name]


def test_no_stray_control_bytes_in_tracked_text_files() -> None:
    offenders = []
    for rel in _tracked_text_files():
        path = ROOT / rel
        if rel in CONTROL_BYTE_REVIEW_ITEMS or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue  # binary
        if re.search(rb"[\x07\x08\x0c]", data):
            offenders.append(rel)
    assert offenders == []


def test_no_personal_windows_account_name_in_tests_or_scripts() -> None:
    offenders = []
    for rel in _tracked_text_files():
        if not rel.startswith(("tests/", "scripts/")) or not rel.endswith((".py", ".ps1", ".md", ".txt")):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if "HAVVAG~" in text or re.search(r"Users[\\/]+Havva", text):
            offenders.append(rel)
    assert offenders == []
