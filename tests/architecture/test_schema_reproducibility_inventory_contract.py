"""P1-02 / P2-06 contract: model-vs-migration coverage cannot drift silently.

Final pre-live audit (2026-09-27): the documented install/restore procedure is
``flask db upgrade``, but some active ORM tables are created by no Alembic
revision (only by historical ``db.create_all()`` / repair runs) or only by
request-time DDL, and ``performance_low_score_process_events`` is created by a
migration with a different shape than its model. Migration w2d8e1f4a6c3 closes
those gaps, and the PostgreSQL migration gate in CI now also fails when an ORM
table or column is missing after empty -> head; the test suite still builds its
schema with ``db.create_all()``.

This contract recomputes the read-only inventory
(scripts/quality/bys360_schema_reproducibility_inventory_v1.py) and compares it
with the committed baseline report. It fails when:
- a new ORM table appears without an Alembic migration, or a listed table gets
  one (regenerate the report with ``--write`` so the known gap shrinks
  explicitly);
- a new table gets ORM columns that no DDL in the repository creates.

No live or PostgreSQL database is touched. Whether the live database matches
is a separate read-only validation (docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "reports" / "quality" / "BYS360_SCHEMA_REPRODUCIBILITY_INVENTORY_V1.json"


@pytest.fixture(scope="module")
def current() -> dict:
    sys.path.insert(0, str(ROOT / "scripts" / "quality"))
    try:
        from bys360_schema_reproducibility_inventory_v1 import build_inventory
    finally:
        sys.path.remove(str(ROOT / "scripts" / "quality"))
    return build_inventory(ROOT)


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_no_new_orm_table_without_an_alembic_migration(current, baseline) -> None:
    new = sorted(set(current["no_migration_tables"]) - set(baseline["no_migration_tables"]))
    assert new == [], f"ORM tables without an Alembic migration (add a migration): {new}"


def test_known_gap_shrinks_only_explicitly(current, baseline) -> None:
    fixed = sorted(set(baseline["no_migration_tables"]) - set(current["no_migration_tables"]))
    assert fixed == [], (
        f"these tables now have a migration; regenerate the baseline with "
        f"`python scripts/quality/bys360_schema_reproducibility_inventory_v1.py --write`: {fixed}"
    )


def test_no_new_table_with_orm_columns_that_no_ddl_creates(current, baseline) -> None:
    new = sorted(
        set(current["tables_with_orm_columns_without_any_ddl"]) - set(baseline["tables_with_orm_columns_without_any_ddl"])
    )
    assert new == [], f"ORM columns created by no migration or runtime DDL: {new}"


def test_low_score_events_orm_columns_have_ddl(baseline) -> None:
    """w2d8e1f4a6c3 adopts the ORM shape of an empty phase-6 events table (the PG gate checks ORM parity)."""
    rows = {row["table"]: row for row in baseline["tables"]}
    events = rows["performance_low_score_process_events"]
    assert events["status"] == "MIGRATION_PRESENT"
    assert events["orm_columns_without_any_ddl"] == []


def test_baseline_report_is_internally_consistent(baseline) -> None:
    statuses = [row["status"] for row in baseline["tables"]]
    assert baseline["orm_table_count"] == len(baseline["tables"])
    assert sum(baseline["summary"].values()) == len(statuses)
    assert sorted(r["table"] for r in baseline["tables"] if r["status"] != "MIGRATION_PRESENT") == baseline["no_migration_tables"]
