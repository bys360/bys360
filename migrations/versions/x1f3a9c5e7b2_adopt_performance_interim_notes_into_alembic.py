"""Adopt performance_interim_notes into Alembic ownership.

Revision ID: x1f3a9c5e7b2
Revises: w2d8e1f4a6c3
Create Date: 2026-10-06

``performance_interim_notes`` had no migration, no ORM model and no runtime-schema
group: a fresh ``flask db upgrade`` + ``flask runtime-schema provision`` left it
absent, and ordinary requests created or patched it. Four request-time helpers
did so, each leaving its own shape behind:

- RUNTIME: ``app/services/performance/interim_notes_runtime.py``
  ``ensure_interim_notes_table()`` CREATE TABLE (26 columns, ``visibility_level``
  NOT NULL) plus two indexes, and an ALTER TABLE retrofit of any missing column
  (retrofitted ``visibility_level`` is nullable);
- MOBILE: the fallback CREATE TABLE in ``app/api/mobile/performance_routes.py``
  (18 columns, no indexes);
- MEETING_P2: ``app/services/performance/meeting_p2_archive_notes.py`` (12 columns,
  ``employee_user_id`` / ``note_body`` NOT NULL, ``note_type`` without default).
  Its ``BOOLEAN DEFAULT 1`` is rejected by PostgreSQL, so this shape can only exist
  on SQLite;
- the mobile note-scorecard retrofit of six columns with the same definitions.

Revision ``d1a0e5c7b934`` additionally adds ``development_guidance_id`` and
``converted_to_guidance`` when the table already existed; no code uses them.

HISTORICAL_PRODUCTION_30_VARIANT is the exact PostgreSQL catalog signature
reported by the failed shadow rehearsal. It retains an older, stricter base,
assignment/evaluation links and historical indexes, plus additive runtime and
d1a0 columns. Adoption is strictly read-only: all 30 columns and 13 indexes
(including the primary-key index) must match, and no DDL or data rewrite occurs.
The mobile writer validates the reflected note_type length before inserting.

Canonical contract: the RUNTIME shape -- the one the current code creates on an
empty database -- as the CREATE TABLE definition gives it (the ALTER retrofit's
nullable ``visibility_level`` is accepted on adopted tables, never converted).
Every column is read or written by a live request path. Columns that only an
inactive AI decision query names (``personnel_id``, ``evaluation_id``, ``category``,
``summary``) are deliberately not added to the canonical table. The historical
production table already has evaluation_id, which is preserved; the other
missing AI-query columns are never synthesized. Adding
them would let that query return every note of a period to its caller.

Upgrade:

- table absent: create the canonical table and its two indexes;
- a recognised legacy shape: add only the missing canonical columns (nullable;
  constant defaults are the helpers' own; timestamps get no backfill, so no
  historical time is invented) and the missing canonical indexes. Nothing is
  dropped, renamed, narrowed or made NOT NULL; legacy extra columns stay;
- any other structure: raise ``InterimNotesSchemaNotRecognized`` before any change.
  On PostgreSQL the whole upgrade transaction is rolled back.

Downgrade is a no-op: the table holds institutional data.
"""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op

revision = "x1f3a9c5e7b2"
down_revision = "w2d8e1f4a6c3"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

TABLE_NAME = "performance_interim_notes"

