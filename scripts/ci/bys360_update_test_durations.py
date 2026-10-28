"""Refresh config/quality/bys360_ci_step2_test_durations.json from a CI run's shard manifests.

Download the ``bys360-ci-step2-shard-*`` artifacts of one green ``Run tests`` run into a
directory and pass it as ``--data-dir``. The per-file durations measured by
``scripts/ci/bys360_pytest_shard.py`` (setup + call + teardown of every test) replace the stored
ones; the result only rebalances the shards, it never changes which tests run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "config" / "quality" / "bys360_ci_step2_test_durations.json"


def merged_durations(data_dir: Path) -> tuple[dict[str, float], int]:
    durations: dict[str, float] = {}
    tests = 0
    for path in sorted(data_dir.rglob("step2-shard-manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        durations.update(manifest.get("durations", {}))
        tests += len(manifest.get("selected", []))
    return durations, tests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--source", required=True, help="the run, job and SHA the manifests come from")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    durations, tests = merged_durations(args.data_dir)
    if not durations or not tests:
        print(f"no shard manifests with durations under {args.data_dir}")
        return 1
    doc = json.loads(args.output.read_text(encoding="utf-8"))
    doc["source"] = {"method": "per-file durations measured by scripts/ci/bys360_pytest_shard.py", "run": args.source}
    doc["default_seconds_per_test"] = round(sum(durations.values()) / tests, 2)
    doc["files"] = {path: round(seconds, 1) for path, seconds in sorted(durations.items())}
    args.output.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(durations)} files, {tests} tests, {sum(durations.values()) / 60:.1f} min -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
