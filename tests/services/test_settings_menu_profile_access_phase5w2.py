"""BYS360 Phase 5 coverage wave 2 -- role/unit/user menu authorization layer.

Behavioral tests for ``app/services/settings/menu_profile_access.py``, the
dependency-injected access layer that ``app/services/settings_service.py``
wires up with the real ``RoleMenuDefault`` / ``UnitMenuProfile`` /
``UserMenuPermission`` models, ``db.session``, and the helper callables from
``app/services/settings/menu_permissions.py``. These handlers back the live
admin "Ayarlar" (settings) menu-visibility screens, so the write paths
(``save_role_menu_defaults_handler``, ``save_unit_menu_profile_handler``,
``clear_user_menu_overrides_handler``, ``save_user_menu_overrides_handler``)
perform real authorization-state mutations with an audit trail
(``SettingsChangeLog``) and had zero tests before this file.

Each test builds a real, isolated in-memory SQLite Flask app (the same
``_make_app(monkeypatch)`` pattern as
``tests/integration/test_survey_response_transactions.py``) so DB writes,
deletes, and rollbacks are genuine -- not mocked. Only the pure DI callables
that are cheap/deterministic by construction (``flatten_menu_definitions_func``,
``static_role_default_menu_keys_func``, audit-log/rollback spies, and the
"query raises" stand-in models used to exercise the ``except Exception``
guards) are hand-written stand-ins, matching this file's own
dependency-injection design (see its module docstring: DB/commit/rollback/
change-log wiring is intentionally supplied by the caller).
"""
from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, text

from app.services.settings.menu_permissions import (
    build_complete_visibility_map,
    filter_live_menu_keys,
    filter_live_menu_rows,
    snapshot_role_menu_state,
    snapshot_unit_menu_state,
    snapshot_user_override_state,
)
from app.services.settings.menu_profile_access import (
    build_base_rule_map_for_user_handler,
    build_effective_user_menu_context_handler,
    build_role_default_rule_map_handler,
    build_role_default_snapshot_handler,
    build_settings_profile_context_handler,
    build_unit_profile_snapshot_handler,
    clear_user_menu_overrides_handler,
    get_role_default_menu_keys_handler,
    get_unit_profile_menu_keys_handler,
    save_role_menu_defaults_handler,
    save_unit_menu_profile_handler,
    save_user_menu_overrides_handler,
)


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-menu-profile-access-phase5w2")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    # Config froze its values when config.py was first imported, possibly by
    # another test pointing at its own SQLite file; pin them so every app here
    # gets its own empty in-memory database.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with flask_app.app_context():
        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    flask_app = _make_app(monkeypatch)
    yield flask_app
    from app.extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _items(*keys: str) -> list[dict[str, Any]]:
    return [{"key": key} for key in keys]


def _make_user(*, role: str = "personel", birim: str | None = None, ad: str = "Wave2", soyad: str = "Test"):
    from app.extensions import db
    from app.models import User

    suffix = _uid()
    user = User(
        sicil_no=f"w2-{suffix}",
        email=f"w2-{suffix}@example.test",
        ad=ad,
        soyad=soyad,
        role=role,
        birim=birim,
        is_active=True,
        must_change_password=False,
        must_set_security_question=False,
    )
    user.set_password("Phase5Wave2Pw!")
    db.session.add(user)
    db.session.commit()
    return user


class ChangeLogSpy:
    """Stand-in for ``create_settings_change_log_func`` that records every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class RollbackSpy:
    """Stand-in for ``safe_rollback_func`` that also performs a real rollback."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self.call_count = 0

    def __call__(self) -> None:
        self.call_count += 1
        self._session.rollback()


