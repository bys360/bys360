"""R05 contract: no privilege escalation through role, password or account-state changes.

Threat (R05)
------------
``admin_required`` admits the whole admin family (admin, baskan, baskan_yardimcisi,
grup_baskani, mali_musavir). Every web user-management route behind it trusted the form:

- a non-admin editor could make itself (or anyone) ``admin`` through /admin/users/<id>/edit,
  /personnel/<id>/edit, /admin/users/create, /personnel/add, /personnel/excel-upload or
  /admin/users/import (also through a role inferred from the title or unit in the Excel);
- a non-admin editor could set a new password on an admin account, on another privileged
  account or on a holder of the explicit ``personnel_read_all`` / ``support_all`` grants, then
  log in as that person and take over its data rights;
- a non-admin editor could deactivate, archive, delete or re-activate privileged accounts, and
  /admin/users/reset-all deleted every non-admin user and their data;
- none of these changes left an audit row.

Approved policy (HUMAN_POLICY_APPROVED: least privilege; only the admin role assigns broad
rights; broad rights are explicit, per person and auditable; unknown scope => deny)
------------------------------------------------------------------------------------------
R05-1 Only a real admin (stored ``role`` exactly ``admin``) changes a stored role. Anyone else
      keeps the target's role as it is and creates accounts only with the baseline role
      ``personel``; an Excel row that would create or change any other role refuses the whole
      import (nothing is written).
R05-2 A non-admin editor never sets the password of a protected account: their own, any role
      other than ``personel`` (unknown roles included), or a holder of a visible
      ``personnel_read_all`` / ``support_all`` row. Ordinary accounts keep the existing recovery
      path. A password set by someone else ends the target's other sessions.
R05-3 A non-admin editor never activates, deactivates, archives or deletes a protected account
      (single, bulk or Excel), and never runs reset-all. A deactivation ends the target's
      sessions.
R05-4 Every role change, password set by another user, activation change, deletion and refusal
      on these routes writes an ``audit_logs`` row (never password material).

Every check goes through a real HTTP route with a web session from ``POST /login``.
Tests named ``test_guard_*`` are positive guards that also pass on the pre-fix code
(6d9f885); every other test fails on the pre-fix code and passes with the R05 fix.
"""
from __future__ import annotations

import io
import json
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "R05AccountChangeTest1!"
NEW_PASSWORD = "R05-New-Test-Password-9x!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "r05_contract"

# key: (role, is_active, explicit grant menu_key or None)
_USERS: dict[str, tuple[str, bool, str | None]] = {
    "admin": ("admin", True, None),
    "admin2": ("admin", True, None),
    "admin_off": ("admin", False, None),
    "baskan": ("baskan", True, None),
    "baskan_yardimcisi": ("baskan_yardimcisi", True, None),
    "grup_baskani": ("grup_baskani", True, None),
    "mali_musavir": ("mali_musavir", True, None),
    "koordinator": ("koordinator", True, None),
    "sysadm": ("sistem_yoneticisi", True, None),
    "pra_holder": ("personel", True, "personnel_read_all"),
    "sup_holder": ("personel", True, "support_all"),
    "plain": ("personel", True, None),
    "plain2": ("personel", True, None),
}
SICIL = {key: f"R5{index:02d}X" for index, key in enumerate(_USERS, start=1)}

NON_ADMIN_EDITORS = ("baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir")
PROTECTED_TARGETS = ("admin2", "koordinator", "sysadm", "pra_holder", "sup_holder")


# --------------------------------------------------------------------------------------
# App / synthetic data
# --------------------------------------------------------------------------------------


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-r05-account-change-contract",
        "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "r05-contract-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    return flask_app


_HASH_CACHE: dict[str, str] = {}


def _password_hash() -> str:
    if "hash" not in _HASH_CACHE:
        from app.models import User

        probe = User()
        probe.set_password(PASSWORD)
        _HASH_CACHE["hash"] = probe.password_hash
    return _HASH_CACHE["hash"]


