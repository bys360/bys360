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
    check_runtime_schema,
    compare_interim_notes_catalog,
    compute_migration_graph,
    compute_orm_gaps,
    load_interim_notes_contract,
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
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.load_orm_columns",
            return_value={"users": ["id", "email"]},
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.introspect_orm_parity",
            return_value={},
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.introspect_interim_notes_ownership",
            return_value=[],
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.check_runtime_schema",
            return_value=15,
        ),
        patch(
            "scripts.quality.bys360_postgres_migration_integrity_gate.rehearse_interim_notes_legacy_adoption",
            return_value={"MOBILE_VARIANT": "MOBILE_VARIANT adopted, sentinel preserved"},
        ),
    ):
        exit_code = main([])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "POSTGRES15_INTERIM_NOTES_ALEMBIC_OWNERSHIP=PASS" in out
    assert "POSTGRES15_INTERIM_NOTES_LEGACY_ADOPTION=PASS (1 cases: MOBILE_VARIANT)" in out
    assert "POSTGRES15_ORM_PARITY=PASS (checked 1 tables, 2 columns)" in out
    assert "POSTGRES15_RUNTIME_SCHEMA=PASS (provisioned and verified 15 groups" in out
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

    assert set(CRITICAL_COLUMNS) == {"performance_president_approvals", "performance_periods", "evaluation_assignments", "users"}
    assert "rule_version" not in CRITICAL_COLUMNS["performance_president_approvals"]
    assert "employee_id" in CRITICAL_COLUMNS["evaluation_assignments"]
    # Schema/runtime DDL wave 1: columns adopted into Alembic by w1c5a7d2e9b4.
    assert set(CRITICAL_COLUMNS["users"]) == {"birth_date", "hire_date", "celebration_opt_out"}
    assert {"evaluation_start_date", "evaluation_end_date", "evaluation_due_days"} <= set(CRITICAL_COLUMNS["performance_periods"])
    for columns in CRITICAL_COLUMNS.values():
        assert len(columns) == len(set(columns))


def test_orm_gaps_report_missing_tables_and_columns() -> None:
    present = {("users", "id"), ("users", "email"), ("performance_periods", "id")}
    orm = {
        "users": ["id", "email"],
        "performance_periods": ["id", "special_scenario_type"],
        "performance_low_score_processes": ["id"],
    }
    assert compute_orm_gaps(present, orm) == {
        "performance_low_score_processes": ["<table>"],
        "performance_periods": ["special_scenario_type"],
    }


def test_orm_gaps_are_empty_when_every_orm_column_exists() -> None:
    present = {("users", "id"), ("users", "email"), ("raw_sql_only_table", "id")}
    assert compute_orm_gaps(present, {"users": ["id", "email"]}) == {}