# (name, type family, varchar length, nullable on a fresh install, server default token)
CANONICAL_COLUMNS: tuple[tuple[str, str, int | None, bool, str | None], ...] = (
    ("id", "integer", None, False, None),
    ("period_id", "integer", None, True, None),
    ("employee_id", "integer", None, True, None),
    ("employee_user_id", "integer", None, True, None),
    ("manager_id", "integer", None, True, None),
    ("created_by", "integer", None, True, None),
    ("created_by_id", "integer", None, True, None),
    ("note_type", "varchar", 80, False, "genel_gozlem"),
    ("title", "varchar", 255, True, None),
    ("note_title", "varchar", 255, True, None),
    ("note", "text", None, True, None),
    ("note_body", "text", None, True, None),
    ("note_text", "text", None, True, None),
    ("content", "text", None, True, None),
    ("description", "text", None, True, None),
    ("visibility_level", "varchar", 80, False, "manager_scope"),
    ("visibility_scope", "varchar", 80, True, "manager_scope"),
    ("remind_in_evaluation", "boolean", None, True, "true"),
    ("remind_during_scoring", "boolean", None, True, "true"),
    ("include_in_scorecard", "boolean", None, True, "false"),
    ("visible_on_scorecard", "boolean", None, True, "false"),
    ("is_active", "boolean", None, True, "true"),
    ("active", "boolean", None, True, "true"),
    ("occurred_at", "timestamp", None, True, "current_timestamp"),
    ("created_at", "timestamp", None, True, "current_timestamp"),
    ("updated_at", "timestamp", None, True, "current_timestamp"),
)
CANONICAL_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_perf_interim_notes_employee_period", ("employee_id", "period_id")),
    ("ix_perf_interim_notes_employee_user_period", ("employee_user_id", "period_id")),
)
KNOWN_LEGACY_EXTRA_COLUMNS = {
    "development_guidance_id": "integer",
    "converted_to_guidance": "boolean",
}

# Independent from CANONICAL_COLUMNS: same-looking aliases have different
# defaults/nullability and readers give them different precedence. Never merge.
HISTORICAL_PRODUCTION_COLUMNS = (
    ("id", "integer", False, "sequence"),
    ("period_id", "integer", True, None),
    ("employee_id", "integer", False, None),
    ("manager_id", "integer", True, None),
    ("note_type", "character varying(40)", False, "general"),
    ("title", "character varying(255)", False, None),
    ("note", "text", False, None),
    ("visibility_level", "character varying(40)", False, "manager_scope"),
    ("remind_in_evaluation", "boolean", False, "true"),
    ("include_in_scorecard", "boolean", False, "false"),
    ("occurred_at", "timestamp without time zone", True, "current_timestamp"),
    ("created_at", "timestamp without time zone", True, "current_timestamp"),
    ("updated_at", "timestamp without time zone", True, "current_timestamp"),
    ("assignment_id", "integer", True, None),
    ("evaluation_id", "integer", True, None),
    ("note_text", "text", False, ""),
    ("visible_on_scorecard", "boolean", False, "false"),
    ("is_active", "boolean", False, "true"),
    ("created_by_id", "integer", True, None),
    ("employee_user_id", "integer", True, None),
    ("created_by", "integer", True, None),
    ("note_title", "character varying(255)", True, None),
    ("note_body", "text", True, None),
    ("visibility_scope", "character varying(80)", True, "manager_scope"),
    ("remind_during_scoring", "boolean", True, "false"),
    ("content", "text", True, None),
    ("description", "text", True, None),
    ("active", "boolean", True, "true"),
    ("development_guidance_id", "integer", True, None),
    ("converted_to_guidance", "boolean", True, None),
)
HISTORICAL_PRODUCTION_INDEXES = (
    ("idx_perf_interim_notes_assignment", ("assignment_id",)),
    ("idx_perf_interim_notes_employee_period", ("employee_id", "period_id")),
    ("idx_perf_interim_notes_evaluation", ("evaluation_id",)),
    ("ix_bys360_fast_performance_interim_notes_created_at", ("created_at",)),
    ("ix_bys360_fast_performance_interim_notes_period_id", ("period_id",)),
    ("ix_bys360_fast_performance_interim_notes_updated_at", ("updated_at",)),
    ("ix_perf_interim_notes_created_by", ("created_by_id",)),
    ("ix_perf_interim_notes_employee", ("employee_id",)),
    ("ix_perf_interim_notes_employee_period", ("employee_id", "period_id")),
    ("ix_perf_interim_notes_employee_user_period", ("employee_user_id", "period_id")),
    ("ix_perf_interim_notes_manager", ("manager_id",)),
    ("ix_perf_interim_notes_type", ("note_type",)),
    ("performance_interim_notes_pkey", ("id",)),
)

