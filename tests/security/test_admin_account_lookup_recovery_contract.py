"""Admin account lookup and recovery contract (urgent: "Kullanıcı bulunamadı" for a new admin).

Report (2026-10-11): an account created on production with the ``admin`` role could not be found on
``/forgot-password`` ("Kullanıcı bulunamadı"), and the creator could not see it in the user lists.

Two separate causes on the current code:

1. Lists: ``/admin/users`` and ``/personnel`` exclude every ``role == "admin"`` row, for every
   viewer. A real admin therefore never sees an admin account it has just created.
2. Lookup: web login and ``/forgot-password`` match ``sicil_no`` exactly and ``email`` against the
   lower-cased input, and the mobile login matches both exactly. An identifier typed in another
   case ("ad9001" for "AD9001"), a stored e-mail with capitals (legacy or imported rows), or an
   invisible character copied with the identifier, all end in "Kullanıcı bulunamadı" although the
   row exists. The uniqueness check uses the same exact match, so a case variant of an existing
   e-mail or sicil is accepted as a new account (a second, confusing row), and when both the sicil
   and the e-mail collide the forms report only one of them.

Rule now (``app/services/account_lookup.py``):

- an exact match keeps winning; otherwise the sicil is compared case-insensitively and the e-mail
  case-insensitively, both trimmed and without zero-width characters; if more than one account
  matches that way, nobody is returned (no login into the wrong account);
- the same lookup serves the web login, ``/forgot-password`` and the mobile login;
- uniqueness checks use the same normalisation and report the sicil and the e-mail separately;
- a real admin (stored role exactly ``admin``) sees admin accounts in ``/admin/users`` and
  ``/personnel``; nobody else does (unchanged).

Tests named ``test_guard_*`` pass before and after (the new admin's login, first-login security
question and password-change flow); every other test fails on f796107f.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "AdminLookupTestPass1!"
FIRST_LOGIN = "admin-lookup-test-first-login-1"
NEW_PASSWORD = "AdminLookupTest-New-Pass-9!"
QUESTION = "Çocukluk lakabınız nedir?"
ANSWER = "test-cevap-1234"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "admin_lookup_contract"

# key: (sicil_no, email, role)
_USERS = {
    "admin": ("AL01X", "al01x@example.gov.tr", "admin"),
    "baskan": ("AL02X", "al02x@example.gov.tr", "baskan"),
    "other_admin": ("AL03X", "al03x@example.gov.tr", "admin"),
    # A legacy/imported row whose e-mail was stored with capitals.
    "mixed": ("MX01", "Mixed.Case@Example.gov.tr", "personel"),
    # Two legacy rows whose e-mails differ only in case.
    "dup_a": ("DP01", "Dup.User@Example.gov.tr", "personel"),
    "dup_b": ("DP02", "DUP.USER@Example.gov.tr", "personel"),
}

NEW_SICIL = "AD9001"
NEW_EMAIL = "senior.dev@example.gov.tr"


def _make_app(monkeypatch, uri):
    # Import Config before setting the environment: Config reads DEFAULT_FIRST_LOGIN_PASSWORD once,
    # at import time, so setting the env first would pin this module's value for every later test
    # module. The value is pinned with monkeypatch instead and restored after each test.
    from config import Config

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-admin-lookup-contract",
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
        "DEFAULT_FIRST_LOGIN_PASSWORD": FIRST_LOGIN,
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app

    monkeypatch.setattr(Config, "DEFAULT_FIRST_LOGIN_PASSWORD", FIRST_LOGIN)
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    return flask_app


def _seed() -> dict[str, int]:
    from app.extensions import db
    from app.models import User

    ids: dict[str, int] = {}
    for key, (sicil, email, role) in _USERS.items():
        user = User(
            sicil_no=sicil,
            email=email,
            ad="Kisi",
            soyad=sicil,
            unvan="Uzman",
            role=role,
            birim="AL Birim",
            ust_birim="AL Ust Birim",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
            is_first_login=False,
        )
        user.set_password(PASSWORD)
        user.security_question = QUESTION
        user.set_security_answer(ANSWER)
        db.session.add(user)
        db.session.flush()
        ids[key] = int(user.id)
    db.session.commit()
    return ids


@pytest.fixture
def env(monkeypatch, install_interim_notes_schema):
    from sqlalchemy import event

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"al_{uuid.uuid4().hex}.sqlite3"
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
        ids = _seed()
    yield SimpleNamespace(app=app, ids=ids)
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _login(client, identifier, password):
    return client.post("/login", data={"sicil_or_email": identifier, "password": password})


def _logged_in(response) -> bool:
    return response.status_code == 302 and "/login" not in response.headers.get("Location", "")


def _web(env, key):
    client = env.app.test_client()
    assert _logged_in(_login(client, _USERS[key][0], PASSWORD)), key
    return client


def _forgot_finds(env, identifier) -> bool:
    """True when /forgot-password recognises the account (it then asks its security question)."""
    body = env.app.test_client().post("/forgot-password", data={"sicil_or_email": identifier}).get_data(as_text=True)
    return "Kullanıcı bulunamadı" not in body


def _user(env, **filters):
    from app.models import User

    with env.app.app_context():
        rows = User.query.filter_by(**filters).all()
        return [SimpleNamespace(id=r.id, sicil_no=r.sicil_no, email=r.email, role=r.role) for r in rows]


def _create_form(sicil, email, role="admin"):
    return {
        "ad": "Kidemli",
        "soyad": "Yazilimci",
        "sicil_no": sicil,
        "email": email,
        "unvan": "Kıdemli Yazılım Uzmanı",
        "role": role,
        "birim": "AL Birim",
        "ust_birim": "AL Ust Birim",
        "personnel_category": "Diğer",
        "is_active": "on",
    }


def _create_new_admin(env):
    client = _web(env, "admin")
    response = client.post("/admin/users/create", data=_create_form(NEW_SICIL, NEW_EMAIL), follow_redirects=True)
    created = _user(env, sicil_no=NEW_SICIL)
    assert len(created) == 1 and created[0].role == "admin", response.get_data(as_text=True)[:500]
    return created[0]


# --------------------------------------------------------------------------------------
# Guard: the new admin's normal login, first-login security question and password change
# --------------------------------------------------------------------------------------


def test_guard_new_admin_first_login_security_question_and_password_change(env):
    _create_new_admin(env)
    client = env.app.test_client()

    first = _login(client, NEW_SICIL, FIRST_LOGIN)
    assert _logged_in(first)
    assert "/account/security-setup" in first.headers.get("Location", "")
    # Every other page sends the user back to the security setup first.
    assert "/account/security-setup" in client.get("/home").headers.get("Location", "")

    setup = client.post("/account/security-setup", data={"security_question": QUESTION, "security_answer": ANSWER})
    assert "/account/change-password" in setup.headers.get("Location", "")

    change = client.post(
        "/account/change-password",
        data={"current_password": FIRST_LOGIN, "new_password": NEW_PASSWORD, "new_password_repeat": NEW_PASSWORD},
    )
    assert change.status_code == 302
    client.post("/logout")

    fresh = env.app.test_client()
    assert not _logged_in(_login(fresh, NEW_SICIL, FIRST_LOGIN))
    second = _login(fresh, NEW_SICIL, NEW_PASSWORD)
    assert _logged_in(second)
    assert "/account/security-setup" not in second.headers.get("Location", "")
    assert "/account/change-password" not in second.headers.get("Location", "")


def test_guard_new_admin_is_found_by_its_exact_identifiers(env):
    _create_new_admin(env)
    assert _forgot_finds(env, NEW_SICIL)
    assert _forgot_finds(env, NEW_EMAIL)
    assert _forgot_finds(env, NEW_EMAIL.upper())


def test_guard_forgot_password_resets_the_new_admin_after_setup(env):
    _create_new_admin(env)
    client = env.app.test_client()
    _login(client, NEW_SICIL, FIRST_LOGIN)
    client.post("/account/security-setup", data={"security_question": QUESTION, "security_answer": ANSWER})
    client.post(
        "/account/change-password",
        data={"current_password": FIRST_LOGIN, "new_password": NEW_PASSWORD, "new_password_repeat": NEW_PASSWORD},
    )
    reset_password = "AdminLookupTest-Reset-7!"
    env.app.test_client().post(
        "/forgot-password",
        data={"sicil_or_email": NEW_SICIL, "security_answer": ANSWER, "new_password": reset_password, "new_password_repeat": reset_password},
    )
    assert _logged_in(_login(env.app.test_client(), NEW_SICIL, reset_password))


# --------------------------------------------------------------------------------------
# Cause 2: lookup normalisation (web login, /forgot-password, mobile login)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifier",
    (NEW_SICIL.lower(), f"  {NEW_SICIL}  ", f"{NEW_SICIL}​", f"﻿{NEW_EMAIL}", f" {NEW_EMAIL.upper()} "),
)
def test_forgot_password_finds_the_new_admin_by_identifier_variants(env, identifier):
    _create_new_admin(env)
    assert _forgot_finds(env, identifier)


def test_web_login_accepts_a_sicil_typed_in_another_case(env):
    assert _logged_in(_login(env.app.test_client(), _USERS["baskan"][0].lower(), PASSWORD))


@pytest.mark.parametrize("identifier", ("mixed.case@example.gov.tr", "MIXED.CASE@EXAMPLE.GOV.TR", "mx01"))
def test_a_legacy_capitalised_account_is_found_and_logs_in(env, identifier):
    assert _forgot_finds(env, identifier)
    assert _logged_in(_login(env.app.test_client(), identifier, PASSWORD))


@pytest.mark.parametrize("identifier", ("AL02X".lower(), "AL02X@EXAMPLE.GOV.TR", "Mixed.Case@example.gov.tr".lower()))
def test_mobile_login_uses_the_same_lookup(env, identifier):
    response = env.app.test_client().post("/api/mobile/auth/login", json={"username": identifier, "password": PASSWORD})
    assert response.status_code == 200, response.get_data(as_text=True)


def test_guard_case_duplicates_never_log_into_the_wrong_account(env):
    """dup_a / dup_b differ only in case: an ambiguous identifier finds nobody."""
    for identifier in ("dup.user@example.gov.tr", "Dup.User@EXAMPLE.gov.tr"):
        assert not _logged_in(_login(env.app.test_client(), identifier, PASSWORD))
    # The exact stored values still work.
    assert _logged_in(_login(env.app.test_client(), "DP01", PASSWORD))
    assert _logged_in(_login(env.app.test_client(), "DP02", PASSWORD))


def test_guard_wrong_password_is_still_refused_for_a_case_variant(env):
    assert not _logged_in(_login(env.app.test_client(), _USERS["baskan"][0].lower(), "wrong-password-123"))


# --------------------------------------------------------------------------------------
# Uniqueness: case variants are conflicts, and sicil vs e-mail are reported separately
# --------------------------------------------------------------------------------------

SICIL_TAKEN = "Bu sicil numarası zaten kayıtlı."
EMAIL_TAKEN = "Bu e-posta adresi zaten kayıtlı."


def test_a_case_variant_of_an_existing_email_is_a_conflict(env):
    body = _web(env, "admin").post(
        "/admin/users/create", data=_create_form("NEWSIC1", "mixed.case@example.gov.tr", role="personel"), follow_redirects=True
    ).get_data(as_text=True)
    assert _user(env, sicil_no="NEWSIC1") == []
    assert EMAIL_TAKEN in body and SICIL_TAKEN not in body


def test_a_case_variant_of_an_existing_sicil_is_a_conflict(env):
    body = _web(env, "admin").post(
        "/admin/users/create", data=_create_form("mx01", "brand.new@example.gov.tr", role="personel"), follow_redirects=True
    ).get_data(as_text=True)
    assert _user(env, email="brand.new@example.gov.tr") == []
    assert SICIL_TAKEN in body and EMAIL_TAKEN not in body


def test_both_conflicts_are_reported_separately(env):
    body = _web(env, "admin").post(
        "/admin/users/create", data=_create_form("AL03X", "al03x@example.gov.tr", role="personel"), follow_redirects=True
    ).get_data(as_text=True)
    assert SICIL_TAKEN in body and EMAIL_TAKEN in body


def test_personnel_add_reports_both_conflicts(env):
    form = _create_form("AL03X", "AL03X@EXAMPLE.GOV.TR", role="personel")
    body = _web(env, "admin").post("/personnel/add", data=form, follow_redirects=True).get_data(as_text=True)
    assert "sicil numarası ile kayıtlı" in body and "e-posta adresi ile kayıtlı" in body


# --------------------------------------------------------------------------------------
# Cause 1: admin accounts are listed only in the real-admin management view
# --------------------------------------------------------------------------------------

ADMIN_VIEW = "/admin/users?view=admins"


def test_the_admin_accounts_view_lists_admin_accounts_for_a_real_admin(env):
    _create_new_admin(env)
    response = _web(env, "admin").get(ADMIN_VIEW)
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert NEW_SICIL in body and _USERS["other_admin"][0] in body
    assert "no-store" in response.headers.get("Cache-Control", "")


@pytest.mark.parametrize("key", ("baskan", "mixed"))
def test_the_admin_accounts_view_is_closed_to_everyone_else(env, key):
    response = _web(env, key).get(ADMIN_VIEW)
    assert response.status_code in (302, 403, 404)
    assert _USERS["other_admin"][0] not in response.get_data(as_text=True)


@pytest.mark.parametrize("key", ("admin", "baskan"))
@pytest.mark.parametrize("path", ("/admin/users", "/personnel"))
def test_guard_the_general_lists_still_hide_admin_accounts(env, path, key):
    body = _web(env, key).get(path).get_data(as_text=True)
    assert _USERS["other_admin"][0] not in body


# --------------------------------------------------------------------------------------
# Recovery: reissue an initial password without deleting or re-creating the account
# --------------------------------------------------------------------------------------


def _state(env, key_or_id):
    from app.extensions import db
    from app.models import User

    user_id = env.ids[key_or_id] if isinstance(key_or_id, str) else key_or_id
    with env.app.app_context():
        user = db.session.get(User, user_id)
        return SimpleNamespace(
            password_hash=user.password_hash,
            security_stamp=user.security_stamp,
            must_change_password=bool(user.must_change_password),
            must_set_security_question=bool(user.must_set_security_question),
        )


def _audit(env, action):
    from app.models import AuditLog

    with env.app.app_context():
        return [
            SimpleNamespace(user_id=row.user_id, entity_id=row.entity_id, raw=f"{row.old_data_json}{row.new_data_json}{row.summary}")
            for row in AuditLog.query.filter_by(action=action).all()
        ]


def _flashes(client):
    with client.session_transaction() as sess:
        return list(sess.get("_flashes") or [])


def _reissue(client, user_id, actor_password):
    return client.post(
        f"/admin/users/{user_id}/edit",
        data={"form_action": "issue_initial_password", "actor_password": actor_password},
    )


def test_reissue_needs_the_admins_own_password(env):
    target = _create_new_admin(env)
    before = _state(env, target.id)
    response = _reissue(_web(env, "admin"), target.id, "wrong-password-123")
    assert _state(env, target.id).password_hash == before.password_hash
    assert response.status_code == 302
    refused = [row for row in _audit(env, "account.initial_password_reissue_refused") if row.entity_id == target.id]
    assert refused and refused[0].user_id == env.ids["admin"]


def test_reissue_delivers_a_one_time_password_and_audits_it(env, caplog):
    target = _create_new_admin(env)
    before = _state(env, target.id)
    client = _web(env, "admin")
    caplog.set_level("DEBUG")
    response = _reissue(client, target.id, PASSWORD)
    assert response.status_code == 200
    assert "no-store" in response.headers.get("Cache-Control", "")
    body = response.get_data(as_text=True)

    after = _state(env, target.id)
    assert after.password_hash != before.password_hash
    assert after.security_stamp != before.security_stamp
    assert after.must_change_password and after.must_set_security_question

    # The new password is in the response body only: it logs in, the old one does not.
    import re

    match = re.search(r"<code>([^<]+)</code>", body)
    assert match
    credential = match.group(1).strip()
    assert credential not in str(_flashes(client))
    assert credential not in caplog.text
    assert not _logged_in(_login(env.app.test_client(), NEW_SICIL, FIRST_LOGIN))
    first = _login(env.app.test_client(), NEW_SICIL, credential)
    assert _logged_in(first) and "/account/security-setup" in first.headers.get("Location", "")

    rows = [row for row in _audit(env, "account.initial_password_reissued") if row.entity_id == target.id]
    assert len(rows) == 1 and rows[0].user_id == env.ids["admin"]
    assert credential not in rows[0].raw and "pbkdf2" not in rows[0].raw and "scrypt" not in rows[0].raw


def test_reissue_is_refused_for_the_admins_own_account(env):
    before = _state(env, "admin")
    _reissue(_web(env, "admin"), env.ids["admin"], PASSWORD)
    assert _state(env, "admin").password_hash == before.password_hash


def test_reissue_is_refused_for_a_non_admin_account(env):
    before = _state(env, "mixed")
    _reissue(_web(env, "admin"), env.ids["mixed"], PASSWORD)
    assert _state(env, "mixed").password_hash == before.password_hash


def test_reissue_is_refused_for_a_non_admin_actor(env):
    before = _state(env, "other_admin")
    _reissue(_web(env, "baskan"), env.ids["other_admin"], PASSWORD)
    assert _state(env, "other_admin").password_hash == before.password_hash


# --------------------------------------------------------------------------------------
# One-time delivery of the initial password when an account is created
# --------------------------------------------------------------------------------------


def test_create_delivers_the_initial_password_once_and_not_in_the_session_cookie(env):
    client = _web(env, "admin")
    response = client.post("/admin/users/create", data=_create_form("AD9002", "second.admin@example.gov.tr"))
    assert response.status_code == 200
    assert "no-store" in response.headers.get("Cache-Control", "")
    body = response.get_data(as_text=True)
    assert body.count(FIRST_LOGIN) == 1
    assert FIRST_LOGIN not in str(_flashes(client))
