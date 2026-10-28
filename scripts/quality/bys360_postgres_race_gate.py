"""BYS360 PostgreSQL 15 concurrency (race) gate.

The admin-continuity race tests (R05c ``test_c_postgresql_*`` and
``tests/postgresql/test_r05d_admin_access_race.py``) and the File Center
chunked-upload finalize race (``tests/postgresql/test_f09_chunk_finalize_race.py``)
prove their ``FOR UPDATE`` row locks with two independent database connections. On SQLite
they cannot run, and without ``BYS360_R05C_PG_URL`` the R05c pair is skipped.
This gate runs exactly those tests against a disposable PostgreSQL 15
database and fails unless every one of them ran and passed:

  - URL guard: local/CI host only, disposable ``bys360_race_test_*`` name.
  - The server must report PostgreSQL major version 15 (``SHOW server_version``).
  - pytest must report exactly ``EXPECTED_TEST_COUNT`` tests, 0 skipped,
    0 failed, 0 errors (a skip is a failure here, never a pass).

The guards are hardcoded; there is no bypass flag. Credentials never reach
stdout (``redact``).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

ENV_VAR = "BYS360_R05C_PG_URL"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
SAFE_DB_NAME_RE = re.compile(r"^bys360_race_test_[a-z0-9_]+$")
REQUIRED_PG_MAJOR = 15

R05C = "tests/security/test_r05c_settings_authority_and_admin_continuity_contract.py"
RACE_TESTS = (
    "tests/postgresql/test_r05d_admin_access_race.py",
    f"{R05C}::test_c_postgresql_concurrent_mutual_demotion_keeps_one_active_admin",
    f"{R05C}::test_c_postgresql_control_without_the_row_lock_the_race_loses_every_admin",
    "tests/postgresql/test_f09_chunk_finalize_race.py",
)
# test_r05d is parametrised (revoke, demote) + the two R05c tests + the F-09 finalize race.
EXPECTED_TEST_COUNT = 5

ROOT = Path(__file__).resolve().parents[2]


class GateFailure(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def redact(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1) if parts.password else parts.netloc
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def validate_url(url: str) -> SplitResult:
    if not url or not url.strip():
        raise GateFailure("MISSING_URL", f"{ENV_VAR} is not set (or empty).")
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgresql+psycopg2"):
        raise GateFailure("UNSAFE_SCHEME", f"Only postgresql:// URLs are accepted; got scheme={parts.scheme!r}.")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise GateFailure("UNSAFE_HOST", f"Host {host!r} is not an allowed local/CI test host {sorted(ALLOWED_HOSTS)!r}.")
    db_name = (parts.path or "").lstrip("/")
    if not SAFE_DB_NAME_RE.match(db_name):
        raise GateFailure(
            "UNSAFE_DB_NAME",
            f"Database name {db_name!r} does not match the disposable-test naming contract ({SAFE_DB_NAME_RE.pattern!r}).",
        )
    return parts


def parse_major(version_str: str) -> int:
    match = re.match(r"(\d+)", version_str or "")
    return int(match.group(1)) if match else -1


def check_postgres_major_version(parts: SplitResult) -> str:
    import psycopg2

    try:
        conn = psycopg2.connect(
            host=parts.hostname,
            port=parts.port or 5432,
            user=parts.username,
            password=parts.password,
            dbname=(parts.path or "").lstrip("/"),
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW server_version;")
                version_str = cur.fetchone()[0]
        finally:
            conn.close()
    except psycopg2.Error as exc:
        raise GateFailure("CONNECT_FAILED", f"could not read the server version: {exc}".strip()) from exc
    major = parse_major(version_str)
    if major != REQUIRED_PG_MAJOR:
        raise GateFailure(
            "WRONG_PG_MAJOR",
            f"Server reports PostgreSQL major version {major} (full: {version_str!r}); required {REQUIRED_PG_MAJOR}.",
        )
    return version_str


def evaluate_junit(junit_path: Path) -> dict[str, int]:
    """Totals from a pytest JUnit XML report; raises unless all expected tests ran and passed."""
    root = ET.parse(junit_path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {key: sum(int(suite.get(key, 0)) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
    if totals["skipped"]:
        raise GateFailure("SKIPPED", f"{totals['skipped']} race test(s) skipped; a skip is a failure here. {totals}")
    if totals["failures"] or totals["errors"]:
        raise GateFailure("FAILED", f"race tests failed: {totals}")
    if totals["tests"] != EXPECTED_TEST_COUNT:
        raise GateFailure("WRONG_COUNT", f"expected {EXPECTED_TEST_COUNT} race tests, pytest reported {totals}")
    return totals


def run_race_tests(junit_path: Path) -> int:
    command = [
        sys.executable, "-m", "pytest", *RACE_TESTS,
        "-p", "no:cacheprovider", "-rA", "--tb=short", "-q", f"--junitxml={junit_path}",
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    url = os.environ.get(ENV_VAR, "")
    try:
        parts = validate_url(url)
        print(f"BYS360 PG race gate target: {redact(url)}")
        version_str = check_postgres_major_version(parts)
        print(f"PostgreSQL server_version: {version_str} (required major {REQUIRED_PG_MAJOR})")
        with tempfile.TemporaryDirectory() as tmp:
            junit_path = Path(tmp) / "race.xml"
            returncode = run_race_tests(junit_path)
            if not junit_path.exists():
                raise GateFailure("NO_REPORT", f"pytest exited {returncode} without a JUnit report")
            totals = evaluate_junit(junit_path)
        if returncode != 0:
            raise GateFailure("FAILED", f"pytest exited {returncode}: {totals}")
    except GateFailure as failure:
        print(f"BYS360 PG race gate FAILED [{failure.code}]: {failure.detail}")
        return 1
    print(f"BYS360 PG race gate PASSED on PostgreSQL {version_str}: {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
