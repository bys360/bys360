"""K13 compatibility with role_menu_defaults written by older seeders (source-known data).

The fixtures in ``tests/security/data/k13_old_seed/`` are the exact ``role_menu_defaults`` rows the
seeder of two earlier trees wrote on an empty database (regenerate with ``export_seed_rows.py``):

- ``3fd21b6b``: the last tree before K13 (the old seeder rewrote seed rows on every GET /settings, so
  a database served by it holds this state);
- ``d8b50c4c``: the 13 June 2026 baseline, the oldest tree in this repository.

Limitation: these are repository seeder outputs, not a copy of a live database. Manual rows, unit
profiles and personal exceptions of a real institution are represented only by the synthetic manual
row below; rows written before the repository history are not covered.

On the current tree, for every sampled role:
- an old seed never opens a menu key the explicit sync would not open;
- a key the sync opens but the old seed does not is always one the old seed has no row for (added
  to the static default later); the explicit real-admin sync fills it;
- viewing /settings writes nothing; the explicit sync brings the database to the synced menu and
  keeps manual rows.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent / "data" / "k13_old_seed"
FIXTURES = {"3fd21b6b": "seed_3fd21b6b.json", "d8b50c4c": "seed_d8b50c4c.json"}
ROLES = [
    "admin", "baskan", "baskan_yardimcisi", "grup_baskani", "birim_sorumlusu", "koordinator", "mali_musavir",
    "personel", "sistem_yoneticisi", "ust_yonetim", "standart_personel", "user", "ai_yoneticisi",
]
PASSWORD = "K13OldSeedCompatTest1!"
SELF_ASSESSMENT = "performance_self_assessment"
PERSONEL_CLOSED = [
    "feedback_actions", "feedback_admin", "feedback_manager", "feedback_results",
    "performance_tasks", "feedback_meetings", "performance_feedback_meetings", "support_assigned",
]
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "k13_old_seed_compat" / "dbs"


def _fixture(name: str) -> dict:
    return json.loads((DATA / FIXTURES[name]).read_text(encoding="utf-8"))


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-k13-old-seed", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "k13-old-seed-first-login-test",
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


def _load_rows(app, rows) -> None:
    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault

    with app.app_context():
        for role, key, visible, source_type in rows:
            db.session.add(RoleMenuDefault(role_name=role, menu_key=key, is_visible=visible, source_type=source_type))
        db.session.commit()


def _users(app, prefix: str) -> dict[str, int]:
    from app.extensions import db
    from app.models import User

    ids = {}
    with app.app_context():
        for index, role in enumerate(ROLES):
            sicil = f"{prefix}{index}"
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=sicil, role=role,
                        birim="Sahte Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()
            ids[role] = user.id
    return ids


def _open_menus(app, ids: dict[str, int]) -> dict[str, set[str]]:
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.route_support import build_menu_visibility_map

    menus = {}
    with app.app_context():
        for role, user_id in ids.items():
            with app.test_request_context("/"):
                user = db.session.get(User, user_id)
                login_user(user)
                menus[role] = {key for key, visible in build_menu_visibility_map(user).items() if visible}
    return menus


def _sync(app, sicil: str) -> None:
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD}).status_code == 302
    assert client.post("/settings", data={"form_action": "sync_role_defaults"}).status_code == 302


def _synced_menus(app) -> dict[str, set[str]]:
    ids = _users(app, "K13S")
    _sync(app, "K13S0")  # ROLES[0] is the real admin
    return _open_menus(app, ids)


def _role_rows(app) -> list[tuple]:
    from app.models.settings_models import RoleMenuDefault

    with app.app_context():
        return sorted((r.role_name, r.menu_key, bool(r.is_visible), r.source_type) for r in RoleMenuDefault.query.all())


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_the_fixture_is_the_recorded_seeder_output(name) -> None:
    data = _fixture(name)
    rows = data["rows"]
    provenance = data["provenance"]
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert provenance["commit"].startswith(name) and len(provenance["commit"]) == 40
    assert (provenance["row_count"], provenance["rows_sha256"]) == (len(rows), digest)
    assert {row[3] for row in rows} == {"seed"}
    assert {"personel", "admin"} <= {row[0] for row in rows}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_an_old_seed_never_opens_more_than_the_explicit_sync(app, name) -> None:
    rows = _fixture(name)["rows"]
    _load_rows(app, rows)
    old = _open_menus(app, _users(app, "K13O"))
    present = {(role, key) for role, key, _visible, _source in rows}

    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault

    with app.app_context():  # the same tree on a fresh database: the explicit sync's own result
        RoleMenuDefault.query.delete()
        db.session.commit()
    synced = _synced_menus(app)

    assert {role: sorted(old[role] - synced[role]) for role in ROLES if old[role] - synced[role]} == {}
    gaps = {(role, key) for role in ROLES for key in synced[role] - old[role]}
    assert {gap for gap in gaps if gap in present} == set(), "a gap is only a key the old seed has no row for"
    assert old["personel"].isdisjoint(PERSONEL_CLOSED)
    assert SELF_ASSESSMENT in old["personel"]


def test_viewing_settings_on_an_old_seed_database_writes_nothing(app) -> None:
    _load_rows(app, _fixture("d8b50c4c")["rows"])
    _users(app, "K13V")
    before = _role_rows(app)
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": "K13V0", "password": PASSWORD}).status_code == 302
    assert client.get("/settings").status_code == 200
    assert _role_rows(app) == before


def test_the_explicit_sync_brings_an_old_seed_to_the_synced_menu_and_keeps_manual_rows(app) -> None:
    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault

    rows = _fixture("d8b50c4c")["rows"]
    manual = ("personel", "surveys", False, "manual")  # a manual decision next to the old seed
    _load_rows(app, [row for row in rows if (row[0], row[1]) != manual[:2]] + [list(manual)])
    ids = _users(app, "K13M")
    _sync(app, "K13M0")
    after_sync = _open_menus(app, ids)
    assert manual in _role_rows(app)
    with app.app_context():
        assert db.session.execute(db.text("SELECT COUNT(*) FROM audit_logs WHERE action = 'settings.role_defaults_sync'")).scalar() == 1
        RoleMenuDefault.query.delete()
        db.session.commit()
    synced = _synced_menus(app)
    assert "surveys" in synced["personel"], "the manual row closes a key the sync would open"
    synced["personel"].discard("surveys")
    assert after_sync == synced
