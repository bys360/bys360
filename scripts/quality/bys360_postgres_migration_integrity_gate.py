"""BYS360 PostgreSQL Migration Integrity Gate.

TD-032 closure: a repeatable, safety-guarded harness that proves the full
Alembic migration chain reaches head on a real, disposable PostgreSQL 15
database -- empty DB -> `flask db upgrade` -> head match -> second upgrade
is a no-op -> critical schema introspection. This is the SAME logic used
for every ad-hoc TD-032 verification run in this repo's history; it exists
here once so local runs and CI invoke identical code (no second migration
implementation to drift out of sync).

Ownership model: this gate does NOT create or drop the target database
itself. The caller (a human running it locally, or a CI `services:`
container) is responsible for provisioning an already-existing, empty,
disposable database before invoking this gate, and for dropping it
afterwards. This keeps the gate's own capability surface free of any
`DROP DATABASE`/`CREATE DATABASE` statement, which removes an entire class
of destructive-command risk from a script that is meant to be safe to run
against arbitrary connection strings.

Target selection is intentionally inflexible -- there is no `--allow-remote`
or similar bypass flag. The three guards below (host, database name,
PostgreSQL major version) are hardcoded and cannot be relaxed from the
command line:

  - Host must be 127.0.0.1 / localhost / ::1, or the CI service hostname
    "postgres" (the GitHub Actions `services:` container's DNS alias).
  - Database name must match `bys360_migration_test_*`, and must not be one
    of this repo's known real/maintenance database names.
  - Server must report PostgreSQL major version 15.

Usage:
    BYS360_REALDB_MIGRATION_TEST_URL=postgresql://postgres@127.0.0.1:5432/bys360_migration_test_<unique> \\
        python scripts/quality/bys360_postgres_migration_integrity_gate.py

Exit 0 = PASS. Any non-zero exit means a safety guard rejected the target,
or the migration chain itself failed -- see stdout for exactly which.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

PACKAGE = "BYS360_POSTGRES_MIGRATION_INTEGRITY_GATE_V1"

ENV_VAR = "BYS360_REALDB_MIGRATION_TEST_URL"

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# DNS alias GitHub Actions gives a `services: postgres:` container.
ALLOWED_CI_HOSTS = frozenset({"postgres"})

# Real/maintenance databases that must never be a target, however they are
# spelled -- belt-and-suspenders alongside the naming-pattern check below.
FORBIDDEN_DB_NAME_EXACT = frozenset(
    {
        "bys_db",
        "bys_db_livecore_final",
        "bys_db_restore_proof",
        "bys_db_restore_test",
        "postgres",
        "template0",
        "template1",
    }
)
SAFE_DB_NAME_RE = re.compile(r"^bys360_migration_test_[a-z0-9_]+$")

REQUIRED_PG_MAJOR = 15

CRITICAL_TABLES: tuple[str, ...] = (
    "users",
    "support_tickets",
    "surveys",
    "survey_assignments",
    "communication_survey_reminder_logs",
    "portal_groups",
    "portal_posts",
    "portal_post_comments",
    "portal_comment_mentions",
)

# Columns that application read paths select, which must exist after a fresh
# empty->head migration (BYS360 live evidence remediation V1). The approval
# entry is the full PerformancePresidentApproval ORM column set; the other two
# are the Faz 8 decision-support SELECT lists. tests/quality/
# test_bys360_postgres_migration_integrity_gate.py keeps these in sync with
# the application code.
CRITICAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "performance_president_approvals": (
        "id", "flow_id", "evaluation_id", "period_id", "employee_id", "final_score", "status",
        "president_user_id", "requested_at", "decided_at", "decision_note", "created_at", "updated_at",
    ),
    "performance_periods": (
        "id", "title", "name", "period_type", "scope_type",
        "scope_unit_label", "scope_category_label", "scope_personnel_filter",
        "start_date", "end_date", "is_active", "created_at",
        # adopted by w1c5a7d2e9b4 (previously runtime-only)
        "evaluation_start_date", "evaluation_end_date", "evaluation_due_days",
    ),
    "evaluation_assignments": ("id", "period_id", "evaluator_id", "employee_id", "status", "created_at"),
    # adopted by w1c5a7d2e9b4 (previously runtime-only)
    "users": ("birth_date", "hire_date", "celebration_opt_out"),
}


class GateFailure(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def redact(url: str) -> str:
    """Never let a real password reach stdout/logs."""
    parts = urlsplit(url)
    if parts.password:
        netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
    else:
        netloc = parts.netloc
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def validate_url(url: str) -> SplitResult:
    if not url or not url.strip():
        raise GateFailure("MISSING_URL", f"{ENV_VAR} is not set (or empty).")

    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgresql+psycopg2"):
        raise GateFailure(
            "UNSAFE_SCHEME",
            f"Only postgresql:// URLs are accepted; got scheme={parts.scheme!r}.",
        )

    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS and host not in ALLOWED_CI_HOSTS:
        raise GateFailure(
            "UNSAFE_HOST",
            f"Host {host!r} is not an allowed local/CI test host "
            f"({sorted(ALLOWED_HOSTS | ALLOWED_CI_HOSTS)!r}). Remote/institutional "
            "hosts are never accepted; there is no bypass flag.",
        )

    db_name = (parts.path or "").lstrip("/")
    if not db_name:
        raise GateFailure("UNSAFE_DB_NAME", "No database name present in the connection URL.")
    if db_name.lower() in FORBIDDEN_DB_NAME_EXACT:
        raise GateFailure(
            "UNSAFE_DB_NAME",
            f"Database name {db_name!r} is a known real/maintenance database -- refusing.",
        )
    if not SAFE_DB_NAME_RE.match(db_name):
        raise GateFailure(
            "UNSAFE_DB_NAME",
            f"Database name {db_name!r} does not match the disposable-test naming "
            f"contract ({SAFE_DB_NAME_RE.pattern!r}).",
        )
    return parts


# ---------------------------------------------------------------------------
# Migration graph: parsed statically from migrations/versions/*.py, matching
# the pure-Python approach used throughout TD-032's own verification runs.
# No Alembic import needed for this part -- keeps head discovery usable
# without an app context.
# ---------------------------------------------------------------------------


def _extract_refs(raw: str | None) -> list[str]:
    if raw is None or raw.strip() == "None":
        return []
    return re.findall(r"""['"]([a-zA-Z0-9_]+)['"]""", raw)


