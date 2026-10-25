"""BYS360 H1E residual closure -- HR self-service request domain.

A final repo-wide residual scan (post H1E-A..G) found the request-review
detail panel was left behind on two pages that already had a correct,
existing label-mapping helper for the SAME data on the SAME page:

  - app/templates/hr_personnel_request_review.html's list rows already
    render `row.request_type_label` / `row.priority_label` (computed via
    _request_type_label()/_request_priority_label() in
    app/institutional/hr_personnel_operations_routes.py's
    _request_review_payload()), but the "Talep kararı" detail panel for
    the SELECTED request rendered the raw `selected_request.request_type`
    / `.priority` through a bare `|replace('_',' ')|title` filter chain
    instead -- so e.g. `belge_talebi` showed as "Belge Talebi" only by
    accident (title-casing happens to match this one dictionary entry)
    while a future/unmapped type would show its raw snake_case verbatim,
    and `high`/`critical` priorities would show "High"/"Critical"
    (English) instead of "Yüksek"/"Kritik".
  - app/templates/hr_self_service_requests.html's own "Seçili talebin
    akışı" detail panel had the identical defect for `.priority`.

Fixed by adding `selected_request_type_label` / `selected_request_priority
_label` to both payload builders (_request_review_payload(),
_self_service_request_payload()), reusing the exact same
_request_type_label()/_request_priority_label() functions their sibling
list rows already use -- no new dictionary, no duplicated logic.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_hr_residual_tmp" / "test_dbs"
_PASSWORD = "H1EHrResidualTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_request_type_and_priority_labels_never_leak_raw() -> None:
    from app.institutional.hr_personnel_operations_routes import (
        _request_priority_label,
        _request_type_label,
    )

    assert _request_type_label("belge_talebi") == "Belge Talebi"
    assert _request_priority_label("critical") == "Kritik"

    assert _request_type_label("future_request_type_v9") == "Bilinmiyor"
    assert _request_priority_label("future_priority_v9") == "Bilinmiyor"

    assert _request_type_label(None) == "-"
    assert _request_priority_label(None) == "-"


# ---------------------------------------------------------------------------
# B: app/DB-backed contracts.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-hr-residual-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-hr-residual-first-login-test-pw")
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
            soyad="HrResidualContract",
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


def _create_self_service_request(app, *, user_id, request_type, priority):
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=user_id,
            request_type=request_type,
            title="H1E residual test request",
            description="H1E residual test request description",
            priority=priority,
            status="submitted",
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def test_self_service_requests_page_shows_turkish_type_and_priority(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_res_employee", role="personel")
    request_id = _create_self_service_request(app, user_id=employee_id, request_type="belge_talebi", priority="critical")

    _login(client, "h1e_hr_res_employee")
    body = client.get(f"/hr-management/self-service/requests?request_id={request_id}").get_data(as_text=True)

    assert "Belge Talebi" in body
    assert "Kritik" in body


def test_self_service_requests_page_never_leaks_an_unmapped_type_or_priority(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_res_employee_b", role="personel")
    request_id = _create_self_service_request(app, user_id=employee_id, request_type="future_request_type_v9", priority="future_priority_v9")

    _login(client, "h1e_hr_res_employee_b")
    body = client.get(f"/hr-management/self-service/requests?request_id={request_id}").get_data(as_text=True)

    assert "future_request_type_v9" not in body
    assert "future_priority_v9" not in body
    assert body.count("Bilinmiyor") >= 2


def test_stored_request_type_and_priority_are_unchanged_by_rendering(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_res_employee_c", role="personel")
    request_id = _create_self_service_request(app, user_id=employee_id, request_type="future_request_type_v9", priority="future_priority_v9")

    _login(client, "h1e_hr_res_employee_c")
    client.get(f"/hr-management/self-service/requests?request_id={request_id}")

    with app.app_context():
        from app.models.hr_models import PersonnelSelfServiceRequest

        row = PersonnelSelfServiceRequest.query.get(request_id)
        assert row.request_type == "future_request_type_v9"
        assert row.priority == "future_priority_v9"
