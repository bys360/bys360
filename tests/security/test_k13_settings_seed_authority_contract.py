"""K13: viewing /settings grants nothing; automatic seed rows never lift personel above the role definition.

Root cause (18 Oct 2026 analysis, file:line re-resolved on the current tree):
- ``settings_page`` (app/main_handlers/account_settings_helpers.py) called
  ``ensure_settings_phase1_seeded`` on every request, GET included. The seeder
  (app/services/settings/foundation_access.py) wrote ``role_menu_defaults`` rows with
  ``source_type="seed"`` from the static ``ROLE_MENU_DEFAULTS`` and committed.
- The static personel default held eight keys whose menu definition (``required_roles``) excludes
  personel. Once a seed row existed, the live authority layer skipped the static role gate for that
  key, so the first GET /settings by a real admin or Başkan opened 14 performance GET routes, two
  POST operations (run-alerts, run-digest: notifications, mail_logs, audit) and /support/assigned
  to every personel.

Owner decision (night instruction, 18-19 Oct 2026): viewing /settings changes no effective
permission; the default sync is an explicit real-admin POST (CSRF, audit); performance_self_assessment
stays a legitimate personel key; the other eight keys give personel no general access, whether from
the static default or an old seed row; manual role/unit profiles, approved exceptions, support_all and
personnel_read_all are kept; run-alerts and run-digest keep their own role check (manager family, the
same set as the menu definition) so a menu exception cannot trigger them.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "K13SeedContractTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "k13_seed_authority" / "dbs"

SELF_ASSESSMENT = "performance_self_assessment"
# The eight keys of the owner decision. feedback_meetings is the alias of performance_feedback_meetings
# (never a static default itself); the other seven were in the old static personel default.
EIGHT_KEYS = [
    "feedback_actions", "feedback_admin", "feedback_manager", "feedback_results",
    "performance_tasks", "feedback_meetings", "performance_feedback_meetings", "support_assigned",
]
LEGACY_SEED_KEYS = [key for key in EIGHT_KEYS if key != "feedback_meetings"]
PERFORMANCE_GETS = [
    "/performance/feedback-ops",
    "/performance/feedback-watch",
    "/performance/feedback-executive-summary",
    "/performance/go-live-center",
    "/performance/go-live-center/uat",
    "/performance/go-live-center/uat/export.txt",
    "/performance/go-live-center/issues.csv",
    "/performance/go-live-center/release-packet.txt",
    "/performance/go-live-center/smoke-test",
    "/performance/go-live-center/smoke-test.csv",
    "/performance/go-live-center/management-brief.txt",
    "/performance/feedback-audit",
    "/performance/feedback-meetings",
    "/performance/pilot-simulation-center",
]
SUPPORT_GET = "/support/assigned"
POSTS = ["/performance/feedback-watch/run-alerts", "/performance/feedback-executive-summary/run-digest"]
PERMISSION_TABLE_HINTS = ("menu", "role", "permission", "setting", "profile", "grant", "policy")


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-k13-seed", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "k13-seed-first-login-test",
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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _user(app, sicil: str, role: str, *, birim: str = "Sahte Birim A", rows: dict[str, tuple[bool, str]] | None = None) -> int:
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Sahte", soyad=sicil, role=role,
                    birim=birim, is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        for key, (visible, source_type) in (rows or {}).items():
            db.session.add(UserMenuPermission(user_id=user.id, menu_key=key, is_visible=visible, source_type=source_type))
        db.session.commit()
        return user.id


def _client(app, sicil: str):
    client = app.test_client()
    assert client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD}).status_code == 302
    return client


def _legacy_seeded_db(app) -> None:
    """The state every live database reached: the old seeder ran (any GET /settings) and wrote the old
    static personel default, eight keys of it visible, as ``source_type="seed"`` rows."""
    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault
    from app.services.settings_service import ensure_settings_phase1_seeded

    with app.app_context():
        assert ensure_settings_phase1_seeded(updated_by_user_id=None).get("ok")
        for key in LEGACY_SEED_KEYS + [SELF_ASSESSMENT]:
            row = RoleMenuDefault.query.filter_by(role_name="personel", menu_key=key).first()
            if row is None:
                db.session.add(RoleMenuDefault(role_name="personel", menu_key=key, is_visible=True, source_type="seed"))
            else:
                row.is_visible, row.source_type = True, "seed"
        db.session.commit()


def _permission_tables(app) -> dict[str, list[str]]:
    from sqlalchemy import inspect, text

    from app.extensions import db

    with app.app_context():
        names = sorted(n for n in inspect(db.engine).get_table_names() if any(h in n for h in PERMISSION_TABLE_HINTS))
        state = {}
        for name in names:
            rows = db.session.execute(text(f'SELECT * FROM "{name}"')).fetchall()
            state[name] = sorted(repr(tuple(row)) for row in rows)
        return state


def _menu(app, user_id: int, keys) -> dict[str, bool]:
    from flask_login import login_user

    from app.extensions import db
    from app.models import User
    from app.route_support import build_menu_visibility_map

    with app.app_context(), app.test_request_context("/"):
        user = db.session.get(User, user_id)
        login_user(user)
        visibility = build_menu_visibility_map(user)
        return {key: bool(visibility.get(key)) for key in keys}


def _count(app, table: str) -> int:
    from sqlalchemy import inspect, text

    from app.extensions import db

    with app.app_context():
        if table not in inspect(db.engine).get_table_names():
            return 0
        return int(db.session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)


def _audit_actions(app) -> list[str]:
    from sqlalchemy import text

    from app.extensions import db

    with app.app_context():
        return [row[0] for row in db.session.execute(text("SELECT action FROM audit_logs ORDER BY id")).fetchall()]


def _role_row(app, role: str, key: str):
    from app.models.settings_models import RoleMenuDefault

    with app.app_context():
        row = RoleMenuDefault.query.filter_by(role_name=role, menu_key=key).first()
        return None if row is None else (bool(row.is_visible), row.source_type)


# ---------------------------------------------------------------------------
# A. Viewing /settings writes no role, profile or permission data
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("database", ["bos", "eski_seed"])
@pytest.mark.parametrize("viewer_role", ["admin", "baskan"])
def test_viewing_settings_changes_no_permission_data(app, database, viewer_role) -> None:
    if database == "eski_seed":
        _legacy_seeded_db(app)
    personel = _user(app, "K13-PER", "personel")
    _user(app, "K13-VIEW", viewer_role)
    keys = EIGHT_KEYS + [SELF_ASSESSMENT]
    tables_before, menu_before = _permission_tables(app), _menu(app, personel, keys)
    client = _client(app, "K13-VIEW")
    for _ in range(3):
        assert client.get("/settings").status_code == 200
    assert client.head("/settings").status_code == 200
    assert _permission_tables(app) == tables_before
    assert _menu(app, personel, keys) == menu_before


def test_the_static_personel_default_keeps_only_the_legitimate_key() -> None:
    from app.menu_registry import get_role_default_menu_keys

    defaults = get_role_default_menu_keys("personel")
    assert SELF_ASSESSMENT in defaults
    assert not set(EIGHT_KEYS) & defaults, sorted(set(EIGHT_KEYS) & defaults)


# ---------------------------------------------------------------------------
# B. The default sync is an explicit real-admin POST with CSRF and audit
# ---------------------------------------------------------------------------
def _csrf_token(client) -> str:
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', client.get("/settings").get_data(as_text=True))
    assert match, "csrf token not rendered on /settings"
    return match.group(1)


def test_the_real_admin_syncs_defaults_by_post_with_csrf_and_audit(app) -> None:
    _user(app, "K13-ADM", "admin")
    client = _client(app, "K13-ADM")
    app.config["WTF_CSRF_ENABLED"] = True  # after login: the session carries the CSRF secret
    assert _role_row(app, "personel", SELF_ASSESSMENT) is None
    response = client.post("/settings", data={"form_action": "sync_role_defaults", "csrf_token": _csrf_token(client)})
    assert response.status_code == 302
    assert _role_row(app, "personel", SELF_ASSESSMENT) == (True, "seed")
    for key in LEGACY_SEED_KEYS:
        assert _role_row(app, "personel", key) in (None, (False, "seed")), key
    assert "settings.role_defaults_sync" in _audit_actions(app)


def test_the_sync_rewrites_old_seed_rows_and_records_each_change(app) -> None:
    import json

    from sqlalchemy import text

    from app.extensions import db

    _legacy_seeded_db(app)
    _user(app, "K13-ADM", "admin")
    response = _client(app, "K13-ADM").post("/settings", data={"form_action": "sync_role_defaults"})
    assert response.status_code == 302
    for key in LEGACY_SEED_KEYS:
        assert _role_row(app, "personel", key) == (False, "seed"), key
    assert _role_row(app, "personel", SELF_ASSESSMENT) == (True, "seed")
    with app.app_context():
        payload = db.session.execute(
            text("SELECT new_data_json FROM audit_logs WHERE action = 'settings.role_defaults_sync'")
        ).scalar()
    assert payload is not None, "the sync is audited"
    changes = {(c["role"], c["menu_key"]): (c["before"], c["after"]) for c in json.loads(payload)["role_default_changes"]}
    for key in LEGACY_SEED_KEYS:
        assert changes[("personel", key)] == (True, False), key


def test_a_missing_csrf_token_changes_nothing(app) -> None:
    _user(app, "K13-ADM", "admin")
    client = _client(app, "K13-ADM")
    app.config["WTF_CSRF_ENABLED"] = True
    assert _csrf_token(client)  # the form is rendered; only the token is missing/forged below
    before = _permission_tables(app)
    client.post("/settings", data={"form_action": "sync_role_defaults"})
    client.post("/settings", data={"form_action": "sync_role_defaults", "csrf_token": "sahte-token"})
    assert _permission_tables(app) == before


@pytest.mark.parametrize("role", ["baskan", "baskan_yardimcisi", "sistem_yoneticisi"])
def test_no_one_but_the_real_admin_can_sync(app, role) -> None:
    _user(app, "K13-ACT", role)
    before = _permission_tables(app)
    _client(app, "K13-ACT").post("/settings", data={"form_action": "sync_role_defaults"})
    assert _permission_tables(app) == before
    assert "settings.role_defaults_sync" not in _audit_actions(app)


def test_personel_cannot_reach_the_sync(app) -> None:
    _user(app, "K13-PER", "personel")
    before = _permission_tables(app)
    response = _client(app, "K13-PER").post("/settings", data={"form_action": "sync_role_defaults"})
    assert response.status_code == 403
    assert _permission_tables(app) == before


# ---------------------------------------------------------------------------
# C/D. Personel: 14 performance GETs, /support/assigned and the two POSTs stay closed
# ---------------------------------------------------------------------------
def _prepare(app, database: str) -> None:
    if database == "eski_seed":
        _legacy_seeded_db(app)
    else:  # empty profile data, then the explicit real-admin sync
        _user(app, "K13-ADM", "admin")
        assert _client(app, "K13-ADM").post("/settings", data={"form_action": "sync_role_defaults"}).status_code == 302


@pytest.mark.parametrize("database", ["bos_ve_acik_senkron", "eski_seed"])
def test_personel_gets_no_performance_or_support_route_from_seed_rows(app, database) -> None:
    _prepare(app, database)
    personel = _user(app, "K13-PER", "personel")
    assert _menu(app, personel, EIGHT_KEYS) == {key: False for key in EIGHT_KEYS}
    client = _client(app, "K13-PER")
    opened = {path: client.get(path).status_code for path in PERFORMANCE_GETS + [SUPPORT_GET]}
    assert {path: code for path, code in opened.items() if code != 403} == {}


@pytest.mark.parametrize("database", ["bos_ve_acik_senkron", "eski_seed"])
def test_personel_keeps_self_assessment(app, database) -> None:
    _prepare(app, database)
    personel = _user(app, "K13-PER", "personel")
    assert _menu(app, personel, [SELF_ASSESSMENT]) == {SELF_ASSESSMENT: True}


@pytest.mark.parametrize("database", ["bos_ve_acik_senkron", "eski_seed"])
def test_a_refused_post_starts_no_notification_or_mail(app, database) -> None:
    _prepare(app, database)
    _user(app, "K13-PER", "personel")
    client = _client(app, "K13-PER")
    notifications, mails, audits = _count(app, "notifications"), _count(app, "mail_logs"), _audit_actions(app)
    for path in POSTS:
        assert client.post(path, data={"send_email": "1"}).status_code == 403, path
    assert _count(app, "notifications") == notifications
    assert _count(app, "mail_logs") == mails
    new_actions = _audit_actions(app)[len(audits):]
    assert not [action for action in new_actions if "feedback" in action], new_actions


def test_a_menu_exception_does_not_unlock_the_two_operations(app) -> None:
    """A real admin's exception for the screen family opens the pages, not the management operations."""
    _legacy_seeded_db(app)
    _user(app, "K13-EXC", "personel", rows={"performance_feedback_meetings": (True, "admin_exception")})
    client = _client(app, "K13-EXC")
    assert client.get("/performance/feedback-watch").status_code == 200
    notifications, mails = _count(app, "notifications"), _count(app, "mail_logs")
    for path in POSTS:
        assert client.post(path, data={"send_email": "1"}).status_code == 403, path
    assert (_count(app, "notifications"), _count(app, "mail_logs")) == (notifications, mails)


