"""BYS360_DEFECT_W_PERFORMANCE_SINGLE_ACTIVE_PERIOD_INTEGRATION

Regression contract for a mechanically-confirmed invariant violation in
``app.services.performance.v2_1_6_category_period_integration.
create_or_update_period_from_plan``.

Canonical invariant (proven from the existing codebase, not invented): AT
MOST ONE ``PerformancePeriod`` may have ``is_active=True`` at a time. This is
independently confirmed by two pre-existing, un-touched pieces of the
codebase:
  - ``app.services.performance_v2.validators.validate_single_active_period``
    -- returns an issue list ("Aynı anda birden fazla aktif dönem var: ...")
    whenever more than one period is active.
  - the sibling activation flow
    ``app.performance.admin_core_routes.performance_period_toggle_active``
    (the canonical implementation), which -- before setting the target
    period active -- runs:
        PerformancePeriod.query
            .filter(PerformancePeriod.is_active.is_(True), PerformancePeriod.id != period.id)
            .update({PerformancePeriod.is_active: False}, synchronize_session=False)

Root cause (confirmed by reading the source before this fix):
``create_or_update_period_from_plan`` could set ``period.is_active = True``
(for both a newly created period and an existing one, via its
``activate_period`` flag) without ever deactivating any other period. Two
periods could therefore end up simultaneously active after a successful
commit.

Fix (reviewed contract, reused verbatim from the canonical
``performance_period_toggle_active`` bulk-deactivation query -- not a new,
competing invariant implementation): when ``activate_period`` is True, the
same bulk ``UPDATE ... WHERE is_active=True AND id != target.id`` runs in the
SAME transaction, before the final flush/commit that persists the target
period's own activation.

Fixture pattern: proven per this remediation wave's mandatory rule -- copied
from tests/behavior/test_mobile_kpi_goals_scope_leak_contract.py's
``_make_app`` (Config class attributes monkeypatched BEFORE create_app(),
StaticPool + pysqlite isolation_level=None + explicit BEGIN event listener),
trimmed to a plain app-context fixture since this defect's regression is
service-level (no Flask route/client involved). Uses its own dedicated tmp DB
directory (C:\\bys360_pytest_tmp_defect_w) so it shares no state with any
other wave/agent running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_w")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-w-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-w-first-login-test-pw")
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
    db_path = os.path.join(_TMP_DB_DIR, f"defect_w_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # BYS360_DEFECT_W: Config.SQLALCHEMY_DATABASE_URI is a class attribute
    # frozen the first time config.py is imported anywhere in this pytest
    # process. Flask-SQLAlchemy 3.x lazily binds AND CACHES the per-app
    # Engine on first access, read from app.config at that exact moment.
    # Patching Config's class attributes BEFORE create_app() (not updating
    # flask_app.config afterward) is required for this test's own unique
    # file-backed SQLite DB to actually take effect.
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
    from app.services import runtime_schema

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has

    return flask_app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_period(app, *, title, is_active):
    import datetime

    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        period = PerformancePeriod(
            title=title,
            name=title,
            period_type="monthly",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            is_active=is_active,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _create_plan(app, *, category_key="guvenlik", start_date="2026-02-01", end_date="2026-02-28"):
    from app.services.performance.v2_1_5_category_period_scope import (
        upsert_category_period_scope_plan,
    )

    with app.app_context():
        result = upsert_category_period_scope_plan(
            category_key=category_key,
            start_date=start_date,
            end_date=end_date,
        )
        assert result["ok"] is True
        return result["plan_key"]


def _is_active(app, period_id) -> bool:
    from app.models import PerformancePeriod

    with app.app_context():
        period = PerformancePeriod.query.get(period_id)
        return bool(period.is_active)


def _active_period_ids(app) -> set[int]:
    from app.models import PerformancePeriod

    with app.app_context():
        return {p.id for p in PerformancePeriod.query.filter_by(is_active=True).all()}


# ---------------------------------------------------------------------------
# 1: existing active A + activating B via the plan-integration path -> A
#    inactive, B active
# ---------------------------------------------------------------------------


def test_activating_period_via_plan_integration_deactivates_existing_active_period(app):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    period_a_id = _create_period(app, title="DefectW Period A", is_active=True)
    plan_key = _create_plan(app)

    with app.app_context():
        result = create_or_update_period_from_plan(plan_key, activate_period=True)
        assert result["ok"] is True
        period_b_id = result["period_id"]

    assert period_b_id != period_a_id
    assert _is_active(app, period_a_id) is False, "activating B must deactivate the previously active A"
    assert _is_active(app, period_b_id) is True
    assert _active_period_ids(app) == {period_b_id}


# ---------------------------------------------------------------------------
# 2: three periods -> exactly one active after activating target
# ---------------------------------------------------------------------------


def test_three_periods_exactly_one_active_after_activating_target(app):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    period_a_id = _create_period(app, title="DefectW Three A", is_active=True)
    period_b_id = _create_period(app, title="DefectW Three B", is_active=False)
    _ = period_b_id
    plan_key = _create_plan(app, start_date="2026-03-01", end_date="2026-03-31")

    with app.app_context():
        result = create_or_update_period_from_plan(plan_key, activate_period=True)
        target_id = result["period_id"]

    active_ids = _active_period_ids(app)
    assert active_ids == {target_id}
    assert period_a_id not in active_ids


# ---------------------------------------------------------------------------
# 3: updating an already-active target through this path preserves exactly
#    one active period (no duplicate deactivation bugs, no accidental
#    self-deactivation)
# ---------------------------------------------------------------------------


def test_updating_active_target_through_plan_integration_preserves_exactly_one_active(app):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    plan_key = _create_plan(app, start_date="2026-04-01", end_date="2026-04-30")
    with app.app_context():
        first = create_or_update_period_from_plan(plan_key, activate_period=True)
        target_id = first["period_id"]
    assert _is_active(app, target_id) is True

    with app.app_context():
        second = create_or_update_period_from_plan(plan_key, activate_period=True)
        assert second["action"] == "updated"
        assert second["period_id"] == target_id

    assert _active_period_ids(app) == {target_id}


# ---------------------------------------------------------------------------
# 4: creating a NON-active period through this path does not touch the
#    currently active period
# ---------------------------------------------------------------------------


def test_creating_inactive_period_does_not_deactivate_current_active_period(app):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    period_a_id = _create_period(app, title="DefectW Untouched Active", is_active=True)
    plan_key = _create_plan(app, start_date="2026-05-01", end_date="2026-05-31")

    with app.app_context():
        result = create_or_update_period_from_plan(plan_key, activate_period=False)
        new_period_id = result["period_id"]

    assert _is_active(app, period_a_id) is True, "an unrelated non-activating create must not deactivate the active period"
    assert _is_active(app, new_period_id) is False
    assert _active_period_ids(app) == {period_a_id}


# ---------------------------------------------------------------------------
# 5: updating an unrelated INACTIVE period (activate_period=False) does not
#    change which period is active
# ---------------------------------------------------------------------------


def test_updating_unrelated_inactive_period_does_not_change_active_period(app):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    period_a_id = _create_period(app, title="DefectW Stays Active", is_active=True)
    plan_key = _create_plan(app, start_date="2026-06-01", end_date="2026-06-30")

    with app.app_context():
        first = create_or_update_period_from_plan(plan_key, activate_period=False)
        inactive_id = first["period_id"]
        second = create_or_update_period_from_plan(plan_key, activate_period=False)
        assert second["action"] == "updated"
        assert second["period_id"] == inactive_id

    assert _is_active(app, period_a_id) is True
    assert _is_active(app, inactive_id) is False
    assert _active_period_ids(app) == {period_a_id}


# ---------------------------------------------------------------------------
# 6/7: canonical active-period resolvers agree on the target after activation
# ---------------------------------------------------------------------------


def test_canonical_active_period_resolvers_agree_after_activation(app):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    _create_period(app, title="DefectW Resolver Old", is_active=True)
    plan_key = _create_plan(app, start_date="2026-07-01", end_date="2026-07-31")

    with app.app_context():
        result = create_or_update_period_from_plan(plan_key, activate_period=True)
        target_id = result["period_id"]

    with app.app_context():
        from app.services.performance.common import get_active_period, get_period
        from app.services.performance.context import get_selected_period

        resolved_active = get_active_period()
        resolved_period = get_period(None)
        resolved_selected = get_selected_period(None, fallback_to_active=True)
        assert resolved_active is not None
        assert resolved_period is not None
        assert resolved_selected is not None
        assert resolved_active.id == target_id
        assert resolved_period.id == target_id
        assert resolved_selected.id == target_id


def test_validate_single_active_period_passes_after_activation(app):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )
    from app.services.performance_v2.validators import validate_single_active_period

    _create_period(app, title="DefectW Validator Old", is_active=True)
    plan_key = _create_plan(app, start_date="2026-08-01", end_date="2026-08-31")

    with app.app_context():
        create_or_update_period_from_plan(plan_key, activate_period=True)

    with app.app_context():
        from app.models import PerformancePeriod

        issues = validate_single_active_period(PerformancePeriod.query.all())
    assert issues == [], f"expected no single-active-period violations, got: {issues}"


# ---------------------------------------------------------------------------
# 8: a forced failure mid-operation rolls back atomically -- no partial
#    active-state corruption (both the target's own activation and the
#    sibling deactivation bulk-update live in the same uncommitted
#    transaction).
# ---------------------------------------------------------------------------


def test_forced_failure_rolls_back_without_partial_active_state_corruption(app, monkeypatch):
    from app.services.performance.v2_1_6_category_period_integration import (
        create_or_update_period_from_plan,
    )

    period_a_id = _create_period(app, title="DefectW Rollback Guard", is_active=True)
    plan_key = _create_plan(app, start_date="2026-09-01", end_date="2026-09-30")

    with app.app_context():
        from app.extensions import db

        def _boom(*args, **kwargs):
            raise RuntimeError("BYS360 defect W forced-failure rollback probe")

        monkeypatch.setattr(db.session, "commit", _boom)
        with pytest.raises(RuntimeError):
            create_or_update_period_from_plan(plan_key, activate_period=True)
        monkeypatch.undo()
        db.session.rollback()

    assert _is_active(app, period_a_id) is True, (
        "a forced commit failure must roll back the sibling deactivation bulk-update "
        "together with the target's own activation, leaving the original active period untouched"
    )
    assert _active_period_ids(app) == {period_a_id}