def _seed() -> SimpleNamespace:
    from app.extensions import db
    from app.models import SupportTicket, User, UserMenuPermission

    ids: dict[str, int] = {}
    for key, (role, active, grant) in _USERS.items():
        user = User(
            sicil_no=SICIL[key],
            email=f"{SICIL[key].lower()}@example.gov.tr",
            ad="Kisi",
            soyad=SICIL[key],
            unvan="Uzman",
            role=role,
            birim="R05 Birim",
            ust_birim="R05 Ust Birim",
            is_active=active,
            must_change_password=False,
            must_set_security_question=False,
            is_first_login=False,
        )
        user.password_hash = _password_hash()
        db.session.add(user)
        db.session.flush()
        ids[key] = int(user.id)
        if grant:
            db.session.add(
                UserMenuPermission(user_id=user.id, menu_key=grant, is_visible=True, source_type="user_override")
            )
    ticket = SupportTicket(
        ticket_no="R05-T-1",
        title="R05 ticket",
        description="R05 ticket body",
        ticket_type="other",
        module_name="test",
        status="open",
        created_by_user_id=ids["plain"],
    )
    db.session.add(ticket)
    db.session.commit()
    return SimpleNamespace(ids=ids)


@pytest.fixture
def env(monkeypatch, install_interim_notes_schema):
    from sqlalchemy import event

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"r05_{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    from app.extensions import db
    from app.services import runtime_schema

    with app.app_context():
        engine = db.engine

        @event.listens_for(engine, "connect")
        def _fast_temp_sqlite(dbapi_connection, _record):  # throwaway test DB: no fsync
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA synchronous=OFF")
            cursor.execute("PRAGMA journal_mode=MEMORY")
            cursor.close()

        engine.dispose()
        db.create_all()
        runtime_schema.provision_all()
        install_interim_notes_schema(db.engine)
        data = _seed()
    data.app = app
    yield data
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _login(env, who, password=PASSWORD):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": SICIL[who], "password": password})
    return client, response


def _web(env, who):
    client, response = _login(env, who)
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), who
    return client


def _login_succeeds(env, who, password) -> bool:
    _client, response = _login(env, who, password)
    return response.status_code == 302 and "/login" not in response.headers.get("Location", "")


def _state(env, key):
    """(role, is_active, password_hash, security_stamp) of a seeded user, or None if deleted."""
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[key])
        if user is None:
            return None
        return SimpleNamespace(
            role=user.role,
            is_active=bool(user.is_active),
            password_hash=user.password_hash,
            security_stamp=user.security_stamp,
        )


def _user_by_sicil(env, sicil):
    from app.models import User

    with env.app.app_context():
        user = User.query.filter_by(sicil_no=sicil).first()
        return None if user is None else SimpleNamespace(id=user.id, role=user.role, is_active=bool(user.is_active))


def _audit_rows(env, action=None):
    from app.models import AuditLog

    with env.app.app_context():
        query = AuditLog.query
        if action:
            query = query.filter_by(action=action)
        return [
            SimpleNamespace(
                user_id=row.user_id,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                old=json.loads(row.old_data_json) if row.old_data_json else None,
                new=json.loads(row.new_data_json) if row.new_data_json else None,
                raw=f"{row.old_data_json or ''}{row.new_data_json or ''}{row.summary or ''}",
            )
            for row in query.order_by(AuditLog.id.asc()).all()
        ]


def _admin_edit_form(env, key, **overrides):
    form = {
        "ad": "Kisi",
        "soyad": SICIL[key],
        "sicil_no": SICIL[key],
        "email": f"{SICIL[key].lower()}@example.gov.tr",
        "unvan": "Uzman",
        "role": _USERS[key][0],
        "birim": "R05 Birim",
        "ust_birim": "R05 Ust Birim",
        "personnel_category": "Diğer",
    }
    if _USERS[key][1]:
        form["is_active"] = "on"
    form.update(overrides)
    return {k: v for k, v in form.items() if v is not None}


def _personnel_edit_form(env, key, **overrides):
    form = _admin_edit_form(env, key)
    form.update(overrides)
    return {k: v for k, v in form.items() if v is not None}


def _new_user_form(sicil, role):
    return {
        "ad": "Yeni",
        "soyad": sicil,
        "sicil_no": sicil,
        "email": f"{sicil.lower()}@example.gov.tr",
        "unvan": "Uzman",
        "role": role,
        "birim": "R05 Birim",
        "ust_birim": "R05 Ust Birim",
        "personnel_category": "Diğer",
        "is_active": "on",
    }