MOBILE_BASE_COLUMNS = frozenset(
    {
        "id",
        "period_id",
        "employee_id",
        "employee_user_id",
        "manager_id",
        "created_by",
        "created_by_id",
        "note_type",
        "title",
        "note",
        "note_body",
        "visibility_level",
        "remind_during_scoring",
        "include_in_scorecard",
        "is_active",
        "occurred_at",
        "created_at",
        "updated_at",
    }
)
MEETING_P2_BASE_COLUMNS = frozenset(
    {
        "id",
        "employee_user_id",
        "period_id",
        "note_type",
        "note_title",
        "note_body",
        "visibility_scope",
        "remind_during_scoring",
        "include_in_scorecard",
        "created_by",
        "created_at",
        "updated_at",
    }
)
KNOWN_VARIANTS = (
    "ABSENT",
    "CANONICAL_VARIANT",
    "RUNTIME_VARIANT",
    "MOBILE_VARIANT",
    "MEETING_P2_VARIANT",
    "HISTORICAL_PRODUCTION_30_VARIANT (PostgreSQL only, exact catalog, no optional fields)",
    "(non-historical variants optionally with development_guidance_id/converted_to_guidance from d1a0e5c7b934)",
)

_SPEC = {
    name: (family, length, nullable, default)
    for name, family, length, nullable, default in CANONICAL_COLUMNS
}


class InterimNotesSchemaNotRecognized(RuntimeError):
    """performance_interim_notes exists with a structure no known helper produces."""


class InterimNotesShape(NamedTuple):
    variant: str
    missing_columns: tuple[str, ...]
    missing_indexes: tuple[tuple[str, tuple[str, ...]], ...]


def default_token(raw: object) -> str | None:
    """Normalise a reflected column default (PostgreSQL or SQLite rendering) to a comparable token."""
    if raw is None:
        return None
    value = str(raw).strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    value = re.sub(r"::[a-z ]+$", "", value, flags=re.I)
    lowered = value.lower()
    if lowered.startswith("nextval("):
        return "sequence"
    if lowered in {"1", "true"}:
        return "true"
    if lowered in {"0", "false"}:
        return "false"
    if lowered in {"current_timestamp", "now()", "current_timestamp()"}:
        return "current_timestamp"
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return f"<unrecognised {value}>"


def _family(column_type: sa.types.TypeEngine) -> tuple[str, int | None]:
    if isinstance(column_type, sa.Boolean):
        return "boolean", None
    if isinstance(column_type, sa.Integer):
        return "integer", None
    if isinstance(column_type, sa.Text):
        return "text", None
    if isinstance(column_type, sa.String):
        return "varchar", column_type.length
    if isinstance(column_type, sa.DateTime):
        return ("timestamptz" if getattr(column_type, "timezone", False) else "timestamp"), None
    return f"<unrecognised {column_type!r}>", None


def _type_matches(
    expected: str, length: int | None, actual: tuple[str, int | None], dialect: str
) -> bool:
    family, actual_length = actual
    if expected == "boolean" and family == "integer" and dialect == "sqlite":
        return True  # the helpers render booleans as INTEGER on SQLite (_bool_sql / bool_type)
    return family == expected and (expected != "varchar" or actual_length == length)


def _safe_list(call) -> list:
    try:
        return list(call() or [])
    except NotImplementedError:
        return []


