"""P2-08 contract: application code defaults follow the public attribution.

Canonical public identity (README / NOTICE on the default branch):
  Developer: Havva Gülsen Özden
  Co-developer (Eş Geliştirici): Mustafa Bektaş

Final pre-live audit (2026-09-27): the Künye page, the About modal and the
assistant answers named a single developer ("Personel Gülsen ÖZDEN" /
"Havva Gülsen Özden"), and the assistant intro-hiding script recognised the
automatic intro by one exact sentence containing a person's name.

Only code defaults change here. ``system_settings`` rows override these
defaults on a live database, so an existing live row keeps its old value until
it is updated through the settings screen (LIVE SETTINGS UPDATE REQUIRED).
The existing "Proje Yürütücüsü" (project owner) entry is unchanged.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
DEVELOPER = "Havva Gülsen Özden"
CO_DEVELOPER = "Mustafa Bektaş"
V34_JS = ROOT / "app" / "static" / "js" / "bys360_assistant_no_chat_intro_open_fix_v34.js"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        db_path = tmp_path_factory.mktemp("p2_08") / "attribution.sqlite3"
        db_uri = "sqlite:///" + db_path.as_posix()
        for key, value in {
            "APP_ENV": "testing",
            "SECRET_KEY": "test-secret-key-for-p2-08-attribution-contract",
            "DEFAULT_FIRST_LOGIN_PASSWORD": "p2-08-first-login-test-pw",
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

            db.create_all()
            db.session.commit()
        yield flask_app


def test_kunye_defaults_distinguish_developer_and_co_developer() -> None:
    from app.services.kunye_settings_service import KUNYE_DEFAULTS

    assert (KUNYE_DEFAULTS["developer_label"], KUNYE_DEFAULTS["developer_name"]) == ("Geliştirici", "Havva Gülsen ÖZDEN")
    assert (KUNYE_DEFAULTS["co_developer_label"], KUNYE_DEFAULTS["co_developer_name"]) == (
        "Eş Geliştirici (Co-developer)",
        "Mustafa BEKTAŞ",
    )
    # project-owner semantics are not changed by this contract
    assert (KUNYE_DEFAULTS["project_owner_label"], KUNYE_DEFAULTS["project_owner_name"]) == ("Proje Yürütücüsü", "Mustafa BEKTAŞ")


def test_settings_catalog_defaults_match_the_code_defaults() -> None:
    from app.services.kunye_settings_service import KUNYE_DEFAULTS
    from app.services.settings.catalog import SYSTEM_SETTING_DEFINITIONS

    defaults = {item["setting_key"]: item.get("default") for item in SYSTEM_SETTING_DEFINITIONS}
    for key in ("developer_label", "developer_name", "co_developer_label", "co_developer_name"):
        assert defaults[f"kunye.{key}"] == KUNYE_DEFAULTS[key], key
    assert defaults["about.developer_name"] == DEVELOPER
    assert defaults["about.co_developer_name"] == CO_DEVELOPER


def test_kunye_page_renders_both_roles(app) -> None:
    body = app.test_client().get("/kunye").get_data(as_text=True)

    assert "Havva Gülsen ÖZDEN" in body
    assert "Eş Geliştirici (Co-developer)" in body
    assert "Personel Gülsen" not in body


def test_about_modal_context_distinguishes_both_roles(app) -> None:
    from app.template_safety import _build_about_modal_context

    with app.app_context():
        context = _build_about_modal_context()

    assert (context["developer_name"], context["co_developer_name"]) == (DEVELOPER, CO_DEVELOPER)


def test_no_stale_single_developer_default_left_in_application_code() -> None:
    offenders = []
    for path in (ROOT / "app").rglob("*"):
        if path.suffix not in {".py", ".html", ".js", ".json"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Personel Gülsen" in text or re.search(r"BYS360 için Havva Gülsen Özden tarafından geliştirildim", text):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_assistant_identity_answers_name_both_roles() -> None:
    from app.services.ai_agent import service

    source = Path(service.__file__).read_text(encoding="utf-8")
    assert f"{DEVELOPER} (geliştirici) ve {CO_DEVELOPER} (eş geliştirici)" in source
    bank = json.loads((ROOT / "app" / "assistant_training_bank" / "assistant_training_bank.json").read_text(encoding="utf-8"))
    assert f"{DEVELOPER} (geliştirici) ve {CO_DEVELOPER} (eş geliştirici)" in json.dumps(bank, ensure_ascii=False)


def test_intro_hiding_script_does_not_depend_on_a_person_name() -> None:
    source = V34_JS.read_text(encoding="utf-8")
    body = source[source.index("function isBadIntroText") : source.index("function rootEl")]
    assert DEVELOPER not in body
    assert CO_DEVELOPER not in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Merhaba, ben BYS360 Asistanı. BYS360 için Havva Gülsen Özden tarafından geliştirildim.", True),
        (f"Merhaba, ben BYS360 Asistanı. BYS360 için {DEVELOPER} (geliştirici) ve {CO_DEVELOPER} (eş geliştirici) tarafından geliştirildim.", True),
        ("Merhaba, ben BYS360 Asistanı. Bulunduğunuz ekrana göre yardımcı olurum.", True),
        ("BYS360 için X tarafından geliştirildim. Sorunuzu ekrana göre sorunuzu yazabilirsiniz.", True),
        (f"Ben BYS360 Asistanı’yım. BYS360 için {DEVELOPER} (geliştirici) ve {CO_DEVELOPER} (eş geliştirici) tarafından geliştirildim.", False),
        ("Performans dönemleri ekranı açıldı.", False),
    ],
)
def test_intro_hiding_behavior_is_stable_across_developer_text(text: str, expected: bool) -> None:
    source = V34_JS.read_text(encoding="utf-8")
    norm = source[source.index("function norm") : source.index("function isBadIntroText")]
    detector = source[source.index("function isBadIntroText") : source.index("function rootEl")]
    script = norm + detector + f"process.stdout.write(String(isBadIntroText({json.dumps(text)})));"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    assert result.stdout.strip() == ("true" if expected else "false")
