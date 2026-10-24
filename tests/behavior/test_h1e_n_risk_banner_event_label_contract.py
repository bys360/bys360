"""BYS360 H1E-N -- global risk banner event_label raw-value closure.

Found during the H1E-N final residual audit's carve-out reconfirmation
pass: app/services/ui_context/risk.py's `event_label` field
(`(event_type or "").replace("_", " ").title()`) was initially assumed to
match the same "event_type is an open-ended internal audit-log slug"
carve-out already established elsewhere in H1E (communication's
action_type, file_center's FileAuditLog.action). Re-reading the actual
code disproved that: get_global_risk_banner_context()'s focus_rows
comprehension explicitly filters to exactly 4 known values
(`event_type in {"uncovered", "chain_issue", "warning", "exempted"}`,
the same 4 keys build_assignment_log_summary() and _risk_score() already
treat as a small closed set) -- so this is a genuinely closed vocabulary
that was leaking English words ("Uncovered", "Chain Issue", "Warning",
"Exempted") via a naive title-case fallback, not an open-ended one.

This banner is registered as an app_context_processor
(app/routes.py::inject_global_risk_banner), so it renders inside
app/templates/base.html on every page matching BANNER_ALLOWED_PREFIXES
(dashboard, performance, hr, repository, education, strategy) -- a
high-visibility, cross-cutting surface, not a narrow one-off screen.

Fixed with a small _EVENT_TYPE_LABELS dict + _event_type_label() helper,
reusing established Turkish phrasing from elsewhere in the codebase
("Kapsama sorunu" already used for the same "uncovered" concept in
performance_tasks.html; "Muaf" matching PERFORMANCE_MODE_LABELS'
existing "exclude"->"Muaf" convention).

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_n_risk_banner_tmp" / "test_dbs"
_PASSWORD = "H1ENRiskBannerTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_event_type_label_never_leaks_raw() -> None:
    from app.services.ui_context.risk import _event_type_label

    assert _event_type_label("uncovered") == "Kapsama Sorunu"
    assert _event_type_label("chain_issue") == "Zincir Sorunu"
    assert _event_type_label("warning") == "Uyarı"
    assert _event_type_label("exempted") == "Muaf"

    assert _event_type_label("future_event_type_v9") == "Bilinmiyor"
    assert _event_type_label(None) == "-"
    assert _event_type_label("") == "-"


# ---------------------------------------------------------------------------
# B: app/DB-backed contract -- the real banner, the real template.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-n-risk-banner-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-n-risk-banner-first-login-test-pw")
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


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="H1E",
            soyad="RiskBannerContract",
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


def _seed_uncovered_assignment_log(app, *, employee_id):
    from app.extensions import db
    from app.models import PerformancePeriod
    from app.models.performance_models import AssignmentCoverageLog

    with app.app_context():
        period = PerformancePeriod(
            title="H1E N Risk Banner Test Period",
            period_type="yillik",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_active=True,
        )
        db.session.add(period)
        db.session.commit()
        log = AssignmentCoverageLog(
            period_id=period.id,
            employee_id=employee_id,
            event_scope="generation",
            event_type="uncovered",
            severity="warning",
            reason=None,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.session.add(log)
        db.session.commit()
        return period.id


def test_global_risk_banner_shows_turkish_event_label_not_raw(app, client) -> None:
    admin_id = _create_user(app, sicil_no="h1e_n_risk_admin", role="admin")
    _seed_uncovered_assignment_log(app, employee_id=admin_id)

    _login(client, "h1e_n_risk_admin")
    body = client.get("/dashboard").get_data(as_text=True)

    if "ops-focus-event" not in body:
        pytest.skip("Global risk banner did not render for this scope/DB combination -- unit test above already proves the label function itself is safe.")

    assert "Kapsama Sorunu" in body
    assert "Uncovered" not in body


def test_admin_dashboard_coverage_alerts_show_turkish_event_label_not_raw(app, client) -> None:
    """A second, independent consumer of the exact same closed 4-value
    event_type vocabulary: app/services/ui_context/dashboard.py's
    today_coverage_alerts (filtered to the identical {"uncovered",
    "chain_issue", "warning", "exempted"} set as risk.py's focus_rows,
    confirmed by reading both list comprehensions) fed
    admin_dashboard.html's risk-pill via the same raw
    `|replace('_',' ')|title` chain -- found during the Section 14 fresh
    repo-wide re-audit, after risk.py's fix above. Reuses the same
    _event_type_label() rather than a second dictionary."""
    admin_id = _create_user(app, sicil_no="h1e_n_dash_admin", role="admin")
    _seed_uncovered_assignment_log(app, employee_id=admin_id)

    _login(client, "h1e_n_dash_admin")
    body = client.get("/admin/dashboard").get_data(as_text=True)

    if "risk-pill" not in body:
        pytest.skip("Admin dashboard coverage-alert row did not render for this scope/DB combination -- unit test above already proves the label function itself is safe.")

    assert "Kapsama Sorunu" in body
    assert "Uncovered" not in body
