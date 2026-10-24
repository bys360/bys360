"""BYS360_PHASE5_COVERAGE_WAVE5_AGENT2_FILE_CENTER_PERMISSION_ENGINE_CONTRACT

Behavioral contract for app/file_center/permissions.py (role/permission
resolution engine for the Dosya Merkezi feature):

    _effective_role_key, _admin_like_text, _manager_like_text,
    _permission_from_matrix, _permission, ensure_file_center_role_matrix_defaults,
    role_matrix_rows, update_role_matrix_from_form, is_file_center_admin,
    is_file_center_manager, can_use_file_center, can_upload_files,
    can_download_files, can_create_guest_links, can_create_guest_upload_requests,
    can_view_transfers, can_view_requests, can_use_chunk_upload, can_view_logs,
    can_manage_file_center_admin, can_manage_file_center_settings,
    can_manage_file_center_role_matrix, can_manage_file_center_security,
    can_manage_file_center_maintenance, can_manage_file_center_quota_policy,
    menu_context

No prior test in this repo references this module -- this file is its first
coverage. Route-level testing of the quota/role-matrix admin endpoints is a
separate file (test_file_center_quota_and_role_matrix_admin_contract.py, not
touched or duplicated here); this file is pure-logic + DB-backed unit tests
only, no HTTP routes.

Most functions accept an explicit ``user=`` argument and need no Flask
app/request context at all: ``_table_ready()`` defensively catches
``RuntimeError`` when called outside an app context (no bound session), so
even ``_permission`` / the ``can_*`` wrappers work unguarded and simply fall
through to the static ``DEFAULT_ROLE_MATRIX``/heuristic path. Those tests use
plain ``SimpleNamespace`` fakes with no app fixture at all (Group A). Tests
that need to prove real ``FileCenterRolePermission`` DB-row behavior (exact
match wins, inactive rows ignored, fallback substring scan, defaults seeding,
form updates) use a dedicated app+DB fixture, following the proven mandatory
pattern (Config class attributes patched before create_app(); StaticPool +
pysqlite dual-connection isolation-level/explicit-BEGIN fix), with its own
tmp DB directory (C:\\bys360_pytest_tmp_wave5_agent2_fcperm) so this file
shares no state with any other wave/agent (Group B).

BYS360 DEFECT AQ update -- Defect I is now FIXED (was: already known, out of
scope, tracked separately): ``_effective_role_key``/``_admin_like_text``/
``_manager_like_text``/``_permission_from_matrix``'s fallback substring scan
used to run ``if "admin" in text: return "admin"`` against ``role_key(user)``
(``_user_text`` concatenating all 12 fields, including username/email/
department/unit) -- so e.g. an ``email="sysadmin-contact@..."`` on an
otherwise "personel" user misclassified as admin, and a real 12-field
concatenation exploit could reach as far as editing the role-permission
matrix itself. This has been replaced with ``_user_role_values(user)``: each
of 7 genuine role-bearing fields (role/role_key/role_name/role_label/title/
position/job_title -- username/email/department/unit/unit_name excluded) is
normalized and checked individually via EXACT set membership, never
substring/"in" containment on a concatenated blob. ``role_key(user)``/
``_user_text(user)`` themselves are left intact (unused internally now, kept
as existing public surface) -- only the 4 functions that consumed them for
authorization decisions were changed. See the new "BYS360 DEFECT AQ" test
group below for the adversarial coverage this fix requires.

NEW_PRODUCTION_DEFECT (found while implementing, reported rather than
frozen -- see final report): ``_permission()`` has
``if _admin_like_text(user): return True`` as an unconditional early return,
*before* ever consulting ``default_role.permissions.get(field, ...)``. This
means that whenever the DB role-matrix table has no row for a user's
effective role (fresh/unseeded table), *any* field -- not just the ones
DEFAULT_ROLE_MATRIX actually grants -- resolves True for any role whose text
matches an ``ADMIN_ROLE_HINTS`` token. Concretely,
"dosya_merkezi_yetkilisi" is deliberately *not* granted
``can_manage_settings``/``can_manage_maintenance``/``can_manage_role_matrix``
in ``DEFAULT_ROLE_MATRIX`` (those are reserved for sistem_yoneticisi/admin),
but the no-DB fallback path grants all three anyway, because
"dosya_merkezi_yetkilisi" is itself a literal ``ADMIN_ROLE_HINTS`` entry.
Per this wave's rule, that specific per-field assertion is not written here
as "expected" -- instead, "dosya_merkezi_yetkilisi" granularity is only
exercised below via a *seeded* DB matrix row, where ``_permission_from_matrix``
returns the real stored value before this shortcut is ever reached (proven
correct, not buggy, on that path). "admin"/"sistem_yoneticisi" are safe to
exercise in no-DB mode because DEFAULT_ROLE_MATRIX grants them ALL fields
True anyway, so the shortcut's result coincides with the intended default
there. "yonetici"/"personel" are also safe in no-DB mode because neither
matches any ADMIN_ROLE_HINTS token, so the shortcut never fires for them and
the real ``default_role.permissions`` dict is genuinely consulted.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

from app.file_center.permissions import (
    DEFAULT_ROLE_MATRIX,
    _admin_like_text,
    _effective_role_key,
    _manager_like_text,
    _permission,
    _permission_from_matrix,
    can_create_guest_links,
    can_create_guest_upload_requests,
    can_download_files,
    can_manage_file_center_admin,
    can_manage_file_center_maintenance,
    can_manage_file_center_quota_policy,
    can_manage_file_center_role_matrix,
    can_manage_file_center_security,
    can_manage_file_center_settings,
    can_upload_files,
    can_use_chunk_upload,
    can_use_file_center,
    can_view_logs,
    can_view_requests,
    can_view_transfers,
    ensure_file_center_role_matrix_defaults,
    is_file_center_admin,
    is_file_center_manager,
    menu_context,
    role_matrix_rows,
    update_role_matrix_from_form,
)
from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave5_agent2_fcperm")

# All can_* wrapper functions paired with the underlying PERMISSION_FIELDS
# key they read, in the exact order declared in permissions.py.
_CAN_WRAPPERS = (
    (can_use_file_center, "can_use"),
    (can_upload_files, "can_upload_files"),
    (can_download_files, "can_download_files"),
    (can_create_guest_links, "can_create_guest_links"),
    (can_create_guest_upload_requests, "can_create_guest_upload_requests"),
    (can_view_transfers, "can_view_transfers"),
    (can_view_requests, "can_view_requests"),
    (can_use_chunk_upload, "can_use_chunk_upload"),
    (can_view_logs, "can_view_logs"),
    (can_manage_file_center_admin, "can_manage_admin"),
    (can_manage_file_center_settings, "can_manage_settings"),
    (can_manage_file_center_role_matrix, "can_manage_role_matrix"),
    (can_manage_file_center_security, "can_manage_security"),
    (can_manage_file_center_maintenance, "can_manage_maintenance"),
    (can_manage_file_center_quota_policy, "can_manage_quota_policy"),
)


def _default_permissions_for(role_key_value: str) -> dict[str, bool]:
    item = next(i for i in DEFAULT_ROLE_MATRIX if i.role_key == role_key_value)
    return item.permissions


def _user(role: str, *, authenticated: bool = True) -> SimpleNamespace:
    return SimpleNamespace(role=role, is_authenticated=authenticated)


# ---------------------------------------------------------------------------
# Group A -- pure logic, no Flask app/DB context needed at all.
# ---------------------------------------------------------------------------


def test_effective_role_key_exact_admin():
    assert _effective_role_key(_user("admin")) == "admin"


def test_effective_role_key_exact_sistem_yoneticisi():
    assert _effective_role_key(_user("sistem_yoneticisi")) == "sistem_yoneticisi"


def test_effective_role_key_exact_dosya_merkezi_yetkilisi():
    assert _effective_role_key(_user("dosya_merkezi_yetkilisi")) == "dosya_merkezi_yetkilisi"


def test_effective_role_key_exact_yonetici():
    assert _effective_role_key(_user("yonetici")) == "yonetici"


def test_effective_role_key_manager_hint_koordinator_resolves_yonetici():
    # "koordinator" is a MANAGER_HINTS entry, not itself one of the 5
    # DEFAULT_ROLE_MATRIX keys -- proves the manager-hint fallback branch.
    assert _effective_role_key(_user("koordinator")) == "yonetici"


def test_effective_role_key_plain_personel():
    assert _effective_role_key(_user("personel")) == "personel"


def test_effective_role_key_unknown_custom_role_falls_back_to_personel():
    assert _effective_role_key(_user("temizlik_gorevlisi")) == "personel"


@pytest.mark.parametrize("role", ["admin", "sistem_yoneticisi", "dosya_merkezi_yetkilisi"])
def test_admin_like_text_true_for_recognized_admin_hints(role):
    assert _admin_like_text(_user(role)) is True


@pytest.mark.parametrize("role", ["personel", "yonetici", "temizlik_gorevlisi"])
def test_admin_like_text_false_for_non_admin_roles(role):
    assert _admin_like_text(_user(role)) is False


def test_admin_like_text_true_for_all_caps_turkish_capital_i_role_value():
    # BYS360 DEFECT AQ: _normalize() used to call .lower() before
    # .translate(); Python's 'İ'.lower() (capital dotted I, U+0130)
    # produces the two-codepoint sequence 'i' + COMBINING DOT ABOVE
    # (U+0307), not plain 'i', so the translate table's 'İ' entry was dead
    # code and a realistic all-caps HR value like "SİSTEM YÖNETİCİSİ"
    # failed to normalize to "sistem_yoneticisi", silently denying a real
    # admin. This is now fixed.
    assert _admin_like_text(_user("SİSTEM YÖNETİCİSİ")) is True


@pytest.mark.parametrize("role", ["yonetici", "koordinator", "mudur", "baskan"])
def test_manager_like_text_true_for_manager_hints(role):
    assert _manager_like_text(_user(role)) is True


@pytest.mark.parametrize("role", ["personel", "admin"])
def test_manager_like_text_false_for_non_manager_roles(role):
    assert _manager_like_text(_user(role)) is False


# ---------------------------------------------------------------------------
# BYS360 DEFECT AQ -- mandatory adversarial coverage for the substring-match
# fix (canonical authorized role -> allowed; substring lookalike -> denied;
# unknown role -> denied; free-form unvan/display text -> denied; helper
# failure/missing-field -> denied).
# ---------------------------------------------------------------------------


def test_admin_like_text_denies_email_and_department_lookalikes_not_role():
    # BYS360 DEFECT AQ adversarial case: the confirmed live exploit -- an
    # ordinary "personel" whose email/department merely CONTAINS "admin"/
    # "sistem"+"yonetici" must not be treated as admin-like. email/
    # department are not role-identity fields at all.
    user = SimpleNamespace(
        role="personel", role_key=None, role_name=None, role_label=None,
        title=None, position=None, job_title=None,
        username="user123", email="office-admin@bys360.test",
        department="Sistem Yönetimi Destek Birimi", unit=None, unit_name=None,
        is_authenticated=True,
    )
    assert _admin_like_text(user) is False
    assert _effective_role_key(user) == "personel"


def test_admin_like_text_denies_baskanligi_uzmani_lookalike_via_title():
    user = SimpleNamespace(
        role="personel", role_key=None, role_name=None, role_label=None,
        title="Başkanlığı Uzmanı", position=None, job_title=None,
        username=None, email=None, department=None, unit=None, unit_name=None,
        is_authenticated=True,
    )
    assert _admin_like_text(user) is False
    assert _manager_like_text(user) is False
    assert _effective_role_key(user) == "personel"


def test_manager_like_text_denies_insan_kaynaklari_yoneticisi_job_title_lookalike():
    # "İnsan Kaynakları Yöneticisi" (HR Manager) contains "yonetici" as a
    # substring but is not itself an exact MANAGER_HINTS member.
    user = SimpleNamespace(
        role="personel", role_key=None, role_name=None, role_label=None,
        title=None, position=None, job_title="İnsan Kaynakları Yöneticisi",
        username=None, email=None, department=None, unit=None, unit_name=None,
        is_authenticated=True,
    )
    assert _manager_like_text(user) is False


def test_admin_like_text_allows_real_canonical_role_field():
    user = _user("sistem_yoneticisi")
    assert _admin_like_text(user) is True


def test_effective_role_key_denies_unknown_role_with_no_matching_fields():
    user = SimpleNamespace(
        role="", role_key=None, role_name=None, role_label=None,
        title=None, position=None, job_title=None,
        username=None, email=None, department=None, unit=None, unit_name=None,
        is_authenticated=True,
    )
    assert _effective_role_key(user) == "personel"
    assert _admin_like_text(user) is False
    assert _manager_like_text(user) is False


def test_permission_fail_closed_unauthenticated_across_all_wrappers():
    user = _user("admin", authenticated=False)
    for wrapper, _field in _CAN_WRAPPERS:
        assert wrapper(user) is False, f"{wrapper.__name__} should be False for unauthenticated user"
    assert _permission(user, "can_use", default=True) is False
    assert _permission_from_matrix(user, "can_use") is False
    assert is_file_center_admin(user) is False
    assert is_file_center_manager(user) is False


def test_permission_default_matrix_personel_no_db():
    user = _user("personel")
    expected = _default_permissions_for("personel")
    for wrapper, field in _CAN_WRAPPERS:
        assert wrapper(user) == expected[field], f"{wrapper.__name__} mismatched personel default for {field}"


def test_permission_default_matrix_yonetici_no_db():
    user = _user("yonetici")
    expected = _default_permissions_for("yonetici")
    for wrapper, field in _CAN_WRAPPERS:
        assert wrapper(user) == expected[field], f"{wrapper.__name__} mismatched yonetici default for {field}"


def test_permission_default_matrix_admin_full_access_no_db():
    user = _user("admin")
    for wrapper, _field in _CAN_WRAPPERS:
        assert wrapper(user) is True, f"{wrapper.__name__} should be True for admin"


def test_permission_default_matrix_sistem_yoneticisi_full_access_no_db():
    user = _user("sistem_yoneticisi")
    for wrapper, _field in _CAN_WRAPPERS:
        assert wrapper(user) is True, f"{wrapper.__name__} should be True for sistem_yoneticisi"


def test_permission_unknown_role_falls_back_to_personel_defaults_no_db():
    user = _user("temizlik_gorevlisi")
    expected = _default_permissions_for("personel")
    for wrapper, field in _CAN_WRAPPERS:
        assert wrapper(user) == expected[field], f"{wrapper.__name__} should use personel default for unknown role"


def test_is_file_center_manager_true_for_yonetici_hint_no_db():
    assert is_file_center_manager(_user("yonetici")) is True
    assert is_file_center_manager(_user("koordinator")) is True


def test_is_file_center_manager_false_for_plain_personel_no_db():
    assert is_file_center_manager(_user("personel")) is False


def test_is_file_center_admin_matches_can_manage_admin_wrapper_no_db():
    for role in ("personel", "yonetici", "admin", "sistem_yoneticisi"):
        user = _user(role)
        assert is_file_center_admin(user) == can_manage_file_center_admin(user)


def test_menu_context_matches_direct_can_calls_no_db():
    user = _user("yonetici")
    ctx = menu_context(user)
    assert ctx["can_use"] == can_use_file_center(user)
    assert ctx["can_upload"] == can_upload_files(user)
    assert ctx["can_logs"] == can_view_logs(user)
    assert ctx["can_admin"] == can_manage_file_center_admin(user)
    assert ctx["can_settings"] == can_manage_file_center_settings(user)
    assert ctx["can_security"] == can_manage_file_center_security(user)
    assert ctx["can_manager"] == is_file_center_manager(user)
    assert ctx["can_quota_policy"] == can_manage_file_center_quota_policy(user)


def test_menu_context_all_false_for_unauthenticated_no_db():
    user = _user("admin", authenticated=False)
    ctx = menu_context(user)
    assert all(value is False for value in ctx.values()), ctx


# ---------------------------------------------------------------------------
# Group B -- DB-backed FileCenterRolePermission matrix contract.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-file-center-permission-engine-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "fc-permission-engine-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"agent2_fcperm_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # Config.SQLALCHEMY_DATABASE_URI is a class attribute frozen the first
    # time config.py is imported in this pytest process, and Flask-SQLAlchemy
    # 3.x lazily binds+caches the per-app Engine on first db.engine/db.session
    # touch during create_app()'s own bootstrap -- so it must be patched onto
    # Config BEFORE create_app() is called, not onto flask_app.config after.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def test_ensure_defaults_creates_five_rows_when_table_empty(app):
    from app.extensions import db

    with app.app_context():
        result = ensure_file_center_role_matrix_defaults()
        db.session.commit()
        assert result == {"created": 5, "updated": 0}
        rows = role_matrix_rows()
        assert len(rows) == 5
        assert {row.role_key for row in rows} == {item.role_key for item in DEFAULT_ROLE_MATRIX}


def test_ensure_defaults_preserves_explicit_false_no_backfill_on_second_call(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        ensure_file_center_role_matrix_defaults()
        db.session.commit()

        # sistem_yoneticisi's DEFAULT_ROLE_MATRIX entry says can_manage_quota_policy
        # should be True -- explicitly flip it to False (a real, non-null value,
        # simulating a prior deliberate admin edit) and commit.
        row = FileCenterRolePermission.query.filter_by(role_key="sistem_yoneticisi").one()
        row.can_manage_quota_policy = False
        db.session.commit()

        result = ensure_file_center_role_matrix_defaults()
        db.session.commit()
        # Nothing should be backfilled: the field is already a real boolean
        # (False), not None, so ensure_... must leave it alone.
        assert result == {"created": 0, "updated": 0}

        reread = FileCenterRolePermission.query.filter_by(role_key="sistem_yoneticisi").one()
        assert reread.can_manage_quota_policy is False


def test_role_matrix_rows_ordered_by_id_asc(app):
    from app.extensions import db

    with app.app_context():
        ensure_file_center_role_matrix_defaults()
        db.session.commit()
        rows = role_matrix_rows()
        ids = [row.id for row in rows]
        assert ids == sorted(ids)
        assert len(ids) == len(set(ids))


def test_exact_db_role_key_match_wins_over_default(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        # personel's DEFAULT_ROLE_MATRIX entry says can_manage_admin=False --
        # seed a real DB row that deliberately contradicts that default.
        db.session.add(FileCenterRolePermission(
            role_key="personel",
            role_label="Personel (override)",
            description="",
            can_manage_admin=True,
        ))
        db.session.commit()

        user = _user("personel")
        assert can_manage_file_center_admin(user) is True
        assert _permission_from_matrix(user, "can_manage_admin") is True


def test_is_active_false_row_ignored_by_exact_match_and_fallback_scan(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        # Inactive row for "personel" that also contradicts the True default
        # for can_use -- must be ignored by both the exact-key lookup
        # (filter_by(..., is_active=True)) and the fallback substring scan
        # (filter_by(is_active=True)).
        db.session.add(FileCenterRolePermission(
            role_key="personel",
            role_label="Personel (inactive override)",
            description="",
            is_active=False,
            can_use=False,
        ))
        db.session.commit()

        user = _user("personel")
        assert _permission_from_matrix(user, "can_use") is None
        # Falls through to the static default (True), not the inactive row's False.
        assert can_use_file_center(user) is True


# BYS360 DEFECT AQ: bu test önceden fallback taramasının "prefix/substring"
# eşleşmesini ("saha_teknisyeni_kidemli" rol metni, "saha_teknisyeni" DB
# satırının role_key'ini ALT DİZE olarak içerdiği için eşleşiyordu)
# "kasıtlı" olarak kilitliyordu. Bu davranışın gerçek bir ürün gereksinimi
# olduğuna dair kod tabanında başka hiçbir kanıt yok; aynı mekanizma canlı
# bir yetki açığının kök nedeniydi (bkz. üstteki modül notu). Fallback
# taraması artık TAM eşleşme gerektirir -- aşağıdaki iki test hem düzeltilen
# (artık eşleşmeyen) hem de hâlâ çalışan (tam eşleşen) durumu kilitler.
def test_permission_matrix_fallback_scan_no_longer_matches_hierarchical_prefix(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        db.session.add(FileCenterRolePermission(
            role_key="saha_teknisyeni",
            role_label="Saha Teknisyeni",
            description="",
            can_view_logs=True,
        ))
        db.session.commit()

        # "saha_teknisyeni_kidemli" is not an EXACT match for the DB row's
        # role_key "saha_teknisyeni" -- must no longer inherit that row.
        user = _user("saha_teknisyeni_kidemli")
        assert _permission_from_matrix(user, "can_view_logs") is None
        assert can_view_logs(user) is False


def test_permission_matrix_fallback_scan_still_matches_exact_custom_role(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        db.session.add(FileCenterRolePermission(
            role_key="saha_teknisyeni",
            role_label="Saha Teknisyeni",
            description="",
            can_view_logs=True,
        ))
        db.session.commit()

        user = _user("saha_teknisyeni")
        assert _permission_from_matrix(user, "can_view_logs") is True
        assert can_view_logs(user) is True


def test_permission_matrix_fallback_scan_denies_email_department_lookalike(app):
    # BYS360 DEFECT AQ adversarial case: the confirmed live exploit -- a
    # custom role_key/label must not be granted via username/email/
    # department/unit containment, only via a genuine role field.
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        db.session.add(FileCenterRolePermission(
            role_key="vip",
            role_label="VIP",
            description="",
            can_view_logs=True,
        ))
        db.session.commit()

        user = SimpleNamespace(
            role="personel", is_authenticated=True,
            email="vip-support@bys360.test", department="VIP Destek Birimi",
        )
        assert _permission_from_matrix(user, "can_view_logs") is None
        assert can_view_logs(user) is False


def test_db_seeded_dosya_merkezi_yetkilisi_respects_granular_false_fields(app):
    from app.extensions import db

    with app.app_context():
        # Contrast case for the NEW_PRODUCTION_DEFECT documented at module
        # scope: once the matrix table is actually seeded, the *real* stored
        # values are returned directly by _permission_from_matrix, before the
        # buggy _admin_like_text early-return in _permission() is ever
        # reached -- so this role's intentionally-False fields stay False.
        ensure_file_center_role_matrix_defaults()
        db.session.commit()

        user = _user("dosya_merkezi_yetkilisi")
        assert can_manage_file_center_settings(user) is False
        assert can_manage_file_center_maintenance(user) is False
        assert can_manage_file_center_role_matrix(user) is False
        # ...while the fields DEFAULT_ROLE_MATRIX actually grants this role
        # remain True.
        assert can_manage_file_center_admin(user) is True
        assert can_manage_file_center_security(user) is True
        assert can_manage_file_center_quota_policy(user) is True


def test_update_role_matrix_from_form_valid_updates(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        ensure_file_center_role_matrix_defaults()
        db.session.commit()
        row = FileCenterRolePermission.query.filter_by(role_key="personel").one()
        assert row.can_view_logs is False

        form = {
            f"role_{row.id}_role_label": "Personel (Updated)",
            f"role_{row.id}_description": "Updated description",
            f"role_{row.id}_is_active": "on",
            f"role_{row.id}_can_view_logs": "true",
        }
        changed = update_role_matrix_from_form(form)
        db.session.commit()
        assert changed >= 3

        reread = FileCenterRolePermission.query.filter_by(role_key="personel").one()
        assert reread.role_label == "Personel (Updated)"
        assert reread.description == "Updated description"
        assert reread.can_view_logs is True


def test_update_role_matrix_from_form_missing_values_no_crash(app):
    with app.app_context():
        ensure_file_center_role_matrix_defaults()

        # Empty form: no row_* keys, no new_role_* keys at all.
        changed = update_role_matrix_from_form({})

        assert isinstance(changed, int)
        assert len(role_matrix_rows()) == 5


def test_update_role_matrix_from_form_new_custom_role_baseline_only(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        form = {"new_role_key": "saha_destek", "new_role_label": "Saha Destek"}
        changed = update_role_matrix_from_form(form)
        db.session.commit()
        assert changed >= 1

        row = FileCenterRolePermission.query.filter_by(role_key="saha_destek").one()
        assert row.role_label == "Saha Destek"
        assert row.can_use is True
        assert row.can_upload_files is True
        assert row.can_download_files is True
        assert row.can_view_transfers is True
        assert row.can_view_requests is True
        # Explicit contrast with Defect I / the NEW_PRODUCTION_DEFECT: this
        # code path is conservative -- no admin/manage field is granted to a
        # freshly-created custom role.
        assert row.can_manage_admin is False
        assert row.can_manage_security is False
        assert row.can_manage_settings is False
        assert row.can_manage_maintenance is False
        assert row.can_manage_role_matrix is False
        assert row.can_manage_quota_policy is False
        assert row.can_view_logs is False


def test_update_role_matrix_from_form_duplicate_new_role_key_is_noop(app):
    with app.app_context():
        form = {"new_role_key": "saha_destek", "new_role_label": "Saha Destek"}
        update_role_matrix_from_form(form)
        rows_after_first = role_matrix_rows()
        count_after_first = len(rows_after_first)
        assert count_after_first == 6  # 5 defaults (auto-seeded) + 1 new role

        update_role_matrix_from_form(form)
        rows_after_second = role_matrix_rows()
        assert len(rows_after_second) == count_after_first  # no duplicate row created


def test_update_role_matrix_from_form_permission_field_truthy_string_set(app):
    from app.extensions import db
    from app.models.file_center_models import FileCenterRolePermission

    with app.app_context():
        ensure_file_center_role_matrix_defaults()
        db.session.commit()
        row = FileCenterRolePermission.query.filter_by(role_key="personel").one()

        # Only the exact {"on","true","1","yes"} strings should count as
        # truthy; anything else (including a naive "True"/"yes please") must
        # be treated as unchecked/False.
        form = {f"role_{row.id}_can_manage_security": "yes"}
        update_role_matrix_from_form(form)
        db.session.commit()
        reread = FileCenterRolePermission.query.filter_by(role_key="personel").one()
        assert reread.can_manage_security is True

        form2 = {f"role_{row.id}_can_manage_security": "please-enable"}
        update_role_matrix_from_form(form2)
        db.session.commit()
        reread2 = FileCenterRolePermission.query.filter_by(role_key="personel").one()
        assert reread2.can_manage_security is False