def compute_migration_graph(versions_dir: Path = MIGRATIONS_VERSIONS_DIR) -> dict:
    """Parse revision/down_revision out of every migrations/versions/*.py
    file and derive graph facts (heads, roots, cycles) the same way this
    repo's TD-032 verification runs have done throughout -- a lightweight
    regex parse, not a full Alembic ScriptDirectory load (which needs an
    app context this function should not require)."""
    graph: dict[str, str | None] = {}
    for path in sorted(versions_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        rev_match = re.search(r"""^revision\s*=\s*['"]([^'"]+)['"]""", text, re.M)
        down_match = re.search(r"^down_revision\s*=\s*(.+)", text, re.M)
        if not rev_match:
            continue
        graph[rev_match.group(1)] = down_match.group(1).strip() if down_match else None

    parents = {rev: _extract_refs(down) for rev, down in graph.items()}
    children: dict[str, list[str]] = {rev: [] for rev in graph}
    for rev, ps in parents.items():
        for p in ps:
            children.setdefault(p, []).append(rev)

    roots = [r for r, ps in parents.items() if not ps]
    heads = [r for r in graph if not children.get(r)]

    def has_cycle() -> bool:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(graph, WHITE)

        def dfs(u: str) -> bool:
            color[u] = GRAY
            for v in children.get(u, []):
                if color[v] == GRAY:
                    return True
                if color[v] == WHITE and dfs(v):
                    return True
            color[u] = BLACK
            return False

        return any(color[r] == WHITE and dfs(r) for r in graph)

    return {
        "revision_count": len(graph),
        "root_count": len(roots),
        "roots": sorted(roots),
        "head_count": len(heads),
        "heads": sorted(heads),
        "cycles": has_cycle(),
    }


# ---------------------------------------------------------------------------
# Real-database guards and probes. Imported lazily so pure graph/URL logic
# (and the harness contract tests) can run without psycopg2 installed.
# ---------------------------------------------------------------------------


def _connect(parts):
    import psycopg2

    return psycopg2.connect(
        host=parts.hostname,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        dbname=(parts.path or "").lstrip("/"),
    )


def check_postgres_major_version(parts) -> int:
    conn = _connect(parts)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version;")
            version_str = cur.fetchone()[0]
    finally:
        conn.close()
    match = re.match(r"(\d+)", version_str)
    major = int(match.group(1)) if match else -1
    if major != REQUIRED_PG_MAJOR:
        raise GateFailure(
            "WRONG_PG_MAJOR",
            f"Server reports PostgreSQL major version {major} (full: {version_str!r}); "
            f"required {REQUIRED_PG_MAJOR}.",
        )
    return major


def check_database_is_empty(parts) -> None:
    conn = _connect(parts)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';"
            )
            table_count = cur.fetchone()[0]
    finally:
        conn.close()
    if table_count != 0:
        raise GateFailure(
            "NON_EMPTY_DB",
            f"Target database has {table_count} table(s) in schema 'public'; expected 0. "
            "A stamped-but-empty or partially-provisioned database is not accepted for the "
            "empty->head chain proof.",
        )


