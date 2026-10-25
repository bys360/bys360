"""Regenerate or verify requirements.lock: Windows x64, CPython 3.12, wheels only, hash-pinned.

The lock is the full resolved graph of requirements.txt for the production target. pip evaluates
environment markers (``platform_system == "Windows"`` and friends) against the interpreter that
runs the resolution, even with ``--platform win_amd64``: resolved on Linux, click loses its
Windows-only ``colorama`` dependency. So the lock is written only from a resolution that really
ran on Windows x64 CPython 3.12; the report's own environment block is checked, not assumed.

Determinism:
- direct pins come from requirements.txt;
- every transitive package keeps the version the current lock pins, unless it is named with
  ``--upgrade-package`` (then pip picks the newest allowed version);
- only files uploaded before the cutoff written in the lock header are considered
  (``pip --uploaded-prior-to``), so a package that is new to the graph resolves the same way
  tomorrow as today;
- the output is sorted and carries no timestamps beyond that cutoff.

``--check`` regenerates into memory with the committed lock as the constraint set and fails
unless the result is byte-identical, which proves that the lock is complete and minimal for
requirements.txt on the target, that its direct pins agree with requirements.txt, and that every
hash is the one the index publishes for the target wheel. scripts/release/build_bys360_wheelhouse.py
then downloads each wheel and checks its SHA256 against the lock independently.

Usage (on Windows x64, CPython 3.12):
    python scripts/release/generate_bys360_requirements_lock.py --check
    python scripts/release/generate_bys360_requirements_lock.py --upgrade-package urllib3 \\
        --uploaded-prior-to 2026-10-25T00:00:00Z
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PACKAGE = "BYS360_REQUIREMENTS_LOCK_GENERATOR_V1"

TARGET_PYTHON_VERSION = "3.12"
TARGET_PLATFORM = "win_amd64"
TARGET_IMPLEMENTATION = "cp"
TARGET_ABI = "cp312"
TARGET_ENVIRONMENT = {
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "implementation_name": "cpython",
    "python_version": "3.12",
}
WHEEL_PLATFORMS = {TARGET_PLATFORM, "any"}
PIP_TIMEOUT_SECONDS = 900
DIAGNOSTIC_BANNER = "# DIAGNOSTIC OUTPUT -- NOT A LOCK. Resolved outside the target environment; never commit it.\n"

REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9,._ -]+\])?==([A-Za-z0-9][A-Za-z0-9._!+-]*)$")
LOCK_ENTRY_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._!+-]*)\s*\\?$")
CUTOFF_RE = re.compile(r"^# Uploaded-prior-to: (\S+)$", re.MULTILINE)
CUTOFF_FORMAT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class LockGenerationError(Exception):
    """Anything that must stop the generation without touching the lock."""


@dataclass(frozen=True)
class LockedPackage:
    name: str
    version: str
    sha256: str
    direct: bool


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(text: str) -> dict[str, tuple[str, str]]:
    """{canonical name: (name as written, version)}; only exact ``==`` pins are accepted."""
    pins: dict[str, tuple[str, str]] = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = REQUIREMENT_RE.match(line)
        if not match:
            raise LockGenerationError(f"requirements.txt:{line_no}: yalniz 'paket==surum' kabul edilir: {raw!r}")
        name, _extras, version = match.groups()
        key = canonical_name(name)
        if key in pins:
            raise LockGenerationError(f"requirements.txt:{line_no}: {name} iki kez sabitlenmis")
        pins[key] = (name, version)
    if not pins:
        raise LockGenerationError("requirements.txt bos")
    return pins


def parse_lock_pins(text: str) -> dict[str, tuple[str, str]]:
    """{canonical name: (name, version)} of every entry in an existing lock."""
    pins: dict[str, tuple[str, str]] = {}
    for raw in text.splitlines():
        match = LOCK_ENTRY_RE.match(raw.strip())
        if match:
            pins[canonical_name(match.group(1))] = (match.group(1), match.group(2))
    return pins


def lock_cutoff(text: str) -> str | None:
    match = CUTOFF_RE.search(text)
    return match.group(1) if match else None


def constraint_lines(
    lock_pins: dict[str, tuple[str, str]],
    direct: dict[str, tuple[str, str]],
    upgrade: set[str],
) -> list[str]:
    """Pins that keep transitive packages where the lock has them (direct pins come from requirements.txt)."""
    unknown = sorted(name for name in upgrade if name not in lock_pins and name not in direct)
    if unknown:
        raise LockGenerationError("--upgrade-package kilitte ya da requirements.txt'te yok: " + ", ".join(unknown))
    return [
        f"{name}=={version}"
        for key, (name, version) in sorted(lock_pins.items())
        if key not in direct and key not in upgrade
    ]


def packages_from_report(report: dict, direct: dict[str, tuple[str, str]], *, check_environment: bool = True) -> list[LockedPackage]:
    environment = report.get("environment") or {}
    if check_environment:
        wrong = {
            key: environment.get(key)
            for key, expected in TARGET_ENVIRONMENT.items()
            if str(environment.get(key)) != expected
        }
        if wrong:
            raise LockGenerationError(
                "cozumleme hedef ortamda calismadi (Windows x64, CPython 3.12 gerekli); "
                f"pip raporundaki farkli degerler: {wrong}"
            )
    packages: list[LockedPackage] = []
    seen: set[str] = set()
    for item in report.get("install") or []:
        metadata = item.get("metadata") or {}
        name, version = str(metadata.get("name") or ""), str(metadata.get("version") or "")
        info = item.get("download_info") or {}
        url = str(info.get("url") or "")
        sha256 = str(((info.get("archive_info") or {}).get("hashes") or {}).get("sha256") or "")
        filename = url.rsplit("/", 1)[-1]
        if not name or not version:
            raise LockGenerationError(f"pip raporunda adi/surumu olmayan kayit: {url}")
        if not filename.endswith(".whl"):
            raise LockGenerationError(f"{name}=={version}: wheel degil ({filename}); kaynak koddan derleme kabul edilmez")
        platform_tags = set(filename[: -len(".whl")].split("-")[-1].split("."))
        if not platform_tags & WHEEL_PLATFORMS:
            raise LockGenerationError(f"{name}=={version}: hedef disi wheel {filename}")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise LockGenerationError(f"{name}=={version}: pip raporunda sha256 yok")
        key = canonical_name(name)
        if key in seen:
            raise LockGenerationError(f"{name} raporda iki kez var")
        seen.add(key)
        packages.append(LockedPackage(name=name, version=version, sha256=sha256, direct=key in direct))
    for key, (name, version) in direct.items():
        locked = next((p for p in packages if canonical_name(p.name) == key), None)
        if locked is None or locked.version != version:
            raise LockGenerationError(f"{name}=={version} cozumlemede yok ya da surumu farkli: {locked}")
    return sorted(packages, key=lambda p: canonical_name(p.name))


def render_lock(packages: list[LockedPackage], *, cutoff: str, requirements_sha256: str) -> str:
    direct = [p for p in packages if p.direct]
    lines = [
        "# BYS360 requirements.lock",
        "# Generated by scripts/release/generate_bys360_requirements_lock.py -- DO NOT hand-edit.",
        "# Target: Windows x64, CPython 3.12, wheels only (no sdist, no local compiler ever required).",
        "# Resolved on Windows x64 CPython 3.12 (the generator refuses any other resolver environment), via:",
        "#   pip install -r requirements.txt -c <transitive pins of the previous lock> --dry-run --ignore-installed \\",
        "#     --report <path> --python-version 3.12 --platform win_amd64 --implementation cp --abi cp312 \\",
        "#     --only-binary=:all: --uploaded-prior-to <cutoff below>",
        f"# Uploaded-prior-to: {cutoff}",
        f"# requirements.txt sha256: {requirements_sha256}",
        "#",
        f"# {len(packages)} total packages resolved ({len(direct)} direct from requirements.txt + "
        f"{len(packages) - len(direct)} transitive).",
        "#",
        "# Format: pip's native hash-checking requirements syntax (PEP 508 name==version + --hash=sha256:<digest>).",
        "# Every line is pinned and hash-verified: pip's --require-hashes mode refuses to run unless ALL",
        "# requirements in play are hash-pinned (https://pip.pypa.io/en/stable/topics/secure-installs/).",
        "#",
        "# Consume with either:",
        "#   pip install --no-index --find-links build/wheelhouse -r requirements.lock  (wheelhouse, offline)",
        "#   pip install --require-hashes -r requirements.lock                          (online, hash-checked)",
        "#",
        "# Verify (Windows x64, CPython 3.12):",
        "#   python scripts/release/generate_bys360_requirements_lock.py --check",
        "#   python scripts/release/build_bys360_wheelhouse.py --clean",
        "# Regenerate after changing requirements.txt; move a transitive package with --upgrade-package <name>.",
        "#",
        "# Direct dependencies (pinned in requirements.txt):",
        *[f"#   {p.name}=={p.version}" for p in direct],
        "",
    ]
    for package in packages:
        lines.append(f"{package.name}=={package.version} \\")
        lines.append(f"    --hash=sha256:{package.sha256}")
    return "\n".join(lines) + "\n"


def run_pip_report(python_exe: str, requirements: Path, constraints: list[str], cutoff: str, workdir: Path) -> dict:
    constraints_path = workdir / "constraints.txt"
    constraints_path.write_text("".join(f"{line}\n" for line in constraints), encoding="utf-8")
    report_path = workdir / "report.json"
    command = [
        python_exe, "-m", "pip", "install",
        "-r", str(requirements),
        "-c", str(constraints_path),
        "--dry-run", "--ignore-installed", "--quiet", "--no-input", "--disable-pip-version-check",
        "--report", str(report_path),
        "--python-version", TARGET_PYTHON_VERSION,
        "--platform", TARGET_PLATFORM,
        "--implementation", TARGET_IMPLEMENTATION,
        "--abi", TARGET_ABI,
        "--only-binary=:all:",
        "--uploaded-prior-to", cutoff,
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=PIP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise LockGenerationError(f"pip cozumlemesi {PIP_TIMEOUT_SECONDS} sn icinde bitmedi") from exc
    if proc.returncode != 0:
        raise LockGenerationError(
            f"pip cozumlemesi basarisiz (rc={proc.returncode}):\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
        )
    return json.loads(report_path.read_text(encoding="utf-8"))


def interpreter_is_64bit(python_exe: str) -> bool:
    """32-bit Python under WOW64 still reports platform_machine AMD64; the pointer size does not lie."""
    proc = subprocess.run(
        [python_exe, "-c", "import struct; print(struct.calcsize('P') * 8)"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "64"


def generate(
    *,
    requirements: Path,
    lock: Path,
    upgrade: list[str],
    cutoff: str | None,
    python_exe: str,
    check_environment: bool = True,
) -> str:
    # Text mode reads CRLF as LF, so the digest is the same even where .gitattributes is ignored.
    requirements_bytes = requirements.read_text(encoding="utf-8").encode("utf-8")
    direct = parse_requirements(requirements_bytes.decode("utf-8"))
    lock_text = lock.read_text(encoding="utf-8") if lock.is_file() else ""
    effective_cutoff = cutoff or lock_cutoff(lock_text)
    if not effective_cutoff:
        raise LockGenerationError("kilitte 'Uploaded-prior-to' yok; --uploaded-prior-to verin (or. 2026-10-25T00:00:00Z)")
    if not CUTOFF_FORMAT_RE.match(effective_cutoff):
        raise LockGenerationError(f"--uploaded-prior-to UTC 'YYYY-MM-DDTHH:MM:SSZ' olmali: {effective_cutoff!r}")
    constraints = constraint_lines(parse_lock_pins(lock_text), direct, {canonical_name(n) for n in upgrade})
    if check_environment and not interpreter_is_64bit(python_exe):
        raise LockGenerationError(f"cozumleyici 64 bit bir Python degil: {python_exe}")
    with tempfile.TemporaryDirectory(prefix="bys360_lock_") as tmp:
        report = run_pip_report(python_exe, requirements, constraints, effective_cutoff, Path(tmp))
    packages = packages_from_report(report, direct, check_environment=check_environment)
    return render_lock(packages, cutoff=effective_cutoff, requirements_sha256=hashlib.sha256(requirements_bytes).hexdigest())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", default=".", help="Depo koku (varsayilan: mevcut dizin)")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--lock", default="requirements.lock")
    parser.add_argument("--upgrade-package", action="append", default=[], help="Bu gecisli paketi kilitteki surumunden serbest birak")
    parser.add_argument("--uploaded-prior-to", default=None, help="UTC kesme zamani; verilmezse kilit basligindaki deger")
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--check", action="store_true", help="Yeniden uret ve kilitle birebir karsilastir; dosya yazma")
    parser.add_argument(
        "--diagnostic-output",
        default=None,
        help="Tani amacli: hedef ortam denetimini atla ve sonucu bu yola yaz (kilit dosyasina asla yazilmaz)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    requirements = (root / args.requirements).resolve()
    lock = (root / args.lock).resolve()
    diagnostic = Path(args.diagnostic_output).resolve() if args.diagnostic_output else None
    protected = {lock, requirements, (root / "requirements.lock").resolve(), (root / "requirements.txt").resolve()}
    if diagnostic is not None and (args.check or diagnostic in protected or diagnostic.exists()):
        print(
            f"{PACKAGE}: --diagnostic-output --check ile, kilit/requirements dosyasina ya da var olan bir dosyaya kullanilamaz",
            file=sys.stderr,
        )
        return 2
    try:
        generated = generate(
            requirements=requirements,
            lock=lock,
            upgrade=args.upgrade_package,
            cutoff=args.uploaded_prior_to,
            python_exe=args.python_exe,
            check_environment=diagnostic is None,
        )
    except LockGenerationError as exc:
        print(f"{PACKAGE}: HATA: {exc}", file=sys.stderr)
        return 1

    if diagnostic is not None:
        diagnostic.write_text(DIAGNOSTIC_BANNER + generated, encoding="utf-8", newline="\n")
        print(f"{PACKAGE}: tani ciktisi (kilit degil) yazildi: {diagnostic}")
        return 0
    if args.check:
        # Byte comparison: .gitattributes keeps requirements.txt/requirements.lock LF on every checkout.
        current_bytes = lock.read_bytes() if lock.is_file() else b""
        current = current_bytes.decode("utf-8", errors="replace")
        if current_bytes == generated.encode("utf-8"):
            print(f"{PACKAGE}: PASS -- {lock.name} yeniden uretimle birebir ayni (sha256 {hashlib.sha256(generated.encode()).hexdigest()})")
            return 0
        print(f"{PACKAGE}: FAIL -- {lock.name} yeniden uretilen kilitle ayni degil", file=sys.stderr)
        sys.stderr.writelines(difflib.unified_diff(current.splitlines(True), generated.splitlines(True), "committed", "regenerated"))
        print("----- BEGIN REGENERATED requirements.lock -----")
        print(generated, end="")
        print("----- END REGENERATED requirements.lock -----")
        return 1
    lock.write_text(generated, encoding="utf-8", newline="\n")
    print(f"{PACKAGE}: yazildi {lock} (sha256 {hashlib.sha256(generated.encode()).hexdigest()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
