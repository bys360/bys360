"""BYS360 CI coverage inputs gate: the data files combined for the ratchet all belong here.

The final ``quality-gate`` job combines the coverage data of the ci_safe step and every
``quality-gate-tests`` shard. coverage.py merges a file only when its recorded path is identical,
so data recorded under another checkout path would be counted as a second copy of ``app/`` and
silently lower the combined percentage. This gate fails unless every input file exists, holds
branch coverage (``branch = true`` in pyproject.toml) and measured only files under this
checkout's ``app/`` directory. Exit 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coverage import CoverageData


def problems(root: Path, data_files: list[Path]) -> list[str]:
    app = (root / "app").resolve()
    found = []
    for path in data_files:
        if not path.is_file():
            found.append(f"{path}: missing")
            continue
        data = CoverageData(basename=str(path))
        data.read()
        measured = sorted(data.measured_files())
        if not measured:
            found.append(f"{path}: measured no files")
        if not data.has_arcs():
            found.append(f"{path}: no branch data (pyproject.toml sets branch = true)")
        outside = [name for name in measured if not Path(name).resolve().is_relative_to(app)]
        if outside:
            found.append(f"{path}: {len(outside)} measured files outside {app}, e.g. {outside[0]}")
        else:
            print(f"BYS360 coverage inputs: {path}: {len(measured)} files under {app}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("data_files", type=Path, nargs="+")
    args = parser.parse_args(argv)
    found = problems(args.root, args.data_files)
    for problem in found:
        print(f"BYS360 coverage inputs FAIL: {problem}")
    if found:
        return 1
    print(f"BYS360 coverage inputs: PASS ({len(args.data_files)} data files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
