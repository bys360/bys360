"""Regression contract: app/ai/decision_support_faz9_routes.py's
_notification_rows()/_mail_log_rows() used PostgreSQL-only ``ILIKE``, which
SQLite's driver does not support at all. Replaced with
``LOWER(x) LIKE LOWER(y)`` (ANSI-standard, dialect-neutral, uses bound
parameters), preserving the same case-insensitive, diacritic-literal
substring-match semantics on both PostgreSQL and SQLite -- a plain
``ILIKE`` -> ``LIKE`` text swap would have been unsafe (SQLite's own LIKE
is already case-insensitive for ASCII, masking the difference there, but
PostgreSQL's LIKE is case-sensitive by default, so a naive swap would
silently break matching on PostgreSQL).

Mechanical reproduction of the prior defect: the raw query raised
``sqlite3.OperationalError: near "ILIKE": syntax error`` unconditionally,
once an unrelated earlier fix (introspection helper portability) let
_table_columns() stop crashing first and let execution reach this query
for the first time.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_am")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-am-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-am-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_am_{uuid.uuid4().hex}.sqlite3")
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
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )
    return flask_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
    yield flask_app


def _insert_notification(db, title: str):
    from app.models.communication_models import Notification

    row = Notification(user_id=1, title=title, notification_type="test")
    db.session.add(row)
    db.session.commit()
    return row


def _insert_mail_log(db, subject: str):
    from app.models.communication_models import MailLog

    row = MailLog(
        mail_type="test",
        recipient_email="test@example.com",
        subject=subject,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_notification_rows_real_caller_succeeds_on_sqlite(app) -> None:
    from app.ai.decision_support_faz9_routes import _notification_rows

    with app.app_context():
        assert list(_notification_rows()) == []


def test_mail_log_rows_real_caller_succeeds_on_sqlite(app) -> None:
    from app.ai.decision_support_faz9_routes import _mail_log_rows

    with app.app_context():
        assert list(_mail_log_rows()) == []


def test_notification_rows_matches_lowercase_uppercase_and_mixed_case(app) -> None:
    from app.ai.decision_support_faz9_routes import _notification_rows
    from app.extensions import db

    with app.app_context():
        lower = _insert_notification(db, "performans hatirlatmasi")
        upper = _insert_notification(db, "PERFORMANS RAPORU HAZIR")
        mixed = _insert_notification(db, "Performans degerlendirmesi baslatildi")
        unrelated = _insert_notification(db, "Sistem Bakim Bildirimi")

        matched_ids = {row["id"] for row in _notification_rows()}
        assert lower.id in matched_ids
        assert upper.id in matched_ids
        assert mixed.id in matched_ids
        assert unrelated.id not in matched_ids


def test_notification_rows_matches_the_diacritic_keyword_in_natural_sentence_case(app) -> None:
    from app.ai.decision_support_faz9_routes import _notification_rows
    from app.extensions import db

    with app.app_context():
        row = _insert_notification(db, "Yillik değerlendirme sonuclari yayinlandi")
        matched_ids = {r["id"] for r in _notification_rows()}
        assert row.id in matched_ids


def test_notification_rows_diacritic_keyword_uppercase_edge_case_is_a_disclosed_sqlite_limitation(app) -> None:
    """SQLite's built-in LOWER() only folds ASCII (confirmed: sqlite3's own
    LOWER('DEĞERLENDIRME') leaves the non-ASCII Ğ untouched) -- this is a
    pre-existing SQLite platform limitation, not something this fix
    introduces or could portably close without registering a custom
    Unicode-aware SQL function (a materially larger, connection-level
    change outside this defect's boundary). The ASCII keyword
    ("performans") is unaffected in any casing; only an ALL-CAPS Turkish
    word containing a non-ASCII letter (Ğ, İ, Ş, Ö, Ü, Ç) in the target
    text is affected, and only on SQLite. Documented here rather than
    silently assumed to work."""
    from app.ai.decision_support_faz9_routes import _notification_rows
    from app.extensions import db

    with app.app_context():
        row = _insert_notification(db, "Yillik DEĞERLENDIRME sonuclari yayinlandi")
        matched_ids = {r["id"] for r in _notification_rows()}
        assert row.id not in matched_ids  # documents the known SQLite-only gap, not the desired end state


def test_mail_log_rows_matches_lowercase_uppercase_and_mixed_case(app) -> None:
    from app.ai.decision_support_faz9_routes import _mail_log_rows
    from app.extensions import db

    with app.app_context():
        lower = _insert_mail_log(db, "performans ozeti ektedir")
        upper = _insert_mail_log(db, "PERFORMANS OZETI EKTEDIR")
        unrelated = _insert_mail_log(db, "Fatura bildirimi")

        matched_ids = {row["id"] for row in _mail_log_rows()}
        assert lower.id in matched_ids
        assert upper.id in matched_ids
        assert unrelated.id not in matched_ids
