"""P2-07 guard: no repository test module is silently outside canonical CI.

Final pre-live audit (2026-09-27) found 11 tests that CI never executed:
tests/quality/test_settings_center_v2_menu_authorization_integrity_audit_v1.py
(9 tests, an authorization integrity audit) carried no ``ci_safe`` marker, so
the ``pytest tests/quality -m "ci_safe"`` step deselected it, and the two loose
tests/test_h1e_n_*.py files were never named in the broad coverage step, which
lists loose top-level files one by one.

This contract fails as soon as either blind spot reappears:
- every loose tests/test_*.py module is named in a CI pytest command;
- every tests/quality module is either ci_safe-marked or named explicitly.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.quality.bys360_quality9_ci_gate import workflow_run_commands

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "bys360-ci.yml"


def _pytest_commands() -> list[str]:
    return [c for c in workflow_run_commands(CI_WORKFLOW.read_text(encoding="utf-8")) if "pytest" in c]


def _named_paths() -> set[str]:
    return {token for command in _pytest_commands() for token in command.split() if token.startswith("tests/")}


def _declares_ci_safe(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "ci_safe":
            return True
    return False


def _loose_test_modules() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_*.py"))


def _quality_test_modules() -> list[Path]:
    return sorted((ROOT / "tests" / "quality").glob("test_*.py"))


def test_ci_has_exactly_one_ci_safe_quality_step() -> None:
    assert len([c for c in _pytest_commands() if "tests/quality" in c.split() and '-m "ci_safe"' in c]) == 1


@pytest.mark.parametrize("rel_path", _loose_test_modules())
def test_every_loose_top_level_test_module_is_named_in_ci(rel_path: str) -> None:
    assert rel_path in _named_paths(), f"{rel_path} is collected by no CI pytest command"


@pytest.mark.parametrize("path", _quality_test_modules(), ids=lambda p: p.name)
def test_every_quality_test_module_is_selected_by_ci(path: Path) -> None:
    rel_path = path.relative_to(ROOT).as_posix()
    assert _declares_ci_safe(path) or rel_path in _named_paths(), (
        f"{rel_path} has no ci_safe marker and is not named in a CI command -- CI never runs it"
    )


@pytest.mark.parametrize(
    "rel_path",
    [
        "tests/quality/test_settings_center_v2_menu_authorization_integrity_audit_v1.py",
        "tests/test_h1e_n_feedback_meeting_p4_archive_status_label_contract.py",
        "tests/test_h1e_n_team_compare_status_label_contract.py",
    ],
)
def test_audit_blind_spot_modules_still_exist(rel_path: str) -> None:
    assert (ROOT / rel_path).is_file()
