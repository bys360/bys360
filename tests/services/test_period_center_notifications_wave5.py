from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db as flask_db
from app.services.performance import (
    v2_1_9_period_center_process_notifications as notifications,
)

# BYS360 Phase 5 exception-debt wave 5: closes the 10 remaining broad
# `except Exception` handlers in
# app/services/performance/v2_1_9_period_center_process_notifications.py:
#   _integration_for_plan (outer + nested rollback)
#   ensure_period_center_process_notification_schema (outer + nested rollback)
#   _assignment_scalar (outer + nested rollback)
#   _assignment_count_where (outer + nested rollback)
#   _recent_mail_count (outer + nested rollback)
#
# All ten were narrowed to `except SQLAlchemyError` (not `(SQLAlchemyError,
# RuntimeError)`), matching the file's own precedent already established in
# wave 4 for the structurally identical `_period_summary` /
# `_assignment_status_counts` query functions. RuntimeError -- including the
# real "Working outside of application context" case -- is deliberately left
# uncaught here: these functions always run inside a real Flask request
# context in production (the only caller chain is the period-management
# routes), and several of them sit behind multi-module schema-bootstrap call
# chains (list_integrations -> ensure_category_period_integration_schema ->
# ensure_category_period_scope_schema -> four more ensure_*/seed_* modules)
# that were not individually audited line-by-line -- so a bare `RuntimeError`
# catch here could just as easily swallow an unrelated programming bug
# (e.g. a RecursionError, which subclasses RuntimeError) as a genuine
# context-absence condition, and the two are not distinguishable without
# fragile message inspection. Per this file's own established pattern
# (introspection helpers _dialect_name/_has_table/_columns tolerate
# context-absence because their *entire* body is one simple attribute/
# inspector call; these five do not), the safer, evidence-consistent choice
# is to let RuntimeError propagate untouched.


class _FakeScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar(self):
        return self._value


# ---------------------------------------------------------------------------
# _integration_for_plan
# ---------------------------------------------------------------------------


def test_integration_for_plan_returns_matching_item_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notifications,
        "list_integrations",
        lambda: [{"plan_key": "other"}, {"plan_key": "target", "period_id": 5}],
    )

    result = notifications._integration_for_plan("target")

    assert result == {"plan_key": "target", "period_id": 5}


def test_integration_for_plan_returns_none_and_rolls_back_on_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error():
        raise SQLAlchemyError("simulated list_integrations failure")

    monkeypatch.setattr(notifications, "list_integrations", raise_error)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    log_calls: list[str] = []
    monkeypatch.setattr(
        notifications.logger, "exception", lambda msg, *a, **k: log_calls.append(msg)
    )

    result = notifications._integration_for_plan("target")

    # Fake success is impossible: on failure the result is None, never a
    # fabricated integration dict.
    assert result is None
    assert rollback_calls == [True]
    assert len(log_calls) == 1


def test_integration_for_plan_does_not_swallow_unexpected_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode():
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(notifications, "list_integrations", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with pytest.raises(RuntimeError):
        notifications._integration_for_plan("target")

    # RuntimeError propagates before the except block runs -- no rollback.
    assert rollback_calls == []


# ---------------------------------------------------------------------------
# provision_period_center_process_notification_schema (maintenance only)
# ---------------------------------------------------------------------------


def test_provision_schema_success_path_unchanged(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications, "provision_category_period_integration_schema", lambda: None)
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)
    monkeypatch.setattr(notifications, "_dialect_name", lambda: "sqlite")

    commit_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "commit", lambda: commit_calls.append(True))

    with app.app_context():
        result = notifications.provision_period_center_process_notification_schema()

    assert result == {
        "ok": True,
        "added_columns": [],
        "dialect": "sqlite",
        "rule_version": notifications.RULE_VERSION,
    }
    assert commit_calls == [True]


