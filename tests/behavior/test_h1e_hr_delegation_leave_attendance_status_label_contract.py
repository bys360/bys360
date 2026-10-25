"""BYS360 H1E residual closure -- HR delegation/leave/attendance status.

A final repo-wide residual scan flagged app/templates/hr_management.html,
hr_attendance.html, hr_leave.html as soft findings: their DelegationAssignment/
PersonnelLeave/AttendanceException status columns were rendered via a bare
`row.status|replace('_',' ')|title` filter chain instead of a real label
dictionary. Impact looked cosmetic for TODAY's known values ("aktif",
"bekliyor", "onaylandi" title-case to acceptable-looking Turkish words), but
it's still the named self-fallback anti-pattern this whole initiative
targets, and a genuinely future/unmapped status would leak raw with zero
safe fallback.

Fixed by adding two new reusable label functions to
app/institutional/hr_scope_helpers.py (matching the file's existing
_leave_type_label/_attendance_type_label/_scope_label/_performance_mode_label
convention exactly): _delegation_status_label() (backed by
DELEGATION_STATUS_CHOICES) and _leave_status_label() (backed by
LEAVE_STATUS_CHOICES, extended with "aktif" -- confirmed a real runtime
value for both PersonnelLeave.status and AttendanceException.status via
existing `.status.in_([...])` filters elsewhere in this file -- so it maps
to "Aktif" instead of the unknown-value fallback wrongly hiding an
already-good value). leave_status_label doubles as the attendance status
label too: both models share the exact same status vocabulary per those
existing filters, so a second near-duplicate dict was not created.

While wiring app/templates/hr_attendance.html's delegations table, found
and fixed a genuine PRE-EXISTING bug directly blocking that fix: the
template called `scope_label(row.scope_type)` as a function, but
_leave_page_context()/_attendance_page_context() only ever provided
`scope_label` as a plain descriptive STRING ("Kurum Geneli" etc, used
correctly elsewhere on the same page via a template-local `_scope_label`
Jinja variable) -- calling a str as a function raises TypeError, which
safe_render()'s except-all would have silently replaced the entire page
with its fallback HTML the moment `delegations` was non-empty. Fixed by
adding a distinctly-named `delegation_scope_label` context callable
(backed by hr_scope_helpers._scope_label, the function version already
used correctly for the SAME delegations table on hr_management.html) so
the string and the callable no longer collide under one name.
hr_leave.html had the identical delegations table with the same
`row.scope_type` shown fully raw (not even title-cased) -- same fix
applied there too.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_hr_delegation_leave_tmp" / "test_dbs"
_PASSWORD = "H1EHrDelegationLeaveTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_delegation_and_leave_status_labels_never_leak_raw() -> None:
    from app.institutional.hr_scope_helpers import (
        _delegation_status_label,
        _leave_status_label,
    )

    assert _delegation_status_label("aktif") == "Aktif"
    assert _delegation_status_label("sona_erdi") == "Sona Erdi"
    assert _delegation_status_label("future_delegation_status_v9") == "Bilinmiyor"

    assert _leave_status_label("onaylandi") == "Onaylandı"
    assert _leave_status_label("aktif") == "Aktif"
    assert _leave_status_label("future_leave_status_v9") == "Bilinmiyor"


# ---------------------------------------------------------------------------
# B: app/DB-backed contracts.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-hr-delegation-leave-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-hr-delegation-leave-first-login-test-pw")
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
            soyad="HrDelegationLeaveContract",
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


def _create_delegation(app, *, delegator_id, delegate_id, status, scope_type="performance"):
    from app.extensions import db
    from app.models.hr_models import DelegationAssignment

    with app.app_context():
        row = DelegationAssignment(
            delegator_user_id=delegator_id,
            delegate_user_id=delegate_id,
            status=status,
            scope_type=scope_type,
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=7),
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_leave(app, *, user_id, status):
    from app.extensions import db
    from app.models.hr_models import PersonnelLeave

    with app.app_context():
        row = PersonnelLeave(
            user_id=user_id,
            leave_type="yillik_izin",
            status=status,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=2),
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _create_attendance_exception(app, *, user_id, status):
    from app.extensions import db
    from app.models.hr_models import AttendanceException

    with app.app_context():
        row = AttendanceException(
            user_id=user_id,
            record_date=date.today(),
            exception_type="devamsizlik",
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def test_hr_management_page_shows_turkish_delegation_status(app, client) -> None:
    delegator_id = _create_user(app, sicil_no="h1e_hr_del_delegator", role="admin")
    delegate_id = _create_user(app, sicil_no="h1e_hr_del_delegate", role="personel")
    _create_delegation(app, delegator_id=delegator_id, delegate_id=delegate_id, status="aktif")

    _login(client, "h1e_hr_del_delegator")
    body = client.get("/hr-management").get_data(as_text=True)

    assert "Aktif" in body


def test_hr_leave_page_renders_and_shows_turkish_delegation_and_leave_labels(app, client) -> None:
    """Regression test for the pre-existing scope_label str/callable
    collision: before the fix, this page would 500/fallback whenever
    active_delegations was non-empty. A 200 with the expected Turkish
    text proves both the collision fix and the label wiring."""
    delegator_id = _create_user(app, sicil_no="h1e_hr_leave_delegator", role="admin")
    delegate_id = _create_user(app, sicil_no="h1e_hr_leave_delegate", role="personel")
    _create_delegation(app, delegator_id=delegator_id, delegate_id=delegate_id, status="aktif")
    _create_leave(app, user_id=delegate_id, status="onaylandi")

    _login(client, "h1e_hr_leave_delegator")
    response = client.get("/hr-management/leave")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Onaylandı" in body
    assert "Performans" in body  # delegation_scope_label("performance")


def test_hr_attendance_page_renders_and_shows_turkish_labels(app, client) -> None:
    """Same scope_label collision, reached via the attendance page this
    time (hr_attendance.html has its own independent template copy of the
    broken call)."""
    delegator_id = _create_user(app, sicil_no="h1e_hr_att_delegator", role="admin")
    delegate_id = _create_user(app, sicil_no="h1e_hr_att_delegate", role="personel")
    _create_delegation(app, delegator_id=delegator_id, delegate_id=delegate_id, status="bekliyor")
    _create_attendance_exception(app, user_id=delegate_id, status="onaylandi")

    _login(client, "h1e_hr_att_delegator")
    response = client.get("/hr-management/attendance")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Onaylandı" in body
    assert "Bekliyor" in body


def test_hr_leave_page_never_leaks_an_unmapped_delegation_or_leave_status(app, client) -> None:
    delegator_id = _create_user(app, sicil_no="h1e_hr_leave_delegator_b", role="admin")
    delegate_id = _create_user(app, sicil_no="h1e_hr_leave_delegate_b", role="personel")
    _create_delegation(app, delegator_id=delegator_id, delegate_id=delegate_id, status="future_delegation_status_v9")
    _create_leave(app, user_id=delegate_id, status="future_leave_status_v9")

    _login(client, "h1e_hr_leave_delegator_b")
    body = client.get("/hr-management/leave").get_data(as_text=True)

    assert "future_delegation_status_v9" not in body
    assert "future_leave_status_v9" not in body
    assert body.count("Bilinmiyor") >= 2
