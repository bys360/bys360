"""Behavior contract for app/main_handlers/account_settings_helpers.py::settings_page().

Routed via app/account/routes.py: /settings, /admin/settings,
/admin/settings/performance, /admin/settings/security -- GET+POST, all four
paths point at the same view function, itself wrapped in a route-level
try/except that converts any UNHANDLED exception from the real settings_page()
body into an HTTP 200 "safe mode" fallback page (never a 500). Every branch
tested below has its own internal try/except, so this fallback path is not
itself exercised here.

This is a pre-refactor safety net: it pins CURRENT behavior (including a few
known legacy quirks called out explicitly below) so a later production
refactor of settings_page() cannot silently change behavior. It intentionally
does not "fix" anything it finds.

Deliberately uses a per-test, file-backed SQLite app (see _make_app) rather
than the shared session-scoped app/client fixtures in tests/conftest.py: this
file does heavy DB-mutation, commit-fault, and rollback testing, and the
shared session app is mutated by other tests during a full run. Isolation
here matches the already-proven pattern in
tests/security/test_phase13b_anonymous_write_negative.py and
tests/security/test_phase13b_csrf_and_scope.py.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from flask import template_rendered

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "settings_behavior_tmp" / "test_dbs"
DEFAULT_PASSWORD = "SettingsBehaviorTest1!"


def _make_app(monkeypatch, **env_overrides):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-settings-behavior-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, email, role="personel", birim=None, password=DEFAULT_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Behavior",
            soyad="Contract",
            role=role,
            birim=birim,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=DEFAULT_PASSWORD):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _flashes(client):
    """Read (without consuming) the session's flashed (category, message)
    tuples. Safe right after a 302 response, since a redirect response body
    never triggers get_flashed_messages()."""
    with client.session_transaction() as sess:
        return list(sess.get("_flashes", []))


@contextmanager
def _captured_template_context(app):
    captured: list[dict] = []

    def _record(sender, template, context, **extra):
        captured.append(dict(context))

    template_rendered.connect(_record, app)
    try:
        yield captured
    finally:
        template_rendered.disconnect(_record, app)


def _role_menu_default(app, *, role_name, menu_key):
    with app.app_context():
        from app.models import RoleMenuDefault

        row = (
            RoleMenuDefault.query
            .filter_by(role_name=role_name, menu_key=menu_key)
            .order_by(RoleMenuDefault.id.desc())
            .first()
        )
        return None if row is None else bool(row.is_visible)


def _seed_role_menu_default(app, *, role_name, menu_key, is_visible, source_type="seed"):
    with app.app_context():
        from app.extensions import db
        from app.models import RoleMenuDefault

        row = RoleMenuDefault.query.filter_by(role_name=role_name, menu_key=menu_key).first()
        if row is None:
            row = RoleMenuDefault(role_name=role_name, menu_key=menu_key, is_visible=is_visible, source_type=source_type)
            db.session.add(row)
        else:
            row.is_visible = is_visible
            row.source_type = source_type
        db.session.commit()


def _system_setting_value(app, *, setting_key):
    with app.app_context():
        from app.models import SystemSetting

        row = SystemSetting.query.filter_by(setting_key=setting_key).first()
        return None if row is None else row.value_text


def _seed_named_archive(app, *, archive_name, scope, visible_keys):
    with app.app_context():
        from app.extensions import db
        from app.main_handlers.account_visibility_helpers import (
            SETTINGS_ARCHIVE_GROUP_KEY,
            _build_settings_archive_setting_key,
        )
        from app.models import SystemSetting

        setting_key = _build_settings_archive_setting_key(scope, archive_name)
        row = SystemSetting(
            setting_key=setting_key,
            group_key=SETTINGS_ARCHIVE_GROUP_KEY,
            label=archive_name,
            value_type="json",
            is_active=True,
            value_text=json.dumps(
                {"archive_name": archive_name, "archive_scope": scope, "visible_keys": list(visible_keys)}
            ),
        )
        db.session.add(row)
        db.session.commit()
        return setting_key


def _live_menu_key(app) -> str:
    """Derive any real, live menu key -- for tests that need a valid form
    field name but don't care which specific key, so they are NOT
    incidentally coupled to the "general" role-matrix-group code path (see
    _general_matrix_menu_key, which deliberately IS coupled to that path for
    the tests that specifically exercise it)."""
    with app.app_context():
        from app.main_handlers.account_settings_helpers import (
            _bys360_personnel_feature_matrix_v14_dedupe_items,
            flatten_settings_menu_definitions,
        )

        flat = _bys360_personnel_feature_matrix_v14_dedupe_items(flatten_settings_menu_definitions())
        return flat[0]["key"]


def _general_matrix_menu_key(app) -> str:
    """Derive one real, live menu key scoped to the "general" role-matrix
    group the same way settings_page() itself builds grouped/flat menu items
    (account_settings_helpers.py lines 144-146) and resolves a matrix's scoped
    policy items (_get_role_matrix_policy_items_or_raise). Avoids hardcoding a
    catalog key that could drift as the menu catalog changes."""
    with app.app_context():
        from app.main_handlers.account_communication_helpers import (
            _get_role_matrix_policy_items_or_raise,
        )
        from app.main_handlers.account_settings_helpers import (
            _bys360_personnel_feature_matrix_v14_dedupe_grouped_menu,
            _bys360_personnel_feature_matrix_v14_dedupe_items,
            extend_flat_menu_items_with_assistant_role_matrix_items,
            flatten_settings_menu_definitions,
            get_grouped_menu_definitions,
        )

        grouped = _bys360_personnel_feature_matrix_v14_dedupe_grouped_menu(get_grouped_menu_definitions())
        flat = _bys360_personnel_feature_matrix_v14_dedupe_items(flatten_settings_menu_definitions())
        flat = _bys360_personnel_feature_matrix_v14_dedupe_items(
            extend_flat_menu_items_with_assistant_role_matrix_items(flat)
        )
        _config, policy_items = _get_role_matrix_policy_items_or_raise("general", grouped, flat)
        return policy_items[0]["key"]


# ---------------------------------------------------------------------------
# GET / authorization contract
# ---------------------------------------------------------------------------


def test_get_authorized_returns_200_with_expected_context(app, client):
    _create_user(app, sicil_no="sb001", email="sb001@ktb.gov.tr", role="admin")
    _login(client, "sb001")

    with _captured_template_context(app) as captured:
        response = client.get("/settings")

    assert response.status_code == 200
    assert len(captured) == 1
    context = captured[0]
    expected_subset = {
        "users", "grouped_menu_definitions", "selected_user", "selected_rule_map",
        "settings_matrix", "role_default_keys", "settings_presets",
        "bulk_settings_profiles", "bulk_target_users", "bulk_result_summary",
        "role_options", "birim_options", "foundation_context",
        "communication_role_matrix", "assistant_role_matrix",
        "settings_role_matrix_groups", "phase1_seed_summary", "profile_context",
        "settings_section_links", "selected_profile_resolution", "compare_user",
        "user_diff_context", "settings_archives", "selected_archive_key",
        "settings_ui_panel_context",
    }
    assert expected_subset <= set(context)
    assert context["phase1_seed_summary"]["ok"] is True


def test_get_anonymous_redirects_to_login(client):
    response = client.get("/settings", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


@pytest.mark.parametrize("role", ["personel", "birim_sorumlusu", "koordinator"])
def test_get_authenticated_wrong_role_returns_403(app, client, role):
    _create_user(app, sicil_no=f"sb01{role[:3]}", email=f"sb01{role[:3]}@ktb.gov.tr", role=role)
    _login(client, f"sb01{role[:3]}")

    response = client.get("/settings", follow_redirects=False)

    assert response.status_code == 403


def test_get_request_writes_no_seed_and_the_explicit_sync_is_idempotent(app, client):
    """K13 (owner decision 19 Oct 2026): rendering /settings writes nothing; the phase-1
    seed (ensure_settings_phase1_seeded: RoleMenuDefault/SystemSetting/ModuleSetting rows)
    runs only on the real admin's explicit form_action "sync_role_defaults" and stays
    idempotent on a second sync. Replaces the former pin of the per-request GET seed."""
    _create_user(app, sicil_no="sb002", email="sb002@ktb.gov.tr", role="admin")
    _login(client, "sb002")

    with app.app_context():
        from app.models import RoleMenuDefault
        assert RoleMenuDefault.query.count() == 0

    first = client.get("/settings")
    assert first.status_code == 200
    with app.app_context():
        from app.models import RoleMenuDefault
        assert RoleMenuDefault.query.count() == 0

    synced = client.post("/settings", data={"form_action": "sync_role_defaults"})
    assert synced.status_code == 302
    with app.app_context():
        from app.models import RoleMenuDefault
        seeded_count = RoleMenuDefault.query.filter_by(source_type="seed").count()
        assert seeded_count > 0

    second = client.post("/settings", data={"form_action": "sync_role_defaults"})
    assert second.status_code == 302
    with app.app_context():
        from app.models import RoleMenuDefault
        assert RoleMenuDefault.query.filter_by(source_type="seed").count() == seeded_count


# ---------------------------------------------------------------------------
# save_system_foundation
# ---------------------------------------------------------------------------


def test_save_system_foundation_success_changes_real_db_value(app, client):
    _create_user(app, sicil_no="sb010", email="sb010@ktb.gov.tr", role="admin")
    _login(client, "sb010")

    response = client.post(
        "/settings",
        data={
            "form_action": "save_system_foundation",
            "system__general__system_name": "BYS360 Behavior Contract Kurum Adi",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    assert _system_setting_value(app, setting_key="general.system_name") == "BYS360 Behavior Contract Kurum Adi"


# ---------------------------------------------------------------------------
# Validation-failure guard clauses
# ---------------------------------------------------------------------------


def test_apply_named_archive_missing_archive_is_rejected(app, client):
    _create_user(app, sicil_no="sb020", email="sb020@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb021", email="sb021@ktb.gov.tr", role="personel")
    _login(client, "sb020")

    response = client.post(
        "/settings",
        data={
            "form_action": "apply_named_archive",
            "user_id": str(target_id),
            "archive_key": "settings_archive::general::does-not-exist",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("warning", "Uygulanacak arşiv seçilemedi.")
    with app.app_context():
        from app.models import RoleMenuDefault
        assert RoleMenuDefault.query.filter_by(source_type="manual").count() == 0


def test_save_role_matrix_group_invalid_matrix_key_falls_back_to_flash_danger(app, client):
    _create_user(app, sicil_no="sb022", email="sb022@ktb.gov.tr", role="admin")
    _login(client, "sb022")

    response = client.post(
        "/settings",
        data={"form_action": "save_role_matrix_group__totally_bogus_matrix_v1"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "section=module-role-matrices" in response.headers.get("Location", "")
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "danger"
    assert "Rol matrisi kaydedilirken hata oluştu" in flashes[-1][1]


# ---------------------------------------------------------------------------
# save_role_matrix_group__* / reset_role_matrix_group__*
# ---------------------------------------------------------------------------


def test_save_role_matrix_group_general_success_sets_role_visible(app, client):
    _create_user(app, sicil_no="sb030", email="sb030@ktb.gov.tr", role="admin")
    menu_key = _general_matrix_menu_key(app)
    _login(client, "sb030")

    response = client.post(
        "/settings",
        data={
            "form_action": "save_role_matrix_group__general",
            f"role_matrix__general__personel__{menu_key}": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "section=general-role-policy" in response.headers.get("Location", "")
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    assert _role_menu_default(app, role_name="personel", menu_key=menu_key) is True


def test_reset_role_matrix_group_general_restores_static_default(app, client):
    _create_user(app, sicil_no="sb031", email="sb031@ktb.gov.tr", role="admin")
    menu_key = _general_matrix_menu_key(app)
    with app.app_context():
        from app.services.settings_service import get_role_default_menu_keys
        static_visible = menu_key in get_role_default_menu_keys("personel", prefer_database=False)
    # Force the DB row to the OPPOSITE of the static default and mark it
    # "manual" -- the assertion below can only pass if reset genuinely
    # re-derives from the static catalog, not if it just leaves the row alone.
    _seed_role_menu_default(app, role_name="personel", menu_key=menu_key, is_visible=not static_visible, source_type="manual")
    _login(client, "sb031")

    response = client.post(
        "/settings",
        data={"form_action": "reset_role_matrix_group__general"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert _role_menu_default(app, role_name="personel", menu_key=menu_key) is static_visible


def test_save_role_matrix_group_promotes_unrelated_seed_rows_to_manual(app, client):
    """Documented pre-existing quirk, pinned as current behavior (NOT
    something this test recommends as correct): save_role_menu_defaults is
    called with all_menu_keys = the FULL live catalog for every role-matrix
    save, not just the edited matrix's scope (account_settings_helpers.py
    line 253). In save_role_menu_defaults_handler
    (app/services/settings/menu_profile_access.py), the update condition is
    `row.is_visible != desired OR row.source_type != "manual"` -- so an
    out-of-scope row whose visibility is unchanged still gets its
    source_type silently promoted from "seed" to "manual"."""
    _create_user(app, sicil_no="sb032", email="sb032@ktb.gov.tr", role="admin")
    general_key = _general_matrix_menu_key(app)

    with app.app_context():
        from app.main_handlers.account_communication_helpers import (
            _get_role_matrix_policy_items_or_raise,
        )
        from app.main_handlers.account_settings_helpers import (
            _bys360_personnel_feature_matrix_v14_dedupe_grouped_menu,
            _bys360_personnel_feature_matrix_v14_dedupe_items,
            extend_flat_menu_items_with_assistant_role_matrix_items,
            flatten_settings_menu_definitions,
            get_grouped_menu_definitions,
        )

        grouped = _bys360_personnel_feature_matrix_v14_dedupe_grouped_menu(get_grouped_menu_definitions())
        flat = _bys360_personnel_feature_matrix_v14_dedupe_items(flatten_settings_menu_definitions())
        flat = _bys360_personnel_feature_matrix_v14_dedupe_items(
            extend_flat_menu_items_with_assistant_role_matrix_items(flat)
        )
        _config, general_items = _get_role_matrix_policy_items_or_raise("general", grouped, flat)
        general_keys = {item["key"] for item in general_items}
        out_of_scope_key = next(item["key"] for item in flat if item["key"] not in general_keys)

    _seed_role_menu_default(app, role_name="personel", menu_key=out_of_scope_key, is_visible=False, source_type="seed")
    _login(client, "sb032")

    response = client.post(
        "/settings",
        data={
            "form_action": "save_role_matrix_group__general",
            f"role_matrix__general__personel__{general_key}": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        from app.models import RoleMenuDefault
        row = RoleMenuDefault.query.filter_by(role_name="personel", menu_key=out_of_scope_key).first()
        assert row is not None
        assert row.is_visible is False        # visibility itself: unchanged
        assert row.source_type == "manual"     # source_type: silently promoted


def test_save_role_matrix_group_partial_apply_when_mid_loop_role_fails(app, client, monkeypatch):
    """save_role_matrix_group__* commits PER ROLE inside a loop over the
    fixed 8-role COMMUNICATION_POLICY_ROLE_OPTIONS list
    (account_communication_helpers.py), with the single success/danger flash
    fired only AFTER the whole loop (account_settings_helpers.py lines
    243-262). A failure partway through must leave roles processed BEFORE the
    failure already durably committed, while the user only ever sees one
    undifferentiated danger flash -- a real partial-apply risk, not something
    this test "fixes"."""
    import app.main_handlers.account_settings_helpers as settings_helpers
    from app.main_handlers import account_communication_helpers as comm_helpers

    _create_user(app, sicil_no="sb033", email="sb033@ktb.gov.tr", role="admin")
    menu_key = _general_matrix_menu_key(app)
    role_order = [role_key for role_key, _label in comm_helpers.COMMUNICATION_POLICY_ROLE_OPTIONS]
    fail_at_role = role_order[3]

    real_save = settings_helpers.save_role_menu_defaults
    seen_roles: list[str] = []

    def _fault_fourth_role(role_key, all_menu_keys, visible_keys, *, updated_by_user_id=None):
        seen_roles.append(role_key)
        if role_key == fail_at_role:
            raise RuntimeError("BYS360-TEST-INDUCED-MID-LOOP-ROLE-FAILURE")
        return real_save(role_key, all_menu_keys, visible_keys, updated_by_user_id=updated_by_user_id)

    monkeypatch.setattr(settings_helpers, "save_role_menu_defaults", _fault_fourth_role)
    _login(client, "sb033")

    response = client.post(
        "/settings",
        data={
            "form_action": "save_role_matrix_group__general",
            f"role_matrix__general__{role_order[0]}__{menu_key}": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert seen_roles == role_order[:4]  # stopped exactly at the fault, in fixed order

    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "danger"

    # Role 0 was processed (and internally committed) BEFORE the fault fired.
    assert _role_menu_default(app, role_name=role_order[0], menu_key=menu_key) is True


# ---------------------------------------------------------------------------
# bulk_apply_profile
# ---------------------------------------------------------------------------


def test_bulk_apply_profile_dynamic_role_defaults_preserves_unrelated_user(app, client):
    _create_user(app, sicil_no="sb040", email="sb040@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb041", email="sb041@ktb.gov.tr", role="personel", birim="Birim-X")
    sentinel_id = _create_user(app, sicil_no="sb042", email="sb042@ktb.gov.tr", role="koordinator", birim="Birim-Y")
    _login(client, "sb040")

    response = client.post(
        "/settings",
        data={
            "form_action": "bulk_apply_profile",
            "bulk_profile_key": "dynamic::role_defaults",
            "bulk_scope_type": "role",
            "bulk_role": "personel",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    with app.app_context():
        from app.models import UserMenuPermission
        assert UserMenuPermission.query.filter_by(user_id=target_id).count() > 0
        assert UserMenuPermission.query.filter_by(user_id=sentinel_id).count() == 0


def test_bulk_apply_profile_writes_no_audit_log_rows(app, client):
    """Documented pre-existing audit-trail gap, pinned as current behavior:
    bulk_apply_profile (account_settings_helpers.py lines 365-413) is the
    highest-blast-radius branch (can touch every user in a role/birim scope
    at once) yet never writes a SettingsChangeLog row."""
    _create_user(app, sicil_no="sb043", email="sb043@ktb.gov.tr", role="admin")
    _create_user(app, sicil_no="sb044", email="sb044@ktb.gov.tr", role="personel")
    _login(client, "sb043")

    with app.app_context():
        from app.models import SettingsChangeLog
        before = SettingsChangeLog.query.count()

    response = client.post(
        "/settings",
        data={
            "form_action": "bulk_apply_profile",
            "bulk_profile_key": "dynamic::role_defaults",
            "bulk_scope_type": "role",
            "bulk_role": "personel",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        from app.models import SettingsChangeLog
        assert SettingsChangeLog.query.count() == before


# ---------------------------------------------------------------------------
# export / import visibility template
# ---------------------------------------------------------------------------


def test_export_visibility_template_returns_json_attachment(app, client):
    _create_user(app, sicil_no="sb050", email="sb050@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb051", email="sb051@ktb.gov.tr", role="personel")
    _login(client, "sb050")

    response = client.post(
        "/settings",
        data={"form_action": "export_visibility_template", "user_id": str(target_id)},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    disposition = response.headers.get("Content-Disposition", "")
    assert "attachment" in disposition and ".json" in disposition
    payload = json.loads(response.data)
    assert payload["template_type"] == "user_menu_visibility"
    assert {"template_version", "template_type", "source_user", "visible_keys", "effective_rule_map", "labels"} <= set(payload)
    assert payload["source_user"]["id"] == target_id


def test_export_visibility_template_missing_user_is_rejected(app, client):
    _create_user(app, sicil_no="sb0501", email="sb0501@ktb.gov.tr", role="admin")
    _login(client, "sb0501")

    response = client.post(
        "/settings",
        data={"form_action": "export_visibility_template"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("warning", "Dışa aktarma için kullanıcı seçiniz.")


def test_import_visibility_template_success_creates_overrides(app, client):
    _create_user(app, sicil_no="sb052", email="sb052@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb053", email="sb053@ktb.gov.tr", role="personel")
    menu_key = _live_menu_key(app)
    _login(client, "sb052")

    response = client.post(
        "/settings",
        data={
            "form_action": "import_visibility_template",
            "user_id": str(target_id),
            "import_template_json": json.dumps({"visible_keys": [menu_key]}),
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    with app.app_context():
        from app.models import UserMenuPermission
        row = UserMenuPermission.query.filter_by(user_id=target_id, menu_key=menu_key).first()
        assert row is not None and row.is_visible is True


def test_import_visibility_template_malformed_payload_is_rejected(app, client):
    _create_user(app, sicil_no="sb054", email="sb054@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb055", email="sb055@ktb.gov.tr", role="personel")
    _login(client, "sb054")

    response = client.post(
        "/settings",
        data={
            "form_action": "import_visibility_template",
            "user_id": str(target_id),
            # Valid JSON, but empty visible_keys AND no effective_rule_map
            # dict -- hits the explicit ValueError guard clause.
            "import_template_json": json.dumps({"visible_keys": []}),
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "danger"
    assert "Yetki şablonu içe aktarılırken hata oluştu" in flashes[-1][1]
    with app.app_context():
        from app.models import UserMenuPermission
        assert UserMenuPermission.query.filter_by(user_id=target_id).count() == 0


# ---------------------------------------------------------------------------
# save_named_archive / delete_named_archive / apply_named_archive
# ---------------------------------------------------------------------------


def test_save_named_archive_persists_system_setting_row(app, client):
    _create_user(app, sicil_no="sb060", email="sb060@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb061", email="sb061@ktb.gov.tr", role="personel")
    menu_key = _live_menu_key(app)
    _login(client, "sb060")

    response = client.post(
        "/settings",
        data={
            "form_action": "save_named_archive",
            "user_id": str(target_id),
            "archive_name": "Behavior Contract Archive",
            "archive_scope": "general",
            f"menu_{menu_key}": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    with app.app_context():
        from app.models import SystemSetting
        row = SystemSetting.query.filter_by(setting_key="settings_archive::general::behavior-contract-archive").first()
        assert row is not None
        payload = json.loads(row.value_text)
        assert menu_key in payload["visible_keys"]


def test_delete_named_archive_removes_system_setting_row(app, client):
    _create_user(app, sicil_no="sb062", email="sb062@ktb.gov.tr", role="admin")
    setting_key = _seed_named_archive(app, archive_name="To Delete Archive", scope="general", visible_keys=[])
    _login(client, "sb062")

    response = client.post(
        "/settings",
        data={"form_action": "delete_named_archive", "archive_key": setting_key},
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    with app.app_context():
        from app.models import SystemSetting
        assert SystemSetting.query.filter_by(setting_key=setting_key).first() is None


def test_apply_named_archive_role_profile_success(app, client):
    _create_user(app, sicil_no="sb070", email="sb070@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb071", email="sb071@ktb.gov.tr", role="personel")
    menu_key = _live_menu_key(app)
    setting_key = _seed_named_archive(app, archive_name="Role Profile Archive", scope="general", visible_keys=[menu_key])
    _login(client, "sb070")

    response = client.post(
        "/settings",
        data={
            "form_action": "apply_named_archive",
            "user_id": str(target_id),
            "archive_key": setting_key,
            "archive_apply_mode": "role_profile",
            "archive_apply_role": "personel",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    assert _role_menu_default(app, role_name="personel", menu_key=menu_key) is True


def test_apply_named_archive_double_flash_when_only_second_commit_fails(app, client, monkeypatch):
    """Reproduces the documented "double flash" quirk in apply_named_archive
    (account_settings_helpers.py lines 488-521): save_role_menu_defaults's
    OWN internal db.session.commit() (menu_profile_access.py
    save_role_menu_defaults_handler) succeeds and durably persists the row
    change; a "success" flash is queued; THEN the route's own second,
    redundant db.session.commit() at line 516 is the one that fails. The
    user sees BOTH a success flash (for a mutation that already landed) and
    a misleading danger flash appended after it.

    The fault must fire on the SECOND commit call specifically -- a
    call-count closure over the real, unpatched db.session.commit lets call
    #1 (the internal one) through unchanged and raises only on call #2 (the
    route's own)."""
    from app.extensions import db

    _create_user(app, sicil_no="sb080", email="sb080@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb081", email="sb081@ktb.gov.tr", role="personel")
    menu_key = _live_menu_key(app)
    setting_key = _seed_named_archive(app, archive_name="Double Flash Archive", scope="general", visible_keys=[menu_key])

    # Log in BEFORE patching db.session.commit: the login view itself commits
    # (e.g. last-login bookkeeping), and patching before login would count
    # that unrelated commit as call #1, shifting the fault onto the wrong
    # call for this request.
    _login(client, "sb080")

    with app.app_context():
        real_commit = db.session.commit
        call_count = {"n": 0}

        def _fault_second_commit():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return real_commit()
            raise RuntimeError("BYS360-TEST-INDUCED-SECOND-COMMIT-FAILURE")

        monkeypatch.setattr(db.session, "commit", _fault_second_commit)

    response = client.post(
        "/settings",
        data={
            "form_action": "apply_named_archive",
            "user_id": str(target_id),
            "archive_key": setting_key,
            "archive_apply_mode": "role_profile",
            "archive_apply_role": "personel",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert call_count["n"] == 2  # proves both commits were actually attempted

    flashes = _flashes(client)
    categories = [category for category, _message in flashes]
    assert categories[-2:] == ["success", "danger"], categories

    # The mutation is already durably committed by call #1 -- the danger
    # flash is misleading, not accurate. A fresh query proves this.
    with app.app_context():
        from app.models import RoleMenuDefault
        row = RoleMenuDefault.query.filter_by(role_name="personel", menu_key=menu_key).first()
        assert row is not None and row.is_visible is True


def test_save_named_archive_commit_failure_rolls_back_and_leaves_no_row(app, client, monkeypatch):
    """save_named_archive's only DB commit is the explicit
    db.session.commit() at account_settings_helpers.py line 478 -- the
    archive helper itself only .flush()es. Faulting that single commit call
    must leave the DB with no persisted archive row, proving the except
    branch's db.session.rollback() actually undoes the flushed INSERT."""
    from app.extensions import db

    _create_user(app, sicil_no="sb090", email="sb090@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb091", email="sb091@ktb.gov.tr", role="personel")
    menu_key = _live_menu_key(app)

    # Log in BEFORE patching db.session.commit: the login view itself commits
    # (e.g. last-login bookkeeping), and an unconditional commit fault applied
    # before login would make the login request itself fail with a 500.
    _login(client, "sb090")

    with app.app_context():
        def _always_fail_commit():
            raise RuntimeError("BYS360-TEST-INDUCED-COMMIT-FAILURE")

        monkeypatch.setattr(db.session, "commit", _always_fail_commit)

    response = client.post(
        "/settings",
        data={
            "form_action": "save_named_archive",
            "user_id": str(target_id),
            "archive_name": "Rollback Contract Archive",
            "archive_scope": "general",
            f"menu_{menu_key}": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "danger"
    assert "Şablon arşivi kaydedilirken hata oluştu" in flashes[-1][1]

    monkeypatch.undo()  # restore the real commit before the verification query
    with app.app_context():
        from app.models import SystemSetting
        row = SystemSetting.query.filter_by(setting_key="settings_archive::general::rollback-contract-archive").first()
        assert row is None


# ---------------------------------------------------------------------------
# save_user_visibility (default / fallback branch)
# ---------------------------------------------------------------------------


def test_save_user_visibility_default_branch_success(app, client):
    _create_user(app, sicil_no="sb100", email="sb100@ktb.gov.tr", role="admin")
    target_id = _create_user(app, sicil_no="sb101", email="sb101@ktb.gov.tr", role="personel")
    menu_key = _live_menu_key(app)
    _login(client, "sb100")

    response = client.post(
        "/settings",
        data={
            # no "form_action" key at all -- exercises the documented
            # default fallback ("save_user_visibility" if absent).
            "user_id": str(target_id),
            f"menu_{menu_key}": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert f"user_id={target_id}" in response.headers.get("Location", "")
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    with app.app_context():
        from app.models import UserMenuPermission
        row = UserMenuPermission.query.filter_by(user_id=target_id, menu_key=menu_key).first()
        assert row is not None and row.is_visible is True


# ---------------------------------------------------------------------------
# save_assistant_role_matrix / reset_assistant_role_matrix / rollback_settings_change_entry
#
# Added ahead of the settings_page() complexity refactor: these three actions
# had zero test coverage anywhere in the repo (route level or service level)
# before this addition, per an explicit forensic sweep of tests/ -- yet each
# is a structurally-unique, materially-unprotected branch about to be
# extracted into its own helper function. These are minimal, semantic
# (DB-state and flash assertions, not source/line-position assertions)
# regression nets for CURRENT, already-shipped behavior -- not new
# behavior, and not a fix for anything.
# ---------------------------------------------------------------------------


def _assistant_module_setting_value(app, *, setting_key):
    with app.app_context():
        from app.models import ModuleSetting
        row = ModuleSetting.query.filter_by(module_key="assistant", setting_key=setting_key).first()
        return None if row is None else row.value_text


def test_save_assistant_role_matrix_success_updates_visible_roles(app, client):
    _create_user(app, sicil_no="sb110", email="sb110@ktb.gov.tr", role="admin")
    _login(client, "sb110")

    response = client.post(
        "/settings",
        data={
            "form_action": "save_assistant_role_matrix",
            "assistant_role_policy__admin__assistant_module": "on",
            "assistant_role_policy__personel__assistant_module": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "section=assistant-role-policy" in response.headers.get("Location", "")
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    assert "Açık rol sayısı: 2" in flashes[-1][1]
    assert _assistant_module_setting_value(app, setting_key="visible_roles") == "admin,personel"
    assert _assistant_module_setting_value(app, setting_key="enabled") == "true"


def test_reset_assistant_role_matrix_restores_default_roles(app, client):
    from app.services.assistant_role_matrix_service import ASSISTANT_DEFAULT_VISIBLE_ROLES

    _create_user(app, sicil_no="sb111", email="sb111@ktb.gov.tr", role="admin")
    _login(client, "sb111")

    # First move it away from the default so the reset is a real assertion,
    # not a no-op.
    client.post(
        "/settings",
        data={
            "form_action": "save_assistant_role_matrix",
            "assistant_role_policy__personel__assistant_module": "on",
        },
        follow_redirects=False,
    )
    assert _assistant_module_setting_value(app, setting_key="visible_roles") == "personel"

    response = client.post(
        "/settings",
        data={"form_action": "reset_assistant_role_matrix"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "section=assistant-role-policy" in response.headers.get("Location", "")
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    assert f"Açık rol sayısı: {len(ASSISTANT_DEFAULT_VISIBLE_ROLES)}" in flashes[-1][1]
    restored = set((_assistant_module_setting_value(app, setting_key="visible_roles") or "").split(","))
    assert restored == ASSISTANT_DEFAULT_VISIBLE_ROLES


def test_rollback_settings_change_entry_restores_previous_system_setting_value(app, client):
    _create_user(app, sicil_no="sb112", email="sb112@ktb.gov.tr", role="admin")
    _login(client, "sb112")

    # Sync first so phase1 seeding has already run and a baseline value exists
    # (K13: the seed runs on the real admin's explicit sync, not on GET).
    client.post("/settings", data={"form_action": "sync_role_defaults"}, follow_redirects=False)
    before_value = _system_setting_value(app, setting_key="general.system_name")

    save_response = client.post(
        "/settings",
        data={
            "form_action": "save_system_foundation",
            "system__general__system_name": "Rollback Contract Value",
        },
        follow_redirects=False,
    )
    assert save_response.status_code == 302
    assert _system_setting_value(app, setting_key="general.system_name") == "Rollback Contract Value"

    with app.app_context():
        from app.models import SettingsChangeLog
        log_row = (
            SettingsChangeLog.query
            .filter_by(change_scope="system_settings", is_rollback=False)
            .order_by(SettingsChangeLog.id.desc())
            .first()
        )
        assert log_row is not None
        log_id = log_row.id

    rollback_response = client.post(
        "/settings",
        data={"form_action": "rollback_settings_change_entry", "change_log_id": str(log_id)},
        follow_redirects=False,
    )

    assert rollback_response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1][0] == "success"
    assert _system_setting_value(app, setting_key="general.system_name") == before_value


def test_rollback_settings_change_entry_missing_log_id_flashes_danger(app, client):
    _create_user(app, sicil_no="sb113", email="sb113@ktb.gov.tr", role="admin")
    _login(client, "sb113")

    response = client.post(
        "/settings",
        data={"form_action": "rollback_settings_change_entry"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    flashes = _flashes(client)
    assert flashes and flashes[-1] == ("danger", "Geri alınacak ayar değişikliği kaydı belirtilmedi.")
