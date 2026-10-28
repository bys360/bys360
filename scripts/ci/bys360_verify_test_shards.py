"""BYS360 CI shard gate: proves the parallel test shards ran the whole command, once.

Runs in the final ``quality-gate`` job on the artifacts of every ``quality-gate-tests`` shard
(one directory per shard holding ``step2-shard-manifest.json`` written by
``scripts/ci/bys360_pytest_shard.py`` and the shard's ``step2-junit.xml``). Fails unless:

  - there is exactly one manifest for every shard 1..N (``--shards N``);
  - every shard saw the same full collection (same size and digest);
  - the shards' selections are disjoint and their union is exactly that collection;
  - every shard exited 0 and its JUnit report counts exactly its selected tests,
    with 0 failures and 0 errors.

There is no bypass flag. Exit 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.bys360_pytest_shard import (  # noqa: E402  (after the repo root is on sys.path)
    collection_digest,
)

MANIFEST_NAME = "step2-shard-manifest.json"
JUNIT_NAME = "step2-junit.xml"


class GateFailure(RuntimeError):
    pass


def junit_totals(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    return {key: sum(int(suite.get(key, 0)) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}


def load_shards(data_dir: Path) -> list[tuple[dict[str, Any], Path]]:
    shards = []
    for manifest_path in sorted(data_dir.rglob(MANIFEST_NAME)):
        shards.append((json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path.parent))
    return shards


def verify(data_dir: Path, expected_shards: int) -> list[str]:
    shards = load_shards(data_dir)
    indexes = sorted(str(manifest.get("shard")) for manifest, _ in shards)
    if indexes != sorted(str(index) for index in range(1, expected_shards + 1)):
        raise GateFailure(f"expected one manifest for each shard 1..{expected_shards}, found shards {indexes}")
    totals = {str(manifest.get("total")) for manifest, _ in shards}
    if totals != {str(expected_shards)}:
        raise GateFailure(f"shards were run with total {sorted(totals)}, expected {expected_shards}")
    collections = {(manifest.get("collected"), manifest.get("collected_digest")) for manifest, _ in shards}
    if len(collections) != 1:
        raise GateFailure(f"shards collected different test sets: {sorted(collections, key=str)}")
    collected, digest = collections.pop()
    if not collected:
        raise GateFailure("the shards collected no tests")

    union: set[str] = set()
    selected_total = 0
    lines = []
    for manifest, directory in sorted(shards, key=lambda item: item[0]["shard"]):
        index = manifest["shard"]
        selected = manifest.get("selected", [])
        if manifest.get("exitstatus") != 0:
            raise GateFailure(f"shard {index} exited with status {manifest.get('exitstatus')}")
        if not selected:
            raise GateFailure(f"shard {index} selected no tests")
        overlap = union.intersection(selected)
        if overlap or len(set(selected)) != len(selected):
            raise GateFailure(f"shard {index} repeats tests of another shard: {sorted(overlap)[:5]}")
        union.update(selected)
        selected_total += len(selected)
        junit_path = directory / JUNIT_NAME
        if not junit_path.is_file():
            raise GateFailure(f"shard {index} has no JUnit report ({junit_path})")
        junit = junit_totals(junit_path)
        if junit["failures"] or junit["errors"]:
            raise GateFailure(f"shard {index} JUnit reports failures: {junit}")
        if junit["tests"] != len(selected):
            raise GateFailure(f"shard {index} ran {junit['tests']} tests but selected {len(selected)}")
        seconds = sum(manifest.get("durations", {}).values())
        lines.append(f"shard {index}/{expected_shards}: {len(selected)} tests ({junit['skipped']} skipped), "
                     f"{len(manifest.get('files', []))} files, test time {seconds / 60:.1f} min")
    if selected_total != collected or len(union) != collected or collection_digest(union) != digest:
        raise GateFailure(f"the shards ran {len(union)} distinct tests; the collection has {collected}")
    lines.append(f"all {expected_shards} shards: {collected} collected = {selected_total} run, none twice, none missing")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--shards", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        for line in verify(args.data_dir, args.shards):
            print(f"BYS360 shard gate: {line}")
    except GateFailure as exc:
        print(f"BYS360 shard gate FAIL: {exc}")
        return 1
    print("BYS360 shard gate: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