def historical_production_catalog(bind: sa.engine.Connection) -> dict:
    """Read the full PG catalog, including indexes/constraints reflection omits."""
    params = {"table": TABLE_NAME}
    columns = list(bind.execute(sa.text("""
        SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
               NOT a.attnotnull AS nullable, pg_get_expr(d.adbin, d.adrelid) AS default,
               a.attidentity AS identity, a.attgenerated AS generated
        FROM pg_attribute a LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = to_regclass(:table) AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
    """), params).mappings())
    constraints = list(bind.execute(sa.text("""
        SELECT conname AS name, contype AS kind, condeferrable AS deferrable,
               condeferred AS deferred, convalidated AS validated,
               pg_get_constraintdef(oid) AS definition
        FROM pg_constraint WHERE conrelid = to_regclass(:table) ORDER BY conname
    """), params).mappings())
    indexes = list(bind.execute(sa.text("""
        SELECT c.relname AS name, i.indisunique AS unique, i.indisprimary AS primary,
               i.indisvalid AS valid, i.indisready AS ready, am.amname AS method,
               pg_get_expr(i.indpred, i.indrelid) AS predicate,
               pg_get_expr(i.indexprs, i.indrelid) AS expressions,
               i.indnatts - i.indnkeyatts AS included, i.indoption::text AS options,
               i.indcollation::text AS collations, i.indnullsnotdistinct AS nulls_not_distinct,
               c.reloptions AS storage_options,
               ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(num, ord)
                     LEFT JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.num
                     ORDER BY k.ord) AS columns,
               ARRAY(SELECT o.opcdefault FROM unnest(i.indclass) WITH ORDINALITY k(num, ord)
                     JOIN pg_opclass o ON o.oid = k.num ORDER BY k.ord) AS default_opclasses,
               ARRAY(SELECT i.indcollation[k.ord::integer - 1] = a.attcollation
                     FROM unnest(i.indkey) WITH ORDINALITY k(num, ord)
                     JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.num
                     ORDER BY k.ord) AS default_collations
        FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_am am ON am.oid = c.relam
        WHERE i.indrelid = to_regclass(:table) ORDER BY c.relname
    """), params).mappings())
    owned_default = bind.execute(sa.text("""
        SELECT 'nextval(' || quote_literal(pg_get_serial_sequence(:table, 'id')::regclass::text)
               || '::regclass)'
    """), params).scalar()
    return {"columns": columns, "constraints": constraints, "indexes": indexes,
            "owned_id_default": owned_default}


def historical_production_problems(catalog: dict) -> list[str]:
    """Exact contract; no fallback to a legacy subset after a mismatch."""
    problems = []
    columns = {c["name"]: c for c in catalog["columns"]}
    expected_names = {name for name, *_ in HISTORICAL_PRODUCTION_COLUMNS}
    if set(columns) != expected_names:
        problems.append("historical production column names differ")
    if [c["name"] for c in catalog["columns"]] != [c[0] for c in HISTORICAL_PRODUCTION_COLUMNS]:
        problems.append("historical production column order differs")
    for name, type_sql, nullable, default in HISTORICAL_PRODUCTION_COLUMNS:
        column = columns.get(name)
        if column is None:
            continue
        if (column["type"], column["nullable"], default_token(column["default"])) != (
            type_sql, nullable, default
        ) or column["identity"] or column["generated"]:
            problems.append(f"historical production {name}: type/nullability/default differs")
        if name == "id" and (not catalog["owned_id_default"] or
                              column["default"] != catalog["owned_id_default"]):
            problems.append("historical production id: default is not its owned serial sequence")
    if [dict(c) for c in catalog["constraints"]] != [{
        "name": "performance_interim_notes_pkey", "kind": "p", "deferrable": False,
        "deferred": False, "validated": True, "definition": "PRIMARY KEY (id)",
    }]:
        problems.append("historical production constraints differ")
    expected_indexes = dict(HISTORICAL_PRODUCTION_INDEXES)
    if {i["name"] for i in catalog["indexes"]} != set(expected_indexes):
        problems.append("historical production index names differ")
    for index in catalog["indexes"]:
        name = index["name"]
        cols = expected_indexes.get(name)
        if cols is None:
            continue
        is_pk = name == "performance_interim_notes_pkey"
        if (tuple(index["columns"]) != cols or index["unique"] != is_pk or
            index["primary"] != is_pk or not index["valid"] or not index["ready"] or
            index["method"] != "btree" or index["predicate"] is not None or
            index["expressions"] is not None or index["included"] != 0 or
            index["options"] != " ".join("0" for _ in cols) or
            index["default_collations"] != [True] * len(cols) or
            index["default_opclasses"] != [True] * len(cols) or
            index["nulls_not_distinct"] or index["storage_options"] is not None):
            problems.append(f"historical production index {name}: definition differs")
    return problems


