"""Contract: both required CI workflows also run on pushes to the default branch.

assistant-v2-full is the repository's default branch and the base of every PR. The
workflows ran on pull requests into it, but a push to it (every PR merge) started no run:
"Run tests" (bys360-ci.yml) listed push branches main/master/develop only, and "BYS360
Quality Assurance Gate V1" (bys360-score100-quality-gate-v1.yml) had no push trigger at all.
The merged state of the default branch was therefore never verified by CI itself.

This test reads the workflow files as text (PyYAML is not a project dependency) and only
checks the trigger block; it does not run the workflows.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BRANCH = "assistant-v2-full"
WORKFLOWS = {
    "Run tests": ROOT / ".github" / "workflows" / "bys360-ci.yml",
    "BYS360 Quality Assurance Gate V1": ROOT / ".github" / "workflows" / "bys360-score100-quality-gate-v1.yml",
}


def _trigger_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^on:\n(.*?)^jobs:", text, flags=re.MULTILINE | re.DOTALL)
    assert match, f"{path.name}: no top-level 'on:' block before 'jobs:'"
    return match.group(1)


def _event_branches(block: str, event: str) -> list[str]:
    match = re.search(rf"^  {event}:\n    branches: \[([^\]]*)\]", block, flags=re.MULTILINE)
    assert match, f"no '{event}: branches: [...]' trigger"
    return [branch.strip() for branch in match.group(1).split(",") if branch.strip()]


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_runs_on_push_to_default_branch(name):
    branches = _event_branches(_trigger_block(WORKFLOWS[name]), "push")
    assert DEFAULT_BRANCH in branches, f"{name}: push trigger does not include {DEFAULT_BRANCH}"


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_still_runs_on_pull_requests_into_default_branch(name):
    branches = _event_branches(_trigger_block(WORKFLOWS[name]), "pull_request")
    assert DEFAULT_BRANCH in branches, f"{name}: pull_request trigger lost {DEFAULT_BRANCH}"


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_keeps_manual_dispatch(name):
    assert re.search(r"^  workflow_dispatch:", _trigger_block(WORKFLOWS[name]), flags=re.MULTILINE)


def test_run_tests_keeps_its_existing_push_branches():
    branches = _event_branches(_trigger_block(WORKFLOWS["Run tests"]), "push")
    assert {"main", "master", "develop"} <= set(branches)
