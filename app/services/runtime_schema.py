"""Raw-SQL tables and indexes that request handlers use but must never create.

Some modules keep tables outside the ORM and Alembic. Request code only verifies
that those objects exist (read-only; a positive result is cached per database).
Creating a missing object is an explicit maintenance step:

    flask runtime-schema check       # read-only, exit code 1 if anything is missing
    flask runtime-schema provision   # creates missing objects

so a page view or API call never alters the schema.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass

import click
from flask import Flask
from flask.cli import AppGroup
from sqlalchemy import inspect

from app.extensions import db


class RuntimeSchemaMissing(RuntimeError):
    """A runtime schema group is not provisioned in the connected database."""

    def __init__(self, group: str, missing: list[str]):
        super().__init__(f"Runtime schema group '{group}' is not provisioned; missing: {', '.join(missing)}")
        self.group = group
        self.missing = missing


@dataclass(frozen=True)
class SchemaGroup:
    name: str
    tables: tuple[str, ...]
    indexes: tuple[tuple[str, str], ...] = ()
    columns: tuple[tuple[str, str], ...] = ()
    provision: Callable[[], object] | None = None


_GROUPS: dict[str, SchemaGroup] = {}
_verified: set[tuple[str, str]] = set()

# Every module that registers a group; the CLI imports them all so no group is skipped.
GROUP_MODULES = (
    "app.api.mobile.domains.push_notifications",
    "app.services.performance.v2_1_2_category_engine",
    "app.services.performance.v2_1_3_personnel_category_card",
    "app.services.performance.v2_1_4_category_scope_visibility",
    "app.services.performance.v2_1_5_category_period_scope",
    "app.services.performance.v2_1_6_category_period_integration",
    "app.services.performance.meeting_development",
    "app.services.performance.feedback_aftercare",
    "app.services.performance.feedback_followup_phase4",
    "app.performance.interim_notes_manager_routes",
    "app.performance.phase10_development_guidance_ui",
    "app.services.ai_agent.knowledge",
    "app.services.cic.cic_context",
)


def register(group: SchemaGroup) -> SchemaGroup:
    _GROUPS[group.name] = group
    return group


def registered_groups() -> list[SchemaGroup]:
    for module in GROUP_MODULES:
        importlib.import_module(module)
    return list(_GROUPS.values())


def missing_objects(group: SchemaGroup) -> list[str]:
    inspector = inspect(db.engine)
    present = {table for table in {*group.tables, *(t for t, _ in group.indexes), *(t for t, _ in group.columns)}
               if inspector.has_table(table)}
    missing = [table for table in group.tables if table not in present]
    for table, index in group.indexes:
        if table not in present or index not in {ix.get("name") for ix in inspector.get_indexes(table)}:
            missing.append(f"{table}.{index}")
    for table, column in group.columns:
        if table not in present or column not in {col["name"] for col in inspector.get_columns(table)}:
            missing.append(f"{table}.{column}")
    return missing


def require(group: SchemaGroup) -> None:
    """Raise RuntimeSchemaMissing unless every object of ``group`` exists. Never writes."""
    key = (str(db.engine.url), group.name)
    if key in _verified:
        return
    missing = missing_objects(group)
    if missing:
        raise RuntimeSchemaMissing(group.name, missing)
    _verified.add(key)


def forget_verified() -> None:
    """Drop cached positive checks (tests that recreate databases in one process)."""
    _verified.clear()


def provision_all() -> dict[str, tuple[list[str], list[str]]]:
    """Create missing objects of every group; returns {group: (missing before, missing after)}.

    Groups can depend on each other's tables, so passes repeat while they make progress.
    """
    before = {group.name: missing_objects(group) for group in registered_groups()}
    after = {name: list(missing) for name, missing in before.items()}
    for _ in range(len(_GROUPS)):
        progress = False
        for group in registered_groups():
            if after[group.name] and group.provision is not None:
                group.provision()
                db.session.commit()
                now = missing_objects(group)
                progress = progress or now != after[group.name]
                after[group.name] = now
        if not progress:
            break
    return {name: (before[name], after[name]) for name in before}


runtime_schema_cli = AppGroup("runtime-schema", help="Check or explicitly provision raw-SQL tables that are not owned by Alembic.")


@runtime_schema_cli.command("check")
def check_command() -> None:
    missing_total = 0
    for group in registered_groups():
        missing = missing_objects(group)
        missing_total += len(missing)
        click.echo(f"{group.name}: {'OK' if not missing else 'MISSING ' + ', '.join(missing)}")
    if missing_total:
        raise SystemExit(1)


@runtime_schema_cli.command("provision")
def provision_command() -> None:
    still_missing = 0
    for name, (before, after) in provision_all().items():
        if after:
            still_missing += len(after)
            click.echo(f"{name}: STILL MISSING {', '.join(after)}")
        else:
            click.echo(f"{name}: {'already present' if not before else 'provisioned ' + ', '.join(before)}")
    if still_missing:
        raise SystemExit(1)


def register_runtime_schema_cli(app: Flask) -> None:
    app.cli.add_command(runtime_schema_cli)
