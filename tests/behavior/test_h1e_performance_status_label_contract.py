"""BYS360 H1E-D -- performance module raw status/workflow display closure
contract.

Investigation found the performance/president-approval domain already had
FIVE independent "status code -> Turkish label" helper functions (a genuine
duplicate-mapping drift risk), several of which shared the exact
fallback-to-raw defect this initiative targets -- the mapped value was
returned when known, but an UNRECOGNIZED value was echoed back verbatim
(sometimes with cosmetic underscore-to-space cleanup) instead of a safe
generic label:

  - app/services/performance/history.py's humanize_workflow_status() /
    humanize_action_type() -- feeds performance_evaluation_history.html
    and app/services/performance/health_report.py's orphan-evaluation rows
    (performance_task_health.html).
  - app/services/performance/president_card_review_service.py's
    status_label() -- feeds president_card_review.html's scoring-history
    and process-flow-step rows.
  - app/services/performance/phase5_4_status_language.py's
    phase5_4_status_label() Jinja filter -- used directly in
    performance_evaluation_history.html on top of an ALREADY-humanized
    label. A naive "never echo unchanged text" fix here would have been a
    regression (it would blank out perfectly good already-translated
    labels that just don't need further cleanup) -- the actual fix only
    withholds text that looks like a raw machine slug (contains "_", no
    spaces) and was left completely unchanged by both the dictionary
    lookup and the partial-text cleanup pass. This file proves BOTH
    halves: the raw-slug case falls back safely, AND the
    already-humanized-sentence case is NOT touched.
  - app/services/performance/feedback_integration.py had three separate
    "X_LABELS.get(raw, raw)" self-fallback instances (note_type_label,
    aftercare status_label, action status_label) plus one unmapped
    scorecard `status` field with zero translation at all.

app/services/performance_v2/reporting_workspace.py's build_period_scorecard_
context() fed performance_v2_phase5_publish.html's evaluation-status column
with the completely raw Evaluation.status / .workflow_status values (no
label at all) -- new additive status_label / workflow_status_label fields
close this while leaving the raw fields untouched for any existing
comparison/counting logic.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_performance_status_tmp" / "test_dbs"
_PASSWORD = "H1EPerformanceStatusTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_humanize_workflow_status_maps_known_values_and_never_leaks_raw() -> None:
    from app.services.performance.history import humanize_workflow_status

    assert humanize_workflow_status("taslak_1_amir") == "2. amir taslak aşamasında"
    assert humanize_workflow_status("bekliyor_3_amir") == "3. amir bekleniyor"

    # Mandatory negative test: an unrecognized future workflow_status value
    # must never leak raw, cosmetically-cleaned or otherwise.
    assert humanize_workflow_status("future_workflow_state_v9") == "Süreç Durumu"
    assert "future_workflow_state_v9" not in humanize_workflow_status("future_workflow_state_v9")

    assert humanize_workflow_status(None) == "-"
    assert humanize_workflow_status("") == "-"


def test_humanize_action_type_maps_known_values_and_never_leaks_raw() -> None:
    from app.services.performance.history import humanize_action_type

    assert humanize_action_type("SAVED_BY_LEVEL_1") == "1. amir taslağı kaydetti"
    assert humanize_action_type("WITHDRAWN") == "2. amir gönderimi geri çekti"

    assert humanize_action_type("SOME_FUTURE_ACTION_V9") == "Süreç işlemi"
    assert "SOME_FUTURE_ACTION_V9" not in humanize_action_type("SOME_FUTURE_ACTION_V9")

    assert humanize_action_type(None) == "-"


def test_phase5_4_status_label_preserves_already_humanized_text() -> None:
    """Regression guard: this filter is applied a SECOND time, in
    performance_evaluation_history.html, to text that
    humanize_workflow_status() already turned into a proper Turkish
    sentence. It must pass such text through completely unchanged --
    treating "no further cleanup needed" as a leak would blank out
    perfectly good labels."""
    from app.services.performance.phase5_4_status_language import phase5_4_status_label

    already_good = "2. amir taslak aşamasında"
    assert phase5_4_status_label(already_good) == already_good

    another_good_label = "Yayınlanabilir"
    assert phase5_4_status_label(another_good_label) == another_good_label


def test_phase5_4_status_label_maps_known_and_never_leaks_a_raw_slug() -> None:
    from app.services.performance.phase5_4_status_language import phase5_4_status_label

    assert phase5_4_status_label("draft") == "Taslak"
    assert phase5_4_status_label("pending") == "Bekliyor"

    # A raw machine slug (underscored, no spaces) that matches nothing must
    # never be echoed back, even cosmetically cleaned.
    raw_slug = "custom_flow_state_v9"
    result = phase5_4_status_label(raw_slug)
    assert result != raw_slug
    assert "custom_flow_state_v9" not in result
    assert result == "-"

    assert phase5_4_status_label(None) == "-"
    assert phase5_4_status_label("", fallback="Bilinmiyor") == "Bilinmiyor"


def test_president_card_review_status_label_never_leaks_raw() -> None:
    from app.services.performance.president_card_review_service import status_label

    assert status_label("approved") == "Başkan onayladı"
    assert status_label("blocked_president_pending") == "Başkan onayı beklediği için yayın kilitli"

    unmapped = "totally_unknown_future_status_v9"
    result = status_label(unmapped, fallback="Süreç takipte")
    assert result == "Süreç takipte"
    assert unmapped not in result


def test_feedback_integration_source_no_longer_has_self_fallback_pattern() -> None:
    """app/services/performance/feedback_integration.py's action/aftercare/
    note_type status_label fields previously fell back to the raw value
    itself (e.g. `ACTION_STATUS_LABELS.get(str(row.get("status") or ""),
    row.get("status") or "-")`) when unmapped. The underlying tables
    (feedback_meeting_action_plans, feedback_meeting_after_notes) are raw
    SQL-introspected and not present in a fresh db.create_all() test
    database, so this is a source-level regression guard rather than a
    full route exercise -- it locks in that the exact `.get(X, X)` /
    `.get(X, row.get(...) or ...)` self-fallback shape cannot silently
    come back for these three fields."""
    import pathlib

    project_root = pathlib.Path(__file__).resolve().parents[2]
    source = (project_root / "app" / "services" / "performance" / "feedback_integration.py").read_text(encoding="utf-8")
    assert 'row.get("note_type") or "Genel Not")' not in source
    assert 'row.get("status") or "-")' not in source
    assert 'status_label(str(status), status or "Kayıt")' not in source


# ---------------------------------------------------------------------------
# App/client fixtures.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-performance-status-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-performance-status-first-login-test-pw")
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

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="personel", password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="H1E",
            soyad="PerformanceStatusContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _build_evaluation_with_assignment(app, *, evaluator_id, employee_id, workflow_status):
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod

    with app.app_context():
        period = PerformancePeriod(
            title="H1E Performance Status Test Period",
            period_type="yillik",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        db.session.add(period)
        db.session.commit()

        evaluation = PerformanceEvaluation(
            period_id=period.id,
            employee_id=employee_id,
            workflow_status=workflow_status,
        )
        db.session.add(evaluation)
        db.session.commit()

        db.session.add(
            EvaluationAssignment(
                period_id=period.id,
                employee_id=employee_id,
                evaluator_id=evaluator_id,
                manager_level=1,
            )
        )
        db.session.commit()
        return evaluation.id


# ---------------------------------------------------------------------------
# B: performance_evaluation_history.html route -- known + unmapped
# workflow_status, and the double-filtered from_status_label/to_status_label.
# ---------------------------------------------------------------------------


def test_evaluation_history_page_shows_turkish_for_known_workflow_status(app, client) -> None:
    evaluator_id = _create_user(app, sicil_no="h1e_perf_a_evaluator")
    employee_id = _create_user(app, sicil_no="h1e_perf_a_employee")
    evaluation_id = _build_evaluation_with_assignment(
        app, evaluator_id=evaluator_id, employee_id=employee_id, workflow_status="taslak_1_amir"
    )
    _login(client, "h1e_perf_a_evaluator")

    body = client.get(f"/performance/evaluations/{evaluation_id}/history").get_data(as_text=True)
    assert "2. amir taslak aşamasında" in body
    assert "taslak_1_amir" not in body


def test_evaluation_history_page_never_leaks_an_unmapped_workflow_status(app, client) -> None:
    evaluator_id = _create_user(app, sicil_no="h1e_perf_b_evaluator")
    employee_id = _create_user(app, sicil_no="h1e_perf_b_employee")
    evaluation_id = _build_evaluation_with_assignment(
        app, evaluator_id=evaluator_id, employee_id=employee_id, workflow_status="future_workflow_state_v9"
    )
    _login(client, "h1e_perf_b_evaluator")

    body = client.get(f"/performance/evaluations/{evaluation_id}/history").get_data(as_text=True)
    assert "future_workflow_state_v9" not in body
    assert "Süreç Durumu" in body


def test_evaluation_history_row_labels_show_turkish_and_never_leak_raw(app, client) -> None:
    from app.extensions import db
    from app.models import PerformanceEvaluationHistory

    evaluator_id = _create_user(app, sicil_no="h1e_perf_c_evaluator")
    employee_id = _create_user(app, sicil_no="h1e_perf_c_employee")
    evaluation_id = _build_evaluation_with_assignment(
        app, evaluator_id=evaluator_id, employee_id=employee_id, workflow_status="taslak_1_amir"
    )
    with app.app_context():
        db.session.add(
            PerformanceEvaluationHistory(
                evaluation_id=evaluation_id,
                action_type="SAVED_BY_LEVEL_1",
                from_status="future_from_status_v9",
                to_status="taslak_1_amir",
            )
        )
        db.session.commit()

    _login(client, "h1e_perf_c_evaluator")
    body = client.get(f"/performance/evaluations/{evaluation_id}/history").get_data(as_text=True)

    assert "1. amir taslağı kaydetti" in body
    assert "future_from_status_v9" not in body
    assert "2. amir taslak aşamasında" in body


# ---------------------------------------------------------------------------
# Contract: stored raw values are completely unchanged.
# ---------------------------------------------------------------------------


def test_stored_workflow_status_is_unchanged_by_rendering(app, client) -> None:
    evaluator_id = _create_user(app, sicil_no="h1e_perf_d_evaluator")
    employee_id = _create_user(app, sicil_no="h1e_perf_d_employee")
    evaluation_id = _build_evaluation_with_assignment(
        app, evaluator_id=evaluator_id, employee_id=employee_id, workflow_status="taslak_1_amir"
    )
    _login(client, "h1e_perf_d_evaluator")
    client.get(f"/performance/evaluations/{evaluation_id}/history")

    from app.extensions import db
    from app.models import PerformanceEvaluation

    with app.app_context():
        row = db.session.get(PerformanceEvaluation, evaluation_id)
        assert row is not None
        assert row.workflow_status == "taslak_1_amir"


# ---------------------------------------------------------------------------
# Authorization is unchanged.
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    response = client.get("/performance/evaluations/1/history", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in (response.headers.get("Location") or "")
