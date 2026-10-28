"""BYS360 CI test shards: one pytest command split across parallel jobs, nothing left out.

Loaded explicitly by the CI command (``-p scripts.ci.bys360_pytest_shard``). Without
``BYS360_CI_SHARD`` it does nothing: the command collects and runs every test, exactly as
before. With ``BYS360_CI_SHARD=<index>/<total>`` (the ``quality-gate-tests`` matrix):

  - The full collection is split by test file; a file is never split, so module-level
    fixtures and the order inside a file are unchanged.
  - Files are balanced by measured CI duration
    (``config/quality/bys360_ci_step2_test_durations.json``), heaviest first onto the lightest
    shard. Every shard computes the same assignment from the same collection, so the shards
    are disjoint and together cover every collected test.
  - The shard writes a manifest (``BYS360_CI_SHARD_MANIFEST``): its selected node IDs, the
    size and digest of the full collection, its exit status and measured per-file durations.
    ``scripts/ci/bys360_verify_test_shards.py`` checks the manifests of all shards in the
    final ``quality-gate`` job; a missing, overlapping or failed shard fails that gate.

The selection only deselects other shards' files; it never skips a test. The environment
variables are removed after reading, so a pytest subprocess started by a test runs unsharded.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

SHARD_ENV = "BYS360_CI_SHARD"
MANIFEST_ENV = "BYS360_CI_SHARD_MANIFEST"
WEIGHTS_ENV = "BYS360_CI_SHARD_WEIGHTS"
DEFAULT_WEIGHTS = "config/quality/bys360_ci_step2_test_durations.json"


def parse_shard(value: str) -> tuple[int, int]:
    try:
        index_text, total_text = value.split("/")
        index, total = int(index_text), int(total_text)
    except ValueError as exc:
        raise pytest.UsageError(f"{SHARD_ENV} must be <index>/<total>, got {value!r}") from exc
    if total < 1 or not 1 <= index <= total:
        raise pytest.UsageError(f"{SHARD_ENV}={value!r}: index must be between 1 and total")
    return index, total


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def collection_digest(nodeids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(nodeids)).encode("utf-8")).hexdigest()


def file_weights(counts: Counter[str], weights_doc: dict[str, Any]) -> dict[str, float]:
    measured = weights_doc.get("files", {})
    default = float(weights_doc["default_seconds_per_test"])
    return {path: float(measured.get(path, count * default)) for path, count in counts.items()}


def assign_files(weights: dict[str, float], total: int) -> dict[str, int]:
    """Heaviest file first onto the currently lightest shard (ties: path, then lowest shard)."""
    loads = [0.0] * total
    assignment: dict[str, int] = {}
    for path in sorted(weights, key=lambda p: (-weights[p], p)):
        shard = min(range(total), key=lambda i: (loads[i], i))
        assignment[path] = shard + 1
        loads[shard] += weights[path]
    return assignment


class ShardSelection:
    def __init__(self, index: int, total: int, weights_path: Path, manifest_path: Path) -> None:
        self.index = index
        self.total = total
        self.weights_path = weights_path
        self.manifest_path = manifest_path
        self.manifest: dict[str, Any] = {}
        self.durations: defaultdict[str, float] = defaultdict(float)

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config: pytest.Config, items: list[pytest.Item]) -> None:
        nodeids = [item.nodeid for item in items]
        counts = Counter(file_of(nodeid) for nodeid in nodeids)
        weights = file_weights(counts, json.loads(self.weights_path.read_text(encoding="utf-8")))
        assignment = assign_files(weights, self.total)
        selected = [item for item in items if assignment[file_of(item.nodeid)] == self.index]
        deselected = [item for item in items if assignment[file_of(item.nodeid)] != self.index]
        if deselected:
            config.hook.pytest_deselected(items=deselected)
        items[:] = selected
        planned = [0.0] * self.total
        for path, shard in assignment.items():
            planned[shard - 1] += weights[path]
        self.manifest = {
            "shard": self.index,
            "total": self.total,
            "collected": len(nodeids),
            "collected_digest": collection_digest(nodeids),
            "selected": [item.nodeid for item in selected],
            "files": sorted(path for path, shard in assignment.items() if shard == self.index),
            "planned_seconds": [round(load, 1) for load in planned],
        }

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.durations[file_of(report.nodeid)] += report.duration

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if not self.manifest:  # collection failed before the shard was selected
            self.manifest = {"shard": self.index, "total": self.total, "collected": 0, "selected": []}
        self.manifest["exitstatus"] = int(exitstatus)
        self.manifest["durations"] = {path: round(seconds, 2) for path, seconds in sorted(self.durations.items())}
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.manifest, indent=1) + "\n", encoding="utf-8")


def pytest_configure(config: pytest.Config) -> None:
    value = os.environ.pop(SHARD_ENV, "").strip()
    manifest = os.environ.pop(MANIFEST_ENV, "").strip()
    weights = os.environ.pop(WEIGHTS_ENV, "").strip() or DEFAULT_WEIGHTS
    if not value:
        return
    index, total = parse_shard(value)
    if not manifest:
        raise pytest.UsageError(f"{SHARD_ENV} is set but {MANIFEST_ENV} is not: the shard must leave a manifest")
    weights_path = Path(weights) if Path(weights).is_absolute() else config.rootpath / weights
    if not weights_path.is_file():
        raise pytest.UsageError(f"shard weights file not found: {weights_path}")
    manifest_path = Path(manifest) if Path(manifest).is_absolute() else Path.cwd() / manifest
    config.pluginmanager.register(ShardSelection(index, total, weights_path, manifest_path), "bys360_ci_shard")