def read_alembic_version(parts) -> str | None:
    conn = _connect(parts)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.alembic_version');")
            if cur.fetchone()[0] is None:
                return None
            cur.execute("SELECT version_num FROM alembic_version;")
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def introspect_critical_tables(parts) -> dict[str, bool]:
    conn = _connect(parts)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )
            present = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    return {table: (table in present) for table in CRITICAL_TABLES}


def introspect_critical_columns(parts) -> dict[str, list[str]]:
    """Return, per CRITICAL_COLUMNS table, the listed columns missing from the database."""
    conn = _connect(parts)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public';"
            )
            present = {(row[0], row[1]) for row in cur.fetchall()}
    finally:
        conn.close()
    return {
        table: [column for column in columns if (table, column) not in present]
        for table, columns in CRITICAL_COLUMNS.items()
    }


# Prints {table: [columns]} for every ORM model; run in a subprocess so the
# gate process itself never imports the application.
ORM_COLUMNS_SCRIPT = "\n".join((
    "import json, logging, warnings",
    "logging.disable(logging.CRITICAL)",
    "warnings.simplefilter('ignore')",
    "from app import create_app",
    "from app.extensions import db",
    "create_app()",
    "print(json.dumps({t.name: [c.name for c in t.columns] for t in db.metadata.tables.values()}))",
))