def test_provision_schema_dependency_failure_rolls_back_and_reports_missing_table(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_error():
        raise SQLAlchemyError("simulated dependency schema failure")

    monkeypatch.setattr(notifications, "provision_category_period_integration_schema", raise_error)
    # The dependency schema genuinely failed, so the integration table is
    # still absent -- this must be reported as ok:False, never a fake success.
    monkeypatch.setattr(notifications, "_has_table", lambda name: False)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    log_calls: list[str] = []
    monkeypatch.setattr(
        notifications.logger, "exception", lambda msg, *a, **k: log_calls.append(msg)
    )

    with app.app_context():
        result = notifications.provision_period_center_process_notification_schema()

    assert result["ok"] is False
    assert result["message"] == "Dönem entegrasyon tablosu bulunamadı."
    assert rollback_calls == [True]
    assert len(log_calls) == 1


def test_provision_schema_does_not_swallow_unexpected_runtime_error(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode():
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(notifications, "provision_category_period_integration_schema", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with app.app_context(), pytest.raises(RuntimeError):
        notifications.provision_period_center_process_notification_schema()

    assert rollback_calls == []


# ---------------------------------------------------------------------------
# _assignment_scalar
# ---------------------------------------------------------------------------


def test_assignment_scalar_returns_real_value_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)
    monkeypatch.setattr(
        flask_db.session, "execute", lambda *a, **k: _FakeScalarResult(7)
    )

    assert notifications._assignment_scalar(1, "COUNT(DISTINCT evaluator_id)") == 7


def test_assignment_scalar_returns_fallback_and_rolls_back_on_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated scalar failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    # fallback is caller-provided and must be returned verbatim -- never an
    # invented nonzero value.
    result = notifications._assignment_scalar(1, "COUNT(DISTINCT evaluator_id)", fallback=99)

    assert result == 99
    assert rollback_calls == [True]


def test_assignment_scalar_does_not_swallow_unexpected_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)

    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "execute", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with pytest.raises(RuntimeError):
        notifications._assignment_scalar(1, "COUNT(DISTINCT evaluator_id)")

    assert rollback_calls == []


# ---------------------------------------------------------------------------
# _assignment_count_where
# ---------------------------------------------------------------------------


def test_assignment_count_where_returns_real_value_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)
    monkeypatch.setattr(
        flask_db.session, "execute", lambda *a, **k: _FakeScalarResult(3)
    )

    assert notifications._assignment_count_where(1, "completed_at IS NOT NULL") == 3


def test_assignment_count_where_returns_zero_and_rolls_back_on_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated count failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    result = notifications._assignment_count_where(1, "completed_at IS NOT NULL")

    # No fake positive count -- the documented safe fallback is exactly 0.
    assert result == 0
    assert rollback_calls == [True]


def test_assignment_count_where_does_not_swallow_unexpected_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_has_column", lambda table, column: True)

    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "execute", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with pytest.raises(RuntimeError):
        notifications._assignment_count_where(1, "completed_at IS NOT NULL")

    assert rollback_calls == []


# ---------------------------------------------------------------------------
# _recent_mail_count
# ---------------------------------------------------------------------------


def test_recent_mail_count_returns_real_value_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_columns", lambda name: {"period_id"})
    monkeypatch.setattr(
        flask_db.session, "execute", lambda *a, **k: _FakeScalarResult(4)
    )

    assert notifications._recent_mail_count(1) == 4


def test_recent_mail_count_returns_zero_and_rolls_back_on_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_columns", lambda name: {"period_id"})

    def raise_execute(*_a, **_k):
        raise SQLAlchemyError("simulated mail count failure")

    monkeypatch.setattr(flask_db.session, "execute", raise_execute)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    result = notifications._recent_mail_count(1)

    # A genuine query failure must not be reported as "0 mail" success --
    # it returns the same safe sentinel as the "no mail_logs table" case,
    # but rollback proves the failure path (not the happy path) executed.
    assert result == 0
    assert rollback_calls == [True]


def test_recent_mail_count_does_not_swallow_unexpected_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "_has_table", lambda name: True)
    monkeypatch.setattr(notifications, "_columns", lambda name: {"period_id"})

    def explode(*_a, **_k):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(flask_db.session, "execute", explode)

    rollback_calls: list[bool] = []
    monkeypatch.setattr(flask_db.session, "rollback", lambda: rollback_calls.append(True))

    with pytest.raises(RuntimeError):
        notifications._recent_mail_count(1)

    assert rollback_calls == []