def classify_existing_table(bind: sa.engine.Connection) -> InterimNotesShape:
    """Fingerprint the existing table; raise InterimNotesSchemaNotRecognized for anything unknown. Read-only."""
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name
    columns = {column["name"]: column for column in inspector.get_columns(TABLE_NAME)}
    indexes = inspector.get_indexes(TABLE_NAME)
    problems: list[str] = []

    if ({"assignment_id", "evaluation_id"} & set(columns) or
        getattr(columns.get("note_type", {}).get("type"), "length", None) == 40):
        if dialect != "postgresql":
            problems = ["historical production requires PostgreSQL catalog validation"]
        else:
            problems = historical_production_problems(historical_production_catalog(bind))
        if problems:
            raise InterimNotesSchemaNotRecognized(
                f"{TABLE_NAME} has an unrecognised structure: {'; '.join(problems)}. "
                "Exact HISTORICAL_PRODUCTION_30_VARIANT required; no schema change was made."
            )
        return InterimNotesShape("HISTORICAL_PRODUCTION_30_VARIANT", (), ())

    unknown = sorted(set(columns) - set(_SPEC) - set(KNOWN_LEGACY_EXTRA_COLUMNS))
    if unknown:
        problems.append(f"unknown columns {unknown}")

    def nullable(name: str) -> bool:
        return bool(columns[name]["nullable"])

    p2_signature = (
        "employee_user_id" in columns
        and not nullable("employee_user_id")
        and "note_body" in columns
        and not nullable("note_body")
        and "note_type" in columns
        and default_token(columns["note_type"]["default"]) is None
    )
    for name, column in columns.items():
        if name in KNOWN_LEGACY_EXTRA_COLUMNS:
            expected_family = KNOWN_LEGACY_EXTRA_COLUMNS[name]
            if not _type_matches(
                expected_family, None, _family(column["type"]), dialect
            ) or not nullable(name):
                problems.append(f"{name}: expected nullable {expected_family}")
            continue
        if name not in _SPEC:
            continue
        family, length, fresh_nullable, default = _SPEC[name]
        if not _type_matches(family, length, _family(column["type"]), dialect):
            problems.append(
                f"{name}: type {column['type']!r}, expected {family}{f'({length})' if length else ''}"
            )
        if name == "id":
            continue
        allowed_nullable = {fresh_nullable}
        if name == "visibility_level":
            allowed_nullable = {
                True,
                False,
            }  # NOT NULL from CREATE TABLE, nullable from the ALTER retrofit
        elif name in {"employee_user_id", "note_body"} and p2_signature:
            allowed_nullable = {True, False}
        elif fresh_nullable is False:
            allowed_nullable = {False}
        if nullable(name) not in allowed_nullable:
            problems.append(f"{name}: nullable={nullable(name)}")
        allowed_defaults = {default}
        if name == "note_type" and p2_signature:
            allowed_defaults.add(None)
        if family == "timestamp" and dialect == "sqlite":
            allowed_defaults.add(None)  # SQLite cannot ADD COLUMN with a CURRENT_TIMESTAMP default
        token = default_token(column["default"])
        if token not in allowed_defaults:
            problems.append(f"{name}: default {column['default']!r}")

    if inspector.get_pk_constraint(TABLE_NAME).get("constrained_columns") != ["id"]:
        problems.append("primary key is not (id)")
    if _safe_list(lambda: inspector.get_foreign_keys(TABLE_NAME)):
        problems.append("foreign keys present")
    if _safe_list(lambda: inspector.get_unique_constraints(TABLE_NAME)):
        problems.append("unique constraints present")
    if _safe_list(lambda: inspector.get_check_constraints(TABLE_NAME)):
        problems.append("check constraints present")
    canonical_indexes = dict(CANONICAL_INDEXES)
    present_indexes: set[str] = set()
    for index in indexes:
        name = index.get("name")
        if (
            name not in canonical_indexes
            or tuple(index["column_names"]) != canonical_indexes[name]
            or index.get("unique")
        ):
            problems.append(
                f"unexpected index {name} {index.get('column_names')} unique={bool(index.get('unique'))}"
            )
        else:
            present_indexes.add(name)

    if p2_signature:
        variant, base = "MEETING_P2_VARIANT", MEETING_P2_BASE_COLUMNS
    elif "visibility_level" in columns and not nullable("visibility_level"):
        variant, base = "RUNTIME_VARIANT", frozenset(_SPEC)
    else:
        variant, base = "MOBILE_VARIANT", MOBILE_BASE_COLUMNS
    if not base <= set(columns):
        problems.append(f"lacks base columns of {variant}: {sorted(base - set(columns))}")

    if problems:
        raise InterimNotesSchemaNotRecognized(
            f"{TABLE_NAME} has an unrecognised structure: {'; '.join(problems)}. "
            f"Detected columns: {sorted(columns)}; indexes: {sorted(str(ix.get('name')) for ix in indexes)}. "
            f"Known structures: {', '.join(KNOWN_VARIANTS)}. "
            "No schema change was made by this revision; on PostgreSQL the upgrade transaction is rolled back. "
            "Inspect the table and decide the adoption manually."
        )
    missing_columns = tuple(name for name, *_ in CANONICAL_COLUMNS if name not in columns)
    missing_indexes = tuple(
        (name, cols) for name, cols in CANONICAL_INDEXES if name not in present_indexes
    )
    if variant == "RUNTIME_VARIANT" and not missing_indexes:
        variant = "CANONICAL_VARIANT"
    return InterimNotesShape(variant, missing_columns, missing_indexes)


