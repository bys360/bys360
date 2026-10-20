"""TD-032 closure -- PostgreSQL 15 migration-integrity CI enforcement contract.

Locks in that the real-PostgreSQL migration-integrity gate
(``scripts/quality/bys360_postgres_migration_integrity_gate.py``) is not
just a local ad-hoc script but genuinely wired into
``.github/workflows/bys360-ci.yml``: a ``postgres:15`` service container is
present, the gate is actually invoked (not merely referenced in a comment),
it does not use production secrets, it is not marked ``continue-on-error``
(an allow-failure step would make the gate decorative), and the pre-existing
Step1/Step2 pytest commands are unchanged by this addition -- this is meant
to be a purely additive CI change, not a rewrite of the existing gates.

Also locks in the ``quality-gate`` job's runtime budget (2026-08-17,
job-timeout unblock): a real remote run was cancelled by GitHub Actions at
~25m18s, mid-Step2, at 99% test progress, 0 failures/errors -- the job's own
``timeout-minutes: 25`` firing, not a hang or a test regression (confirmed:
no ``concurrency:`` block exists anywhere in this workflow, and no
superseding push landed before the cancellation). Local measurement this
session put Step2 alone at ~26-28 minutes on its own, before counting
checkout/install/Ruff/the PostgreSQL steps/coverage/mypy/quality9/pip-audit
that share the same job budget. The test below asserts a floor, not the
exact chosen value, so a future, evidence-based recalibration (e.g. if
Step2 grows further) isn't blocked by an over-fitted exact-match assertion.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "bys360-ci.yml"

STEP1_COMMAND_NEEDLE = 'pytest tests/quality -m "ci_safe"'
STEP2_COMMAND_NEEDLE = "pytest tests/integration tests/architecture tests/security"


def _workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_file_exists() -> None:
    assert CI_WORKFLOW.exists(), f"{CI_WORKFLOW} not found."


_MINIMUM_EVIDENCE_BACKED_TIMEOUT_MINUTES = 40
_KEY_LINE_RE = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_-]+):(?P<rest>.*)$")


def _job_level_timeout_minutes(text: str, job: str = "quality-gate") -> int:
    """Read ``jobs.<job>.timeout-minutes`` from the workflow's real YAML keys.

    The previous implementation took the first ``timeout-minutes: <n>``
    regex match in the job header. That header carries history comments
    ("cancelled by its own timeout-minutes: 45 ..."), so the guard read 45
    from a comment and passed even with a real ``timeout-minutes: 10``.
    This reader skips comment lines, strips trailing comments, and only
    accepts the key at the job's own property indentation -- so a comment
    or a step-level ``timeout-minutes`` can never stand in for the job
    value. A missing, duplicated or non-integer job-level key fails loudly.
    """
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    jobs_at = next((i for i, line in enumerate(lines) if line == "jobs:"), None)
    assert jobs_at is not None, "Workflow has no top-level `jobs:` key."

    assert jobs_at + 1 < len(lines), "Workflow `jobs:` block is empty."
    # The first line after `jobs:` is a job id (quoted or not); its indentation is the job level.
    jobs_child_indent = len(lines[jobs_at + 1]) - len(lines[jobs_at + 1].lstrip(" "))
    assert jobs_child_indent > 0, "Workflow `jobs:` block is empty."
    job_at = job_indent = None
    for i in range(jobs_at + 1, len(lines)):
        match = _KEY_LINE_RE.match(lines[i])
        if not match:
            continue
        indent = len(match.group("indent"))
        if indent == 0:
            break
        if indent != jobs_child_indent:
            continue  # a nested key inside another job, never a job id
        if match.group("key") == job and match.group("rest").split("#", 1)[0].strip() == "":
            job_at, job_indent = i, indent
            break
    assert job_at is not None and job_indent is not None, f"Workflow has no `jobs.{job}` block."

    body = []
    for line in lines[job_at + 1 :]:
        if len(line) - len(line.lstrip(" ")) <= job_indent:
            break
        body.append(line)
    assert body, f"`jobs.{job}` block is empty."
    property_indent = len(body[0]) - len(body[0].lstrip(" "))

    values = []
    for line in body:
        match = _KEY_LINE_RE.match(line)
        if match and len(match.group("indent")) == property_indent and match.group("key") == "timeout-minutes":
            values.append(match.group("rest").split("#", 1)[0].strip().strip("'\""))
    assert len(values) == 1, (
        f"Expected exactly one job-level `timeout-minutes` in `jobs.{job}`, found {len(values)}."
    )
    assert values[0].isdigit(), f"`jobs.{job}.timeout-minutes` is not an integer: {values[0]!r}."
    return int(values[0])


def test_quality_gate_job_timeout_has_an_evidence_backed_floor() -> None:
    """Regression guard for the exact remote failure this wave fixed: the
    job was killed by its own `timeout-minutes` mid-Step2 at 99% progress,
    0 test failures. Asserts a FLOOR (not the exact current value) so a
    future, deliberate, evidence-based change (e.g. Step2 growing further)
    isn't blocked by an over-fitted exact-match assertion -- but a
    regression back toward the old, proven-insufficient 25 minutes is
    caught immediately."""
    timeout_minutes = _job_level_timeout_minutes(_workflow_text())
    assert timeout_minutes >= _MINIMUM_EVIDENCE_BACKED_TIMEOUT_MINUTES, (
        f"quality-gate timeout-minutes is {timeout_minutes}; must be at least "
        f"{_MINIMUM_EVIDENCE_BACKED_TIMEOUT_MINUTES} (local measurement: Step2 alone "
        "takes ~26-28 minutes, before checkout/install/Ruff/PostgreSQL/coverage/mypy/"
        "quality9/pip-audit in the same job budget)."
    )


_JOB_LEVEL_TIMEOUT_LINE_RE = re.compile(r"^    timeout-minutes: \d+$", re.MULTILINE)


def _workflow_with_job_timeout(minutes: int) -> str:
    """The real workflow text with only the job-level value replaced."""
    text = _workflow_text()
    assert len(_JOB_LEVEL_TIMEOUT_LINE_RE.findall(text)) == 1
    return _JOB_LEVEL_TIMEOUT_LINE_RE.sub(f"    timeout-minutes: {minutes}", text)


def test_timeout_reader_returns_the_real_value_not_the_history_comment() -> None:
    """Negative regression for the false pass: with a real 10-minute value the
    header comments still say "timeout-minutes: 45"; the reader must return 10
    and the floor must reject it."""
    text = _workflow_with_job_timeout(10)
    assert "timeout-minutes: 45" in text, "premise: the history comment is still there"
    assert _job_level_timeout_minutes(text) == 10
    assert _job_level_timeout_minutes(text) < _MINIMUM_EVIDENCE_BACKED_TIMEOUT_MINUTES


@pytest.mark.parametrize("minutes", [180, 240])
def test_timeout_reader_accepts_real_evidence_backed_values(minutes: int) -> None:
    """Positive regression: the real 180 (base) and 240 (#84) values are read
    exactly and clear the floor."""
    value = _job_level_timeout_minutes(_workflow_with_job_timeout(minutes))
    assert value == minutes
    assert value >= _MINIMUM_EVIDENCE_BACKED_TIMEOUT_MINUTES


_SYNTHETIC_WORKFLOW = """\
name: t
on: [push]
jobs:
  other-job:
    runs-on: ubuntu-latest
    timeout-minutes: 999
  quality-gate:
    runs-on: ubuntu-latest
    # cancelled by its own timeout-minutes: 45 mid-Step2
    timeout-minutes: {value}
    steps:
      - name: slow step
        timeout-minutes: 500
        run: echo "timeout-minutes: 600"
"""


def test_timeout_reader_ignores_comments_other_jobs_and_step_level_keys() -> None:
    assert _job_level_timeout_minutes(_SYNTHETIC_WORKFLOW.format(value="10")) == 10
    assert _job_level_timeout_minutes(_SYNTHETIC_WORKFLOW.format(value="240  # trailing note")) == 240


def test_timeout_reader_ignores_a_nested_quality_gate_key_inside_another_job() -> None:
    """A mapping key named ``quality-gate`` nested in an earlier job (here under
    ``env:``) is not the job; only a direct child of ``jobs:`` is."""
    nested_first = _SYNTHETIC_WORKFLOW.replace(
        "    timeout-minutes: 999\n",
        "    timeout-minutes: 999\n    env:\n      quality-gate:\n        timeout-minutes: 5\n",
    )
    assert "      quality-gate:\n        timeout-minutes: 5" in nested_first
    assert _job_level_timeout_minutes(nested_first.format(value="240")) == 240


def test_timeout_reader_does_not_take_a_property_key_for_a_quoted_job_id() -> None:
    """With a quoted first job id the job level is still the first line's
    indentation, so a nested ``quality-gate:`` (here at property level) is not
    taken as the job; the unquoted id the reader looks for is then missing."""
    quoted = "jobs:\n  'other':\n    quality-gate:\n      timeout-minutes: 99\n"
    with pytest.raises(AssertionError, match="no `jobs.quality-gate` block"):
        _job_level_timeout_minutes(quoted)


@pytest.mark.parametrize("minutes", [10, 39])
def test_floor_test_fails_for_a_real_value_below_the_floor(minutes: int) -> None:
    """End to end with the real workflow text: below 40 the guard's own
    comparison rejects the value the reader returns (the old regex read 45
    from the history comment and passed)."""
    value = _job_level_timeout_minutes(_workflow_with_job_timeout(minutes))
    assert value == minutes
    assert not value >= _MINIMUM_EVIDENCE_BACKED_TIMEOUT_MINUTES


@pytest.mark.parametrize(
    "broken",
    [
        _SYNTHETIC_WORKFLOW.replace("    timeout-minutes: {value}\n", ""),
        _SYNTHETIC_WORKFLOW.format(value="10") + "    timeout-minutes: 240\n",
        _SYNTHETIC_WORKFLOW.format(value="${{ vars.TIMEOUT }}"),
    ],
    ids=["missing", "duplicated", "not-an-integer"],
)
def test_timeout_reader_fails_loudly_instead_of_guessing(broken: str) -> None:
    with pytest.raises(AssertionError):
        _job_level_timeout_minutes(broken)


def test_postgres_15_service_is_declared() -> None:
    text = _workflow_text()
    assert "services:" in text
    assert "postgres:" in text
    assert "image: postgres:15" in text


def test_postgres_service_has_a_healthcheck() -> None:
    text = _workflow_text()
    assert "pg_isready" in text, "postgres service must gate readiness with pg_isready (or equivalent)."


def test_migration_integrity_gate_script_is_actually_invoked() -> None:
    text = _workflow_text()
    assert "run: python scripts/quality/bys360_postgres_migration_integrity_gate.py" in text, (
        "The gate script must be genuinely invoked as a `run:` command, not just mentioned "
        "in a comment."
    )


def test_migration_integrity_gate_script_exists() -> None:
    gate_path = REPO_ROOT / "scripts" / "quality" / "bys360_postgres_migration_integrity_gate.py"
    assert gate_path.exists(), f"{gate_path} referenced by CI but missing."


def test_gate_env_var_is_wired_and_points_at_the_ci_service_host() -> None:
    text = _workflow_text()
    assert "BYS360_REALDB_MIGRATION_TEST_URL:" in text
    assert "@127.0.0.1:5432/bys360_migration_test_ci" in text, (
        "TD-032 remote-CI unblock (2026-08-17): this job has no job-level `container:`, "
        "so it cannot resolve the postgres service's Docker-network label ('postgres') -- "
        "only its published loopback port. See "
        "test_create_db_step_and_harness_step_use_the_same_reachable_host below for the "
        "full regression guard."
    )


_DSN_HOST_RE = re.compile(r"host='([^']+)'")
_URL_HOST_RE = re.compile(r"@([^:/]+):5432/bys360_migration_test_ci")


def test_create_db_step_and_harness_step_use_the_same_reachable_host() -> None:
    """Regression guard for the exact remote failure this wave fixed:
    `psycopg2.OperationalError: could not translate host name "postgres" to
    address: Temporary failure in name resolution`. This job has no
    job-level `container:`, so it runs directly on the runner host, not on
    the same Docker network as the `postgres` service container -- the
    service's Docker-network label is only resolvable from *other
    containers* on that job's network. A host-runner job must use the
    service's published port on the loopback interface instead (already
    published: `ports: - 5432:5432` on the service). If this job is ever
    moved under a job-level `container:`, this test's premise (and the
    workflow's DSN hosts) needs re-deriving, not just re-asserting."""
    text = _workflow_text()
    job_header = text[text.index("runs-on: ubuntu-latest") : text.index("\n    steps:")]
    assert "container:" not in job_header, (
        "quality-gate now has a job-level `container:` -- the loopback-host requirement "
        "this test enforces no longer applies as-is; re-derive the correct DSN host for "
        "the new topology instead of just updating this assertion."
    )

    create_step_match = _DSN_HOST_RE.search(text)
    assert create_step_match, "Could not find the create-database step's psycopg2.connect host=... argument."
    create_step_host = create_step_match.group(1)

    harness_step_match = _URL_HOST_RE.search(text)
    assert harness_step_match, "Could not find the migration gate's BYS360_REALDB_MIGRATION_TEST_URL host."
    harness_step_host = harness_step_match.group(1)

    assert create_step_host == "127.0.0.1", (
        f"Create-database step host is {create_step_host!r}; a host-runner job with no "
        "job-level `container:` cannot resolve the postgres service's Docker-network "
        "label and must use its published loopback port (127.0.0.1) instead."
    )
    assert harness_step_host == "127.0.0.1", (
        f"Migration gate host is {harness_step_host!r}; must be 127.0.0.1 for the same "
        "host-runner-vs-service-container reason as the create-database step."
    )
    assert create_step_host == harness_step_host, (
        f"Create-database step host {create_step_host!r} and migration gate host "
        f"{harness_step_host!r} must be identical -- both connect to the same disposable "
        "PostgreSQL service."
    )


