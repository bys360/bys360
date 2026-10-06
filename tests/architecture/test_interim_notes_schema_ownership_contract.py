"""performance_interim_notes has exactly one schema owner: Alembic revision x1f3a9c5e7b2.

Static guards so request-time ownership cannot come back under another helper name:
no runtime-schema group owns the table, no application code carries DDL that targets
it (by literal name or through the helpers' table-name constants), and exactly one
migration creates it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE = "performance_interim_notes"
OWNER_REVISION = (
    ROOT
    / "migrations"
    / "versions"
    / "x1f3a9c5e7b2_adopt_performance_interim_notes_into_alembic.py"
)
# Former request-time creators and the constants they used for the table name.
FORMER_CREATORS = {
    "app/services/performance/interim_notes_runtime.py": "TABLE_NAME",
    "app/services/performance/meeting_p2_archive_notes.py": "P2_INTERIM_NOTES_TABLE",
    "app/api/mobile/performance_routes.py": None,
    "app/api/mobile/services/performance_note_route_services.py": None,
}
LITERAL_DDL = re.compile(
    rf"(CREATE\s+TABLE(\s+IF\s+NOT\s+EXISTS)?\s+{TABLE}\b(?!_)"
    rf"|ALTER\s+TABLE\s+{TABLE}\b(?!_)"
    rf"|CREATE\s+(UNIQUE\s+)?INDEX\b[^\n]*\bON\s+{TABLE}\b(?!_))",
    re.I,
)


def _app_sources() -> list[Path]:
    return sorted((ROOT / "app").rglob("*.py"))


def test_runtime_schema_does_not_own_performance_interim_notes() -> None:
    from app.services import runtime_schema

    for group in runtime_schema.registered_groups():
        owned = {*group.tables, *(t for t, _ in group.indexes), *(t for t, _ in group.columns)}
        assert TABLE not in owned, f"runtime-schema group {group.name!r} claims {TABLE}"


def test_no_application_code_carries_ddl_for_performance_interim_notes() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{text[: match.start()].count(chr(10)) + 1}"
        for path in _app_sources()
        for text in [path.read_text(encoding="utf-8")]
        for match in LITERAL_DDL.finditer(text)
    ]
    assert offenders == []


def test_former_creators_carry_no_ddl_through_their_table_name_constants() -> None:
    for rel, constant in FORMER_CREATORS.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        if constant:
            pattern = re.compile(
                rf"(CREATE\s+TABLE[^\n]*\{{{constant}\}}|ALTER\s+TABLE[^\n]*\{{{constant}\}}|ON\s+\{{{constant}\}})",
                re.I,
            )
            assert not pattern.search(text), f"{rel} builds DDL from {constant}"
    runtime = "\n".join(
        line
        for line in (ROOT / "app/services/performance/interim_notes_runtime.py")
        .read_text(encoding="utf-8")
        .splitlines()
        if not line.lstrip().startswith("#")
    )
    # The generic "ALTER TABLE {table_name} ADD COLUMN" retrofit helper is gone, not renamed.
    assert not re.search(r"ALTER\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX|CREATE\s+TABLE", runtime, re.I)


def test_exactly_one_migration_creates_the_table_and_it_is_the_owner_revision() -> None:
    creators = [
        path.name
        for path in sorted((ROOT / "migrations" / "versions").glob("*.py"))
        if re.search(
            rf"create_table\(\s*(TABLE_NAME|['\"]{TABLE}['\"])", path.read_text(encoding="utf-8")
        )
        and TABLE in path.read_text(encoding="utf-8")
    ]
    assert creators == [OWNER_REVISION.name]


def test_runtime_readiness_check_matches_the_migration_contract() -> None:
    import importlib.util

    from app.services.performance import interim_notes_runtime

    spec = importlib.util.spec_from_file_location("x1f3a9c5e7b2_contract", OWNER_REVISION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert interim_notes_runtime.TABLE_NAME == module.TABLE_NAME == TABLE
    assert {name for name, *_ in module.CANONICAL_COLUMNS} == interim_notes_runtime.REQUIRED_COLUMNS
    assert tuple(interim_notes_runtime.INDEXES) == tuple(
        name for name, _ in module.CANONICAL_INDEXES
    )