def _sa_type(family: str, length: int | None) -> sa.types.TypeEngine:
    return {
        "integer": sa.Integer(),
        "varchar": sa.String(length=length),
        "text": sa.Text(),
        "boolean": sa.Boolean(),
        "timestamp": sa.DateTime(),
    }[family]


def _server_default(default: str | None):
    if default is None:
        return None
    if default == "true":
        return sa.true()
    if default == "false":
        return sa.false()
    if default == "current_timestamp":
        return sa.text("CURRENT_TIMESTAMP")
    return sa.text(f"'{default}'")


def _create_canonical_table() -> None:
    columns = [sa.Column("id", sa.Integer(), primary_key=True)]
    for name, family, length, nullable, default in CANONICAL_COLUMNS[1:]:
        columns.append(
            sa.Column(
                name,
                _sa_type(family, length),
                nullable=nullable,
                server_default=_server_default(default),
            )
        )
    op.create_table(TABLE_NAME, *columns)
    for name, index_columns in CANONICAL_INDEXES:
        op.create_index(name, TABLE_NAME, list(index_columns))


def _add_missing_column(name: str, dialect: str) -> None:
    family, length, _fresh_nullable, default = _SPEC[name]
    if family == "timestamp":
        # No backfill: existing rows keep NULL instead of an invented time; new rows get the default.
        op.add_column(TABLE_NAME, sa.Column(name, _sa_type(family, length), nullable=True))
        if dialect == "postgresql":
            op.alter_column(TABLE_NAME, name, server_default=_server_default(default))
        return
    op.add_column(
        TABLE_NAME,
        sa.Column(
            name, _sa_type(family, length), nullable=True, server_default=_server_default(default)
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE_NAME):
        _create_canonical_table()
        logger.info("%s created (ABSENT -> canonical)", TABLE_NAME)
        return
    shape = classify_existing_table(bind)
    for name in shape.missing_columns:
        _add_missing_column(name, bind.dialect.name)
    for name, index_columns in shape.missing_indexes:
        op.create_index(name, TABLE_NAME, list(index_columns))
    logger.info(
        "%s adopted from %s: added columns %s, added indexes %s",
        TABLE_NAME,
        shape.variant,
        list(shape.missing_columns),
        [name for name, _ in shape.missing_indexes],
    )


def downgrade() -> None:
    """Keep the table: it holds institutional notes and may predate this revision."""
