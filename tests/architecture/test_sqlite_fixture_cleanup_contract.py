"""Throwaway SQLite files of app fixtures are deleted when the fixture's scope ends.

Root cause (CI ``quality-gate`` Step 14, 23 Oct 2026): most app fixtures build a
full-schema SQLite file (about 4.6 MB) in the system temp directory for every test
and never delete it. One Step 14 run left 8.74 GiB in /tmp (11,985 inodes; open
file handles were not the cause), the runner hit its disk quota and the last
tests failed with ``disk I/O error``. ``tests/sqlite_test_cleanup.py`` adds
``release_sqlite_app``; every measured leaker registers it right after the app
is created.

This contract checks that the helper deletes the app's own database file and
side files only, refuses anything that is not a SQLite file in the temp
directory, runs after a passing test, a failing test and a failing fixture setup,
never deletes a module-scoped database while its tests still run, and that no
test module builds a temp SQLite app without a cleanup again.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app, sqlite_file_of

REPO_ROOT = Path(__file__).resolve().parents[2]
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "sqlite_fixture_cleanup_contract"

# Modules that set DATABASE_URL but do not patch Config, so their app uses Config's
# import-time default: in CI Step 14 that is sqlite:///:memory: (measured 0 bytes on
# 60d07e74). Run alone, the module may be the first to import config and then all of its
# tests share that one file, so a per-test finalizer would delete it under the next test.
# They need Config patched like the other fixtures before a finalizer can be added.
_NO_FILE_CREATED = {
    "tests/security/test_phase13b_password_reset.py",
    "tests/security/test_phase13b_setup_admin.py",
}

_APP_ENV = {
    "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-sqlite-cleanup", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
    "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
    "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false", "SCHEDULER_ENABLED": "false",
    "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    "DEFAULT_FIRST_LOGIN_PASSWORD": "sqlite-cleanup-test-first-login",
}


def _fake_app(uri: str) -> SimpleNamespace:
    return SimpleNamespace(config={"SQLALCHEMY_DATABASE_URI": uri})


def _open_handles_to(path: Path) -> list[str]:
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():  # no /proc (e.g. Windows): nothing to inspect
        return []
    targets = []
    for fd in fd_dir.iterdir():
        try:
            targets.append(os.readlink(fd))
        except OSError:
            continue
    return [t for t in targets if t.startswith(str(path))]


# ---------------------------------------------------------------------------
# 1. The helper only accepts a SQLite file inside the temp directory
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("uri", [
    "sqlite://", "sqlite:///", "sqlite:///:memory:",
    "postgresql://user@localhost/bys360", "",
])
def test_non_file_databases_are_refused(uri) -> None:
    with pytest.raises(ValueError):
        sqlite_file_of(_fake_app(uri))


def test_database_outside_the_temp_directory_is_refused(tmp_path) -> None:
    outside = REPO_ROOT / "instance" / "bys360.sqlite3"
    with pytest.raises(ValueError, match="outside"):
        sqlite_file_of(_fake_app("sqlite:///" + outside.as_posix()))
    narrow_root = tmp_path / "own_root"
    sibling = tmp_path / "other_root" / "db.sqlite3"
    with pytest.raises(ValueError, match="outside"):
        sqlite_file_of(_fake_app("sqlite:///" + sibling.as_posix()), root=narrow_root)


def test_non_sqlite_file_name_is_refused() -> None:
    path = _DB_ROOT / "notes.txt"
    with pytest.raises(ValueError, match="not a SQLite"):
        sqlite_file_of(_fake_app("sqlite:///" + path.as_posix()))


@pytest.mark.parametrize("raw", ["relative.sqlite3", "sub/dir/relative.sqlite3"])
def test_relative_path_is_refused(raw) -> None:
    with pytest.raises(ValueError, match="absolute"):
        sqlite_file_of(_fake_app("sqlite:///" + raw))


def test_uri_with_query_is_refused() -> None:
    path = _DB_ROOT / "db.sqlite3"
    with pytest.raises(ValueError, match="absolute"):
        sqlite_file_of(_fake_app("sqlite:///" + path.as_posix() + "?mode=ro"))


# ---------------------------------------------------------------------------
# 2. Real app: only its own file and side files go; its connections are closed
# ---------------------------------------------------------------------------
def test_release_deletes_only_the_apps_database_and_closes_its_connections(monkeypatch) -> None:
    folder = _DB_ROOT / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    db_path = folder / "own.sqlite3"
    neighbour = folder / "neighbour.sqlite3"
    neighbour.write_bytes(b"not this fixture's database")
    uri = "sqlite:///" + db_path.as_posix()
    # Import before DATABASE_URL is set: Config reads it once, at first import, and other
    # tests rely on that default; this test must not leave its own path there.
    from app import create_app
    from config import Config

    for key, value in {**_APP_ENV, "DATABASE_URL": uri}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        db.create_all()
        assert db.session.query(User).count() == 0  # a pooled connection is now open
    for suffix in ("-journal", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").write_bytes(b"side file")
    assert db_path.stat().st_size > 0

    release_sqlite_app(flask_app)

    assert not db_path.exists()
    assert not any(Path(f"{db_path}{suffix}").exists() for suffix in ("-journal", "-wal", "-shm"))
    assert neighbour.read_bytes() == b"not this fixture's database"
    assert _open_handles_to(db_path) == []
    release_sqlite_app(flask_app)  # idempotent: a second call finds nothing to delete

    # Configured file and engine file disagree: refuse and delete nothing.
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + neighbour.as_posix()
    with pytest.raises(ValueError, match="engine uses"):
        release_sqlite_app(flask_app)
    assert neighbour.read_bytes() == b"not this fixture's database"
    neighbour.unlink()
    folder.rmdir()


# ---------------------------------------------------------------------------
# 3. Pytest teardown: passing test, failing test, failing setup, module scope
# ---------------------------------------------------------------------------
_PROBE_MODULE = '''
import json, os, uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

ROOT = Path({root!r})
MANIFEST = Path({manifest!r})
ENV = {env!r}


def _record(label, path, exists_during_test=None):
    data = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {{}}
    data.setdefault(label, []).append({{"path": str(path), "during": exists_during_test}})
    MANIFEST.write_text(json.dumps(data))


def _make_app(monkeypatch):
    ROOT.mkdir(parents=True, exist_ok=True)
    db_path = ROOT / f"{{uuid.uuid4().hex}}.sqlite3"
    uri = "sqlite:///" + db_path.as_posix()
    for key, value in {{**ENV, "DATABASE_URL": uri}}.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {{}})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db

    with flask_app.app_context():
        db.create_all()
    return flask_app, db_path


@pytest.fixture
def app(monkeypatch, request):
    flask_app, db_path = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app, db_path


@pytest.fixture
def broken_app(monkeypatch, request):
    flask_app, db_path = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    _record("setup_error", db_path, db_path.exists())
    raise RuntimeError("later setup step fails")


@pytest.fixture(scope="module")
def shared_app(request):
    with pytest.MonkeyPatch.context() as monkeypatch:
        flask_app, db_path = _make_app(monkeypatch)
        request.addfinalizer(lambda: release_sqlite_app(flask_app))
        yield flask_app, db_path


def test_passes(app):
    _record("passed", app[1], app[1].exists())


def test_fails(app):
    _record("failed", app[1], app[1].exists())
    assert False, "deliberate failure"


def test_setup_error(broken_app):
    pass


def test_module_scope_first(shared_app):
    _record("module_first", shared_app[1], shared_app[1].exists())


def test_module_scope_second(shared_app):
    _record("module_second", shared_app[1], shared_app[1].exists())
'''


def test_files_are_deleted_after_pass_failure_setup_error_and_module_scope(tmp_path) -> None:
    root = _DB_ROOT / f"probe_{uuid.uuid4().hex}"
    manifest = tmp_path / "manifest.json"
    probe = tmp_path / "test_sqlite_cleanup_probe.py"
    probe.write_text(textwrap.dedent(_PROBE_MODULE.format(
        root=str(root), manifest=str(manifest), env=_APP_ENV)), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), str(probe)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr
    assert "3 passed" in summary and "1 failed" in summary and "1 error" in summary, result.stdout + result.stderr

    data = json.loads(manifest.read_text())
    for label in ("passed", "failed", "setup_error"):
        (entry,) = data[label]
        assert entry["during"] is True, label  # the file existed while the test used it
        assert not Path(entry["path"]).exists(), label  # and is gone after teardown
    first, second = data["module_first"][0], data["module_second"][0]
    assert first["path"] == second["path"]
    assert first["during"] is True and second["during"] is True  # not deleted between the module's tests
    assert not Path(first["path"]).exists()
    assert not root.exists() or not any(root.iterdir())
    if root.exists():
        root.rmdir()


# ---------------------------------------------------------------------------
# 4. No test module builds a temp SQLite app without a cleanup again
# ---------------------------------------------------------------------------
def _builds_temp_sqlite_app(source: str) -> bool:
    return (
        "create_app(" in source
        and re.search(r"gettempdir\(\)|mkdtemp\(", source) is not None
        and "sqlite:///" in source
        and re.search(r"\.(sqlite3|sqlite|db)\b", source) is not None
    )


def _has_cleanup(source: str) -> bool:
    return "release_sqlite_app" in source or re.search(
        r"\.unlink\(|os\.remove\(|os\.unlink\(|rmtree\(", source) is not None


def test_every_temp_sqlite_app_module_cleans_up() -> None:
    offenders = []
    builders = 0
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8-sig", errors="ignore")
        if not _builds_temp_sqlite_app(source):
            continue
        builders += 1
        if rel not in _NO_FILE_CREATED and not _has_cleanup(source):
            offenders.append(rel)
    assert builders > 100  # the scan really sees the fixtures
    assert offenders == [], (
        "These test modules build an app on a SQLite file in the temp directory without deleting it; "
        "register tests.sqlite_test_cleanup.release_sqlite_app right after create_app: " + ", ".join(offenders)
    )


def test_exempt_modules_still_exist_and_still_need_the_exemption() -> None:
    for rel in sorted(_NO_FILE_CREATED):
        source = (REPO_ROOT / rel).read_text(encoding="utf-8-sig")
        assert _builds_temp_sqlite_app(source), rel
        assert not _has_cleanup(source), f"{rel} cleans up now; drop it from _NO_FILE_CREATED"
