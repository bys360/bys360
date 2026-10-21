"""Contract for scripts/release/generate_bys360_requirements_lock.py and the committed lock.

pip is never run here: ``run_pip_resolution`` is replaced by synthetic reports, so these tests
are offline. The real resolution is exercised by the Windows CI step
``generate_bys360_requirements_lock.py --check``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.ci_safe

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "generate_bys360_requirements_lock.py"


def _load():
    spec = importlib.util.spec_from_file_location("bys360_lock_generator_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _item(name, version, requires=(), filename=None, yanked=False):
    filename = filename or f"{name.lower().replace('-', '_')}-{version}-py3-none-any.whl"
    return {
        "metadata": {"name": name, "version": version, "requires_dist": list(requires)},
        "download_info": {"url": f"https://files.example/{filename}",
                          "archive_info": {"hashes": {"sha256": _sha(name + version)}}},
        "is_yanked": yanked,
    }


def _report(*items):
    return {"version": "1", "install": list(items)}


def _write_project(tmp_path, requirements, previous):
    (tmp_path / "requirements.txt").write_text(requirements, encoding="utf-8")
    lines = ["# previous lock", ""]
    for name, version in previous:
        lines += [f"{name}=={version} \\", f"    --hash=sha256:{_sha(name + version)}"]
    (tmp_path / "requirements.lock").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path / "requirements.txt", tmp_path / "requirements.lock"


@pytest.fixture
def fake_pip(monkeypatch):
    calls = []

    def install(reports):
        def run(requirements, constraints, extra_roots, report):
            calls.append({"extra_roots": list(extra_roots), "constraints": constraints.read_text(encoding="utf-8")})
            return reports[min(len(calls), len(reports)) - 1]

        monkeypatch.setattr(gen, "run_pip_resolution", run)
        monkeypatch.setattr(gen, "check_interpreter", lambda: None)
        return calls

    return install


def test_windows_only_dependency_is_added_in_a_second_pass(tmp_path, fake_pip):
    """pip on Linux drops click's colorama; the Windows closure must bring it back."""
    req, lock = _write_project(tmp_path, "click==8.4.2\n", [("click", "8.4.2"), ("colorama", "0.4.6")])
    click = _item("click", "8.4.2", ['colorama; platform_system == "Windows"'])
    calls = fake_pip([_report(click), _report(click, _item("colorama", "0.4.6"))])
    text = gen.generate(req, lock, {})
    assert [c["extra_roots"] for c in calls] == [[], ["colorama"]]
    assert "colorama==0.4.6" in calls[0]["constraints"] and "click" not in calls[0]["constraints"]
    assert "\ncolorama==0.4.6 \\\n    --hash=sha256:" in text
    assert "# bys360-lock: packages=2 direct=1 transitive=1\n" in text


def test_extras_requested_in_requirements_reach_the_closure(tmp_path, fake_pip):
    req, lock = _write_project(tmp_path, "sentry-sdk[flask]==2.20.0\n", [("sentry-sdk", "2.20.0"), ("blinker", "1.9.0")])
    sentry = _item("sentry-sdk", "2.20.0", ['blinker>=1.1; extra == "flask"'])
    fake_pip([_report(sentry, _item("blinker", "1.9.0"))])
    text = gen.generate(req, lock, {})
    assert "#   sentry-sdk==2.20.0\n" in text and "\nblinker==1.9.0 \\\n" in text


def test_package_only_a_linux_host_needs_is_refused(tmp_path, fake_pip):
    req, lock = _write_project(tmp_path, "app==1.0\n", [("app", "1.0"), ("linuxonly", "2.0")])
    fake_pip([_report(_item("app", "1.0", ['linuxonly; sys_platform == "linux"']), _item("linuxonly", "2.0"))])
    with pytest.raises(gen.LockGenerationError, match="does not need"):
        gen.generate(req, lock, {})


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (_item("app", "1.0", filename="app-1.0.tar.gz"), "not a wheel"),
        (_item("app", "1.0", filename="app-1.0-cp312-cp312-manylinux_2_28_x86_64.whl"), "no tag supported"),
        (_item("app", "1.0", yanked=True), "yanked"),
        (_item("app", "1.0", filename="not-a-valid-wheel.whl"), "invalid wheel filename"),
    ],
    ids=["sdist", "linux-wheel", "yanked", "bad-filename"],
)
def test_unusable_artifacts_are_refused(tmp_path, fake_pip, item, message):
    req, lock = _write_project(tmp_path, "app==1.0\n", [("app", "1.0")])
    fake_pip([_report(item)])
    with pytest.raises(gen.LockGenerationError, match=message):
        gen.generate(req, lock, {})


def test_new_package_is_refused(tmp_path, fake_pip):
    req, lock = _write_project(tmp_path, "app==1.0\n", [("app", "1.0")])
    fake_pip([_report(_item("app", "1.0", ["newdep"]), _item("newdep", "1.0"))])
    with pytest.raises(gen.LockGenerationError, match="new package newdep"):
        gen.generate(req, lock, {})


def test_unapproved_transitive_version_change_is_refused(tmp_path, fake_pip):
    req, lock = _write_project(tmp_path, "app==1.0\n", [("app", "1.0"), ("dep", "1.0")])
    fake_pip([_report(_item("app", "1.0", ["dep"]), _item("dep", "1.1"))])
    with pytest.raises(gen.LockGenerationError, match="unapproved version change dep 1.0 -> 1.1"):
        gen.generate(req, lock, {})