def _xlsx(rows, headers=("Sicil No", "Ad", "Soyad", "E-posta", "Unvan", "Birim", "Üst Birim", "Rol")):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def _xlsx_row(sicil, role, *, unvan="Uzman", birim="R05 Birim", ust_birim="R05 Ust Birim"):
    return (sicil, "Kisi", sicil, f"{sicil.lower()}@example.gov.tr", unvan, birim, ust_birim, role)


def _upload(client, path, rows, **form):
    data = {"excel_file": (_xlsx(rows), "personel.xlsx"), **form}
    return client.post(path, data=data, content_type="multipart/form-data")


EDIT_ROUTES = ("admin_users_edit", "personnel_edit")


def _post_edit(client, route, env, target, **overrides):
    if route == "admin_users_edit":
        return client.post(f"/admin/users/{env.ids[target]}/edit", data=_admin_edit_form(env, target, **overrides))
    return client.post(f"/personnel/{env.ids[target]}/edit", data=_personnel_edit_form(env, target, **overrides))


# --------------------------------------------------------------------------------------
# R05-1 Role changes
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
@pytest.mark.parametrize("route", EDIT_ROUTES)
def test_r05_1_non_admin_cannot_make_itself_admin(env, actor, route):
    client = _web(env, actor)
    _post_edit(client, route, env, actor, role="admin")
    assert _state(env, actor).role == _USERS[actor][0]


@pytest.mark.parametrize("new_role", ("admin", "baskan", "koordinator", "sistem_yoneticisi"))
@pytest.mark.parametrize("route", EDIT_ROUTES)
def test_r05_1_non_admin_cannot_grant_a_role(env, route, new_role):
    client = _web(env, "mali_musavir")
    _post_edit(client, route, env, "plain", role=new_role)
    assert _state(env, "plain").role == "personel"


@pytest.mark.parametrize("route", EDIT_ROUTES)
def test_r05_1_non_admin_cannot_demote_an_admin(env, route):
    client = _web(env, "baskan")
    _post_edit(client, route, env, "admin2", role="personel")
    assert _state(env, "admin2").role == "admin"


@pytest.mark.parametrize("role", ("admin", "mali_musavir", "koordinator"))
@pytest.mark.parametrize("path", ("/admin/users/create", "/personnel/add"))
def test_r05_1_non_admin_cannot_create_a_privileged_account(env, path, role):
    client = _web(env, "grup_baskani")
    client.post(path, data=_new_user_form("R5NEW01", role))
    created = _user_by_sicil(env, "R5NEW01")
    assert created is None or created.role == "personel"


def test_r05_1_non_admin_excel_upload_cannot_change_a_role(env):
    client = _web(env, "mali_musavir")
    _upload(
        client,
        "/personnel/excel-upload",
        [_xlsx_row(SICIL["mali_musavir"], "admin"), _xlsx_row(SICIL["plain"], "baskan")],
        update_existing="on",
    )
    assert _state(env, "mali_musavir").role == "mali_musavir"
    assert _state(env, "plain").role == "personel"


def test_r05_1_non_admin_excel_upload_cannot_create_a_privileged_account(env):
    client = _web(env, "mali_musavir")
    _upload(client, "/personnel/excel-upload", [_xlsx_row("R5NEW02", "admin")], activate_new_users="on")
    created = _user_by_sicil(env, "R5NEW02")
    assert created is None or created.role == "personel"


def test_r05_1_non_admin_excel_upload_cannot_derive_a_role_from_the_title(env):
    client = _web(env, "baskan")
    # Without a role cell the importer infers the role from the title ("Grup Başkanı" -> grup_baskani).
    _upload(client, "/personnel/excel-upload", [_xlsx_row("R5NEW03", "", unvan="Grup Başkanı")], activate_new_users="on")
    created = _user_by_sicil(env, "R5NEW03")
    assert created is None or created.role == "personel"


def test_r05_1_non_admin_admin_import_cannot_change_or_create_roles(env):
    client = _web(env, "baskan_yardimcisi")
    _upload(
        client,
        "/admin/users/import",
        [_xlsx_row(SICIL["plain"], "mali_musavir"), _xlsx_row("R5NEW04", "koordinator")],
    )
    assert _state(env, "plain").role == "personel"
    created = _user_by_sicil(env, "R5NEW04")
    assert created is None or created.role == "personel"