@pytest.mark.parametrize("role", ["baskan", "birim_sorumlusu"])
def test_the_management_family_keeps_pages_and_operations(app, role) -> None:
    _legacy_seeded_db(app)
    _user(app, "K13-MGR", role)
    client = _client(app, "K13-MGR")
    assert {path: client.get(path).status_code for path in PERFORMANCE_GETS} == {path: 200 for path in PERFORMANCE_GETS}
    notifications, audits = _count(app, "notifications"), len(_audit_actions(app))
    assert client.post(POSTS[1], data={"send_email": "0"}).status_code == 302
    new_actions = _audit_actions(app)[audits:]
    assert _count(app, "notifications") > notifications or any("feedback" in a for a in new_actions), new_actions  # the digest ran
    assert client.post(POSTS[0], data={"send_email": "0"}).status_code == 302


# ---------------------------------------------------------------------------
# Kept: manual role / unit profiles; old non-seed rows are not reinterpreted
# ---------------------------------------------------------------------------
def test_a_manual_role_profile_row_is_kept(app) -> None:
    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault

    _legacy_seeded_db(app)
    with app.app_context():
        row = RoleMenuDefault.query.filter_by(role_name="personel", menu_key="feedback_results").first()
        row.source_type = "manual"
        db.session.commit()
    personel = _user(app, "K13-PER", "personel")
    assert _menu(app, personel, ["feedback_results", "performance_tasks"]) == {"feedback_results": True, "performance_tasks": False}


