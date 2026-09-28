"""P2-05 contract: the existing constraints that stop duplicate / stale
critical-operation transitions stay in force.

Final pre-live audit (2026-09-27): no ``SELECT ... FOR UPDATE`` is used; two
concurrent approvals / publications / rescorings are last-writer-wins. That is
a structural risk, not a reproduced corruption. This contract pins the guards
that already make the dangerous interleavings fail loudly instead of
producing duplicate state:

- one evaluation per (period, employee)          uq_period_employee_evaluation
- one item per (evaluation, criteria, level)     uq_eval_criteria_level_item
- one assignment per (period, employee, evaluator, level)
- one snapshot row per (period, employee, version_no): two publishers that
  both compute the same next version cannot both commit a current row
- one process flow / low-score process per evaluation

Approval re-decisions (approved <-> returned) are deliberately allowed by the
current services; turning them into first-decision-wins is a policy choice
(HUMAN DECISION REQUIRED), see docs/quality/BYS360_CONCURRENCY_CRITICAL_OPERATIONS.md.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        db_path = os.path.join(str(tmp_path_factory.mktemp("p2_05")), f"p2_05_{uuid.uuid4().hex}.sqlite3")
        db_uri = "sqlite:///" + db_path.replace("\\", "/")
        for key, value in {
            "APP_ENV": "testing",
            "SECRET_KEY": "test-secret-key-for-p2-05-idempotency-contract",
            "DEFAULT_FIRST_LOGIN_PASSWORD": "p2-05-first-login-test-pw",
            "FLASK_SKIP_SCHEMA_VALIDATION": "1",
            "AUTO_REPAIR_SCHEMA": "false",
            "STRICT_SCHEMA_CHECK": "false",
            "REQUIRE_DOTENV_FILE": "false",
            "STRICT_ENV_VALIDATION": "false",
            "WTF_CSRF_ENABLED": "false",
            "SCHEDULER_ENABLED": "false",
            "MAIL_SUPPRESS_SEND": "true",
            "DATABASE_URL": db_uri,
        }.items():
            monkeypatch.setenv(key, value)

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
            db.session.commit()
        yield flask_app


@pytest.fixture
def seed(app):
    from app.extensions import db
    from app.models import PerformanceCriteria, PerformanceEvaluation, PerformancePeriod, User

    with app.app_context():
        suffix = uuid.uuid4().hex[:8]
        employee = User(sicil_no=f"I5E{suffix}", email=f"e{suffix}@example.gov.tr", ad="Idem", soyad="Personel", role="personel", is_active=True)
        evaluator = User(sicil_no=f"I5V{suffix}", email=f"v{suffix}@example.gov.tr", ad="Idem", soyad="Amir", role="grup_baskani", is_active=True)
        for user in (employee, evaluator):
            user.set_password("TestIdempotencyContract-2026!x")
        period = PerformancePeriod(title=f"P2-05 {suffix}", period_type="quarterly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_active=True)
        criteria = PerformanceCriteria(name=f"P2-05 Kriter {suffix}", weight=100.0, sort_order=0, is_active=True)
        db.session.add_all([employee, evaluator, period, criteria])
        db.session.flush()
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=employee.id, status="tamamlandi")
        db.session.add(evaluation)
        db.session.commit()
        ids = {
            "employee": employee.id,
            "evaluator": evaluator.id,
            "period": period.id,
            "criteria": criteria.id,
            "evaluation": evaluation.id,
        }
    return ids


def _duplicate_is_rejected(app, factory) -> None:
    from app.extensions import db

    with app.app_context():
        db.session.add(factory())
        db.session.commit()
        db.session.add(factory())
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_second_evaluation_for_the_same_period_and_employee_is_rejected(app, seed) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        db.session.add(PerformanceEvaluation(period_id=seed["period"], employee_id=seed["employee"], status="taslak"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_duplicate_evaluation_item_for_the_same_level_is_rejected(app, seed) -> None:
    from app.models import PerformanceEvaluationItem

    _duplicate_is_rejected(
        app,
        lambda: PerformanceEvaluationItem(
            evaluation_id=seed["evaluation"], criteria_id=seed["criteria"], manager_level=1, score=4.0, score_100=80.0
        ),
    )


def test_duplicate_assignment_for_the_same_evaluator_level_is_rejected(app, seed) -> None:
    from app.models import EvaluationAssignment

    _duplicate_is_rejected(
        app,
        lambda: EvaluationAssignment(
            period_id=seed["period"], employee_id=seed["employee"], evaluator_id=seed["evaluator"], manager_level=1
        ),
    )


def test_two_snapshots_with_the_same_version_cannot_both_commit(app, seed) -> None:
    from app.models import PerformanceResultSnapshot

    _duplicate_is_rejected(
        app,
        lambda: PerformanceResultSnapshot(
            period_id=seed["period"],
            evaluation_id=seed["evaluation"],
            employee_id=seed["employee"],
            employee_name_snapshot="Idem Personel",
            sicil_no_snapshot="I5E",
            final_total_100=80.0,
            published_at=datetime(2026, 4, 1),
            source_type="system_published",
            version_no=1,
            is_current=True,
        ),
    )


def test_second_process_flow_for_the_same_evaluation_is_rejected(app, seed) -> None:
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    _duplicate_is_rejected(app, lambda: PerformanceProcessFlow(evaluation_id=seed["evaluation"], employee_id=seed["employee"]))
