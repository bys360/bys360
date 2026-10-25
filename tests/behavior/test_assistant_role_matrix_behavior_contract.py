"""Canonical behavior contract for TD-CAND-002 (assistant role-matrix
consolidation): app/services/assistant_role_matrix_service.py.

This module used to be the pre-consolidation behavior-lock net for two
independently-drifting duplicate implementations (account_settings_helpers.py's
V12 block and account_communication_helpers.py's V11 block). Both have now
been deleted; this file asserts the single canonical implementation's
resolved contract, including the two explicit product decisions made during
consolidation:

  DIV-1 (missing configuration): resolved to "fall back to the 7
  recommended default roles" -- matching the confirmed-live settings-side
  behavior (see module docstring in assistant_role_matrix_service.py).
  An explicit "__none__" sentinel remains distinct and always resolves to
  an empty role set.

  PR #70 R05d: an explicitly empty configuration grants nothing, matching the live
  consumer and the authority guard. Never-configured installs retain their defaults.

  DIV-2 (error-boundary behavior): a recoverable settings-row *lookup*
  failure degrades safely (falls through to "create a new row"); a real
  persistence (commit) failure is never swallowed and always propagates.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "role_matrix_behavior_tmp" / "test_dbs"


def _make_app(monkeypatch, **env_overrides):
    """Per-test, file-backed SQLite app -- same proven isolation pattern already used by
    tests/behavior/test_settings_page_behavior_contract.py and ~24 other test files in this
    suite (see each file's own _make_app), deliberately not the shared session-scoped
    app/client fixtures in tests/conftest.py: these tests need to control the exact set of
    ModuleSetting rows present (including "zero rows at all"), which a DB shared with other
    tests running in the same session cannot guarantee."""
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-role-matrix-behavior-contract")
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
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def _module_setting_value(*, setting_key):
    from app.models import ModuleSetting
    row = ModuleSetting.query.filter_by(module_key="assistant", setting_key=setting_key).first()
    return None if row is None else row.value_text


def _mock_get_assistant_settings(monkeypatch, payload):
    """assistant_role_matrix_service does `from app.services.assistant_settings_service
    import get_assistant_settings` INSIDE its own function body (not at module level),
    so patching the attribute on the source module affects the next invocation -- there
    is no per-module-cached binding to route around."""
    monkeypatch.setattr(
        "app.services.assistant_settings_service.get_assistant_settings",
        lambda: payload,
    )


def _raise_get_assistant_settings(monkeypatch):
    def _raise():
        raise RuntimeError("simulated get_assistant_settings failure")
    monkeypatch.setattr("app.services.assistant_settings_service.get_assistant_settings", _raise)


# ---------------------------------------------------------------------------
# A. Full-stack, real (unmocked) get_assistant_settings() against a genuinely
# empty DB -- what a never-configured install actually shows today.
# ---------------------------------------------------------------------------


def test_visible_roles_on_fresh_unconfigured_db_returns_default_seven(app):
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            ASSISTANT_DEFAULT_VISIBLE_ROLES,
            _assistant_visible_roles_from_settings,
        )
        assert _assistant_visible_roles_from_settings() == ASSISTANT_DEFAULT_VISIBLE_ROLES


# ---------------------------------------------------------------------------
# B. DIV-1: canonical contract for missing/empty/exception/explicit-none.
# ---------------------------------------------------------------------------


def test_div1_missing_configuration_falls_back_to_recommended_defaults(app, monkeypatch):
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            ASSISTANT_DEFAULT_VISIBLE_ROLES,
            _assistant_visible_roles_from_settings,
        )
        _mock_get_assistant_settings(monkeypatch, {})  # no "visible_roles" key at all
        assert _assistant_visible_roles_from_settings() == ASSISTANT_DEFAULT_VISIBLE_ROLES


def test_div1_explicit_empty_configuration_grants_no_roles(app, monkeypatch):
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            _assistant_visible_roles_from_settings,
        )
        _mock_get_assistant_settings(monkeypatch, {"visible_roles": ""})
        assert _assistant_visible_roles_from_settings() == set()


def test_div1_settings_fetch_exception_falls_back_to_recommended_defaults(app, monkeypatch):
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            ASSISTANT_DEFAULT_VISIBLE_ROLES,
            _assistant_visible_roles_from_settings,
        )
        _raise_get_assistant_settings(monkeypatch)
        assert _assistant_visible_roles_from_settings() == ASSISTANT_DEFAULT_VISIBLE_ROLES


def test_div1_explicit_none_sentinel_resolves_to_empty_set_not_defaults(app, monkeypatch):
    """The mandatory distinction: "__none__" (explicitly saved as zero roles)
    must NOT be treated the same as "never configured"."""
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            _assistant_visible_roles_from_settings,
        )
        _mock_get_assistant_settings(monkeypatch, {"visible_roles": "__none__"})
        assert _assistant_visible_roles_from_settings() == set()


def test_div1_populated_roles_returns_exactly_configured_roles(app, monkeypatch):
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            _assistant_visible_roles_from_settings,
        )
        _mock_get_assistant_settings(monkeypatch, {"visible_roles": "admin,personel"})
        assert _assistant_visible_roles_from_settings() == {"admin", "personel"}


def test_visible_roles_normalization(app, monkeypatch):
    """Whitespace-trimmed, lower-cased, dash-to-underscore, comma/semicolon/
    newline-separated, blank tokens dropped."""
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            _assistant_visible_roles_from_settings,
        )
        _mock_get_assistant_settings(monkeypatch, {"visible_roles": " ADMIN , Baskan-Yardimcisi ,,"})
        assert _assistant_visible_roles_from_settings() == {"admin", "baskan_yardimcisi"}


# ---------------------------------------------------------------------------
# C. build_assistant_role_matrix() output shape and ordering.
# ---------------------------------------------------------------------------


def test_build_role_matrix_output_shape_and_ordering(app, monkeypatch):
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            ASSISTANT_POLICY_ROLE_OPTIONS,
            build_assistant_role_matrix,
        )
        _mock_get_assistant_settings(monkeypatch, {"visible_roles": "admin,personel"})

        result = build_assistant_role_matrix()

        assert set(result.keys()) == {"roles", "rows", "items", "item_count", "visible_roles"}
        assert result["visible_roles"] == sorted({"admin", "personel"})
        assert result["rows"] is result["items"]
        assert result["item_count"] == len(result["items"]) == 1

        # role_rows order is deterministic: it follows ASSISTANT_POLICY_ROLE_OPTIONS'
        # fixed declaration order, not sorted() and not visible-first.
        expected_role_key_order = [role_key for role_key, _label in ASSISTANT_POLICY_ROLE_OPTIONS]
        assert [row["role_key"] for row in result["roles"]] == expected_role_key_order

        admin_row = next(row for row in result["roles"] if row["role_key"] == "admin")
        personel_row = next(row for row in result["roles"] if row["role_key"] == "personel")
        baskan_row = next(row for row in result["roles"] if row["role_key"] == "baskan")
        assert admin_row["visible_count"] == 1
        assert personel_row["visible_count"] == 1
        assert baskan_row["visible_count"] == 0
        assert admin_row["recommended_count"] == 1  # admin is in ASSISTANT_DEFAULT_VISIBLE_ROLES
        assert personel_row["recommended_count"] == 0  # personel is not

        item = result["items"][0]
        assert item["key"] == "assistant_module"
        assert item["visible_count"] == 2  # admin + personel
        assert [state["role_key"] for state in item["states"]] == expected_role_key_order
        assert item["recommended_roles"]  # non-empty: recommended labels present


# ---------------------------------------------------------------------------
# D. save_assistant_role_matrix_from_form() -- direct call, real DB, single
# commit. NOT read-only: two upserts, then one db.session.commit().
# ---------------------------------------------------------------------------


def test_save_role_matrix_persists_selected_roles_and_returns_count(app):
    with app.app_context():
        from app.services.assistant_role_matrix_service import save_assistant_role_matrix_from_form

        form = {
            "assistant_role_policy__admin__assistant_module": "on",
            "assistant_role_policy__personel__assistant_module": "on",
        }
        selected_count = save_assistant_role_matrix_from_form(form, updated_by_user_id=None)

        assert selected_count == 2
        assert _module_setting_value(setting_key="visible_roles") == "admin,personel"
        assert _module_setting_value(setting_key="enabled") == "true"


def test_save_role_matrix_with_no_roles_selected_persists_none_sentinel(app):
    with app.app_context():
        from app.services.assistant_role_matrix_service import save_assistant_role_matrix_from_form

        selected_count = save_assistant_role_matrix_from_form({}, updated_by_user_id=None)

        assert selected_count == 0
        assert _module_setting_value(setting_key="visible_roles") == "__none__"


# ---------------------------------------------------------------------------
# E. reset_assistant_role_matrix_defaults() -- direct call, real DB.
# ---------------------------------------------------------------------------


def test_reset_role_matrix_persists_and_returns_default_roles(app):
    with app.app_context():
        from app.services.assistant_role_matrix_service import (
            ASSISTANT_DEFAULT_VISIBLE_ROLES,
            reset_assistant_role_matrix_defaults,
            save_assistant_role_matrix_from_form,
        )

        # Move it away from the default first so the reset is a real assertion.
        save_assistant_role_matrix_from_form(
            {"assistant_role_policy__personel__assistant_module": "on"}, updated_by_user_id=None,
        )
        assert _module_setting_value(setting_key="visible_roles") == "personel"

        returned_count = reset_assistant_role_matrix_defaults(updated_by_user_id=None)

        assert returned_count == len(ASSISTANT_DEFAULT_VISIBLE_ROLES) == 7
        restored = set((_module_setting_value(setting_key="visible_roles") or "").split(","))
        assert restored == ASSISTANT_DEFAULT_VISIBLE_ROLES
        assert _module_setting_value(setting_key="enabled") == "true"


# ---------------------------------------------------------------------------
# F. DIV-2: error-boundary behavior. A recoverable *lookup* failure degrades
# safely; a real *persistence* (commit) failure is never swallowed.
# ---------------------------------------------------------------------------


def test_div2_recoverable_lookup_failure_falls_back_to_safe_create_no_exception(app, monkeypatch):
    """If the existing-row lookup query itself raises (e.g. a transient
    connection hiccup), the upsert must not blow up the caller -- it treats
    the row as not-found and creates a fresh one, and the save still
    succeeds end to end."""
    with app.app_context():
        from app.models import ModuleSetting
        from app.services.assistant_role_matrix_service import save_assistant_role_matrix_from_form

        original_filter_by = ModuleSetting.query.__class__.filter_by
        call_count = {"n": 0}

        def _flaky_filter_by(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated transient lookup failure")
            return original_filter_by(self, *args, **kwargs)

        monkeypatch.setattr(ModuleSetting.query.__class__, "filter_by", _flaky_filter_by)

        selected_count = save_assistant_role_matrix_from_form(
            {"assistant_role_policy__admin__assistant_module": "on"}, updated_by_user_id=None,
        )

        assert selected_count == 1
        assert _module_setting_value(setting_key="visible_roles") == "admin"


def test_div2_real_persistence_failure_is_not_swallowed(app, monkeypatch):
    """A genuine commit failure (real persistence failure) must propagate --
    it must never be silently treated as a successful save."""
    with app.app_context():
        from app.extensions import db
        from app.services.assistant_role_matrix_service import save_assistant_role_matrix_from_form

        def _raise_on_commit():
            raise RuntimeError("simulated persistence failure")

        monkeypatch.setattr(db.session, "commit", _raise_on_commit)

        with pytest.raises(RuntimeError, match="simulated persistence failure"):
            save_assistant_role_matrix_from_form(
                {"assistant_role_policy__admin__assistant_module": "on"}, updated_by_user_id=None,
            )
