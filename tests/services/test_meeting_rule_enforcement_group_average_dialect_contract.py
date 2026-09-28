"""BYS360 DEFECT FS (Final Sweep A1-01):
app/services/performance/meeting_rule_enforcement.py::
build_employee_group_average_context() previously cast scores with the
PostgreSQL-only `column::numeric` syntax inside its UNION-ALL subquery
(needed there because ROUND(AVG(<float column>), N) is invalid on
PostgreSQL, the same class of defect already fixed elsewhere for
process_engine_phase6_president_approvals.py / dashboard_rebuild_service.py).
`::numeric` itself is not valid SQLite syntax ("unrecognized token: ':'"),
and the failure was silently swallowed by `_rows()`'s broad except,
returning an empty result set instead of a computed average -- so an
employee's "kendi grup ortalaması" panel silently showed no data on a
SQLite-backed instance, with no visible error.

Fix: CAST(x AS NUMERIC), which is ANSI-portable and behaves identically
on SQLite (confirmed) and PostgreSQL (already the established fix pattern
in this codebase), instead of the `::` shorthand.

This test proves the real, end-to-end behavioral fix against a genuine
SQLite-backed Flask app (not a bare sqlite3 connection), reusing the
already-live schema/seeding helper (ensure_meeting_rule_foundation) rather
than hand-rolling the category schema.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-fs-meeting-rule-enforcement")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    tmp_dir = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_fs_meeting_rule")
    os.makedirs(tmp_dir, exist_ok=True)
    db_path = os.path.join(tmp_dir, f"defect_fs_meeting_rule_{uuid.uuid4().hex}.sqlite3")
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
        from app.services import runtime_schema
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
    return flask_app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


def test_group_average_is_computed_not_silently_empty_on_sqlite(app):
    with app.app_context():
        from app.extensions import db
        from app.models import PerformanceEvaluation, PerformancePeriod, User
        from app.services.performance.meeting_rule_enforcement import (
            build_employee_group_average_context,
            ensure_meeting_rule_foundation,
        )

        ensure_meeting_rule_foundation(seed_categories=True)

        category_id = db.session.execute(
            db.text("SELECT id FROM performance_employee_categories ORDER BY id ASC LIMIT 1")
        ).scalar()
        assert category_id is not None, "seeded default category must exist"

        employee = User(
            sicil_no="FSMR001", email="fs-mr-001@bys360.test", ad="Deniz", soyad="Group",
            role="personel", is_active=True, must_change_password=False, must_set_security_question=False,
        )
        employee.set_password("DefectFsMeetingRuleTestKey1!")
        peer = User(
            sicil_no="FSMR002", email="fs-mr-002@bys360.test", ad="Baris", soyad="Peer",
            role="personel", is_active=True, must_change_password=False, must_set_security_question=False,
        )
        peer.set_password("DefectFsMeetingRuleTestKey1!")
        db.session.add_all([employee, peer])
        db.session.commit()

        db.session.execute(
            db.text(
                "INSERT INTO performance_employee_category_assignments (employee_id, category_id, is_active) "
                "VALUES (:eid, :cid, 1)"
            ),
            {"eid": employee.id, "cid": category_id},
        )
        db.session.execute(
            db.text(
                "INSERT INTO performance_employee_category_assignments (employee_id, category_id, is_active) "
                "VALUES (:eid, :cid, 1)"
            ),
            {"eid": peer.id, "cid": category_id},
        )
        db.session.commit()

        period = PerformancePeriod(
            title="Defect FS Meeting Rule Period", period_type="yillik",
            start_date=__import__("datetime").date(2026, 1, 1),
            end_date=__import__("datetime").date(2026, 12, 31),
        )
        db.session.add(period)
        db.session.commit()

        db.session.add(PerformanceEvaluation(
            period_id=period.id, employee_id=employee.id, final_total_100=80.0,
            status="tamamlandi", is_published_to_employee=True,
        ))
        db.session.add(PerformanceEvaluation(
            period_id=period.id, employee_id=peer.id, final_total_100=90.0,
            status="tamamlandi", is_published_to_employee=True,
        ))
        db.session.commit()

        result = build_employee_group_average_context(employee.id, period_id=period.id)

        # Before the fix: `::numeric` raised on SQLite, silently swallowed,
        # record_count stayed 0 and average_score stayed None.
        assert result["record_count"] == 2, result
        assert result["average_score"] == pytest.approx(85.0), result