def test_a_manual_unit_profile_row_is_kept(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    _legacy_seeded_db(app)
    with app.app_context():
        db.session.add(UnitMenuProfile(unit_name="Sahte Birim A", menu_key="feedback_results", is_visible=True))
        db.session.commit()
    personel = _user(app, "K13-PER", "personel")
    assert _menu(app, personel, ["feedback_results"]) == {"feedback_results": True}


# ---------------------------------------------------------------------------
# E. /support/assigned: unauthorised, approved, ownership, out-of-scope ticket and attachment
# ---------------------------------------------------------------------------
def _ticket(app, number: str, title: str, created_by: int, assigned_to: int | None) -> int:
    from app.extensions import db
    from app.models.support_models import SupportTicket, SupportTicketAttachment

    with app.app_context():
        ticket = SupportTicket(ticket_no=number, title=title, description="sahte", ticket_type="talep", module_name="genel",
                               created_by_user_id=created_by, assigned_to_user_id=assigned_to)
        db.session.add(ticket)
        db.session.commit()
        db.session.add(SupportTicketAttachment(ticket_id=ticket.id, uploaded_by_user_id=created_by, filename="sahte.txt",
                                               stored_name=f"{uuid.uuid4().hex}.txt"))
        db.session.commit()
        return ticket.id


@pytest.mark.parametrize("rows", [None, {"support_assigned": (True, "user_override")}])
def test_support_assigned_is_closed_to_ordinary_personel(app, rows) -> None:
    _legacy_seeded_db(app)
    _user(app, "K13-PER", "personel", rows=rows)
    assert _client(app, "K13-PER").get(SUPPORT_GET).status_code == 403


def test_an_approved_exception_lists_only_the_users_own_assigned_tickets(app) -> None:
    from app.extensions import db
    from app.models.support_models import SupportTicketAttachment

    _legacy_seeded_db(app)
    holder = _user(app, "K13-EXC", "personel", rows={"support_assigned": (True, "admin_exception")})
    other = _user(app, "K13-DIGER", "personel", birim="Sahte Birim B")
    requester = _user(app, "K13-TALEP", "personel", birim="Sahte Birim B")
    _ticket(app, "K13-T1", "SAHTE-BANA-ATANAN", requester, holder)
    foreign = _ticket(app, "K13-T2", "SAHTE-BASKASINA-ATANAN", requester, other)
    client = _client(app, "K13-EXC")
    page = client.get(SUPPORT_GET)
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "SAHTE-BANA-ATANAN" in body
    assert "SAHTE-BASKASINA-ATANAN" not in body
    assert client.get(f"/support/{foreign}").status_code == 403
    with app.app_context():
        attachment_id = SupportTicketAttachment.query.filter_by(ticket_id=foreign).first().id
        db.session.remove()
    assert client.get(f"/support/{foreign}/attachments/{attachment_id}").status_code == 403


def test_the_management_family_keeps_its_own_assigned_list(app) -> None:
    _legacy_seeded_db(app)
    manager = _user(app, "K13-MGR", "birim_sorumlusu")
    requester = _user(app, "K13-TALEP", "personel")
    _ticket(app, "K13-T3", "SAHTE-YONETICIYE-ATANAN", requester, manager)
    page = _client(app, "K13-MGR").get(SUPPORT_GET)
    assert page.status_code == 200
    assert "SAHTE-YONETICIYE-ATANAN" in page.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Review findings (19 Oct 2026): a role with only stale seed rows, and a failed sync audit
# ---------------------------------------------------------------------------
def _stale_only_personel_rows(app, extra: dict[str, tuple[bool, str]] | None = None) -> None:
    """personel holds no role rows but the old opening seed rows (plus ``extra``): what the static role
    gate must decide again, as if there were no record."""
    from app.extensions import db
    from app.models.settings_models import RoleMenuDefault

    rows = {key: (True, "seed") for key in LEGACY_SEED_KEYS}
    rows.update(extra or {})
    with app.app_context():
        for key, (visible, source_type) in rows.items():
            db.session.add(RoleMenuDefault(role_name="personel", menu_key=key, is_visible=visible, source_type=source_type))
        db.session.commit()


def _role_default_keys(app, role: str, *, prefer_database: bool = True) -> set[str]:
    from app.services.settings_service import get_role_default_menu_keys

    with app.app_context():
        return set(get_role_default_menu_keys(role, prefer_database=prefer_database))


def test_a_role_with_only_stale_seed_rows_falls_back_to_the_static_role_default(app) -> None:
    _stale_only_personel_rows(app)
    static_default = _role_default_keys(app, "personel", prefer_database=False)
    assert SELF_ASSESSMENT in static_default
    assert _role_default_keys(app, "personel") == static_default
    assert not static_default & set(LEGACY_SEED_KEYS)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"feedback_results": (True, "manual")}, {"feedback_results"}),  # a manual grant still decides
        ({SELF_ASSESSMENT: (False, "manual")}, set()),  # a manual refusal still decides
    ],
)
def test_manual_role_rows_still_decide_next_to_stale_seed_rows(app, extra, expected) -> None:
    _stale_only_personel_rows(app, extra)
    assert _role_default_keys(app, "personel") == expected


