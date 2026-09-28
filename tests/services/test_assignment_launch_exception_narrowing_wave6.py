from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db as flask_db
from app.services.performance import (
    v2_1_6_category_period_integration as category_integration,
    v2_1_8_period_center_assignment_launch as launch,
)

# BYS360 Phase 5 exception-debt wave 6: closes the 13 remaining broad
# `except Exception` handlers in
# app/services/performance/v2_1_8_period_center_assignment_launch.py:
#   _dialect_name
#   _has_column
#   _safe_json
#   _safe_int
#   ensure_period_center_assignment_launch_schema (ALTER handler)
#   _integration_for_plan (outer + nested rollback)
#   _period_for_integration (outer + nested rollback)
#   _precheck_count (outer + nested rollback)
#   _precheck_status_counts (outer + nested rollback)
#
# Narrowing follows the already-narrowed sibling module
# app/services/performance/v2_1_9_period_center_process_notifications.py
# (same wave family, structurally identical functions):
#   - _dialect_name -> RuntimeError only. Its entire body is the single
#     attribute chain `_db().engine.dialect.name`; empirically verified
#     (outside this test file, during wave-6 investigation) that
#     Flask-SQLAlchemy's `db.engine` accessor raises
#     RuntimeError("Working outside of application context.") when no app
#     context is active, and `.dialect.name` is a plain attribute read on an
#     already-resolved object -- no SQLAlchemyError is possible there.
#   - _has_column -> (SQLAlchemyError, RuntimeError). Body does
#     `inspect(_db().engine)` (same RuntimeError source as above) followed by
#     real inspector DB introspection calls (SQLAlchemyError source).
#   - _safe_json / _safe_int -> (TypeError, ValueError). Pure Python value
#     coercion (`json.dumps`, `int(...)`), matching the identical functions
#     already narrowed in v2_1_9 and v2_1_rule_engine.
#   - schema ALTER handler, _integration_for_plan, _period_for_integration,
#     _precheck_count, _precheck_status_counts -> SQLAlchemyError only
#     (outer AND nested rollback). RuntimeError is deliberately NOT added:
#     these functions call into multi-module chains (list_integrations,
#     ensure_category_period_integration_schema, db.session.get/execute)
#     that were not individually audited line-by-line, so a bare RuntimeError
#     catch could just as easily swallow an unrelated programming bug as a
#     genuine context-absence condition -- not safely distinguishable. This
#     matches the precedent and its documented rationale in
#     tests/services/test_period_center_notifications_wave5.py.


@pytest.fixture
def provisioned_app(app):
    """Session app whose database also holds the category tables the launch schema extends."""
    with app.app_context():
        category_integration.provision_category_period_integration_schema()
    return app


class _FakeScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar(self):
        return self._value


class _FakeMappingsResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappingsResult:
        return self

    def all(self):
        return self._rows


# ---------------------------------------------------------------------------
# _dialect_name
# ---------------------------------------------------------------------------


def test_dialect_name_returns_real_dialect_on_success(app) -> None:
    with app.app_context():
        assert launch._dialect_name() == flask_db.engine.dialect.name


def test_dialect_name_returns_unknown_on_runtime_error_outside_context() -> None:
    # No app_context() active here -- this is the real, empirically-verified
    # failure mode, not a monkeypatched simulation.
    assert launch._dialect_name() == "unknown"


def test_dialect_name_does_not_swallow_unexpected_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingDialect:
        @property
        def name(self):
            raise ValueError("unexpected programming failure")

    class FakeEngine:
        dialect = ExplodingDialect()

    class FakeDb:
        engine = FakeEngine()

    monkeypatch.setattr(launch, "_db", lambda: FakeDb())

    with pytest.raises(ValueError):
        launch._dialect_name()


# ---------------------------------------------------------------------------
# _has_column
# ---------------------------------------------------------------------------


def test_has_column_returns_true_when_column_present(provisioned_app) -> None:
    with provisioned_app.app_context():
        launch.ensure_period_center_assignment_launch_schema()
        assert launch._has_column(launch.INTEGRATION_TABLE, "plan_key") is True


def test_has_column_returns_false_on_sqlalchemy_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExplodingInspector:
        def has_table(self, *_a, **_k):
            raise SQLAlchemyError("simulated inspection failure")

    monkeypatch.setattr(launch, "inspect", lambda *_a, **_k: ExplodingInspector())

    with app.app_context():
        assert launch._has_column("any_table", "any_column") is False


def test_has_column_returns_false_on_runtime_error_outside_context() -> None:
    assert launch._has_column("any_table", "any_column") is False


