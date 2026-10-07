"""Offline fingerprint regression; real PG15 execution is mandatory in the existing gate."""
from __future__ import annotations

import copy
import re

import pytest
import sqlalchemy as sa

from scripts.quality.bys360_postgres_migration_integrity_gate import (
    HISTORICAL_PRODUCTION_PG_DDL,
    HISTORICAL_PRODUCTION_PG_INDEXES,
    load_interim_notes_contract,
)


def _catalog():
    # Parse the independent evidence fixture, never the adoption contract.
    columns = []
    serial_default = "nextval('performance_interim_notes_id_seq'::regclass)"
    for ddl in HISTORICAL_PRODUCTION_PG_DDL.split("(", 1)[1].rsplit(")", 1)[0].split(","):
        match = re.match(r"\s*(\w+)\s+(\w+)(?:\((\d+)\))?", ddl)
        assert match is not None
        name, kind, length = match.groups()
        type_sql = {"SERIAL": "integer", "INTEGER": "integer", "VARCHAR": f"character varying({length})",
                    "TEXT": "text", "BOOLEAN": "boolean", "TIMESTAMP": "timestamp without time zone"}[kind]
        default = ddl.split("DEFAULT ", 1)[1].strip() if "DEFAULT " in ddl else None
        if kind == "SERIAL":
            default = serial_default
        columns.append({"name": name, "type": type_sql, "nullable": "NOT NULL" not in ddl and kind != "SERIAL",
                        "default": default, "identity": "", "generated": ""})
    indexes = []
    for name, cols in {**HISTORICAL_PRODUCTION_PG_INDEXES, "performance_interim_notes_pkey": "id"}.items():
        names = cols.split(", ")
        pk = name == "performance_interim_notes_pkey"
        indexes.append({"name": name, "columns": names, "unique": pk, "primary": pk, "valid": True,
                        "ready": True, "method": "btree", "predicate": None, "expressions": None,
                        "included": 0, "options": " ".join("0" for _ in names),
                        "default_opclasses": [True] * len(names), "default_collations": [True] * len(names),
                        "nulls_not_distinct": False, "storage_options": None})
    return {"columns": columns, "indexes": indexes, "owned_id_default": serial_default,
            "constraints": [{"name": "performance_interim_notes_pkey", "kind": "p", "deferrable": False,
                             "deferred": False, "validated": True, "definition": "PRIMARY KEY (id)"}]}


def test_exact_independent_historical_signature_is_accepted():
    assert load_interim_notes_contract().historical_production_problems(_catalog()) == []


@pytest.mark.parametrize("name", [c["name"] for c in _catalog()["columns"]])
def test_every_historical_column_is_required(name):
    catalog = _catalog()
    catalog["columns"] = [c for c in catalog["columns"] if c["name"] != name]
    assert load_interim_notes_contract().historical_production_problems(catalog)


@pytest.mark.parametrize("name", list(HISTORICAL_PRODUCTION_PG_INDEXES) + ["performance_interim_notes_pkey"])
def test_every_historical_index_is_required(name):
    catalog = _catalog()
    catalog["indexes"] = [i for i in catalog["indexes"] if i["name"] != name]
    assert load_interim_notes_contract().historical_production_problems(catalog)


@pytest.mark.parametrize(("field", "value"), [
    ("type", "character varying(80)"), ("type", "text"), ("type", "bigint"),
    ("nullable", True), ("default", "'genel_gozlem'"), ("identity", "a"), ("generated", "s"),
])
def test_historical_column_drift_is_rejected(field, value):
    catalog = _catalog()
    next(c for c in catalog["columns"] if c["name"] == "note_type")[field] = value
    assert load_interim_notes_contract().historical_production_problems(catalog)


@pytest.mark.parametrize(("field", "value"), [
    ("unique", True), ("primary", True), ("valid", False), ("ready", False),
    ("method", "hash"), ("predicate", "is_active"), ("expressions", "lower(note_type)"),
    ("included", 1), ("options", "1"), ("default_opclasses", [False]),
    ("default_collations", [False]), ("nulls_not_distinct", True), ("storage_options", ["fillfactor=70"]),
    ("columns", ["created_by"]),
])
def test_historical_index_options_fail_closed(field, value):
    catalog = _catalog()
    next(i for i in catalog["indexes"] if i["name"] == "ix_perf_interim_notes_type")[field] = value
    assert load_interim_notes_contract().historical_production_problems(catalog)


@pytest.mark.parametrize("change", ["extra_column", "extra_index", "extra_constraint", "unowned_sequence"])
def test_unexpected_catalog_objects_fail_closed(change):
    catalog = _catalog()
    if change == "unowned_sequence":
        catalog["owned_id_default"] = None
    else:
        group = {"extra_column": "columns", "extra_index": "indexes", "extra_constraint": "constraints"}[change]
        extra = copy.deepcopy(catalog[group][0])
        extra["name"] = "unknown_extra"
        catalog[group].append(extra)
    assert load_interim_notes_contract().historical_production_problems(catalog)


def test_partial_hybrid_cannot_fall_back_to_sqlite_legacy_matching():
    contract = load_interim_notes_contract()
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(HISTORICAL_PRODUCTION_PG_DDL.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY")))
            with pytest.raises(contract.InterimNotesSchemaNotRecognized, match="PostgreSQL catalog"):
                contract.classify_existing_table(conn)
    finally:
        engine.dispose()