def test_r05_1_refused_excel_import_writes_nothing(env):
    client = _web(env, "baskan_yardimcisi")
    _upload(
        client,
        "/admin/users/import",
        [_xlsx_row("R5NEW05", "personel"), _xlsx_row(SICIL["koordinator"], "personel")],
    )
    assert _state(env, "koordinator").role == "koordinator"
    assert _user_by_sicil(env, "R5NEW05") is None


# --------------------------------------------------------------------------------------
# R05-2 Passwords
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", (*PROTECTED_TARGETS, "self"))
@pytest.mark.parametrize("actor", ("baskan", "mali_musavir"))
def test_r05_2_non_admin_cannot_set_a_protected_password(env, actor, target):
    target = actor if target == "self" else target
    before = _state(env, target)
    client = _web(env, actor)
    client.post(
        f"/personnel/{env.ids[target]}/edit",
        data=_personnel_edit_form(env, target, new_password=NEW_PASSWORD, new_password_repeat=NEW_PASSWORD),
    )
    assert _state(env, target).password_hash == before.password_hash
    assert not _login_succeeds(env, target, NEW_PASSWORD)


def test_r05_2_password_set_by_another_user_ends_target_sessions(env):
    before = _state(env, "plain")
    client = _web(env, "admin")
    client.post(
        f"/personnel/{env.ids['plain']}/edit",
        data=_personnel_edit_form(env, "plain", new_password=NEW_PASSWORD, new_password_repeat=NEW_PASSWORD),
    )
    after = _state(env, "plain")
    assert after.password_hash != before.password_hash
    assert after.security_stamp != before.security_stamp


def test_guard_non_admin_keeps_recovery_for_ordinary_accounts(env):
    client = _web(env, "baskan")
    client.post(
        f"/personnel/{env.ids['plain']}/edit",
        data=_personnel_edit_form(env, "plain", new_password=NEW_PASSWORD, new_password_repeat=NEW_PASSWORD),
    )
    assert _login_succeeds(env, "plain", NEW_PASSWORD)


def test_guard_admin_can_set_a_protected_password(env):
    client = _web(env, "admin")
    client.post(
        f"/personnel/{env.ids['pra_holder']}/edit",
        data=_personnel_edit_form(env, "pra_holder", new_password=NEW_PASSWORD, new_password_repeat=NEW_PASSWORD),
    )
    assert _login_succeeds(env, "pra_holder", NEW_PASSWORD)


# --------------------------------------------------------------------------------------
# R05-3 Account state
# --------------------------------------------------------------------------------------

DEACTIVATE_ROUTES = (
    "admin_toggle",
    "personnel_toggle",
    "admin_archive",
    "admin_users_edit",
    "personnel_edit",
)


def _deactivate(client, route, env, target):
    user_id = env.ids[target]
    if route == "admin_toggle":
        return client.post(f"/admin/users/{user_id}/toggle-active", data={"target_state": "0"})
    if route == "personnel_toggle":
        return client.post(f"/personnel/{user_id}/toggle-active")
    if route == "admin_archive":
        return client.post(f"/admin/users/{user_id}/archive")
    return _post_edit(client, route, env, target, is_active=None)


@pytest.mark.parametrize("target", PROTECTED_TARGETS)
@pytest.mark.parametrize("route", DEACTIVATE_ROUTES)
def test_r05_3_non_admin_cannot_deactivate_a_protected_account(env, route, target):
    client = _web(env, "baskan")
    _deactivate(client, route, env, target)
    assert _state(env, target).is_active is True


@pytest.mark.parametrize("route", ("admin_toggle", "personnel_toggle"))
def test_r05_3_non_admin_cannot_reactivate_a_disabled_admin(env, route):
    client = _web(env, "mali_musavir")
    user_id = env.ids["admin_off"]
    if route == "admin_toggle":
        client.post(f"/admin/users/{user_id}/toggle-active", data={"target_state": "1"})
    else:
        client.post(f"/personnel/{user_id}/toggle-active")
    assert _state(env, "admin_off").is_active is False