def test_has_column_does_not_swallow_unexpected_type_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_a, **_k):
        raise TypeError("unexpected programming failure")

    monkeypatch.setattr(launch, "inspect", explode)

    with app.app_context(), pytest.raises(TypeError):
        launch._has_column("any_table", "any_column")


# ---------------------------------------------------------------------------
# _safe_json
# ---------------------------------------------------------------------------


def test_safe_json_serializes_normal_payload() -> None:
    assert launch._safe_json({"a": 1}) == '{"a": 1}'


def test_safe_json_returns_empty_object_on_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_value_error(*_a, **_k):
        raise ValueError("simulated dumps failure")

    monkeypatch.setattr(launch.json, "dumps", raise_value_error)

    assert launch._safe_json({"a": 1}) == "{}"


def test_safe_json_does_not_swallow_unexpected_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(launch.json, "dumps", explode)

    with pytest.raises(RuntimeError):
        launch._safe_json({"a": 1})


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------


def test_safe_int_converts_valid_value() -> None:
    assert launch._safe_int("7") == 7


def test_safe_int_returns_default_on_value_error() -> None:
    assert launch._safe_int("not-a-number", default=5) == 5


def test_safe_int_does_not_swallow_unexpected_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodesOnInt:
        def __int__(self):
            raise RuntimeError("unexpected programming failure")

    with pytest.raises(RuntimeError):
        launch._safe_int(ExplodesOnInt(), default=5)


# ---------------------------------------------------------------------------
# ensure_period_center_assignment_launch_schema (ALTER handler)
# ---------------------------------------------------------------------------


def test_ensure_schema_success_path_adds_missing_columns(provisioned_app) -> None:
    with provisioned_app.app_context():
        result = launch.ensure_period_center_assignment_launch_schema()

    assert result["ok"] is True
    assert result["rule_version"] == launch.RULE_VERSION


def test_ensure_schema_rolls_back_and_reraises_when_column_still_missing_after_sqlalchemy_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "ensure_category_period_integration_schema", lambda: None)
    monkeypatch.setattr(launch, "_dialect_name", lambda: "sqlite")
    monkeypatch.setattr(launch, "_has_column", lambda table, column: False)

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated ALTER failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(SQLAlchemyError):
        launch.ensure_period_center_assignment_launch_schema()

    # Rollback runs exactly once per attempted column, and the failure is
    # never swallowed into a fake success -- it propagates because the
    # column genuinely never got added.
    assert rollback_calls == [True]


def test_ensure_schema_rollback_failure_does_not_lose_original_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "ensure_category_period_integration_schema", lambda: None)
    monkeypatch.setattr(launch, "_dialect_name", lambda: "sqlite")
    monkeypatch.setattr(launch, "_has_column", lambda table, column: False)

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated ALTER failure")

    def raise_rollback():
        raise SQLAlchemyError("simulated rollback failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)
    monkeypatch.setattr(flask_db.session, "rollback", raise_rollback)

    with app.app_context(), pytest.raises(SQLAlchemyError) as excinfo:
        launch.ensure_period_center_assignment_launch_schema()

    # The rollback-failure exception itself propagates (this handler does not
    # wrap its own rollback() in a nested try) -- nothing is silently
    # swallowed and no fake success is returned either way.
    assert "rollback failure" in str(excinfo.value)


def test_ensure_schema_does_not_swallow_unexpected_runtime_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "ensure_category_period_integration_schema", lambda: None)
    monkeypatch.setattr(launch, "_dialect_name", lambda: "sqlite")
    monkeypatch.setattr(launch, "_has_column", lambda table, column: False)

    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "execute", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(RuntimeError):
        launch.ensure_period_center_assignment_launch_schema()

    assert rollback_calls == []


# ---------------------------------------------------------------------------
# _integration_for_plan
# ---------------------------------------------------------------------------


def test_integration_for_plan_returns_matching_item_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        launch,
        "list_integrations",
        lambda: [{"plan_key": "other"}, {"plan_key": "target", "period_id": 5}],
    )

    assert launch._integration_for_plan("target") == {"plan_key": "target", "period_id": 5}


def test_integration_for_plan_returns_none_and_rolls_back_on_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error():
        raise SQLAlchemyError("simulated list_integrations failure")

    monkeypatch.setattr(launch, "list_integrations", raise_error)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    result = launch._integration_for_plan("target")

    assert result is None
    assert rollback_calls == [True]


