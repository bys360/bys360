"""BYS360_DEFECT_T_REMEDIATION_OPERATIONS_CENTER_EMPTY_SCOPE_FAIL_CLOSED_CONTRACT

Permanent regression contract for DEFECT T
(app/services/performance/ops_center.py::
build_performance_operations_snapshot and its private scope-aware
helpers). Asserts the FIXED behavior only -- it does not characterize,
freeze, or otherwise exercise the prior buggy shape.

Prior defect (fixed by this same change), confirmed by disposable
reproduction before implementing: `build_performance_operations_snapshot`
normalized its `scope_user_ids` argument with `_coerce_scope_ids`, which
always returns a plain `list[int]` (`[]` for both `None` and an explicit
empty scope), then forwarded `scope_ids or None` to EVERY downstream
call -- including the already-fixed `build_task_management_preflight_
report` and `build_performance_task_health_report` (Defect S). Because
`scope_ids or None` collapses an empty list back to `None`, an explicit
empty scope reaching this function was silently converted to
"unrestricted" before it ever reached those correctly fail-closed
functions -- neutralizing their fix for any caller working through
Operations Center. The four private helpers
(`_collect_feedback_data`, `_build_assignment_log_rows`,
`_build_publish_log_rows`, `_build_mail_log_rows`) independently repeated
the same collapse AND had no fail-closed else branch of their own. A
THIRD, independent mechanism: the call into `build_performance_go_live_
center` omitted the `scope_employee_ids` argument entirely, so go-live
cards/blockers were unconditionally organization-wide through this route
regardless of the caller's scope -- not just for the empty-scope edge
case.

The fix preserves whether `scope_user_ids` was `None` end-to-end via
`_normalize_scope_ids` (None stays None; anything else is coerced to a
possibly-empty `list[int]`), forwards that value unchanged (no `or None`)
into every downstream call, adds the missing `employee_id == -1`
fail-closed branch to each private helper, and forwards the scope into
`build_performance_go_live_center` via its `scope_employee_ids`
parameter.

Fixture pattern: service-boundary style (real Flask app_context/
test_request_context + real ORM + real SQLite DB, no mocking of any
function under test), matching this codebase's established Wave 6/7 and
Defect S precedent. Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_defect_t_ops_center) so it shares no state with any
other wave/agent/test file running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_defect_t_ops_center")

DEFAULT_PASSWORD = "DefectTOpsCenterTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "defect-t-ops-center-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-t-ops-center-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", DEFAULT_FIRST_LOGIN_PASSWORD)
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"defect_t_ops_center_{uuid.uuid4().hex}.sqlite3")
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
        SERVER_NAME="defect-t-ops-center.test",
    )

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


# ---------------------------------------------------------------------------
# Fixture builders (real DB rows)
# ---------------------------------------------------------------------------


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, ad="Merve", soyad=None):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"DTOC{n:06d}",
            email=f"defect-t-ops-{n}@bys360.test",
            ad=ad,
            soyad=soyad or f"OpsCenter{n}",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_period(app):
    import datetime as _dt

    from app.extensions import db
    from app.models import PerformancePeriod

    n = _next_suffix()
    with app.app_context():
        period = PerformancePeriod(
            title=f"DefectT OpsCenter Period {n}",
            name=f"DefectT OpsCenter Period {n}",
            period_type="yillik",
            start_date=_dt.date(2026, 1, 1),
            end_date=_dt.date(2026, 12, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _get_period(app, period_id):
    from app.models import PerformancePeriod

    with app.app_context():
        return PerformancePeriod.query.get(period_id)


def _create_assignment(app, *, period_id, employee_id, evaluator_id, manager_level=1, status="bekliyor"):
    from app.extensions import db
    from app.models import EvaluationAssignment

    with app.app_context():
        row = EvaluationAssignment(
            period_id=period_id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            manager_level=manager_level,
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_evaluation(app, *, period_id, employee_id):
    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        row = PerformanceEvaluation(period_id=period_id, employee_id=employee_id)
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_coverage_log(app, *, period_id, employee_id, event_type="uncovered"):
    from app.extensions import db
    from app.models import AssignmentCoverageLog

    with app.app_context():
        row = AssignmentCoverageLog(
            period_id=period_id,
            employee_id=employee_id,
            manager_level=1,
            event_scope="generation",
            event_type=event_type,
            severity="warning",
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_mail_log(app, *, period_id, employee_id):
    import datetime as _dt

    from app.extensions import db
    from app.models import MailLog

    with app.app_context():
        row = MailLog(
            mail_type="feedback_response",
            related_period_id=period_id,
            related_user_id=employee_id,
            recipient_email=f"defect-t-mail-{employee_id}@bys360.test",
            subject="test konu",
            sent_at=_dt.datetime(2026, 1, 5),
            is_success=True,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_feedback_request(app, *, period_id, evaluation_id, employee_id):
    import datetime as _dt

    from app.extensions import db
    from app.models import FeedbackRequest

    with app.app_context():
        row = FeedbackRequest(
            evaluation_id=evaluation_id,
            period_id=period_id,
            employee_id=employee_id,
            reason="test gerekcesi",
            status="bekliyor",
            requested_at=_dt.datetime(2026, 1, 5),
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_publish_log(app, *, period_id, evaluation_id, employee_id):
    import datetime as _dt

    from app.extensions import db
    from app.models import EvaluationPublishLog

    with app.app_context():
        row = EvaluationPublishLog(
            evaluation_id=evaluation_id,
            employee_id=employee_id,
            period_id=period_id,
            action="published",
            acted_at=_dt.datetime(2026, 1, 5),
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_criteria_100(app):
    """Seeds one active criterion whose weight sums to 100 -- avoids the
    period-level "Kriter toplamı 100 değil" blocker, which is unrelated to
    employee scoping, so tests can isolate scope-derived blockers only."""
    from app.extensions import db
    from app.models import PerformanceCriteria

    n = _next_suffix()
    with app.app_context():
        row = PerformanceCriteria(name=f"DefectT Kriter {n}", weight=100.0, is_active=True)
        db.session.add(row)
        db.session.commit()
        return row.id


def _seed_full_snapshot_data(app, *, period_id, evaluator_id, employee_id):
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)
    evaluation_id = _create_evaluation(app, period_id=period_id, employee_id=employee_id)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id)
    _create_mail_log(app, period_id=period_id, employee_id=employee_id)
    _create_feedback_request(app, period_id=period_id, evaluation_id=evaluation_id, employee_id=employee_id)
    _create_publish_log(app, period_id=period_id, evaluation_id=evaluation_id, employee_id=employee_id)


# ---------------------------------------------------------------------------
# 1-4. None / matching / unrelated / empty scope -- top-level snapshot
# ---------------------------------------------------------------------------


def test_none_scope_preserves_unrestricted_behavior(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=None)

    assert snapshot["health_report"]["summary"]["employee_count"] == 2
    assert snapshot["task_preflight"]["health_report"]["summary"]["employee_count"] == 2
    assert snapshot["go_live"]["cards"]["open_assignments"] == 1


def test_matching_nonempty_scope_shows_only_matching_employee_data(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    other_employee_id = _create_user(app)
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)
    _create_assignment(app, period_id=period_id, employee_id=other_employee_id, evaluator_id=evaluator_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids={employee_id})

    assert snapshot["health_report"]["summary"]["employee_count"] == 1
    assert snapshot["go_live"]["cards"]["open_assignments"] == 1, "go_live must now honor the forwarded scope instead of always showing org-wide counts"


def test_unrelated_nonexistent_scope_leaks_no_data(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids={999999})

    assert snapshot["health_report"]["summary"]["employee_count"] == 0
    assert snapshot["task_preflight"]["health_report"]["summary"]["employee_count"] == 0
    assert snapshot["go_live"]["cards"]["open_assignments"] == 0
    assert snapshot["assignment_logs"] == []
    assert snapshot["mail_logs"] == []


def test_empty_set_scope_returns_zero_operations_center_rows(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())

    assert snapshot["health_report"]["summary"]["employee_count"] == 0, "an explicitly empty authorization scope must never fall back to the global/unrestricted dataset"
    assert snapshot["go_live"]["cards"]["open_assignments"] == 0


# ---------------------------------------------------------------------------
# 5-7. nested reports + private helper rows fail closed under empty scope
# ---------------------------------------------------------------------------


def test_empty_set_scope_nested_health_report_is_empty(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())

    assert snapshot["health_report"]["assignments"] == []
    assert snapshot["health_report"]["evaluations"] == []


def test_empty_set_scope_nested_preflight_is_empty(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())

    scope_derived_titles = {"Mükerrer görev satırı bulundu", "Değerlendirme ve görev amiri farklı", "Yetim kayıt bulundu", "Açıkta kalan görev var", "Amir zinciri çakışması bulundu"}
    assert not any(b["title"] in scope_derived_titles for b in snapshot["task_preflight"]["blockers"]), "no scope-derived blocker may surface under an explicitly empty authorization scope"
    assert snapshot["task_preflight"]["health_report"]["assignments"] == []


def test_empty_set_scope_private_helper_rows_are_empty(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())

    assert snapshot["assignment_logs"] == [], "AssignmentCoverageLog rows must not leak under an explicit empty scope"
    assert snapshot["publish_logs"] == [], "EvaluationPublishLog rows must not leak under an explicit empty scope"
    assert snapshot["mail_logs"] == [], "MailLog rows must not leak under an explicit empty scope"
    assert snapshot["cards"]["recent_log_events"] == 0


# ---------------------------------------------------------------------------
# 8. matching scope leaks no unrelated employee identity
# ---------------------------------------------------------------------------


def test_matching_scope_leaks_no_unrelated_employee_identity(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app, ad="Ela", soyad="Yildirim")
    other_employee_id = _create_user(app, ad="Baris", soyad="Ozturk")
    period_id = _create_period(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)
    _create_assignment(app, period_id=period_id, employee_id=other_employee_id, evaluator_id=evaluator_id)
    _create_coverage_log(app, period_id=period_id, employee_id=other_employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids={employee_id})

    serialized = repr(snapshot["assignment_logs"]) + repr(snapshot["health_report"]["assignments"])
    assert "Baris" not in serialized
    assert "Ozturk" not in serialized


# ---------------------------------------------------------------------------
# 9. readiness/cards derive only from scoped data
# ---------------------------------------------------------------------------


def test_empty_set_scope_readiness_and_cards_derive_from_scoped_data_only(app):
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_criteria_100(app)
    _seed_full_snapshot_data(app, period_id=period_id, evaluator_id=evaluator_id, employee_id=employee_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot_empty = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())
        snapshot_none = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=None)

    assert snapshot_empty["cards"]["task_blockers"] == 0
    assert snapshot_empty["cards"]["critical_health"] == 0
    assert snapshot_empty["cards"] != snapshot_none["cards"], "sanity check: the real seeded data does influence the unrestricted (None) scope's cards, proving the empty-scope zeros above are not coincidental"


# ---------------------------------------------------------------------------
# 10. empty scope does not become global at ANY downstream boundary
# ---------------------------------------------------------------------------


def test_empty_set_scope_go_live_does_not_become_global(app):
    """Proves the third, independent T mechanism is fixed: previously
    `scope_employee_ids` was never forwarded to build_performance_go_live_
    center at all, so go_live cards were unconditionally organization-wide
    through Operations Center regardless of scope."""
    from app.services.performance.ops_center import build_performance_operations_snapshot

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context("/performance/operations-center"):
        snapshot_none = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=None)
        snapshot_match = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids={employee_id})
        snapshot_empty = build_performance_operations_snapshot(period=_get_period(app, period_id), viewer=None, scope_user_ids=set())

    assert snapshot_none["go_live"]["cards"]["open_assignments"] == 1
    assert snapshot_match["go_live"]["cards"]["open_assignments"] == 1
    assert snapshot_empty["go_live"]["cards"]["open_assignments"] == 0, "go_live must now vary with scope instead of remaining organization-wide unconditionally"
