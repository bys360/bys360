"""BYS360 schema reproducibility inventory (final pre-live audit P1-02 / P2-06).

Answers, for every ORM table, whether the documented install/restore procedure
(``flask db upgrade``) can reproduce it:

- MIGRATION_PRESENT        an Alembic revision creates the table
- RUNTIME_DDL_ONLY         only request/startup-time application DDL creates it
- NO_REPRODUCIBLE_SOURCE   neither; it exists only where historical
                           ``db.create_all()`` / repair scripts built it
                           (split into ACTIVE and CANDIDATE_DEAD by whether any
                           application module outside app/models references it)

Plus migration-only tables (no ORM model) and, for tables created by a
migration, ORM columns that no migration statement mentions (informational:
runtime ``ALTER TABLE`` or live history may still provide them).

Read-only and deterministic: static parsing of migrations/versions, app/ and
scripts/, plus the in-process ORM metadata of an app built on in-memory SQLite.
It never connects to a live or PostgreSQL database. The answer to "does the
live database match?" is a separate, read-only live validation step.

Usage:
    python scripts/quality/bys360_schema_reproducibility_inventory_v1.py [--write]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

INVENTORY_VERSION = "BYS360_SCHEMA_REPRODUCIBILITY_INVENTORY_V1"
REPORT_JSON = Path("reports/quality/BYS360_SCHEMA_REPRODUCIBILITY_INVENTORY_V1.json")
REPORT_MD = Path("reports/quality/BYS360_SCHEMA_REPRODUCIBILITY_INVENTORY_V1.md")

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_CREATE_TABLE_OP = re.compile(r"op\.create_table\(\s*['\"](" + _NAME + r")['\"]")
_CREATE_TABLE_SQL = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?(" + _NAME + r")", re.IGNORECASE)
_TABLE_CREATE_CALL = re.compile(r"\b(" + _NAME + r")\.__table__\.create\(")
_DROP_TABLE_OP = re.compile(r"op\.drop_table\(\s*['\"](" + _NAME + r")['\"]")
_ADD_COLUMN_OP = re.compile(
    r"op\.add_column\(\s*['\"](" + _NAME + r")['\"]\s*,\s*sa\.Column\(\s*['\"](" + _NAME + r")['\"]"
)
_BATCH_BLOCK = re.compile(r"batch_alter_table\(\s*['\"](" + _NAME + r")['\"]")
_BATCH_ADD = re.compile(r"batch_op\.add_column\(\s*sa\.Column\(\s*['\"](" + _NAME + r")['\"]")
_COLUMN_NAME = re.compile(r"sa\.Column\(\s*['\"](" + _NAME + r")['\"]")
_CREATE_TABLE_FSTRING = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\{(" + _NAME + r")\}", re.IGNORECASE)
_ALTER_ADD_SQL = re.compile(
    r"ALTER\s+TABLE\s+[\"`]?(" + _NAME + r")[\"`]?\s+ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?(" + _NAME + r")",
    re.IGNORECASE,
)
_SQL_KEYWORDS = {"IF", "NOT", "EXISTS", "TABLE", "COLUMN"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _py_files(root: Path, *parts: str) -> list[Path]:
    base = root.joinpath(*parts)
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts) if base.exists() else []


def _sql_tables(text: str) -> set[str]:
    """Tables named by CREATE TABLE literals, incl. f-strings over module constants."""
    names = {m.group(1) for m in _CREATE_TABLE_SQL.finditer(text) if m.group(1).upper() not in _SQL_KEYWORDS}
    for match in _CREATE_TABLE_FSTRING.finditer(text):
        constant = re.search(
            r"^\s*" + re.escape(match.group(1)) + r"\s*(?::[^=\n]+)?=\s*['\"](" + _NAME + r")['\"]", text, re.M
        )
        if constant:
            names.add(constant.group(1))
    return names


def _call_body(text: str, start: int) -> str:
    """Text of the parenthesised call starting at ``text[start] == '('``."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def _starred_columns(text: str, body: str) -> set[str]:
    """Column names from ``*helper()`` / ``*column_list`` splats inside a create_table call,
    resolved against a function or list/tuple defined in the same migration file."""
    names: set[str] = set()
    for star in re.finditer(r"\*\s*(" + _NAME + r")\b", body):
        symbol = star.group(1)
        func = re.search(r"^def\s+" + re.escape(symbol) + r"\s*\(", text, re.M)
        if func:
            body_start = text.find("\n", func.end()) + 1
            end = re.search(r"^\S", text[body_start:], re.M)
            names.update(_COLUMN_NAME.findall(text[func.start() : body_start + (end.start() if end else len(text))]))
            continue
        assign = re.search(r"^\s*" + re.escape(symbol) + r"\s*(?::[^=\n]+)?=\s*[\[(]", text, re.M)
        if assign:
            names.update(_COLUMN_NAME.findall(_call_body(text.replace("[", "(").replace("]", ")"), assign.end() - 1)))
    return names


