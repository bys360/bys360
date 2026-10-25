"""Teardown for test fixtures that build a throwaway SQLite database file.

Most app fixtures create a full-schema SQLite file (about 4.6 MB) in the system
temp directory for every test. Without a teardown the files are never deleted:
one CI Step 14 run left 8.7 GiB behind, the runner hit its disk quota and the
last tests failed with ``disk I/O error``.

``release_sqlite_app`` closes the application's connections and deletes the
database file of that application only, with its journal/WAL/SHM side files.
It refuses a database that is not a SQLite file inside the temp directory, so a
repository, instance or production database is never touched.

Register it right after the app is created, so it runs when the fixture's
scope ends, whether the test passed or failed::

    flask_app = _make_app(monkeypatch)
    request.addfinalizer(functools.partial(release_sqlite_app, flask_app))
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

SQLITE_URI_PREFIX = "sqlite:///"
SQLITE_SUFFIXES = (".sqlite3", ".sqlite", ".db")
SIDE_FILE_SUFFIXES = ("-journal", "-wal", "-shm")


def sqlite_file_of(flask_app: Any, *, root: Path | str | None = None) -> Path:
    """The SQLite database file of ``flask_app``; it must lie inside ``root`` (default: the temp dir)."""
    uri = str(flask_app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    raw = uri[len(SQLITE_URI_PREFIX):]
    if not uri.startswith(SQLITE_URI_PREFIX) or raw in ("", ":memory:"):
        raise ValueError(f"not a SQLite database file: {uri!r}")
    if "?" in raw or not Path(raw).is_absolute():
        # A relative path is resolved by Flask-SQLAlchemy against instance_path, not the cwd.
        raise ValueError(f"not an absolute SQLite file path: {uri!r}")
    path = Path(raw).resolve()
    base = Path(root if root is not None else tempfile.gettempdir()).resolve()
    if base not in path.parents:
        raise ValueError(f"{path} is outside {base}")
    if path.suffix not in SQLITE_SUFFIXES:
        raise ValueError(f"{path} is not a SQLite database file name")
    return path


def release_sqlite_app(flask_app: Any, *, root: Path | str | None = None) -> None:
    """Close the app's connections, then delete its SQLite file and side files."""
    path = sqlite_file_of(flask_app, root=root)
    from app.extensions import db

    with flask_app.app_context():
        engine_file = db.engine.url.database
        if not engine_file or Path(engine_file).resolve() != path:
            raise ValueError(f"the engine uses {engine_file!r}, not the configured {path}")
        db.session.remove()
        db.engine.dispose()
    for candidate in (path, *(Path(f"{path}{suffix}") for suffix in SIDE_FILE_SUFFIXES)):
        candidate.unlink(missing_ok=True)
