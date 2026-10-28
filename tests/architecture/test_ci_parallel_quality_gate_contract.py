"""Contract: the parallel quality gate of .github/workflows/bys360-ci.yml stays complete and strict.

Since 2026-10-28 (PR #92) the old single quality-gate job runs as three jobs: the unchanged
Step2 command in a matrix of shards (quality-gate-tests), every other gate in parallel
(quality-gate-checks), and the required check quality-gate, which always runs, requires both
jobs to have succeeded, proves that the shards ran every collected test once, combines the
coverage and runs the ratchet. This contract fails if any of that is weakened: a job that can be
skipped into a pass, a shard count that the gate does not check, a gate that moved out of CI, or a
shard budget below the measured shard runtime.

The workflow is read as text (PyYAML is not a project dependency).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.ci.bys360_pytest_shard import assign_files

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "bys360-ci.yml"
WEIGHTS = ROOT / "config" / "quality" / "bys360_ci_step2_test_durations.json"
STEP2_NEEDLE = "pytest tests/integration tests/architecture tests/security"
# 28 Oct 2026: the slower GitHub runners needed 1.28x the 17f9cdb3 green run's time for the same
# Step2 tests (cancelled runs 40656101048 attempt 2 and 40727993522 against job 122504819166).
SLOW_RUNNER_FACTOR = 1.28
# A shard must fit its budget at that speed with this margin left for checkout/install/collection.
SHARD_BUDGET_MARGIN = 1.5

# Every gate of the old single job besides Step2, the ratchet and the report upload.
CHECK_STEPS = (
    "BYS360 secret/repo gate",
    "Build safe release audit",
    "Ruff full-select gate (E,F,I,UP,B,SIM)",
    "Compile Python source",
    "BYS360 safe release audit",
    "Run quality tests",
    "Create disposable PostgreSQL 15 race-test database",
    "PostgreSQL 15 race tests",
    "Create disposable PostgreSQL 15 migration-test database",
    "PostgreSQL 15 migration integrity gate",
    "Type check service layer",
    "BYS360 operations audit",
    "BYS360 Quality 9 CI contract gate",
    "Ruff syntax/import sanity",
    "Dependency vulnerability audit",
    "Dependency vulnerability audit (requirements.lock)",
)


def _jobs() -> dict[str, str]:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    body = text[text.index("\njobs:\n") :]
    keys = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", body, flags=re.MULTILINE))
    return {
        match.group(1): body[match.end() : keys[i + 1].start() if i + 1 < len(keys) else len(body)]
        for i, match in enumerate(keys)
    }


def _steps(job: str) -> list[str]:
    return re.findall(r"^      - name: (.+)$", job, flags=re.MULTILINE)


def _step(job: str, name: str) -> str:
    start = job.index(f"      - name: {name}\n")
    following = job.find("\n      - name: ", start + 1)
    return job[start : following if following != -1 else len(job)]


def _timeout(job: str) -> int:
    match = re.search(r"^    timeout-minutes:\s*(\d+)", job, flags=re.MULTILINE)
    assert match, "job without timeout-minutes"
    return int(match.group(1))


def _shard_count() -> int:
    match = re.search(r"^        shard: \[([0-9, ]+)\]$", _jobs()["quality-gate-tests"], flags=re.MULTILINE)
    assert match, "quality-gate-tests has no shard matrix"
    shards = [int(value) for value in match.group(1).split(",")]
    assert shards == list(range(1, len(shards) + 1)), f"shards must be 1..N, got {shards}"
    return len(shards)


def test_the_workflow_has_exactly_the_three_quality_gate_jobs() -> None:
    assert set(_jobs()) == {"quality-gate", "quality-gate-checks", "quality-gate-tests"}


def test_the_required_check_keeps_its_name_and_can_never_be_skipped_into_a_pass() -> None:
    job = _jobs()["quality-gate"]
    header = job[: job.index("\n    steps:")]
    assert not re.search(r"^    name:", header, flags=re.MULTILINE), "the required check is named by its job key"
    assert "needs: [quality-gate-checks, quality-gate-tests]" in header
    assert "if: ${{ always() }}" in header, "a skipped required check counts as passed on GitHub"


def test_the_required_check_fails_unless_every_job_succeeded() -> None:
    job = _jobs()["quality-gate"]
    assert _steps(job)[0] == "Require every quality-gate job to pass"
    step = _step(job, "Require every quality-gate job to pass")
    assert "CHECKS_RESULT: ${{ needs.quality-gate-checks.result }}" in step
    assert "TESTS_RESULT: ${{ needs.quality-gate-tests.result }}" in step
    assert 'test "$CHECKS_RESULT" = success' in step
    assert 'test "$TESTS_RESULT" = success' in step


def test_the_required_check_verifies_the_shards_and_combines_coverage_before_the_ratchet() -> None:
    job = _jobs()["quality-gate"]
    steps = _steps(job)
    order = [
        "Download quality test and shard results",
        "Verify the test shards ran every collected test once",
        "Combine coverage of the quality tests and every shard",
        "Coverage ratchet gate",
        "Upload quality reports",
    ]
    assert [name for name in steps if name in order] == order
    verify = _step(job, "Verify the test shards ran every collected test once")
    assert f"--shards {_shard_count()}" in verify
    assert "scripts/ci/bys360_verify_test_shards.py --data-dir ci-data" in verify
    combine = _step(job, "Combine coverage of the quality tests and every shard")
    inputs = "ci-data/bys360-ci-quality-tests/coverage-quality-tests ci-data/bys360-ci-step2-shard-*/coverage-step2-shard-*"
    gate = f"python scripts/ci/bys360_verify_coverage_inputs.py --root . {inputs}"
    assert gate in combine and f"coverage combine --keep {inputs}" in combine
    assert combine.index(gate) < combine.index("coverage combine"), "inputs are checked before they are combined"
    assert "ci-data/bys360-ci-quality-tests/coverage-quality-tests" in combine
    assert "ci-data/bys360-ci-step2-shard-*/coverage-step2-shard-*" in combine
    assert "coverage xml -o reports/quality/coverage.xml" in combine
    assert "pattern: bys360-ci-*" in _step(job, "Download quality test and shard results")


def test_every_shard_runs_the_unchanged_step2_command_with_the_shard_plugin() -> None:
    jobs = _jobs()
    assert [name for name, job in jobs.items() if STEP2_NEEDLE in job] == ["quality-gate-tests"]
    job = jobs["quality-gate-tests"]
    step = _step(job, "Run integration and architecture tests")
    count = _shard_count()
    assert f"BYS360_CI_SHARD: ${{{{ matrix.shard }}}}/{count}" in step
    assert "BYS360_CI_SHARD_MANIFEST: reports/quality/step2-shard-manifest.json" in step
    command = step[step.index("run: python -m pytest") :]
    assert "-p scripts.ci.bys360_pytest_shard" in command
    assert "--junitxml=reports/quality/step2-junit.xml" in command
    assert "fail-fast: false" in job, "one failing shard must not cancel the others' evidence"


def test_every_shard_always_uploads_its_coverage_manifest_and_junit_report() -> None:
    job = _jobs()["quality-gate-tests"]
    save = _step(job, "Save shard results")
    upload = _step(job, "Upload shard results")
    assert "if: always()" in save and "if: always()" in upload
    assert "cp .coverage ci-data/coverage-step2-shard-${{ matrix.shard }}" in save
    assert "reports/quality/step2-shard-manifest.json reports/quality/step2-junit.xml ci-data/" in save
    assert "name: bys360-ci-step2-shard-${{ matrix.shard }}" in upload
    assert "if-no-files-found: error" in upload


def test_every_other_gate_of_the_old_job_still_runs_in_quality_gate_checks() -> None:
    job = _jobs()["quality-gate-checks"]
    steps = _steps(job)
    assert [name for name in steps if name in CHECK_STEPS] == list(CHECK_STEPS)
    assert "image: postgres:15" in job
    upload = _step(job, "Upload quality test coverage data")
    assert "name: bys360-ci-quality-tests" in upload and "if-no-files-found: error" in upload
    assert "cp .coverage ci-data/coverage-quality-tests" in _step(job, "Save quality test coverage data")


def test_no_job_can_pass_with_a_failing_step() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in text
    assert "|| true" not in text


def test_the_shard_budget_covers_the_measured_shard_runtime() -> None:
    doc = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = {path: float(seconds) for path, seconds in doc["files"].items()}
    loads = [0.0] * _shard_count()
    for path, shard in assign_files(weights, len(loads)).items():
        loads[shard - 1] += weights[path]
    heaviest_minutes = max(loads) / 60
    timeout = _timeout(_jobs()["quality-gate-tests"])
    assert heaviest_minutes * SLOW_RUNNER_FACTOR * SHARD_BUDGET_MARGIN <= timeout, (
        f"the heaviest shard needs {heaviest_minutes:.1f} min on the reference runner; "
        f"timeout-minutes {timeout} leaves too little room -- add shards rather than raising the budget"
    )