def test_main_orm_schema_gap_is_blocked(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    gate = "scripts.quality.bys360_postgres_migration_integrity_gate"
    graph = {"revision_count": 1, "root_count": 1, "roots": [], "head_count": 1, "heads": ["h1"], "cycles": False}
    with (
        patch(f"{gate}.check_postgres_major_version", return_value=15),
        patch(f"{gate}.check_database_is_empty", return_value=None),
        patch(f"{gate}.compute_migration_graph", return_value=graph),
        patch(f"{gate}.run_flask_db_upgrade", side_effect=[_completed(0), _completed(0)]),
        patch(f"{gate}.read_alembic_version", return_value="h1"),
        patch(f"{gate}.introspect_critical_tables", return_value={"users": True}),
        patch(f"{gate}.introspect_critical_columns", return_value={"users": []}),
        patch(f"{gate}.load_orm_columns", return_value={"performance_low_score_processes": ["id"]}),
        patch(f"{gate}.introspect_orm_parity", return_value={"performance_low_score_processes": ["<table>"]}),
    ):
        exit_code = main([])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "ORM_SCHEMA_MISSING" in out
    assert "performance_low_score_processes" in out


def _cli(returncode: int, *lines: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="".join(line + chr(10) for line in lines), stderr="")


GATE = "scripts.quality.bys360_postgres_migration_integrity_gate"


def test_runtime_schema_step_counts_verified_groups() -> None:
    runs = [
        _cli(0, "performance.a: provisioned t1", "mobile.b: already present"),
        _cli(0, "performance.a: OK", "mobile.b: OK"),
        _cli(0, "performance.a: already present", "mobile.b: already present"),
    ]
    with patch(f"{GATE}.run_flask_runtime_schema", side_effect=runs):
        assert check_runtime_schema(VALID_URL) == 2


def test_runtime_schema_step_fails_when_provision_fails() -> None:
    with (
        patch(f"{GATE}.run_flask_runtime_schema", side_effect=[_cli(1, "performance.a: STILL MISSING t1")]),
        pytest.raises(GateFailure) as excinfo,
    ):
        check_runtime_schema(VALID_URL)
    assert excinfo.value.code == "RUNTIME_SCHEMA_FAILURE"


def test_runtime_schema_step_fails_when_second_provision_changes_something() -> None:
    runs = [_cli(0, "performance.a: provisioned t1"), _cli(0, "performance.a: OK"), _cli(0, "performance.a: provisioned t1")]
    with patch(f"{GATE}.run_flask_runtime_schema", side_effect=runs), pytest.raises(GateFailure) as excinfo:
        check_runtime_schema(VALID_URL)
    assert excinfo.value.code == "RUNTIME_SCHEMA_NOT_IDEMPOTENT"


def test_runtime_schema_timeout_is_a_gate_failure() -> None:
    from scripts.quality.bys360_postgres_migration_integrity_gate import run_flask_runtime_schema

    with (
        patch(f"{GATE}.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="flask", timeout=1)),
        pytest.raises(GateFailure) as excinfo,
    ):
        run_flask_runtime_schema(VALID_URL, "provision")
    assert excinfo.value.code == "RUNTIME_SCHEMA_TIMEOUT"


# ---------------------------------------------------------------------------
# performance_interim_notes Alembic ownership (G3-A)
# ---------------------------------------------------------------------------

# information_schema.columns of the table as the former request-time helpers created it on
# PostgreSQL 15.19 (captured from the real helpers against disposable databases).
RUNTIME_HELPER_PG15_COLUMNS = [
    ('id', 'integer', None, 'NO', "nextval('performance_interim_notes_id_seq'::regclass)"),
    ('period_id', 'integer', None, 'YES', None),
    ('employee_id', 'integer', None, 'YES', None),
    ('employee_user_id', 'integer', None, 'YES', None),
    ('manager_id', 'integer', None, 'YES', None),
    ('created_by', 'integer', None, 'YES', None),
    ('created_by_id', 'integer', None, 'YES', None),
    ('note_type', 'character varying', 80, 'NO', "'genel_gozlem'::character varying"),
    ('title', 'character varying', 255, 'YES', None),
    ('note_title', 'character varying', 255, 'YES', None),
    ('note', 'text', None, 'YES', None),
    ('note_body', 'text', None, 'YES', None),
    ('note_text', 'text', None, 'YES', None),
    ('content', 'text', None, 'YES', None),
    ('description', 'text', None, 'YES', None),
    ('visibility_level', 'character varying', 80, 'NO', "'manager_scope'::character varying"),
    ('visibility_scope', 'character varying', 80, 'YES', "'manager_scope'::character varying"),
    ('remind_in_evaluation', 'boolean', None, 'YES', 'true'),
    ('remind_during_scoring', 'boolean', None, 'YES', 'true'),
    ('include_in_scorecard', 'boolean', None, 'YES', 'false'),
    ('visible_on_scorecard', 'boolean', None, 'YES', 'false'),
    ('is_active', 'boolean', None, 'YES', 'true'),
    ('active', 'boolean', None, 'YES', 'true'),
    ('occurred_at', 'timestamp without time zone', None, 'YES', 'CURRENT_TIMESTAMP'),
    ('created_at', 'timestamp without time zone', None, 'YES', 'CURRENT_TIMESTAMP'),
    ('updated_at', 'timestamp without time zone', None, 'YES', 'CURRENT_TIMESTAMP'),
]
MOBILE_FALLBACK_PG15_COLUMNS = [
    ('id', 'integer', None, 'NO', "nextval('performance_interim_notes_id_seq'::regclass)"),
    ('period_id', 'integer', None, 'YES', None),
    ('employee_id', 'integer', None, 'YES', None),
    ('employee_user_id', 'integer', None, 'YES', None),
    ('manager_id', 'integer', None, 'YES', None),
    ('created_by', 'integer', None, 'YES', None),
    ('created_by_id', 'integer', None, 'YES', None),
    ('note_type', 'character varying', 80, 'NO', "'genel_gozlem'::character varying"),
    ('title', 'character varying', 255, 'YES', None),
    ('note', 'text', None, 'YES', None),
    ('note_body', 'text', None, 'YES', None),
    ('visibility_level', 'character varying', 80, 'YES', "'manager_scope'::character varying"),
    ('remind_during_scoring', 'boolean', None, 'YES', 'true'),
    ('include_in_scorecard', 'boolean', None, 'YES', 'false'),
    ('is_active', 'boolean', None, 'YES', 'true'),
    ('occurred_at', 'timestamp without time zone', None, 'YES', 'CURRENT_TIMESTAMP'),
    ('created_at', 'timestamp without time zone', None, 'YES', 'CURRENT_TIMESTAMP'),
    ('updated_at', 'timestamp without time zone', None, 'YES', 'CURRENT_TIMESTAMP'),
]
CANONICAL_PG15_INDEXES = {
    "ix_perf_interim_notes_employee_period": ("employee_id", "period_id"),
    "ix_perf_interim_notes_employee_user_period": ("employee_user_id", "period_id"),
}


def _catalog(rows: list) -> list[dict]:
    keys = ("name", "data_type", "length", "is_nullable", "default")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def test_interim_notes_contract_equals_the_shape_the_runtime_helper_created_on_pg15() -> None:
    contract = load_interim_notes_contract()
    problems = compare_interim_notes_catalog(_catalog(RUNTIME_HELPER_PG15_COLUMNS), CANONICAL_PG15_INDEXES, ["id"], contract)
    assert problems == []


def test_interim_notes_contract_rejects_the_mobile_fallback_shape_and_missing_indexes() -> None:
    contract = load_interim_notes_contract()
    problems = compare_interim_notes_catalog(_catalog(MOBILE_FALLBACK_PG15_COLUMNS), {}, ["id"], contract)
    assert any(p.startswith("columns differ: missing ['active', 'content'") for p in problems)
    assert any(p.startswith("indexes {}") for p in problems)


def test_interim_notes_contract_rejects_type_nullability_default_and_pk_drift() -> None:
    contract = load_interim_notes_contract()
    rows = [list(row) for row in RUNTIME_HELPER_PG15_COLUMNS]
    by_name = {row[0]: row for row in rows}
    by_name["note_type"][2] = 40
    by_name["visibility_level"][3] = "YES"
    by_name["is_active"][4] = "false"
    problems = compare_interim_notes_catalog(_catalog(rows), CANONICAL_PG15_INDEXES, [], contract)
    assert any(p.startswith("note_type: type") for p in problems)
    assert any(p.startswith("visibility_level: is_nullable=YES") for p in problems)
    assert any(p.startswith("is_active: default") for p in problems)
    assert any(p.startswith("primary key") for p in problems)


def _main_until_interim_steps(monkeypatch, **interim_patches):
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    base = "scripts.quality.bys360_postgres_migration_integrity_gate."
    patches = {
        "check_postgres_major_version": {"return_value": 15},
        "check_database_is_empty": {"return_value": None},
        "compute_migration_graph": {"return_value": {"revision_count": 80, "root_count": 10, "roots": [], "head_count": 1,
                                                     "heads": ["x1f3a9c5e7b2"], "cycles": False}},
        "run_flask_db_upgrade": {"side_effect": [_completed(0, "Running upgrade a1 -> a2\n"), _completed(0, "")]},
        "read_alembic_version": {"return_value": "x1f3a9c5e7b2"},
        "introspect_critical_tables": {"return_value": {"users": True}},
        "introspect_critical_columns": {"return_value": {"users": []}},
        "load_orm_columns": {"return_value": {"users": ["id"]}},
        "introspect_orm_parity": {"return_value": {}},
        "check_runtime_schema": {"return_value": 15},
        **interim_patches,
    }
    from contextlib import ExitStack

    with ExitStack() as stack:
        for name, kwargs in patches.items():
            stack.enter_context(patch(base + name, **kwargs))
        return main([])


def test_main_interim_notes_contract_mismatch_is_blocked_before_runtime_schema(monkeypatch, capsys) -> None:
    runtime_schema = patch("scripts.quality.bys360_postgres_migration_integrity_gate.check_runtime_schema")
    with runtime_schema as runtime_mock:
        exit_code = _main_until_interim_steps(
            monkeypatch,
            introspect_interim_notes_ownership={"return_value": ["performance_interim_notes does not exist after flask db upgrade"]},
        )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "BYS360_POSTGRES_MIGRATION_INTEGRITY_GATE_V1_INTERIM_NOTES_CONTRACT_MISMATCH" in out
    assert "does not exist after flask db upgrade" in out
    runtime_mock.assert_not_called()


def test_main_interim_notes_legacy_adoption_failure_is_blocked(monkeypatch, capsys) -> None:
    exit_code = _main_until_interim_steps(
        monkeypatch,
        introspect_interim_notes_ownership={"return_value": []},
        rehearse_interim_notes_legacy_adoption={
            "side_effect": GateFailure("INTERIM_NOTES_LEGACY_ADOPTION_FAILURE", "MOBILE_VARIANT: sentinel rows changed")
        },
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "BYS360_POSTGRES_MIGRATION_INTEGRITY_GATE_V1_INTERIM_NOTES_LEGACY_ADOPTION_FAILURE" in out
    assert "BYS360_POSTGRES_MIGRATION_INTEGRITY_GATE_V1_RESULT=PASS" not in out
