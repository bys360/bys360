"""BYS360 DEFECT FS (Final Sweep FS-R2): app/performance/phase10_development_
guidance_ui.py::_concat_name_expr() built a raw ``COALESCE(email::text, '')``
style fallback expression using the PostgreSQL-only ``::text`` cast operator,
with no SQLite equivalent ("unrecognized token: ':'"). _fetch_people_options()
wraps its query in a broad except that logs a warning and returns an empty
list on any failure, so the "Gelişim Rehberi Merkezi" personnel picker
silently rendered empty on a SQLite-backed instance instead of raising.

Every column _concat_name_expr() applies the cast to (email, sicil_no,
full_name_cache, ...) is already a text/string column in this schema, so the
fix removes the cast outright rather than reformulating it as a portable
CAST(... AS TEXT).

This test proves the real, end-to-end behavioral fix: a genuine SQLite-backed
Flask app, a real User row, and a direct call into the same
_fetch_people_options()/_concat_name_expr() code path the live route
(app/performance/meeting_p4_development_guidance_routes.py) uses.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-fs-phase10-people-options")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    tmp_dir = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_fs_phase10_people_options")
    os.makedirs(tmp_dir, exist_ok=True)
    db_path = os.path.join(tmp_dir, f"defect_fs_phase10_people_options_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
    )
    with flask_app.app_context():
        from app.extensions import db
        db.create_all()
    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def test_fetch_people_options_returns_real_rows_not_silently_empty_on_sqlite(app):
    with app.app_context():
        from app.extensions import db
        from app.models import User
        from app.performance.phase10_development_guidance_ui import _fetch_people_options

        user = User(
            sicil_no="FSR2001", email="fs-r2-001@bys360.test", ad="Deniz", soyad="Gelisim",
            role="personel", is_active=True, must_change_password=False, must_set_security_question=False,
        )
        user.set_password("DefectFsR2TestKey1!")
        db.session.add(user)
        db.session.commit()

        # Before the fix: ``::text`` raised OperationalError on SQLite, the
        # broad except in _fetch_people_options() swallowed it and returned
        # [], silently hiding every real employee from the picker.
        options = _fetch_people_options()

        assert options, "expected at least one real people option, got an empty list"
        matching = [o for o in options if o["id"] == user.id]
        assert matching, options
        assert matching[0]["label"], "expected a non-empty fallback label (email/sicil/name)"


def test_concat_name_expr_no_longer_emits_postgresql_only_cast_operator():
    from app.performance.phase10_development_guidance_ui import _concat_name_expr

    expr = _concat_name_expr({"ad", "soyad", "email", "sicil_no", "full_name_cache"})
    assert "::" not in expr, expr


def test_build_phase10_meeting_development_context_people_options_not_silently_empty(app):
    with app.app_context():
        from app.extensions import db
        from app.models import User
        from app.performance.phase10_development_guidance_ui import (
            build_phase10_meeting_development_context,
        )

        user = User(
            sicil_no="FSR2002", email="fs-r2-002@bys360.test", ad="Baris", soyad="Rehber",
            role="personel", is_active=True, must_change_password=False, must_set_security_question=False,
        )
        user.set_password("DefectFsR2TestKey1!")
        db.session.add(user)
        db.session.commit()

        context = build_phase10_meeting_development_context()

        assert context["people_options"], "expected non-empty people_options from the real live context builder"
