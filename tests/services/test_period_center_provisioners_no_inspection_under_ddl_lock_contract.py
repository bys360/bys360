"""Contract: the period-center column provisioners never inspect the table while their DDL is uncommitted.

On PostgreSQL, ALTER TABLE through the session holds an ACCESS EXCLUSIVE lock until
commit, and _has_column() inspects through another pooled connection: inspecting after
the first ALTER waited on that lock forever (observed with `flask runtime-schema
provision` on PostgreSQL 15). SQLite has no such lock, so the ordering is asserted here.
"""
from __future__ import annotations

import pytest

from app.extensions import db as flask_db
from app.services.performance import (
    v2_1_8_period_center_assignment_launch as launch,
    v2_1_9_period_center_process_notifications as notifications,
)

PROVISIONERS = (
    (launch, "provision_period_center_assignment_launch_schema"),
    (notifications, "provision_period_center_process_notification_schema"),
)


@pytest.mark.parametrize("module, provisioner", PROVISIONERS)
def test_columns_are_inspected_before_any_alter(app, monkeypatch, module, provisioner):
    events: list[str] = []
    monkeypatch.setattr(module, "provision_category_period_integration_schema", lambda: None)
    monkeypatch.setattr(module, "_dialect_name", lambda: "postgresql")
    if hasattr(module, "_has_table"):
        monkeypatch.setattr(module, "_has_table", lambda name: True)

    def has_column(table, column):
        events.append("inspect")
        return False

    def execute(statement, *args, **kwargs):
        events.append("ddl")

    monkeypatch.setattr(module, "_has_column", has_column)
    monkeypatch.setattr(flask_db.session, "execute", execute)
    monkeypatch.setattr(flask_db.session, "commit", lambda: events.append("commit"))

    with app.app_context():
        getattr(module, provisioner)()

    first_ddl = events.index("ddl")
    assert "inspect" not in events[first_ddl:events.index("commit")], events
    assert events.count("ddl") == 4