def collect_orm_metadata() -> dict[str, dict[str, Any]]:
    """ORM tables of the fully registered app (every blueprint/module imported)."""
    os.environ.setdefault("APP_ENV", "testing")
    os.environ.setdefault("FLASK_ENV", "testing")
    os.environ.setdefault("SECRET_KEY", "schema-inventory-only-not-a-real-secret-key-0000")
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    os.environ.setdefault("SCHEDULER_ENABLED", "false")
    os.environ.setdefault("MAIL_SUPPRESS_SEND", "true")
    from app import create_app
    from app.extensions import db

    create_app()
    classes: dict[str, list[str]] = {}
    for mapper in db.Model.registry.mappers:  # type: ignore[attr-defined]
        table = getattr(mapper, "local_table", None)
        if table is not None:
            classes.setdefault(table.name, []).append(mapper.class_.__name__)
    return {
        name: {"columns": sorted(col.name for col in table.columns), "model_classes": sorted(classes.get(name, []))}
        for name, table in sorted(db.metadata.tables.items())
    }


def collect_migration_ddl(root: Path) -> dict[str, Any]:
    created: dict[str, set[str]] = {}
    dropped: dict[str, set[str]] = {}
    create_columns: dict[str, set[str]] = {}
    added_columns: dict[str, set[str]] = {}
    for path in _py_files(root, "migrations", "versions"):
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        for match in _CREATE_TABLE_OP.finditer(text):
            name = match.group(1)
            created.setdefault(name, set()).add(rel)
            body = _call_body(text, text.index("(", match.start()))
            create_columns.setdefault(name, set()).update(_COLUMN_NAME.findall(body) + sorted(_starred_columns(text, body)))
        for name in _sql_tables(text):
            created.setdefault(name, set()).add(rel)
        for table, column in _ALTER_ADD_SQL.findall(text):
            added_columns.setdefault(table, set()).add(column)
        for match in _DROP_TABLE_OP.finditer(text):
            dropped.setdefault(match.group(1), set()).add(rel)
        for table, column in _ADD_COLUMN_OP.findall(text):
            added_columns.setdefault(table, set()).add(column)
        for block in _BATCH_BLOCK.finditer(text):
            window = text[block.end() : block.end() + 4000]
            next_block = _BATCH_BLOCK.search(window)
            window = window[: next_block.start()] if next_block else window
            added_columns.setdefault(block.group(1), set()).update(_BATCH_ADD.findall(window))
        # Loose association for conditional helpers / loops / table-name constants
        # (e.g. _add_column_if_missing(bind, table_name, sa.Column(...))): a column
        # counts as mentioned when the same migration file names the table.
        mentioned_tables = set(re.findall(r"['\"](" + _NAME + r")['\"]", text))
        file_columns = set(_COLUMN_NAME.findall(text))
        for table in mentioned_tables:
            added_columns.setdefault(table, set()).update(file_columns)
    return {"created": created, "dropped": dropped, "create_columns": create_columns, "added_columns": added_columns}


