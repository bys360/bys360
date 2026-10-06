"""BYS360 DEFECT AR: app/performance/interim_notes_manager_routes.py's
_ensure_table() hardcoded ``id SERIAL PRIMARY KEY`` (PostgreSQL-only syntax)
with no dialect branch, unlike the sibling dialect-safe helper
app/services/performance/interim_notes_runtime.py::_id_sql(). On SQLite,
``SERIAL`` is accepted as an arbitrary (non-INTEGER) type-affinity token, so
SQLite does not apply rowid-alias/autoincrement behavior to it and every
inserted row's ``id`` came back permanently NULL.

The fix reuses the existing dialect-safe ``_id_sql()`` helper instead of a
new hand-rolled branch. This contract proves the id column now actually
works (non-NULL, distinct, incrementing) for rows created through the real
POST /performance/interim-notes route on SQLite -- the same route path
tests/security/test_phase13b_csrf_and_scope.py already exercises for the
unrelated cross-user scope fix, which continuing to pass is itself proof the
raw string-built IN-clause parameterization fix in this same commit did not
regress live scoped reads.

While implementing this fix, empirical verification (not just static
reading) uncovered that the "reference" helper itself,
interim_notes_runtime.py::_dialect_name(), had its own separate, deeper
pre-existing bug: it read ``db.session.bind``, which this Flask-SQLAlchemy
version always returns as None (confirmed directly), instead of the correct
``db.session.get_bind()``. Every call silently hit the except branch and
defaulted to "postgresql" -- meaning _id_sql()/_bool_sql() always took the
PostgreSQL branch even when actually running on SQLite, so the *reference*
table (performance_interim_notes, managed by ensure_interim_notes_table())
had exactly the same permanently-NULL id bug this whole time, despite
"looking" dialect-branched in a static read. That helper was fixed too; since
G3-A the table is created by Alembic revision x1f3a9c5e7b2 instead, and
test_interim_notes_table_id_column_is_not_null_on_sqlite below proves the
same guarantee there.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

_TMP_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "defect_ar" / "test_dbs"


def _make_app(monkeypatch: pytest.MonkeyPatch):
    _TMP_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TMP_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ar-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ar-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
    return flask_app


def _create_user(app, *, sicil_no, email, role="personel", yonetici_sicil=None):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Defect",
            soyad="AR",
            role=role,
            yonetici_sicil=yonetici_sicil,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("DefectArTestKey1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": "DefectArTestKey1!"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_interim_note_id_column_is_not_null_after_insert_on_sqlite(monkeypatch):
    app = _make_app(monkeypatch)
    manager_id = _create_user(app, sicil_no="ar010", email="ar.manager@ktb.gov.tr", role="birim_sorumlusu")
    subordinate_id = _create_user(
        app, sicil_no="ar011", email="ar.subordinate@ktb.gov.tr", role="personel", yonetici_sicil="ar010",
    )

    client = app.test_client()
    _login(client, "ar010")

    for note_text in ("BYS360-DEFECT-AR-NOTE-ONE", "BYS360-DEFECT-AR-NOTE-TWO"):
        response = client.post(
            "/performance/interim-notes",
            data={"personnel_id": str(subordinate_id), "note_type": "genel", "note": note_text},
            follow_redirects=False,
        )
        assert response.status_code == 302
    assert manager_id is not None

    from app.extensions import db

    with app.app_context():
        rows = db.session.execute(
            db.text("SELECT id, note FROM performance_interim_notes_live ORDER BY id ASC")
        ).fetchall()

    assert len(rows) == 2
    ids = [row[0] for row in rows]
    # Before the fix every id was NULL on SQLite; now ids must exist and be
    # distinct, incrementing primary-key values.
    assert all(i is not None for i in ids)
    assert len(set(ids)) == 2
    assert ids[0] < ids[1]


def test_interim_notes_table_id_column_is_not_null_on_sqlite(monkeypatch, install_interim_notes_schema):
    # Since G3-A the table comes from Alembic revision x1f3a9c5e7b2 (the readiness helper no
    # longer creates it); the Defect AR guarantee -- a real autoincrement id on SQLite -- holds there.
    app = _make_app(monkeypatch)
    with app.app_context():
        from app.extensions import db
        from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

        install_interim_notes_schema(db.engine)
        ok, warnings = ensure_interim_notes_table()
        assert ok, warnings

        db.session.execute(
            db.text(
                "INSERT INTO performance_interim_notes (employee_id, note_type, note) "
                "VALUES (:employee_id, :note_type, :note)"
            ),
            {"employee_id": 1, "note_type": "genel_gozlem", "note": "BYS360-DEFECT-AR-REFERENCE-TABLE-NOTE"},
        )
        db.session.commit()

        row = db.session.execute(
            db.text("SELECT id FROM performance_interim_notes WHERE note = :note"),
            {"note": "BYS360-DEFECT-AR-REFERENCE-TABLE-NOTE"},
        ).fetchone()

    assert row is not None
    assert row[0] is not None


def test_interim_notes_list_view_renders_real_created_at_label_not_empty_on_sqlite(monkeypatch):
    """BYS360 DEFECT FS (Final Sweep A1-04): the list query in
    performance_interim_notes() used TO_CHAR(n.created_at, 'DD.MM.YYYY
    HH24:MI') -- a PostgreSQL-only function with no SQLite equivalent at
    any version. On SQLite this raised inside _rows()'s broad except,
    which logged and returned an empty list -- so the manager's note list
    silently rendered as empty instead of showing real note data. Fix:
    fetch the raw datetime and format it in Python (same "%d.%m.%Y %H:%M"
    convention already used elsewhere in this codebase)."""
    app = _make_app(monkeypatch)
    _create_user(app, sicil_no="fs104", email="fs104.manager@ktb.gov.tr", role="birim_sorumlusu")
    subordinate_id = _create_user(
        app, sicil_no="fs105", email="fs105.subordinate@ktb.gov.tr", role="personel", yonetici_sicil="fs104",
    )

    client = app.test_client()
    _login(client, "fs104")

    response = client.post(
        "/performance/interim-notes",
        data={"personnel_id": str(subordinate_id), "note_type": "genel", "note": "BYS360-DEFECT-FS-A1-04-NOTE"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    list_response = client.get("/performance/interim-notes")
    assert list_response.status_code == 200

    body = list_response.get_data(as_text=True)
    assert "BYS360-DEFECT-FS-A1-04-NOTE" in body, (
        "Before the fix, TO_CHAR's SQLite failure was silently swallowed and "
        "the note list rendered empty -- the posted note must be visible."
    )
    import re
    assert re.search(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", body), (
        "Expected a real 'DD.MM.YYYY HH:MM' formatted created_at_label in the "
        "rendered page (the same display format TO_CHAR previously produced "
        "on PostgreSQL), not a missing/blank date."
    )