@pytest.mark.parametrize("path", ("/admin/users/bulk-passive", "/admin/users/bulk-archive"))
def test_r05_3_non_admin_bulk_state_change_skips_protected_accounts(env, path):
    client = _web(env, "grup_baskani")
    client.post(path, data={"user_ids": [str(env.ids[key]) for key in ("admin2", "pra_holder", "sup_holder", "plain")]})
    assert _state(env, "admin2").is_active is True
    assert _state(env, "pra_holder").is_active is True
    assert _state(env, "sup_holder").is_active is True
    assert _state(env, "plain").is_active is False


@pytest.mark.parametrize("route", ("admin_delete", "personnel_delete", "bulk_delete"))
def test_r05_3_non_admin_cannot_delete_a_protected_account(env, route):
    client = _web(env, "baskan")
    if route == "admin_delete":
        client.post(f"/admin/users/{env.ids['admin2']}/delete")
        client.post(f"/admin/users/{env.ids['pra_holder']}/delete")
    elif route == "personnel_delete":
        client.post(f"/personnel/{env.ids['admin2']}/delete")
        client.post(f"/personnel/{env.ids['pra_holder']}/delete")
    else:
        client.post("/admin/users/bulk-delete", data={"user_ids": [str(env.ids["admin2"]), str(env.ids["pra_holder"])]})
    assert _state(env, "admin2") is not None
    assert _state(env, "pra_holder") is not None


def test_r05_3_non_admin_excel_import_cannot_deactivate_a_protected_account(env):
    client = _web(env, "baskan")
    headers = ("Sicil No", "Ad", "Soyad", "E-posta", "Unvan", "Birim", "Üst Birim", "Rol", "Aktif")
    rows = [(*_xlsx_row(SICIL["sup_holder"], "personel"), "0")]
    client.post(
        "/admin/users/import",
        data={"excel_file": (_xlsx(rows, headers=headers), "personel.xlsx")},
        content_type="multipart/form-data",
    )
    assert _state(env, "sup_holder").is_active is True


@pytest.mark.parametrize("actor", NON_ADMIN_EDITORS)
def test_r05_3_non_admin_cannot_reset_all_personnel(env, actor):
    client = _web(env, actor)
    client.post("/admin/users/reset-all")
    for key in ("plain", "pra_holder", "koordinator", actor):
        assert _state(env, key) is not None, key


def test_r05_3_deactivation_ends_target_sessions(env):
    before = _state(env, "plain")
    client = _web(env, "admin")
    client.post(f"/admin/users/{env.ids['plain']}/toggle-active", data={"target_state": "0"})
    after = _state(env, "plain")
    assert after.is_active is False
    assert after.security_stamp != before.security_stamp


def test_guard_admin_can_deactivate_a_protected_account(env):
    client = _web(env, "admin")
    client.post(f"/admin/users/{env.ids['admin2']}/toggle-active", data={"target_state": "0"})
    assert _state(env, "admin2").is_active is False


def test_guard_non_admin_can_deactivate_an_ordinary_account(env):
    client = _web(env, "baskan")
    client.post(f"/personnel/{env.ids['plain2']}/toggle-active")
    assert _state(env, "plain2").is_active is False


# --------------------------------------------------------------------------------------
# R05-4 Audit
# --------------------------------------------------------------------------------------


def test_r05_4_role_change_is_audited(env):
    client = _web(env, "admin")
    _post_edit(client, "personnel_edit", env, "plain", role="koordinator")
    assert _state(env, "plain").role == "koordinator"
    rows = [row for row in _audit_rows(env, "account.role_change") if row.entity_id == env.ids["plain"]]
    assert len(rows) == 1
    assert rows[0].user_id == env.ids["admin"]
    assert rows[0].entity_type == "user"
    assert rows[0].old == {"role": "personel"}
    assert rows[0].new == {"role": "koordinator"}


def test_r05_4_password_set_is_audited_without_password_material(env):
    client = _web(env, "admin")
    client.post(
        f"/personnel/{env.ids['plain']}/edit",
        data=_personnel_edit_form(env, "plain", new_password=NEW_PASSWORD, new_password_repeat=NEW_PASSWORD),
    )
    rows = [row for row in _audit_rows(env, "account.password_set") if row.entity_id == env.ids["plain"]]
    assert len(rows) == 1 and rows[0].user_id == env.ids["admin"]
    for row in _audit_rows(env):
        assert NEW_PASSWORD not in row.raw
        assert "pbkdf2" not in row.raw and "scrypt" not in row.raw


