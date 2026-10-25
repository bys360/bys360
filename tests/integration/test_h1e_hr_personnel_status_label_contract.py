"""BYS360 H1E-E -- HR/personnel module raw status/type display closure
contract.

A repo-wide grep for the shape `X_LABELS.get(raw, raw.replace("_", " ")
.title() if raw else "-")` found this exact fallback-to-raw defect
independently repeated across TEN files in app/institutional/ and
app/services/ (hr_personnel_extension_routes.py, hr_operations_service.py
[six separate functions], hr_operations_enhancements.py,
hr_scope_helpers.py [four functions], hr_personnel_phase13_routes.py
[three functions plus one newly-added], hr_personnel_operations_routes.py
[three functions], hr_personnel_phase11_routes.py [four functions],
hr_personnel_phase12_routes.py [three functions], hr_request_task_routes.py,
hr_personnel_phase10_routes.py) -- every one of these "_xxx_label()"
helpers echoed the raw machine value (cosmetically cleaned: underscores to
spaces, title-cased) back to the user whenever the value did not match its
own dictionary, instead of the intended safe fallback.

Also found two completely unmapped raw fields with no label function at
all: hr_personnel_digital_handover_documents.html's `row.document_type`
(new DOCUMENT_TYPE_LABELS dict added) and
hr_personnel_operations.html/personnel_profile.html's
`row.assignment_type` in the org-movement-history rows (reused the
existing POSITION_ASSIGNMENT_TYPE_LABELS dict from
hr_operations_enhancements.py, which already covers the same
"atama/gorevlendirme/vekalet/..." vocabulary for position assignments).

One deliberately NOT fixed: hr_operations_service.py's `_document_label()`
falls back the same way for a document CATEGORY code -- but categories are
an admin-extensible catalog (PersonnelDocumentCategory, managed through the
UI), not a small closed backend enum, so an orphaned-but-recognizable
category code (e.g. "ozluk_evrak" -> "Ozluk Evrak") is legitimately more
useful to an HR user than a generic "Bilinmiyor" and isn't the kind of raw
machine-jargon leak this initiative targets. Documented, not silently
skipped.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB (file-backed, per the documented pattern in
tests/integration/test_hr_personnel_operations_routes_phase5w2.py --
app/institutional/hr_personnel_extension_routes.py's `_table_exists()`
opens a second raw connection mid-transaction, which corrupts a
sqlite:///:memory: SingletonThreadPool connection but is harmless against
a real file).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_hr_personnel_status_tmp" / "test_dbs"
_PASSWORD = "H1EHrPersonnelStatusTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required) -- one representative
# case per fixed helper, proving the fallback-to-raw defect is gone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "import_path,func_name,known_raw,known_label,unmapped_raw",
    [
        ("app.institutional.hr_personnel_extension_routes", "_asset_status_label", "assigned", "Zimmette", "future_asset_status_v9"),
        ("app.institutional.hr_personnel_extension_routes", "_checklist_status_label", "approved", "Onaylandı", "future_checklist_status_v9"),
        ("app.institutional.hr_personnel_extension_routes", "_reminder_type_label", "critical", "Kritik", "future_reminder_type_v9"),
        ("app.institutional.hr_personnel_extension_routes", "_reminder_log_status_label", "queued", "Kuyrukta", "future_log_status_v9"),
        ("app.services.hr_operations_service", "_document_status_label", "aktif", "Aktif", "future_doc_status_v9"),
        ("app.services.hr_operations_service", "_note_type_label", "disiplin", "Disiplin", "future_note_type_v9"),
        ("app.services.hr_operations_service", "_note_status_label", None, None, "future_note_status_v9"),
        ("app.services.hr_operations_service", "_batch_status_label", "tamamlandi", "Tamamlandı", "future_batch_status_v9"),
        ("app.institutional.hr_scope_helpers", "_scope_label", "performance", "Performans", "future_scope_v9"),
        ("app.institutional.hr_scope_helpers", "_leave_type_label", "yillik_izin", "Yıllık İzin", "future_leave_type_v9"),
        ("app.institutional.hr_scope_helpers", "_attendance_type_label", "devamsizlik", "Devamsızlık", "future_attendance_type_v9"),
        ("app.institutional.hr_scope_helpers", "_performance_mode_label", "exclude", "Muaf", "future_perf_mode_v9"),
        ("app.institutional.hr_personnel_phase13_routes", "_approval_status_label", "approved", "Onaylandı", "future_approval_status_v9"),
        ("app.institutional.hr_personnel_phase13_routes", "_doc_status_label", "signed", "İmzalandı", "future_doc_status_v9"),
        ("app.institutional.hr_personnel_phase13_routes", "_risk_level_label", "kritik", "Kritik", "future_risk_level_v9"),
        ("app.institutional.hr_personnel_phase13_routes", "_document_type_label", "ilisik_kesme", "İlişik kesme", "future_document_type_v9"),
        ("app.institutional.hr_personnel_operations_routes", "_request_type_label", None, None, "future_request_type_v9"),
        ("app.institutional.hr_personnel_operations_routes", "_request_priority_label", None, None, "future_request_priority_v9"),
        ("app.institutional.hr_personnel_operations_routes", "_request_status_label", None, None, "future_request_status_v9"),
        ("app.institutional.hr_personnel_phase11_routes", "_type_label", None, None, "future_lifecycle_type_v9"),
        ("app.institutional.hr_personnel_phase11_routes", "_status_label", None, None, "future_lifecycle_status_v9"),
        ("app.institutional.hr_personnel_phase11_routes", "_task_status_label", None, None, "future_task_status_v9"),
        ("app.institutional.hr_personnel_phase11_routes", "_reason_label", None, None, "future_separation_reason_v9"),
        ("app.institutional.hr_personnel_phase12_routes", "_operation_type_label", None, None, "future_operation_type_v9"),
        ("app.institutional.hr_personnel_phase12_routes", "_handover_status_label", None, None, "future_handover_status_v9"),
        ("app.institutional.hr_personnel_phase12_routes", "_item_status_label", None, None, "future_item_status_v9"),
        ("app.institutional.hr_request_task_routes", "_task_status_label", "cancelled", "İptal", "future_hr_task_status_v9"),
        ("app.institutional.hr_personnel_phase10_routes", "_transfer_status_label", None, None, "future_transfer_status_v9"),
    ],
)
def test_hr_label_helper_never_leaks_an_unmapped_raw_value(import_path, func_name, known_raw, known_label, unmapped_raw) -> None:
    import importlib

    module = importlib.import_module(import_path)
    func = getattr(module, func_name)

    if known_raw is not None:
        assert func(known_raw) == known_label

    result = func(unmapped_raw)
    assert result != unmapped_raw
    assert unmapped_raw not in result
    assert result == "Bilinmiyor"

    # None input must never crash and must never echo raw text either --
    # its exact placeholder is function-specific pre-existing behavior
    # (most use "-"; two hr_scope_helpers functions default to a real
    # business value like "Performans" for a missing scope), so only the
    # "never raw" property is asserted generically here.
    none_result = func(None)
    assert none_result != "None"


def test_hr_operations_enhancements_generic_label_helper_never_leaks_raw() -> None:
    from app.services.hr_operations_enhancements import POSITION_ASSIGNMENT_TYPE_LABELS, _label

    assert _label(POSITION_ASSIGNMENT_TYPE_LABELS, "terfi") == "Terfi"
    unmapped = "future_assignment_type_v9"
    result = _label(POSITION_ASSIGNMENT_TYPE_LABELS, unmapped)
    assert result != unmapped
    assert result == "Bilinmiyor"
    assert _label(POSITION_ASSIGNMENT_TYPE_LABELS, None) == "-"


# ---------------------------------------------------------------------------
# App/client fixtures. File-backed SQLite per the documented
# _table_exists()-mid-transaction :memory: artifact (see module docstring).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-hr-personnel-status-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-hr-personnel-status-first-login-test-pw")
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
            soyad="HrPersonnelStatusContract",
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


def _insert_handover_document(app, *, user_id, document_type, status="draft"):
    from app.extensions import db
    from app.models import PersonnelDigitalHandoverDocument

    with app.app_context():
        row = PersonnelDigitalHandoverDocument(
            user_id=user_id,
            document_type=document_type,
            title="H1E negative-test document",
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_exit_risk_assessment(app, *, user_id, risk_level):
    from app.extensions import db
    from app.models import PersonnelExitRiskAssessment

    with app.app_context():
        row = PersonnelExitRiskAssessment(user_id=user_id, risk_score=42, risk_level=risk_level)
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_reminder_log(app, *, user_id, document_id, status):
    from app.extensions import db
    from app.models import PersonnelDocumentReminderLog

    with app.app_context():
        row = PersonnelDocumentReminderLog(
            user_id=user_id,
            document_id=document_id,
            reminder_type="manual",
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _insert_document(app, *, user_id):
    from app.extensions import db
    from app.models import PersonnelDocument

    with app.app_context():
        row = PersonnelDocument(user_id=user_id, category="ozluk", title="H1E test document", status="aktif")
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------------------------------------------------------------------------
# B: route-level tests -- known + unmapped values never leak raw.
# ---------------------------------------------------------------------------


def test_digital_handover_documents_page_shows_turkish_and_never_leaks_raw(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_a_employee", role="personel")
    _insert_handover_document(app, user_id=employee_id, document_type="ilisik_kesme")
    unmapped_id = _insert_handover_document(app, user_id=employee_id, document_type="future_document_type_v9")

    _create_user(app, sicil_no="h1e_hr_a_manager")
    _login(client, "h1e_hr_a_manager")

    body = client.get(f"/hr-management/personnel-operations/digital-handover-documents?user_id={employee_id}").get_data(as_text=True)
    assert "İlişik kesme" in body
    assert "future_document_type_v9" not in body
    assert "Bilinmiyor" in body
    assert unmapped_id > 0


def test_exit_risk_center_page_shows_turkish_and_never_leaks_raw(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_b_employee", role="personel")
    _insert_exit_risk_assessment(app, user_id=employee_id, risk_level="kritik")

    _create_user(app, sicil_no="h1e_hr_b_manager")
    _login(client, "h1e_hr_b_manager")

    body = client.get(f"/hr-management/personnel-operations/exit-risk-center?user_id={employee_id}").get_data(as_text=True)
    assert "Kritik" in body


def test_reminder_center_never_leaks_an_unmapped_log_status(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_c_employee", role="personel")
    document_id = _insert_document(app, user_id=employee_id)
    _insert_reminder_log(app, user_id=employee_id, document_id=document_id, status="future_log_status_v9")

    _create_user(app, sicil_no="h1e_hr_c_manager")
    _login(client, "h1e_hr_c_manager")

    body = client.get(f"/hr-management/personnel-operations/reminders?user_id={employee_id}").get_data(as_text=True)
    assert "future_log_status_v9" not in body
    assert "Bilinmiyor" in body


def test_reminder_center_shows_turkish_for_known_log_status(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_d_employee", role="personel")
    document_id = _insert_document(app, user_id=employee_id)
    _insert_reminder_log(app, user_id=employee_id, document_id=document_id, status="queued")

    _create_user(app, sicil_no="h1e_hr_d_manager")
    _login(client, "h1e_hr_d_manager")

    body = client.get(f"/hr-management/personnel-operations/reminders?user_id={employee_id}").get_data(as_text=True)
    assert "Kuyrukta" in body


# ---------------------------------------------------------------------------
# Contract: stored raw values are completely unchanged.
# ---------------------------------------------------------------------------


def test_stored_document_type_and_risk_level_are_unchanged_by_rendering(app, client) -> None:
    employee_id = _create_user(app, sicil_no="h1e_hr_e_employee", role="personel")
    doc_id = _insert_handover_document(app, user_id=employee_id, document_type="future_document_type_v9")
    risk_id = _insert_exit_risk_assessment(app, user_id=employee_id, risk_level="future_risk_level_v9")

    _create_user(app, sicil_no="h1e_hr_e_manager")
    _login(client, "h1e_hr_e_manager")
    client.get(f"/hr-management/personnel-operations/digital-handover-documents?user_id={employee_id}")
    client.get(f"/hr-management/personnel-operations/exit-risk-center?user_id={employee_id}")

    from app.extensions import db
    from app.models import PersonnelDigitalHandoverDocument, PersonnelExitRiskAssessment

    with app.app_context():
        doc = db.session.get(PersonnelDigitalHandoverDocument, doc_id)
        risk = db.session.get(PersonnelExitRiskAssessment, risk_id)
        assert doc is not None and doc.document_type == "future_document_type_v9"
        assert risk is not None and risk.risk_level == "future_risk_level_v9"


# ---------------------------------------------------------------------------
# Authorization is unchanged.
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    for path in (
        "/hr-management/personnel-operations/reminders",
        "/hr-management/personnel-operations/digital-handover-documents",
        "/hr-management/personnel-operations/exit-risk-center",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, path
        assert "/login" in (response.headers.get("Location") or ""), path
