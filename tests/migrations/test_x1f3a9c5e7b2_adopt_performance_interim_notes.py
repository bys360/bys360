"""Drives migrations/versions/x1f3a9c5e7b2 (performance_interim_notes Alembic ownership).

The table used to be created and patched at request time by four helpers. Every
historical shape they could leave behind is reproduced here from the helpers'
own DDL (SQLite rendering), then only the migration runs:

- ABSENT: the canonical table and both indexes are created;
- CANONICAL / RUNTIME / MOBILE / MEETING_P2 variants (optionally carrying the
  d1a0e5c7b934 columns) are adopted in place: rows and values are preserved,
  missing canonical columns and indexes are added, nothing is dropped or renamed;
- an unrecognised structure fails closed before any change;
- a second upgrade and the downgrade change nothing.

PostgreSQL behaviour (catalog types, defaults, transactional rollback) is proven by
scripts/quality/bys360_postgres_migration_integrity_gate.py
(POSTGRES15_INTERIM_NOTES_ALEMBIC_OWNERSHIP and POSTGRES15_INTERIM_NOTES_LEGACY_ADOPTION).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "migrations"
    / "versions"
    / "x1f3a9c5e7b2_adopt_performance_interim_notes_into_alembic.py"
)
TABLE = "performance_interim_notes"

# app/services/performance/interim_notes_runtime.py::ensure_interim_notes_table() CREATE TABLE,
# SQLite rendering (_id_sql() -> AUTOINCREMENT, _bool_sql() -> INTEGER DEFAULT 1/0).
RUNTIME_DDL = f"""
CREATE TABLE {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NULL, employee_id INTEGER NULL, employee_user_id INTEGER NULL,
    manager_id INTEGER NULL, created_by INTEGER NULL, created_by_id INTEGER NULL,
    note_type VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem',
    title VARCHAR(255) NULL, note_title VARCHAR(255) NULL,
    note TEXT NULL, note_body TEXT NULL, note_text TEXT NULL, content TEXT NULL, description TEXT NULL,
    visibility_level VARCHAR(80) NOT NULL DEFAULT 'manager_scope',
    visibility_scope VARCHAR(80) NULL DEFAULT 'manager_scope',
    remind_in_evaluation INTEGER DEFAULT 1 NULL, remind_during_scoring INTEGER DEFAULT 1 NULL,
    include_in_scorecard INTEGER DEFAULT 0 NULL, visible_on_scorecard INTEGER DEFAULT 0 NULL,
    is_active INTEGER DEFAULT 1 NULL, active INTEGER DEFAULT 1 NULL,
    occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
)
"""
RUNTIME_INDEXES = (
    f"CREATE INDEX ix_perf_interim_notes_employee_period ON {TABLE}(employee_id, period_id)",
    f"CREATE INDEX ix_perf_interim_notes_employee_user_period ON {TABLE}(employee_user_id, period_id)",
)
# app/api/mobile/performance_routes.py::_v2853_ensure_interim_notes_table() fallback CREATE TABLE.
MOBILE_DDL = f"""
CREATE TABLE {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NULL, employee_id INTEGER NULL, employee_user_id INTEGER NULL,
    manager_id INTEGER NULL, created_by INTEGER NULL, created_by_id INTEGER NULL,
    note_type VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem',
    title VARCHAR(255) NULL, note TEXT NULL, note_body TEXT NULL,
    visibility_level VARCHAR(80) NULL DEFAULT 'manager_scope',
    remind_during_scoring BOOLEAN DEFAULT TRUE, include_in_scorecard BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
)
"""
# app/services/performance/meeting_p2_archive_notes.py::ensure_interim_notes_table() CREATE TABLE
# (SQLite only: on PostgreSQL its BOOLEAN DEFAULT 1 is rejected, so this shape cannot exist there).
P2_DDL = f"""
CREATE TABLE {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, employee_user_id INTEGER NOT NULL, period_id INTEGER,
    note_type VARCHAR(80) NOT NULL, note_title VARCHAR(255), note_body TEXT NOT NULL,
    visibility_scope VARCHAR(80) DEFAULT 'manager_scope',
    remind_during_scoring INTEGER DEFAULT 1, include_in_scorecard INTEGER DEFAULT 0,
    created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
# The runtime helper's ALTER TABLE retrofit definitions (SQLite rendering).
RUNTIME_ALTER = {
    "employee_id": "INTEGER NULL",
    "manager_id": "INTEGER NULL",
    "created_by_id": "INTEGER NULL",
    "title": "VARCHAR(255) NULL",
    "note_title": "VARCHAR(255) NULL",
    "note": "TEXT NULL",
    "note_text": "TEXT NULL",
    "content": "TEXT NULL",
    "description": "TEXT NULL",
    "visibility_level": "VARCHAR(80) NULL DEFAULT 'manager_scope'",
    "visibility_scope": "VARCHAR(80) NULL DEFAULT 'manager_scope'",
    "remind_in_evaluation": "INTEGER DEFAULT 1 NULL",
    "visible_on_scorecard": "INTEGER DEFAULT 0 NULL",
    "is_active": "INTEGER DEFAULT 1 NULL",
    "active": "INTEGER DEFAULT 1 NULL",
}
D1A0_EXTRAS = (
    "ALTER TABLE {t} ADD COLUMN development_guidance_id INTEGER",
    "ALTER TABLE {t} ADD COLUMN converted_to_guidance BOOLEAN",
)

RUNTIME_ROW = {
    "id": 41,
    "period_id": 7,
    "employee_id": 3,
    "employee_user_id": 3,
    "manager_id": 9,
    "created_by": 9,
    "created_by_id": 9,
    "note_type": "basari",
    "title": "Proje teslimi",
    "note": "Zamanında teslim etti",
    "note_body": "Zamanında teslim etti",
    "include_in_scorecard": 1,
    "created_at": "2026-02-03 10:11:12",
}
MOBILE_ROW = {
    "id": 52,
    "period_id": 8,
    "employee_id": 4,
    "employee_user_id": 4,
    "manager_id": 4,
    "created_by": 4,
    "created_by_id": 4,
    "note_type": "olumsuz_olay",
    "title": "Gecikme",
    "note": "Rapor iki gün gecikti",
    "note_body": "Rapor iki gün gecikti",
    "include_in_scorecard": 0,
    "created_at": "2026-03-04 08:09:10",
}
P2_ROW = {
    "id": 63,
    "employee_user_id": 5,
    "period_id": 9,
    "note_type": "success",
    "note_title": "Ödül",
    "note_body": "Kurum içi ödül aldı",
    "include_in_scorecard": 1,
    "created_by": 2,
    "created_at": "2026-01-02 03:04:05",
}


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("x1f3a9c5e7b2_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection: sa.Connection, step: str = "upgrade", module: Any = None) -> None:
    module = module or _module()
    original = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        getattr(module, step)()
    finally:
        module.op = original


def _engine() -> sa.Engine:
    return sa.create_engine("sqlite:///:memory:")


def _columns(connection: sa.Connection) -> dict[str, Any]:
    return {c["name"]: c for c in sa.inspect(connection).get_columns(TABLE)}


def _indexes(connection: sa.Connection) -> dict[str, list[str]]:
    return {
        str(ix["name"]): [str(c) for c in ix["column_names"]] for ix in sa.inspect(connection).get_indexes(TABLE)
    }


def _insert(connection: sa.Connection, row: dict[str, Any]) -> None:
    keys = ", ".join(row)
    connection.execute(
        sa.text(f"INSERT INTO {TABLE} ({keys}) VALUES ({', '.join(':' + k for k in row)})"), row
    )


def _rows(connection: sa.Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in connection.execute(sa.text(f"SELECT * FROM {TABLE} ORDER BY id")).mappings()
    ]


def _canonical_names() -> set[str]:
    return {name for name, *_ in _module().CANONICAL_COLUMNS}


def _assert_canonical_columns_and_indexes(connection: sa.Connection) -> None:
    module = _module()
    assert _canonical_names() <= set(_columns(connection))
    assert _indexes(connection) == {name: list(cols) for name, cols in module.CANONICAL_INDEXES}


def _assert_preserved(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    assert len(after) == len(before)
    for old, new in zip(before, after, strict=True):
        assert {k: new[k] for k in old} == old


def test_revision_descends_from_previous_production_head_and_is_the_single_head() -> None:
    module = _module()
    assert module.revision == "x1f3a9c5e7b2"
    assert module.down_revision == "w2d8e1f4a6c3"
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == ["x1f3a9c5e7b2"]


def test_contract_is_the_runtime_helper_shape() -> None:
    module = _module()
    assert len(module.CANONICAL_COLUMNS) == 26
    assert len(module.CANONICAL_INDEXES) == 2
    by_name = {
        name: (family, length, nullable, default)
        for name, family, length, nullable, default in module.CANONICAL_COLUMNS
    }
    assert by_name["id"] == ("integer", None, False, None)
    assert by_name["note_type"] == ("varchar", 80, False, "genel_gozlem")
    assert by_name["visibility_level"] == ("varchar", 80, False, "manager_scope")
    assert by_name["include_in_scorecard"] == ("boolean", None, True, "false")
    assert by_name["created_at"] == ("timestamp", None, True, "current_timestamp")
    # Columns only an inactive AI decision query names (never created by any helper) are not canonical.
    assert not {"personnel_id", "evaluation_id", "category", "summary"} & set(by_name)


def test_absent_table_is_created_with_canonical_columns_and_indexes() -> None:
    with _engine().begin() as connection:
        _run(connection)
        module = _module()
        columns = _columns(connection)
        assert list(columns) == [name for name, *_ in module.CANONICAL_COLUMNS]
        for name, family, length, nullable, default in module.CANONICAL_COLUMNS:
            if name != "id":
                assert columns[name]["nullable"] is nullable, name
            assert module.default_token(columns[name]["default"]) == default, name
        assert sa.inspect(connection).get_pk_constraint(TABLE)["constrained_columns"] == ["id"]
        _assert_canonical_columns_and_indexes(connection)
        assert module.classify_existing_table(connection).variant == "CANONICAL_VARIANT"


def test_canonical_runtime_table_is_left_unchanged() -> None:
    with _engine().begin() as connection:
        connection.execute(sa.text(RUNTIME_DDL))
        for ddl in RUNTIME_INDEXES:
            connection.execute(sa.text(ddl))
        _insert(connection, RUNTIME_ROW)
        before_columns, before_rows = _columns(connection), _rows(connection)
        assert _module().classify_existing_table(connection).variant == "CANONICAL_VARIANT"
        _run(connection)
        assert list(_columns(connection)) == list(before_columns)
        assert _rows(connection) == before_rows
        _assert_canonical_columns_and_indexes(connection)


def test_runtime_table_missing_its_indexes_gains_only_the_indexes() -> None:
    with _engine().begin() as connection:
        connection.execute(sa.text(RUNTIME_DDL))
        _insert(connection, RUNTIME_ROW)
        before_columns, before_rows = _columns(connection), _rows(connection)
        shape = _module().classify_existing_table(connection)
        assert shape.variant == "RUNTIME_VARIANT"
        assert shape.missing_columns == ()
        _run(connection)
        assert list(_columns(connection)) == list(before_columns)
        assert _rows(connection) == before_rows
        _assert_canonical_columns_and_indexes(connection)


@pytest.mark.parametrize("with_d1a0_extras", [False, True], ids=["plain", "with_d1a0_columns"])
def test_mobile_fallback_table_is_adopted_and_rows_preserved(with_d1a0_extras: bool) -> None:
    with _engine().begin() as connection:
        connection.execute(sa.text(MOBILE_DDL))
        if with_d1a0_extras:
            for ddl in D1A0_EXTRAS:
                connection.execute(sa.text(ddl.format(t=TABLE)))
        _insert(connection, MOBILE_ROW)
        before = _rows(connection)
        shape = _module().classify_existing_table(connection)
        assert shape.variant == "MOBILE_VARIANT"
        assert set(shape.missing_columns) == {
            "note_title",
            "note_text",
            "content",
            "description",
            "visibility_scope",
            "remind_in_evaluation",
            "visible_on_scorecard",
            "active",
        }
        _run(connection)
        after = _rows(connection)
        _assert_preserved(before, after)
        _assert_canonical_columns_and_indexes(connection)
        assert (
            {"development_guidance_id", "converted_to_guidance"} <= set(_columns(connection))
        ) is with_d1a0_extras
        # Added nullable columns hold no fabricated text; constant defaults match what readers COALESCE to.
        assert after[0]["note_title"] is None and after[0]["content"] is None
        assert after[0]["remind_in_evaluation"] == 1 and after[0]["visible_on_scorecard"] == 0
        assert after[0]["active"] == 1 and after[0]["visibility_scope"] == "manager_scope"


def test_mobile_table_partially_retrofitted_by_the_runtime_helper_gets_the_rest() -> None:
    with _engine().begin() as connection:
        connection.execute(sa.text(MOBILE_DDL))
        for name in ("note_title", "note_text", "remind_in_evaluation"):
            connection.execute(
                sa.text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {RUNTIME_ALTER[name]}")
            )
        connection.execute(sa.text(RUNTIME_INDEXES[0]))
        _insert(connection, MOBILE_ROW)
        before = _rows(connection)
        shape = _module().classify_existing_table(connection)
        assert shape.variant == "MOBILE_VARIANT"
        assert set(shape.missing_columns) == {
            "content",
            "description",
            "visibility_scope",
            "visible_on_scorecard",
            "active",
        }
        assert [name for name, _ in shape.missing_indexes] == [
            "ix_perf_interim_notes_employee_user_period"
        ]
        _run(connection)
        _assert_preserved(before, _rows(connection))
        _assert_canonical_columns_and_indexes(connection)


@pytest.mark.parametrize("with_d1a0_extras", [False, True], ids=["plain", "with_d1a0_columns"])
def test_meeting_p2_table_is_adopted_rows_and_constraints_preserved(with_d1a0_extras: bool) -> None:
    with _engine().begin() as connection:
        connection.execute(sa.text(P2_DDL))
        if with_d1a0_extras:
            for ddl in D1A0_EXTRAS:
                connection.execute(sa.text(ddl.format(t=TABLE)))
        _insert(connection, P2_ROW)
        before = _rows(connection)
        shape = _module().classify_existing_table(connection)
        assert shape.variant == "MEETING_P2_VARIANT"
        assert len(shape.missing_columns) == 14
        _run(connection)
        after = _rows(connection)
        _assert_preserved(before, after)
        _assert_canonical_columns_and_indexes(connection)
        columns = _columns(connection)
        # The P2 NOT NULL columns are not relaxed; the historical timestamp is not overwritten.
        assert (
            columns["employee_user_id"]["nullable"] is False
            and columns["note_body"]["nullable"] is False
        )
        assert after[0]["created_at"] == P2_ROW["created_at"] and after[0]["occurred_at"] is None
        assert after[0]["employee_id"] is None  # not invented from employee_user_id


def test_p2_table_retrofitted_by_the_runtime_helper_is_recognised() -> None:
    with _engine().begin() as connection:
        connection.execute(sa.text(P2_DDL))
        # Every retrofit the runtime helper can apply to a P2 table on SQLite (its
        # "occurred_at ... DEFAULT CURRENT_TIMESTAMP" is rejected there as a non-constant default).
        for name, ddl in RUNTIME_ALTER.items():
            if name not in _module().MEETING_P2_BASE_COLUMNS:
                connection.execute(sa.text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl}"))
        _insert(connection, P2_ROW)
        before = _rows(connection)
        assert _module().classify_existing_table(connection).variant == "MEETING_P2_VARIANT"
        _run(connection)
        _assert_preserved(before, _rows(connection))
        _assert_canonical_columns_and_indexes(connection)


UNKNOWN_CASES = {
    "unknown_extra_column": (RUNTIME_DDL, [f"ALTER TABLE {TABLE} ADD COLUMN personnel_id INTEGER"]),
    "known_column_wrong_type": (
        MOBILE_DDL.replace("note_body TEXT NULL", "note_body INTEGER NULL"),
        [],
    ),
    "varchar_length_differs": (MOBILE_DDL.replace("title VARCHAR(255)", "title VARCHAR(100)"), []),
    "not_null_without_p2_signature": (
        MOBILE_DDL.replace("note_body TEXT NULL", "note_body TEXT NOT NULL"),
        [],
    ),
    "note_type_nullable": (
        MOBILE_DDL.replace("note_type VARCHAR(80) NOT NULL", "note_type VARCHAR(80) NULL"),
        [],
    ),
    "unexpected_default": (MOBILE_DDL.replace("DEFAULT 'genel_gozlem'", "DEFAULT 'diger'"), []),
    "unknown_index": (RUNTIME_DDL, [f"CREATE INDEX ix_interim_notes_custom ON {TABLE}(note_type)"]),
    "canonical_index_name_on_other_columns": (
        RUNTIME_DDL,
        [f"CREATE INDEX ix_perf_interim_notes_employee_period ON {TABLE}(period_id)"],
    ),
    "unique_constraint": (
        RUNTIME_DDL,
        [f"CREATE UNIQUE INDEX ux_interim_notes_title ON {TABLE}(title)"],
    ),
    "id_not_integer_primary_key": (
        MOBILE_DDL.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", "id TEXT PRIMARY KEY"),
        [],
    ),
    "missing_base_column": (MOBILE_DDL.replace("manager_id INTEGER NULL, ", ""), []),
    "foreign_key": (
        MOBILE_DDL.replace(
            "period_id INTEGER NULL,", "period_id INTEGER NULL REFERENCES users(id),", 1
        ),
        [],
    ),
}


@pytest.mark.parametrize("case", sorted(UNKNOWN_CASES))
def test_unrecognised_structure_fails_closed_before_any_change(case: str) -> None:
    ddl, extra = UNKNOWN_CASES[case]
    with _engine().begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text(ddl))
        for statement in extra:
            connection.execute(sa.text(statement))
        connection.execute(
            sa.text(
                f"INSERT INTO {TABLE} (id, note_type, note_body) VALUES (77, 'basari', 'korunacak')"
            )
        )
        before_columns, before_indexes, before_rows = (
            _columns(connection),
            _indexes(connection),
            _rows(connection),
        )
        module = _module()
        with pytest.raises(module.InterimNotesSchemaNotRecognized) as excinfo:
            _run(connection, module=module)
        message = str(excinfo.value)
        assert "No schema change was made" in message
        assert "MOBILE_VARIANT" in message and "MEETING_P2_VARIANT" in message
        assert list(_columns(connection)) == list(before_columns)
        assert _indexes(connection) == before_indexes
        assert _rows(connection) == before_rows


def test_second_upgrade_is_a_no_op_for_every_adopted_variant() -> None:
    for ddl in (MOBILE_DDL, P2_DDL, RUNTIME_DDL):
        with _engine().begin() as connection:
            connection.execute(sa.text(ddl))
            _run(connection)
            columns, indexes, rows = _columns(connection), _indexes(connection), _rows(connection)
            _run(connection)
            assert list(_columns(connection)) == list(columns)
            assert _indexes(connection) == indexes
            assert _rows(connection) == rows


def test_downgrade_keeps_the_table_and_its_rows() -> None:
    with _engine().begin() as connection:
        _run(connection)
        connection.execute(
            sa.text(
                f"INSERT INTO {TABLE} (note_type, note_body) VALUES ('basari', 'korunacak not')"
            )
        )
        _run(connection, "downgrade")
        assert (
            connection.execute(sa.text(f"SELECT note_body FROM {TABLE}")).scalar_one()
            == "korunacak not"
        )


@pytest.mark.parametrize(
    ("raw", "token"),
    [
        ("'genel_gozlem'::character varying", "genel_gozlem"),
        ("'genel_gozlem'", "genel_gozlem"),
        ("true", "true"),
        ("1", "true"),
        ("TRUE", "true"),
        ("false", "false"),
        ("0", "false"),
        ("CURRENT_TIMESTAMP", "current_timestamp"),
        ("now()", "current_timestamp"),
        ("nextval('performance_interim_notes_id_seq'::regclass)", "sequence"),
        (None, None),
    ],
)
def test_default_tokens_normalise_postgresql_and_sqlite_renderings(
    raw: str | None, token: str | None
) -> None:
    assert _module().default_token(raw) == token
