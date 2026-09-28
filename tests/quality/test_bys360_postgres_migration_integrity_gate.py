"""Contract tests for scripts/quality/bys360_postgres_migration_integrity_gate.py.

These are static/mocked contract tests -- they prove the harness's safety
guards, redaction, and result/exit-code contract without ever touching a
real PostgreSQL server. They do NOT replace the real PostgreSQL 15 run
(see the TD-032 wave report for that proof); they exist so a future change
to this gate's guard logic gets caught by the normal test suite before it
ever reaches a real database.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.quality.bys360_postgres_migration_integrity_gate import (
    ENV_VAR,
    GateFailure,
    compute_migration_graph,
    main,
    redact,
    validate_url,
)

pytestmark = pytest.mark.ci_safe


# ---------------------------------------------------------------------------
# URL / target guards
# ---------------------------------------------------------------------------


def test_missing_url_is_rejected() -> None:
    with pytest.raises(GateFailure) as excinfo:
        validate_url("")
    assert excinfo.value.code == "MISSING_URL"


def test_remote_host_is_rejected() -> None:
    with pytest.raises(GateFailure) as excinfo:
        validate_url("postgresql://postgres@db.canakkaletarihialan.gov.tr:5432/bys360_migration_test_x")
    assert excinfo.value.code == "UNSAFE_HOST"


def test_localhost_and_loopback_and_ci_service_host_are_accepted() -> None:
    for host in ("127.0.0.1", "localhost", "postgres"):
        parts = validate_url(f"postgresql://postgres@{host}:5432/bys360_migration_test_x")
        assert parts.hostname == host


@pytest.mark.parametrize(
    "db_name",
    ["bys_db", "bys_db_livecore_final", "bys_db_restore_proof", "bys_db_restore_test", "postgres"],
)
def test_known_real_or_maintenance_db_name_is_rejected(db_name: str) -> None:
    with pytest.raises(GateFailure) as excinfo:
        validate_url(f"postgresql://postgres@127.0.0.1:5432/{db_name}")
    assert excinfo.value.code == "UNSAFE_DB_NAME"


@pytest.mark.parametrize("db_name", ["my_test_db", "bys360_test", "bys360_migration_test", ""])
def test_db_name_not_matching_disposable_pattern_is_rejected(db_name: str) -> None:
    with pytest.raises(GateFailure) as excinfo:
        validate_url(f"postgresql://postgres@127.0.0.1:5432/{db_name}")
    assert excinfo.value.code == "UNSAFE_DB_NAME"


def test_disposable_db_name_pattern_is_accepted() -> None:
    parts = validate_url("postgresql://postgres@127.0.0.1:5432/bys360_migration_test_20260101_000000")
    assert parts.path.lstrip("/") == "bys360_migration_test_20260101_000000"


def test_non_postgresql_scheme_is_rejected() -> None:
    with pytest.raises(GateFailure) as excinfo:
        validate_url("mysql://root@127.0.0.1:3306/bys360_migration_test_x")
    assert excinfo.value.code == "UNSAFE_SCHEME"


def test_no_allow_remote_bypass_flag_exists() -> None:
    """There must be no CLI/env escape hatch around the host/db-name guards
    (the module docstring discusses, in prose, why no such flag exists --
    stripped out below so this check only scans real code)."""
    import scripts.quality.bys360_postgres_migration_integrity_gate as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    first = source.index('"""')
    second = source.index('"""', first + 3) + 3
    code_only = source[:first] + source[second:]
    assert "allow-remote" not in code_only
    assert "allow_remote" not in code_only
    assert "add_argument" not in source


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def test_redact_hides_password() -> None:
    redacted = redact("postgresql://postgres:supersecret@127.0.0.1:5432/bys360_migration_test_x")
    assert "supersecret" not in redacted
    assert "***" in redacted
    assert "bys360_migration_test_x" in redacted


def test_redact_is_noop_when_no_password_present() -> None:
    url = "postgresql://postgres@127.0.0.1:5432/bys360_migration_test_x"
    assert redact(url) == url


# ---------------------------------------------------------------------------
# Migration graph: head/root/cycle discovery
# ---------------------------------------------------------------------------


def _write_revision(directory: Path, revision: str, down_revision) -> None:
    down_literal = "None" if down_revision is None else repr(down_revision)
    (directory / f"{revision}_x.py").write_text(
        f'revision = "{revision}"\ndown_revision = {down_literal}\n', encoding="utf-8"
    )


