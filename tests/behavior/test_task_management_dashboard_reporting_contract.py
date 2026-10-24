"""BYS360_COVERAGE_WAVE7_AGENT3_TASK_MANAGEMENT_DASHBOARD_REPORTING_CONTRACT

Behavioral, service-boundary contract for the approved Wave 7 remaining
surface of app/services/performance/task_management_service.py (Wave 6
already covered clear_period_task_records and log_performance_
recommendation_export -- neither is retested here):

    build_task_management_dashboard_payload
    matches_audit_query / filter_audit_rows / build_audit_employee_options
    build_assignment_recommendation_payload
    build_task_health_csv_text / build_task_audit_csv_text /
        build_task_recommendation_export_response

Tested directly at the service-function boundary (matching Wave 6's own
precedent for this exact file): real Flask app_context/test_request_context
+ real ORM + real SQLite DB throughout; no mocking of any function under
test.

DEFECT R (discovered during this wave, NOT fixed, NOT characterized as
correct -- reported separately, mechanically reproduced before writing a
single test):

Both `build_task_management_dashboard_payload` and
`build_assignment_recommendation_payload` normalize their `scope_user_ids`
parameter with the repeated idiom `scope_user_ids = scope_user_ids or
set()` followed by `scope_user_ids if scope_user_ids else None` at every
downstream call site. This collapses an EXPLICITLY EMPTY scope (`set()`,
representing "this caller's authorized scope currently contains zero
employees") into the SAME thing as `None` (representing "no scope
restriction at all" -- the legitimate global/full-access case) before it
ever reaches `_apply_assignment_scope`, which itself has a real, different,
fail-closed contract for exactly this distinction (`if scope_user_ids is
not None and not scope_ids: return query.filter(EvaluationAssignment.
employee_id == -1)`).

Direct reproduction (before writing this file): with one real
EvaluationAssignment row seeded, `build_task_management_dashboard_payload
(period, scope_user_ids=set())` returned `stats={'total': 1, ...}` --
byte-identical to `scope_user_ids=None` (the legitimate global-scope
result) -- while `scope_user_ids={some_unrelated_user_id}` (a real,
non-empty, correctly-mismatched scope) returned `stats={'total': 0, ...}`
as expected. This proves the defect is isolated specifically to the
explicitly-empty-set input shape, not to scoping in general.

Impact: a caller whose real, legitimately-computed authorization scope
resolves to zero currently-authorized employees would see the FULL
organization-wide dashboard (assignment counts, delegated/uncovered
assignment identities, exempt-evaluation records, hierarchy alerts)
instead of an empty one. Severity assessed as MEDIUM-HIGH given the
confidentiality-adjacent blast radius, even though end-to-end reachability
from a live caller was not traced beyond this file's own boundary (that
would require tracing app/view_helpers.py::build_scope_switch_context and
app/services/hierarchy_admin_service.py, both outside this wave's approved
file scope).

Per this wave's defect-handling rule, this file therefore:
  - Does NOT test `scope_user_ids=set()` as if it correctly returns empty
    results (it does not -- that would fabricate a passing test for
    behavior that isn't real).
  - Does NOT test `scope_user_ids=set()` as if the global-fallback were
    correct/intended (that would freeze a genuine defect as design).
  - DOES test the two confirmed-correct, unaffected contracts: `scope_
    user_ids=None` (global scope, correct) and `scope_user_ids={real_ids}`
    (correctly scoped, both matching-inclusion and correctly-excluding-
    mismatch cases) -- proven via the same direct-reproduction technique
    above, now captured as permanent regression tests.

SQL dialect note: `_filtered_assignment_query` uses SQLAlchemy's portable
`.ilike()` column method (not a raw `ILIKE` SQL keyword) for its free-text
search -- SQLAlchemy compiles this to a dialect-appropriate case-
insensitive comparison on every backend, confirmed working here against
real SQLite. No other dialect-specific construct (information_schema,
ARRAY, JSONB, RETURNING, ON CONFLICT) appears anywhere in this file.

Fixture pattern: this wave's mandatory proven shape, copied from Wave 6's
own tests/behavior/test_task_management_destructive_and_audit_contract.py
(Config class-attribute patch BEFORE create_app(), StaticPool + pysqlite
isolation_level=None + explicit BEGIN event listener). Several functions
under test call `url_for(...)` internally, so this file wraps those calls
in `app.test_request_context()` (SERVER_NAME configured) rather than a
bare app_context -- still pure service-level testing, no Flask test client
or HTTP route involved. Uses its own dedicated tmp DB directory
(C:\\bys360_pytest_tmp_wave7_agent3) so it shares no state with any other
wave/agent running concurrently.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave7_agent3")

DEFAULT_PASSWORD = "Wave7Agent3TaskDashboardTest1!"
DEFAULT_FIRST_LOGIN_PASSWORD = "wave7-agent3-first-login-test-pw"

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-wave7-agent3-contract")
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
    db_path = os.path.join(_TMP_DB_DIR, f"wave7_agent3_{uuid.uuid4().hex}.sqlite3")
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
        SERVER_NAME="wave7-agent3.test",
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


def _create_user(app, *, role="personel", ad=None, soyad=None, is_active=True):
    from app.extensions import db
    from app.models import User

    n = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"W7A3{n:06d}",
            email=f"wave7-agent3-{n}@bys360.test",
            ad=ad or "Wave7",
            soyad=soyad or f"Dashboard{n}",
            role=role,
            is_active=is_active,
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
            title=f"Wave7 Agent3 Period {n}",
            name=f"Wave7 Agent3 Period {n}",
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


def _create_coverage_log(app, *, period_id, employee_id, event_type, severity="warning", reason=None, acting_evaluator_id=None, original_evaluator_id=None):
    from app.extensions import db
    from app.models import AssignmentCoverageLog

    with app.app_context():
        row = AssignmentCoverageLog(
            period_id=period_id,
            employee_id=employee_id,
            manager_level=1,
            event_scope="generation",
            event_type=event_type,
            severity=severity,
            reason=reason,
            acting_evaluator_id=acting_evaluator_id,
            original_evaluator_id=original_evaluator_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _get_coverage_logs(app, ids):
    from app.models import AssignmentCoverageLog

    with app.app_context():
        return AssignmentCoverageLog.query.filter(AssignmentCoverageLog.id.in_(ids)).order_by(AssignmentCoverageLog.id.asc()).all()


def _fetch_coverage_logs_in_context(ids):
    """Like _get_coverage_logs, but assumes an app_context is already active
    on the stack -- callers that need to access lazy relationships
    (row.employee, row.acting_evaluator, ...) on the returned rows must
    fetch and use them inside the SAME app_context, since a Flask-
    SQLAlchemy scoped session is torn down at that context's exit and a
    previously-returned row's lazy attributes become inaccessible (a real
    SQLAlchemy detached-instance constraint, not a workaround for one)."""
    from app.models import AssignmentCoverageLog

    return AssignmentCoverageLog.query.filter(AssignmentCoverageLog.id.in_(ids)).order_by(AssignmentCoverageLog.id.asc()).all()


# ---------------------------------------------------------------------------
# 1. build_task_management_dashboard_payload -- scoping contract (Defect R aware)
# ---------------------------------------------------------------------------


def test_dashboard_none_scope_shows_global_assignments(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids=None)

    assert payload["stats"]["total"] == 1
    assert payload["stats"]["pending"] == 1


def test_dashboard_real_scope_includes_matching_employee(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids={employee_id})

    assert payload["stats"]["total"] == 1


def test_dashboard_real_scope_excludes_unrelated_employee(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    employee_id = _create_user(app)
    unrelated_id = _create_user(app)
    period_id = _create_period(app)
    _create_assignment(app, period_id=period_id, employee_id=employee_id, evaluator_id=evaluator_id)

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids={unrelated_id})

    assert payload["stats"]["total"] == 0, "a real, non-empty scope that excludes the assignment's employee must show zero, not fall back to global data"
    assert payload["assignments"] == []


def test_dashboard_status_aggregates_correct_across_mixed_states(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    evaluator_id = _create_user(app)
    period_id = _create_period(app)
    emp_pending = _create_user(app)
    emp_partial = _create_user(app)
    emp_completed = _create_user(app)
    _create_assignment(app, period_id=period_id, employee_id=emp_pending, evaluator_id=evaluator_id, status="bekliyor")
    _create_assignment(app, period_id=period_id, employee_id=emp_partial, evaluator_id=evaluator_id, status="kismen_tamamlandi")
    _create_assignment(app, period_id=period_id, employee_id=emp_completed, evaluator_id=evaluator_id, status="tamamlandi")

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(_get_period(app, period_id), scope_user_ids=None)

    stats = payload["stats"]
    assert stats["total"] == 3
    assert stats["pending"] == 1
    assert stats["partial"] == 1
    assert stats["completed"] == 1


def test_dashboard_no_period_returns_empty_shell_without_crashing(app):
    from app.services.performance.task_management_service import (
        build_task_management_dashboard_payload,
    )

    with app.test_request_context():
        payload = build_task_management_dashboard_payload(None, scope_user_ids=None)

    assert payload["stats"]["total"] == 0
    assert payload["assignments"] == []


# ---------------------------------------------------------------------------
# 2. matches_audit_query / filter_audit_rows -- pure query filtering
# ---------------------------------------------------------------------------


def test_matches_audit_query_matches_across_searchable_fields(app):
    from app.services.performance.task_management_service import matches_audit_query

    period_id = _create_period(app)
    employee_id = _create_user(app, ad="Aylin", soyad="Kaya")
    log_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered", reason="zincir kirigi")

    with app.app_context():
        (row,) = _fetch_coverage_logs_in_context([log_id])
        assert matches_audit_query(row, "aylin") is True
        assert matches_audit_query(row, "kaya") is True
        assert matches_audit_query(row, "uncovered") is True
        assert matches_audit_query(row, "zincir") is True
        assert matches_audit_query(row, "") is True


def test_matches_audit_query_excludes_non_matching_rows(app):
    from app.services.performance.task_management_service import matches_audit_query

    period_id = _create_period(app)
    employee_id = _create_user(app, ad="Aylin", soyad="Kaya")
    log_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")

    with app.app_context():
        (row,) = _fetch_coverage_logs_in_context([log_id])
        assert matches_audit_query(row, "tamamen-alakasiz-arama-metni") is False


def test_filter_audit_rows_filters_by_severity(app):
    from app.services.performance.task_management_service import filter_audit_rows

    period_id = _create_period(app)
    employee_id = _create_user(app)
    warn_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered", severity="warning")
    crit_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered", severity="critical")
    rows = _get_coverage_logs(app, [warn_id, crit_id])

    with app.app_context():
        result = filter_audit_rows(rows, severity="critical")

    assert [r.id for r in result] == [crit_id]


def test_filter_audit_rows_filters_by_event_type(app):
    from app.services.performance.task_management_service import filter_audit_rows

    period_id = _create_period(app)
    employee_id = _create_user(app)
    uncovered_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered")
    chain_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="chain_issue")
    rows = _get_coverage_logs(app, [uncovered_id, chain_id])

    with app.app_context():
        result = filter_audit_rows(rows, event_type="chain_issue")

    assert [r.id for r in result] == [chain_id]


def test_filter_audit_rows_filters_by_employee_id(app):
    from app.services.performance.task_management_service import filter_audit_rows

    period_id = _create_period(app)
    employee_a = _create_user(app)
    employee_b = _create_user(app)
    log_a = _create_coverage_log(app, period_id=period_id, employee_id=employee_a, event_type="uncovered")
    log_b = _create_coverage_log(app, period_id=period_id, employee_id=employee_b, event_type="uncovered")
    rows = _get_coverage_logs(app, [log_a, log_b])

    with app.app_context():
        result = filter_audit_rows(rows, employee_id=employee_b)

    assert [r.id for r in result] == [log_b]


def test_filter_audit_rows_combines_severity_and_query_filters(app):
    from app.services.performance.task_management_service import filter_audit_rows

    period_id = _create_period(app)
    employee_id = _create_user(app, ad="Deniz", soyad="Yildiz")
    match_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered", severity="critical", reason="ozel-arama-terimi")
    wrong_severity_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered", severity="warning", reason="ozel-arama-terimi")

    with app.app_context():
        rows = _fetch_coverage_logs_in_context([match_id, wrong_severity_id])
        result = filter_audit_rows(rows, severity="critical", q="ozel-arama-terimi")
        result_ids = [r.id for r in result]

    assert result_ids == [match_id]


# ---------------------------------------------------------------------------
# 3. build_audit_employee_options -- real DB query
# ---------------------------------------------------------------------------


def test_build_audit_employee_options_excludes_admin_and_inactive(app):
    from app.services.performance.task_management_service import build_audit_employee_options

    active_id = _create_user(app, ad="Zeynep", soyad="Aktif", is_active=True)
    _create_user(app, role="admin", ad="Admin", soyad="Kisi", is_active=True)
    _create_user(app, ad="Pasif", soyad="Kisi", is_active=False)

    with app.app_context():
        options = build_audit_employee_options()
        option_ids = {u.id for u in options}

    assert active_id in option_ids
    assert len(options) == 1


def test_build_audit_employee_options_sorted_by_first_then_last_name(app):
    from app.services.performance.task_management_service import build_audit_employee_options

    _create_user(app, ad="Zehra", soyad="Aaa")
    _create_user(app, ad="Ahmet", soyad="Zzz")

    with app.app_context():
        options = build_audit_employee_options()

    names = [u.ad for u in options]
    assert names == sorted(names)


def test_build_audit_employee_options_scoped_to_ids(app):
    from app.services.performance.task_management_service import build_audit_employee_options

    in_scope_id = _create_user(app)
    out_of_scope_id = _create_user(app)

    with app.app_context():
        options = build_audit_employee_options(scope_user_ids={in_scope_id})
        option_ids = {u.id for u in options}

    assert option_ids == {in_scope_id}
    assert out_of_scope_id not in option_ids


# ---------------------------------------------------------------------------
# 4. build_assignment_recommendation_payload
# ---------------------------------------------------------------------------


def test_recommendation_payload_empty_shell_when_no_period(app):
    from app.services.performance.task_management_service import (
        build_assignment_recommendation_payload,
    )

    with app.test_request_context():
        payload = build_assignment_recommendation_payload(None, "")

    assert payload["recommendation_rows"] == []
    assert payload["action_plan_rows"] == []
    assert payload["summary"]["uncovered"] == 0


def test_recommendation_payload_reflects_real_uncovered_logs(app):
    from app.services.performance.task_management_service import (
        build_assignment_recommendation_payload,
    )

    period_id = _create_period(app)
    employee_id = _create_user(app)
    _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered", severity="warning")

    with app.test_request_context():
        payload = build_assignment_recommendation_payload(_get_period(app, period_id), "")

    assert payload["summary"]["uncovered"] == 1
    assert len(payload["recommendation_rows"]) >= 1
    assert any("Açıkta" in row["title"] for row in payload["recommendation_rows"])
    assert len(payload["action_plan_rows"]) >= 1


# ---------------------------------------------------------------------------
# 5. build_task_health_csv_text / build_task_audit_csv_text
# ---------------------------------------------------------------------------


def test_build_task_health_csv_text_headers_and_rows(app):
    from app.services.performance.task_management_service import build_task_health_csv_text

    report = {
        "duplicate_rows": [{"employee_name": "Ada Lovelace", "employee_unit": "Bilgi İşlem", "manager_level": 1, "evaluators": ["Amir A"], "row_count": 2, "source_labels": ["direct"]}],
        "mismatch_rows": [],
        "orphan_evaluations": [],
        "orphan_assignments": [],
        "health_rows": [],
    }

    csv_text = build_task_health_csv_text(report)

    assert csv_text.startswith("\ufeff")
    assert "Bölüm" in csv_text
    assert "Mükerrer görev" in csv_text
    assert "Ada Lovelace" in csv_text


def test_build_task_health_csv_text_empty_report_still_has_header_and_bom(app):
    from app.services.performance.task_management_service import build_task_health_csv_text

    csv_text = build_task_health_csv_text({})

    assert csv_text.startswith("\ufeff")
    assert "Bölüm" in csv_text
    lines = csv_text.lstrip("\ufeff").strip().splitlines()
    assert len(lines) == 1, "an empty health report must produce only the header row, never a fabricated data row"


def test_build_task_audit_csv_text_real_rows_null_safe(app):
    from app.services.performance.task_management_service import build_task_audit_csv_text

    period_id = _create_period(app)
    employee_id = _create_user(app, ad="Can", soyad="Demir")
    log_id = _create_coverage_log(app, period_id=period_id, employee_id=employee_id, event_type="uncovered", severity="critical", reason="test nedeni")

    with app.app_context():
        rows = _fetch_coverage_logs_in_context([log_id])
        csv_text = build_task_audit_csv_text(rows)

    assert csv_text.startswith("\ufeff")
    assert "Personel" in csv_text
    assert "Can Demir" in csv_text
    assert "critical" in csv_text
    assert "test nedeni" in csv_text


def test_build_task_audit_csv_text_empty_rows_still_has_header(app):
    from app.services.performance.task_management_service import build_task_audit_csv_text

    csv_text = build_task_audit_csv_text([])

    assert csv_text.startswith("\ufeff")
    assert "Personel" in csv_text


# ---------------------------------------------------------------------------
# 6. build_task_recommendation_export_response
# ---------------------------------------------------------------------------


def test_build_task_recommendation_export_response_csv_content_and_type(app):
    from app.services.performance.task_management_service import (
        build_task_recommendation_export_response,
    )

    action_plan_rows = [
        {"priority": 1, "title": "Açıkta kalan görevleri önce kapat", "count": 5, "tone": "critical", "owner": "İK", "next_step": "İncele", "url": "/x"},
    ]

    result = build_task_recommendation_export_response(action_plan_rows, export_format="csv")

    assert result["mimetype"] == "text/csv; charset=utf-8"
    assert result["extension"] == "csv"
    assert result["content"].startswith("\ufeff")
    assert "Açıkta kalan görevleri önce kapat" in result["content"]


def test_build_task_recommendation_export_response_defaults_to_csv_for_unknown_format(app):
    from app.services.performance.task_management_service import (
        build_task_recommendation_export_response,
    )

    result = build_task_recommendation_export_response([], export_format="unknown-format")

    assert result["extension"] == "csv"
