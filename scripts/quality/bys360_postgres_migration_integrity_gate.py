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

import os
import re
import subprocess
import sys
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

    except GateFailure as exc:
        print(f"{PACKAGE}_{exc.code}")
        print(exc.detail)
        return 1

    print(f"{PACKAGE}_RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
