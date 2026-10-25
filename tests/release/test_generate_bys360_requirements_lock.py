"""requirements.lock generator: refusals, determinism, and the committed lock's consistency.

The full regeneration runs on a real Windows runner (.github/workflows/
bys360-windows-dependency-lock-v1.yml, ``--check``). These tests run everywhere: they pin the
generator's refusals with synthetic pip reports and check that the committed lock still matches
requirements.txt, so a requirements.txt edit without a lock regeneration fails on Linux CI too.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release" / "generate_bys360_requirements_lock.py"


def _load():
    spec = importlib.util.spec_from_file_location("generate_bys360_requirements_lock", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load()

WINDOWS_ENV = {
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "implementation_name": "cpython",
    "python_version": "3.12",
}
DIRECT = {"flask": ("Flask", "3.1.3"), "pillow": ("Pillow", "13.0.0")}


def _item(name, version, filename, sha="a" * 64, requested=False):
    return {
        "metadata": {"name": name, "version": version},
        "requested": requested,
        "download_info": {"url": f"https://files.example/{filename}", "archive_info": {"hashes": {"sha256": sha}}},
    }


def _report(*items, environment=None):
    return {"environment": dict(WINDOWS_ENV if environment is None else environment), "install": list(items)}


GOOD_ITEMS = (
    _item("Flask", "3.1.3", "flask-3.1.3-py3-none-any.whl", "1" * 64, True),
    _item("pillow", "13.0.0", "pillow-13.0.0-cp312-cp312-win_amd64.whl", "2" * 64, True),
    _item("colorama", "0.4.6", "colorama-0.4.6-py2.py3-none-any.whl", "3" * 64),
    _item("Werkzeug", "3.1.9", "werkzeug-3.1.9-py3-none-any.whl", "4" * 64),
)


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


def test_requirements_must_be_exact_pins():
    assert gen.parse_requirements("Flask==3.1.3\n# c\nsentry-sdk[flask]==2.20.0  # x\n") == {
        "flask": ("Flask", "3.1.3"),
        "sentry-sdk": ("sentry-sdk", "2.20.0"),
    }
    for bad in ("Flask>=3.1\n", "Flask\n", "-e .\n", "--index-url https://x\n", "Flask==3.1.3\nflask==3.1.4\n", "\n"):
        with pytest.raises(gen.LockGenerationError):
            gen.parse_requirements(bad)


def test_transitive_pins_are_kept_direct_and_upgraded_ones_are_released():
    lock = {
        "flask": ("Flask", "3.1.2"),
        "werkzeug": ("Werkzeug", "3.1.8"),
        "urllib3": ("urllib3", "2.7.0"),
        "colorama": ("colorama", "0.4.6"),
    }
    assert gen.constraint_lines(lock, DIRECT, {"urllib3"}) == ["colorama==0.4.6", "Werkzeug==3.1.8"]
    with pytest.raises(gen.LockGenerationError, match="not-a-package"):
        gen.constraint_lines(lock, DIRECT, {"not-a-package"})


# --------------------------------------------------------------------------------------
# Report validation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "environment",
    (
        {**WINDOWS_ENV, "sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64"},
        {**WINDOWS_ENV, "platform_machine": "x86"},
        {**WINDOWS_ENV, "python_version": "3.13"},
        {**WINDOWS_ENV, "implementation_name": "pypy"},
        {},
    ),
)
def test_a_resolution_outside_windows_x64_cpython_312_is_refused(environment):
    with pytest.raises(gen.LockGenerationError, match="hedef ortamda"):
        gen.packages_from_report(_report(*GOOD_ITEMS, environment=environment), DIRECT)


@pytest.mark.parametrize(
    ("bad_item", "message"),
    (
        (_item("pillow", "13.0.0", "pillow-13.0.0.tar.gz"), "wheel degil"),
        (_item("pillow", "13.0.0", "pillow-13.0.0-cp312-cp312-manylinux_2_28_x86_64.whl"), "hedef disi"),
        (_item("pillow", "13.0.0", "pillow-13.0.0-cp312-cp312-win32.whl"), "hedef disi"),
        (_item("pillow", "13.0.0", "pillow-13.0.0-cp312-cp312-win_amd64.whl", sha=""), "sha256 yok"),
        (_item("pillow", "12.3.0", "pillow-12.3.0-cp312-cp312-win_amd64.whl"), "surumu farkli"),
    ),
)
def test_unsafe_or_inconsistent_report_entries_are_refused(bad_item, message):
    items = [item for item in GOOD_ITEMS if item["metadata"]["name"] != "pillow"] + [bad_item]
    with pytest.raises(gen.LockGenerationError, match=message):
        gen.packages_from_report(_report(*items), DIRECT)


def test_a_missing_direct_requirement_is_refused():
    items = [item for item in GOOD_ITEMS if item["metadata"]["name"] != "Flask"]
    with pytest.raises(gen.LockGenerationError, match="Flask==3.1.3"):
        gen.packages_from_report(_report(*items), DIRECT)


def test_render_is_sorted_and_independent_of_report_order():
    first = gen.render_lock(gen.packages_from_report(_report(*GOOD_ITEMS), DIRECT), cutoff="2026-10-25T00:00:00Z", requirements_sha256="0" * 64)
    second = gen.render_lock(
        gen.packages_from_report(_report(*reversed(GOOD_ITEMS)), DIRECT), cutoff="2026-10-25T00:00:00Z", requirements_sha256="0" * 64
    )
    assert first == second
    entries = re.findall(r"^([A-Za-z0-9._-]+)==", first, flags=re.MULTILINE)
    assert entries == ["colorama", "Flask", "pillow", "Werkzeug"]
    assert "# 4 total packages resolved (2 direct from requirements.txt + 2 transitive)." in first
    assert "# Uploaded-prior-to: 2026-10-25T00:00:00Z" in first


def test_diagnostic_output_never_targets_the_lock_the_requirements_or_an_existing_file(tmp_path):
    lock = tmp_path / "requirements.lock"
    requirements = tmp_path / "requirements.txt"
    existing = tmp_path / "existing.lock"
    existing.write_text("keep\n", encoding="utf-8")
    other_lock = tmp_path / "other.lock"
    assert gen.main(["--root", str(tmp_path), "--diagnostic-output", str(lock)]) == 2
    assert gen.main(["--root", str(tmp_path), "--diagnostic-output", str(requirements)]) == 2
    # --lock pointing elsewhere does not unprotect the canonical lock
    assert gen.main(["--root", str(tmp_path), "--lock", str(other_lock), "--diagnostic-output", str(lock)]) == 2
    assert gen.main(["--root", str(tmp_path), "--diagnostic-output", str(existing)]) == 2
    assert gen.main(["--root", str(tmp_path), "--check", "--diagnostic-output", str(tmp_path / "x.lock")]) == 2
    assert not lock.exists() and not requirements.exists() and existing.read_text(encoding="utf-8") == "keep\n"


def test_diagnostic_output_is_marked_as_not_a_lock(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("Flask==3.1.3\nPillow==13.0.0\n", encoding="utf-8")
    monkeypatch.setattr(gen, "run_pip_report", lambda *args, **kwargs: _report(*GOOD_ITEMS, environment={"sys_platform": "linux"}))
    target = tmp_path / "diag.lock"
    assert gen.main(["--root", str(tmp_path), "--uploaded-prior-to", "2026-10-25T00:00:00Z", "--diagnostic-output", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("# DIAGNOSTIC OUTPUT -- NOT A LOCK.")


def test_check_compares_bytes(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("Flask==3.1.3\nPillow==13.0.0\n", encoding="utf-8")
    monkeypatch.setattr(gen, "run_pip_report", lambda *args, **kwargs: _report(*GOOD_ITEMS))
    monkeypatch.setattr(gen, "interpreter_is_64bit", lambda python_exe: True)
    args = ["--root", str(tmp_path), "--uploaded-prior-to", "2026-10-25T00:00:00Z"]
    assert gen.main(args) == 0
    lock = tmp_path / "requirements.lock"
    assert gen.main([*args, "--check"]) == 0
    lock.write_bytes(lock.read_bytes().replace(b"\n", b"\r\n"))
    assert gen.main([*args, "--check"]) == 1


def test_a_32_bit_resolver_is_refused(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("Flask==3.1.3\nPillow==13.0.0\n", encoding="utf-8")
    monkeypatch.setattr(gen, "run_pip_report", lambda *args, **kwargs: _report(*GOOD_ITEMS))
    monkeypatch.setattr(gen, "interpreter_is_64bit", lambda python_exe: False)
    assert gen.main(["--root", str(tmp_path), "--uploaded-prior-to", "2026-10-25T00:00:00Z"]) == 1
    assert not (tmp_path / "requirements.lock").exists()


def test_the_repository_keeps_the_dependency_manifests_lf():
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "requirements.txt text eol=lf" in attributes and "requirements.lock text eol=lf" in attributes
    assert b"\r" not in (REPO_ROOT / "requirements.lock").read_bytes()


# --------------------------------------------------------------------------------------
# The committed lock
# --------------------------------------------------------------------------------------

LOCK_TEXT = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
REQUIREMENTS_TEXT = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
ENTRY_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+) \\\n    --hash=sha256:([0-9a-f]{64})$", re.MULTILINE)


def test_committed_lock_was_generated_from_the_current_requirements_txt():
    recorded = re.search(r"^# requirements\.txt sha256: ([0-9a-f]{64})$", LOCK_TEXT, flags=re.MULTILINE)
    assert recorded, "requirements.lock has no requirements.txt digest; regenerate it with the generator"
    assert recorded.group(1) == hashlib.sha256(REQUIREMENTS_TEXT.encode("utf-8")).hexdigest(), (
        "requirements.txt changed after requirements.lock was generated; regenerate the lock on Windows"
    )
    assert gen.lock_cutoff(LOCK_TEXT) and gen.CUTOFF_FORMAT_RE.match(gen.lock_cutoff(LOCK_TEXT))


def test_committed_lock_entries_are_complete_sorted_single_hash_and_match_the_direct_pins():
    entries = ENTRY_RE.findall(LOCK_TEXT)
    pinned_lines = [line for line in LOCK_TEXT.splitlines() if line and not line.startswith(("#", " "))]
    assert len(entries) == len(pinned_lines) > 0, "every pinned line carries exactly one sha256"
    names = [gen.canonical_name(name) for name, _version, _sha in entries]
    assert names == sorted(names) and len(set(names)) == len(names)

    direct = gen.parse_requirements(REQUIREMENTS_TEXT)
    locked = {gen.canonical_name(name): version for name, version, _sha in entries}
    assert {key: version for key, (_name, version) in direct.items()} == {key: locked.get(key) for key in direct}

    count = re.search(r"^# (\d+) total packages resolved \((\d+) direct from requirements\.txt \+ (\d+) transitive\)\.$", LOCK_TEXT, flags=re.MULTILINE)
    assert count and int(count.group(1)) == len(entries) and int(count.group(2)) == len(direct)
    assert int(count.group(3)) == len(entries) - len(direct)
    commented_direct = re.findall(r"^#   ([A-Za-z0-9._-]+)==(\S+)$", LOCK_TEXT, flags=re.MULTILINE)
    assert {gen.canonical_name(name): version for name, version in commented_direct} == {
        key: version for key, (_name, version) in direct.items()
    }


def test_committed_lock_keeps_the_windows_only_dependency():
    # click needs colorama only on Windows; a lock resolved on Linux silently drops it.
    names = {gen.canonical_name(name) for name, _version, _sha in ENTRY_RE.findall(LOCK_TEXT)}
    assert {"click", "colorama"} <= names