def load_orm_columns(database_url: str) -> dict[str, list[str]]:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    proc = subprocess.run(
        [sys.executable, "-c", ORM_COLUMNS_SCRIPT],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise GateFailure("ORM_METADATA_FAILURE", "Could not read ORM metadata: " + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def compute_orm_gaps(present: set[tuple[str, str]], orm_columns: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return ORM tables the database lacks entirely, and missing columns of tables it has."""
    tables = {table for table, _ in present}
    gaps: dict[str, list[str]] = {}
    for table, columns in sorted(orm_columns.items()):
        if table not in tables:
            gaps[table] = ["<table>"]
            continue
        missing = [column for column in columns if (table, column) not in present]
        if missing:
            gaps[table] = missing
    return gaps


def introspect_orm_parity(parts, orm_columns: dict[str, list[str]]) -> dict[str, list[str]]:
    conn = _connect(parts)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public';"
            )
            present = {(row[0], row[1]) for row in cur.fetchall()}
    finally:
        conn.close()
    return compute_orm_gaps(present, orm_columns)


# ---------------------------------------------------------------------------
# flask db upgrade -- run via the real CLI, same semantics as any human
# operator or CI step, not a re-implementation of Alembic's own logic.
# ---------------------------------------------------------------------------


def run_flask_db_upgrade(database_url: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    env["FLASK_APP"] = "wsgi.py"
    return subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


# performance_interim_notes is owned by one Alembic revision (G3-A). The gate proves on
# PostgreSQL 15 that `flask db upgrade` alone creates it in the canonical shape, and
# rehearses the adoption of every known request-time legacy shape (each in its own
# schema of this disposable database), the fail-closed refusal of an unknown shape
# and the transactional rollback of an interrupted adoption.
INTERIM_NOTES_TABLE = "performance_interim_notes"
INTERIM_NOTES_OWNER_REVISION = MIGRATIONS_VERSIONS_DIR / "x1f3a9c5e7b2_adopt_performance_interim_notes_into_alembic.py"
PG_TYPE_BY_FAMILY = {
    "integer": "integer",
    "varchar": "character varying",
    "text": "text",
    "boolean": "boolean",
    "timestamp": "timestamp without time zone",
}
# PostgreSQL renderings of the historical creators' DDL (rehearsal fixtures).
_INTERIM_RUNTIME_PG_DDL = f"""
    CREATE TABLE {INTERIM_NOTES_TABLE} (
        id SERIAL PRIMARY KEY, period_id INTEGER NULL, employee_id INTEGER NULL, employee_user_id INTEGER NULL,
        manager_id INTEGER NULL, created_by INTEGER NULL, created_by_id INTEGER NULL,
        note_type VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem', title VARCHAR(255) NULL, note_title VARCHAR(255) NULL,
        note TEXT NULL, note_body TEXT NULL, note_text TEXT NULL, content TEXT NULL, description TEXT NULL,
        visibility_level VARCHAR(80) NOT NULL DEFAULT 'manager_scope', visibility_scope VARCHAR(80) NULL DEFAULT 'manager_scope',
        remind_in_evaluation BOOLEAN DEFAULT TRUE NULL, remind_during_scoring BOOLEAN DEFAULT TRUE NULL,
        include_in_scorecard BOOLEAN DEFAULT FALSE NULL, visible_on_scorecard BOOLEAN DEFAULT FALSE NULL,
        is_active BOOLEAN DEFAULT TRUE NULL, active BOOLEAN DEFAULT TRUE NULL,
        occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP)"""
_INTERIM_RUNTIME_PG_INDEXES = (
    f"CREATE INDEX ix_perf_interim_notes_employee_period ON {INTERIM_NOTES_TABLE}(employee_id, period_id)",
    f"CREATE INDEX ix_perf_interim_notes_employee_user_period ON {INTERIM_NOTES_TABLE}(employee_user_id, period_id)",
)
_INTERIM_MOBILE_PG_DDL = f"""
    CREATE TABLE {INTERIM_NOTES_TABLE} (
        id SERIAL PRIMARY KEY, period_id INTEGER NULL, employee_id INTEGER NULL, employee_user_id INTEGER NULL,
        manager_id INTEGER NULL, created_by INTEGER NULL, created_by_id INTEGER NULL,
        note_type VARCHAR(80) NOT NULL DEFAULT 'genel_gozlem', title VARCHAR(255) NULL, note TEXT NULL, note_body TEXT NULL,
        visibility_level VARCHAR(80) NULL DEFAULT 'manager_scope', remind_during_scoring BOOLEAN DEFAULT TRUE,
        include_in_scorecard BOOLEAN DEFAULT FALSE, is_active BOOLEAN DEFAULT TRUE,
        occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP)"""
# The P2 helper's own DDL (BOOLEAN DEFAULT 1) is rejected by PostgreSQL; this is the same
# structure with valid boolean defaults, the closest shape that could exist there.
_INTERIM_P2_PG_DDL = f"""
    CREATE TABLE {INTERIM_NOTES_TABLE} (
        id SERIAL PRIMARY KEY, employee_user_id INTEGER NOT NULL, period_id INTEGER, note_type VARCHAR(80) NOT NULL,
        note_title VARCHAR(255), note_body TEXT NOT NULL, visibility_scope VARCHAR(80) DEFAULT 'manager_scope',
        remind_during_scoring BOOLEAN DEFAULT TRUE, include_in_scorecard BOOLEAN DEFAULT FALSE, created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
_INTERIM_D1A0_EXTRAS = (
    f"ALTER TABLE {INTERIM_NOTES_TABLE} ADD COLUMN development_guidance_id INTEGER",
    f"ALTER TABLE {INTERIM_NOTES_TABLE} ADD COLUMN converted_to_guidance BOOLEAN",
)
_INTERIM_SENTINEL = (
    f"INSERT INTO {INTERIM_NOTES_TABLE} (id, employee_user_id, period_id, note_type, note_body, include_in_scorecard, created_at) "
    "VALUES (9001, 77, 5, 'basari', 'G3A sentinel: Proje ödülü – korunmalı', TRUE, '2026-01-02 03:04:05')"
)
INTERIM_LEGACY_REHEARSALS: dict[str, tuple[tuple[str, ...], str]] = {
    "CANONICAL_VARIANT": ((_INTERIM_RUNTIME_PG_DDL, *_INTERIM_RUNTIME_PG_INDEXES), "CANONICAL_VARIANT"),
    "RUNTIME_VARIANT": ((_INTERIM_RUNTIME_PG_DDL,), "RUNTIME_VARIANT"),
    "MOBILE_VARIANT": ((_INTERIM_MOBILE_PG_DDL,), "MOBILE_VARIANT"),
    "MOBILE_VARIANT_WITH_D1A0": ((_INTERIM_MOBILE_PG_DDL, *_INTERIM_D1A0_EXTRAS), "MOBILE_VARIANT"),
    "MEETING_P2_VARIANT": ((_INTERIM_P2_PG_DDL,), "MEETING_P2_VARIANT"),
    "MEETING_P2_VARIANT_WITH_D1A0": ((_INTERIM_P2_PG_DDL, *_INTERIM_D1A0_EXTRAS), "MEETING_P2_VARIANT"),
}


def load_interim_notes_contract():
    """The owner revision module (its CANONICAL_COLUMNS/CANONICAL_INDEXES are the contract)."""
    spec = importlib.util.spec_from_file_location("x1f3a9c5e7b2_gate_contract", INTERIM_NOTES_OWNER_REVISION)
    if spec is None or spec.loader is None:
        raise GateFailure("INTERIM_NOTES_CONTRACT_MISSING", f"Cannot load {INTERIM_NOTES_OWNER_REVISION}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compare_interim_notes_catalog(
    columns: list[dict], indexes: Mapping[str, tuple[str, ...]], pk_columns: list[str], contract
) -> list[str]:
    """Problems between a PostgreSQL catalog snapshot and the canonical contract (empty = exact match)."""
    problems: list[str] = []
    by_name = {column["name"]: column for column in columns}
    expected = {name: (family, length, nullable, default) for name, family, length, nullable, default in contract.CANONICAL_COLUMNS}
    if set(by_name) != set(expected):
        problems.append(f"columns differ: missing {sorted(set(expected) - set(by_name))}, extra {sorted(set(by_name) - set(expected))}")
    for name, (family, length, nullable, default) in expected.items():
        column = by_name.get(name)
        if column is None:
            continue
        if column["data_type"] != PG_TYPE_BY_FAMILY[family] or (family == "varchar" and column["length"] != length):
            problems.append(f"{name}: type {column['data_type']}({column['length']}), expected {PG_TYPE_BY_FAMILY[family]}({length})")
        if (column["is_nullable"] == "YES") is not nullable:
            problems.append(f"{name}: is_nullable={column['is_nullable']}")
        token = contract.default_token(column["default"])
        if token != ("sequence" if name == "id" else default):
            problems.append(f"{name}: default {column['default']!r}")
    expected_indexes = dict(contract.CANONICAL_INDEXES)
    if dict(indexes) != expected_indexes:
        problems.append(f"indexes {indexes!r}, expected {expected_indexes!r}")
    if pk_columns != ["id"]:
        problems.append(f"primary key {pk_columns!r}")
    return problems


def _interim_notes_catalog(parts) -> tuple[list[dict], dict[str, tuple[str, ...]], list[str]]:
    conn = _connect(parts)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position;",
                (INTERIM_NOTES_TABLE,),
            )
            columns = [dict(zip(("name", "data_type", "length", "is_nullable", "default"), row, strict=True)) for row in cur.fetchall()]
            cur.execute(
                "SELECT i.relname, array_agg(a.attname ORDER BY k.ord) FROM pg_index x "
                "JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "CROSS JOIN LATERAL unnest(x.indkey) WITH ORDINALITY AS k(attnum, ord) "
                "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                "WHERE n.nspname = 'public' AND t.relname = %s AND NOT x.indisprimary GROUP BY i.relname;",
                (INTERIM_NOTES_TABLE,),
            )
            indexes = {row[0]: tuple(row[1]) for row in cur.fetchall()}
            cur.execute(
                "SELECT kcu.column_name FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name "
                "AND kcu.table_schema = tc.table_schema WHERE tc.table_schema = 'public' AND tc.table_name = %s "
                "AND tc.constraint_type = 'PRIMARY KEY' ORDER BY kcu.ordinal_position;",
                (INTERIM_NOTES_TABLE,),
            )
            pk_columns = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    return columns, indexes, pk_columns


def introspect_interim_notes_ownership(parts) -> list[str]:
    """Run right after `flask db upgrade` and before any runtime-schema step."""
    columns, indexes, pk_columns = _interim_notes_catalog(parts)
    if not columns:
        return [f"{INTERIM_NOTES_TABLE} does not exist after flask db upgrade"]
    return compare_interim_notes_catalog(columns, indexes, pk_columns, load_interim_notes_contract())


def rehearse_interim_notes_legacy_adoption(database_url: str) -> dict[str, str]:
    """Adopt each known legacy shape on PostgreSQL 15 in its own schema; returns {case: outcome}."""
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    contract = load_interim_notes_contract()
    canonical = {name for name, *_ in contract.CANONICAL_COLUMNS}
    admin = sa.create_engine(database_url)
    outcomes: dict[str, str] = {}
    schemas: list[str] = []

    def engine_for(schema: str):
        admin_conn = admin.connect()
        admin_conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
        admin_conn.commit()
        admin_conn.close()
        schemas.append(schema)
        return sa.create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})

    def snapshot(engine):
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            cols = [c["name"] for c in insp.get_columns(INTERIM_NOTES_TABLE)]
            idx = sorted(i["name"] for i in insp.get_indexes(INTERIM_NOTES_TABLE))
            rows = [dict(r) for r in conn.execute(sa.text(f"SELECT * FROM {INTERIM_NOTES_TABLE} ORDER BY id")).mappings()]
        return cols, idx, rows

    def upgrade(conn, operations=None):
        contract.op = operations or Operations(MigrationContext.configure(conn))
        contract.upgrade()

    try:
        for number, (case, (statements, expected_variant)) in enumerate(INTERIM_LEGACY_REHEARSALS.items()):
            engine = engine_for(f"g3a_rehearsal_{number}")
            with engine.begin() as conn:
                for statement in statements:
                    conn.execute(sa.text(statement))
                conn.execute(sa.text(_INTERIM_SENTINEL))
            with engine.connect() as conn:
                variant = contract.classify_existing_table(conn).variant
            if variant != expected_variant:
                raise GateFailure("INTERIM_NOTES_LEGACY_ADOPTION_FAILURE", f"{case}: classified {variant}, expected {expected_variant}")
            _, _, rows_before = snapshot(engine)
            with engine.begin() as conn:
                upgrade(conn)
            cols, idx, rows_after = snapshot(engine)
            if not canonical <= set(cols) or idx != sorted(name for name, _ in contract.CANONICAL_INDEXES):
                raise GateFailure("INTERIM_NOTES_LEGACY_ADOPTION_FAILURE", f"{case}: not canonical after upgrade: columns {cols}, indexes {idx}")
            if len(rows_after) != len(rows_before) or any(
                {k: new[k] for k in old} != old for old, new in zip(rows_before, rows_after, strict=True)
            ):
                raise GateFailure("INTERIM_NOTES_LEGACY_ADOPTION_FAILURE", f"{case}: sentinel rows changed: {rows_before} -> {rows_after}")
            engine.dispose()
            outcomes[case] = f"{variant} adopted, sentinel preserved"

        engine = engine_for("g3a_rehearsal_unknown")
        with engine.begin() as conn:
            conn.execute(sa.text(_INTERIM_RUNTIME_PG_DDL))
            conn.execute(sa.text(f"ALTER TABLE {INTERIM_NOTES_TABLE} ADD COLUMN personnel_id INTEGER"))
        before = snapshot(engine)
        try:
            with engine.begin() as conn:
                upgrade(conn)
        except contract.InterimNotesSchemaNotRecognized:
            pass
        else:
            raise GateFailure("INTERIM_NOTES_LEGACY_ADOPTION_FAILURE", "unknown shape was not refused")
        if snapshot(engine) != before:
            raise GateFailure("INTERIM_NOTES_LEGACY_ADOPTION_FAILURE", "unknown shape changed although refused")
        engine.dispose()
        outcomes["UNKNOWN_VARIANT"] = "refused, unchanged"

        engine = engine_for("g3a_rehearsal_rollback")
        with engine.begin() as conn:
            conn.execute(sa.text(_INTERIM_MOBILE_PG_DDL))
            conn.execute(sa.text(_INTERIM_SENTINEL))
        before = snapshot(engine)

        class _FailingOperations(Operations):
            def create_index(self, *args, **kwargs):  # columns were already added in this transaction
                raise RuntimeError("injected failure during adoption")

        try:
            with engine.begin() as conn:
                upgrade(conn, _FailingOperations(MigrationContext.configure(conn)))
        except RuntimeError:
            pass
        if snapshot(engine) != before:
            raise GateFailure("INTERIM_NOTES_LEGACY_ADOPTION_FAILURE", "interrupted adoption left a half-adopted table")
        engine.dispose()
        outcomes["INTERRUPTED_ADOPTION"] = "rolled back, unchanged"
    finally:
        with admin.connect() as conn:
            for schema in schemas:
                conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            conn.commit()
        admin.dispose()
    return outcomes


RUNTIME_SCHEMA_TIMEOUT_SECONDS = 300
RUNTIME_SCHEMA_LINE = re.compile(r"^[a-z0-9_.]+: ")


def run_flask_runtime_schema(database_url: str, command: str) -> subprocess.CompletedProcess:
    """`flask runtime-schema <command>`; a hang (e.g. a lock wait) becomes a gate failure, not a stuck job."""
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    env["FLASK_APP"] = "wsgi.py"
    try:
        return subprocess.run(
            [sys.executable, "-m", "flask", "runtime-schema", command],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=RUNTIME_SCHEMA_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure(
            "RUNTIME_SCHEMA_TIMEOUT",
            f"flask runtime-schema {command} did not finish within {RUNTIME_SCHEMA_TIMEOUT_SECONDS}s",
        ) from exc


def check_runtime_schema(database_url: str) -> int:
    """Provision the raw-SQL runtime groups, verify them, and require a second provision to change nothing."""
    for command in ("provision", "check"):
        result = run_flask_runtime_schema(database_url, command)
        if result.returncode != 0:
            raise GateFailure(
                "RUNTIME_SCHEMA_FAILURE",
                f"flask runtime-schema {command} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
    groups = [line for line in result.stdout.splitlines() if RUNTIME_SCHEMA_LINE.match(line)]
    again = run_flask_runtime_schema(database_url, "provision")
    changed = [
        line for line in again.stdout.splitlines()
        if RUNTIME_SCHEMA_LINE.match(line) and not line.rstrip().endswith("already present")
    ]
    if again.returncode != 0 or changed:
        raise GateFailure("RUNTIME_SCHEMA_NOT_IDEMPOTENT", f"Second provision changed or failed: {changed!r}")
    return len(groups)


def main(argv: list[str] | None = None) -> int:
    raw_url = os.environ.get(ENV_VAR, "")

    try:
        parts = validate_url(raw_url)
    except GateFailure as exc:
        print(f"{PACKAGE}_{exc.code}")
        print(exc.detail)
        return 1

    print(f"{PACKAGE}_TARGET={redact(raw_url)}")

    try:
        major = check_postgres_major_version(parts)
        print(f"POSTGRES_MAJOR={major}")

        check_database_is_empty(parts)
        print("EMPTY_DB_GUARD=PASS")

        graph = compute_migration_graph()
        print(f"REVISION_COUNT={graph['revision_count']}")
        print(f"ROOT_COUNT={graph['root_count']}")
        print(f"HEAD_COUNT={graph['head_count']}")
        print(f"HEADS={graph['heads']}")
        print(f"CYCLES={graph['cycles']}")
        if graph["cycles"]:
            raise GateFailure("CYCLE_DETECTED", "Migration graph contains a cycle.")
        if graph["head_count"] != 1:
            raise GateFailure(
                "MULTIPLE_HEADS",
                f"Expected exactly 1 head, found {graph['head_count']}: {graph['heads']!r}.",
            )
        expected_head = graph["heads"][0]

        first_run = run_flask_db_upgrade(raw_url)
        if first_run.returncode != 0:
            raise GateFailure(
                "MIGRATION_FAILURE",
                "flask db upgrade (empty->head) failed:\n"
                f"stdout:\n{first_run.stdout}\nstderr:\n{first_run.stderr}",
            )
        print("POSTGRES15_EMPTY_TO_HEAD=PASS")

        db_head = read_alembic_version(parts)
        if db_head != expected_head:
            raise GateFailure(
                "HEAD_MISMATCH",
                f"Database alembic_version is {db_head!r}; expected {expected_head!r} "
                "(the migration graph's own single head).",
            )
        print(f"POSTGRES15_HEAD_MATCH=PASS (head={db_head})")

        second_run = run_flask_db_upgrade(raw_url)
        if second_run.returncode != 0:
            raise GateFailure(
                "SECOND_UPGRADE_FAILURE",
                "Second flask db upgrade (expected no-op) failed:\n"
                f"stdout:\n{second_run.stdout}\nstderr:\n{second_run.stderr}",
            )
        running_upgrade_lines = [
            line for line in second_run.stdout.splitlines() if "Running upgrade" in line
        ]
        if running_upgrade_lines:
            raise GateFailure(
                "SECOND_UPGRADE_NOT_NOOP",
                f"Second upgrade executed {len(running_upgrade_lines)} migration step(s); "
                f"expected 0 (already at head): {running_upgrade_lines!r}",
            )
        print("POSTGRES15_SECOND_UPGRADE=PASS")

        table_presence = introspect_critical_tables(parts)
        missing = [table for table, present in table_presence.items() if not present]
        if missing:
            raise GateFailure(
                "CRITICAL_TABLE_MISSING",
                f"Critical table(s) missing after full migration: {missing!r}",
            )
        print(f"POSTGRES15_SCHEMA_INTROSPECTION=PASS (checked {len(CRITICAL_TABLES)} tables)")

        missing_columns = {
            table: columns for table, columns in introspect_critical_columns(parts).items() if columns
        }
        if missing_columns:
            raise GateFailure(
                "CRITICAL_COLUMN_MISSING",
                f"Critical column(s) missing after full migration: {missing_columns!r}",
            )
        checked = sum(len(columns) for columns in CRITICAL_COLUMNS.values())
        print(f"POSTGRES15_COLUMN_INTROSPECTION=PASS (checked {checked} columns)")

        orm_columns = load_orm_columns(raw_url)
        orm_gaps = introspect_orm_parity(parts, orm_columns)
        if orm_gaps:
            raise GateFailure(
                "ORM_SCHEMA_MISSING",
                f"ORM table(s)/column(s) missing after full migration: {orm_gaps!r}",
            )
        orm_column_count = sum(len(columns) for columns in orm_columns.values())
        print(f"POSTGRES15_ORM_PARITY=PASS (checked {len(orm_columns)} tables, {orm_column_count} columns)")

        interim_problems = introspect_interim_notes_ownership(parts)
        if interim_problems:
            raise GateFailure(
                "INTERIM_NOTES_CONTRACT_MISMATCH",
                f"{INTERIM_NOTES_TABLE} after flask db upgrade alone: {'; '.join(interim_problems)}",
            )
        print(f"POSTGRES15_INTERIM_NOTES_ALEMBIC_OWNERSHIP=PASS ({INTERIM_NOTES_TABLE} created by flask db upgrade alone, canonical contract)")

        runtime_groups = check_runtime_schema(raw_url)
        print(f"POSTGRES15_RUNTIME_SCHEMA=PASS (provisioned and verified {runtime_groups} groups, second provision no-op)")

        rehearsal = rehearse_interim_notes_legacy_adoption(raw_url)
        print(f"POSTGRES15_INTERIM_NOTES_LEGACY_ADOPTION=PASS ({len(rehearsal)} cases: {', '.join(sorted(rehearsal))})")

    except GateFailure as exc:
        print(f"{PACKAGE}_{exc.code}")
        print(exc.detail)
        return 1

    print(f"{PACKAGE}_RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
