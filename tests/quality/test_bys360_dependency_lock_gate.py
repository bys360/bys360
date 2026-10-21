"""Contract for scripts/quality/bys360_dependency_lock_gate.py and its CI wiring.

Offline: pip-audit is never called; its JSON is synthesized or the subprocess is replaced.
The real audit runs in the CI steps this file pins (Linux) and in the negative-control step.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.ci_safe

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "quality" / "bys360_dependency_lock_gate.py"
LOCK = ROOT / "requirements.lock"
REQUIREMENTS = ROOT / "requirements.txt"
FIXTURE = ROOT / "tests" / "fixtures" / "dependency_audit" / "requirements_lock_pre_fix_vulnerable.lock"
CI = ROOT / ".github" / "workflows" / "bys360-ci.yml"
SCORE100 = ROOT / ".github" / "workflows" / "bys360-score100-quality-gate-v1.yml"


def _load():
    spec = importlib.util.spec_from_file_location("bys360_dependency_lock_gate_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _validate(tmp_path, lock_text, requirements_text=None):
    lock = tmp_path / "requirements.lock"
    lock.write_text(lock_text, encoding="utf-8")
    requirements = None
    if requirements_text is not None:
        requirements = tmp_path / "requirements.txt"
        requirements.write_text(requirements_text, encoding="utf-8")
    result, _ = gate.validate(lock, requirements)
    return result


# ------------------------------------------------------------------ validate


def test_committed_lock_passes_validation():
    result, pins = gate.validate(LOCK, REQUIREMENTS)
    assert (result.status, result.reasons) == ("PASS", [])
    assert len(pins) == 59 and "colorama" in pins


def _entry(text, name):
    match = re.search(rf"^{re.escape(name)}==\S+ \\\n    --hash=sha256:[0-9a-f]{{64}}\n", text, re.M)
    assert match, name
    return match.group(0)


HASH = "--hash=sha256:" + "a" * 64


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda t: t.replace(_entry(t, "six"), ""), "lock_header_count_mismatch"),
        (lambda t: t.replace(_entry(t, "colorama"), "").replace("packages=59 direct=24 transitive=35",
                                                                    "packages=58 direct=24 transitive=34"),
         "windows_dependency_missing"),
        (lambda t: t + "SIX==1.17.0 \\\n    " + HASH + "\n", "lock_entry_invalid"),
        (lambda t: t + "extra-pkg==1.0 \\\n    " + HASH + " " + HASH.replace("a", "b") + "\n", "lock_entry_invalid"),
        (lambda t: t + "extra-pkg==1.0 \\\n    --hash=sha256:" + "a" * 65 + "\n", "lock_entry_invalid"),
        (lambda t: t + "extra-pkg==1.0 \\\n    --hash=md5:" + "a" * 32 + "\n", "lock_unparseable"),
        (lambda t: t + "extra-pkg==1.0 \\\n    " + HASH + " --index-url=https://evil.example\n", "lock_entry_invalid"),
        (lambda t: t + "extra-pkg>=1.0 \\\n    " + HASH + "\n", "lock_unparseable"),
        (lambda t: t + "extra-pkg==1.0; sys_platform == 'win32' \\\n    " + HASH + "\n", "lock_unparseable"),
        (lambda t: t + "extra-pkg[x]==1.0 \\\n    " + HASH + "\n", "lock_unparseable"),
        (lambda t: t + "extra-pkg==1.0\n", "lock_unparseable"),
        (lambda t: t + "--index-url https://evil.example\n", "lock_unparseable"),
        (lambda t: t.replace("# bys360-lock: packages=59 direct=24 transitive=35\n", ""), "lock_header_count_missing"),
        (lambda t: "", "lock_unparseable"),
    ],
    ids=["removed-entry", "removed-colorama", "case-duplicate", "two-hashes", "65-hex", "md5", "trailing-option",
         "unpinned", "marker", "extras", "no-hash", "option-line", "no-header-count", "empty"],
)
def test_structural_defects_fail(tmp_path, mutate, reason):
    result = _validate(tmp_path, mutate(LOCK.read_text(encoding="utf-8")))
    assert result.status == "FAIL" and reason in result.reasons, result.reasons


def test_stale_lock_against_requirements_fails(tmp_path):
    stale_requirements = REQUIREMENTS.read_text(encoding="utf-8").replace("Pillow==13.0.0", "Pillow==12.3.0")
    result = _validate(tmp_path, LOCK.read_text(encoding="utf-8"), stale_requirements)
    assert result.reasons == ["lock_stale_against_requirements"]


# ------------------------------------------------------------------ audit decision


def _pins():
    return gate.validate(LOCK, REQUIREMENTS)[1]


def _audit_json(pins, *, vulns=None, drop=0, extra=False, skip=None, bump=None):
    deps = []
    for key, (name, version) in list(sorted(pins.items()))[drop:]:
        dep = {"name": name.lower(), "version": "9.9.9" if key == bump else version, "vulns": []}
        if vulns and key in vulns:
            dep["vulns"] = [{"id": vulns[key], "fix_versions": ["99"]}]
        if key == skip:
            dep = {"name": name.lower(), "skip_reason": "not on PyPI"}
        deps.append(dep)
    if extra:
        deps.append({"name": "ghost", "version": "1.0", "vulns": []})
    return json.dumps({"dependencies": deps, "fixes": []})


@pytest.mark.parametrize(
    ("returncode", "payload", "reason"),
    [
        (1, lambda p: _audit_json(p, vulns={"pillow": "CVE-2026-112895"}), "vulnerabilities_found"),
        (0, lambda p: _audit_json(p, vulns={"pillow": "CVE-2026-112895"}), "vulnerabilities_found"),
        (0, lambda p: _audit_json(p, drop=1), "scan_set_mismatch"),
        (0, lambda p: _audit_json(p, extra=True), "scan_set_mismatch"),
        (0, lambda p: _audit_json(p, skip="six"), "skipped_dependencies"),
        (0, lambda p: _audit_json(p, bump="six"), "scan_version_mismatch"),
        (1, lambda p: _audit_json(p), "nonzero_exit_without_vulnerabilities"),
        (1, lambda p: None, "audit_json_missing"),
        (0, lambda p: None, "audit_json_missing"),
        (0, lambda p: "{not json", "audit_json_invalid"),
        (0, lambda p: json.dumps({"dependencies": "x"}), "audit_json_invalid"),
    ],
    ids=["vulnerable-rc1", "vulnerable-rc0", "58-scanned", "60-scanned", "skipped", "version-mismatch",
         "rc1-no-vulns", "no-json-rc1", "no-json-rc0", "invalid-json", "bad-shape"],
)
def test_audit_evaluation_fails_closed(returncode, payload, reason):
    pins = _pins()
    result = gate.GateResult()
    gate.evaluate_audit(returncode, payload(pins), pins, result)
    assert result.status == "FAIL" and reason in result.reasons, result.reasons


def test_clean_complete_audit_passes():
    pins = _pins()
    result = gate.GateResult()
    gate.evaluate_audit(0, _audit_json(pins), pins, result)
    assert (result.status, result.details["packages_scanned"]) == ("PASS", 59)


def test_audit_command_is_fixed_and_has_no_ignore_options(tmp_path):
    cmd = gate.audit_command(LOCK, tmp_path / "out.json")
    assert cmd[1:5] == ["-m", "pip_audit", "-r", str(LOCK)]
    assert "--disable-pip" in cmd and "--strict" in cmd  # never installs; a skipped package is fatal
    assert not any(token.startswith(("--ignore-vuln", "--vulnerability-service", "-s")) for token in cmd)
    assert "--no-deps" not in cmd and "--require-hashes" not in cmd


def _fake_audit(monkeypatch, payload_for):
    def run(cmd, capture_output, text, timeout):
        output = Path(cmd[cmd.index("--output") + 1])
        lock = Path(cmd[cmd.index("-r") + 1])
        pins = gate.validate(lock, None)[1]
        payload = payload_for(pins)
        output.write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 1 if '"id"' in payload else 0, "", "")

    monkeypatch.setattr(gate.subprocess, "run", run)


def test_self_test_passes_only_when_the_negative_control_finds_vulnerabilities(tmp_path, monkeypatch):
    _fake_audit(monkeypatch, lambda pins: _audit_json(pins, vulns={"pillow": "CVE-2026-112895"}))
    assert gate.main(["self-test", "--vulnerable-lock", str(FIXTURE), "--report", str(tmp_path / "r.json")]) == 0
    _fake_audit(monkeypatch, lambda pins: _audit_json(pins))
    assert gate.main(["self-test", "--vulnerable-lock", str(FIXTURE), "--report", str(tmp_path / "r.json")]) == 1
    _fake_audit(monkeypatch, lambda pins: _audit_json(pins, vulns={"pillow": "X"}, drop=1))
    assert gate.main(["self-test", "--vulnerable-lock", str(FIXTURE), "--report", str(tmp_path / "r.json")]) == 1


def test_audit_command_line_fails_on_vulnerabilities(tmp_path, monkeypatch):
    _fake_audit(monkeypatch, lambda pins: _audit_json(pins, vulns={"werkzeug": "CVE-2026-102598"}))
    assert gate.main(["audit", "--lock", str(LOCK), "--requirements", str(REQUIREMENTS),
                      "--report", str(tmp_path / "a.json")]) == 1
    report = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert report["reasons"] == ["vulnerabilities_found"]


def test_negative_control_fixture_is_the_pre_fix_lock():
    """Byte-pinned: the pre-PR pins (Pillow 12.3.0, Werkzeug 3.1.8, urllib3 2.7.0, certifi 2026.7.22)."""
    text = FIXTURE.read_text(encoding="ascii")
    assert hashlib.sha256(text.encode("ascii")).hexdigest() == "87c1113f8eba278157ae1a7ad8a756b627d801604800c06a3e495a066a01bd6b"
    for pin in ("pillow==12.3.0", "Werkzeug==3.1.8", "urllib3==2.7.0", "certifi==2026.7.22", "colorama==0.4.6"):
        assert f"\n{pin} \\\n" in text, pin
    result, pins = gate.validate(FIXTURE, None)
    assert result.status == "PASS" and len(pins) == 59


# ------------------------------------------------------------------ CI wiring


def _step(text, name):
    start = text.index(f"      - name: {name}\n")
    end = text.find("\n      - name:", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_linux_ci_audits_requirements_and_the_production_lock():
    text = CI.read_text(encoding="utf-8")
    assert _step(text, "Dependency vulnerability audit").startswith(
        "      - name: Dependency vulnerability audit\n"
        "        run: python -m pip_audit -r requirements.txt --progress-spinner off\n"
    )
    expected = {
        "Production lock manifest gate (requirements.lock)":
            "python scripts/quality/bys360_dependency_lock_gate.py validate --lock requirements.lock "
            "--requirements requirements.txt --report reports/quality/BYS360_DEPENDENCY_LOCK_MANIFEST.json",
        "Production lock vulnerability audit (requirements.lock)":
            "python scripts/quality/bys360_dependency_lock_gate.py audit --lock requirements.lock "
            "--requirements requirements.txt --report reports/quality/BYS360_DEPENDENCY_LOCK_AUDIT.json",
        "Production lock audit negative control":
            "python scripts/quality/bys360_dependency_lock_gate.py self-test --vulnerable-lock "
            "tests/fixtures/dependency_audit/requirements_lock_pre_fix_vulnerable.lock "
            "--report reports/quality/BYS360_DEPENDENCY_LOCK_SELFTEST.json",
    }
    order = [text.index("      - name: Dependency vulnerability audit\n")]
    for name, command in expected.items():
        assert text.count(f"      - name: {name}\n") == 1
        assert f"run: {command}\n" in _step(text, name)
        order.append(text.index(f"      - name: {name}\n"))
    order.append(text.index("      - name: Upload quality reports\n"))
    assert order == sorted(order)


def test_windows_ci_regenerates_builds_and_installs_the_lock_with_hashes():
    text = SCORE100.read_text(encoding="utf-8")
    install = _step(text, "Production lock offline hash-checked install (Windows)")
    for token in ("--no-index", "--find-links", "--require-hashes", "--only-binary=:all:", "-r requirements.lock",
                  "bys360-lock-venv/Scripts/python.exe"):
        assert token in install, token
    assert "--no-deps" not in install  # pip's resolver must see the whole graph under real Windows markers
    assert "generate_bys360_requirements_lock.py --check" in _step(text, "Production lock regeneration check (Windows)")
    assert "build_bys360_wheelhouse.py" in _step(text, "Production wheelhouse build and hash verification (Windows)")
    assert "pip check" in _step(text, "Production lock dependency consistency (Windows)")
    assert "smoke_bys360_locked_dependencies.py" in _step(text, "Production lock runtime smoke (Windows)")
    assert text.index("Production lock runtime smoke (Windows)") < text.index("- name: Run BYS360 Quality Assurance Gate V1")


@pytest.mark.parametrize("path", [CI, SCORE100], ids=["ci", "score100"])
def test_no_bypass_in_dependency_steps(path):
    text = path.read_text(encoding="utf-8")
    for forbidden in ("continue-on-error", "|| true", "--ignore-vuln", "PIP_AUDIT_IGNORE"):
        assert forbidden not in text, forbidden
