"""BYS360_DEFECT_X_PERFORMANCE_WEIGHT_CONFIG_PERIOD_BINDING

Regression contract for a mechanically-confirmed wrong-period weight
configuration fallback, found in TWO sibling functions sharing the exact same
root cause (both inspected and confirmed before this fix):

  - app.services.performance.common.get_active_weight_config
  - app.services.performance.context.get_weight_config_for_period

Root cause: when called for a SPECIFIC period that has no active
``PerformanceWeightConfig`` row of its own, each function fell through to an
UNFILTERED query -- ``PerformanceWeightConfig.query.filter_by(is_active=True)
.order_by(id.desc()).first()`` -- which returns the most recently inserted
active config belonging to ANY period, not the requested one. A period with
no custom weight configuration could therefore silently receive another
period's weights.

Canonical default contract (proven from the existing, un-touched caller
``app.services.performance.common.get_base_weight_map``, NOT invented here):
when ``get_active_weight_config`` correctly returns ``None`` for a period
with no config of its own, ``get_base_weight_map`` already falls back to
that period's own ``level_1_weight``/``level_2_weight``/``level_3_weight``
columns (or, with no period at all, the flat 50/50/0 constants). Returning
``None`` for a period-specific miss -- instead of silently substituting
another period's row -- is therefore the correct fix; no new default
weighting policy is introduced.

Fix: both functions now return the period-scoped query's result directly (or
``None``) when a specific period is requested, without any further
unfiltered fallback. The "no period specified at all" call shape (used
elsewhere for a period-agnostic "most recent active config" lookup) is left
unchanged -- that is a different, legitimate call pattern, not part of this
defect.

Fixture pattern: proven per this remediation wave's mandatory rule -- copied
from tests/behavior/test_mobile_kpi_goals_scope_leak_contract.py's
``_make_app``, trimmed to a plain app-context fixture since this defect's
regression is service-level (no Flask route/client involved). Uses its own
dedicated tmp DB directory (C:\\bys360_pytest_tmp_defect_x) so it shares no
state with any other wave/agent running concurrently.
"""
from __future__ import annotations