class _BoomAttr:
    """Any attribute access/call on this object raises -- simulates a query blow-up."""

    def __getattr__(self, name: str) -> Any:
        def _raise(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(f"BYS360 phase5w2 simulated query failure on '{name}'")
        return _raise


class BoomModel:
    """Stand-in DB model whose ``.query`` (and any class attribute) always raises.

    Used to exercise the ``except Exception: ... safe_rollback_func()`` guards
    without needing to break a real table -- the handlers under test are
    dependency-injected, so a raising stand-in is a faithful way to simulate
    "the query itself raises".
    """

    query = _BoomAttr()


# ---------------------------------------------------------------------------
# get_role_default_menu_keys_handler
# ---------------------------------------------------------------------------


def test_get_role_default_menu_keys_returns_db_visible_rows_when_present(app, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        db.session.add_all([
            RoleMenuDefault(role_name=role, menu_key="wave_alpha", is_visible=True, source_type="manual"),
            RoleMenuDefault(role_name=role, menu_key="wave_beta", is_visible=True, source_type="manual"),
            RoleMenuDefault(role_name=role, menu_key="wave_gamma", is_visible=False, source_type="manual"),
        ])
        db.session.commit()

        rollback_spy = RollbackSpy(db.session)
        result = get_role_default_menu_keys_handler(
            role_name=role,
            prefer_database=True,
            role_menu_default_model=RoleMenuDefault,
            static_role_default_menu_keys_func=lambda _role: {"static_fallback_should_not_be_used"},
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            safe_rollback_func=rollback_spy,
        )

        assert result == {"wave_alpha", "wave_beta"}
        assert rollback_spy.call_count == 0

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


def test_get_role_default_menu_keys_returns_empty_set_when_rows_exist_but_none_visible(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        db.session.add(RoleMenuDefault(role_name=role, menu_key="wave_alpha", is_visible=False, source_type="manual"))
        db.session.commit()

        result = get_role_default_menu_keys_handler(
            role_name=role,
            prefer_database=True,
            role_menu_default_model=RoleMenuDefault,
            static_role_default_menu_keys_func=lambda _role: {"static_fallback_should_not_be_used"},
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            safe_rollback_func=RollbackSpy(db.session),
        )

        # Rows exist for this role (all hidden) -> real "configured but all hidden",
        # must NOT fall back to the static default set.
        assert result == set()

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


def test_get_role_default_menu_keys_falls_back_to_static_when_no_rows_in_db(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        result = get_role_default_menu_keys_handler(
            role_name=role,
            prefer_database=True,
            role_menu_default_model=RoleMenuDefault,
            static_role_default_menu_keys_func=lambda _role: ["wave_static_one", "wave_static_two", ""],
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            safe_rollback_func=RollbackSpy(db.session),
        )

        assert result == {"wave_static_one", "wave_static_two"}


def test_get_role_default_menu_keys_prefer_database_false_skips_db_and_uses_static(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        # A visible DB row exists, but prefer_database=False must skip the DB
        # branch entirely and go straight to the static fallback.
        db.session.add(RoleMenuDefault(role_name=role, menu_key="wave_db_only", is_visible=True, source_type="manual"))
        db.session.commit()

        result = get_role_default_menu_keys_handler(
            role_name=role,
            prefer_database=False,
            role_menu_default_model=RoleMenuDefault,
            static_role_default_menu_keys_func=lambda _role: {"wave_static_only"},
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            safe_rollback_func=RollbackSpy(db.session),
        )

        assert result == {"wave_static_only"}

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


def test_get_role_default_menu_keys_exception_path_falls_back_to_static_and_rolls_back(app) -> None:
    from app.extensions import db

    with app.app_context():
        rollback_spy = RollbackSpy(db.session)
        result = get_role_default_menu_keys_handler(
            role_name="phase5w2_boom_role",
            prefer_database=True,
            role_menu_default_model=BoomModel,
            static_role_default_menu_keys_func=lambda _role: {"wave_static_fallback"},
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            safe_rollback_func=rollback_spy,
        )

        assert result == {"wave_static_fallback"}
        assert rollback_spy.call_count == 1


# ---------------------------------------------------------------------------
# build_role_default_snapshot_handler
# ---------------------------------------------------------------------------


def test_build_role_default_snapshot_computes_coverage_ratio_per_role(app) -> None:
    with app.app_context():
        role_defaults_map: dict[str, Any] = {"roleA": set(), "roleB": set()}
        visible_by_role = {"roleA": {"k1", "k2"}, "roleB": {"k1"}}

        rows = build_role_default_snapshot_handler(
            role_menu_defaults=role_defaults_map,
            flatten_menu_definitions_func=lambda: _items("k1", "k2", "k3", "k4"),
            get_role_default_menu_keys_func=lambda role_name: visible_by_role[role_name],
        )

        assert rows == [
            {"role_name": "roleA", "visible_count": 2, "total_count": 4, "coverage_ratio": 50.0},
            {"role_name": "roleB", "visible_count": 1, "total_count": 4, "coverage_ratio": 25.0},
        ]


# ---------------------------------------------------------------------------
# build_unit_profile_snapshot_handler
# ---------------------------------------------------------------------------


def test_build_unit_profile_snapshot_groups_rows_by_unit_and_computes_visible_counts(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit_a = f"phase5w2_unit_a_{_uid()}"
    unit_b = f"phase5w2_unit_b_{_uid()}"
    with app.app_context():
        db.session.add_all([
            UnitMenuProfile(unit_name=unit_a, menu_key="wave_alpha", is_visible=True, source_type="manual"),
            UnitMenuProfile(unit_name=unit_a, menu_key="wave_beta", is_visible=False, source_type="manual"),
            UnitMenuProfile(unit_name=unit_b, menu_key="wave_alpha", is_visible=True, source_type="manual"),
        ])
        db.session.commit()

        rollback_spy = RollbackSpy(db.session)
        rows = build_unit_profile_snapshot_handler(
            unit_menu_profile_model=UnitMenuProfile,
            flatten_menu_definitions_func=lambda: _items("wave_alpha", "wave_beta", "wave_gamma", "wave_delta"),
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=rollback_spy,
        )
        by_unit = {row["unit_name"]: row for row in rows if row["unit_name"] in (unit_a, unit_b)}

        assert by_unit[unit_a] == {
            "unit_name": unit_a, "configured_count": 2, "visible_count": 1, "coverage_ratio": 25.0,
        }
        assert by_unit[unit_b] == {
            "unit_name": unit_b, "configured_count": 1, "visible_count": 1, "coverage_ratio": 25.0,
        }
        assert rollback_spy.call_count == 0

        UnitMenuProfile.query.filter(UnitMenuProfile.unit_name.in_([unit_a, unit_b])).delete(
            synchronize_session=False
        )
        db.session.commit()


def test_build_unit_profile_snapshot_exception_path_returns_empty_list_and_rolls_back(app) -> None:
    from app.extensions import db

    with app.app_context():
        rollback_spy = RollbackSpy(db.session)
        rows = build_unit_profile_snapshot_handler(
            unit_menu_profile_model=BoomModel,
            flatten_menu_definitions_func=lambda: _items("k1"),
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=rollback_spy,
        )

        assert rows == []
        assert rollback_spy.call_count == 1


# ---------------------------------------------------------------------------
# get_unit_profile_menu_keys_handler
# ---------------------------------------------------------------------------


def test_get_unit_profile_menu_keys_returns_visible_keys_for_unit(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        db.session.add_all([
            UnitMenuProfile(unit_name=unit, menu_key="wave_alpha", is_visible=True, source_type="manual"),
            UnitMenuProfile(unit_name=unit, menu_key="wave_beta", is_visible=False, source_type="manual"),
        ])
        db.session.commit()

        result = get_unit_profile_menu_keys_handler(
            unit_name=unit,
            unit_menu_profile_model=UnitMenuProfile,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=RollbackSpy(db.session),
        )

        assert result == {"wave_alpha"}

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        db.session.commit()


def test_get_unit_profile_menu_keys_blank_unit_name_short_circuits_without_querying(app) -> None:
    with app.app_context():
        # BoomModel raises on any attribute/query access -- if the blank-unit-name
        # guard didn't short-circuit, this would raise instead of returning set().
        result = get_unit_profile_menu_keys_handler(
            unit_name="   ",
            unit_menu_profile_model=BoomModel,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=RollbackSpy(object()),
        )

        assert result == set()


def test_get_unit_profile_menu_keys_exception_path_returns_empty_set_and_rolls_back(app) -> None:
    from app.extensions import db

    with app.app_context():
        rollback_spy = RollbackSpy(db.session)
        result = get_unit_profile_menu_keys_handler(
            unit_name="phase5w2_boom_unit",
            unit_menu_profile_model=BoomModel,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=rollback_spy,
        )

        assert result == set()
        assert rollback_spy.call_count == 1


# ---------------------------------------------------------------------------
# build_role_default_rule_map_handler
# ---------------------------------------------------------------------------


def test_build_role_default_rule_map_maps_items_to_visibility_booleans(app) -> None:
    with app.app_context():
        rule_map = build_role_default_rule_map_handler(
            role_name="phase5w2_role",
            flat_menu_items=_items("k1", "k2", "k3"),
            flatten_menu_definitions_func=lambda: _items("should_not_be_used"),
            get_role_default_menu_keys_func=lambda _role: {"k1", "k3"},
        )

        assert rule_map == {"k1": True, "k2": False, "k3": True}


# ---------------------------------------------------------------------------
# build_base_rule_map_for_user_handler
# ---------------------------------------------------------------------------


def test_build_base_rule_map_for_user_applies_unit_override_over_role_defaults(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        db.session.add_all([
            UnitMenuProfile(unit_name=unit, menu_key="k2", is_visible=False, source_type="manual"),
            UnitMenuProfile(unit_name=unit, menu_key="k3", is_visible=True, source_type="manual"),
        ])
        db.session.commit()

        user = _make_user(role="phase5w2_role", birim=unit)

        rollback_spy = RollbackSpy(db.session)
        context = build_base_rule_map_for_user_handler(
            user=user,
            flat_menu_items=_items("k1", "k2", "k3", "k4"),
            flatten_menu_definitions_func=lambda: _items("should_not_be_used"),
            build_role_default_rule_map_func=lambda _role, _items_: {
                "k1": True, "k2": True, "k3": False, "k4": False,
            },
            unit_menu_profile_model=UnitMenuProfile,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=rollback_spy,
        )

        assert context["role_rule_map"] == {"k1": True, "k2": True, "k3": False, "k4": False}
        assert context["base_rule_map"] == {"k1": True, "k2": False, "k3": True, "k4": False}
        assert {row.menu_key for row in context["unit_rows"]} == {"k2", "k3"}
        assert context["unit_name"] == unit
        assert rollback_spy.call_count == 0

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        db.session.commit()


def test_build_base_rule_map_for_user_no_unit_name_skips_unit_query_entirely(app) -> None:
    with app.app_context():
        user = _make_user(role="phase5w2_role", birim=None)

        # BoomModel would raise if the handler attempted to query it; since the
        # user has no birim, the unit lookup must be skipped entirely.
        context = build_base_rule_map_for_user_handler(
            user=user,
            flat_menu_items=_items("k1", "k2"),
            flatten_menu_definitions_func=lambda: _items("should_not_be_used"),
            build_role_default_rule_map_func=lambda _role, _items_: {"k1": True, "k2": False},
            unit_menu_profile_model=BoomModel,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=RollbackSpy(object()),
        )

        assert context["base_rule_map"] == {"k1": True, "k2": False}
        assert context["unit_rows"] == []
        assert context["unit_name"] == ""


def test_build_base_rule_map_for_user_exception_path_falls_back_to_role_map_only(app) -> None:
    from app.extensions import db

    with app.app_context():
        user = _make_user(role="phase5w2_role", birim="phase5w2_boom_unit")

        rollback_spy = RollbackSpy(db.session)
        context = build_base_rule_map_for_user_handler(
            user=user,
            flat_menu_items=_items("k1", "k2"),
            flatten_menu_definitions_func=lambda: _items("should_not_be_used"),
            build_role_default_rule_map_func=lambda _role, _items_: {"k1": True, "k2": False},
            unit_menu_profile_model=BoomModel,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=rollback_spy,
        )

        assert context["base_rule_map"] == {"k1": True, "k2": False}
        assert context["unit_rows"] == []
        assert rollback_spy.call_count == 1


# ---------------------------------------------------------------------------
# build_effective_user_menu_context_handler
# ---------------------------------------------------------------------------


def test_build_effective_user_menu_context_layers_role_unit_user_and_attributes_sources(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile, UserMenuPermission

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        user = _make_user(role="phase5w2_role", birim=unit)

        db.session.add_all([
            UnitMenuProfile(unit_name=unit, menu_key="k2", is_visible=False, source_type="manual"),
            UnitMenuProfile(unit_name=unit, menu_key="k3", is_visible=True, source_type="manual"),
            UserMenuPermission(user_id=user.id, menu_key="k1", is_visible=False, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="k4", is_visible=True, source_type="user_override"),
        ])
        db.session.commit()

        def _role_map_func(_role_name: str, _items_: list[dict[str, Any]]) -> dict[str, bool]:
            return {"k1": True, "k2": True, "k3": False, "k4": False, "k5": True}

        def _base_rule_map_func(user_obj: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
            return build_base_rule_map_for_user_handler(
                user=user_obj,
                flat_menu_items=items,
                flatten_menu_definitions_func=lambda: items,
                build_role_default_rule_map_func=_role_map_func,
                unit_menu_profile_model=UnitMenuProfile,
                filter_live_menu_rows_func=filter_live_menu_rows,
                safe_rollback_func=RollbackSpy(db.session),
            )

        flat_items = _items("k1", "k2", "k3", "k4", "k5")
        rollback_spy = RollbackSpy(db.session)
        context = build_effective_user_menu_context_handler(
            user=user,
            flat_menu_items=flat_items,
            flatten_menu_definitions_func=lambda: flat_items,
            build_base_rule_map_for_user_func=_base_rule_map_func,
            user_menu_permission_model=UserMenuPermission,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=rollback_spy,
        )

        assert context["effective_rule_map"] == {
            "k1": False, "k2": False, "k3": True, "k4": True, "k5": True,
        }
        assert context["source_map"] == {
            "k1": "user_override", "k2": "unit_profile", "k3": "unit_profile",
            "k4": "user_override", "k5": "role_default",
        }
        assert context["visible_source_counts"] == {
            "role_default": 1, "unit_profile": 1, "user_override": 1,
        }
        assert context["hidden_source_counts"] == {
            "role_default": 0, "unit_profile": 1, "user_override": 1,
        }
        assert context["role_default_keys"] == {"k1", "k2", "k5"}
        assert context["unit_profile_keys"] == {"k3"}
        assert context["base_visible_total"] == 3
        assert rollback_spy.call_count == 0

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        UserMenuPermission.query.filter_by(user_id=user.id).delete()
        db.session.commit()


def test_build_effective_user_menu_context_exception_path_falls_back_to_base_map(app) -> None:
    from app.extensions import db

    with app.app_context():
        user = _make_user(role="phase5w2_role", birim=None)

        rollback_spy = RollbackSpy(db.session)
        context = build_effective_user_menu_context_handler(
            user=user,
            flat_menu_items=_items("k1", "k2"),
            flatten_menu_definitions_func=lambda: _items("should_not_be_used"),
            build_base_rule_map_for_user_func=lambda _user, _items_: {
                "base_rule_map": {"k1": True, "k2": False},
                "role_rule_map": {"k1": True, "k2": False},
                "unit_rows": [],
                "unit_name": "",
            },
            user_menu_permission_model=BoomModel,
            filter_live_menu_rows_func=filter_live_menu_rows,
            safe_rollback_func=rollback_spy,
        )

        assert context["override_rows"] == []
        assert context["effective_rule_map"] == {"k1": True, "k2": False}
        assert rollback_spy.call_count == 1


# ---------------------------------------------------------------------------
# save_role_menu_defaults_handler
# ---------------------------------------------------------------------------


def test_save_role_menu_defaults_blank_role_raises_value_error(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    with app.app_context(), pytest.raises(ValueError):
        save_role_menu_defaults_handler(
            role_name="   ",
            all_menu_keys=["k1"],
            visible_keys={"k1"},
            updated_by_user_id=1,
            role_menu_default_model=RoleMenuDefault,
            db_session=db.session,
            filter_live_menu_keys_func=filter_live_menu_keys,
            filter_live_menu_rows_func=filter_live_menu_rows,
            snapshot_role_menu_state_func=snapshot_role_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=ChangeLogSpy(),
        )


def test_save_role_menu_defaults_persists_new_rows_with_correct_fields_and_audits(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        spy = ChangeLogSpy()
        changed = save_role_menu_defaults_handler(
            role_name=role,
            all_menu_keys=["wave_alpha", "wave_beta", "wave_gamma"],
            visible_keys={"wave_alpha", "wave_gamma"},
            updated_by_user_id=42,
            role_menu_default_model=RoleMenuDefault,
            db_session=db.session,
            filter_live_menu_keys_func=filter_live_menu_keys,
            filter_live_menu_rows_func=filter_live_menu_rows,
            snapshot_role_menu_state_func=snapshot_role_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=spy,
        )

        assert changed == 3
        rows = {row.menu_key: row for row in RoleMenuDefault.query.filter_by(role_name=role).all()}
        assert rows["wave_alpha"].is_visible is True
        assert rows["wave_beta"].is_visible is False
        assert rows["wave_gamma"].is_visible is True
        for row in rows.values():
            assert row.source_type == "manual"
            assert row.updated_by_user_id == 42

        assert len(spy.calls) == 1
        call = spy.calls[0]
        assert call["change_scope"] == "role_menu_defaults"
        assert call["action_type"] == "save"
        assert call["target_role_name"] == role
        assert call["actor_user_id"] == 42
        assert call["previous_state"] == {"wave_alpha": False, "wave_beta": False, "wave_gamma": False}
        assert call["new_state"] == {"wave_alpha": True, "wave_beta": False, "wave_gamma": True}

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


def test_save_role_menu_defaults_idempotent_second_call_reports_zero_changed(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        def _save(spy: ChangeLogSpy) -> int:
            return save_role_menu_defaults_handler(
                role_name=role,
                all_menu_keys=["wave_alpha", "wave_beta"],
                visible_keys={"wave_alpha"},
                updated_by_user_id=7,
                role_menu_default_model=RoleMenuDefault,
                db_session=db.session,
                filter_live_menu_keys_func=filter_live_menu_keys,
                filter_live_menu_rows_func=filter_live_menu_rows,
                snapshot_role_menu_state_func=snapshot_role_menu_state,
                build_complete_visibility_map_func=build_complete_visibility_map,
                create_settings_change_log_func=spy,
            )

        first = _save(ChangeLogSpy())
        second = _save(ChangeLogSpy())

        assert first == 2
        assert second == 0

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


def test_save_role_menu_defaults_updates_existing_row_when_visibility_changes(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        db.session.add(RoleMenuDefault(role_name=role, menu_key="wave_alpha", is_visible=False, source_type="seed"))
        db.session.commit()

        changed = save_role_menu_defaults_handler(
            role_name=role,
            all_menu_keys=["wave_alpha"],
            visible_keys={"wave_alpha"},
            updated_by_user_id=9,
            role_menu_default_model=RoleMenuDefault,
            db_session=db.session,
            filter_live_menu_keys_func=filter_live_menu_keys,
            filter_live_menu_rows_func=filter_live_menu_rows,
            snapshot_role_menu_state_func=snapshot_role_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert changed == 1
        row = RoleMenuDefault.query.filter_by(role_name=role, menu_key="wave_alpha").one()
        assert row.is_visible is True
        assert row.source_type == "manual"
        assert row.updated_by_user_id == 9

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


def test_save_role_menu_defaults_prunes_rows_for_menu_keys_no_longer_present(app) -> None:
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        save_role_menu_defaults_handler(
            role_name=role,
            all_menu_keys=["wave_alpha", "wave_beta", "wave_gamma"],
            visible_keys={"wave_alpha", "wave_beta", "wave_gamma"},
            updated_by_user_id=1,
            role_menu_default_model=RoleMenuDefault,
            db_session=db.session,
            filter_live_menu_keys_func=filter_live_menu_keys,
            filter_live_menu_rows_func=filter_live_menu_rows,
            snapshot_role_menu_state_func=snapshot_role_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        changed = save_role_menu_defaults_handler(
            role_name=role,
            all_menu_keys=["wave_alpha", "wave_beta"],
            visible_keys={"wave_alpha", "wave_beta"},
            updated_by_user_id=1,
            role_menu_default_model=RoleMenuDefault,
            db_session=db.session,
            filter_live_menu_keys_func=filter_live_menu_keys,
            filter_live_menu_rows_func=filter_live_menu_rows,
            snapshot_role_menu_state_func=snapshot_role_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert changed == 1
        remaining = {row.menu_key for row in RoleMenuDefault.query.filter_by(role_name=role).all()}
        assert remaining == {"wave_alpha", "wave_beta"}

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


def test_save_role_menu_defaults_preserves_removed_scope_row_untouched_by_form(app) -> None:
    """Regression for the mirror-image bug of clear_user_menu_overrides_handler
    (fixed in eac6d03): a routine "save role profile" call must not silently
    delete a RoleMenuDefault row for a permanently-removed menu scope (e.g.
    "repository", governed by app.config.is_removed_menu_key) just because
    the live settings form -- which never renders removed-scope keys at all
    -- doesn't include it in all_menu_keys. Before the fix, `existing` was
    queried without a live-row filter, so the removed-scope row was visible
    to the prune loop and got deleted even though the admin never saw or
    touched it. Mirrors save_unit_menu_profile_handler's existing (correct)
    preserve behavior.
    """
    from app.extensions import db
    from app.models import RoleMenuDefault

    role = f"phase5w2_role_{_uid()}"
    with app.app_context():
        db.session.add_all([
            RoleMenuDefault(role_name=role, menu_key="dashboard", is_visible=True, source_type="manual"),
            RoleMenuDefault(role_name=role, menu_key="repository", is_visible=True, source_type="manual"),
        ])
        db.session.commit()

        before = {row.menu_key: row.is_visible for row in RoleMenuDefault.query.filter_by(role_name=role).all()}
        assert before == {"dashboard": True, "repository": True}

        spy = ChangeLogSpy()
        changed = save_role_menu_defaults_handler(
            role_name=role,
            all_menu_keys=["dashboard"],
            visible_keys={"dashboard"},
            updated_by_user_id=1,
            role_menu_default_model=RoleMenuDefault,
            db_session=db.session,
            filter_live_menu_keys_func=filter_live_menu_keys,
            filter_live_menu_rows_func=filter_live_menu_rows,
            snapshot_role_menu_state_func=snapshot_role_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=spy,
        )

        after = {row.menu_key: row.is_visible for row in RoleMenuDefault.query.filter_by(role_name=role).all()}
        assert after == {"dashboard": True, "repository": True}, (
            "removed-scope 'repository' row must survive a routine save the admin never saw it in"
        )
        assert changed == 0, "nothing the admin actually controls changed -- the removed row must not count"

        assert len(spy.calls) == 1
        call = spy.calls[0]
        assert call["previous_state"] == {"dashboard": True}
        assert call["new_state"] == {"dashboard": True}

        RoleMenuDefault.query.filter_by(role_name=role).delete()
        db.session.commit()


# ---------------------------------------------------------------------------
# save_unit_menu_profile_handler
# ---------------------------------------------------------------------------


def test_save_unit_menu_profile_blank_unit_name_raises_value_error(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    with app.app_context(), pytest.raises(ValueError):
        save_unit_menu_profile_handler(
            unit_name="",
            all_menu_keys=["k1"],
            visible_keys={"k1"},
            updated_by_user_id=1,
            unit_menu_profile_model=UnitMenuProfile,
            db_session=db.session,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_unit_menu_state_func=snapshot_unit_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=ChangeLogSpy(),
        )


def test_save_unit_menu_profile_persists_new_rows_with_correct_fields_and_audits(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        spy = ChangeLogSpy()
        changed = save_unit_menu_profile_handler(
            unit_name=unit,
            all_menu_keys=["wave_alpha", "wave_beta"],
            visible_keys={"wave_alpha"},
            updated_by_user_id=13,
            unit_menu_profile_model=UnitMenuProfile,
            db_session=db.session,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_unit_menu_state_func=snapshot_unit_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=spy,
        )

        assert changed == 2
        rows = {row.menu_key: row for row in UnitMenuProfile.query.filter_by(unit_name=unit).all()}
        assert rows["wave_alpha"].is_visible is True
        assert rows["wave_beta"].is_visible is False
        for row in rows.values():
            assert row.source_type == "manual"
            assert row.updated_by_user_id == 13

        assert len(spy.calls) == 1
        assert spy.calls[0]["change_scope"] == "unit_menu_profiles"
        assert spy.calls[0]["target_unit_name"] == unit
        assert spy.calls[0]["new_state"] == {"wave_alpha": True, "wave_beta": False}

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        db.session.commit()


def test_save_unit_menu_profile_idempotent_second_call_reports_zero_changed(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        def _save(spy: ChangeLogSpy) -> int:
            return save_unit_menu_profile_handler(
                unit_name=unit,
                all_menu_keys=["wave_alpha", "wave_beta"],
                visible_keys={"wave_beta"},
                updated_by_user_id=3,
                unit_menu_profile_model=UnitMenuProfile,
                db_session=db.session,
                filter_live_menu_rows_func=filter_live_menu_rows,
                filter_live_menu_keys_func=filter_live_menu_keys,
                snapshot_unit_menu_state_func=snapshot_unit_menu_state,
                build_complete_visibility_map_func=build_complete_visibility_map,
                create_settings_change_log_func=spy,
            )

        first = _save(ChangeLogSpy())
        second = _save(ChangeLogSpy())

        assert first == 2
        assert second == 0

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        db.session.commit()


def test_save_unit_menu_profile_updates_existing_row_when_visibility_changes(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        db.session.add(UnitMenuProfile(unit_name=unit, menu_key="wave_alpha", is_visible=False, source_type="seed"))
        db.session.commit()

        changed = save_unit_menu_profile_handler(
            unit_name=unit,
            all_menu_keys=["wave_alpha"],
            visible_keys={"wave_alpha"},
            updated_by_user_id=21,
            unit_menu_profile_model=UnitMenuProfile,
            db_session=db.session,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_unit_menu_state_func=snapshot_unit_menu_state,
            build_complete_visibility_map_func=build_complete_visibility_map,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert changed == 1
        row = UnitMenuProfile.query.filter_by(unit_name=unit, menu_key="wave_alpha").one()
        assert row.is_visible is True
        assert row.source_type == "manual"
        assert row.updated_by_user_id == 21

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        db.session.commit()


def test_save_unit_menu_profile_prunes_rows_for_menu_keys_no_longer_present(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        def _save(all_menu_keys: list[str], visible_keys: set[str]) -> int:
            return save_unit_menu_profile_handler(
                unit_name=unit,
                all_menu_keys=all_menu_keys,
                visible_keys=visible_keys,
                updated_by_user_id=1,
                unit_menu_profile_model=UnitMenuProfile,
                db_session=db.session,
                filter_live_menu_rows_func=filter_live_menu_rows,
                filter_live_menu_keys_func=filter_live_menu_keys,
                snapshot_unit_menu_state_func=snapshot_unit_menu_state,
                build_complete_visibility_map_func=build_complete_visibility_map,
                create_settings_change_log_func=ChangeLogSpy(),
            )

        _save(["wave_alpha", "wave_beta"], {"wave_alpha", "wave_beta"})
        changed = _save(["wave_alpha"], {"wave_alpha"})

        assert changed == 1
        remaining = {row.menu_key for row in UnitMenuProfile.query.filter_by(unit_name=unit).all()}
        assert remaining == {"wave_alpha"}

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        db.session.commit()


# ---------------------------------------------------------------------------
# clear_user_menu_overrides_handler
# ---------------------------------------------------------------------------


def test_clear_user_menu_overrides_deletes_all_rows_and_returns_count_with_audit(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        db.session.add_all([
            UserMenuPermission(user_id=user.id, menu_key="wave_alpha", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="wave_beta", is_visible=False, source_type="user_override"),
        ])
        db.session.commit()

        spy = ChangeLogSpy()
        deleted = clear_user_menu_overrides_handler(
            user_id=user.id,
            updated_by_user_id=99,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=spy,
        )

        assert deleted == 2
        assert UserMenuPermission.query.filter_by(user_id=user.id).count() == 0
        assert len(spy.calls) == 1
        assert spy.calls[0]["change_scope"] == "user_menu_overrides"
        assert spy.calls[0]["action_type"] == "clear"
        assert spy.calls[0]["target_user_id"] == user.id
        assert spy.calls[0]["new_state"] == {}
        assert spy.calls[0]["previous_state"] == {"wave_alpha": True, "wave_beta": False}


def test_clear_user_menu_overrides_zero_rows_returns_zero_but_still_logs(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()

        spy = ChangeLogSpy()
        deleted = clear_user_menu_overrides_handler(
            user_id=user.id,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=spy,
        )

        assert deleted == 0
        assert len(spy.calls) == 1
        assert spy.calls[0]["previous_state"] == {}
        assert spy.calls[0]["new_state"] == {}


def test_clear_user_menu_overrides_deletes_rows_regardless_of_live_scope_filter(app) -> None:
    """REAL_FUNCTIONAL_BUG_DISCOVERED / fixed: ``clear_user_menu_overrides_handler``
    used to apply a live-scope filter before computing the delete set, so
    override rows for permanently-removed-module menu keys (``repository``,
    ``education``, ``strategy`` -- see ``app/config/removed_modules.py``)
    silently survived a "clear all overrides" call, ``deleted_count``
    undercounted, and the audit log's ``new_state={}`` claim was false. The
    handler signature no longer accepts a live-scope filter at all: it deletes
    every row for the user unconditionally. This test replaces the old
    characterization test (which asserted the removed-scope row survived) and
    instead asserts full deletion of a mixed live + removed-scope row set.
    """
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        db.session.add_all([
            UserMenuPermission(user_id=user.id, menu_key="dashboard", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="repository", is_visible=True, source_type="user_override"),
        ])
        db.session.commit()

        deleted = clear_user_menu_overrides_handler(
            user_id=user.id,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert deleted == 2
        remaining = {row.menu_key for row in UserMenuPermission.query.filter_by(user_id=user.id).all()}
        assert remaining == set()


def test_clear_user_menu_overrides_deletes_only_removed_scope_rows(app) -> None:
    """Scenario B: a user whose overrides are ALL on removed-scope menu keys
    (``repository``/``education``/``strategy``) must still have every row
    deleted and counted -- there is no "removed scope survives" carve-out.
    """
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        db.session.add_all([
            UserMenuPermission(user_id=user.id, menu_key="repository", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="education", is_visible=False, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="strategy", is_visible=True, source_type="user_override"),
        ])
        db.session.commit()

        deleted = clear_user_menu_overrides_handler(
            user_id=user.id,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert deleted == 3
        assert UserMenuPermission.query.filter_by(user_id=user.id).count() == 0


def test_clear_user_menu_overrides_deletes_only_live_scope_rows_no_regression(app) -> None:
    """Scenario C: the already-correct live-only case must keep working --
    no regression from removing the live-scope filter from the handler.
    """
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        db.session.add_all([
            UserMenuPermission(user_id=user.id, menu_key="dashboard", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="personel_yetki", is_visible=False, source_type="user_override"),
        ])
        db.session.commit()

        deleted = clear_user_menu_overrides_handler(
            user_id=user.id,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert deleted == 2
        assert UserMenuPermission.query.filter_by(user_id=user.id).count() == 0


def test_clear_user_menu_overrides_audit_previous_state_includes_live_and_removed_keys(app) -> None:
    """Scenario E: the audit log's ``previous_state`` must reflect BOTH the
    live-scope and removed-scope override rows with their real ``is_visible``
    values -- not just the live subset.
    """
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        db.session.add_all([
            UserMenuPermission(user_id=user.id, menu_key="dashboard", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="repository", is_visible=False, source_type="user_override"),
        ])
        db.session.commit()

        spy = ChangeLogSpy()
        clear_user_menu_overrides_handler(
            user_id=user.id,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=spy,
        )

        assert len(spy.calls) == 1
        assert spy.calls[0]["previous_state"] == {"dashboard": True, "repository": False}


def test_clear_user_menu_overrides_audit_new_state_matches_actual_empty_db_state(app) -> None:
    """Scenario F: the whole point of the original bug was that the audit
    log's ``new_state={}`` claim and DB reality diverged. Assert both
    independently and confirm they now agree.
    """
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        db.session.add_all([
            UserMenuPermission(user_id=user.id, menu_key="dashboard", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="education", is_visible=True, source_type="user_override"),
        ])
        db.session.commit()

        spy = ChangeLogSpy()
        deleted = clear_user_menu_overrides_handler(
            user_id=user.id,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=spy,
        )

        assert deleted == 2
        assert spy.calls[0]["new_state"] == {}
        # Independently re-query the DB -- do not just trust the logged claim.
        real_remaining_count = UserMenuPermission.query.filter_by(user_id=user.id).count()
        assert real_remaining_count == 0


def test_clear_user_menu_overrides_commit_failure_propagates_without_swallowing(app) -> None:
    """Scenario G: the handler has no try/except around the commit -- an
    exception raised during commit must propagate to the caller rather than
    being silently swallowed. Wraps the real session so ``delete`` still
    behaves normally but ``commit`` raises, matching this file's existing
    ``BoomModel``-style "raising stand-in simulates a real failure" pattern.
    """
    from app.extensions import db
    from app.models import UserMenuPermission

    class _CommitFailsSession:
        def __init__(self, real_session: Any) -> None:
            self._real = real_session

        def delete(self, obj: Any) -> None:
            self._real.delete(obj)

        def commit(self) -> None:
            raise RuntimeError("BYS360 phase5w2 simulated commit failure for clear_user_menu_overrides")

    with app.app_context():
        user = _make_user()
        db.session.add(
            UserMenuPermission(user_id=user.id, menu_key="dashboard", is_visible=True, source_type="user_override")
        )
        db.session.commit()

        with pytest.raises(RuntimeError, match="simulated commit failure"):
            clear_user_menu_overrides_handler(
                user_id=user.id,
                updated_by_user_id=1,
                user_menu_permission_model=UserMenuPermission,
                db_session=_CommitFailsSession(db.session),
                create_settings_change_log_func=ChangeLogSpy(),
            )

        # The failed commit never landed -- the pending delete only exists on
        # the real session's transaction. Roll it back and confirm the row
        # was never actually removed (no silent partial-success).
        db.session.rollback()
        remaining = {row.menu_key for row in UserMenuPermission.query.filter_by(user_id=user.id).all()}
        assert remaining == {"dashboard"}


def test_clear_user_menu_overrides_real_production_wiring_fixes_mixed_scope_bug_end_to_end(app) -> None:
    """Section 4 (most important): exercises the REAL production call path --
    ``settings_service.clear_user_menu_overrides`` -- with its real
    ``UserMenuPermission``/``db.session``/``create_settings_change_log``
    wiring baked in (no injected test doubles for the handler's dependencies).
    This is the path actual users/admins hit, and the one that would have
    caught the original bug: before the fix, the removed-scope ``repository``
    row would have survived the clear and ``deleted_count`` would have been 1
    instead of 2.
    """
    from app.extensions import db
    from app.models import SettingsChangeLog, UserMenuPermission
    from app.services import settings_service
    from app.services.settings.change_logs import deserialize_settings_state

    with app.app_context():
        user = _make_user()
        db.session.add_all([
            UserMenuPermission(user_id=user.id, menu_key="dashboard", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user.id, menu_key="repository", is_visible=True, source_type="user_override"),
        ])
        db.session.commit()

        deleted = settings_service.clear_user_menu_overrides(user.id, updated_by_user_id=77)

        assert deleted == 2
        assert UserMenuPermission.query.filter_by(user_id=user.id).count() == 0

        log_row = SettingsChangeLog.query.filter_by(
            target_user_id=user.id, change_scope="user_menu_overrides", action_type="clear"
        ).order_by(SettingsChangeLog.id.desc()).first()
        assert log_row is not None
        assert log_row.actor_user_id == 77
        assert deserialize_settings_state(log_row.new_state_json) == {}
        assert deserialize_settings_state(log_row.previous_state_json) == {
            "dashboard": True, "repository": True,
        }


def test_clear_user_menu_overrides_does_not_affect_other_users_rows(app) -> None:
    """Section 5: clearing user A's overrides must leave user B's rows --
    including their removed-scope row -- completely untouched.
    """
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user_a = _make_user(ad="UserA")
        user_b = _make_user(ad="UserB")
        db.session.add_all([
            UserMenuPermission(user_id=user_a.id, menu_key="dashboard", is_visible=True, source_type="user_override"),
            UserMenuPermission(user_id=user_a.id, menu_key="repository", is_visible=False, source_type="user_override"),
            UserMenuPermission(user_id=user_b.id, menu_key="dashboard", is_visible=False, source_type="user_override"),
            UserMenuPermission(user_id=user_b.id, menu_key="repository", is_visible=True, source_type="user_override"),
        ])
        db.session.commit()

        deleted = clear_user_menu_overrides_handler(
            user_id=user_a.id,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert deleted == 2
        assert UserMenuPermission.query.filter_by(user_id=user_a.id).count() == 0

        user_b_rows = {
            row.menu_key: bool(row.is_visible)
            for row in UserMenuPermission.query.filter_by(user_id=user_b.id).all()
        }
        assert user_b_rows == {"dashboard": False, "repository": True}


# ---------------------------------------------------------------------------
# save_user_menu_overrides_handler
# ---------------------------------------------------------------------------


def _is_removed_key(key: Any) -> bool:
    return str(key or "") == "wave_removed"


def test_save_user_menu_overrides_dedupes_duplicate_menu_keys_keeping_first(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        flat_items = [
            {"key": "wave_alpha", "label": "first"},
            {"key": "wave_alpha", "label": "duplicate-should-be-dropped"},
            {"key": "wave_beta"},
        ]

        result = save_user_menu_overrides_handler(
            user=user,
            flat_menu_items=flat_items,
            visible_keys={"wave_alpha", "wave_beta"},
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            is_removed_menu_key_func=_is_removed_key,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_user_override_state_func=snapshot_user_override_state,
            build_base_rule_map_for_user_func=lambda _u, _items_: {"base_rule_map": {}},
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert result == {"changed": 2, "override_count": 2}
        rows = {row.menu_key for row in UserMenuPermission.query.filter_by(user_id=user.id).all()}
        assert rows == {"wave_alpha", "wave_beta"}


def test_save_user_menu_overrides_filters_removed_menu_keys_via_injected_predicate(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        flat_items = [{"key": "wave_alpha"}, {"key": "wave_removed"}]

        result = save_user_menu_overrides_handler(
            user=user,
            flat_menu_items=flat_items,
            visible_keys={"wave_alpha", "wave_removed"},
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            is_removed_menu_key_func=_is_removed_key,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_user_override_state_func=snapshot_user_override_state,
            build_base_rule_map_for_user_func=lambda _u, _items_: {"base_rule_map": {}},
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert result["override_count"] == 1
        rows = {row.menu_key for row in UserMenuPermission.query.filter_by(user_id=user.id).all()}
        assert rows == {"wave_alpha"}


def test_save_user_menu_overrides_persists_with_user_override_source_and_real_audit_row(app) -> None:
    from app.extensions import db
    from app.models import SettingsChangeLog, UserMenuPermission
    from app.services.settings.change_logs import (
        create_settings_change_log,
        deserialize_settings_state,
    )

    with app.app_context():
        user = _make_user(ad="Ada", soyad="Lovelace")
        flat_items = [{"key": "wave_alpha"}, {"key": "wave_beta"}]

        result = save_user_menu_overrides_handler(
            user=user,
            flat_menu_items=flat_items,
            visible_keys={"wave_alpha"},
            updated_by_user_id=user.id,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            is_removed_menu_key_func=lambda _key: False,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_user_override_state_func=snapshot_user_override_state,
            build_base_rule_map_for_user_func=lambda _u, _items_: {"base_rule_map": {}},
            create_settings_change_log_func=create_settings_change_log,
        )

        assert result == {"changed": 2, "override_count": 2}
        rows = {row.menu_key: row for row in UserMenuPermission.query.filter_by(user_id=user.id).all()}
        assert rows["wave_alpha"].is_visible is True
        assert rows["wave_alpha"].source_type == "user_override"
        assert rows["wave_beta"].is_visible is False

        log_row = SettingsChangeLog.query.filter_by(
            target_user_id=user.id, change_scope="user_menu_overrides"
        ).order_by(SettingsChangeLog.id.desc()).first()
        assert log_row is not None
        assert log_row.action_type == "save_full_personnel_feature_matrix"
        assert log_row.summary == "Personel bazlı rol matrisi kaydedildi: Ada Lovelace"
        assert deserialize_settings_state(log_row.new_state_json) == {"wave_alpha": True, "wave_beta": False}


def test_save_user_menu_overrides_idempotent_second_call_reports_zero_changed(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        flat_items = [{"key": "wave_alpha"}, {"key": "wave_beta"}]
        kwargs = dict(
            user=user,
            flat_menu_items=flat_items,
            visible_keys={"wave_alpha"},
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            is_removed_menu_key_func=lambda _key: False,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_user_override_state_func=snapshot_user_override_state,
            build_base_rule_map_for_user_func=lambda _u, _items_: {"base_rule_map": {}},
        )
        first = save_user_menu_overrides_handler(create_settings_change_log_func=ChangeLogSpy(), **kwargs)
        second = save_user_menu_overrides_handler(create_settings_change_log_func=ChangeLogSpy(), **kwargs)

        assert first["changed"] == 2
        assert second["changed"] == 0


def test_save_user_menu_overrides_updates_existing_row_when_visibility_changes(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        db.session.add(
            UserMenuPermission(user_id=user.id, menu_key="wave_alpha", is_visible=False, source_type="seed")
        )
        db.session.commit()

        result = save_user_menu_overrides_handler(
            user=user,
            flat_menu_items=[{"key": "wave_alpha"}],
            visible_keys={"wave_alpha"},
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            is_removed_menu_key_func=lambda _key: False,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_user_override_state_func=snapshot_user_override_state,
            build_base_rule_map_for_user_func=lambda _u, _items_: {"base_rule_map": {}},
            create_settings_change_log_func=ChangeLogSpy(),
        )

        assert result == {"changed": 1, "override_count": 1}
        row = UserMenuPermission.query.filter_by(user_id=user.id, menu_key="wave_alpha").one()
        assert row.is_visible is True
        assert row.source_type == "user_override"


def test_save_user_menu_overrides_prunes_rows_for_menu_keys_no_longer_present(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    with app.app_context():
        user = _make_user()
        base_kwargs = dict(
            user=user,
            updated_by_user_id=1,
            user_menu_permission_model=UserMenuPermission,
            db_session=db.session,
            is_removed_menu_key_func=lambda _key: False,
            filter_live_menu_rows_func=filter_live_menu_rows,
            filter_live_menu_keys_func=filter_live_menu_keys,
            snapshot_user_override_state_func=snapshot_user_override_state,
            build_base_rule_map_for_user_func=lambda _u, _items_: {"base_rule_map": {}},
        )
        save_user_menu_overrides_handler(
            flat_menu_items=[{"key": "wave_alpha"}, {"key": "wave_beta"}],
            visible_keys={"wave_alpha", "wave_beta"},
            create_settings_change_log_func=ChangeLogSpy(),
            **base_kwargs,
        )
        result = save_user_menu_overrides_handler(
            flat_menu_items=[{"key": "wave_alpha"}],
            visible_keys={"wave_alpha"},
            create_settings_change_log_func=ChangeLogSpy(),
            **base_kwargs,
        )

        assert result["changed"] == 1
        assert result["override_count"] == 1
        remaining = {row.menu_key for row in UserMenuPermission.query.filter_by(user_id=user.id).all()}
        assert remaining == {"wave_alpha"}


# ---------------------------------------------------------------------------
# build_settings_profile_context_handler
# ---------------------------------------------------------------------------


def test_build_settings_profile_context_without_selected_user_returns_snapshot_and_total(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    unit = f"phase5w2_unit_{_uid()}"
    with app.app_context():
        db.session.add(UnitMenuProfile(unit_name=unit, menu_key="wave_alpha", is_visible=True, source_type="manual"))
        db.session.commit()

        rollback_spy = RollbackSpy(db.session)
        context = build_settings_profile_context_handler(
            selected_user=None,
            flat_menu_items=_items("wave_alpha"),
            flatten_menu_definitions_func=lambda: _items("wave_alpha"),
            unit_menu_profile_model=UnitMenuProfile,
            build_unit_profile_snapshot_func=lambda: [{"unit_name": unit}],
            build_effective_user_menu_context_func=lambda *_a, **_k: pytest.fail("should not be called"),
            list_recent_settings_change_logs_func=lambda **_k: ["log1", "log2"],
            safe_rollback_func=rollback_spy,
        )

        assert context["unit_profiles_snapshot"] == [{"unit_name": unit}]
        assert context["unit_profile_total"] >= 1
        assert context["selected_user_resolution"] is None
        assert context["recent_change_logs"] == ["log1", "log2"]
        assert rollback_spy.call_count == 0

        UnitMenuProfile.query.filter_by(unit_name=unit).delete()
        db.session.commit()


def test_build_settings_profile_context_with_selected_user_includes_effective_context(app) -> None:
    from app.extensions import db
    from app.models import UnitMenuProfile

    with app.app_context():
        user = _make_user()
        calls: list[Any] = []

        def _effective_context_func(user_obj: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append((user_obj, items))
            return {"effective_rule_map": {"k1": True}}

        context = build_settings_profile_context_handler(
            selected_user=user,
            flat_menu_items=_items("k1"),
            flatten_menu_definitions_func=lambda: _items("k1"),
            unit_menu_profile_model=UnitMenuProfile,
            build_unit_profile_snapshot_func=lambda: [],
            build_effective_user_menu_context_func=_effective_context_func,
            list_recent_settings_change_logs_func=lambda **kwargs: [kwargs.get("target_user_id")],
            safe_rollback_func=RollbackSpy(db.session),
        )

        assert context["selected_user_resolution"] == {"effective_rule_map": {"k1": True}}
        assert context["recent_change_logs"] == [user.id]
        assert len(calls) == 1
        assert calls[0][0] is user


def test_build_settings_profile_context_exception_path_defaults_total_to_zero(app) -> None:
    from app.extensions import db

    with app.app_context():
        rollback_spy = RollbackSpy(db.session)
        context = build_settings_profile_context_handler(
            selected_user=None,
            flat_menu_items=_items("k1"),
            flatten_menu_definitions_func=lambda: _items("k1"),
            unit_menu_profile_model=BoomModel,
            build_unit_profile_snapshot_func=lambda: [],
            build_effective_user_menu_context_func=lambda *_a, **_k: pytest.fail("should not be called"),
            list_recent_settings_change_logs_func=lambda **_k: [],
            safe_rollback_func=rollback_spy,
        )

        assert context["unit_profile_total"] == 0
        assert rollback_spy.call_count == 1


# --- isolation from a stale process-global Config database URI ---
#
# config.Config.SQLALCHEMY_DATABASE_URI is computed once, when config.py is
# first imported. If an earlier test imported it while DATABASE_URL pointed at
# its own SQLite file, setting DATABASE_URL here came too late: this module's
# apps would silently use that file and read menu rows left there by other
# apps.

_STALE_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "settings_menu_profile_stale_config"


def test_app_does_not_inherit_a_stale_frozen_config_database_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.extensions import db
    from config import Config

    _STALE_DB_ROOT.mkdir(parents=True, exist_ok=True)
    stale_path = _STALE_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    conn = sqlite3.connect(stale_path)
    conn.execute("CREATE TABLE stale_config_marker (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + stale_path.as_posix())

    app = _make_app(monkeypatch)
    counts: dict[str, Any] = {}
    try:
        with app.app_context():
            engine_url = str(db.engine.url)
            on_stale_db = inspect(db.engine).has_table("stale_config_marker")
            counts["users"] = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            counts["role_menu_defaults"] = db.session.execute(
                text("SELECT COUNT(*) FROM role_menu_defaults")
            ).scalar()
            counts["unit_menu_profiles"] = db.session.execute(
                text("SELECT COUNT(*) FROM unit_menu_profiles")
            ).scalar()
            counts["user_menu_permissions"] = db.session.execute(
                text("SELECT COUNT(*) FROM user_menu_permissions")
            ).scalar()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        stale_path.unlink(missing_ok=True)

    assert engine_url == "sqlite:///:memory:"
    assert not on_stale_db
    assert counts == {
        "users": 0,
        "role_menu_defaults": 0,
        "unit_menu_profiles": 0,
        "user_menu_permissions": 0,
    }