def test_the_role_default_bulk_profile_over_stale_seed_rows_applies_the_static_role_default(app) -> None:
    from app.models import UserMenuPermission

    _stale_only_personel_rows(app)
    _user(app, "K13-ADM", "admin")
    personel = _user(app, "K13-PER", "personel")
    response = _client(app, "K13-ADM").post("/settings", data={
        "form_action": "bulk_apply_profile", "bulk_profile_key": "dynamic::role_defaults",
        "bulk_scope_type": "role", "bulk_role": "personel",
    })
    assert response.status_code == 302
    with app.app_context():
        stored = {row.menu_key: bool(row.is_visible) for row in UserMenuPermission.query.filter_by(user_id=personel).all()}
    assert stored.get(SELF_ASSESSMENT) is True, "the persisted role default keeps the legitimate personel key"
    assert {key for key in LEGACY_SEED_KEYS if stored.get(key)} == set()
    assert _menu(app, personel, [SELF_ASSESSMENT] + LEGACY_SEED_KEYS) == {SELF_ASSESSMENT: True, **{key: False for key in LEGACY_SEED_KEYS}}


def test_stale_seed_rows_keep_the_unit_profile_and_the_personal_exception(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    _stale_only_personel_rows(app)
    with app.app_context():
        db.session.add(UnitMenuProfile(unit_name="Sahte Birim A", menu_key="feedback_results", is_visible=True))
        db.session.commit()
    personel = _user(app, "K13-PER", "personel", rows={"performance_feedback_meetings": (True, "admin_exception")})
    assert _menu(app, personel, [SELF_ASSESSMENT, "feedback_results", "performance_feedback_meetings", "feedback_actions", "performance_tasks", "support_assigned"]) == {
        SELF_ASSESSMENT: True, "feedback_results": True, "performance_feedback_meetings": True,
        "feedback_actions": False, "performance_tasks": False, "support_assigned": False,
    }


def _fail_the_sync_audit_commit(monkeypatch, app) -> None:
    """The commit that carries the sync audit row fails (a controlled database error); other commits run."""
    from sqlalchemy.exc import OperationalError

    from app.extensions import db
    from app.models import AuditLog

    original = db.session.commit

    def commit():
        if any(isinstance(obj, AuditLog) and obj.action == "settings.role_defaults_sync" for obj in db.session.new):
            raise OperationalError("COMMIT", {}, Exception("simulated audit commit failure"))
        return original()

    monkeypatch.setattr(db.session, "commit", commit)


def _flashes(client) -> list[tuple[str, str]]:
    with client.session_transaction() as session:
        return list(session.get("_flashes", []))


def _drop_flashes(client) -> None:
    """Forget the login flash so only the sync's own message is checked."""
    with client.session_transaction() as session:
        session.pop("_flashes", None)


def test_a_failed_sync_audit_reports_failure_and_keeps_no_unaudited_change(app, monkeypatch) -> None:
    from sqlalchemy import text

    from app.extensions import db

    _legacy_seeded_db(app)
    _user(app, "K13-ADM", "admin")
    client = _client(app, "K13-ADM")
    _drop_flashes(client)
    seed_rows_before = {key: _role_row(app, "personel", key) for key in LEGACY_SEED_KEYS}
    assert set(seed_rows_before.values()) == {(True, "seed")}
    _fail_the_sync_audit_commit(monkeypatch, app)
    response = client.post("/settings", data={"form_action": "sync_role_defaults"})
    assert response.status_code == 302
    categories = [category for category, _message in _flashes(client)]
    assert "success" not in categories, _flashes(client)
    assert "danger" in categories, _flashes(client)
    monkeypatch.undo()
    assert {key: _role_row(app, "personel", key) for key in LEGACY_SEED_KEYS} == seed_rows_before, "no seed change without its audit"
    with app.app_context():
        assert db.session.execute(text("SELECT COUNT(*) FROM audit_logs WHERE action = 'settings.role_defaults_sync'")).scalar() == 0


def test_a_successful_sync_stores_the_seed_change_and_its_audit_together(app) -> None:
    from sqlalchemy import text

    from app.extensions import db

    _legacy_seeded_db(app)
    _user(app, "K13-ADM", "admin")
    client = _client(app, "K13-ADM")
    _drop_flashes(client)
    assert client.post("/settings", data={"form_action": "sync_role_defaults"}).status_code == 302
    assert [category for category, _message in _flashes(client)] == ["success"]
    assert {key: _role_row(app, "personel", key) for key in LEGACY_SEED_KEYS} == {key: (False, "seed") for key in LEGACY_SEED_KEYS}
    with app.app_context():
        assert db.session.execute(text("SELECT COUNT(*) FROM audit_logs WHERE action = 'settings.role_defaults_sync'")).scalar() == 1
