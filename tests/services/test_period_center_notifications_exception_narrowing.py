from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db as flask_db
from app.services.performance import (
    v2_1_9_period_center_process_notifications as notifications,
)

# BYS360 Phase 5 exception-debt wave 4: targeted coverage for the 12
# `except Exception` -> narrow-type conversions in
# app/services/performance/v2_1_9_period_center_process_notifications.py.
# Groups covered:
#  A) pure Python parsing (_safe_json, _parse_json, _safe_int, _safe_percent)
#  B) Flask-SQLAlchemy engine/inspector access outside app context
#     (_dialect_name, _has_table, _columns)
#  C) SQLAlchemy query + rollback (_period_summary,
#     _assignment_status_counts) and the ALTER COLUMN re-raise handler
#     inside ensure_period_center_process_notification_schema.


class _Unstringable:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __str__(self) -> str:
        raise self._exc


class _ExplodesOnInt:
    def __bool__(self) -> bool:
        return True

    def __int__(self) -> int:
        raise RuntimeError("boom - not a value/type error")


# ---------------------------------------------------------------------------
# Group A: pure Python parsing contracts
# ---------------------------------------------------------------------------


def test_safe_json_handles_unstringable_value_via_default_str() -> None:
    result = notifications._safe_json({"x": _Unstringable(ValueError("cannot stringify"))})
    assert result == "{}"


def test_safe_json_does_not_swallow_unexpected_runtime_error() -> None:
    with pytest.raises(RuntimeError):
        notifications._safe_json({"x": _Unstringable(RuntimeError("boom"))})


def test_parse_json_returns_none_for_malformed_json() -> None:
    assert notifications._parse_json("{not valid json") is None
    assert notifications._parse_json(None) is None
    assert notifications._parse_json({"already": "a dict"}) == {"already": "a dict"}


def test_safe_int_returns_default_for_invalid_string() -> None:
    assert notifications._safe_int("not-a-number", default=5) == 5
    assert notifications._safe_int("7") == 7


def test_safe_int_does_not_swallow_unexpected_runtime_error() -> None:
    with pytest.raises(RuntimeError):
        notifications._safe_int(_ExplodesOnInt())


def test_safe_percent_handles_non_numeric_done_gracefully() -> None:
    assert notifications._safe_percent("bad", 10) == 0  # type: ignore[arg-type]
    assert notifications._safe_percent(5, 10) == 50


# ---------------------------------------------------------------------------
# Group B: engine/inspector access -- real RuntimeError outside app context
# ---------------------------------------------------------------------------


def test_dialect_name_returns_unknown_outside_app_context() -> None:
    # No app.app_context() active here: this reproduces the real,
    # unmocked RuntimeError Flask-SQLAlchemy raises for `db.engine`
    # access outside an application context.
    assert notifications._dialect_name() == "unknown"


def test_has_table_returns_false_outside_app_context() -> None:
    assert notifications._has_table("performance_periods") is False


def test_columns_returns_empty_set_outside_app_context() -> None:
    assert notifications._columns("performance_periods") == set()


def test_dialect_name_resolves_real_value_inside_app_context(app) -> None:
    with app.app_context():
        assert notifications._dialect_name() in {"sqlite", "postgresql"}


# ---------------------------------------------------------------------------
# Group C: SQLAlchemy query + rollback, and ALTER COLUMN re-raise handler
# ---------------------------------------------------------------------------


def test_period_summary_rolls_back_and_returns_not_found_on_sqlalchemy_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_columns", lambda name: {"id", "title"})

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated select failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    log_calls: list[str] = []
    monkeypatch.setattr(
        notifications.logger, "exception", lambda msg, *a, **k: log_calls.append(msg)
    )

    with app.app_context():
        result = notifications._period_summary(1)

    # Expected failure is handled: safe "not found" payload, never a fake
    # success (result["ok"] must be False).
    assert result == {
        "ok": False,
        "period_id": 1,
        "title": "-",
        "message": "Bağlı performans dönemi bulunamadı.",
    }
    assert rollback_calls == [True]
    assert len(log_calls) >= 1


def test_period_summary_does_not_swallow_unexpected_runtime_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_columns", lambda name: {"id", "title"})

    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "execute", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(RuntimeError):
        notifications._period_summary(1)

    # The narrow `except SQLAlchemyError` must not catch this, and must not
    # perform a rollback that belongs to a different failure class.
    assert rollback_calls == []


def test_assignment_status_counts_rolls_back_and_returns_empty_on_sqlalchemy_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated aggregate failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context():
        result = notifications._assignment_status_counts(1)

    assert result == {}
    assert rollback_calls == [True]


def test_provision_schema_alter_column_reraises_when_column_still_missing(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications, "provision_category_period_integration_schema", lambda: None)
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: False)
    monkeypatch.setattr(notifications, "_dialect_name", lambda: "sqlite")

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated alter failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(SQLAlchemyError):
        notifications.provision_period_center_process_notification_schema()

    # Rollback must still run before the pre-existing re-raise-if-still-missing
    # behavior fires -- this is existing behavior, unchanged by the narrowing.
    assert rollback_calls