def test_no_production_secret_pattern_used_for_the_ci_postgres_credentials() -> None:
    """The CI-only disposable password is a literal, self-documenting
    placeholder hardcoded in the workflow -- not read from a real secret
    store or an ``.env`` file (this repo's real secrets live in an
    untracked ``.env``, never committed and never referenced here)."""
    text = _workflow_text()
    assert "bys360_ci_test_only_password" in text
    assert ".env" not in text
    assert "${{ secrets." not in text, (
        "This workflow defines no GitHub Actions repository secrets to read; the "
        "PostgreSQL credentials are disposable, CI-local, and hardcoded on purpose."
    )


def test_migration_integrity_gate_step_is_not_allow_failure() -> None:
    """An allow-failure migration gate would be decorative, not enforcement."""
    text = _workflow_text()
    gate_step_start = text.index("- name: PostgreSQL 15 migration integrity gate")
    next_step_start = text.find("\n      - name:", gate_step_start + 1)
    gate_step_text = text[gate_step_start : next_step_start if next_step_start != -1 else len(text)]
    assert "continue-on-error" not in gate_step_text


def test_step1_pytest_command_is_unchanged() -> None:
    text = _workflow_text()
    assert STEP1_COMMAND_NEEDLE in text


def test_step2_pytest_command_is_unchanged() -> None:
    text = _workflow_text()
    assert STEP2_COMMAND_NEEDLE in text


