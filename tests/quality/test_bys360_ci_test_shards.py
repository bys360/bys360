"""Contract tests for the parallel CI test shards (scripts/ci/).

The shard plugin must split one pytest command into disjoint shards that together run every
collected test, and the shard gate must fail on any missing, repeated or failed shard. The
end-to-end tests run real pytest subprocesses on a small synthetic suite; the real 8991-test
split is checked by the gate itself in the final quality-gate job.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest
from coverage import CoverageData

from scripts.ci import (
    bys360_update_test_durations as updater,
    bys360_verify_coverage_inputs as coverage_inputs,
    bys360_verify_test_shards as shard_gate,
)
from scripts.ci.bys360_pytest_shard import (
    MANIFEST_ENV,
    SHARD_ENV,
    WEIGHTS_ENV,
    assign_files,
    collection_digest,
    file_weights,
    parse_shard,
)

pytestmark = pytest.mark.ci_safe

ROOT = Path(__file__).resolve().parents[2]
WEIGHTS = ROOT / "config" / "quality" / "bys360_ci_step2_test_durations.json"

SUITE = {
    "test_alpha.py": "def test_a1():\n    pass\n\ndef test_a2():\n    pass\n",
    "test_beta.py": "import pytest\n\n@pytest.mark.parametrize('n', [1, 2, 3])\ndef test_b(n):\n    pass\n",
    "test_gamma.py": "import pytest\n\ndef test_g1():\n    pytest.skip('a skip still counts as run')\n",
    "test_env.py": textwrap.dedent(
        """
        import os

        def test_shard_variables_do_not_leak_to_subprocesses():
            assert not [k for k in os.environ if k.startswith("BYS360_CI_SHARD")]
        """
    ),
}
SUITE_WEIGHTS = {"test_alpha.py": 30.0, "test_beta.py": 20.0, "test_gamma.py": 10.0, "test_env.py": 5.0}


def _suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for name, body in SUITE.items():
        (suite / name).write_text(body, encoding="utf-8")
    weights = {"default_seconds_per_test": 1.0, "files": SUITE_WEIGHTS}
    (tmp_path / "weights.json").write_text(json.dumps(weights), encoding="utf-8")
    return suite


def _run_shard(tmp_path: Path, suite: Path, shard: str | None, out: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BYS360_CI_SHARD")}
    if shard:
        env.update({SHARD_ENV: shard, MANIFEST_ENV: str(out / "step2-shard-manifest.json"),
                    WEIGHTS_ENV: str(tmp_path / "weights.json")})
    command = [sys.executable, "-m", "pytest", str(suite), "-c", str(suite / "pytest.ini"), "-q",
               "-p", "no:cacheprovider", "-p", "scripts.ci.bys360_pytest_shard",
               f"--junitxml={out / 'step2-junit.xml'}"]
    return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)


# --- the split --------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1/1", "2/6", "6/6"])
def test_parse_shard_accepts_index_over_total(value: str) -> None:
    index, total = parse_shard(value)
    assert f"{index}/{total}" == value


@pytest.mark.parametrize("value", ["0/6", "7/6", "1/0", "3", "a/b", "1/2/3"])
def test_parse_shard_rejects_anything_else(value: str) -> None:
    with pytest.raises(pytest.UsageError):
        parse_shard(value)


def test_every_file_goes_to_exactly_one_shard_and_the_split_is_deterministic() -> None:
    weights = {f"tests/test_{i:03}.py": float((i * 37) % 101 + 1) for i in range(200)}
    first = assign_files(weights, 6)
    assert first == assign_files(dict(reversed(list(weights.items()))), 6)
    assert set(first) == set(weights) and set(first.values()) == set(range(1, 7))


def test_the_heaviest_files_are_balanced_across_shards() -> None:
    weights = {f"tests/test_{i:03}.py": float((i * 37) % 101 + 1) for i in range(200)}
    loads = Counter[int]()
    for path, shard in assign_files(weights, 6).items():
        loads[shard] += int(weights[path])
    assert max(loads.values()) - min(loads.values()) <= max(weights.values())


def test_an_unmeasured_file_is_weighted_by_its_test_count() -> None:
    weights = file_weights(Counter({"tests/known.py": 3, "tests/new.py": 4}),
                           {"default_seconds_per_test": 2.0, "files": {"tests/known.py": 50.0}})
    assert weights == {"tests/known.py": 50.0, "tests/new.py": 8.0}


def test_the_committed_weights_file_is_well_formed() -> None:
    doc = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    assert float(doc["default_seconds_per_test"]) > 0
    assert doc["files"] and all(path.startswith("tests/") and path.endswith(".py") for path in doc["files"])
    assert all(float(seconds) >= 0 for seconds in doc["files"].values())


# --- the plugin end to end --------------------------------------------------------------------


def test_without_a_shard_the_plugin_runs_every_test(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    result = _run_shard(tmp_path, suite, None, tmp_path / "full")
    assert result.returncode == 0, result.stdout + result.stderr
    assert shard_gate.junit_totals(tmp_path / "full" / "step2-junit.xml")["tests"] == 7
    assert not (tmp_path / "full" / "step2-shard-manifest.json").exists()


def test_the_shards_together_run_every_test_once_and_pass_the_gate(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    for index in (1, 2, 3):
        result = _run_shard(tmp_path, suite, f"{index}/3", tmp_path / "data" / f"shard-{index}")
        assert result.returncode == 0, result.stdout + result.stderr
    manifests = [json.loads(p.read_text()) for p in sorted((tmp_path / "data").rglob("step2-shard-manifest.json"))]
    selected = [nodeid for manifest in manifests for nodeid in manifest["selected"]]
    assert len(selected) == len(set(selected)) == 7
    assert {manifest["collected"] for manifest in manifests} == {7}
    assert shard_gate.main(["--data-dir", str(tmp_path / "data"), "--shards", "3"]) == 0


def test_a_failing_test_fails_its_shard_and_the_gate(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    (suite / "test_alpha.py").write_text("def test_a1():\n    assert False\n\ndef test_a2():\n    pass\n")
    exit_codes = [_run_shard(tmp_path, suite, f"{i}/2", tmp_path / "data" / f"s{i}").returncode for i in (1, 2)]
    assert sorted(exit_codes) == [0, 1]
    assert shard_gate.main(["--data-dir", str(tmp_path / "data"), "--shards", "2"]) == 1


def test_a_shard_without_a_manifest_path_is_refused(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BYS360_CI_SHARD")}
    env[SHARD_ENV] = "1/2"
    result = subprocess.run([sys.executable, "-m", "pytest", str(suite), "-c", str(suite / "pytest.ini"),
                             "-p", "no:cacheprovider", "-p", "scripts.ci.bys360_pytest_shard"],
                            cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert result.returncode != 0 and MANIFEST_ENV in result.stdout + result.stderr


# --- the gate ---------------------------------------------------------------------------------

NODES = [f"tests/test_x.py::test_{i}" for i in range(6)]


def _write(data: Path, shard: int, selected: list[str], *, exitstatus: int = 0, tests: int | None = None,
           failures: int = 0, total: int = 2, collected: list[str] = NODES) -> None:
    directory = data / f"shard-{shard}"
    directory.mkdir(parents=True)
    manifest = {"shard": shard, "total": total, "collected": len(collected),
                "collected_digest": collection_digest(collected), "selected": selected,
                "files": ["tests/test_x.py"], "exitstatus": exitstatus, "durations": {}}
    (directory / "step2-shard-manifest.json").write_text(json.dumps(manifest))
    count = len(selected) if tests is None else tests
    (directory / "step2-junit.xml").write_text(
        f'<testsuites><testsuite tests="{count}" failures="{failures}" errors="0" skipped="0"/></testsuites>')


def _gate(data: Path, shards: int = 2) -> list[str]:
    return shard_gate.verify(data, shards)


def test_the_gate_passes_a_complete_disjoint_split(tmp_path: Path) -> None:
    _write(tmp_path, 1, NODES[:3])
    _write(tmp_path, 2, NODES[3:])
    assert "6 collected = 6 run" in _gate(tmp_path)[-1]


@pytest.mark.parametrize(
    ("shard_2", "kwargs", "reason"),
    [
        (None, {}, "one manifest for each shard"),
        (NODES[2:], {}, "repeats tests"),
        (NODES[4:], {}, "distinct tests"),
        (NODES[3:], {"exitstatus": 1}, "exited with status 1"),
        (NODES[3:], {"tests": 2}, "ran 2 tests but selected 3"),
        (NODES[3:], {"failures": 1}, "JUnit reports failures"),
        (NODES[3:], {"total": 3}, "total"),
        (NODES[3:], {"collected": NODES[:5]}, "different test sets"),
        ([], {}, "selected no tests"),
    ],
)
def test_the_gate_fails_any_incomplete_or_failed_split(tmp_path: Path, shard_2, kwargs, reason: str) -> None:
    _write(tmp_path, 1, NODES[:3])
    if shard_2 is not None:
        _write(tmp_path, 2, shard_2, **kwargs)
    with pytest.raises(shard_gate.GateFailure, match=reason):
        _gate(tmp_path)


def test_the_gate_requires_every_junit_report(tmp_path: Path) -> None:
    _write(tmp_path, 1, NODES[:3])
    _write(tmp_path, 2, NODES[3:])
    (tmp_path / "shard-2" / "step2-junit.xml").unlink()
    with pytest.raises(shard_gate.GateFailure, match="no JUnit report"):
        _gate(tmp_path)


# --- the coverage inputs gate -----------------------------------------------------------------


def _coverage_file(path: Path, measured: Path, *, arcs: bool = True) -> Path:
    data = CoverageData(basename=str(path))
    if arcs:
        data.add_arcs({str(measured): {(-1, 1), (1, -1)}})
    else:
        data.add_lines({str(measured): [1]})
    data.write()
    return path


def test_the_coverage_inputs_gate_passes_branch_data_of_this_checkout(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    inputs = [_coverage_file(tmp_path / f"cov-{i}", root / "app" / f"m{i}.py") for i in range(2)]
    assert coverage_inputs.main(["--root", str(root), *map(str, inputs)]) == 0


@pytest.mark.parametrize(
    ("measured", "arcs", "reason"),
    [
        (Path("other-checkout") / "app" / "m.py", True, "outside"),
        (Path("checkout") / "app" / "m.py", False, "no branch data"),
    ],
)
def test_the_coverage_inputs_gate_fails_foreign_or_line_only_data(tmp_path: Path, measured: Path, arcs: bool, reason: str) -> None:
    good = _coverage_file(tmp_path / "cov-good", tmp_path / "checkout" / "app" / "ok.py")
    bad = _coverage_file(tmp_path / "cov-bad", tmp_path / measured, arcs=arcs)
    assert any(reason in problem for problem in coverage_inputs.problems(tmp_path / "checkout", [good, bad]))
    assert coverage_inputs.main(["--root", str(tmp_path / "checkout"), str(good), str(bad)]) == 1


def test_the_coverage_inputs_gate_fails_a_missing_input(tmp_path: Path) -> None:
    assert coverage_inputs.main(["--root", str(tmp_path), str(tmp_path / "missing")]) == 1


# --- the weights refresh ----------------------------------------------------------------------


def test_the_weights_refresh_takes_the_measured_durations(tmp_path: Path) -> None:
    for shard, durations in ((1, {"tests/a.py": 12.34}), (2, {"tests/b.py": 3.0})):
        directory = tmp_path / "data" / str(shard)
        directory.mkdir(parents=True)
        (directory / "step2-shard-manifest.json").write_text(
            json.dumps({"selected": ["x", "y"], "durations": durations}))
    output = tmp_path / "weights.json"
    output.write_text(json.dumps({"_comment": "kept", "default_seconds_per_test": 9, "files": {"tests/old.py": 1}}))
    assert updater.main(["--data-dir", str(tmp_path / "data"), "--source", "run 1", "--output", str(output)]) == 0
    doc = json.loads(output.read_text())
    assert doc["_comment"] == "kept"
    assert doc["files"] == {"tests/a.py": 12.3, "tests/b.py": 3.0}
    assert doc["default_seconds_per_test"] == round(15.34 / 4, 2)
