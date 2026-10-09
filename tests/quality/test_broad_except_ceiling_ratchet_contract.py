"""Contract: the CI broad-except ceiling equals the measured count (a real ratchet).

The "BYS360 operations audit" CI step runs scripts/quality/bys360_ops_audit.py with
``--max-broad-except`` and fails the job when ``except Exception`` handlers in
app/, config.py, wsgi.py and run.py exceed it. The ceiling was 2300 while the code
had 2064 such handlers (the same count in every CI run of 2026-10-07/08), so up to
236 new broad handlers could be added without any gate noticing.

Counting methods, both AST-based:
- ops audit (``--source-paths app config.py wsgi.py run.py``): 2064 = 2063 in app/
  + 1 in config.py (wsgi.py and run.py have none);
- Quality 9 gate (app/ only): 2063.

The ceiling is now the measured ops-audit count, and the Quality 9 default target is
the same number, so the gate also rejects a workflow that loosens the flag again.
When broad handlers are removed, this test fails until the ceiling is lowered to the
new count: the ceiling only moves down.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.quality import bys360_ops_audit as ops_audit, bys360_quality9_ci_gate as quality9

pytestmark = pytest.mark.ci_safe

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "bys360-ci.yml"
OPS_AUDIT_SOURCE_PATHS = ["app", "config.py", "wsgi.py", "run.py"]


def _workflow_ceiling() -> int:
    values = re.findall(r"bys360_ops_audit\.py[^\n]*--max-broad-except\s+(\d+)", WORKFLOW.read_text(encoding="utf-8"))
    assert len(values) == 1, f"expected exactly one ops-audit --max-broad-except in the CI workflow, found {values}"
    return int(values[0])


def _measured_count() -> int:
    report = ops_audit.build_report(ROOT, "ci", OPS_AUDIT_SOURCE_PATHS)
    return int(report["totals"]["broad_except_exception"])


def test_ci_broad_except_ceiling_has_no_unused_headroom() -> None:
    ceiling = _workflow_ceiling()
    measured = _measured_count()
    assert measured <= ceiling, f"{measured} broad except handlers exceed the CI ceiling {ceiling}"
    assert ceiling == measured, (
        f"CI --max-broad-except is {ceiling} but the code has {measured}; "
        "lower the ceiling in .github/workflows/bys360-ci.yml and "
        "scripts/quality/bys360_quality9_ci_gate.py to the measured count"
    )


def test_quality9_target_matches_the_ci_ceiling() -> None:
    ceiling = _workflow_ceiling()
    assert ceiling == quality9.DEFAULT_QUALITY9_MAX_APP_BROAD_EXCEPT
    assert quality9.check_workflow(ROOT, quality9.DEFAULT_QUALITY9_MAX_APP_BROAD_EXCEPT) == []


def test_quality9_rejects_a_workflow_that_loosens_the_ceiling(tmp_path: Path) -> None:
    loosened = WORKFLOW.read_text(encoding="utf-8").replace(
        f"--max-broad-except {_workflow_ceiling()}", f"--max-broad-except {_workflow_ceiling() + 1}"
    )
    target = tmp_path / ".github" / "workflows" / "bys360-ci.yml"
    target.parent.mkdir(parents=True)
    target.write_text(loosened, encoding="utf-8")
    codes = {finding.code for finding in quality9.check_workflow(tmp_path, quality9.DEFAULT_QUALITY9_MAX_APP_BROAD_EXCEPT)}
    assert "broad_except_threshold_above_quality9" in codes