def test_existing_named_steps_are_all_still_present() -> None:
    """Every step name this workflow had before the TD-032 PostgreSQL
    addition is still present, unrenamed and unremoved -- this addition
    only inserts new steps, it does not touch any existing one."""
    text = _workflow_text()
    pre_existing_step_names = (
        "Checkout",
        "Set up Python 3.12",
        "Install dependencies",
        "BYS360 secret/repo gate",
        "Build safe release audit",
        "Ruff full-select gate (E,F,I,UP,B,SIM)",
        "Compile Python source",
        "BYS360 safe release audit",
        "Run quality tests",
        "Run integration and architecture tests",
        "Coverage ratchet gate",
        "Type check service layer",
        "BYS360 operations audit",
        "BYS360 Quality 9 CI contract gate",
        "Ruff syntax/import sanity",
        "Dependency vulnerability audit",
        "Upload quality reports",
    )
    for step_name in pre_existing_step_names:
        assert f"- name: {step_name}" in text, f"Pre-existing step {step_name!r} is missing or renamed."


def test_new_steps_do_not_shadow_an_existing_step_name() -> None:
    text = _workflow_text()
    new_step_names = (
        "Create disposable PostgreSQL 15 migration-test database",
        "PostgreSQL 15 migration integrity gate",
    )
    for step_name in new_step_names:
        assert text.count(f"- name: {step_name}") == 1
