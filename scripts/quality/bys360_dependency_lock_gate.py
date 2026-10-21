"""Dependency lock gate: structure check and vulnerability audit of requirements.lock.

requirements.lock is the hash-pinned Windows production lock (see
scripts/release/generate_bys360_requirements_lock.py). The existing CI audit
``pip_audit -r requirements.txt`` re-resolves the graph on Linux, so it never
sees the lock's pinned transitive versions nor Windows-only packages such as
colorama. This gate checks the lock itself:

``validate``
    Offline. Every entry is ``name==version`` plus exactly one
    ``--hash=sha256:<64 hex>``, names are unique after PEP 503 normalization,
    the ``# bys360-lock: packages=N`` header matches, colorama (the Windows-only
    sentinel) is present, and every requirements.txt pin is in the lock at the
    same version. build_bys360_wheelhouse.parse_lock must also accept the file.

``audit``
    ``validate``, then pip-audit on the pinned versions with ``--disable-pip
    --strict`` (nothing is installed, so Windows wheels are never installed on
    Linux). PASS only when pip-audit exits 0, writes JSON, skips nothing, scans
    exactly the lock's name/version set and reports no vulnerability.

``self-test``
    Negative control: the same audit on a known-vulnerable lock must FAIL with
    ``vulnerabilities_found``. Any other outcome (network error, clean result,
    partial scan) fails the self-test, so the gate cannot pass vacuously.

No vulnerability can be ignored here: there is no allow-list option.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
from build_bys360_wheelhouse import LockFileError, parse_lock  # noqa: E402

PACKAGE = "BYS360_DEPENDENCY_LOCK_GATE_V1"
WINDOWS_SENTINEL = "colorama"
AUDIT_TIMEOUT_SECONDS = 240
HEADER_COUNT_RE = re.compile(r"^# bys360-lock: packages=(\d+) direct=(\d+) transitive=(\d+)$")
PIN_TOKEN_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[A-Za-z0-9][A-Za-z0-9._!+-]*)$")
HASH_TOKEN_RE = re.compile(r"^--hash=sha256:[0-9a-f]{64}$")
REQUIREMENT_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9._,-]+\])?==(?P<version>\S+)$")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class GateResult:
    status: str = "PASS"
    reasons: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)

    def fail(self, reason: str) -> None:
        self.status = "FAIL"
        if reason not in self.reasons:
            self.reasons.append(reason)


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Join backslash continuations, skipping blank and comment lines (same rule as parse_lock)."""
    joined: list[tuple[int, str]] = []
    buffer, start = "", 0
    for idx, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not buffer:
            if not stripped or stripped.startswith("#"):
                continue
            start = idx
        buffer += stripped
        if buffer.endswith("\\"):
            buffer = buffer[:-1] + " "
            continue
        joined.append((start, buffer))
        buffer = ""
    if buffer:
        joined.append((start, buffer))
    return joined


def read_lock_pins(lock: Path, result: GateResult) -> dict[str, tuple[str, str]]:
    """Normalized name -> (name, version); structural problems are recorded on ``result``."""
    try:
        parse_lock(lock)
    except LockFileError as exc:
        result.fail("lock_unparseable")
        result.details["lock_error"] = str(exc)
        return {}
    text = lock.read_text(encoding="utf-8")
    pins: dict[str, tuple[str, str]] = {}
    problems: list[str] = []
    for line_no, logical in _logical_lines(text):
        tokens = logical.split()
        pin = PIN_TOKEN_RE.match(tokens[0]) if tokens else None
        hashes = tokens[1:]
        if pin is None or len(hashes) != 1 or not HASH_TOKEN_RE.match(hashes[0]):
            problems.append(f"line {line_no}: expected 'name==version --hash=sha256:<64 hex>' only")
            continue
        key = normalize(pin.group("name"))
        if key in pins:
            problems.append(f"line {line_no}: duplicate package {pin.group('name')}")
            continue
        pins[key] = (pin.group("name"), pin.group("version"))
    if problems:
        result.fail("lock_entry_invalid")
        result.details["lock_problems"] = problems
    headers = [m for m in (HEADER_COUNT_RE.match(line) for line in text.splitlines()) if m]
    if len(headers) != 1:
        result.fail("lock_header_count_missing")
    elif int(headers[0].group(1)) != len(pins) or int(headers[0].group(1)) != int(headers[0].group(2)) + int(headers[0].group(3)):
        result.fail("lock_header_count_mismatch")
    if WINDOWS_SENTINEL not in pins:
        result.fail("windows_dependency_missing")
    result.details["lock_packages"] = len(pins)
    return pins