def test_integration_for_plan_rollback_failure_is_logged_and_result_stays_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error():
        raise SQLAlchemyError("simulated list_integrations failure")

    def raise_rollback():
        raise SQLAlchemyError("simulated rollback failure")

    monkeypatch.setattr(launch, "list_integrations", raise_error)
    monkeypatch.setattr(flask_db.session, "rollback", raise_rollback)

    log_calls: list[str] = []
    monkeypatch.setattr(
        launch.logger, "exception", lambda msg, *a, **k: log_calls.append(msg)
    )

    # The nested try/except SQLAlchemyError around rollback() swallows the
    # rollback failure (by design, matching the v2_1_9 precedent) -- but the
    # original failure is never faked into a success, and both failures are
    # logged.
    result = launch._integration_for_plan("target")

    assert result is None
    assert len(log_calls) == 2


def test_integration_for_plan_does_not_swallow_unexpected_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode():
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(launch, "list_integrations", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with pytest.raises(RuntimeError):
        launch._integration_for_plan("target")

    assert rollback_calls == []


# ---------------------------------------------------------------------------
# _period_for_integration
# ---------------------------------------------------------------------------


def test_period_for_integration_returns_period_on_success(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_period = object()
    monkeypatch.setattr(flask_db.session, "get", lambda model, pid: fake_period)

    with app.app_context():
        result = launch._period_for_integration({"period_id": 9})

    assert result is fake_period


def test_period_for_integration_returns_none_for_missing_or_empty_integration() -> None:
    assert launch._period_for_integration(None) is None
    assert launch._period_for_integration({"period_id": 0}) is None


def test_period_for_integration_returns_none_and_rolls_back_on_sqlalchemy_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_get(*_a, **_k):
        raise SQLAlchemyError("simulated get failure")

    monkeypatch.setattr(flask_db.session, "get", raise_get)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context():
        result = launch._period_for_integration({"period_id": 9})

    assert result is None
    assert rollback_calls == [True]


def test_period_for_integration_rollback_failure_still_returns_none_not_fake_period(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_get(*_a, **_k):
        raise SQLAlchemyError("simulated get failure")

    def raise_rollback():
        raise SQLAlchemyError("simulated rollback failure")

    monkeypatch.setattr(flask_db.session, "get", raise_get)
    monkeypatch.setattr(flask_db.session, "rollback", raise_rollback)

    with app.app_context():
        result = launch._period_for_integration({"period_id": 9})

    assert result is None


def test_period_for_integration_does_not_swallow_unexpected_runtime_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "get", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(RuntimeError):
        launch._period_for_integration({"period_id": 9})

    assert rollback_calls == []


# ---------------------------------------------------------------------------
# _precheck_count
# ---------------------------------------------------------------------------


def test_precheck_count_returns_real_value_on_success(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        flask_db.session, "execute", lambda *a, **k: _FakeScalarResult(4)
    )

    with app.app_context():
        assert launch._precheck_count("plan", 1) == 4


def test_precheck_count_returns_zero_and_rolls_back_on_sqlalchemy_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated count failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context():
        result = launch._precheck_count("plan", 1)

    assert result == 0
    assert rollback_calls == [True]


def test_precheck_count_rollback_failure_still_returns_zero_not_fake_count(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated count failure")

    def raise_rollback():
        raise SQLAlchemyError("simulated rollback failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)
    monkeypatch.setattr(flask_db.session, "rollback", raise_rollback)

    with app.app_context():
        result = launch._precheck_count("plan", 1)

    assert result == 0


def test_precheck_count_does_not_swallow_unexpected_runtime_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "execute", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(RuntimeError):
        launch._precheck_count("plan", 1)

    assert rollback_calls == []


# ---------------------------------------------------------------------------
# _precheck_status_counts
# ---------------------------------------------------------------------------


def test_precheck_status_counts_returns_real_counts_on_success(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        flask_db.session,
        "execute",
        lambda *a, **k: _FakeMappingsResult(
            [{"precheck_status": "ready", "total": 3}, {"precheck_status": "kontrol_gerekiyor", "total": 2}]
        ),
    )

    with app.app_context():
        result = launch._precheck_status_counts("plan", 1)

    assert result == {"ready": 3, "kontrol_gerekiyor": 2}


def test_precheck_status_counts_returns_empty_and_rolls_back_on_sqlalchemy_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated group-by failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context():
        result = launch._precheck_status_counts("plan", 1)

    assert result == {}
    assert rollback_calls == [True]


def test_precheck_status_counts_rollback_failure_still_returns_empty_not_fake_counts(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated group-by failure")

    def raise_rollback():
        raise SQLAlchemyError("simulated rollback failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)
    monkeypatch.setattr(flask_db.session, "rollback", raise_rollback)

    with app.app_context():
        result = launch._precheck_status_counts("plan", 1)

    assert result == {}


def test_precheck_status_counts_does_not_swallow_unexpected_runtime_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "execute", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(RuntimeError):
        launch._precheck_status_counts("plan", 1)

    assert rollback_calls == []