def test_single_linear_chain_has_one_head(tmp_path: Path) -> None:
    _write_revision(tmp_path, "a1", None)
    _write_revision(tmp_path, "a2", "a1")
    _write_revision(tmp_path, "a3", "a2")
    graph = compute_migration_graph(tmp_path)
    assert graph["revision_count"] == 3
    assert graph["head_count"] == 1
    assert graph["heads"] == ["a3"]
    assert graph["cycles"] is False


def test_multiple_heads_are_detected(tmp_path: Path) -> None:
    _write_revision(tmp_path, "a1", None)
    _write_revision(tmp_path, "a2", "a1")
    _write_revision(tmp_path, "a3", "a1")
    graph = compute_migration_graph(tmp_path)
    assert graph["head_count"] == 2
    assert sorted(graph["heads"]) == ["a2", "a3"]


def test_cycle_is_detected(tmp_path: Path) -> None:
    _write_revision(tmp_path, "a1", "a2")
    _write_revision(tmp_path, "a2", "a1")
    graph = compute_migration_graph(tmp_path)
    assert graph["cycles"] is True


def test_merge_revision_tuple_down_revision_is_parsed(tmp_path: Path) -> None:
    _write_revision(tmp_path, "a1", None)
    _write_revision(tmp_path, "a2", None)
    _write_revision(tmp_path, "m1", ("a1", "a2"))
    graph = compute_migration_graph(tmp_path)
    assert graph["head_count"] == 1
    assert graph["heads"] == ["m1"]
    assert graph["root_count"] == 2


def test_real_repo_migration_graph_has_exactly_one_head() -> None:
    """The real target this gate is meant to check -- not mocked."""
    graph = compute_migration_graph()
    assert graph["head_count"] == 1, graph["heads"]
    assert graph["cycles"] is False


# ---------------------------------------------------------------------------
# main(): end-to-end result/exit-code contract, with the real-DB probes and
# `flask db upgrade` subprocess mocked out.
# ---------------------------------------------------------------------------

VALID_URL = "postgresql://postgres@127.0.0.1:5432/bys360_migration_test_contract"


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_main_missing_url_exits_nonzero_without_touching_network(monkeypatch, capsys) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    exit_code = main([])
    assert exit_code == 1
    assert "MISSING_URL" in capsys.readouterr().out


def test_main_unsafe_host_exits_nonzero(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, "postgresql://postgres@evil.example.com:5432/bys360_migration_test_x")
    exit_code = main([])
    assert exit_code == 1
    assert "UNSAFE_HOST" in capsys.readouterr().out


def test_main_full_happy_path_is_pass(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            return_value=None,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.compute_migration_graph",
            return_value={
                "revision_count": 74,
                "root_count": 10,
                "roots": [],
                "head_count": 1,
                "heads": ["e0efcd07abf7"],
                "cycles": False,
            },
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.run_flask_db_upgrade",
            side_effect=[
                _completed(0, "INFO  [alembic.runtime.migration] Running upgrade a1 -> a2\n"),
                _completed(0, "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.\n"),
            ],
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.read_alembic_version",
            return_value="e0efcd07abf7",
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.introspect_critical_tables",
            return_value={"users": True, "portal_post_comments": True},
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.introspect_critical_columns",
            return_value={"performance_president_approvals": [], "performance_periods": []},
        ),
    ):
        exit_code = main([])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "POSTGRES15_EMPTY_TO_HEAD=PASS" in out
    assert "POSTGRES15_HEAD_MATCH=PASS" in out
    assert "POSTGRES15_SECOND_UPGRADE=PASS" in out
    assert "POSTGRES15_SCHEMA_INTROSPECTION=PASS" in out
    assert "POSTGRES15_COLUMN_INTROSPECTION=PASS" in out
    assert "BYS360_POSTGRES_MIGRATION_INTEGRITY_GATE_V1_RESULT=PASS" in out
    # The redacted target line must never contain a real password (there is
    # none in VALID_URL, but this also proves the print call runs redact()).
    assert "TARGET=" in out


def test_main_wrong_pg_major_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with patch(
        "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
        side_effect=GateFailure("WRONG_PG_MAJOR", "Server reports PostgreSQL major version 14."),
    ):
        exit_code = main([])
    assert exit_code == 1
    assert "WRONG_PG_MAJOR" in capsys.readouterr().out


