"""Regression contract: AI decision support Faz 8 queries use the canonical schema
(BYS360 live evidence remediation V1).

The Faz 8 SELECTs named performance_periods.period_name / scope_reference /
category_id / unit_id and evaluation_assignments.evaluated_user_id. None of
these exist in the ORM model or in a fresh migration-built database, and the
live validation (2026-09-28) proved period_name and evaluated_user_id absent
on production, so both Faz 8 endpoints failed on every request.

Canonical replacements, taken from the models rather than from name similarity:
- evaluated person: EvaluationAssignment.employee_id (relationship ``employee``)
- period title: performance_periods.title (normalize_period reads title first)
- scope target: the column period_forms requires per scope type --
  scope_unit_label (unit, upper_unit), scope_category_label (category) and
  scope_personnel_filter (selected_personnel, presence only: it holds registry
  numbers and must not leave the database layer)
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

GHOST_COLUMNS = ("period_name", "evaluated_user_id", "scope_reference", "category_id", "unit_id")
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_live_schema_b")


def _make_app(monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "APP_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-live-schema-b-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "live-schema-b-first-login-test-pw",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"live_schema_b_{uuid.uuid4().hex}.sqlite3")
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
    return flask_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    flask_app = _make_app(monkeypatch)
    with flask_app.app_context():
        from app.extensions import db
        from app.models import EvaluationAssignment, PerformancePeriod

        db.create_all()
        periods = {
            "category": PerformancePeriod(title="Kategori Dönemi", period_type="special", scope_type="category",
                                          scope_category_label="Teknik Personel",
                                          start_date=date(2026, 1, 1), end_date=date(2026, 6, 30)),
            "unit": PerformancePeriod(title="Birim Dönemi", period_type="special", scope_type="unit",
                                      scope_unit_label="Bilgi İşlem", start_date=date(2026, 2, 1), end_date=date(2026, 7, 31)),
            "personnel": PerformancePeriod(title="Seçili Personel Dönemi", period_type="special", scope_type="selected_personnel",
                                           scope_personnel_filter="98765,43210", start_date=date(2026, 3, 1), end_date=date(2026, 8, 31)),
            "all": PerformancePeriod(title="Yıllık Dönem", period_type="annual", scope_type="all",
                                     start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)),
        }
        db.session.add_all(periods.values())
        db.session.flush()
        for employee_id in (11, 12):
            db.session.add(EvaluationAssignment(period_id=periods["category"].id, employee_id=employee_id,
                                                evaluator_id=90, manager_level=1))
        db.session.add(EvaluationAssignment(period_id=periods["unit"].id, employee_id=13, evaluator_id=90, manager_level=1))
        db.session.commit()
        flask_app.config["_TEST_PERIOD_IDS"] = {key: period.id for key, period in periods.items()}
    yield flask_app
    with flask_app.app_context():
        from app.extensions import db

        db.session.remove()


def _orm_columns(model) -> set[str]:
    return {column.name for column in model.__table__.columns}


def test_select_lists_are_canonical_model_columns() -> None:
    import app.ai.decision_support_faz8_routes as faz8
    from app.models import EvaluationAssignment, PerformancePeriod

    assert set(faz8.PERIOD_COLUMNS) <= _orm_columns(PerformancePeriod)
    assert set(faz8.ASSIGNMENT_COLUMNS) <= _orm_columns(EvaluationAssignment)
    assert "employee_id" in faz8.ASSIGNMENT_COLUMNS
    for ghost in GHOST_COLUMNS:
        assert ghost not in faz8.PERIOD_COLUMNS
        assert ghost not in faz8.ASSIGNMENT_COLUMNS


def test_select_lists_are_covered_by_the_fresh_migration_gate() -> None:
    import app.ai.decision_support_faz8_routes as faz8
    from scripts.quality.bys360_postgres_migration_integrity_gate import CRITICAL_COLUMNS

    assert set(faz8.PERIOD_COLUMNS) <= set(CRITICAL_COLUMNS["performance_periods"])
    assert set(faz8.ASSIGNMENT_COLUMNS) <= set(CRITICAL_COLUMNS["evaluation_assignments"])


def test_president_approval_orm_columns_are_covered_by_the_fresh_migration_gate() -> None:
    from app.models.performance_process_engine_models import PerformancePresidentApproval
    from scripts.quality.bys360_postgres_migration_integrity_gate import CRITICAL_COLUMNS

    assert set(CRITICAL_COLUMNS["performance_president_approvals"]) == _orm_columns(PerformancePresidentApproval)


def test_executed_faz8_sql_never_names_a_ghost_column(app) -> None:
    import app.ai.decision_support_faz8_routes as faz8
    from app.extensions import db

    with app.app_context():
        statements: list[str] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", _capture)
        try:
            faz8._periods(250)
            faz8._single_period(app.config["_TEST_PERIOD_IDS"]["category"])
            faz8._assignments()
            faz8._assignments(period_id=app.config["_TEST_PERIOD_IDS"]["category"])
        finally:
            event.remove(db.engine, "before_cursor_execute", _capture)

    faz8_sql = [s for s in statements if "performance_periods" in s or "evaluation_assignments" in s]
    assert len(faz8_sql) == 4
    for statement in faz8_sql:
        for ghost in GHOST_COLUMNS:
            assert ghost not in statement, f"{ghost} still queried: {statement}"


def test_scope_summary_maps_canonical_columns_semantically(app) -> None:
    import app.ai.decision_support_faz8_routes as faz8
    from app.services.ai_decision.period_scope_integration import build_period_scope_summary_payload

    ids = app.config["_TEST_PERIOD_IDS"]
    with app.app_context():
        payload = build_period_scope_summary_payload(faz8._periods(250), faz8._assignments(), None, {})

    by_id = {item["id"]: item for item in payload["periods"]}
    assert by_id[ids["category"]]["title"] == "Kategori Dönemi"
    assert by_id[ids["category"]]["scope_reference"] == "Teknik Personel"
    assert by_id[ids["unit"]]["scope_reference"] == "Bilgi İşlem"
    assert by_id[ids["personnel"]]["scope_reference"] == faz8.SELECTED_PERSONNEL_REFERENCE
    assert by_id[ids["all"]]["scope_reference"] is None
    assert by_id[ids["category"]]["assignment_count"] == 2
    assert by_id[ids["unit"]]["assignment_count"] == 1
    assert by_id[ids["personnel"]]["assignment_count"] == 0
    # The selected-personnel filter holds registry numbers; they must not reach the output.
    rendered = json.dumps(payload, ensure_ascii=False, default=str)
    assert "98765" not in rendered and "43210" not in rendered


def test_single_period_check_and_missing_period(app) -> None:
    import app.ai.decision_support_faz8_routes as faz8
    from app.services.ai_decision.period_scope_integration import build_single_period_payload

    period_id = app.config["_TEST_PERIOD_IDS"]["category"]
    with app.app_context():
        period = faz8._single_period(period_id)
        payload = build_single_period_payload(period, faz8._periods(500), faz8._assignments(period_id=period_id), {})
        with pytest.raises(LookupError):
            faz8._single_period(999_999)

    assert payload["period"]["title"] == "Kategori Dönemi"
    assert payload["period"]["scope_reference"] == "Teknik Personel"
    assert payload["period"]["assignment_count"] == 2
    assert "scope_personnel_filter" not in period
