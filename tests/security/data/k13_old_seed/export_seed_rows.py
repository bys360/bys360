"""Regenerate an old-seed fixture: run the seeder of a checked-out BYS360 tree on an empty SQLite file.

Usage (from the root of a worktree checked out at COMMIT, with this repo's virtualenv)::

    python <this file> COMMIT OUTPUT.json

The fixture holds only ``role_menu_defaults`` rows ``[role_name, menu_key, is_visible, source_type]``
written by that tree's ``ensure_settings_phase1_seeded``; no user, institution or live data.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path


def rows_digest(rows: list[list]) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def main(commit: str, output: Path) -> None:
    db_file = Path(tempfile.gettempdir()) / f"bys360_seed_export_{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "seed-export", "DATABASE_URL": uri, "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false", "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "seed-export-first",
    }.items():
        os.environ[key] = value
    sys.path.insert(0, os.getcwd())
    from config import Config

    Config.APP_ENV = "testing"
    Config.SQLALCHEMY_DATABASE_URI = uri
    Config.SQLALCHEMY_ENGINE_OPTIONS = {}
    from app import create_app
    from app.extensions import db

    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=uri)
    with app.app_context():
        db.create_all()
        import importlib.util

        if importlib.util.find_spec("app.services.runtime_schema"):  # absent in older trees
            importlib.import_module("app.services.runtime_schema").provision_all()
        from app.models.settings_models import RoleMenuDefault
        from app.services.settings_service import ensure_settings_phase1_seeded

        assert ensure_settings_phase1_seeded(updated_by_user_id=None).get("ok")
        rows = sorted([r.role_name, r.menu_key, bool(r.is_visible), r.source_type] for r in RoleMenuDefault.query.all())
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)
    payload = {
        "provenance": {
            "commit": commit,
            "generator": "tests/security/data/k13_old_seed/export_seed_rows.py",
            "seeder": "app.services.settings_service.ensure_settings_phase1_seeded on an empty SQLite database",
            "row_count": len(rows),
            "rows_sha256": rows_digest(rows),
        },
        "rows": rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(output, payload["provenance"])


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