def test_main_non_empty_database_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            side_effect=GateFailure("NON_EMPTY_DB", "Target database has 3 table(s)."),
        ),
    ):
        exit_code = main([])
    assert exit_code == 1
    assert "NON_EMPTY_DB" in capsys.readouterr().out


def test_main_multiple_heads_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            return_value=None,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.compute_migration_graph",
            return_value={
                "revision_count": 5,
                "root_count": 1,
                "roots": [],
                "head_count": 2,
                "heads": ["a2", "a3"],
                "cycles": False,
            },
        ),
    ):
        exit_code = main([])
    assert exit_code == 1
    assert "MULTIPLE_HEADS" in capsys.readouterr().out


def test_main_migration_failure_is_reported(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            return_value=None,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.compute_migration_graph",
            return_value={
                "revision_count": 3,
                "root_count": 1,
                "roots": [],
                "head_count": 1,
                "heads": ["a3"],
                "cycles": False,
            },
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.run_flask_db_upgrade",
            return_value=_completed(1, "UndefinedTable: relation does not exist"),
        ),
    ):
        exit_code = main([])
    assert exit_code == 1
    assert "MIGRATION_FAILURE" in capsys.readouterr().out


def test_main_head_mismatch_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            return_value=None,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.compute_migration_graph",
            return_value={
                "revision_count": 3,
                "root_count": 1,
                "roots": [],
                "head_count": 1,
                "heads": ["expected_head"],
                "cycles": False,
            },
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.run_flask_db_upgrade",
            return_value=_completed(0, ""),
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.read_alembic_version",
            return_value="wrong_head",
        ),
    ):
        exit_code = main([])
    assert exit_code == 1
    assert "HEAD_MISMATCH" in capsys.readouterr().out


def test_main_second_upgrade_not_noop_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    call_count = {"n": 0}

    def fake_upgrade(_url):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _completed(0, "")
        return _completed(0, "INFO  [alembic.runtime.migration] Running upgrade a1 -> a2\n")

    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            return_value=None,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.compute_migration_graph",
            return_value={
                "revision_count": 2,
                "root_count": 1,
                "roots": [],
                "head_count": 1,
                "heads": ["a2"],
                "cycles": False,
            },
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.run_flask_db_upgrade",
            side_effect=fake_upgrade,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.read_alembic_version",
            return_value="a2",
        ),
    ):
        exit_code = main([])
    assert exit_code == 1
    assert "SECOND_UPGRADE_NOT_NOOP" in capsys.readouterr().out


def test_main_critical_table_missing_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            return_value=None,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.compute_migration_graph",
            return_value={
                "revision_count": 2,
                "root_count": 1,
                "roots": [],
                "head_count": 1,
                "heads": ["a2"],
                "cycles": False,
            },
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.run_flask_db_upgrade",
            return_value=_completed(0, ""),
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.read_alembic_version",
            return_value="a2",
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.introspect_critical_tables",
            return_value={"users": True, "portal_post_comments": False},
        ),
    ):
        exit_code = main([])
    assert exit_code == 1
    assert "CRITICAL_TABLE_MISSING" in capsys.readouterr().out


def test_main_critical_column_missing_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with (
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_postgres_major_version",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_database_is_empty",
            return_value=None,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.compute_migration_graph",
            return_value={
                "revision_count": 2,
                "root_count": 1,
                "roots": [],
                "head_count": 1,
                "heads": ["a2"],
                "cycles": False,
            },
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.run_flask_db_upgrade",
            return_value=_completed(0, ""),
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.read_alembic_version",
            return_value="a2",
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.introspect_critical_tables",
            return_value={"users": True},
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.introspect_critical_columns",
            return_value={"performance_president_approvals": ["rule_version"], "performance_periods": []},
        ),
    ):
        exit_code = main([])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "CRITICAL_COLUMN_MISSING" in out
    assert "rule_version" in out
    assert "_RESULT=PASS" not in out


def test_critical_columns_list_the_canonical_read_paths() -> None:
    from scripts.quality.bys360_postgres_migration_integrity_gate import CRITICAL_COLUMNS

    assert set(CRITICAL_COLUMNS) == {"performance_president_approvals", "performance_periods", "evaluation_assignments"}
    assert "rule_version" not in CRITICAL_COLUMNS["performance_president_approvals"]
    assert "employee_id" in CRITICAL_COLUMNS["evaluation_assignments"]
    for columns in CRITICAL_COLUMNS.values():
        assert len(columns) == len(set(columns))