def test_r05_4_activation_change_and_deletion_are_audited(env):
    client = _web(env, "admin")
    client.post(f"/admin/users/{env.ids['plain']}/toggle-active", data={"target_state": "0"})
    client.post(f"/admin/users/{env.ids['plain2']}/delete")
    activation = [row for row in _audit_rows(env, "account.activation_change") if row.entity_id == env.ids["plain"]]
    assert len(activation) == 1
    assert activation[0].old == {"is_active": True} and activation[0].new == {"is_active": False}
    deletion = [row for row in _audit_rows(env, "account.delete") if row.entity_id == env.ids["plain2"]]
    assert len(deletion) == 1 and deletion[0].user_id == env.ids["admin"]


def test_r05_4_refusal_is_audited(env):
    client = _web(env, "mali_musavir")
    _post_edit(client, "admin_users_edit", env, "mali_musavir", role="admin")
    rows = [row for row in _audit_rows(env, "account.change_refused") if row.entity_id == env.ids["mali_musavir"]]
    assert rows and rows[0].user_id == env.ids["mali_musavir"]


# --------------------------------------------------------------------------------------
# Positive guards (legitimate administration keeps working)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", EDIT_ROUTES)
def test_guard_admin_can_change_roles(env, route):
    client = _web(env, "admin")
    _post_edit(client, route, env, "plain", role="baskan")
    assert _state(env, "plain").role == "baskan"


@pytest.mark.parametrize("route", EDIT_ROUTES)
def test_guard_non_admin_can_edit_profile_fields_without_role_change(env, route):
    client = _web(env, "baskan")
    _post_edit(client, route, env, "koordinator", unvan="Kidemli Uzman")
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids["koordinator"])
        assert user is not None
        assert user.unvan == "Kidemli Uzman"
        assert user.role == "koordinator"
        assert bool(user.is_active) is True


@pytest.mark.parametrize("path", ("/admin/users/create", "/personnel/add"))
def test_guard_non_admin_can_create_an_ordinary_account(env, path):
    client = _web(env, "baskan")
    client.post(path, data=_new_user_form("R5NEW09", "personel"))
    created = _user_by_sicil(env, "R5NEW09")
    assert created is not None and created.role.lower() == "personel"


def test_guard_admin_excel_upload_can_assign_roles(env):
    client = _web(env, "admin")
    _upload(client, "/personnel/excel-upload", [_xlsx_row(SICIL["plain"], "koordinator")], update_existing="on")
    assert _state(env, "plain").role == "koordinator"


# --------------------------------------------------------------------------------------
# Independent review of the first R05 head (6672154a): F1, F3, F4, F5, R1
# --------------------------------------------------------------------------------------

IMPORT_PATHS = ("/personnel/excel-upload", "/admin/users/import")


def _roles(env) -> dict[str, str]:
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        return {key: db.session.get(User, user_id).role for key, user_id in env.ids.items()}


@pytest.mark.parametrize("path", IMPORT_PATHS)
def test_r05_f1_non_admin_import_leaves_every_other_role_unchanged(env, path):
    """The manager-chain rebuild after an import re-derived every user's role from the title/unit."""
    before = _roles(env)
    client = _web(env, "baskan")
    _upload(client, path, [_xlsx_row("R5NEW20", "personel")], activate_new_users="on")
    assert _roles(env) == before


@pytest.mark.parametrize("path", IMPORT_PATHS)
def test_r05_f1_admin_import_audits_every_role_it_changes(env, path):
    before = _roles(env)
    client = _web(env, "admin")
    _upload(client, path, [_xlsx_row("R5NEW21", "personel")], activate_new_users="on")
    after = _roles(env)
    changed = {key for key in before if after[key] != before[key]}
    audited = {row.entity_id for row in _audit_rows(env, "account.role_change")}
    assert {env.ids[key] for key in changed} <= audited


@pytest.mark.parametrize("route", EDIT_ROUTES)
def test_r05_f3_non_admin_cannot_rewrite_a_role_to_a_case_variant(env, route):
    client = _web(env, "baskan")
    _post_edit(client, route, env, "admin2", role="ADMIN")
    assert _state(env, "admin2").role == "admin"


