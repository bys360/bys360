"""Contract tests for scripts/quality/bys360_postgres_race_gate.py and its CI wiring.

Static/mocked: they prove the gate's guards (URL, PostgreSQL major version,
skip/count/failure accounting) and that the workflow really invokes it against
the postgres:15 service. They do NOT replace the real PostgreSQL 15 run; that
is the CI step itself.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.quality import bys360_postgres_race_gate as gate
from scripts.quality.bys360_postgres_race_gate import (
    ENV_VAR,
    EXPECTED_TEST_COUNT,
    RACE_TESTS,
    GateFailure,
    evaluate_junit,
    main,
    parse_major,
    redact,
    validate_url,
)

pytestmark = pytest.mark.ci_safe

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "bys360-ci.yml"
VALID_URL = "postgresql://postgres:pw@127.0.0.1:5432/bys360_race_test_ci"
STEP_NAME = "PostgreSQL 15 race tests"
CREATE_STEP_NAME = "Create disposable PostgreSQL 15 race-test database"


def _junit(tmp_path: Path, *, tests: int, failures: int = 0, errors: int = 0, skipped: int = 0, wrapped: bool = True) -> Path:
    suite = f'<testsuite name="pytest" tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"></testsuite>'
    path = tmp_path / "race.xml"
    path.write_text(f"<testsuites>{suite}</testsuites>" if wrapped else suite, encoding="utf-8")
    return path


def _step(text: str, name: str) -> str:
    start = text.index(f"- name: {name}\n")
    end = text.find("\n      - name:", start + 1)
    return text[start : end if end != -1 else len(text)]


# --- URL guards ---


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("", "MISSING_URL"),
        ("mysql://postgres@127.0.0.1:5432/bys360_race_test_ci", "UNSAFE_SCHEME"),
        ("postgresql://postgres@db.example.org:5432/bys360_race_test_ci", "UNSAFE_HOST"),
        ("postgresql://postgres@postgres:5432/bys360_race_test_ci", "UNSAFE_HOST"),
        ("postgresql://postgres@127.0.0.1:5432/postgres", "UNSAFE_DB_NAME"),
        ("postgresql://postgres@127.0.0.1:5432/bys360", "UNSAFE_DB_NAME"),
        ("postgresql://postgres@127.0.0.1:5432/bys360_migration_test_ci", "UNSAFE_DB_NAME"),
    ],
)
def test_unsafe_targets_are_refused(url: str, code: str) -> None:
    with pytest.raises(GateFailure) as excinfo:
        validate_url(url)
    assert excinfo.value.code == code


def test_disposable_local_target_is_accepted() -> None:
    assert validate_url(VALID_URL).hostname == "127.0.0.1"


def test_redact_hides_the_password() -> None:
    assert redact(VALID_URL) == "postgresql://postgres:***@127.0.0.1:5432/bys360_race_test_ci"


# --- PostgreSQL major version ---


@pytest.mark.parametrize(("version", "major"), [("15.8 (Debian 15.8-1.pgdg120+1)", 15), ("16.4", 16), ("", -1)])
def test_parse_major(version: str, major: int) -> None:
    assert parse_major(version) == major


def test_a_postgresql_16_server_fails_the_gate_before_any_test_runs(monkeypatch, capsys) -> None:
    monkeypatch.setenv(ENV_VAR, VALID_URL)
    with patch.object(gate, "check_postgres_major_version", side_effect=GateFailure("WRONG_PG_MAJOR", "16.4")), patch.object(
        gate, "run_race_tests"
    ) as run:
        assert main() == 1
    run.assert_not_called()
    out = capsys.readouterr().out
    assert "WRONG_PG_MAJOR" in out
    assert ":pw@" not in out


def test_an_unreachable_server_is_a_gate_failure_not_a_traceback() -> None:
    import psycopg2

    with patch.object(psycopg2, "connect", side_effect=psycopg2.OperationalError("no route")), pytest.raises(GateFailure) as excinfo:
        gate.check_postgres_major_version(validate_url(VALID_URL))
    assert excinfo.value.code == "CONNECT_FAILED"


# --- pytest result accounting ---


def test_all_expected_tests_passing_is_accepted(tmp_path: Path) -> None:
    assert evaluate_junit(_junit(tmp_path, tests=EXPECTED_TEST_COUNT))["tests"] == EXPECTED_TEST_COUNT
    assert evaluate_junit(_junit(tmp_path, tests=EXPECTED_TEST_COUNT, wrapped=False))["tests"] == EXPECTED_TEST_COUNT


@pytest.mark.parametrize(
    ("counts", "code"),
    [
        ({"tests": EXPECTED_TEST_COUNT, "skipped": 2}, "SKIPPED"),
        ({"tests": EXPECTED_TEST_COUNT, "failures": 1}, "FAILED"),
        ({"tests": EXPECTED_TEST_COUNT, "errors": 1}, "FAILED"),
        ({"tests": EXPECTED_TEST_COUNT - 1}, "WRONG_COUNT"),
        ({"tests": 0}, "WRONG_COUNT"),
    ],
)
def test_a_skip_failure_or_missing_test_fails_the_gate(tmp_path: Path, counts: dict, code: str) -> None:
    with pytest.raises(GateFailure) as excinfo:
        evaluate_junit(_junit(tmp_path, **counts))
    assert excinfo.value.code == code


def test_the_selected_race_tests_exist() -> None:
    for node in RACE_TESTS:
        path, _, name = node.partition("::")
        source = (ROOT / path).read_text(encoding="utf-8")
        if name:
            assert re.search(rf"^def {re.escape(name)}\(", source, re.MULTILINE), node
    # two parametrised cases in test_r05d + the two R05c tests
    assert EXPECTED_TEST_COUNT == 4


# --- CI wiring ---


def test_the_race_gate_step_runs_against_the_postgres_15_service() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "image: postgres:15" in text
    assert text.count(f"- name: {STEP_NAME}\n") == 1
    assert text.count(f"- name: {CREATE_STEP_NAME}\n") == 1
    step = _step(text, STEP_NAME)
    assert "run: python scripts/quality/bys360_postgres_race_gate.py" in step
    assert "continue-on-error" not in step and "|| true" not in step
    url = re.search(rf"{ENV_VAR}: (\S+)", step)
    assert url, "the step must set the race-test database URL"
    parts = validate_url(url.group(1))
    create = _step(text, CREATE_STEP_NAME)
    assert "host='127.0.0.1'" in create
    assert f"CREATE DATABASE {(parts.path or '').lstrip('/')};" in create
    assert text.index(CREATE_STEP_NAME) < text.index(f"- name: {STEP_NAME}\n")