def test_upgrade_package_moves_only_the_named_pin(tmp_path, fake_pip):
    req, lock = _write_project(tmp_path, "app==1.0\n", [("app", "1.0"), ("dep", "1.0"), ("other", "3.0")])
    calls = fake_pip([_report(_item("app", "1.0", ["dep", "other"]), _item("dep", "1.1"), _item("other", "3.0"))])
    text = gen.generate(req, lock, {"dep": "1.1"})
    assert "dep==1.1" in calls[0]["constraints"] and "other==3.0" in calls[0]["constraints"]
    assert "\ndep==1.1 \\\n" in text


@pytest.mark.parametrize("value", ["dep>=1.1", "dep", "dep==1.1; sys_platform=='win32'"])
def test_upgrade_package_needs_an_exact_pin(value):
    with pytest.raises(gen.LockGenerationError):
        gen.parse_upgrades([value])


def test_upgrade_of_a_direct_or_unknown_package_is_refused(tmp_path, fake_pip):
    req, lock = _write_project(tmp_path, "app==1.0\n", [("app", "1.0")])
    fake_pip([_report(_item("app", "1.0"))])
    with pytest.raises(gen.LockGenerationError, match="requirements.txt"):
        gen.generate(req, lock, {"app": "2.0"})
    with pytest.raises(gen.LockGenerationError, match="new packages are refused"):
        gen.generate(req, lock, {"ghost": "1.0"})


@pytest.mark.parametrize("line", ["app>=1.0", "app==1.0; sys_platform == 'win32'", "-e .", "app"])
def test_requirements_must_be_exact_pins(tmp_path, line):
    path = tmp_path / "requirements.txt"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(gen.LockGenerationError):
        gen.read_requirements(path)


def test_interpreter_other_than_cpython_312_is_refused(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 13, 0, "final", 0))
    with pytest.raises(gen.LockGenerationError, match="CPython 3.12"):
        gen.check_interpreter()


def test_rendered_lock_is_byte_exact(tmp_path, fake_pip):
    req, lock = _write_project(tmp_path, "Zeta==2.0\nalpha==1.0\n", [("alpha", "1.0"), ("Zeta", "2.0"), ("mid_dep", "0.1")])
    fake_pip([_report(_item("Zeta", "2.0", ["mid-dep"]), _item("alpha", "1.0"), _item("mid_dep", "0.1"))])
    text = gen.generate(req, lock, {})
    body = text.split("# Direct dependencies (pinned in requirements.txt):\n", 1)[1]
    assert body == (
        "#   alpha==1.0\n#   Zeta==2.0\n\n"
        f"alpha==1.0 \\\n    --hash=sha256:{_sha('alpha1.0')}\n"
        f"mid_dep==0.1 \\\n    --hash=sha256:{_sha('mid_dep0.1')}\n"
        f"Zeta==2.0 \\\n    --hash=sha256:{_sha('Zeta2.0')}\n"
    )
    assert "\r" not in text and text.isascii()


def test_check_mode_accepts_crlf_and_reports_any_difference(tmp_path, fake_pip, monkeypatch, capsys):
    req, lock = _write_project(tmp_path, "app==1.0\n", [("app", "1.0")])
    fake_pip([_report(_item("app", "1.0"))])
    text = gen.generate(req, lock, {})
    lock.write_bytes(text.replace("\n", "\r\n").encode("ascii"))
    assert gen.main(["--root", str(tmp_path), "--check"]) == 0
    lock.write_text(text.replace("app==1.0 \\", "app==1.0  \\"), encoding="ascii")
    assert gen.main(["--root", str(tmp_path), "--check"]) == 1
    assert "requirements.lock (regenerated)" in capsys.readouterr().out
    assert gen.main(["--root", str(tmp_path), "--check", "--upgrade-package", "app==2.0"]) == 1


# ------------------------------------------------------------------ the committed lock


def _committed():
    text = (ROOT / "requirements.lock").read_text(encoding="ascii")
    direct = gen.read_requirements(ROOT / "requirements.txt")
    entries = gen.parse_lock(ROOT / "requirements.lock")
    return text, direct, entries


def test_committed_lock_is_in_generator_form():
    """Rendering the committed pins again gives the committed bytes: nothing was hand-edited."""
    text, direct, entries = _committed()
    packages = {
        gen.canonicalize_name(e.name): gen.ResolvedPackage(e.name, e.version, "", e.hashes[0]) for e in entries
    }
    assert all(len(e.hashes) == 1 for e in entries)
    assert gen.render(packages, direct) == text


def test_committed_lock_contains_the_approved_security_versions():
    _, direct, entries = _committed()
    pins = {gen.canonicalize_name(e.name): e.version for e in entries}
    assert len(pins) == 59
    assert pins["colorama"] == "0.4.6"  # Windows-only (click), must not be lost
    assert {k: pins[k] for k in ("pillow", "werkzeug", "urllib3", "certifi")} == {
        "pillow": "13.0.0", "werkzeug": "3.1.9", "urllib3": "2.8.0", "certifi": "2026.10.19",
    }
    for d in direct:
        assert pins[gen.canonicalize_name(d.name)] == d.version, d.name