def check_requirements(requirements: Path, pins: dict[str, tuple[str, str]], lock: Path, result: GateResult) -> None:
    stale: list[str] = []
    direct = 0
    for raw in requirements.read_text(encoding="utf-8").splitlines():
        text = raw.split("#", 1)[0].strip()
        if not text:
            continue
        match = REQUIREMENT_RE.match(text)
        if match is None:
            result.fail("requirements_not_pinned")
            continue
        direct += 1
        locked = pins.get(normalize(match.group("name")))
        if locked is None or locked[1] != match.group("version"):
            stale.append(f"{match.group('name')}=={match.group('version')} (lock: {locked[1] if locked else 'missing'})")
    if stale:
        result.fail("lock_stale_against_requirements")
        result.details["stale_pins"] = stale
    headers = [m for m in (HEADER_COUNT_RE.match(line) for line in lock.read_text(encoding="utf-8").splitlines()) if m]
    if len(headers) == 1 and int(headers[0].group(2)) != direct:
        result.fail("lock_header_direct_mismatch")


def validate(lock: Path, requirements: Path | None) -> tuple[GateResult, dict[str, tuple[str, str]]]:
    result = GateResult()
    if not lock.is_file():
        result.fail("lock_missing")
        return result, {}
    pins = read_lock_pins(lock, result)
    if requirements is not None and pins:
        check_requirements(requirements, pins, lock, result)
    return result, pins


def audit_command(lock: Path, output: Path) -> list[str]:
    return [
        sys.executable, "-m", "pip_audit",
        "-r", str(lock),
        "--disable-pip", "--strict",
        "--format", "json", "--output", str(output),
        "--progress-spinner", "off",
    ]


def evaluate_audit(returncode: int, json_text: str | None, expected: dict[str, tuple[str, str]], result: GateResult) -> None:
    """Decide from pip-audit's JSON, never from the exit code alone."""
    if json_text is None:
        result.fail("audit_json_missing")
        result.details["audit_exit_code"] = returncode
        return
    try:
        data = json.loads(json_text)
        dependencies = data["dependencies"]
        if not isinstance(dependencies, list):
            raise TypeError("dependencies is not a list")
    except (ValueError, KeyError, TypeError):
        result.fail("audit_json_invalid")
        return
    scanned: dict[str, str] = {}
    vulnerable: list[str] = []
    for dep in dependencies:
        if dep.get("skip_reason"):
            result.fail("skipped_dependencies")
            continue
        scanned[normalize(str(dep.get("name", "")))] = str(dep.get("version", ""))
        for vuln in dep.get("vulns") or []:
            vulnerable.append(f"{dep.get('name')}=={dep.get('version')} {vuln.get('id')}")
    expected_versions = {key: version for key, (_, version) in expected.items()}
    if len(dependencies) != len(expected) or set(scanned) != set(expected_versions):
        result.fail("scan_set_mismatch")
    elif scanned != expected_versions:
        result.fail("scan_version_mismatch")
    result.details.update(audit_exit_code=returncode, packages_scanned=len(dependencies), vulnerabilities=vulnerable)
    if vulnerable:
        result.fail("vulnerabilities_found")
    elif returncode != 0:
        result.fail("nonzero_exit_without_vulnerabilities")


def run_audit(lock: Path, pins: dict[str, tuple[str, str]], work: Path, result: GateResult) -> None:
    output = work / "pip_audit_lock.json"
    output.unlink(missing_ok=True)
    try:
        proc = subprocess.run(audit_command(lock, output), capture_output=True, text=True, timeout=AUDIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        result.fail("audit_timeout")
        return
    if proc.stderr:
        result.details["audit_stderr_tail"] = proc.stderr.strip().splitlines()[-5:]
    evaluate_audit(proc.returncode, output.read_text(encoding="utf-8") if output.is_file() else None, pins, result)


def write_report(path: Path | None, command: str, lock: Path, result: GateResult) -> None:
    payload = {"package": PACKAGE, "command": command, "lock": str(lock), "status": result.status,
               "reasons": result.reasons, **result.details}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and audit the BYS360 production requirements.lock.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "audit"):
        p = sub.add_parser(name)
        p.add_argument("--lock", default=str(ROOT / "requirements.lock"))
        p.add_argument("--requirements", default=str(ROOT / "requirements.txt"))
        p.add_argument("--report", default=None)
    p = sub.add_parser("self-test")
    p.add_argument("--vulnerable-lock", required=True)
    p.add_argument("--report", default=None)
    args = parser.parse_args(argv)

    report = Path(args.report) if args.report else None
    work = (report.parent if report else ROOT / "reports" / "quality")
    work.mkdir(parents=True, exist_ok=True)

    if args.command == "self-test":
        lock = Path(args.vulnerable_lock)
        audited, pins = validate(lock, None)
        if audited.status == "PASS":
            run_audit(lock, pins, work, audited)
        result = GateResult(details={"negative_control": {"status": audited.status, "reasons": audited.reasons, **audited.details}})
        if audited.reasons != ["vulnerabilities_found"]:
            result.fail("negative_control_did_not_fail_on_vulnerabilities")
        write_report(report, "self-test", lock, result)
        return 0 if result.status == "PASS" else 1

    lock = Path(args.lock)
    result, pins = validate(lock, Path(args.requirements))
    if args.command == "audit" and result.status == "PASS":
        run_audit(lock, pins, work, result)
    write_report(report, args.command, lock, result)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