import datetime
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_x")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-x-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-x-first-login-test-pw")
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
    db_path = os.path.join(_TMP_DB_DIR, f"defect_x_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # BYS360_DEFECT_X: Config.SQLALCHEMY_DATABASE_URI is a class attribute
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_period(app, *, title, level_1=50.0, level_2=50.0, level_3=0.0):
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        period = PerformancePeriod(
            title=title,
            name=title,
            period_type="monthly",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            is_active=False,
            level_1_weight=level_1,
            level_2_weight=level_2,
            level_3_weight=level_3,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _create_weight_config(app, *, period_id, evaluator_1, evaluator_2, evaluator_3, name):
    from app.extensions import db
    from app.models import PerformanceWeightConfig

    with app.app_context():
        config = PerformanceWeightConfig(
            name=name,
            period_id=period_id,
            evaluator_1_weight=evaluator_1,
            evaluator_2_weight=evaluator_2,
            evaluator_3_weight=evaluator_3,
            is_active=True,
        )
        db.session.add(config)
        db.session.commit()
        return config.id


# ---------------------------------------------------------------------------
# Shared 3-period dataset:
#   Period A -- custom weight config (70/30/0)
#   Period B -- NO custom weight config, distinctive period-level fallback
#               weights (41/39/20) so a leak from A or C, or a flattened
#               50/50/0 hardcoded default, is each independently detectable
#   Period C -- custom weight config (55/25/20), created AFTER A's config so
#               C's config row has a HIGHER id -- proving B's lookup ignores
#               insertion order/recency, not just "the first row created"
# ---------------------------------------------------------------------------


def _build_matrix(app):
    period_a_id = _create_period(app, title="DefectX Period A")
    period_b_id = _create_period(app, title="DefectX Period B", level_1=41.0, level_2=39.0, level_3=20.0)
    period_c_id = _create_period(app, title="DefectX Period C")

    config_a_id = _create_weight_config(app, period_id=period_a_id, evaluator_1=70.0, evaluator_2=30.0, evaluator_3=0.0, name="DefectX Config A")
    config_c_id = _create_weight_config(app, period_id=period_c_id, evaluator_1=55.0, evaluator_2=25.0, evaluator_3=20.0, name="DefectX Config C")
    assert config_c_id > config_a_id, "test setup requires C's config to be inserted after (higher id than) A's"

    return period_a_id, period_b_id, period_c_id, config_a_id, config_c_id


# ---------------------------------------------------------------------------
# common.get_active_weight_config
# ---------------------------------------------------------------------------


def test_get_active_weight_config_period_a_returns_only_own_config(app):
    from app.services.performance.common import get_active_weight_config

    period_a_id, _b, _c, config_a_id, _cc = _build_matrix(app)
    with app.app_context():
        row = get_active_weight_config(period_a_id)
        assert row is not None
        assert row.id == config_a_id
        assert row.evaluator_1_weight == 70.0


def test_get_active_weight_config_period_c_returns_only_own_config(app):
    from app.services.performance.common import get_active_weight_config

    _a, _b, period_c_id, _ca, config_c_id = _build_matrix(app)
    with app.app_context():
        row = get_active_weight_config(period_c_id)
        assert row is not None
        assert row.id == config_c_id
        assert row.evaluator_1_weight == 55.0


def test_get_active_weight_config_period_b_returns_none_never_another_periods_row(app):
    from app.services.performance.common import get_active_weight_config

    _a, period_b_id, _c, config_a_id, config_c_id = _build_matrix(app)
    with app.app_context():
        row = get_active_weight_config(period_b_id)
        assert row is None, (
            "period B has no config of its own; get_active_weight_config must return None, "
            f"not silently substitute another period's config (got id={getattr(row, 'id', None)})"
        )
        _ = (config_a_id, config_c_id)


# ---------------------------------------------------------------------------
# context.get_weight_config_for_period (confirmed same-root sibling)
# ---------------------------------------------------------------------------


def test_get_weight_config_for_period_a_returns_only_own_config(app):
    from app.models import PerformancePeriod
    from app.services.performance.context import get_weight_config_for_period

    period_a_id, _b, _c, config_a_id, _cc = _build_matrix(app)
    with app.app_context():
        period_a = PerformancePeriod.query.get(period_a_id)
        row = get_weight_config_for_period(period_a)
        assert row is not None
        assert row.id == config_a_id


def test_get_weight_config_for_period_c_returns_only_own_config(app):
    from app.models import PerformancePeriod
    from app.services.performance.context import get_weight_config_for_period

    _a, _b, period_c_id, _ca, config_c_id = _build_matrix(app)
    with app.app_context():
        period_c = PerformancePeriod.query.get(period_c_id)
        row = get_weight_config_for_period(period_c)
        assert row is not None
        assert row.id == config_c_id


def test_get_weight_config_for_period_b_returns_none_never_another_periods_row(app):
    from app.models import PerformancePeriod
    from app.services.performance.context import get_weight_config_for_period

    _a, period_b_id, _c, _ca, _cc = _build_matrix(app)
    with app.app_context():
        period_b = PerformancePeriod.query.get(period_b_id)
        row = get_weight_config_for_period(period_b)
        assert row is None, (
            "period B has no config of its own; get_weight_config_for_period must return None, "
            f"not silently substitute another period's config (got id={getattr(row, 'id', None)})"
        )


# ---------------------------------------------------------------------------
# Effective weight resolution (get_base_weight_map, the real, un-invented
# caller-level default policy) agrees with the same period-binding contract
# ---------------------------------------------------------------------------


def test_effective_weight_map_period_a_uses_a_config(app):
    from app.services.performance.common import get_base_weight_map

    period_a_id, _b, _c, _ca, _cc = _build_matrix(app)
    with app.app_context():
        weights = get_base_weight_map(period_a_id)
    assert weights == {"evaluator_1_weight": 70.0, "evaluator_2_weight": 30.0, "evaluator_3_weight": 0.0}


def test_effective_weight_map_period_c_uses_c_config(app):
    from app.services.performance.common import get_base_weight_map

    _a, _b, period_c_id, _ca, _cc = _build_matrix(app)
    with app.app_context():
        weights = get_base_weight_map(period_c_id)
    assert weights == {"evaluator_1_weight": 55.0, "evaluator_2_weight": 25.0, "evaluator_3_weight": 20.0}


def test_effective_weight_map_period_b_uses_its_own_period_level_default_not_a_or_c(app):
    from app.services.performance.common import get_base_weight_map

    _a, period_b_id, _c, _ca, _cc = _build_matrix(app)
    with app.app_context():
        weights = get_base_weight_map(period_b_id)
    assert weights == {"evaluator_1_weight": 41.0, "evaluator_2_weight": 39.0, "evaluator_3_weight": 20.0}, (
        "period B (no weight config) must fall back to ITS OWN period-level weights, "
        "not period A's or C's config, and not a flattened 50/50/0 default"
    )


# ---------------------------------------------------------------------------
# Insertion-order robustness: rebuilding the matrix with C inserted BEFORE A
# (reversed id order from the primary matrix above) must not change B's
# None result -- proving the fix is period-bound, not "oldest row wins" vs.
# "newest row wins" by coincidence.
# ---------------------------------------------------------------------------


def test_period_b_still_returns_none_when_other_periods_configs_are_inserted_in_reverse_order(app):
    from app.services.performance.common import get_active_weight_config

    period_b_id = _create_period(app, title="DefectX Period B Reversed", level_1=41.0, level_2=39.0, level_3=20.0)
    period_c_id = _create_period(app, title="DefectX Period C Reversed")
    period_a_id = _create_period(app, title="DefectX Period A Reversed")

    # C's config created first (lower id) this time; A's config created after
    # (higher id) -- the opposite insertion order from _build_matrix.
    _create_weight_config(app, period_id=period_c_id, evaluator_1=55.0, evaluator_2=25.0, evaluator_3=20.0, name="Reversed C")
    _create_weight_config(app, period_id=period_a_id, evaluator_1=70.0, evaluator_2=30.0, evaluator_3=0.0, name="Reversed A")

    with app.app_context():
        assert get_active_weight_config(period_b_id) is None