def _identity(env, key):
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[key])
        return (user.sicil_no, user.email, bool(user.must_change_password), bool(user.must_set_security_question))


@pytest.mark.parametrize(
    "field,value",
    (("sicil_no", "R5LOCKED"), ("email", "r5locked@example.gov.tr")),
)
@pytest.mark.parametrize("route", EDIT_ROUTES)
@pytest.mark.parametrize("target", ("admin2", "pra_holder", "self"))
def test_r05_f4_non_admin_cannot_change_login_identifiers_of_protected_accounts(env, route, target, field, value):
    target = "baskan" if target == "self" else target
    before = _identity(env, target)
    client = _web(env, "baskan")
    _post_edit(client, route, env, target, **{field: value})
    assert _identity(env, target) == before


@pytest.mark.parametrize("flag", ("must_change_password", "must_set_security_question"))
def test_r05_f4_non_admin_cannot_set_security_flags_of_protected_accounts(env, flag):
    before = _identity(env, "admin2")
    client = _web(env, "baskan")
    _post_edit(client, "personnel_edit", env, "admin2", **{flag: "on"})
    assert _identity(env, "admin2") == before


def test_r05_f4_non_admin_excel_upload_cannot_change_a_protected_email(env):
    before = _identity(env, "admin2")
    client = _web(env, "baskan")
    row = (SICIL["admin2"], "Kisi", SICIL["admin2"], "r5other@example.gov.tr", "Uzman", "R05 Birim", "R05 Ust Birim", "admin")
    _upload(client, "/personnel/excel-upload", [row], update_existing="on")
    assert _identity(env, "admin2") == before


def test_r05_f4_non_admin_excel_upload_cannot_match_a_protected_account_by_email(env):
    client = _web(env, "baskan")
    row = ("R5OTHER", "Degisti", "Degisti", f"{SICIL['admin2'].lower()}@example.gov.tr", "Uzman", "R05 Birim", "R05 Ust Birim", "admin")
    _upload(client, "/personnel/excel-upload", [row], update_existing="on")
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids["admin2"])
        assert user is not None and user.ad == "Kisi" and user.soyad == SICIL["admin2"]


def test_r05_f4_non_admin_admin_import_cannot_change_a_protected_email(env):
    before = _identity(env, "pra_holder")
    client = _web(env, "baskan")
    row = (SICIL["pra_holder"], "Kisi", SICIL["pra_holder"], "r5other@example.gov.tr", "Uzman", "R05 Birim", "R05 Ust Birim", "personel")
    _upload(client, "/admin/users/import", [row])
    assert _identity(env, "pra_holder") == before


def test_r05_f5_refusal_audit_never_points_at_a_rolled_back_account(env):
    client = _web(env, "baskan")
    shared_email = "r5shared@example.gov.tr"
    rows = [
        ("R5NEWC", "Kisi", "R5NEWC", shared_email, "Uzman", "R05 Birim", "R05 Ust Birim", "personel"),
        ("R5NEWD", "Kisi", "R5NEWD", shared_email, "Uzman", "R05 Birim", "R05 Ust Birim", "admin"),
    ]
    _upload(client, "/personnel/excel-upload", rows, update_existing="on", activate_new_users="on")
    from app.extensions import db
    from app.models import User

    refusals = _audit_rows(env, "account.change_refused")
    assert refusals
    with env.app.app_context():
        for row in refusals:
            assert row.entity_id is None or db.session.get(User, row.entity_id) is not None


def _president_approvals_open(client) -> bool:
    response = client.get("/performance/president-approvals")
    return response.status_code == 200 and "/login" not in response.headers.get("Location", "")


def test_r05_r1_a_self_assigned_title_gives_no_president_approvals(env):
    client = _web(env, "grup_baskani")
    _post_edit(client, "personnel_edit", env, "grup_baskani", unvan="Başkan")
    assert not _president_approvals_open(_web(env, "grup_baskani"))


def test_r05_r1_a_title_set_on_an_ordinary_account_gives_no_president_approvals(env):
    client = _web(env, "baskan")
    _post_edit(client, "personnel_edit", env, "plain", unvan="Başkan")
    assert not _president_approvals_open(_web(env, "plain"))


def test_guard_the_stored_president_role_keeps_president_approvals(env):
    assert _president_approvals_open(_web(env, "baskan"))