def collect_code_ddl(root: Path, parts: Iterable[str], class_to_table: dict[str, str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for part in parts:
        for path in _py_files(root, part):
            rel = path.relative_to(root).as_posix()
            text = _read(path)
            for name in _sql_tables(text):
                found.setdefault(name, set()).add(rel)
            for match in _TABLE_CREATE_CALL.finditer(text):
                table = class_to_table.get(match.group(1))
                if table:
                    found.setdefault(table, set()).add(rel)
    return found


def collect_code_alters(root: Path, parts: Iterable[str]) -> dict[str, set[str]]:
    """Columns added by ``ALTER TABLE ... ADD COLUMN`` literals in application code."""
    found: dict[str, set[str]] = {}
    for part in parts:
        for path in _py_files(root, part):
            for table, column in _ALTER_ADD_SQL.findall(_read(path)):
                if column.upper() not in _SQL_KEYWORDS:
                    found.setdefault(table, set()).add(column)
    return found


def collect_references(root: Path, orm: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Application modules outside app/models that mention the table or its model class."""
    token_sets = [
        set(re.findall(r"\w+", _read(path)))
        for path in _py_files(root, "app")
        if "models" not in path.relative_to(root).parts[:2]
    ]
    counts: dict[str, int] = {}
    for table, info in orm.items():
        needles = {table, *info["model_classes"]}
        counts[table] = sum(1 for tokens in token_sets if needles & tokens)
    return counts


def build_inventory(root: Path) -> dict[str, Any]:
    orm = collect_orm_metadata()
    class_to_table = {cls: table for table, info in orm.items() for cls in info["model_classes"]}
    migrations = collect_migration_ddl(root)
    runtime_ddl = collect_code_ddl(root, ["app"], class_to_table)
    runtime_alters = collect_code_alters(root, ["app"])
    script_ddl = collect_code_ddl(root, ["scripts"], class_to_table)
    references = collect_references(root, orm)

    tables: list[dict[str, Any]] = []
    for table, info in orm.items():
        in_migrations = table in migrations["created"]
        in_runtime = table in runtime_ddl
        if in_migrations:
            status = "MIGRATION_PRESENT"
        elif in_runtime:
            status = "RUNTIME_DDL_ONLY"
        elif references[table] == 0:
            status = "NO_REPRODUCIBLE_SOURCE_CANDIDATE_DEAD"
        else:
            status = "NO_REPRODUCIBLE_SOURCE_ACTIVE"
        migration_columns = migrations["create_columns"].get(table, set()) | migrations["added_columns"].get(table, set())
        column_gaps = sorted(set(info["columns"]) - migration_columns) if table in migrations["create_columns"] else []
        tables.append({
            "table": table,
            "model_classes": info["model_classes"],
            "status": status,
            "migration_files": sorted(migrations["created"].get(table, set())),
            "runtime_ddl_files": sorted(runtime_ddl.get(table, set())),
            "script_ddl_files": sorted(script_ddl.get(table, set())),
            "app_reference_files": references[table],
            "orm_columns_not_in_migrations": column_gaps,
            "orm_columns_without_any_ddl": sorted(set(column_gaps) - runtime_alters.get(table, set())),
            "live_validation_required": status != "MIGRATION_PRESENT" or bool(column_gaps),
        })

    summary: dict[str, int] = {}
    for row in tables:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    return {
        "inventory": INVENTORY_VERSION,
        "orm_table_count": len(orm),
        "summary": dict(sorted(summary.items())),
        "no_migration_tables": sorted(r["table"] for r in tables if r["status"] != "MIGRATION_PRESENT"),
        "migration_only_tables": sorted(set(migrations["created"]) - set(orm) - set(migrations["dropped"])),
        "tables_with_orm_columns_not_in_migrations": sorted(r["table"] for r in tables if r["orm_columns_not_in_migrations"]),
        "tables_with_orm_columns_without_any_ddl": sorted(r["table"] for r in tables if r["orm_columns_without_any_ddl"]),
        "tables": tables,
    }


def render_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# BYS360 Schema Reproducibility Inventory V1",
        "",
        "Generated by `scripts/quality/bys360_schema_reproducibility_inventory_v1.py` (read-only, no live database).",
        "",
        f"ORM tables: **{inventory['orm_table_count']}**",
        "",
        "| Status | Tables |",
        "|---|---:|",
    ]
    lines += [f"| {status} | {count} |" for status, count in inventory["summary"].items()]
    lines += ["", "## ORM tables without an Alembic migration", "", "| Table | Status | Runtime DDL | Script DDL | App refs |", "|---|---|---|---|---:|"]
    for row in inventory["tables"]:
        if row["status"] == "MIGRATION_PRESENT":
            continue
        lines.append(
            f"| `{row['table']}` | {row['status']} | {', '.join(row['runtime_ddl_files']) or '-'} | "
            f"{', '.join(row['script_ddl_files']) or '-'} | {row['app_reference_files']} |"
        )
    lines += [
        "",
        "## Migration-created tables whose ORM columns no migration mentions",
        "",
        "Columns in *italics* are added only by runtime `ALTER TABLE` in application code; the rest have no DDL",
        "in the repository at all. Both need read-only live validation before any adoption migration.",
        "",
    ]
    for row in inventory["tables"]:
        if row["orm_columns_not_in_migrations"]:
            no_ddl = set(row["orm_columns_without_any_ddl"])
            rendered = [f"`{c}`" if c in no_ddl else f"*{c}*" for c in row["orm_columns_not_in_migrations"]]
            lines.append(f"- `{row['table']}`: {', '.join(rendered)}")
    lines += ["", "## Migration-only tables (no ORM model)", ""]
    lines += [f"- `{name}`" for name in inventory["migration_only_tables"]] or ["- none"]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the JSON and Markdown reports")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    inventory = build_inventory(root)
    if args.write:
        (root / REPORT_JSON).write_text(json.dumps(inventory, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (root / REPORT_MD).write_text(render_markdown(inventory), encoding="utf-8")
    print(json.dumps({"orm_table_count": inventory["orm_table_count"], "summary": inventory["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
